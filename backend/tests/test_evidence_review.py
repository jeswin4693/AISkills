"""What the independent review of slice V found, each as a test that failed before the fix. All offline, no model."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from conftest import commit_all, git
from test_evidence import APP, NOW, only, rebuild, snap
from test_library import NAME, write_skill

from skillforge import cli
from skillforge.evidence import EVIDENCE_FILE, EvidenceError, collect, evidence_bytes, read_evidence, recheck, resolve_ref
from skillforge.evidence import model as evidence_model
from skillforge.graph.model import Edge
from skillforge.library import Library, LibraryError, import_skill, install_skill
from skillforge.library.evidence import cite, recheck_version, refresh
from skillforge.validate import validate_files


def edit(root: Path, rel: str, old: str, new: str) -> None:
    text = (root / rel).read_text(encoding="utf-8")
    assert old in text, old
    (root / rel).write_text(text.replace(old, new), encoding="utf-8")


def status_of(root, ev, ref_id):
    return only(recheck(ev, rebuild(root)), ref_id)


# ---- C1: a changed decorator is a change ------------------------------------------------------------

DECORATED = {
    "app.py": (
        "import functools\n\n"
        "def login_required(f):\n    return f\n\n"
        "@login_required\n"
        "def secret(user):\n    return user.name\n\n"
        "@functools.lru_cache(\n    maxsize=10,\n)\n"
        "def cached(x):\n    return x\n"
    ),
}


def test_removing_a_decorator_is_a_change(repo):
    root = repo(DECORATED)
    ev = snap(rebuild(root), "app.py::secret")
    edit(root, "app.py", "@login_required\ndef secret", "def secret")
    f = status_of(root, ev, "app.py::secret")
    assert f.status == "changed" and "decorator" in " ".join(f.details)


def test_swapping_a_decorator_is_at_least_an_edit(repo):
    root = repo(DECORATED)
    ev = snap(rebuild(root), "app.py::secret")
    edit(root, "app.py", "@login_required\ndef secret", "@functools.lru_cache\ndef secret")
    assert status_of(root, ev, "app.py::secret").status in ("changed", "edited")


def test_a_changed_argument_of_a_multi_line_decorator_is_seen(repo):
    root = repo(DECORATED)
    ev = snap(rebuild(root), "app.py::cached")
    edit(root, "app.py", "maxsize=10,", "maxsize=99,")
    assert status_of(root, ev, "app.py::cached").status == "edited"


def test_a_typescript_decorator_that_was_removed_is_seen(repo):
    src = "class Svc {\n  @Component()\n  run(x: number): number {\n    return x + 1;\n  }\n}\nexport { Svc };\n"
    root = repo({"a.ts": src})
    ev = snap(rebuild(root), "a.ts::Svc.run")
    edit(root, "a.ts", "  @Component()\n", "")
    assert status_of(root, ev, "a.ts::Svc.run").status in ("changed", "edited")


# ---- C2: a class is compared by what the graph knows of it -------------------------------------------

CLASSY = {"m.py": "class Svc:\n    def a(self):\n        return 1\n\n    def b(self):\n        return 2\n"}


def test_new_base_classes_and_methods_of_a_class_are_changes(repo):
    root = repo(CLASSY)
    ev = snap(rebuild(root), "m.py::Svc")
    assert ev.refs[0].bases == [] and ev.refs[0].members == ["Svc.a", "Svc.b"]
    edit(root, "m.py", "class Svc:", "class Svc(dict):")
    f = status_of(root, ev, "m.py::Svc")
    assert f.status == "changed" and "base" in " ".join(f.details)
    edit(root, "m.py", "class Svc(dict):", "class Svc:")
    edit(root, "m.py", "    def b(self):\n        return 2\n", "    def b(self):\n        return 2\n\n    def extra(self):\n        return 3\n")
    f = status_of(root, ev, "m.py::Svc")
    assert f.status == "changed" and "Svc.extra" in " ".join(f.details)


def test_an_edit_to_a_place_with_no_structure_hash_does_not_claim_the_structure_is_the_same(repo):
    root = repo(CLASSY)
    ev = snap(rebuild(root), "m.py::Svc")
    edit(root, "m.py", "return 1", "return 100")
    f = status_of(root, ev, "m.py::Svc")
    assert f.status == "edited" and "structure is the same" not in " ".join(f.details) and "text differs" in " ".join(f.details)


# ---- C3: a file whose text was rewritten is not "holds" ----------------------------------------------


def test_a_file_whose_bodies_were_all_rewritten_is_edited_not_holds(repo):
    root = repo({"app.py": "def a():\n    return 1\n\ndef b():\n    print(1)\n"})
    ev = snap(rebuild(root), "app.py")
    edit(root, "app.py", "return 1", "return 100")
    edit(root, "app.py", "print(1)", "delete(1)")
    f = status_of(root, ev, "app.py")
    assert f.status == "edited" and "file" in " ".join(f.details)


def test_a_file_that_only_changed_line_endings_still_holds(repo):
    root = repo({"app.py": "def a():\n    return 1\n"})
    ev = snap(rebuild(root), "app.py")
    (root / "app.py").write_bytes(b"def a():\r\n    return 1\r\n")
    assert status_of(root, ev, "app.py").status == "holds"


# ---- C4: a cut list is still compared, by a digest of the whole -------------------------------------

MANY = "from svc import clean\n\n" + "".join(f"def f{i}():\n    clean(1)\n\n" for i in range(45))


def test_swapping_one_caller_in_a_cut_list_is_a_change(repo):
    root = repo({**APP, "many.py": MANY})
    ev = snap(rebuild(root), "svc.py::clean")
    assert ev.refs[0].truncated("callers")
    edit(root, "many.py", "def f44():\n    clean(1)\n", "def f44():\n    pass\n\ndef g():\n    clean(2)\n")
    f = status_of(root, ev, "svc.py::clean")
    assert f.status == "changed" and "cut" in " ".join(f.details)


def test_an_unchanged_cut_list_holds(repo):
    root = repo({**APP, "many.py": MANY})
    ev = snap(rebuild(root), "svc.py::clean")
    assert status_of(root, ev, "svc.py::clean").status == "holds"


# ---- I1: nothing from a hostile file or repository reaches the terminal raw --------------------------

ESC = "\x1b]0;PWNED\x07\x1b[31mred"


def hostile(**over) -> bytes:
    doc = {"version": 1, "repo": "r", "commit": None, "focus": None, "taken_at": "2026-11-23T09:00:00+00:00",
           "refs": [{"id": "a.py", "kind": "file", "file": "a.py"}], **over}
    return json.dumps(doc).encode()


def test_an_unknown_key_with_escape_characters_is_shown_escaped(tmp_path):
    for raw in (hostile(**{ESC: 1}), hostile(refs=[{"id": "a.py", "kind": "file", "file": "a.py", ESC: 1}])):
        with pytest.raises(EvidenceError) as err:
            read_evidence({EVIDENCE_FILE: raw})
        assert "\x1b" not in str(err.value) and "\x07" not in str(err.value) and "\\x1b" in str(err.value)
        row = [c for c in validate_files({"SKILL.md": b"x", EVIDENCE_FILE: raw}) if "evidence" in c.name.lower()][0]
        assert "\x1b" not in row.detail


@pytest.mark.parametrize("ch", ["\ufeff", "\u061c", "\u00ad", "\ufe0f", "\u180e", "\u206a"])
def test_more_invisible_characters_are_refused(ch):
    with pytest.raises(EvidenceError):
        read_evidence({EVIDENCE_FILE: hostile(refs=[{"id": f"a{ch}.py", "kind": "file", "file": "a.py"}])})


def test_names_taken_from_the_repository_are_shown_escaped(repo):
    root = repo(APP)
    g = rebuild(root)
    ev = snap(g, "svc.py::parse")
    g2 = rebuild(root)
    g2.edges.append(Edge("evil\x1b[31m.py::f", "svc.py::parse", "calls", "resolved"))
    g2.__post_init__()
    f = only(recheck(ev, g2), "svc.py::parse")
    shown = " ".join(f.details)
    assert "\x1b" not in shown and "\\x1b" in shown


# ---- I2: the same focus for everything recorded together ---------------------------------------------

FOCUSED = {
    "src/lib.py": "def f():\n    return 1\n\ndef g():\n    return f()\n",
    "tests/t.py": "from src.lib import f\n\ndef test_f():\n    f()\n",
}


def test_citing_with_a_different_focus_than_the_recorded_one_is_refused(tmp_path, repo):
    root = repo(FOCUSED)
    lib = Library(tmp_path / "library")
    assert not import_skill(write_skill(tmp_path / NAME), lib).refused
    cite(lib, NAME, rebuild(root), ["src/lib.py::f"], focus=None, now=NOW)
    with pytest.raises(LibraryError, match="focus"):
        cite(lib, NAME, rebuild(root), ["src/lib.py::g"], focus="src", now=NOW)


def test_the_command_line_cites_with_the_recorded_focus_and_the_recheck_agrees(tmp_path, repo, capsys):
    root = repo(FOCUSED)
    assert cli.main(["library", "import", str(write_skill(tmp_path / NAME, "Use `g`.\n"))]) == 0
    assert cli.main(["library", "cite", NAME, "--repo", str(root), "--focus", "src", "--ref", "src/lib.py::f"]) == 0
    assert cli.main(["library", "cite", NAME, "--repo", str(root), "--from-text"]) == 0  # no --focus: the recorded one is used
    capsys.readouterr()
    assert cli.main(["library", "recheck", NAME, "--repo", str(root)]) == 0
    out = capsys.readouterr().out
    assert "holds" in out and "CHANGED" not in out


def test_a_recheck_with_another_focus_says_so(tmp_path, repo):
    root = repo(FOCUSED)
    lib = Library(tmp_path / "library")
    assert not import_skill(write_skill(tmp_path / NAME), lib).refused
    cite(lib, NAME, rebuild(root), ["src/lib.py::f"], focus="src", now=NOW)
    g = rebuild(root)
    report = recheck_version(lib, NAME, g, focus=None)
    assert any("focus" in n for n in report.notes)
    assert not any("focus" in n for n in recheck_version(lib, NAME, g, focus="src").notes)


# ---- I3: a file that would be too big is never written as if it were fine ----------------------------


def test_cite_that_would_make_too_big_a_file_says_so(tmp_path, repo, monkeypatch):
    root = repo(APP)
    lib = Library(tmp_path / "library")
    assert not import_skill(write_skill(tmp_path / NAME), lib).refused
    monkeypatch.setattr(evidence_model, "MAX_FILE_BYTES", 600)
    with pytest.raises(LibraryError, match="too large"):
        cite(lib, NAME, rebuild(root), ["svc.py::parse", "api.py"], now=NOW)
    assert [v.tag for v in lib.versions(NAME)] == ["v1"]


def test_a_failed_check_names_the_reason(tmp_path, repo):
    root = repo(APP)
    lib = Library(tmp_path / "library")
    assert not import_skill(write_skill(tmp_path / NAME), lib).refused
    g = rebuild(root)
    g.files["we\u202eird.py"] = g.files["svc.py"]  # skipped by the model, so not recorded
    got = collect(g, ["we\u202eird.py"], now=NOW)
    assert got.skipped and not got.evidence.refs


def test_a_build_keeps_the_evidence_file_inside_the_reader_limit(tmp_path, repo, monkeypatch, capsys):
    from test_evidence_cli import build as run_build
    from test_skill_build import ANSWERS, FIRST

    root = repo(APP)
    report = tmp_path / "report.json"
    report.write_text(json.dumps({"suggestions": [{"title": "T", "skill_requirement": FIRST, "evidence_nodes": ["svc.py::parse", "api.py", "main.py"]}]}), encoding="utf-8")
    answers = tmp_path / "a.json"
    answers.write_text(json.dumps(ANSWERS), encoding="utf-8")
    monkeypatch.setattr(evidence_model, "MAX_FILE_BYTES", 2600)
    code, out, _ = run_build(capsys, monkeypatch, tmp_path, report, answers, "--repo", str(root))
    folder = next((tmp_path / "skills").iterdir())
    data = (folder / EVIDENCE_FILE).read_bytes()
    assert len(data) <= 2600 and read_evidence({EVIDENCE_FILE: data}) is not None
    assert "only the first" in out


# ---- I4: install leaves evidence in the library ------------------------------------------------------


def test_install_does_not_copy_evidence_into_a_skills_folder(tmp_path, repo):
    root = repo(APP)
    lib = Library(tmp_path / "library")
    assert not import_skill(write_skill(tmp_path / NAME), lib).refused
    cite(lib, NAME, rebuild(root), ["svc.py::parse"], now=NOW)
    r = install_skill(lib, NAME, None, tmp_path / "skills")
    assert not (r.path / EVIDENCE_FILE).exists() and (r.path / "SKILL.md").exists() and r.left_out == [EVIDENCE_FILE]


def test_install_says_where_the_evidence_stayed(tmp_path, repo, capsys):
    root = repo(APP)
    assert cli.main(["library", "import", str(write_skill(tmp_path / NAME))]) == 0
    assert cli.main(["library", "cite", NAME, "--repo", str(root), "--ref", "svc.py::parse"]) == 0
    capsys.readouterr()
    assert cli.main(["library", "install", NAME, "--to", str(tmp_path / "skills")]) == 0
    assert "stays in the library" in capsys.readouterr().out


# ---- I5: a name that matches several places is listed, never picked ---------------------------------


def test_a_name_in_source_and_in_a_test_is_ambiguous_for_an_explicit_reference(repo):
    g = rebuild(repo({"pkg/lib.py": "def setup():\n    pass\n", "tests/test_x.py": "def setup():\n    pass\n"}))
    r = resolve_ref(g, "setup")
    assert r.id is None and sorted(r.options) == ["pkg/lib.py::setup", "tests/test_x.py::setup"]


def test_a_file_name_that_matches_two_files_lists_them(repo):
    g = rebuild(repo({"pkg/lib.py": "x = 1\n", "other/lib.py": "y = 2\n"}))
    r = resolve_ref(g, "lib.py")
    assert r.id is None and sorted(r.options) == ["other/lib.py", "pkg/lib.py"]


# ---- I6: the text window follows the graph's idea of a line -----------------------------------------


@pytest.mark.parametrize("sep", ["\x0c", "\x0b", "\x1c", "\x85", "\u2028"])
def test_a_line_separator_the_graph_does_not_count_does_not_shift_the_hashed_window(repo, sep):
    body = "def f():\n    x = 1\n    return x + 5\n"
    text = "A = 1\n# a" + sep + "b\n" + body  # inside a comment: legal Python, and str.splitlines() would split the line there
    root = repo({"m.py": text})
    (root / "m.py").write_text(text, encoding="utf-8", newline="\n")
    ev = snap(rebuild(root), "m.py::f")
    edit(root, "m.py", "x + 5", "x + 6")  # the last line of the function
    assert status_of(root, ev, "m.py::f").status == "edited"


# ---- M1: a refresh that finds no code change makes no version ---------------------------------------


def test_refresh_after_committing_what_was_uncommitted_changes_nothing(tmp_path, repo):
    root = repo(APP)
    git(root, "init", "-q")
    commit_all(root, "first")
    (root / "extra.py").write_text("x = 1\n", encoding="utf-8")  # a dirty tree when the evidence is recorded
    lib = Library(tmp_path / "library")
    assert not import_skill(write_skill(tmp_path / NAME), lib).refused
    cite(lib, NAME, rebuild(root), ["svc.py::parse"], now=NOW)
    commit_all(root, "second")
    r = refresh(lib, NAME, rebuild(root), now=NOW)
    assert r.created is False and r.updated == []


# ---- M3: strictly typed, and a BOM is not an error --------------------------------------------------


@pytest.mark.parametrize("bad", [{"line": "5"}, {"line": True}, {"exported": "yes"}, {"line": 1.5}])
def test_wrongly_typed_values_are_refused(bad):
    with pytest.raises(EvidenceError):
        read_evidence({EVIDENCE_FILE: hostile(refs=[{"id": "a.py", "kind": "file", "file": "a.py", **bad}])})


def test_a_file_with_a_byte_order_mark_is_read():
    assert read_evidence({EVIDENCE_FILE: b"\xef\xbb\xbf" + hostile()}) is not None


# ---- M4: importing a folder that lacks the evidence says what was lost -------------------------------


def test_importing_a_version_without_evidence_after_one_with_it_says_so(tmp_path, repo, capsys):
    root = repo(APP)
    skill = write_skill(tmp_path / NAME)
    assert cli.main(["library", "import", str(skill)]) == 0
    assert cli.main(["library", "cite", NAME, "--repo", str(root), "--ref", "svc.py::parse"]) == 0
    write_skill(skill, "A different body.\n")  # the folder never had evidence.json
    capsys.readouterr()
    assert cli.main(["library", "import", str(skill)]) == 0
    assert "evidence.json" in capsys.readouterr().out
