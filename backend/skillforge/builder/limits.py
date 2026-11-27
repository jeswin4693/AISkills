"""Limits per person on a hosted server (slice AJ, docs/person-limits.md): how much disk, how many kept builds, how many background runs at the same time.

The hosted version is meant to be open to any Google account, and a free server is small: without these, one person could fill its disk or keep both of its
workers busy. The OWNER (and local use) is never limited, a limit of 0 means "none", and one person's numbers never include another's.

The size of a person's space is measured on demand (their folder plus the folders of their own builds), not kept as a running counter: a counter drifts when a
write fails halfway or a folder is changed by hand, a measurement cannot. Every file and folder is charged at least one 4 KB block (what it really takes on a
disk), so a million one-byte files cannot hide under a limit counted in bytes. A walk stops as soon as the limit is passed, so a huge folder costs a bounded
amount to look at, and it is never done while holding the lock the other people's build starts need.
"""

from __future__ import annotations

import os
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import func, select

from ..db import LOCAL_USER_ID, BuildSession, Database, EvalRun, ScanRun

MB = 1024 * 1024
BLOCK = 4096  # what the smallest file or folder takes on a disk
CACHE_SECONDS = 5.0  # how long a measurement may be shown again (the space card, the People page); admission always measures fresh


@dataclass(frozen=True)
class PersonLimits:
    disk_bytes: int = 0  # 0 = no cap, for each of the three
    max_builds: int = 0  # builds a person may keep (discarding one makes room)
    max_active: int = 0  # background runs working at the same time: builds and Testing Lab runs together (the job pool is small and shared)

    @property
    def any(self) -> bool:
        return bool(self.disk_bytes or self.max_builds or self.max_active)


class LimitReached(Exception):
    """A limit was reached. The message is safe to show the person: it names their own numbers and what to do, never anybody else's."""

    def __init__(self, limit: str, message: str) -> None:
        super().__init__(message)
        self.limit = limit  # "disk", "builds" or "active"


