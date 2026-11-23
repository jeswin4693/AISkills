"""The command line for evidence: library cite | recheck | refresh, export --without-evidence, build --repo. All offline."""

from __future__ import annotations

import json

import pytest
from test_evidence import APP, LONG, rebuild
from test_library import NAME, write_skill
from test_skill_build import ANSWERS, FIRST, draft, round_one, round_two

from skillforge import cli
from skillforge.evidence import EVIDENCE_FILE, read_evidence
from skillforge.library import Library
from skillforge.providers import MockProvider


def run(capsys, *argv: str):
    code = cli.main(list(argv))
    out = capsys.readouterr()
    return code, out.out, out.err


@pytest.fixture
def world(tmp_path, repo, capsys):
    """A repository, and a library (the test's own data folder) holding one skill."""
    root = repo(APP)
    skill = write_skill(tmp_path / NAME, "Use `svc.py::parse` and `handler`.\n")
    assert run(capsys, "library", "import", str(skill))[0] == 0
    return root, skill


def edit(root, rel, old, new):
    text = (root / rel).read_text(encoding="utf-8")
    assert old in text
    (root / rel).write_text(text.replace(old, new), encoding="utf-8")


# ---- cite --------------------------------------------------------------------------------------------


def test_cite_records_places_and_says_what_it_did(world, capsys):
    root, _ = world
    code, out, _ = run(capsys, "library", "cite", NAME, "--repo", str(root), "--ref", "svc.py::parse", "--ref", "api.py")
    assert code == 0 and "v2" in out and "svc.py::parse" in out and "api.py" in out
    assert "recheck" in out  # the next step is named
    ev = read_evidence(Library().read(NAME)[1])
    assert [r.id for r in ev.refs] == ["svc.py::parse", "api.py"]


def test_cite_from_the_skills_own_text(world, capsys):
    root, _ = world
    code, out, _ = run(capsys, "library", "cite", NAME, "--repo", str(root), "--from-text")
    assert code == 0 and "svc.py::parse" in out and "api.py::handler" in out


def test_cite_says_what_it_could_not_record(world, capsys):
    root, _ = world
    code, out, _ = run(capsys, "library", "cite", NAME, "--repo", str(root), "--ref", "svc.py::parse", "--ref", "svc.py::nope")
    assert code == 0 and "Not recorded" in out and "svc.py::nope" in out


def test_cite_with_nothing_findable_exits_2_and_names_the_options(world, tmp_path, capsys):
    other = tmp_path / "twin"
    other.mkdir()
    (other / "a.py").write_text("def run():\n    pass\n", encoding="utf-8")
    (other / "b.py").write_text("def run():\n    pass\n", encoding="utf-8")
    code, _, err = run(capsys, "library", "cite", NAME, "--repo", str(other), "--ref", "run")
    assert code == 2 and "a.py::run" in err and "b.py::run" in err


def test_cite_needs_something_to_cite(world, capsys):
    root, _ = world
    code, _, err = run(capsys, "library", "cite", NAME, "--repo", str(root))
    assert code == 2 and "--ref" in err and "--from-text" in err


def test_cite_for_a_missing_repository_is_a_plain_error(world, tmp_path, capsys):
    code, _, err = run(capsys, "library", "cite", NAME, "--repo", str(tmp_path / "nowhere"), "--ref", "x")
    assert code == 2 and "Not a directory" in err


# ---- recheck -----------------------------------------------------------------------------------------


def test_recheck_of_unchanged_code_exits_0(world, capsys):
    root, _ = world
    run(capsys, "library", "cite", NAME, "--repo", str(root), "--ref", "svc.py::parse")
    code, out, _ = run(capsys, "library", "recheck", NAME, "--repo", str(root))
    assert code == 0 and "holds" in out and "not that the skill's advice is right" in out


