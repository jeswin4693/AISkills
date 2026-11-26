"""The owner's People page over HTTP (slice AJ, docs/person-limits.md): who has signed in, what each uses, and a reversible switch to turn an account off.

Only the owner (the access token, a Bearer header) may use these routes; a signed-in person gets 403. Turning an account off signs that person out on their very next
request (the block is checked on every request) and refuses a new sign-in; nothing they made is deleted. Only GET and POST exist: the API's CORS policy allows
GET, POST and DELETE only. A local server has no accounts and says so.
"""

from __future__ import annotations

import re

from fastapi import APIRouter, HTTPException, Request

from ..db import LOCAL_USER_ID
from ..db.users import UserStore
from .builds import get_builder
from .scope import user_id

_HEX32 = re.compile(r"[0-9a-f]{32}\Z")
OWNER_ONLY = "Only the person who runs this server can do this."


def admin_router() -> APIRouter:
    r = APIRouter()

    def owner_only(request: Request) -> None:
        if user_id(request) != LOCAL_USER_ID:
            raise HTTPException(403, OWNER_ONLY)

    def person_store(request: Request, who: str) -> UserStore:
        """The store of people, once this is the owner asking about a person this server made. Everything else is refused before any lookup."""
        owner_only(request)
        if getattr(request.app.state, "hosted", None) is None:
            raise HTTPException(400, "This server has no accounts: it is run on your own computer, where you are the only person.")
        if who == LOCAL_USER_ID:
            raise HTTPException(400, "The owner cannot be turned off: they run this server.")
        if not _HEX32.match(who):
            raise HTTPException(404, "There is no such person.")
        store = UserStore(get_builder(request.app).db)
        if store.get(who) is None:
            raise HTTPException(404, "There is no such person.")
        return store

    @r.get("/admin/people")
    def people(request: Request) -> dict:
        """Everyone who has signed in, newest sign-in first, with what each uses. Never a key and never which model."""
        owner_only(request)
        if getattr(request.app.state, "hosted", None) is None:
            return {"hosted": False, "people": []}
        builder = get_builder(request.app)
        rows = []
        for person in UserStore(builder.db).all():
            rows.append({
                "id": person.id, "name": person.name, "email": person.email, "joined": person.joined, "last_seen": person.last_seen, "blocked": person.blocked,
                "builds": builder.space.kept(person.id), "disk_used": builder.space.used_for_display(person.id), "active": builder.space.active(person.id),
                "calls_today": {"server": builder.access.used_today(person.id), "own": builder.access.used_today(person.id, "own")},
                "has_key": builder.access.store.get(person.id) is not None,
            })
        return {"hosted": True, "people": rows}

    @r.post("/admin/people/{who}/block")
    def block(who: str, request: Request) -> dict:
        """Turn this person's account off. Safe to repeat. Their data is kept."""
        person_store(request, who).set_blocked(who, True)
        return {"blocked": True}

    @r.post("/admin/people/{who}/unblock")
    def unblock(who: str, request: Request) -> dict:
        """Turn it back on: the same session works again. Safe to repeat."""
        person_store(request, who).set_blocked(who, False)
        return {"blocked": False}

    return r
