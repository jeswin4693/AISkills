"""Erasing a person's data (slice AK, docs/data-removal.md). The owner's act, for an account that is already turned off.

What goes: the person's folder (their library of every kind and its backups), their builds (rows, jobs and folders), suggestion runs, Testing Lab runs, behaviour scans and their saved model key.
What stays, on purpose:

* **the account row**: the person is still turned off afterwards, and if the owner turns them back on they start empty;
* **every usage row (`model_calls`)**: they hold counts and timings only, and a person's daily allowance on the server's model is counted from them, so erasing them would let
  someone erase themselves and start again with a fresh allowance. They are tied to a build by a foreign key that CASCADES, so the builds' rows must not be deleted until
  those ids are emptied (the same thing `Builder.discard` does, and the bug its review found).

The build folders are removed first and the rows after, in one transaction; the person's own folder follows once that has committed (a path made from their id, so it can always be
found again). A disk that will not give a build folder up keeps THAT build's row, so erasing again finds it, and `files_left` says so; nothing is ever reported gone while it is not. Nothing is
built from text: the folders are named by ids this server made, checked as 32 hex characters, and each removal goes through `remove_tree`, which never follows a link.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from sqlalchemy import delete, select, update

from ..db import LOCAL_USER_ID, BuildSession, EvalRun, Job, ModelCall, ScanRun, SuggestRun
from ..db.models import UserModelRow
from ..db.users import UserStore
from ..library.package import LibraryError
from ..library.remove import remove_tree
from .errors import BadRequest, WrongState

if TYPE_CHECKING:
    from .service import Builder

_HEX32 = re.compile(r"[0-9a-f]{32}\Z")
_CHUNK = 400  # ids in one `IN (...)`: far below SQLite's limit on variables


@dataclass(frozen=True)
class EraseReport:
    builds: int
    suggestion_runs: int
    lab_runs: int
    scan_runs: int
    key_removed: bool
    files_left: bool  # something could not be removed from the disk (it no longer belongs to anything)


def _gone(path: Path, inside: Path) -> bool:
    """Remove one folder; True when nothing of it is left. A link inside is removed as a link and never followed; a folder that is itself a link is left alone."""
    try:
        return remove_tree(path, inside, allow_inner_links=True)
    except LibraryError:
        return False


def erase_person(builder: "Builder", user_id: str) -> EraseReport:
    """Erase one person's data. Refused (409) unless they are turned off and have nothing running; the owner and anything that is not an id this server made are refused (400)."""
    if user_id == LOCAL_USER_ID:
        raise BadRequest("The owner cannot be erased: they run this server.")
    if not isinstance(user_id, str) or not _HEX32.match(user_id):
        raise BadRequest("There is no such person.")
    person = UserStore(builder.db).get(user_id)
    if person is None:
        raise BadRequest("There is no such person.")
    if not person.blocked:
        raise WrongState("Turn this person off first: erasing is only for an account that is off.")
    if builder.working_for(user_id):
        raise WrongState("This person has work running. Wait for it to finish, then erase.")

    with builder.db.session() as s:
        ids = list(s.execute(select(BuildSession.id).where(BuildSession.user_id == user_id)).scalars())
    # The build folders go FIRST, while their rows still say whose they are. A folder the disk will not give up keeps its row: that row is the only way to find the
    # folder again, so the next erase tries it once more (deleting the row first lost the folder for good, and a second erase then said "Their files are gone").
    erasable = [sid for sid in ids if not _HEX32.match(sid) or _gone(builder.builds_root / sid, builder.builds_root)]  # anything not made by this server is not touched
    files_left = len(erasable) < len(ids)
    with builder.db.session() as s:
        for start in range(0, len(erasable), _CHUNK):
            chunk = erasable[start:start + _CHUNK]
            # Usage rows are kept: first let go of the builds they were tied to, or the foreign key's cascade would delete them with the builds.
            s.execute(update(ModelCall).where(ModelCall.session_id.in_(chunk)).values(session_id=None))
            s.execute(delete(Job).where(Job.session_id.in_(chunk)))
            s.execute(delete(BuildSession).where(BuildSession.id.in_(chunk)))
        suggestions = s.execute(delete(SuggestRun).where(SuggestRun.user_id == user_id)).rowcount
        labs = s.execute(delete(EvalRun).where(EvalRun.user_id == user_id)).rowcount
        scans = s.execute(delete(ScanRun).where(ScanRun.user_id == user_id)).rowcount
        key = s.execute(delete(UserModelRow).where(UserModelRow.user_id == user_id)).rowcount == 1

    if builder.library_for is not None:
        try:
            folder = builder.library_for(user_id).root.parent  # <data>/users/<id>: the library of every kind and its backups
        except LibraryError:
            folder = None
        if folder is not None and folder.name == user_id:
            files_left |= not _gone(folder, folder.parent)
        elif folder is not None:
            files_left = True  # not laid out as expected: nothing was guessed at, and it is said
    builder.space.forget(user_id)
    return EraseReport(len(erasable), suggestions, labs, scans, key, files_left)
