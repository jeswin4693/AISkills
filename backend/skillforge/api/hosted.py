"""The hosted version: a sign-in in front of the whole API.

Local use is unchanged and is the default: the API listens on 127.0.0.1 and has no sign-in. A hosted copy (SKILLFORGE_MODE=hosted)
can be reached from anywhere, and it drives paid model keys, so it needs three things this module provides:

- an access token (SKILLFORGE_ACCESS_TOKEN, at least 20 characters; the server refuses to start without one);
- a sign-in: the token is exchanged for a signed, expiring cookie (HttpOnly, SameSite=Lax, Secure behind https), or a script sends
  `Authorization: Bearer <token>`. The cookie holds no secret and is signed with a key derived from the token, so changing the token
  signs everyone out;
- a guard that locks sign-in for a minute after five wrong tries.

Everything under /api/ needs a sign-in except /api/health (for the platform's health check) and /api/auth/*.
"""

from __future__ import annotations

import hashlib
import hmac
import math
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from http.cookies import CookieError, SimpleCookie

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from .security import host_name

COOKIE = "skillforge_session"
MIN_TOKEN = 20
PUBLIC_PATHS = frozenset({"/api/health", "/api/auth/status", "/api/auth/login", "/api/auth/logout"})


class HostedConfigError(Exception):
    """The hosted version is set up wrongly. The server does not start."""


@dataclass(frozen=True)
class Hosted:
    token: str
    allowed_hosts: frozenset[str] = frozenset()  # host names (no port) besides loopback; "*" allows any
    secure_cookie: bool | None = None  # None: Secure when the request came over https
    session_days: int = 14

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> Hosted | None:
        """None for local use. Raises HostedConfigError for a hosted setup that is missing its token or is not understood."""
        mode = env.get("SKILLFORGE_MODE", "").strip().lower()
        if mode in ("", "local"):
            return None
        if mode != "hosted":
            raise HostedConfigError(f"SKILLFORGE_MODE is '{mode}'. Use 'hosted' for the hosted version, or leave it out for local use.")
        token = env.get("SKILLFORGE_ACCESS_TOKEN", "").strip()
        if not token:
            raise HostedConfigError(
                "SKILLFORGE_ACCESS_TOKEN is empty. The hosted version needs an access token of at least "
                f"{MIN_TOKEN} characters, because it can spend your model keys. Set it as a secret on the host, never in the repository."
            )
        if len(token) < MIN_TOKEN:
            raise HostedConfigError(f"SKILLFORGE_ACCESS_TOKEN is too short: use at least {MIN_TOKEN} characters (a long random string).")
        secure = env.get("SKILLFORGE_COOKIE_SECURE", "").strip().lower()
        return cls(
            token=token,
            allowed_hosts=frozenset(host_name(h) for h in env.get("SKILLFORGE_ALLOWED_HOSTS", "").split(",") if h.strip()),
            secure_cookie=True if secure in ("1", "true", "yes") else False if secure in ("0", "false", "no") else None,
        )


# ---- the session cookie and the bearer token ------------------------------------------------------------------


def _sign(hosted: Hosted, message: str) -> str:
    key = hashlib.sha256(b"skillforge-session-v1\0" + hosted.token.encode("utf-8")).digest()
    return hmac.new(key, message.encode("utf-8"), hashlib.sha256).hexdigest()


def make_cookie(hosted: Hosted, now: float | None = None) -> str:
    expiry = int((time.time() if now is None else now) + hosted.session_days * 86400)
    message = f"v1.{expiry}"
    return f"{message}.{_sign(hosted, message)}"


def valid_cookie(hosted: Hosted, value: object, now: float | None = None) -> bool:
    if not isinstance(value, str):
        return False
    parts = value.split(".")
    if len(parts) != 3 or parts[0] != "v1" or not parts[1].isdigit():
        return False
    if not hmac.compare_digest(parts[2].encode("utf-8"), _sign(hosted, f"v1.{parts[1]}").encode("utf-8")):
        return False
    return int(parts[1]) > (time.time() if now is None else now)


def bearer_ok(hosted: Hosted, header: str | None) -> bool:
    if not header or not header.startswith("Bearer "):
        return False
    return hmac.compare_digest(header[7:].encode("utf-8"), hosted.token.encode("utf-8"))