def charged(size: int) -> int:
    """What a file of this many bytes takes on a disk: whole blocks, and at least one (an empty file still takes an entry)."""
    return -(-max(size, 1) // BLOCK) * BLOCK


def folder_bytes(root: Path, stop_at: int | None = None) -> int:
    """What the files and folders under `root` take on a disk: each file in whole blocks, each folder and each link one block. A link (a symbolic link, or a
    junction on Windows) is never followed, so a link inside someone's folder can neither make another folder count as theirs nor make this walk leave their
    space. With `stop_at` the walk ends as soon as the total reaches it: "at least this much" is all a limit needs to know."""
    total = 0
    pending = [str(root)]
    while pending:
        try:
            with os.scandir(pending.pop()) as entries:
                for entry in entries:
                    try:
                        if entry.is_symlink() or getattr(entry, "is_junction", lambda: False)():
                            total += BLOCK
                        elif entry.is_dir(follow_symlinks=False):
                            total += BLOCK
                            pending.append(entry.path)
                        else:
                            total += charged(entry.stat(follow_symlinks=False).st_size)
                    except OSError:
                        continue
                    if stop_at is not None and total >= stop_at:
                        return total
        except OSError:
            continue
    return total


def size_text(size: int) -> str:
    return f"{size / MB:.1f} MB" if size >= MB else f"{max(1, round(size / 1024))} KB" if size else "0 KB"


class PersonSpace:
    """What each person uses and what they may use. `folders(user)` says which folders on disk are that person's."""

    def __init__(
        self, db: Database, limits: PersonLimits, folders: Callable[[str], list[Path]] | None = None, clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.db = db
        self.limits = limits
        self._folders = folders or (lambda user: [])
        self._clock = clock
        self._seen: dict[str, tuple[float, int]] = {}  # the last measurement of each person, for display only
        # Held from the check until the work it admits is written down, so two requests at the same instant cannot both take the last place. It guards the
        # database counts only (which are quick): the disk is measured BEFORE it is taken, so one person's huge folder never holds up anybody else's start.
        self.lock = threading.Lock()

    def limited(self, user: str) -> bool:
        return self.limits.any and user != LOCAL_USER_ID

    # ---- measuring --------------------------------------------------------------------------------------------------

    def used(self, user: str, stop_at: int | None = None) -> int:
        """What this person's files take. With `stop_at`, "at least this much" is enough and the walk ends there."""
        total = 0
        for folder in self._folders(user):
            total += folder_bytes(folder, None if stop_at is None else max(1, stop_at - total))
            if stop_at is not None and total >= stop_at:
                break
        return total

    def forget(self, user: str) -> None:
        """Drop the remembered measurement of a person's disk (their data was just erased, so the next display must measure again)."""
        self._seen.pop(user, None)

    def used_for_display(self, user: str) -> int:
        """The same, for showing (the space card, the People page): a measurement up to a few seconds old is reused, so repeating the request costs nothing. A person at
        their limit is shown as at least the limit. Admission never uses this: it measures fresh."""
        now = self._clock()
        seen = self._seen.get(user)
        if seen is not None and now - seen[0] < CACHE_SECONDS:
            return seen[1]
        value = self.used(user, stop_at=self.limits.disk_bytes or None)
        self._seen[user] = (now, value)
        return value

    def kept(self, user: str) -> int:
        with self.db.session() as s:
            return s.execute(select(func.count()).select_from(BuildSession).where(BuildSession.user_id == user)).scalar_one()

    def active(self, user: str) -> int:
        with self.db.session() as s:
            builds = s.execute(select(func.count()).select_from(BuildSession).where(BuildSession.user_id == user, BuildSession.status == "working")).scalar_one()
            runs = s.execute(select(func.count()).select_from(EvalRun).where(EvalRun.user_id == user, EvalRun.status == "working")).scalar_one()
            scans = s.execute(select(func.count()).select_from(ScanRun).where(ScanRun.user_id == user, ScanRun.status == "working")).scalar_one()
        return builds + runs + scans

    # ---- refusing ---------------------------------------------------------------------------------------------------

    def check_disk(self, user: str) -> None:
        if not self.limited(user) or not self.limits.disk_bytes:
            return
        used = self.used(user, stop_at=self.limits.disk_bytes)
        if used >= self.limits.disk_bytes:
            raise LimitReached(
                "disk",
                f"You are using {size_text(used)} of the {size_text(self.limits.disk_bytes)} this server gives each person. "
                "Discard builds you no longer need, then try again. If that is not enough, ask whoever runs this server.",
            )

    def admit(self, user: str, *, new_build: bool = False) -> None:
        """Say yes (return) or raise LimitReached, for the counts kept in the database (builds kept, runs working). Called with `self.lock` held, right before the
        work is written down. The disk is NOT looked at here: `check_disk` is called before the lock is taken, because walking a big folder must never hold
        the lock other people's starts need. (An action can therefore overshoot the disk limit by what one action writes: a few MB, never a runaway.)"""
        if not self.limited(user):
            return
        limits = self.limits
        if new_build and limits.max_builds and self.kept(user) >= limits.max_builds:
            raise LimitReached(
                "builds",
                f"You are keeping {limits.max_builds} builds, the most this server keeps for one person. Discard builds you no longer need, then start again.",
            )
        if limits.max_active and self.active(user) >= limits.max_active:
            raise LimitReached(
                "active",
                f"You already have {limits.max_active} runs working at once, the most this server allows. Wait for one to finish, then try again.",
            )

    # ---- showing ----------------------------------------------------------------------------------------------------

    def view(self, user: str) -> dict:
        """What one person sees about their own space. The owner is told there are no limits."""
        if user == LOCAL_USER_ID:
            return {"mode": "owner", "message": "You run this server, so nothing limits you."}
        limits = self.limits
        return {
            "mode": "person",
            "disk": {"used": self.used_for_display(user), "limit": limits.disk_bytes},
            "builds": {"kept": self.kept(user), "limit": limits.max_builds},
            "active": {"now": self.active(user), "limit": limits.max_active},
        }
