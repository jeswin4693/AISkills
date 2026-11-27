"""Git never looks above the data folder (slice AK, task 2b).

A copy of a GitHub repository, a person's build and a person's library all live inside the data folder. If that folder sits inside a git work tree
(a data folder set to `./data` in a checkout, say), `git -C <copy> ls-files` and `git log` would find the PARENT repository and report its files and
its history as if they were the copy's. `git_env` tells git, with GIT_CEILING_DIRECTORIES, not to look up past the data folder. A folder a person
points at themselves is untouched: a subfolder of a repository must keep working.

These tests run the real `git`.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from skillforge.evidence import git_dirty, git_head
from skillforge.graph import files as graph_files
from skillforge.graph import history
from skillforge.graph.gitenv import git_env


def make_repo(tmp_path: Path) -> Path:
    """A real repository holding `top.py` and, below it, a folder shaped like a snapshot: data/github/k/s/proj/a.py."""
    repo = tmp_path / "repo"
    folder = repo / "data" / "github" / "k" / "s" / "proj"
    folder.mkdir(parents=True)
    (folder / "a.py").write_text("x = 1\n", encoding="utf-8")
    (repo / "top.py").write_text("y = 1\n", encoding="utf-8")
    for args in (["init", "-q"], ["add", "-A"], ["-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false", "commit", "-q", "-m", "m"]):
        subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)
    return repo


def test_a_folder_inside_the_data_folder_does_not_see_the_repository_above_it(tmp_path, monkeypatch):
    repo = make_repo(tmp_path)
    monkeypatch.setenv("SKILLFORGE_DATA_DIR", str(repo / "data"))
    folder = repo / "data" / "github" / "k" / "s" / "proj"
    assert graph_files._git_files(folder) is None
    assert git_head(folder) is None
    assert git_dirty(folder) is False
    assert history.collect(folder, set())[0] is None


def test_a_folder_the_person_points_at_inside_a_repository_still_works(tmp_path, monkeypatch):
    repo = make_repo(tmp_path)
    monkeypatch.setenv("SKILLFORGE_DATA_DIR", str(tmp_path / "elsewhere"))
    folder = repo / "data" / "github" / "k" / "s" / "proj"
    assert "a.py" in graph_files._git_files(folder)
    assert git_head(folder) is not None
    assert history.collect(folder, {"a.py"})[0] == 1


def test_git_env_is_for_folders_strictly_inside_the_data_folder_however_they_are_written(tmp_path, monkeypatch):
    data = tmp_path / "data"
    (data / "github" / "x").mkdir(parents=True)
    monkeypatch.setenv("SKILLFORGE_DATA_DIR", str(data))
    assert git_env(tmp_path) is None  # above it
    assert git_env(data) is None  # the data folder itself is not "inside" it
    assert git_env(tmp_path / "other") is None  # beside it
    env = git_env(data / "github" / "x")
    assert env is not None
    assert os.path.normcase(env["GIT_CEILING_DIRECTORIES"]) == os.path.normcase(os.path.realpath(data))
    assert git_env(data / "github" / ".." / "github" / "x") is not None  # a path written with `..`
    if os.name == "nt":  # a disk that ignores case: the same folder in capitals is the same folder
        assert git_env(str(data / "github" / "x").upper()) is not None


def test_git_env_keeps_a_ceiling_the_person_already_had(tmp_path, monkeypatch):
    data = tmp_path / "data"
    (data / "x").mkdir(parents=True)
    monkeypatch.setenv("SKILLFORGE_DATA_DIR", str(data))
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path / "theirs"))
    env = git_env(data / "x")
    assert env is not None
    parts = [os.path.normcase(p) for p in env["GIT_CEILING_DIRECTORIES"].split(os.pathsep)]
    assert os.path.normcase(str(tmp_path / "theirs")) in parts and os.path.normcase(os.path.realpath(data)) in parts
