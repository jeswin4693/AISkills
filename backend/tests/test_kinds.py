"""The kind registry: what the app knows how to build. Phase 0 has one kind (a skill); the registry and the helpers
here are what later kinds, the library, the builder and the API consult, so none of them hardcode "skill".

`FakeKind` and `fake_kind` stand in for a second kind in the tests of those later parts.
"""

from __future__ import annotations

import tempfile
from collections.abc import Mapping
from pathlib import Path

import pytest
from test_library import write_skill

import skillforge.library as library
from skillforge.build.models import SLOTS
from skillforge.build.requirements import QUESTIONS
from skillforge.graph.store import data_dir
from skillforge.kinds import KINDS, UnknownKind, all_kinds, get_kind
from skillforge.kinds.base import Kind
from skillforge.library import Library, import_skill, install_skill, package_skill, rescan, rollback
from skillforge.results import FAILED, PASSED, CheckResult
from skillforge.validate import DEFINITION_CHECKS
from skillforge.validate.static import SLUG


class FakeKind(Kind):
    """A second kind for tests: a folder holding `thing.txt` whose first line is the name."""

    key = "note"
    label = "Note"
    library_dir = "library-note"
    slots = ()

    def name_of(self, files: Mapping[str, bytes]) -> str | None:
        try:
            first = files["thing.txt"].decode("utf-8").split("\n", 1)[0].strip()
        except (KeyError, UnicodeDecodeError):
            return None
        return first if SLUG.match(first) else None

    def personal_dir(self) -> Path:
        return Path(tempfile.gettempdir()) / "skillforge-fake-note-kind"


def check_thing(files: Mapping[str, bytes], folder: str | None) -> list[CheckResult]:
    """The fake kind's definition check, in place of the SKILL.md check: there must be a thing.txt."""
    ok = "thing.txt" in files
    return [CheckResult("thing.txt exists", PASSED if ok else FAILED, "" if ok else "there is no thing.txt")]


@pytest.fixture
def fake_kind(monkeypatch) -> FakeKind:
    """Register the fake kind (and its definition check) for one test, and take them away again afterwards."""
    kind = FakeKind()
    monkeypatch.setitem(KINDS, "note", kind)
    monkeypatch.setitem(DEFINITION_CHECKS, "note", check_thing)
    return kind


def write_thing(root: Path, name: str = "my-thing", body: str = "hello") -> Path:
    """A valid folder of the fake kind. Writing the same folder again with another body gives its next version."""
    root.mkdir(parents=True, exist_ok=True)
    (root / "thing.txt").write_text(f"{name}\n{body}\n", encoding="utf-8", newline="\n")
    return root


def test_the_skill_kind_is_registered_and_an_unknown_kind_is_a_plain_error():
    assert [k.key for k in all_kinds()] == ["skill"]
    with pytest.raises(UnknownKind) as err:
        get_kind("nope")
    assert "skill" in str(err.value)
    assert str(err.value) == "'nope' is not a kind this app builds. It builds: skill."
    assert isinstance(err.value, ValueError)


def test_the_skill_kinds_slots_are_the_checklist_in_order():
    skill = get_kind("skill")
    assert (skill.key, skill.label, skill.library_dir) == ("skill", "Skill", "library")
    assert [s.key for s in skill.slots] == list(SLOTS)
    assert all(s.question == QUESTIONS[s.key] for s in skill.slots)
    assert [s.label for s in skill.slots] == [
        "Goal", "What it receives", "What it produces", "Rules it must respect",
        "How we will know it works", "When something goes wrong",
    ]
    assert skill.slots[1].label == "What it receives"
    assert skill.install_targets == ("personal", "folder")


def test_name_of_reads_the_front_matter_name_and_refuses_unsafe_names():
    name_of = get_kind("skill").name_of

    def md(text: str) -> dict[str, bytes]:
        return {"SKILL.md": text.encode("utf-8")}

    assert name_of(md("---\nname: a-b\n---\n")) == "a-b"
    assert name_of(md("---\r\nname: a-b\r\n---\r\n")) == "a-b"
    assert name_of(md("---\nname: ../x\n---\n")) is None
    assert name_of(md("---\nname: " + "a" * 64 + "\n---\n")) == "a" * 64
    assert name_of(md("---\nname: " + "a" * 65 + "\n---\n")) is None
    assert name_of(md("# no front matter\n")) is None
    assert name_of(md("---\nname: [unclosed\n---\n")) is None
    assert name_of({}) is None
    assert name_of({"SKILL.md": b"\xff\xfe"}) is None
    # The library's own name check is this same behaviour, not a copy that could drift.
    assert library.skill_name_of(md("---\nname: a-b\n---\n")) == "a-b"
    assert library.skill_name_of(md("---\nname: ../x\n---\n")) is None


