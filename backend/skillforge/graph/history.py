"""Git history: how often files change, and which files change together."""

from __future__ import annotations

import itertools
import subprocess
from pathlib import Path

from .gitenv import git_env

MAX_COMMITS = 1500
MAX_FILES_PER_COMMIT = 40  # bigger commits (mass renames, formatting) say nothing about coupling
MIN_SHARED = 2
MAX_PAIRS = 4000


def collect(
    root: Path, indexed: set[str]
) -> tuple[int | None, dict[str, int], list[tuple[str, str, int, float]]]:
    """Returns (commits read or None outside git, churn per file, co-change pairs).

    A pair is (a, b, commits that touched both, shared / the smaller of the two files' commit counts).
    """
    try:
        out = subprocess.run(
            ["git", "-c", "core.quotepath=false", "-C", str(root), "log", "--no-merges", "--relative",
             "--name-only", "--pretty=format:%x00", "-n", str(MAX_COMMITS)],
            capture_output=True, timeout=120, env=git_env(root),
        )
    except (OSError, subprocess.SubprocessError):
        return None, {}, []
    if out.returncode != 0:
        return None, {}, []

    churn: dict[str, int] = {}
    pairs: dict[tuple[str, str], int] = {}
    commits = 0
    for block in out.stdout.decode("utf-8", errors="replace").split("\0"):
        names = [line.strip() for line in block.splitlines() if line.strip()]
        if not names:
            continue
        commits += 1
        files = sorted({n for n in names if n in indexed})
        for f in files:
            churn[f] = churn.get(f, 0) + 1
        if 2 <= len(names) <= MAX_FILES_PER_COMMIT:
            for a, b in itertools.combinations(files, 2):
                pairs[(a, b)] = pairs.get((a, b), 0) + 1

    co = [
        (a, b, n, round(n / min(churn[a], churn[b]), 3))
        for (a, b), n in pairs.items()
        if n >= MIN_SHARED
    ]
    co.sort(key=lambda t: (-t[2], -t[3], t[0], t[1]))
    return commits, churn, co[:MAX_PAIRS]