def test_recheck_says_what_changed_and_exits_1(world, capsys):
    root, _ = world
    run(capsys, "library", "cite", NAME, "--repo", str(root), "--ref", "svc.py::parse", "--ref", "svc.py::clean")
    edit(root, "main.py", "handler(1)", "handler(1)\n    handler(2)")
    edit(root, "main.py", "from api import handler", "from api import handler\nfrom svc import parse")
    edit(root, "main.py", "handler(2)", "handler(2)\n    parse(3)")
    edit(root, "svc.py", "def clean(raw):\n    return raw.strip()\n", "")
    code, out, _ = run(capsys, "library", "recheck", NAME, "--repo", str(root))
    assert code == 1
    assert "CHANGED" in out and "main.py::main" in out and "was 2" in out
    assert "MISSING" in out and "svc.py::clean" in out
    assert out.index("MISSING") < out.index("CHANGED")  # the worst comes first


def test_recheck_lists_a_candidate_and_says_it_is_one(world, capsys):
    root, _ = world
    run(capsys, "library", "cite", NAME, "--repo", str(root), "--ref", "svc.py::tidy")
    edit(root, "svc.py", "def tidy(", "def normalise(")
    code, out, _ = run(capsys, "library", "recheck", NAME, "--repo", str(root))
    assert code == 1 and "MOVED" in out and "svc.py::normalise" in out and "candidate" in out


def test_recheck_json_is_machine_readable(world, capsys):
    root, _ = world
    run(capsys, "library", "cite", NAME, "--repo", str(root), "--ref", "svc.py::parse")
    code, out, _ = run(capsys, "library", "recheck", NAME, "--repo", str(root), "--json")
    doc = json.loads(out)
    assert code == 0 and doc["ok"] is True and doc["counts"] == {"holds": 1} and doc["findings"][0]["ref"] == "svc.py::parse"
    assert "advice" in doc["limits"] and doc["skill"] == NAME and doc["version"] == "v2"


def test_recheck_without_evidence_exits_2_and_says_how_to_add_some(world, capsys):
    root, _ = world
    code, _, err = run(capsys, "library", "recheck", NAME, "--repo", str(root))
    assert code == 2 and "library cite" in err


def test_recheck_changes_nothing_in_the_library(world, capsys):
    root, _ = world
    run(capsys, "library", "cite", NAME, "--repo", str(root), "--ref", "svc.py::parse")
    before = [v.tag for v in Library().versions(NAME)]
    edit(root, "svc.py", "def parse(raw):\n    return clean(raw)\n", "def parse(raw):\n    return 1\n")
    run(capsys, "library", "recheck", NAME, "--repo", str(root))
    assert [v.tag for v in Library().versions(NAME)] == before


# ---- refresh -----------------------------------------------------------------------------------------


def test_refresh_after_a_review_makes_the_recheck_pass(world, capsys):
    root, _ = world
    run(capsys, "library", "cite", NAME, "--repo", str(root), "--ref", "svc.py::clean")
    edit(root, "svc.py", "return raw.strip()", "return raw.rstrip()")
    code, out, _ = run(capsys, "library", "refresh", NAME, "--repo", str(root))
    assert code == 0 and "v3" in out and "svc.py::clean" in out
    assert run(capsys, "library", "recheck", NAME, "--repo", str(root))[0] == 0


def test_refresh_with_nothing_to_record_says_so(world, capsys):
    root, _ = world
    run(capsys, "library", "cite", NAME, "--repo", str(root), "--ref", "svc.py::clean")
    code, out, _ = run(capsys, "library", "refresh", NAME, "--repo", str(root))
    assert code == 0 and "Nothing changed" in out


def test_refresh_reports_what_is_gone_and_can_drop_it(world, capsys):
    root, _ = world
    run(capsys, "library", "cite", NAME, "--repo", str(root), "--ref", "svc.py::clean", "--ref", "svc.py::parse")
    edit(root, "svc.py", "def clean(raw):\n    return raw.strip()\n", "")
    code, out, _ = run(capsys, "library", "refresh", NAME, "--repo", str(root))
    assert code == 0 and "Gone from the repository" in out and "svc.py::clean" in out and "--drop-missing" in out
    code, out, _ = run(capsys, "library", "refresh", NAME, "--repo", str(root), "--drop-missing")
    assert code == 0 and "Dropped" in out


# ---- export ------------------------------------------------------------------------------------------


