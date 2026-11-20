"""Library findings from the independent review of the plugin builder: names that are the same file once spelling is ignored,
and a backup that must never overwrite the person's original file."""

from __future__ import annotations

import io
import zipfile
from datetime import datetime, timezone

import pytest
from test_library import NAME as SKILL, write_skill

from skillforge.library import Library, import_skill, install_skill, read_zip_bytes

NOW = datetime(2026, 11, 20, 12, 0, 0, tzinfo=timezone.utc)


def zip_of(names_and_text: dict[str, str]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, text in names_and_text.items():
            archive.writestr(name, text)
    return buffer.getvalue()


SKILL_MD = f"---\nname: {SKILL}\ndescription: Reads a file and says what it holds.\n---\n# Demo\n"


@pytest.mark.parametrize("first,second", [
    ("SKILL.md", "skill.md"), (".claude-plugin/plugin.json", ".Claude-Plugin/Plugin.json"), ("refs/a.md", "./refs/a.md"),
    ("refs/a.md", "refs//a.md"), ("refs/A.md", "REFS/a.md"),
])
def test_two_names_that_are_the_same_file_once_spelling_is_ignored_are_refused(first, second):
    source = read_zip_bytes(zip_of({first: SKILL_MD, second: "other\n"}), "x.zip")
    assert any(kind == "duplicate" for kind, _ in source.problems), source.problems


def test_different_files_are_not_mistaken_for_duplicates():
    source = read_zip_bytes(zip_of({"SKILL.md": SKILL_MD, "refs/a.md": "one\n", "refs/b.md": "two\n", "Refs2/a.md": "three\n"}), "x.zip")
    assert source.problems == []


def library_with_skill(tmp_path) -> Library:
    lib = Library(tmp_path / "library")
    assert not import_skill(write_skill(tmp_path / SKILL), lib).refused
    return lib


def test_two_forced_installs_in_the_same_second_keep_both_backups_of_a_skill_folder(tmp_path):
    lib = library_with_skill(tmp_path)
    target = tmp_path / "skills"
    install_skill(lib, SKILL, None, target)
    (target / SKILL / "mine.txt").write_text("my first edit", encoding="utf-8")
    install_skill(lib, SKILL, None, target, force=True, now=NOW)
    (target / SKILL / "mine.txt").write_text("my second edit", encoding="utf-8")
    install_skill(lib, SKILL, None, target, force=True, now=NOW)  # the same second: must not overwrite or crash
    texts = sorted(p.read_text(encoding="utf-8") for p in lib.backups.glob(f"{SKILL}-*/mine.txt"))
    assert texts == ["my first edit", "my second edit"]


def test_two_forced_installs_in_the_same_second_keep_both_backups_of_an_agent_file(tmp_path):
    lib = Library(tmp_path / "library")
    agents = lib.for_kind("agent")
    agent = b"---\nname: demo-agent\ndescription: Reviews a diff.\ntools: Read, Grep, Glob\n---\n\nYou are a reviewer.\n"
    agents.add("demo-agent", {"AGENT.md": agent}, source_kind="test", source_label="test")
    target = tmp_path / "agents"
    install_skill(agents, "demo-agent", None, target)
    (target / "demo-agent.md").write_text("my first edit", encoding="utf-8")
    install_skill(agents, "demo-agent", None, target, force=True, now=NOW)
    (target / "demo-agent.md").write_text("my second edit", encoding="utf-8")
    install_skill(agents, "demo-agent", None, target, force=True, now=NOW)
    assert sorted(p.read_text(encoding="utf-8") for p in agents.backups.glob("demo-agent-*.md")) == ["my first edit", "my second edit"]
