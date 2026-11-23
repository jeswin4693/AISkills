"""Evidence: what a skill cites in a repository, the facts the graph had, and the recheck. All offline, no model.

A repository is a few small files in a temporary folder; "later" is the same folder edited and parsed again.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from conftest import commit_all, git

from skillforge.evidence import (
    EVIDENCE_FILE, MAX_REFS, Evidence, EvidenceError, Ref, collect, evidence_bytes, read_evidence, recheck, resolve_ref,
)
from skillforge.graph.build import build_graph
from skillforge.graph.model import Edge

NOW = datetime(2026, 11, 23, 9, 0, tzinfo=timezone.utc)

# a body long enough (30+ syntax nodes) that "the same structure somewhere else" means something
LONG = (
    "def tidy(rows):\n"
    "    out = []\n"
    "    for row in rows:\n"
    "        if row is None:\n"
    "            continue\n"
    "        value = str(row).strip().lower()\n"
    "        if value and value not in out:\n"
    "            out.append(value)\n"
    "    return sorted(out)\n"
)

APP = {
    "svc.py": "def parse(raw):\n    return clean(raw)\n\ndef clean(raw):\n    return raw.strip()\n\n" + LONG,
    "api.py": "from svc import parse\n\ndef handler(req):\n    return parse(req)\n\ndef other(req):\n    return parse(req)\n",
    "main.py": "from api import handler\n\ndef main():\n    handler(1)\n",
}


def rebuild(root: Path):
    return build_graph(root, use_cache=False, with_history=False)


def snap(g, *ids, focus=None):
    got = collect(g, list(ids), focus=focus, now=NOW)
    assert not got.skipped, got.skipped
    return got.evidence


def only(report, ref_id):
    found = [f for f in report.findings if f.ref == ref_id]
    assert len(found) == 1, [(f.ref, f.status) for f in report.findings]
    return found[0]


@pytest.fixture
def app(repo):
    root = repo(APP)
    return root, rebuild(root)


# ---- what is recorded --------------------------------------------------------------------------------


def test_a_function_is_recorded_with_the_facts_the_graph_computed(app):
    _, g = app
    ev = snap(g, "svc.py::parse")
    (ref,) = ev.refs
    assert (ref.id, ref.kind, ref.file, ref.symbol_kind) == ("svc.py::parse", "symbol", "svc.py", "function")
    assert (ref.line, ref.end_line) == (1, 2)
    assert ref.callers == ["api.py::handler", "api.py::other"] and ref.callers_total == 2
    assert ref.callees == ["svc.py::clean"] and ref.callees_total == 1
    assert ref.shape and ref.size > 0 and ref.text_hash and ref.measured is True and ref.exported is True


def test_a_file_is_recorded_with_its_symbols_and_the_files_around_it(app):
    _, g = app
    (ref,) = snap(g, "api.py").refs
    assert (ref.kind, ref.lang) == ("file", "python")
    assert ref.symbols == ["handler", "other"] and ref.imports == ["svc.py"] and ref.importers == ["main.py"]


def test_the_repository_and_the_time_are_recorded_and_no_path_is_kept(app):
    root, g = app
    ev = snap(g, "svc.py::parse", focus="src")
    assert ev.repo == root.name and ev.taken_at == NOW.isoformat(timespec="seconds") and ev.focus == "src"
    assert str(root) not in evidence_bytes(ev).decode()  # evidence travels with the skill: a person's folders stay home


def test_the_commit_is_recorded_when_the_repository_is_in_git(repo):
    root = repo(APP)
    git(root, "init", "-q")
    commit_all(root, "first")
    ev = snap(rebuild(root), "svc.py::parse")
    assert ev.commit and len(ev.commit) >= 7


def test_uncommitted_changes_are_recorded_because_the_commit_alone_would_mislead(repo):
    root = repo(APP)
    git(root, "init", "-q")
    commit_all(root, "first")
    clean = snap(rebuild(root), "svc.py::parse")
    assert clean.dirty is False and clean.refs[0].dirty is False
    (root / "svc.py").write_text((root / "svc.py").read_text(encoding="utf-8") + "\nNEW = 1\n", encoding="utf-8")
    dirty = snap(rebuild(root), "svc.py::parse")
    assert dirty.commit == clean.commit and dirty.dirty is True and dirty.refs[0].dirty is True


def test_outside_git_nothing_is_said_about_a_commit_or_a_dirty_tree(app):
    _, g = app
    ev = snap(g, "svc.py::parse")
    assert ev.commit is None and ev.dirty is False


def test_the_report_says_when_either_side_had_uncommitted_changes(repo):
    root = repo(APP)
    git(root, "init", "-q")
    commit_all(root, "first")
    (root / "extra.py").write_text("x = 1\n", encoding="utf-8")  # untracked: the graph reads it, so it counts
    ev = snap(rebuild(root), "svc.py::parse")
    assert ev.dirty is True
    report = recheck(ev, rebuild(root))
    assert report.recorded_dirty is True and report.current_dirty is True
    assert any("uncommitted" in n for n in report.notes)
    commit_all(root, "second")
    again = recheck(ev, rebuild(root))
    assert again.recorded_dirty is True and again.current_dirty is False


def test_a_name_only_guess_is_never_recorded_as_a_caller(app):
    _, g = app
    g.edges.append(Edge("main.py::main", "svc.py::parse", "calls", "guess"))
    g.__post_init__()  # forget the cached index
    (ref,) = snap(g, "svc.py::parse").refs
    assert "main.py::main" not in ref.callers and ref.callers_total == 2


def test_a_long_list_keeps_the_true_count(repo):
    files = dict(APP)
    files["many.py"] = "from svc import clean\n\n" + "".join(f"def f{i}():\n    clean(1)\n\n" for i in range(60))
    (ref,) = snap(rebuild(repo(files)), "svc.py::clean").refs
    assert ref.callers_total == 61 and len(ref.callers) == 40 and ref.truncated("callers") is True  # parse plus the 60 new functions


def test_what_cannot_be_found_is_reported_and_never_recorded(app):
    _, g = app
    got = collect(g, ["svc.py::parse", "svc.py::nothing", "gone.py"], now=NOW)
    assert [r.id for r in got.evidence.refs] == ["svc.py::parse"]
    assert [s[0] for s in got.skipped] == ["svc.py::nothing", "gone.py"]


def test_a_file_name_with_hidden_characters_is_skipped_not_recorded(app):
    _, g = app
    odd = "we\u202eird.py"  # a right-to-left override in a file name: it would reorder what a terminal shows
    g.files[odd] = g.files["svc.py"]
    got = collect(g, ["svc.py::parse", odd], now=NOW)
    assert [r.id for r in got.evidence.refs] == ["svc.py::parse"]
    assert len(got.skipped) == 1 and "hidden" in got.skipped[0][1] and "\u202e" not in got.skipped[0][0]  # shown escaped, never raw


def test_a_module_symbol_is_recorded_as_its_file(repo):
    g = rebuild(repo({**APP, "boot.py": "from svc import parse\n\nparse(1)\n"}))  # module-level code makes a module symbol
    assert "boot.py::<module>" in g.symbols
    (ref,) = snap(g, "boot.py::<module>").refs
    assert (ref.id, ref.kind) == ("boot.py", "file")


def test_resolving_a_reference_never_picks_between_two(repo):
    g = rebuild(repo({"a.py": "def run():\n    pass\n", "b.py": "def run():\n    pass\n"}))
    r = resolve_ref(g, "run")
    assert r.id is None and sorted(r.options) == ["a.py::run", "b.py::run"]
    assert resolve_ref(g, "a.py::run").id == "a.py::run"
    assert resolve_ref(g, "a.py").id == "a.py"
    assert resolve_ref(g, "nothing_here").id is None and resolve_ref(g, "nothing_here").options == []


# ---- the recheck: nothing changed --------------------------------------------------------------------


def test_nothing_changed_means_everything_holds(app):
    root, g = app
    ev = snap(g, "svc.py::parse", "api.py", "svc.py")
    report = recheck(ev, rebuild(root))
    assert [f.status for f in report.findings] == ["holds"] * 3 and report.ok is True


def test_a_line_that_only_moved_is_not_a_change(app):
    root, g = app
    ev = snap(g, "svc.py::parse")
    text = (root / "svc.py").read_text(encoding="utf-8")
    (root / "svc.py").write_text("# a new comment\n\n\n" + text, encoding="utf-8")
    assert only(recheck(ev, rebuild(root)), "svc.py::parse").status == "holds"


# ---- the recheck: what a person needs to hear --------------------------------------------------------


def test_a_new_caller_is_named(app):
    root, g = app
    ev = snap(g, "svc.py::parse")
    (root / "main.py").write_text("from api import handler\nfrom svc import parse\n\ndef main():\n    handler(1)\n    parse(2)\n", encoding="utf-8")
    f = only(recheck(ev, rebuild(root)), "svc.py::parse")
    assert f.status == "changed"
    text = " ".join(f.details)
    assert "3 resolved callers" in text and "was 2" in text and "main.py::main" in text


def test_a_caller_that_is_gone_is_named(app):
    root, g = app
    ev = snap(g, "svc.py::parse")
    (root / "api.py").write_text("from svc import parse\n\ndef handler(req):\n    return parse(req)\n", encoding="utf-8")
    f = only(recheck(ev, rebuild(root)), "svc.py::parse")
    assert f.status == "changed" and "api.py::other" in " ".join(f.details)


def test_a_changed_body_structure_is_a_change(app):
    root, g = app
    ev = snap(g, "svc.py::clean")
    text = (root / "svc.py").read_text(encoding="utf-8")
    (root / "svc.py").write_text(text.replace("return raw.strip()", "if raw is None:\n        return ''\n    return raw.strip().lower()"), encoding="utf-8")
    f = only(recheck(ev, rebuild(root)), "svc.py::clean")
    assert f.status == "changed" and "structure" in " ".join(f.details)


def test_a_changed_value_alone_is_only_edited(app):
    root, g = app
    ev = snap(g, "svc.py::clean")
    text = (root / "svc.py").read_text(encoding="utf-8")
    (root / "svc.py").write_text(text.replace("raw.strip()", "raw.rstrip()"), encoding="utf-8")
    f = only(recheck(ev, rebuild(root)), "svc.py::clean")
    assert f.status == "edited" and "text" in " ".join(f.details)


def test_a_new_callee_is_named(app):
    root, g = app
    ev = snap(g, "api.py::handler")
    (root / "api.py").write_text(
        "from svc import parse, clean\n\ndef handler(req):\n    clean(req)\n    return parse(req)\n\ndef other(req):\n    return parse(req)\n",
        encoding="utf-8",
    )
    f = only(recheck(ev, rebuild(root)), "api.py::handler")
    assert f.status == "changed" and "svc.py::clean" in " ".join(f.details)


def test_a_new_importer_and_a_new_symbol_change_a_file(app):
    root, g = app
    ev = snap(g, "svc.py")
    (root / "extra.py").write_text("import svc\n\ndef x():\n    return svc.parse(1)\n", encoding="utf-8")
    (root / "svc.py").write_text((root / "svc.py").read_text(encoding="utf-8") + "\ndef added():\n    return 1\n", encoding="utf-8")
    f = only(recheck(ev, rebuild(root)), "svc.py")
    text = " ".join(f.details)
    assert f.status == "changed" and "extra.py" in text and "added" in text


def test_a_removed_symbol_is_named(app):
    root, g = app
    ev = snap(g, "svc.py")
    text = (root / "svc.py").read_text(encoding="utf-8")
    (root / "svc.py").write_text(text.replace("def clean(raw):\n    return raw.strip()\n", ""), encoding="utf-8")
    f = only(recheck(ev, rebuild(root)), "svc.py")
    assert f.status == "changed" and "clean" in " ".join(f.details)


def test_a_deleted_function_is_missing(app):
    root, g = app
    ev = snap(g, "svc.py::clean")
    text = (root / "svc.py").read_text(encoding="utf-8")
    (root / "svc.py").write_text(text.replace("def clean(raw):\n    return raw.strip()\n", ""), encoding="utf-8")
    report = recheck(ev, rebuild(root))
    f = only(report, "svc.py::clean")
    assert f.status == "missing" and "still exists" in " ".join(f.details) and report.ok is False


def test_a_deleted_file_is_missing(app):
    root, g = app
    ev = snap(g, "main.py", "main.py::main")
    (root / "main.py").unlink()
    report = recheck(ev, rebuild(root))
    assert {f.ref: f.status for f in report.findings} == {"main.py": "missing", "main.py::main": "missing"}


def test_a_renamed_function_is_a_candidate_and_never_decided(app):
    root, g = app
    ev = snap(g, "svc.py::tidy")
    text = (root / "svc.py").read_text(encoding="utf-8")
    (root / "svc.py").write_text(text.replace("def tidy(", "def normalise("), encoding="utf-8")
    f = only(recheck(ev, rebuild(root)), "svc.py::tidy")
    assert f.status == "moved" and f.candidates == ["svc.py::normalise"]
    assert "same body structure" in " ".join(f.details) and "check" in " ".join(f.details).lower()


def test_a_function_moved_to_another_file_is_a_candidate(app):
    root, g = app
    ev = snap(g, "svc.py::tidy")
    text = (root / "svc.py").read_text(encoding="utf-8")
    (root / "svc.py").write_text(text.replace(LONG, ""), encoding="utf-8")
    (root / "util.py").write_text(LONG, encoding="utf-8")
    f = only(recheck(ev, rebuild(root)), "svc.py::tidy")
    assert f.status == "moved" and f.candidates == ["util.py::tidy"]


def test_two_look_alikes_are_listed_but_not_chosen(app):
    root, g = app
    ev = snap(g, "svc.py::tidy")
    text = (root / "svc.py").read_text(encoding="utf-8")
    (root / "svc.py").write_text(text.replace(LONG, ""), encoding="utf-8")
    (root / "one.py").write_text(LONG.replace("tidy", "first"), encoding="utf-8")
    (root / "two.py").write_text(LONG.replace("tidy", "second"), encoding="utf-8")
    f = only(recheck(ev, rebuild(root)), "svc.py::tidy")
    assert f.status == "missing" and sorted(f.candidates) == ["one.py::first", "two.py::second"]


def test_a_short_body_is_not_matched_by_structure(app):
    root, g = app
    ev = snap(g, "svc.py::clean")  # one line: many functions look like it
    text = (root / "svc.py").read_text(encoding="utf-8")
    (root / "svc.py").write_text(text.replace("def clean(", "def wash("), encoding="utf-8")
    f = only(recheck(ev, rebuild(root)), "svc.py::clean")
    assert f.status == "missing" and f.candidates == []


def test_a_file_moved_keeps_its_name_as_the_only_clue(app):
    root, g = app
    ev = snap(g, "main.py")
    (root / "main.py").rename(root / "cmd_main.py")
    f = only(recheck(ev, rebuild(root)), "main.py")
    assert f.status == "missing" and f.candidates == []
    (root / "pkg").mkdir()
    (root / "cmd_main.py").rename(root / "pkg" / "main.py")
    f = only(recheck(ev, rebuild(root)), "main.py")
    assert f.status == "moved" and f.candidates == ["pkg/main.py"]


def test_where_calls_are_not_resolved_nothing_is_claimed_about_callers(app):
    root, g = app
    ev = snap(g, "svc.py::parse")
    ev.refs[0].measured = False  # as if recorded for a language whose calls are not resolved
    (root / "main.py").write_text("from api import handler\nfrom svc import parse\n\ndef main():\n    handler(1)\n    parse(2)\n", encoding="utf-8")
    f = only(recheck(ev, rebuild(root)), "svc.py::parse")
    assert f.status == "holds" and any("not measured" in n for n in f.not_measured)


def test_the_report_says_what_it_does_not_check(app):
    root, g = app
    report = recheck(snap(g, "svc.py::parse"), rebuild(root))
    assert "not that the skill's advice is right" in report.limits and report.counts == {"holds": 1}


def test_another_repository_is_pointed_out(app, repo):
    _, g = app
    ev = snap(g, "svc.py::parse")
    other = rebuild(repo(APP))  # same files, a different folder name
    report = recheck(ev, other)
    assert any("recorded from" in n for n in report.notes)


def test_a_different_commit_is_stated(repo):
    root = repo(APP)
    git(root, "init", "-q")
    commit_all(root, "first")
    ev = snap(rebuild(root), "svc.py::parse")
    (root / "extra.py").write_text("x = 1\n", encoding="utf-8")
    commit_all(root, "second")
    report = recheck(ev, rebuild(root))
    assert report.recorded_commit == ev.commit and report.current_commit and report.current_commit != ev.commit
    assert report.counts == {"holds": 1}


def test_a_typescript_export_that_was_removed_is_a_change(repo):
    root = repo({"a.ts": "export function run(x: number): number {\n  return x + 1;\n}\n", "b.ts": "import { run } from './a';\nexport function go(): number {\n  return run(1);\n}\n"})
    ev = snap(rebuild(root), "a.ts::run")
    (root / "a.ts").write_text("function run(x: number): number {\n  return x + 1;\n}\nexport { };\n", encoding="utf-8")
    f = only(recheck(ev, rebuild(root)), "a.ts::run")
    assert f.status == "changed" and "export" in " ".join(f.details).lower()


# ---- the file format: data only, read strictly -------------------------------------------------------


def test_the_file_round_trips(app):
    _, g = app
    ev = snap(g, "svc.py::parse", "api.py")
    again = read_evidence({EVIDENCE_FILE: evidence_bytes(ev)})
    assert again == ev and read_evidence({"SKILL.md": b"x"}) is None


def test_the_file_is_the_same_bytes_every_time(app):
    _, g = app
    assert evidence_bytes(snap(g, "svc.py::parse")) == evidence_bytes(snap(g, "svc.py::parse"))


def good(**over):
    base = {"version": 1, "repo": "r", "commit": None, "focus": None, "taken_at": "2026-11-23T09:00:00+00:00",
            "refs": [{"id": "a.py", "kind": "file", "file": "a.py"}]}
    return {**base, **over}


@pytest.mark.parametrize("doc, why", [
    (good(extra=1), "extra"),
    (good(version=2), "version"),
    (good(refs=[{"id": "a.py", "kind": "file", "file": "a.py"}] * 2), "twice"),
    (good(refs=[{"id": f"f{i}.py", "kind": "file", "file": f"f{i}.py"} for i in range(MAX_REFS + 1)]), "too many"),
    (good(refs=[{"id": "a\x1b[31m.py", "kind": "file", "file": "a.py"}]), "control"),
    (good(refs=[{"id": "a\u202e.py", "kind": "file", "file": "a.py"}]), "direction change"),
    (good(refs=[{"id": "a\u200b.py", "kind": "file", "file": "a.py"}]), "zero width"),
    (good(refs=[{"id": "a.py", "kind": "file", "file": "a.py", "callers": ["x\u2066y"]}]), "isolate in a list"),
    (good(commit="abc\u202e"), "commit"),
    (good(refs=[{"id": "a" * 5000, "kind": "file", "file": "a.py"}]), "long"),
    (good(refs=[{"id": "a.py", "kind": "file", "file": "a.py", "callers": ["x"] * 41}]), "list"),
    (good(refs=[{"id": "a.py", "kind": "dir", "file": "a.py"}]), "kind"),
    (good(refs=[{"id": "a.py", "kind": "file", "file": "a.py", "line": -1}]), "negative"),
    (good(repo="r\nforged line"), "newline"),
])
def test_a_malformed_file_is_refused(doc, why):
    with pytest.raises(EvidenceError):
        read_evidence({EVIDENCE_FILE: json.dumps(doc).encode()})


@pytest.mark.parametrize("raw", [b"not json", b"[]", b"\xff\xfe", b"{" * 5000, b"null", b'{"version": 1}'])
def test_a_file_that_is_not_evidence_is_refused(raw):
    with pytest.raises(EvidenceError):
        read_evidence({EVIDENCE_FILE: raw})


def test_a_hostile_reference_is_only_ever_a_key(app):
    root, g = app
    doc = good(refs=[{"id": "../../etc/passwd", "kind": "file", "file": "../../etc/passwd"},
                     {"id": "svc.py::__import__('os').system('x')", "kind": "symbol", "file": "svc.py"}])
    ev = read_evidence({EVIDENCE_FILE: json.dumps(doc).encode()})
    report = recheck(ev, g)
    assert [f.status for f in report.findings] == ["missing", "missing"]  # looked up, never opened or evaluated


def test_the_model_is_a_plain_data_class():
    assert Ref(id="a", kind="file", file="a").callers == [] and isinstance(Evidence, type)


def test_an_unreadable_source_file_leaves_the_text_hash_empty(app, monkeypatch):
    _, g = app
    monkeypatch.setattr(Path, "read_bytes", lambda self: (_ for _ in ()).throw(OSError("no")))
    (ref,) = snap(g, "svc.py::parse").refs
    assert ref.text_hash is None
