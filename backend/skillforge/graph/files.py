"""Find the source files of a repository."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path, PurePosixPath

LANGUAGES = {
    ".py": "python",
    ".ts": "typescript",
    ".mts": "typescript",
    ".cts": "typescript",
    ".tsx": "tsx",
    ".js": "javascript",
    ".jsx": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
}

SKIP_DIRS = {
    ".git", "node_modules", ".venv", "venv", "env", "__pycache__", "dist", "build", "out", ".next",
    ".tox", ".mypy_cache", ".pytest_cache", ".ruff_cache", "target", "coverage", ".ria", "workspace-data",
    "site-packages",
}
MAX_BYTES = 1_000_000


def language_of(path: str) -> str | None:
    name = PurePosixPath(path).name.lower()
    if name.endswith((".d.ts", ".min.js", ".min.mjs")):
        return None
    return LANGUAGES.get(PurePosixPath(path).suffix.lower())


def is_test_path(path: str) -> bool:
    p = PurePosixPath(path.lower())
    name = p.name
    if any(part in {"tests", "test", "__tests__", "spec", "specs"} for part in p.parts[:-1]):
        return True
    return (
        name == "conftest.py"
        or name.startswith("test_")
        or name.endswith(("_test.py", "_test.go"))
        or ".test." in name
        or ".spec." in name
    )


def _git_files(root: Path) -> list[str] | None:
    try:
        inside = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--is-inside-work-tree"],
            capture_output=True, text=True, timeout=30,
        )
        if inside.returncode != 0 or inside.stdout.strip() != "true":
            return None
        out = subprocess.run(
            ["git", "-c", "core.quotepath=false", "-C", str(root), "ls-files", "-z", "--cached", "--others",
             "--exclude-standard"],
            capture_output=True, timeout=120,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if out.returncode != 0:
        return None
    return [p for p in out.stdout.decode("utf-8", errors="replace").split("\0") if p]


def _walk_files(root: Path) -> list[str]:
    found: list[str] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
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
        if any(part in SKIP_DIRS for part in PurePosixPath(rel).parts[:-1]):
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
