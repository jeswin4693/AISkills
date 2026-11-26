"""A person's own model over HTTP (slice AI, docs/per-person-keys.md): what applies to them, and saving, removing and trying a model and key of their own.

A key goes IN, once, in a POST body, and never comes out: no response, error or log holds it, not even its end. A body that fails validation is answered by
the app's own 422 handler, which says where and why and never what; a value the rules refuse is a 400 naming the field. Only GET, POST and DELETE exist: the
API's CORS policy allows nothing else. The owner has no personal model: their model is the server's own settings, and the routes say so.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from ..builder.model_access import ModelAccess, ModelAccessError
from ..settings import SettingsError
from .builds import get_builder
from .scope import user_id


class ModelBody(BaseModel):
    # Generous on purpose: the RULES (settings/rules.check_person_model) say what is too long, with a message that names the field. These only stop a huge body.
    provider: str = Field(max_length=100)
    model: str = Field(max_length=400)
    key: str = Field(max_length=2000)


def me_router() -> APIRouter:
    r = APIRouter()

    def access(request: Request) -> ModelAccess:
        return get_builder(request.app).access

    @r.get("/me/model")
    def mine(request: Request) -> dict:
        """What applies to this person: the owner, their own model (provider, model, whether a key is saved and when), the shared model with today's allowance, or none."""
        return access(request).my_model(user_id(request))

    @r.post("/me/model")
    def save(body: ModelBody, request: Request):
        """Keep this person's model and key (sealed). 400 names each field the rules refuse; 403 for the owner."""
        try:
            return access(request).save(user_id(request), body.provider, body.model, body.key)
        except SettingsError as exc:
            return JSONResponse({"detail": str(exc), "problems": exc.problems}, status_code=400)
        except ModelAccessError as exc:
            raise HTTPException(403, str(exc)) from None

    @r.delete("/me/model")
    def forget(request: Request) -> dict:
        """Remove this person's model and key. Safe to repeat."""
        try:
            return access(request).remove(user_id(request))
        except ModelAccessError as exc:
            raise HTTPException(403, str(exc)) from None

    @r.post("/me/model/test")
    def test(request: Request) -> dict:
        """One tiny call to THEIR OWN model, so they can see the key works. The server's model is never tried for a person."""
        return access(request).test(user_id(request))

    return r
