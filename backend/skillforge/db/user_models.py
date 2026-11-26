"""A person's own model, kept in the database: which provider and model, and their key as ciphertext (never in the clear).

Sealing and opening the key is builder/keybox.py; this only stores what it gives back. One row per person, found by the id we made for them.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from sqlalchemy import delete

from .database import Database, now_text
from .models import UserModelRow

_HEX32 = re.compile(r"[0-9a-f]{32}\Z")

__all__ = ["ModelStore", "StoredModel"]


@dataclass(frozen=True)
class StoredModel:
    provider: str
    model: str
    key_ciphertext: bytes
    key_nonce: bytes
    updated_at: str


def _stored(row: UserModelRow) -> StoredModel:
    return StoredModel(row.provider, row.model, bytes(row.key_ciphertext), bytes(row.key_nonce), row.updated_at)


class ModelStore:
    def __init__(self, db: Database) -> None:
        self.db = db

    def get(self, user_id: object) -> StoredModel | None:
        """A person's saved model. Anything that is not an id we made (the owner's `local` included) has none."""
        if not isinstance(user_id, str) or not _HEX32.match(user_id):
            return None
        with self.db.session() as s:
            row = s.get(UserModelRow, user_id)
            return _stored(row) if row else None

    def put(self, user_id: str, provider: str, model: str, ciphertext: bytes, nonce: bytes) -> StoredModel:
        """Save (or replace) a person's model. The owner and odd ids are refused: only a person who signed in has a row, and the database
        refuses an id that is not one of the people it knows."""
        if not isinstance(user_id, str) or not _HEX32.match(user_id):
            raise ValueError("A model can only be stored for a person this server made an id for.")
        with self.db.session() as s:
            row = s.get(UserModelRow, user_id)
            if row is None:
                row = UserModelRow(user_id=user_id, provider=provider, model=model, key_ciphertext=ciphertext, key_nonce=nonce, updated_at=now_text())
                s.add(row)
            else:
                row.provider, row.model, row.key_ciphertext, row.key_nonce, row.updated_at = provider, model, ciphertext, nonce, now_text()
            s.flush()
            return _stored(row)

    def delete(self, user_id: object) -> bool:
        """True when there was something to delete."""
        if not isinstance(user_id, str) or not _HEX32.match(user_id):
            return False
        with self.db.session() as s:
            return s.execute(delete(UserModelRow).where(UserModelRow.user_id == user_id)).rowcount == 1
