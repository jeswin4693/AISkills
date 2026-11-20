"""The kind registry: what the app knows how to build. Phase 0 has one kind (a skill); the registry and the helpers
here are what later kinds, the library, the builder and the API consult, so none of them hardcode "skill".

`FakeKind` and `fake_kind` stand in for a second kind in the tests of those later parts.
"""

from __future__ import annotations

import tempfile
from collections.abc import Mapping
from pathlib import Path

import pytest

import skillforge.library as library
from skillforge.build.models import SLOTS
from skillforge.build.requirements import QUESTIONS
from skillforge.kinds import KINDS, UnknownKind, all_kinds, get_kind
from skillforge.kinds.base import Kind
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


@pytest.fixture
def fake_kind(monkeypatch) -> FakeKind:
    """Register the fake kind for one test, and take it away again afterwards."""
    kind = FakeKind()
    monkeypatch.setitem(KINDS, "note", kind)
    return kind


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