def test_export_says_evidence_names_code_and_can_leave_it_out(world, tmp_path, capsys):
    root, _ = world
    run(capsys, "library", "cite", NAME, "--repo", str(root), "--ref", "svc.py::parse")
    code, out, _ = run(capsys, "library", "export", NAME, "--out", str(tmp_path / "a.zip"))
    assert code == 0 and EVIDENCE_FILE in out and "--without-evidence" in out
    code, out, _ = run(capsys, "library", "export", NAME, "--out", str(tmp_path / "b.zip"), "--without-evidence")
    assert code == 0 and "Left out on request: evidence.json" in out


# ---- build --repo ------------------------------------------------------------------------------------


@pytest.fixture
def idea(tmp_path, repo):
    root = repo(APP)
    report = tmp_path / "report.json"
    report.write_text(json.dumps({"repo": root.name, "suggestions": [{
        "title": "Duplicate finder", "skill_requirement": FIRST, "evidence_nodes": ["svc.py::parse", "api.py", "gone.py"],
    }]}), encoding="utf-8")
    answers = tmp_path / "a.json"
    answers.write_text(json.dumps(ANSWERS), encoding="utf-8")
    return root, report, answers


def build(capsys, monkeypatch, tmp_path, report, answers, *extra):
    monkeypatch.setattr(cli, "provider_from_env", lambda: MockProvider([round_one(), round_two(), draft()]))
    return run(capsys, "build", "--from-suggestions", str(report), "--pick", "1", "--answers", str(answers), "--yes",
               "--out", str(tmp_path / "skills"), *extra)


def test_build_with_a_repository_records_the_ideas_evidence(idea, monkeypatch, capsys, tmp_path):
    root, report, answers = idea
    code, out, _ = build(capsys, monkeypatch, tmp_path, report, answers, "--repo", str(root))
    assert code == 0 and "evidence.json" in out and "2 place" in out and "gone.py" in out
    folder = tmp_path / "skills" / "duplicate-function-finder"
    ev = read_evidence({EVIDENCE_FILE: (folder / EVIDENCE_FILE).read_bytes()})
    assert [r.id for r in ev.refs] == ["svc.py::parse", "api.py"] and ev.repo == root.name
    assert run(capsys, "library", "import", str(folder))[0] == 0  # the built folder imports with its evidence
    assert run(capsys, "library", "recheck", "duplicate-function-finder", "--repo", str(root))[0] == 0


def test_build_without_a_repository_says_the_evidence_was_not_recorded(idea, monkeypatch, capsys, tmp_path):
    _, report, answers = idea
    code, out, _ = build(capsys, monkeypatch, tmp_path, report, answers)
    assert code == 0 and "--repo" in out and "not recorded" in out.lower()
    assert not (tmp_path / "skills" / "duplicate-function-finder" / EVIDENCE_FILE).exists()


def test_build_from_a_plain_description_never_makes_evidence(monkeypatch, capsys, tmp_path, repo):
    monkeypatch.setattr(cli, "provider_from_env", lambda: MockProvider([round_one(), round_two(), draft()]))
    answers = tmp_path / "a.json"
    answers.write_text(json.dumps(ANSWERS), encoding="utf-8")
    code, out, _ = run(capsys, "build", FIRST, "--answers", str(answers), "--yes", "--out", str(tmp_path / "s"), "--repo", str(repo(APP)))
    assert code == 0 and "evidence" not in out.lower()
    assert not list((tmp_path / "s").rglob(EVIDENCE_FILE))


def test_a_repository_that_is_not_a_folder_stops_before_a_model_is_asked(idea, monkeypatch, capsys, tmp_path):
    _, report, answers = idea
    mock = MockProvider([round_one(), round_two(), draft()])
    monkeypatch.setattr(cli, "provider_from_env", lambda: mock)
    code, _, err = run(capsys, "build", "--from-suggestions", str(report), "--pick", "1", "--answers", str(answers), "--yes",
                       "--out", str(tmp_path / "s"), "--repo", str(tmp_path / "nowhere"))
    assert code == 2 and "Not a directory" in err and mock.calls == []
