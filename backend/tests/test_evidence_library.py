"""Evidence in the library: citing places, rechecking, refreshing, and what travels with a skill. All offline, no model."""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest
from test_evidence import APP, LONG, NOW, rebuild
from test_library import NAME, write_skill
from test_plugin import compose, make_library

from skillforge.evidence import EVIDENCE_FILE, read_evidence
from skillforge.library import Library, LibraryError, compare_with_risk, export_skill, import_skill, package_skill, rollback
from skillforge.library.evidence import cite, recheck_version, refresh
from skillforge.results import FAILED, PASSED
from skillforge.validate import validate_files

LATER = datetime(2026, 11, 24, 9, 0, tzinfo=timezone.utc)


@pytest.fixture
def lib(tmp_path) -> Library:
    return Library(tmp_path / "library")


@pytest.fixture
def world(tmp_path, repo, lib):
    """A repository, its graph, and a library holding one plain skill."""
    root = repo(APP)
    assert not import_skill(write_skill(tmp_path / NAME), lib).refused
    return root, rebuild(root), lib


def edit(root, rel, old, new):
    text = (root / rel).read_text(encoding="utf-8")
    assert old in text
    (root / rel).write_text(text.replace(old, new), encoding="utf-8")


# ---- the check ---------------------------------------------------------------------------------------


def row(files):
    return [c for c in validate_files(files, folder=NAME) if "evidence" in c.name.lower()]


def good_file(**over) -> bytes:
    doc = {"version": 1, "repo": "r", "commit": None, "focus": None, "taken_at": "2026-11-23T09:00:00+00:00",
           "refs": [{"id": "a.py", "kind": "file", "file": "a.py"}], **over}
    return json.dumps(doc).encode()


def skill_with(evidence: bytes | None) -> dict[str, bytes]:
    files = {"SKILL.md": f"---\nname: {NAME}\ndescription: Reads a file and says what it holds.\n---\n# Demo\n\nRead it.\n".encode(), "README.md": b"x\n"}
    if evidence is not None:
        files[EVIDENCE_FILE] = evidence
    return files


def test_a_skill_without_evidence_has_no_evidence_row():
    assert row(skill_with(None)) == []


def test_good_evidence_passes_and_says_how_many_places():
    (c,) = row(skill_with(good_file()))
    assert c.status == PASSED and "1 place" in c.detail


@pytest.mark.parametrize("raw", [b"not json", good_file(extra=1), good_file(version=2), b"[]"])
def test_bad_evidence_fails_the_check(raw):
    (c,) = row(skill_with(raw))
    assert c.status == FAILED and EVIDENCE_FILE in c.detail


def test_a_skill_with_bad_evidence_is_refused_by_import(tmp_path, lib):
    src = write_skill(tmp_path / "bad", **{EVIDENCE_FILE: "not json"})
    assert import_skill(src, lib).refused


# ---- citing ------------------------------------------------------------------------------------------


def test_citing_a_place_makes_a_new_version_with_the_facts(world):
    _, g, lib = world
    r = cite(lib, NAME, g, ["svc.py::parse", "api.py"], now=NOW)
    assert (r.version.tag, r.created, r.added, r.skipped) == ("v2", True, ["svc.py::parse", "api.py"], [])
    ev = read_evidence(lib.read(NAME)[1])
    assert [x.id for x in ev.refs] == ["svc.py::parse", "api.py"] and ev.refs[0].callers_total == 2
    v = lib.pick(NAME)
    assert v.source_kind == "evidence" and v.source_label == ev.repo


def test_a_place_that_is_not_in_the_repository_is_reported_and_not_recorded(world):
    _, g, lib = world
    r = cite(lib, NAME, g, ["svc.py::parse", "svc.py::nothing"], now=NOW)
    assert [s[0] for s in r.skipped] == ["svc.py::nothing"] and [x.id for x in r.evidence.refs] == ["svc.py::parse"]


def test_citing_only_what_cannot_be_found_changes_nothing(world):
    _, g, lib = world
    with pytest.raises(LibraryError, match="nothing"):
        cite(lib, NAME, g, ["nothing_here"], now=NOW)
    assert [v.tag for v in lib.versions(NAME)] == ["v1"]


def test_an_ambiguous_name_is_listed_and_never_picked(tmp_path, repo, lib):
    root = repo({"a.py": "def run():\n    pass\n", "b.py": "def run():\n    pass\n"})
    assert not import_skill(write_skill(tmp_path / NAME), lib).refused
    with pytest.raises(LibraryError) as err:
        cite(lib, NAME, rebuild(root), ["run"], now=NOW)
    assert "a.py::run" in str(err.value) and "b.py::run" in str(err.value)