def is_signed_in(hosted: Hosted, headers: Mapping[str, str]) -> bool:
    """`headers` has lower-case names. A valid cookie or a correct bearer token is enough."""
    if bearer_ok(hosted, headers.get("authorization")):
        return True
    try:
        jar = SimpleCookie(headers.get("cookie", ""))
    except CookieError:
        return False
    morsel = jar.get(COOKIE)
    return morsel is not None and valid_cookie(hosted, morsel.value)


class LoginGuard:
    """After five wrong tokens in five minutes, sign-in is locked for a minute. One guard for the whole server on purpose: it cannot
    be dodged by changing an address, and a long random token cannot be guessed at five tries a minute."""

    def __init__(
        self, max_failures: int = 5, window_s: float = 300.0, lock_s: float = 60.0, clock: Callable[[], float] = time.monotonic
    ) -> None:
        self.max_failures, self.window_s, self.lock_s, self.clock = max_failures, window_s, lock_s, clock
        self._lock = threading.Lock()
        self._times: list[float] = []
        self._locked_until = 0.0

    def failed(self) -> None:
        with self._lock:
            now = self.clock()
            self._times = [t for t in self._times if now - t < self.window_s] + [now]
            if len(self._times) >= self.max_failures:
                self._locked_until = now + self.lock_s
                self._times = []  # a fresh set of tries when the lock ends

    def succeeded(self) -> None:
        with self._lock:
            self._times, self._locked_until = [], 0.0

    def locked_for(self) -> int:
        """Whole seconds left on the lock, or 0."""
        with self._lock:
            remaining = self._locked_until - self.clock()
            return math.ceil(remaining) if remaining > 0 else 0


# ---- the middleware and the routes ----------------------------------------------------------------------------


class AuthMiddleware:
    """A plain ASGI middleware: 401 before the request reaches any route under /api/ that is not public."""

    def __init__(self, app, hosted: Hosted) -> None:
        self.app = app
        self.hosted = hosted

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http" or scope["method"] == "OPTIONS" or not scope["path"].startswith("/api/") or scope["path"] in PUBLIC_PATHS:
            await self.app(scope, receive, send)
            return
        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope["headers"]}
        if is_signed_in(self.hosted, headers):
            await self.app(scope, receive, send)
            return
        response = JSONResponse({"detail": "Sign in first."}, status_code=401)
        await response(scope, receive, send)


class LoginBody(BaseModel):
    token: str = Field(max_length=500)


def _secure(hosted: Hosted, request: Request) -> bool:
    if hosted.secure_cookie is not None:
        return hosted.secure_cookie
    proto = request.headers.get("x-forwarded-proto", "").split(",")[0].strip().lower() or request.url.scheme
    return proto == "https"


def auth_router(hosted: Hosted | None, guard: LoginGuard) -> APIRouter:
    r = APIRouter()

    @r.get("/auth/status")
    def status(request: Request) -> dict:
        if hosted is None:
            return {"required": False, "authenticated": True}
        return {"required": True, "authenticated": is_signed_in(hosted, dict(request.headers))}

    @r.post("/auth/login")
    def login(body: LoginBody, request: Request) -> JSONResponse:
        if hosted is None:
            raise HTTPException(400, "This server has no sign-in (local mode).")
        wait = guard.locked_for()
        if wait:
            return JSONResponse({"detail": f"Too many wrong tries. Try again in {wait} seconds."}, status_code=429, headers={"Retry-After": str(wait)})
        if not hmac.compare_digest(body.token.encode("utf-8"), hosted.token.encode("utf-8")):
            guard.failed()
            return JSONResponse({"detail": "That is not the access token."}, status_code=401)
        guard.succeeded()
        response = JSONResponse({"authenticated": True})
        response.set_cookie(
            COOKIE, make_cookie(hosted), max_age=hosted.session_days * 86400, httponly=True, samesite="lax",
            secure=_secure(hosted, request), path="/",
        )
        return response

    @r.post("/auth/logout")
    def logout() -> JSONResponse:
        response = JSONResponse({"authenticated": False})
        response.delete_cookie(COOKIE, path="/")
        return response

    return r
