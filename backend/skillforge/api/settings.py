"""The Settings page over HTTP: what is set (never a key), and a save into the git-ignored `.env`.

Writing a file on the machine the server runs on is off in the hosted version, like installing into a folder. The body of a save is
read and checked by hand, so no error (FastAPI's own 422 would repeat the input) can repeat a key. A page on another site cannot call
this: the API's origin check already refuses a changing request from an origin it does not know.
"""

from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse

from ..builder.provider import env_provider, provider_status
from ..settings import SettingsError

HOSTED_OFF = (
    "Settings are turned off in the hosted version: a save would be written on the server. "
    "Set these options in the server's own environment instead (docs/hosting.md)."
)
MAX_BODY = 20_000  # bytes; the whole list of settings is far smaller


async def _changes(request: Request) -> dict:
    size = 0
    chunks: list[bytes] = []
    async for chunk in request.stream():
        size += len(chunk)
        if size > MAX_BODY:
            raise HTTPException(413, "That request is too large for the settings.")
        chunks.append(chunk)
    try:
        body = json.loads(b"".join(chunks))
    except (ValueError, RecursionError):  # UnicodeDecodeError is a ValueError; the text of the error would repeat the input
        raise HTTPException(400, "The request is not valid JSON.") from None
    changes = body.get("changes") if isinstance(body, dict) else None
    if not isinstance(changes, dict) or not changes:
        raise HTTPException(400, 'Send {"changes": {"NAME": "value"}}: a value to set, or null to remove a setting.')
    return changes


def settings_router() -> APIRouter:
    r = APIRouter()

    def local_only(request: Request) -> None:
        if request.app.state.hosted is not None:
            raise HTTPException(403, HOSTED_OFF)

    def current(request: Request) -> dict:
        view = request.app.state.env_settings.view()
        existing = request.app.state.builder
        view["status"] = provider_status(existing.provider_factory if existing else env_provider)  # never a key, no call to the model
        return view

    @r.get("/settings")
    def read(request: Request) -> dict:
        """The settings the page can change: whether each is set and where it comes from. Never a key, not even its end."""
        local_only(request)
        return current(request)

    @r.post("/settings")
    async def save(request: Request):
        """Set or remove settings in `.env`, all or nothing. It takes effect at once. Answers with the new state."""
        local_only(request)
        changes = await _changes(request)
        try:
            await run_in_threadpool(request.app.state.env_settings.apply, changes)
        except SettingsError as exc:
            return JSONResponse({"detail": str(exc), "problems": exc.problems}, status_code=400)
        return await run_in_threadpool(current, request)

    return r
