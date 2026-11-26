"""The hosted version: a sign-in in front of the whole API, and who is signed in.

Local use is unchanged and is the default: the API listens on 127.0.0.1 and has no sign-in. A hosted copy (SKILLFORGE_MODE=hosted)
can be reached from anywhere, and it drives paid model keys, so it needs three things this module provides:

- an access token (SKILLFORGE_ACCESS_TOKEN, at least 20 characters; the server refuses to start without one). It is the OWNER's way in, a script's
  Bearer token, and the key that signs every session, so changing it signs everyone out;
- a sign-in: the token is exchanged for a signed, expiring cookie (HttpOnly, SameSite=Lax, Secure behind https), or "Sign in with Google" (below);
- a guard that locks sign-in for a minute after five wrong tries.

Sign in with Google is for letting other people use the same server. It is on when SKILLFORGE_GOOGLE_CLIENT_ID is set, and it needs
SKILLFORGE_ALLOWED_EMAILS too (addresses, `@domain` entries, or `*` for any Google account): signing in proves who someone is, not that they are welcome.
Each person is then a separate user whose data nobody else can see. The owner (the access token, Bearer, and local mode) is the user `local`.

Everything under /api/ needs a sign-in except /api/health (for the platform's health check) and /api/auth/*.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import math
import re
import secrets
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from http.cookies import CookieError, SimpleCookie
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from ..db.models import LOCAL_USER_ID
from .google_auth import GoogleAuthError, verify_credential
from .security import host_name

COOKIE = "skillforge_session"
NONCE_COOKIE = "skillforge_nonce"
NONCE_SECONDS = 600
NONCE_PATH = "/api/auth"  # the nonce cookie is only ever sent to the sign-in routes
MIN_TOKEN = 20
PUBLIC_PATHS = frozenset({"/api/health", "/api/auth/status", "/api/auth/login", "/api/auth/logout", "/api/auth/nonce", "/api/auth/google"})
_UID = re.compile(r"[0-9a-f]{32}\Z")
_CLIENT_ID = re.compile(r"[0-9A-Za-z._-]+\.apps\.googleusercontent\.com\Z")
_EMAIL_ENTRY = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+\Z")
_DOMAIN_ENTRY = re.compile(r"@[^@\s]+\.[^@\s]+\Z")


class HostedConfigError(Exception):
    """The hosted version is set up wrongly. The server does not start."""


@dataclass(frozen=True)
class User:
    """Who is asking. `id` names their data; `email` is only what they signed in with."""

    id: str
    email: str = ""


LOCAL_USER = User(LOCAL_USER_ID)  # local mode, the access token and Bearer: the one person who used the app before accounts, and whose data that is


@dataclass(frozen=True)
class Hosted:
    token: str
    allowed_hosts: frozenset[str] = frozenset()  # host names (no port) besides loopback; "*" allows any
    secure_cookie: bool | None = None  # None: Secure when the request came over https
    session_days: int = 14
    google_client_id: str = ""  # public; "" means there is no Sign in with Google
    allowed_emails: frozenset[str] = frozenset()  # lower-case: "a@b.c", "@domain", or "*"

    @property
    def google(self) -> bool:
        return bool(self.google_client_id)

    def email_allowed(self, email: str) -> bool:
        """Is this address on the list? Exact address or its whole domain (not a subdomain), whatever the letter case; `*` lets any address in, but never nothing."""
        address = email.strip().lower()
        if not address or address.count("@") != 1:
            return False
        return "*" in self.allowed_emails or address in self.allowed_emails or "@" + address.split("@", 1)[1] in self.allowed_emails

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
        client_id = env.get("SKILLFORGE_GOOGLE_CLIENT_ID", "").strip()
        emails = frozenset(e.strip().lower() for e in env.get("SKILLFORGE_ALLOWED_EMAILS", "").split(",") if e.strip())
        if client_id:
            if client_id.upper().startswith("GOCSPX-"):
                raise HostedConfigError(
                    "SKILLFORGE_GOOGLE_CLIENT_ID holds what looks like a Google client SECRET. This app never needs the secret: use the Client ID, "
                    "which ends in .apps.googleusercontent.com, and keep the secret out of every file."
                )
            if not _CLIENT_ID.match(client_id):
                raise HostedConfigError("SKILLFORGE_GOOGLE_CLIENT_ID does not look like a Google Client ID: it ends in .apps.googleusercontent.com and has no spaces.")
            if not emails:
                raise HostedConfigError(
                    "SKILLFORGE_GOOGLE_CLIENT_ID is set but SKILLFORGE_ALLOWED_EMAILS is empty. Signing in with Google proves who someone is, not that they are welcome: "
                    "list who may sign in (addresses, @domain entries), or write * to allow any Google account."
                )
            for entry in sorted(emails):
                if entry != "*" and not (_EMAIL_ENTRY.match(entry) or _DOMAIN_ENTRY.match(entry)):
                    raise HostedConfigError(f"'{entry}' in SKILLFORGE_ALLOWED_EMAILS is not an email address, an @domain, or *.")
        elif emails:
            raise HostedConfigError("SKILLFORGE_ALLOWED_EMAILS is set but SKILLFORGE_GOOGLE_CLIENT_ID is not: set the Google Client ID, or remove the list.")
        return cls(
            token=token,
            allowed_hosts=frozenset(host_name(h) for h in env.get("SKILLFORGE_ALLOWED_HOSTS", "").split(",") if h.strip()),
            secure_cookie=True if secure in ("1", "true", "yes") else False if secure in ("0", "false", "no") else None,
            google_client_id=client_id,
            allowed_emails=emails,
        )


# ---- the session cookie and the bearer token ------------------------------------------------------------------


def _sign(hosted: Hosted, message: str) -> str:
    key = hashlib.sha256(b"skillforge-session-v1\0" + hosted.token.encode("utf-8")).digest()
    return hmac.new(key, message.encode("utf-8"), hashlib.sha256).hexdigest()


def _b64(text: str) -> str:
    return base64.urlsafe_b64encode(text.encode("utf-8")).decode("ascii").rstrip("=")


def _unb64(text: str) -> str:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4)).decode("utf-8")


def _now(now: float | None) -> float:
    return time.time() if now is None else now


def make_cookie(hosted: Hosted, now: float | None = None, user: User | None = None) -> str:
    """A signed session. For the owner it is the original `v1.<expiry>` cookie. For a person it is `v2.<id>.<email>.<expiry>`, so every request knows who it is
    (and can check that the email is still on the list); the id must be one we made, so nothing odd is ever signed."""
    expiry = int(_now(now) + hosted.session_days * 86400)
    if user is None or user.id == LOCAL_USER.id:
        message = f"v1.{expiry}"
    else:
        if not _UID.match(user.id):
            raise ValueError("A session can only be made for the owner or for a person id this server made.")
        message = f"v2.{user.id}.{_b64(user.email)}.{expiry}"
    return f"{message}.{_sign(hosted, message)}"


def read_cookie(hosted: Hosted, value: object, now: float | None = None) -> User | None:
    """Who a session cookie is for, or None: not signed with this token, expired, garbage, or (for a person) no longer on the allow-list."""
    if not isinstance(value, str) or len(value) > 1000:
        return None
    parts = value.split(".")
    current = _now(now)
    if parts[0] == "v1" and len(parts) == 3:
        if not parts[1].isdigit() or not hmac.compare_digest(parts[2].encode("utf-8"), _sign(hosted, f"v1.{parts[1]}").encode("utf-8")):
            return None
        return LOCAL_USER if int(parts[1]) > current else None
    if parts[0] == "v2" and len(parts) == 5 and hosted.google:
        _, uid, email_text, expiry, signature = parts
        if not (_UID.match(uid) and expiry.isdigit() and hmac.compare_digest(signature.encode("utf-8"), _sign(hosted, ".".join(parts[:4])).encode("utf-8"))):
            return None
        if int(expiry) <= current:
            return None
        try:
            email = _unb64(email_text)
        except (ValueError, UnicodeError):
            return None
        return User(uid, email) if hosted.email_allowed(email) else None
    return None


def valid_cookie(hosted: Hosted, value: object, now: float | None = None) -> bool:
    return read_cookie(hosted, value, now) is not None


def make_nonce(hosted: Hosted, now: float | None = None) -> tuple[str, str]:
    """(a nonce for the page to hand to Google, the signed cookie that remembers it). The ticket Google returns carries the nonce, and it is accepted only
    in the browser that holds this cookie: a ticket stolen from one browser is no use in another."""
    nonce = secrets.token_urlsafe(24)
    message = f"n1.{nonce}.{int(_now(now) + NONCE_SECONDS)}"
    return nonce, f"{message}.{_sign(hosted, message)}"


def read_nonce(hosted: Hosted, value: object, now: float | None = None) -> str:
    """The nonce a nonce cookie holds, or "" when it is not ours, not signed with this token, or older than ten minutes."""
    if not isinstance(value, str) or len(value) > 200:
        return ""
    parts = value.split(".")
    if len(parts) != 4 or parts[0] != "n1" or not parts[2].isdigit() or not re.fullmatch(r"[A-Za-z0-9_-]{16,64}", parts[1]):
        return ""
    if not hmac.compare_digest(parts[3].encode("utf-8"), _sign(hosted, ".".join(parts[:3])).encode("utf-8")):
        return ""
    return parts[1] if int(parts[2]) > _now(now) else ""


def bearer_ok(hosted: Hosted, header: str | None) -> bool:
    if not header or not header.startswith("Bearer "):
        return False
    return hmac.compare_digest(header[7:].encode("utf-8"), hosted.token.encode("utf-8"))


def identify(hosted: Hosted, headers: Mapping[str, str]) -> User | None:
    """Who is asking. `headers` has lower-case names. The Bearer token is the owner; a valid cookie is whoever it was made for."""
    if bearer_ok(hosted, headers.get("authorization")):
        return LOCAL_USER
    try:
        jar = SimpleCookie(headers.get("cookie", ""))
    except CookieError:
        return None
    morsel = jar.get(COOKIE)
    return read_cookie(hosted, morsel.value) if morsel is not None else None


def is_signed_in(hosted: Hosted, headers: Mapping[str, str]) -> bool:
    """`headers` has lower-case names. A valid cookie or a correct bearer token is enough."""
    return identify(hosted, headers) is not None


def current_user(request: Request) -> User:
    """Who this request is for: the person the sign-in middleware identified, or the owner (local mode has no sign-in and one person)."""
    return getattr(request.state, "user", None) or LOCAL_USER


class LoginGuard:
    """After five wrong tokens in five minutes, sign-in is locked for a minute. One guard for the whole server on purpose: it cannot
    be dodged by changing an address, and a long random token cannot be guessed at five tries a minute. Wrong Google tickets count too."""

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
    """A plain ASGI middleware: 401 before the request reaches any route under /api/ that is not public. A request that gets through carries who it is
    (`request.state.user`), so no route has to work it out again."""

    def __init__(self, app, hosted: Hosted) -> None:
        self.app = app
        self.hosted = hosted

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http" or scope["method"] == "OPTIONS" or not scope["path"].startswith("/api/") or scope["path"] in PUBLIC_PATHS:
            await self.app(scope, receive, send)
            return
        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope["headers"]}
        user = identify(self.hosted, headers)
        if user is not None:
            scope.setdefault("state", {})["user"] = user
            await self.app(scope, receive, send)
            return
        response = JSONResponse({"detail": "Sign in first."}, status_code=401)
        await response(scope, receive, send)


class LoginBody(BaseModel):
    token: str = Field(max_length=500)


class GoogleBody(BaseModel):
    credential: str = Field(min_length=1, max_length=8000)  # a Google ticket is about 1 to 2 KB


def _secure(hosted: Hosted, request: Request) -> bool:
    if hosted.secure_cookie is not None:
        return hosted.secure_cookie
    proto = request.headers.get("x-forwarded-proto", "").split(",")[0].strip().lower() or request.url.scheme
    return proto == "https"


def auth_router(hosted: Hosted | None, guard: LoginGuard, *, keys: Callable[[str], Any] | None = None, users: Callable[[], Any] | None = None) -> APIRouter:
    """`keys(ticket)` returns the public key that signed a Google ticket (the real one asks Google; a test hands in its own).
    `users()` returns the store of people (made on first use, so a server that never uses Google never opens the database for it)."""
    r = APIRouter()

    @r.get("/auth/status")
    def status(request: Request) -> dict:
        if hosted is None:
            return {"required": False, "authenticated": True, "google_client_id": "", "user": None, "owner_login": False}
        who = identify(hosted, dict(request.headers))
        person = None
        if who is not None and who.id != LOCAL_USER.id and users is not None:
            record = users().get(who.id)
            person = {"email": who.email, "name": record.name if record else who.email.split("@")[0], "picture": record.picture if record else ""}
        return {"required": True, "authenticated": who is not None, "google_client_id": hosted.google_client_id, "user": person, "owner_login": True}

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

    @r.get("/auth/nonce")
    def nonce(request: Request) -> JSONResponse:
        """A fresh nonce for one sign-in attempt, remembered in a cookie the page cannot read."""
        if hosted is None or not hosted.google:
            raise HTTPException(400, "Sign in with Google is not set up on this server.")
        value, cookie = make_nonce(hosted)
        response = JSONResponse({"nonce": value})
        response.set_cookie(NONCE_COOKIE, cookie, max_age=NONCE_SECONDS, httponly=True, samesite="lax", secure=_secure(hosted, request), path=NONCE_PATH)
        return response

    @r.post("/auth/google")
    def google(body: GoogleBody, request: Request) -> JSONResponse:
        if hosted is None or not hosted.google or keys is None or users is None:
            raise HTTPException(400, "Sign in with Google is not set up on this server.")
        wait = guard.locked_for()
        if wait:
            return JSONResponse({"detail": f"Too many wrong tries. Try again in {wait} seconds."}, status_code=429, headers={"Retry-After": str(wait)})
        try:
            who = verify_credential(
                body.credential, client_id=hosted.google_client_id, nonce=read_nonce(hosted, request.cookies.get(NONCE_COOKIE)), key_for=keys,
            )
        except GoogleAuthError as exc:
            if exc.code == "keys_unavailable":  # Google could not be reached: nobody guessed anything, so it is not counted
                return JSONResponse({"detail": str(exc)}, status_code=503)
            guard.failed()
            return JSONResponse({"detail": str(exc)}, status_code=401)
        if not hosted.email_allowed(who.email):
            return JSONResponse(
                {"detail": "That Google account is not allowed on this server. Ask the person who runs it to add your email address."}, status_code=403
            )
        record = users().upsert_google(who.sub, who.email, who.name, who.picture)
        guard.succeeded()
        response = JSONResponse({"authenticated": True, "user": {"email": record.email, "name": record.name, "picture": record.picture}})
        response.set_cookie(
            COOKIE, make_cookie(hosted, user=User(record.id, record.email)), max_age=hosted.session_days * 86400, httponly=True, samesite="lax",
            secure=_secure(hosted, request), path="/",
        )
        response.delete_cookie(NONCE_COOKIE, path=NONCE_PATH)  # used once
        return response

    @r.post("/auth/logout")
    def logout() -> JSONResponse:
        response = JSONResponse({"authenticated": False})
        response.delete_cookie(COOKIE, path="/")
        response.delete_cookie(NONCE_COOKIE, path=NONCE_PATH)
        return response

    return r
