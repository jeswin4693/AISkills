"""Deleting a library entry (slice AK, task 4): every version and its backups, never anything else, never following a link.

The tests build real libraries on disk, and for links use a symbolic link where this account may create one and a directory junction on Windows (which needs
no special right), so they run on this machine.
"""

from __future__ import annotations

import os
import subprocess
import threading
import time
from pathlib import Path

import pytest

from skillforge.library import Library, LibraryError, NotFound
from skillforge.library import store
from skillforge.library import remove as remove_module
from skillforge.library.remove import remove_tree

STAMP = "20261127-101500"


def add(lib: Library, name: str, versions: int = 1) -> None:
    body_name = "AGENT.md" if lib.kind == "agent" else "SKILL.md"
    for n in range(versions):
        lib.add(name, {body_name: f"{name} v{n + 1}\n".encode()}, source_kind="test", source_label="t")


def tree(path: Path) -> list[str]:
    return sorted(str(p.relative_to(path)) for p in path.rglob("*"))


def make_link(link: Path, target: Path) -> None:
    """A symbolic link, or on Windows a directory junction; the test is skipped when neither can be made."""
    try:
        link.symlink_to(target, target_is_directory=True)
        return
    except OSError:
        pass
    if os.name == "nt":
        done = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)], capture_output=True)
        if done.returncode == 0:
            return
    pytest.skip("this account cannot create symbolic links")


def outside(tmp_path: Path) -> Path:
    folder = tmp_path / "outside"
    folder.mkdir()
    (folder / "precious.txt").write_text("keep me", encoding="utf-8")
    return folder


@pytest.fixture
def lib(tmp_path) -> Library:
    return Library(tmp_path / "library")


def test_delete_removes_every_version_and_only_that_entry(lib):
    add(lib, "foo", versions=3)
    add(lib, "bar")
    before = lib.read("bar")
    report = lib.delete("foo")
    assert (report.name, report.versions, report.leftover) == ("foo", 3, False)
    assert lib.names() == ["bar"] and lib.versions("foo") == []
    assert lib.read("bar")[1] == before[1]


@pytest.mark.parametrize("name", ["", ".", "..", "../x", "a/b", "a\\b", "Foo", "FOO", "foo bar", "foo..", "x" * 65, "foo\x00", None, 5])
def test_an_odd_name_deletes_nothing(tmp_path, lib, name):
    add(lib, "foo")
    # real folders that a name which was NOT checked would reach: beside the library (`../x`), below it (`a/b`), and the library's own parent (`..`)
    (tmp_path / "x" / "v1").mkdir(parents=True)
    (lib.root / "a" / "b" / "v1").mkdir(parents=True)
    before = tree(tmp_path)
    with pytest.raises(LibraryError):
        lib.delete(name)
    assert tree(tmp_path) == before


def test_a_missing_entry_is_not_found(lib):
    with pytest.raises(NotFound):
        lib.delete("nothing-here")


def test_a_link_inside_an_entry_is_refused_and_the_target_untouched(tmp_path, lib):
    add(lib, "foo")
    target = outside(tmp_path)
    make_link(lib.root / "foo" / "v1" / "sneaky", target)
    with pytest.raises(LibraryError, match="link"):
        lib.delete("foo")
    assert (target / "precious.txt").read_text(encoding="utf-8") == "keep me"
    assert "foo" in lib.names()


def test_an_entry_that_is_itself_a_link_is_refused_and_the_target_untouched(tmp_path, lib):
    target = outside(tmp_path)
    lib.root.mkdir(parents=True)
    make_link(lib.root / "foo", target)
    with pytest.raises(LibraryError, match="link"):
        lib.delete("foo")
    assert (target / "precious.txt").read_text(encoding="utf-8") == "keep me"


def make_backups(lib: Library) -> Path:
    backups = lib.backups
    for folder in (f"foo-{STAMP}", f"foo-{STAMP}-2", f"foo-bar-{STAMP}", f"foo-2-{STAMP}", "foo-notastamp", f"other-{STAMP}"):
        (backups / folder).mkdir(parents=True)
        (backups / folder / "SKILL.md").write_text("a copy", encoding="utf-8")
    (backups / f"foo-{STAMP}.md").write_text("an agent copy", encoding="utf-8")
    return backups


def test_only_the_backups_of_that_name_go(lib):
    add(lib, "foo")
    backups = make_backups(lib)
    report = lib.delete("foo")
    assert (report.backups, report.leftover) == (3, False)
    assert sorted(p.name for p in backups.iterdir()) == sorted([f"foo-bar-{STAMP}", f"foo-2-{STAMP}", "foo-notastamp", f"other-{STAMP}"])


