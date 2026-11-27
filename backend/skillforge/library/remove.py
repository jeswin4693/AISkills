"""Removing files and folders without ever following a link (slice AK, docs/data-removal.md).

A delete is the one thing here that cannot be taken back, so the rules are strict and live in one place:

* what is removed must lie STRICTLY inside the folder it belongs to (compared by real path, so `..`, short names and capitals do not get round it);
* a symbolic link, or on Windows a directory junction, is never followed. The thing being removed is refused if it IS one; a link INSIDE it is refused too, unless the caller
  says links inside are expected (a backup of a folder someone installed over can hold links, and `shutil.rmtree` removes a link as a link and leaves its target alone);
* the answer says whether anything is left, so a caller can report it instead of claiming it is gone.

Nothing here builds a path from text: callers pass paths they made from a checked name or an id this server made.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

from .package import LibraryError


def is_link(path: Path) -> bool:
    """A symbolic link, or a directory junction (Windows). A missing path is not a link."""
    if path.is_symlink():
        return True
    junction = getattr(os.path, "isjunction", None)  # Python 3.12 and later; before that a junction cannot be told from a folder this way
    return bool(junction and junction(path))


def has_link(path: Path) -> bool:
    """Whether `path` is a link, or holds one anywhere below it. A link is never walked into: it is found in its parent's listing first."""
    if is_link(path):
        return True
    if not path.is_dir():
        return False
    for folder, folders, files in os.walk(path, followlinks=False):
        for name in (*folders, *files):
            if is_link(Path(folder) / name):
                return True
    return False


def _real(path: Path) -> str:
    return os.path.normcase(os.path.realpath(path))


def remove_tree(path: Path, inside: Path, *, allow_inner_links: bool = False) -> bool:
    """Remove `path` (a file or a folder). Raises `LibraryError`, and removes nothing, when `path` is itself a link, is not strictly inside `inside`, or (unless
    `allow_inner_links`) holds a link. Returns True when nothing of it is left; False when something could not be removed (a program holding a file, say)."""
    path = Path(path)
    if is_link(path):
        raise LibraryError("It is a link, so it was left alone.")
    root, here = _real(inside), _real(path)
    if here == root or not here.startswith(root.rstrip(os.sep) + os.sep):
        raise LibraryError("It is not inside the folder it belongs to, so it was left alone.")
    if not path.exists():
        return True
    if not allow_inner_links and has_link(path):
        raise LibraryError("It holds a link, so it was left alone.")
    if path.is_dir():
        shutil.rmtree(path, ignore_errors=True)  # removes a link inside as a link; never follows it
    else:
        try:
            path.unlink()
        except OSError:
            pass
    return not path.exists()
