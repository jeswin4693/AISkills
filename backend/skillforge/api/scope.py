"""Whose request is this, and whose library. Every route that touches a person's data asks here, so there is one place to look at when asking
"can one person reach another's data?"."""

from __future__ import annotations

from fastapi import Request

from ..library import Library
from .hosted import current_user


def user_id(request: Request) -> str:
    """The id of the person this request is for: the owner (`local`) in local mode and for the access token, otherwise the person who signed in."""
    return current_user(request).id


def user_library(request: Request) -> Library:
    """That person's skill library (their other kinds come from `.for_kind`)."""
    return request.app.state.libraries.for_user(user_id(request))
