"""The environment every `git` call of the graph and of the evidence checks runs in.

Everything SkillForge keeps for a person (a downloaded copy of a repository, a build, a library) lives inside the data folder. When that folder
itself sits inside a git work tree, `git -C <copy> ls-files` or `git log` would climb out of the copy, find the PARENT repository and report its
files and history as if they were the copy's. `GIT_CEILING_DIRECTORIES` tells git not to look at, or above, the listed folders, so a folder inside
the data folder is only ever its own repository, or none.

A folder the person points at themselves (not inside the data folder) is left exactly as it was: a subfolder of a repository must keep working.
"""

from __future__ import annotations

import os
from pathlib import Path

from .store import data_dir


def git_env(root: Path | str) -> dict[str, str] | None:
    """`None` (run git in the environment as it is) unless `root` is strictly inside the data folder; then a copy of the environment with
    `GIT_CEILING_DIRECTORIES` set to the data folder, keeping any ceiling already set. Both paths are resolved (links, `..`, short names) and compared
    without regard to case on a disk that ignores it."""
    data = os.path.realpath(data_dir())
    folder = os.path.realpath(root)
    try:
        inside = os.path.commonpath([os.path.normcase(data), os.path.normcase(folder)]) == os.path.normcase(data)
    except ValueError:  # another drive, or one path relative and one absolute: not inside
        return None
    if not inside or os.path.normcase(folder) == os.path.normcase(data):
        return None
    env = dict(os.environ)
    existing = env.get("GIT_CEILING_DIRECTORIES", "")
    env["GIT_CEILING_DIRECTORIES"] = existing + os.pathsep + data if existing else data
    return env
