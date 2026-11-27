"""Find the source files of a repository."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path, PurePosixPath

from .gitenv import git_env
from .languages import language_of_path

SKIP_DIRS = {
    ".git", "node_modules", ".venv", "venv", "env", "__pycache__", "dist", "build", "out", ".next",
    ".tox", ".mypy_cache", ".pytest_cache", ".ruff_cache", "target", "coverage", ".ria", "workspace-data",
    "site-packages", "vendor", "obj", ".gradle", ".idea", "Pods", ".dart_tool", ".build",
}
# Usually build output, but a Python package with one of these names is source code (this project's own
# `skillforge/build/` is one). Real output never has an `__init__.py` directly inside: setuptools puts it under `build/lib/`.
PACKAGE_NAMED = {"build", "dist", "out"}
MAX_BYTES = 1_000_000


def language_of(path: str) -> str | None:
    """Grammar name of a source file (python, java, go, ...), or None when it is not a programming language we know."""
    return language_of_path(path)


def is_test_path(path: str) -> bool:
    p = PurePosixPath(path.lower())
    name = p.name
    if any(part in {"tests", "test", "__tests__", "spec", "specs"} for part in p.parts[:-1]):
        return True
    return (
        name == "conftest.py"
        or name.startswith("test_")
        or name.endswith((
            "_test.py", "_test.go", "_test.rs", "_spec.rb", "test.java", "tests.java", "test.kt", "tests.kt",
            "tests.cs", "test.cs", "test.php", "_test.c", "_test.cpp", "_test.cc",
        ))
        or ".test." in name
        or ".spec." in name
    )


# Folders of tests and of test scaffolding: end-to-end suites, fixtures, mocks. `is_test_path` is left as it is (test counts, risk and coverage all
# depend on it); this wider rule is only for deciding that an import written in such a folder says nothing about how the project works.
TEST_SUPPORT_DIRS = frozenset({"e2e", "test", "tests", "__tests__", "spec", "specs", "fixtures", "mocks", "__mocks__", "testing"})


def is_test_support_path(path: str) -> bool:
    """Whether a file sits inside a folder of tests or test scaffolding (an end-to-end suite, fixtures, mocks, a test server). Only a whole folder
    name counts: `e2e-tools/` does not, and neither does a file that is itself called `e2e.py`. Case does not matter."""
    return any(part.lower() in TEST_SUPPORT_DIRS for part in path.split("/")[:-1])


def _git_files(root: Path) -> list[str] | None:
    env = git_env(root)  # a folder inside the data folder never sees a repository above it
    try:
        inside = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--is-inside-work-tree"],
            capture_output=True, text=True, timeout=30, env=env,
        )
        if inside.returncode != 0 or inside.stdout.strip() != "true":
            return None
        out = subprocess.run(
            ["git", "-c", "core.quotepath=false", "-C", str(root), "ls-files", "-z", "--cached", "--others",
             "--exclude-standard"],
            capture_output=True, timeout=120, env=env,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if out.returncode != 0:
        return None
    return [p for p in out.stdout.decode("utf-8", errors="replace").split("\0") if p]


def _is_package(folder: Path) -> bool:
    return (folder / "__init__.py").is_file()


def _skipped(root: Path, folders: tuple[str, ...]) -> bool:
    """True when a file sits under a folder that is skipped (dependencies, caches, build output)."""
    for i, part in enumerate(folders):
        if part in SKIP_DIRS and not (part in PACKAGE_NAMED and _is_package(root.joinpath(*folders[: i + 1]))):
            return True
    return False


def _walk_files(root: Path) -> list[str]:
    found: list[str] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS or (d in PACKAGE_NAMED and _is_package(Path(dirpath, d)))]
        for name in filenames:
            rel = Path(dirpath, name).relative_to(root).as_posix()
            found.append(rel)
    return found


def discover(root: Path, focus: str | None = None) -> list[str]:
    """Relative POSIX paths of the parseable source files under `root`, sorted."""
    candidates = _git_files(root)
    if candidates is None:
        candidates = _walk_files(root)
    focus_prefix = (focus or "").strip().replace("\\", "/").strip("/")
    kept: list[str] = []
    for rel in candidates:
        rel = rel.replace("\\", "/")
        if language_of(rel) is None:
            continue
        if _skipped(root, PurePosixPath(rel).parts[:-1]):
            continue
        if focus_prefix and not (rel == focus_prefix or rel.startswith(focus_prefix + "/")):
            continue
        full = root / rel
        try:
            if not full.is_file() or full.stat().st_size > MAX_BYTES:
                continue
        except OSError:
            continue
        kept.append(rel)
    return sorted(set(kept))
