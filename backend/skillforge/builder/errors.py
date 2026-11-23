"""What the builder tells a person when it cannot do what was asked. Each is something they can act on."""

from __future__ import annotations


class BuilderError(Exception):
    """Something the person can act on."""


class SessionNotFound(BuilderError):
    pass


class WrongState(BuilderError):
    """The session is not at the step this action belongs to (or someone else just moved it)."""


class BadRequest(BuilderError):
    pass


class UpstreamError(BuilderError):
    """A service the request depends on (GitHub) could not be reached or refused. The request was fine: trying again later can help."""