def test_the_personal_folder_is_worked_out_when_asked_so_a_test_can_move_home(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    assert get_kind("skill").personal_dir() == tmp_path / ".claude" / "skills"


def test_the_fake_kind_is_only_registered_for_the_test_that_asks(fake_kind):
    assert [k.key for k in all_kinds()] == ["skill", "note"]
    assert get_kind("note") is fake_kind
    assert fake_kind.name_of({"thing.txt": b"my-note\nbody"}) == "my-note"
    assert fake_kind.name_of({"thing.txt": b"Not A Slug"}) is None
    with pytest.raises(UnknownKind) as err:
        get_kind("other")
    assert "skill, note" in str(err.value)


def test_the_fake_kind_is_gone_again_after_that_test():
    assert [k.key for k in all_kinds()] == ["skill"]


# ---- a library for each kind -------------------------------------------------------------------------


def test_each_kind_has_its_own_library_root_and_names_never_cross(tmp_path, fake_kind):
    lib = Library(tmp_path / "library")
    note = lib.for_kind("note")
    report = import_skill(write_thing(tmp_path / "src"), note)
    assert not report.refused and report.name == "my-thing"
    assert note.root == tmp_path / "library-note"
    assert lib.names() == []
    assert note.names() == ["my-thing"]
    assert lib.for_kind("skill") is lib
    assert Library().root == data_dir() / "library"
    assert Library(kind="note").root == data_dir() / "library-note"


@pytest.mark.parametrize("bad", ["../x", "", "a/b"])
def test_a_kind_is_never_joined_into_a_path(tmp_path, bad):
    lib = Library(tmp_path / "library")
    before = sorted(p.name for p in tmp_path.iterdir())
    with pytest.raises(UnknownKind):
        Library(tmp_path / "library", kind=bad)
    with pytest.raises(UnknownKind):
        lib.for_kind(bad)
    assert sorted(p.name for p in tmp_path.iterdir()) == before


def test_importing_into_another_kind_uses_its_name_and_its_checks(tmp_path, fake_kind):
    lib = Library(tmp_path / "library")
    note = lib.for_kind("note")
    only_skill_md = write_skill(tmp_path / "demo-skill")
    report = import_skill(only_skill_md, note)
    assert report.refused
    assert any(c.name == "thing.txt exists" and c.status == FAILED for c in report.checks)
    assert not any(c.name.startswith("SKILL.md") for c in report.checks)  # the skill check is not run for this kind
    assert note.names() == []
    assert not import_skill(only_skill_md, lib).refused  # the same folder is still a fine skill
    import_skill(write_thing(tmp_path / "src"), note)
    assert [c["name"] for c in note.versions("my-thing")[0].checks if c["name"] == "thing.txt exists"] == ["thing.txt exists"]


def test_rescan_and_rollback_use_the_libraries_kind(tmp_path, fake_kind):
    note = Library(tmp_path / "library").for_kind("note")
    src = write_thing(tmp_path / "src", body="one")
    import_skill(src, note)
    write_thing(tmp_path / "src", body="two")
    import_skill(src, note)
    assert [s.status for s in rescan(note)] == ["same", "same"]  # it would say "failing" if it asked for a SKILL.md
    version, created = rollback(note, "my-thing", 1)
    assert created and version.tag == "v3"


def test_export_and_install_check_with_the_libraries_kind(tmp_path, fake_kind):
    note = Library(tmp_path / "library").for_kind("note")
    import_skill(write_thing(tmp_path / "src"), note)
    assert package_skill(note, "my-thing", None).files == 1
    report = install_skill(note, "my-thing", None, tmp_path / "installed")
    assert (report.path / "thing.txt").read_text(encoding="utf-8") == "my-thing\nhello\n"