def test_citing_again_adds_and_leaves_the_recorded_facts_alone(world):
    root, g, lib = world
    cite(lib, NAME, g, ["svc.py::parse"], now=NOW)
    edit(root, "main.py", "handler(1)", "handler(1)\n    handler(2)")
    r = cite(lib, NAME, rebuild(root), ["svc.py::parse", "api.py"], now=LATER)
    assert r.added == ["api.py"] and r.kept == ["svc.py::parse"]
    ev = read_evidence(lib.read(NAME)[1])
    assert ev.refs[0].taken_at == NOW.isoformat(timespec="seconds") and ev.refs[1].taken_at == LATER.isoformat(timespec="seconds")
    assert ev.taken_at == LATER.isoformat(timespec="seconds")  # the latest recording


def test_citing_the_same_again_makes_no_new_version(world):
    _, g, lib = world
    cite(lib, NAME, g, ["svc.py::parse"], now=NOW)
    r = cite(lib, NAME, g, ["svc.py::parse"], now=LATER)
    assert r.created is False and [v.tag for v in lib.versions(NAME)] == ["v1", "v2"]


def test_another_repository_is_refused_for_a_skill_that_has_evidence(world, repo):
    _, g, lib = world
    cite(lib, NAME, g, ["svc.py::parse"], now=NOW)
    other = rebuild(repo({"x.py": "def f():\n    pass\n"}))
    with pytest.raises(LibraryError, match="recorded from"):
        cite(lib, NAME, other, ["x.py"], now=NOW)


def test_too_many_places_are_refused(world):
    root, _, lib = world
    (root / "many.py").write_text("".join(f"def f{i}():\n    pass\n\n" for i in range(70)), encoding="utf-8")
    g = rebuild(root)
    with pytest.raises(LibraryError, match="60"):
        cite(lib, NAME, g, [f"many.py::f{i}" for i in range(70)], now=NOW)
    assert [v.tag for v in lib.versions(NAME)] == ["v1"]


def test_places_named_in_the_skills_own_text_can_be_cited(tmp_path, repo, lib):
    root = repo({**APP, "dup1.py": "def run():\n    pass\n", "dup2.py": "def run():\n    pass\n"})
    body = "Use `svc.py::parse` and then `handler`. Never call run, or `run()`, or the word parse alone.\n"
    assert not import_skill(write_skill(tmp_path / NAME, body), lib).refused
    r = cite(lib, NAME, rebuild(root), [], from_text=True, now=NOW)
    assert sorted(r.added) == ["api.py::handler", "svc.py::parse"]
    assert [a[0] for a in r.ambiguous] == ["run()"] and sorted(r.ambiguous[0][1]) == ["dup1.py::run", "dup2.py::run"]


def test_text_that_names_nothing_is_not_an_error_of_the_text_path(tmp_path, repo, lib):
    root = repo(APP)
    assert not import_skill(write_skill(tmp_path / NAME), lib).refused
    with pytest.raises(LibraryError, match="nothing"):
        cite(lib, NAME, rebuild(root), [], from_text=True, now=NOW)


def test_a_skill_that_is_not_there_is_refused(world):
    _, g, lib = world
    with pytest.raises(LibraryError, match="no skill named"):
        cite(lib, "missing-skill", g, ["svc.py"], now=NOW)


# ---- rechecking --------------------------------------------------------------------------------------


def test_recheck_reads_the_stored_evidence_and_changes_nothing(world):
    root, g, lib = world
    cite(lib, NAME, g, ["svc.py::parse"], now=NOW)
    edit(root, "main.py", "handler(1)", "handler(1)\n    handler(2)")
    assert recheck_version(lib, NAME, rebuild(root)).ok is True  # an unrelated change
    (root / "svc.py").write_text("def other():\n    pass\n", encoding="utf-8")
    report = recheck_version(lib, NAME, rebuild(root))
    assert report.ok is False and report.counts == {"missing": 1} and [v.tag for v in lib.versions(NAME)] == ["v1", "v2"]


def test_recheck_of_a_skill_without_evidence_says_how_to_add_some(world):
    root, _, lib = world
    with pytest.raises(LibraryError, match="library cite"):
        recheck_version(lib, NAME, rebuild(root))


def test_recheck_can_look_at_an_older_version(world):
    root, g, lib = world
    cite(lib, NAME, g, ["svc.py::parse"], now=NOW)
    with pytest.raises(LibraryError, match="no evidence"):
        recheck_version(lib, NAME, rebuild(root), version=1)


# ---- refreshing --------------------------------------------------------------------------------------


def test_refresh_with_nothing_changed_makes_no_new_version(world):
    root, g, lib = world
    cite(lib, NAME, g, ["svc.py::parse", "api.py"], now=NOW)
    r = refresh(lib, NAME, rebuild(root), now=LATER)
    assert r.created is False and r.updated == [] and sorted(r.unchanged) == ["api.py", "svc.py::parse"]


