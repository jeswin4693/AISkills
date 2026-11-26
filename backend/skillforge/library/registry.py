"""Whose library is whose.

The owner's library (the access token, Bearer, local mode) is the library the server was started with, exactly where it always was. Every other person has their
own, at `<data>/users/<their id>/library`, and the other kinds (agents, plugins, MCP servers) sit next to it as `Library.for_kind` already arranges. A person's folder
is named only by the random id this server made for them: nothing a person, an email or Google chose ever becomes part of a path, and anything that is not such an id
is refused before any path is built.
"""

from __future__ import annotations

import re

from ..db.models import LOCAL_USER_ID
from .package import LibraryError
from .store import Library

_UID = re.compile(r"[0-9a-f]{32}\Z")


class Libraries:
    def __init__(self, owner: Library) -> None:
        self.owner = owner
        self.users_root = owner.root.parent / "users"

    def for_user(self, user_id: object) -> Library:
        """The skill library of one person (their other kinds come from `.for_kind`). The owner's id is `local`; anything else must be a 32-character hex id."""
        if user_id == LOCAL_USER_ID:
            return self.owner
        if not isinstance(user_id, str) or not _UID.match(user_id):
            raise LibraryError("There is no library for that user.")
        return Library(self.users_root / user_id / "library", "skill")
