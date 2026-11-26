"""Limits per person on a hosted server (slice AJ, docs/person-limits.md): how much disk, how many kept builds, how many background runs at the same time.

The hosted version is meant to be open to any Google account, and a free server is small: without these, one person could fill its disk or keep both of its
workers busy. The OWNER (and local use) is never limited, a limit of 0 means "none", and one person's numbers never include another's.

The size of a person's space is measured on demand (their folder plus the folders of their own builds), not kept as a running counter: a counter drifts when a
write fails halfway or a folder is changed by hand, a measurement cannot.
"""

from __future__ import annotations

import os
import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import func, select

from ..db import LOCAL_USER_ID, BuildSession, Database, EvalRun

MB = 1024 * 1024


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


def folder_bytes(root: Path) -> int:
    """The size of the files under `root`. A link (a symbolic link, or a junction on Windows) is counted as the small thing it is and never followed, so a
    link inside someone's folder can neither make another folder count as theirs nor make this walk leave their space."""
    total = 0
    pending = [str(root)]
    while pending:
        try:
            with os.scandir(pending.pop()) as entries:
                for entry in entries:
                    try:
                        if entry.is_symlink() or getattr(entry, "is_junction", lambda: False)():
                            total += entry.stat(follow_symlinks=False).st_size
                        elif entry.is_dir(follow_symlinks=False):
                            pending.append(entry.path)
                        else:
                            total += entry.stat(follow_symlinks=False).st_size
                    except OSError:
                        continue
        except OSError:
            continue
    return total


def size_text(size: int) -> str:
    return f"{size / MB:.1f} MB" if size >= MB else f"{max(1, round(size / 1024))} KB" if size else "0 KB"


class PersonSpace:
    """What each person uses and what they may use. `folders(user)` says which folders on disk are that person's."""

    def __init__(self, db: Database, limits: PersonLimits, folders: Callable[[str], list[Path]] | None = None) -> None:
        self.db = db
        self.limits = limits
        self._folders = folders or (lambda user: [])
        # Held from the check until the work it admits is written down, so two requests at the same instant cannot both take the last place.
        self.lock = threading.Lock()

    def limited(self, user: str) -> bool:
        return self.limits.any and user != LOCAL_USER_ID

    # ---- measuring --------------------------------------------------------------------------------------------------

    def used(self, user: str) -> int:
        return sum(folder_bytes(folder) for folder in self._folders(user))

    def kept(self, user: str) -> int:
        with self.db.session() as s:
            return s.execute(select(func.count()).select_from(BuildSession).where(BuildSession.user_id == user)).scalar_one()

    def active(self, user: str) -> int:
        with self.db.session() as s:
            builds = s.execute(select(func.count()).select_from(BuildSession).where(BuildSession.user_id == user, BuildSession.status == "working")).scalar_one()
            runs = s.execute(select(func.count()).select_from(EvalRun).where(EvalRun.user_id == user, EvalRun.status == "working")).scalar_one()
        return builds + runs

    # ---- refusing ---------------------------------------------------------------------------------------------------

    def check_disk(self, user: str) -> None:
        if not self.limited(user) or not self.limits.disk_bytes:
            return
        used = self.used(user)
        if used >= self.limits.disk_bytes:
            raise LimitReached(
                "disk",
                f"You are using {size_text(used)} of the {size_text(self.limits.disk_bytes)} this server gives each person. "
                "Discard builds you no longer need, then try again. If that is not enough, ask whoever runs this server.",
            )

    def admit(self, user: str, *, new_build: bool = False, disk: bool = True) -> None:
        """Say yes (return) or raise LimitReached. Called with `self.lock` held, right before the work is written down."""
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
        if disk:
            self.check_disk(user)

    # ---- showing ----------------------------------------------------------------------------------------------------

    def view(self, user: str) -> dict:
        """What one person sees about their own space. The owner is told there are no limits."""
        if user == LOCAL_USER_ID:
            return {"mode": "owner", "message": "You run this server, so nothing limits you."}
        limits = self.limits
        return {
            "mode": "person",
            "disk": {"used": self.used(user), "limit": limits.disk_bytes},
            "builds": {"kept": self.kept(user), "limit": limits.max_builds},
            "active": {"now": self.active(user), "limit": limits.max_active},
        }
