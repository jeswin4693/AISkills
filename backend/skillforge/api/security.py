"""Keep the local API local: a web page on some other site must not be able to drive it.

Two attacks matter for a server on 127.0.0.1:
- DNS rebinding: a hostile site's name is pointed at 127.0.0.1, so the browser treats the API as that site's own.
  The request still carries the hostile name in `Host`, so a Host that is not a loopback name is refused.
- Cross-site requests: a page on another origin asks the browser to POST to localhost. A browser always sends an
  `Origin` on such a request, so a request that changes something and names an origin we do not know is refused.
  A request with no `Origin` comes from a command-line client, not from a web page, and is allowed.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterable

LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "[::1]"}
DEFAULT_ORIGINS = ("http://localhost:3000", "http://127.0.0.1:3000")
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def host_name(header: str) -> str:
    """The host part of a Host header, without the port."""
    header = header.strip().lower()
    if header.startswith("["):  # [::1]:8000
        return header[: header.find("]") + 1]
    return header.rsplit(":", 1)[0] if ":" in header else header


def allowed_origins(extra: Iterable[str] | None = None) -> list[str]:
    """The UI's own addresses, plus any in SKILLFORGE_UI_ORIGINS (comma separated) or `extra`."""
    env = [o.strip().rstrip("/") for o in os.environ.get("SKILLFORGE_UI_ORIGINS", "").split(",") if o.strip()]
    more = [o.rstrip("/") for o in (extra or [])]
    return list(dict.fromkeys([*DEFAULT_ORIGINS, *env, *more]))


class LocalOnlyMiddleware:
    """A plain ASGI middleware: it answers 403 before the request reaches any route."""

    def __init__(self, app, origins: Iterable[str]) -> None:
        self.app = app
        self.origins = {o.rstrip("/").lower() for o in origins}

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope["headers"]}
        refusal = None
        if host_name(headers.get("host", "")) not in LOOPBACK_HOSTS:
            refusal = "This API answers only on localhost."
        elif scope["method"] not in SAFE_METHODS and "origin" in headers and headers["origin"].rstrip("/").lower() not in self.origins:
            refusal = "This request comes from a page this API does not trust."
        if refusal:
            body = json.dumps({"detail": refusal}).encode()
            await send({"type": "http.response.start", "status": 403, "headers": [
                (b"content-type", b"application/json"), (b"content-length", str(len(body)).encode()),
            ]})
            await send({"type": "http.response.body", "body": body})
            return
        await self.app(scope, receive, send)