def test_a_backup_folder_holding_a_link_is_removed_without_touching_the_target(tmp_path, lib):
    add(lib, "foo")
    backups = make_backups(lib)
    target = outside(tmp_path)
    make_link(backups / f"foo-{STAMP}" / "linked", target)
    report = lib.delete("foo")
    assert report.backups == 3 and not (backups / f"foo-{STAMP}").exists()
    assert (target / "precious.txt").read_text(encoding="utf-8") == "keep me"


def test_a_backup_that_is_itself_a_link_is_left_alone_and_reported(tmp_path, lib):
    add(lib, "foo")
    backups = make_backups(lib)
    target = outside(tmp_path)
    make_link(backups / f"foo-{STAMP[:-1]}9", target)  # named like a backup of foo, but a link
    report = lib.delete("foo")
    assert report.leftover is True and report.backups == 3
    assert (target / "precious.txt").read_text(encoding="utf-8") == "keep me" and (backups / f"foo-{STAMP[:-1]}9").exists()


def test_another_kind_and_another_person_are_untouched(tmp_path, lib):
    add(lib, "foo")
    agents = lib.for_kind("agent")
    add(agents, "foo")
    (agents.backups / f"foo-{STAMP}.md").parent.mkdir(parents=True, exist_ok=True)
    (agents.backups / f"foo-{STAMP}.md").write_text("an agent copy", encoding="utf-8")
    person = Library(tmp_path / "users" / ("a" * 32) / "library")
    add(person, "foo")
    lib.delete("foo")
    assert agents.names() == ["foo"] and (agents.backups / f"foo-{STAMP}.md").exists()
    assert person.names() == ["foo"] and person.read("foo")[0].version == 1


def test_a_delete_waits_for_a_writer_holding_the_library_lock(lib):
    add(lib, "foo")
    done = threading.Event()
    with store._ADD_LOCK:
        worker = threading.Thread(target=lambda: (lib.delete("foo"), done.set()))
        worker.start()
        time.sleep(0.3)
        assert not done.is_set() and "foo" in lib.names()
    worker.join(10)
    assert done.is_set() and lib.names() == []


def test_an_entry_with_a_damaged_manifest_can_still_be_deleted(lib):
    add(lib, "foo", versions=2)
    (lib.root / "foo" / "v2" / "manifest.json").write_text("{ not json", encoding="utf-8")
    report = lib.delete("foo")
    assert report.versions == 2 and lib.names() == []


def test_a_delete_that_cannot_rename_deletes_nothing(monkeypatch, lib):
    add(lib, "foo")

    def refuse(self, target):
        raise PermissionError("in use")

    monkeypatch.setattr(Path, "rename", refuse)
    with pytest.raises(LibraryError, match="in use by another program"):
        lib.delete("foo")
    monkeypatch.undo()
    assert lib.names() == ["foo"] and lib.read("foo")[0].version == 1


def test_what_could_not_be_removed_is_reported_and_already_out_of_the_library(monkeypatch, lib):
    add(lib, "foo")
    monkeypatch.setattr(remove_module.shutil, "rmtree", lambda *a, **k: None)  # nothing can be removed
    report = lib.delete("foo")
    assert report.leftover is True and lib.names() == [] and lib.versions("foo") == []


def test_a_stale_hidden_folder_is_swept_by_the_next_delete(lib):
    add(lib, "foo")
    add(lib, "bar")
    stale = lib.root / f".deleting-{'a' * 32}"
    stale.mkdir()
    (stale / "left.txt").write_text("x", encoding="utf-8")
    lib.delete("bar")
    assert not stale.exists() and lib.names() == ["foo"]


def test_remove_tree_refuses_a_link_itself_and_leaves_its_target_and_the_link(tmp_path):
    root, target = tmp_path / "root", outside(tmp_path)
    root.mkdir()
    make_link(root / "linked", target)
    with pytest.raises(LibraryError, match="link"):
        remove_tree(root / "linked", root)
    with pytest.raises(LibraryError, match="link"):
        remove_tree(root / "linked", root, allow_inner_links=True)
    assert (target / "precious.txt").read_text(encoding="utf-8") == "keep me" and (root / "linked").exists()


def test_remove_tree_refuses_a_path_outside_its_root(tmp_path):
    root, elsewhere = tmp_path / "root", tmp_path / "x"
    root.mkdir()
    elsewhere.mkdir()
    (elsewhere / "f.txt").write_text("keep", encoding="utf-8")
    with pytest.raises(LibraryError):
        remove_tree(elsewhere, root)
    with pytest.raises(LibraryError):
        remove_tree(root, root)  # the root itself is not "strictly inside" it
    assert (elsewhere / "f.txt").exists() and root.exists()
