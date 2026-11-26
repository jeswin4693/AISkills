"""The people who signed in with Google, kept in the database.

The identity of a person is Google's account id (`sub`), which never changes, not their email, which can. Each person gets a random hex id of our own;
that id names their data (their rows and their library folder), so nothing a person or Google chooses ever becomes part of a path.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from .database import Database, now_text
from .models import LOCAL_USER_ID, UserRow

_HEX32 = re.compile(r"[0-9a-f]{32}\Z")

__all__ = ["LOCAL_USER_ID", "UserRecord", "UserStore"]


@dataclass(frozen=True)
class UserRecord:
    id: str
    email: str
    name: str
    picture: str
    joined: str = ""
    last_seen: str = ""
    blocked: bool = False  # turned off by the owner


def _record(row: UserRow) -> UserRecord:
    return UserRecord(row.id, row.email, row.name, row.picture, row.created_at, row.last_login_at, bool(row.blocked))


class UserStore:
    def __init__(self, db: Database) -> None:
        self.db = db

    def upsert_google(self, sub: str, email: str, name: str, picture: str = "") -> UserRecord:
        """The person for this Google account: made on the first sign-in, updated (email, name, picture, last sign-in) on later ones.
        Two first sign-ins at the same moment make one person: the database's own uniqueness settles it and the loser reads the winner's row."""
        for _ in range(2):
            try:
                with self.db.session() as s:
                    row = s.execute(select(UserRow).where(UserRow.google_sub == sub)).scalar_one_or_none()
                    stamp = now_text()
                    if row is None:
                        row = UserRow(id=uuid.uuid4().hex, google_sub=sub, email=email, name=name, picture=picture, created_at=stamp, last_login_at=stamp)
                        s.add(row)
                    else:
                        row.email, row.name, row.picture, row.last_login_at = email, name, picture, stamp
                    s.flush()
                    return _record(row)
            except IntegrityError:
                continue  # someone else made this account a moment ago: read it on the next turn
        raise RuntimeError("could not record the sign-in")

    def all(self, limit: int = 1000) -> list[UserRecord]:
        """Everyone who has signed in, TURNED-OFF people first (so one can always be found to turn back on), then the latest sign-in first. Capped, so a very open
        server cannot make one answer enormous: `count()` says how many there are in all."""
        with self.db.session() as s:
            rows = s.execute(select(UserRow).order_by(UserRow.blocked.desc(), UserRow.last_login_at.desc(), UserRow.id).limit(limit)).scalars().all()
            return [_record(r) for r in rows]

    def count(self) -> int:
        with self.db.session() as s:
            return s.execute(select(func.count()).select_from(UserRow)).scalar_one()

    def find_by_sub(self, sub: str) -> UserRecord | None:
        """The person for this Google account id, or None. Reads only: nothing about them is written."""
        with self.db.session() as s:
            row = s.execute(select(UserRow).where(UserRow.google_sub == sub)).scalar_one_or_none()
            return _record(row) if row else None

    def is_blocked(self, user_id: object) -> bool:
        """Is this person turned off? Asked on every request of a signed-in person, so it is one primary-key lookup. Not a person we made: not blocked."""
        if not isinstance(user_id, str) or not _HEX32.match(user_id):
            return False
        with self.db.session() as s:
            row = s.get(UserRow, user_id)
            return bool(row.blocked) if row else False

    def set_blocked(self, user_id: object, blocked: bool) -> bool:
        """Turn a person off or back on. False when there is no such person. Safe to repeat."""
        if not isinstance(user_id, str) or not _HEX32.match(user_id):
            return False
        with self.db.session() as s:
            row = s.get(UserRow, user_id)
            if row is None:
                return False
            row.blocked = blocked
            return True

    def get(self, user_id: object) -> UserRecord | None:
        """A person by id. Anything that is not an id we made (including the owner's `local`) finds nobody."""
        if not isinstance(user_id, str) or not _HEX32.match(user_id):
            return None
        with self.db.session() as s:
            row = s.get(UserRow, user_id)
            return _record(row) if row else None