def test_refresh_records_what_changed_after_a_person_has_looked(world):
    root, g, lib = world
    cite(lib, NAME, g, ["svc.py::parse", "svc.py::clean"], now=NOW)
    edit(root, "main.py", "handler(1)", "handler(1)\n    handler(2)")
    edit(root, "svc.py", "raw.strip()", "raw.rstrip()")
    r = refresh(lib, NAME, rebuild(root), now=LATER)
    assert r.created is True and r.updated == ["svc.py::clean"] and r.unchanged == ["svc.py::parse"] and r.version.tag == "v3"
    ev = read_evidence(lib.read(NAME)[1])
    by = {x.id: x for x in ev.refs}
    assert by["svc.py::clean"].taken_at == LATER.isoformat(timespec="seconds") and by["svc.py::parse"].taken_at == NOW.isoformat(timespec="seconds")
    assert recheck_version(lib, NAME, rebuild(root)).counts == {"holds": 2}


def test_refresh_keeps_what_is_missing_and_still_flags_it(world):
    root, g, lib = world
    cite(lib, NAME, g, ["svc.py::parse", "svc.py::clean"], now=NOW)
    edit(root, "svc.py", "def clean(raw):\n    return raw.strip()\n", "")
    r = refresh(lib, NAME, rebuild(root), now=LATER)
    assert r.kept_missing == ["svc.py::clean"] and r.dropped == []
    assert recheck_version(lib, NAME, rebuild(root)).counts == {"missing": 1, "holds": 1}


def test_refresh_can_drop_what_is_gone(world):
    root, g, lib = world
    cite(lib, NAME, g, ["svc.py::parse", "svc.py::clean"], now=NOW)
    edit(root, "svc.py", "def clean(raw):\n    return raw.strip()\n", "")
    r = refresh(lib, NAME, rebuild(root), drop_missing=True, now=LATER)
    assert r.dropped == ["svc.py::clean"] and r.created is True
    assert [x.id for x in read_evidence(lib.read(NAME)[1]).refs] == ["svc.py::parse"]


def test_dropping_every_place_is_refused(world):
    root, g, lib = world
    cite(lib, NAME, g, ["svc.py::clean"], now=NOW)
    edit(root, "svc.py", "def clean(raw):\n    return raw.strip()\n", "")
    with pytest.raises(LibraryError, match="every place"):
        refresh(lib, NAME, rebuild(root), drop_missing=True, now=LATER)


def test_a_moved_function_can_be_followed_by_citing_the_new_place_then_dropping_the_old(world):
    root, g, lib = world
    cite(lib, NAME, g, ["svc.py::tidy"], now=NOW)
    edit(root, "svc.py", LONG, "")
    (root / "util.py").write_text(LONG, encoding="utf-8")
    g2 = rebuild(root)
    assert recheck_version(lib, NAME, g2).findings[0].candidates == ["util.py::tidy"]
    cite(lib, NAME, g2, ["util.py::tidy"], now=LATER)
    refresh(lib, NAME, g2, drop_missing=True, now=LATER)
    assert recheck_version(lib, NAME, g2).counts == {"holds": 1}


# ---- what travels with a skill -----------------------------------------------------------------------


def test_evidence_is_not_a_risk_and_rollback_keeps_it(world):
    _, g, lib = world
    cite(lib, NAME, g, ["svc.py::parse"], now=NOW)
    c = compare_with_risk(lib, NAME)
    assert [x.path for x in c.changes] == [EVIDENCE_FILE] and not [r for r in c.risk.changes if r.direction == "riskier"]
    rollback(lib, NAME, 2)  # a new version with the content of v2: the evidence is in it
    assert read_evidence(lib.read(NAME)[1]) is not None


def test_export_includes_evidence_and_can_leave_it_out(world, tmp_path):
    _, g, lib = world
    cite(lib, NAME, g, ["svc.py::parse"], now=NOW)
    assert package_skill(lib, NAME, None).files == 3
    full = export_skill(lib, NAME, None, tmp_path / "a.zip")
    assert full.dropped == []
    out = export_skill(lib, NAME, None, tmp_path / "b.zip", without_evidence=True)
    assert out.dropped == [EVIDENCE_FILE] and out.files == full.files - 1


def test_a_plugin_never_ships_a_components_evidence(tmp_path):
    lib = make_library(tmp_path, {EVIDENCE_FILE: good_file().decode()})
    assert EVIDENCE_FILE in lib.read(NAME)[1]
    plan = compose(lib)
    assert not [p for p in plan.files if p.endswith(EVIDENCE_FILE)]
