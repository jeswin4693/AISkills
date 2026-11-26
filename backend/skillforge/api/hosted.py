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
from collections import OrderedDict
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool
from starlette.requests import cookie_parser

from ..builder.limits import PersonLimits
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
    hd: str = ""  # the Google Workspace domain Google vouched for when they signed in ("" for the owner and for personal accounts)


LOCAL_USER = User(LOCAL_USER_ID)  # local mode, the access token and Bearer: the one person who used the app before accounts, and whose data that is


@dataclass(frozen=True)
class Hosted:
    token: str
    allowed_hosts: frozenset[str] = frozenset()  # host names (no port) besides loopback; "*" allows any
    secure_cookie: bool | None = None  # None: Secure when the request came over https
    session_days: int = 14
    google_client_id: str = ""  # public; "" means there is no Sign in with Google
    allowed_emails: frozenset[str] = frozenset()  # lower-case: "a@b.c", "@domain", or "*"
    shared_calls_per_day: int = 0  # model calls a signed-in person without a key of their own may make on the server's model each day (UTC); 0 means none
    person_limits: PersonLimits = PersonLimits(500 * 1024 * 1024, 50, 2)  # disk, kept builds, runs at once for each signed-in person (never the owner); 0 = none

    @property
    def google(self) -> bool:
        return bool(self.google_client_id)

    def email_allowed(self, email: str, hd: str = "") -> bool:
        """Is this person on the list? An exact address, whatever the letter case; `*` lets any address in, but never nothing.
        A whole-domain entry (`@company.com`) means that company's Google Workspace: the domain must be the address's own (not a subdomain)
        AND Google must have said (`hd`) that the account belongs to that Workspace. Without the second part, a personal Google account that merely
        uses a company address (and stays verified after its owner leaves) would pass for an employee."""
        address = email.strip().lower()
        if not address or address.count("@") != 1:
            return False
        if "*" in self.allowed_emails or address in self.allowed_emails:
            return True
        domain = address.split("@", 1)[1]
        return "@" + domain in self.allowed_emails and hd.strip().lower() == domain

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
        shared_text = env.get("SKILLFORGE_SHARED_KEY_CALLS_PER_DAY", "").strip()
        shared = 0
        if shared_text:
            if not re.fullmatch(r"[0-9]{1,7}", shared_text) or int(shared_text) > 1_000_000:
                raise HostedConfigError("SKILLFORGE_SHARED_KEY_CALLS_PER_DAY must be a whole number from 0 to 1000000 (model calls per person per day on the server's model; 0 means not shared).")
            shared = int(shared_text)
            if shared and not client_id:
                raise HostedConfigError(
                    "SKILLFORGE_SHARED_KEY_CALLS_PER_DAY is set but Google sign-in is not: only the owner can sign in then, and the owner is never limited. "
                    "Set the Google settings, or remove it."
                )
        limits = PersonLimits(
            disk_bytes=_limit(env, "SKILLFORGE_PERSON_DISK_MB", 500) * 1024 * 1024,
            max_builds=_limit(env, "SKILLFORGE_PERSON_MAX_BUILDS", 50),
            max_active=_limit(env, "SKILLFORGE_PERSON_MAX_ACTIVE", 2),
        )
        return cls(
            token=token,
            allowed_hosts=frozenset(host_name(h) for h in env.get("SKILLFORGE_ALLOWED_HOSTS", "").split(",") if h.strip()),
            secure_cookie=True if secure in ("1", "true", "yes") else False if secure in ("0", "false", "no") else None,
            google_client_id=client_id,
            allowed_emails=emails,
            shared_calls_per_day=shared,
            person_limits=limits,
        )


# ---- the session cookie and the bearer token ------------------------------------------------------------------


def _limit(env: Mapping[str, str], name: str, default: int) -> int:
    """A per-person limit from the environment: a whole number from 0 (no limit) to 10,000,000, else a refusal naming the setting. Unset: the default."""
    text = env.get(name, "").strip()
    if not text:
        return default
    if not re.fullmatch(r"[0-9]{1,8}", text) or int(text) > 10_000_000:
        raise HostedConfigError(f"{name} must be a whole number from 0 to 10000000 (0 means no limit).")
    return int(text)


BLOCKED = "This account has been turned off on this server. Ask the person who runs it."


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
    """A signed session. For the owner it is the original `v1.<expiry>` cookie. For a person it is `v2.<id>.<email>.<workspace domain>.<expiry>`, so every request
    knows who it is and HOW they got in (the list is re-checked with both: a `@company.com` entry needs the Workspace domain Google vouched for at sign-in);
    the id must be one we made, so nothing odd is ever signed."""
    expiry = int(_now(now) + hosted.session_days * 86400)
    if user is None or user.id == LOCAL_USER.id:
        message = f"v1.{expiry}"
    else:
        if not _UID.match(user.id):
            raise ValueError("A session can only be made for the owner or for a person id this server made.")
        message = f"v2.{user.id}.{_b64(user.email)}.{_b64(user.hd)}.{expiry}"
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
    if parts[0] == "v2" and len(parts) == 6 and hosted.google:
        _, uid, email_text, hd_text, expiry, signature = parts
        if not (_UID.match(uid) and expiry.isdigit() and hmac.compare_digest(signature.encode("utf-8"), _sign(hosted, ".".join(parts[:5])).encode("utf-8"))):
            return None
        if int(expiry) <= current:
            return None
        try:
            email, hd = _unb64(email_text), _unb64(hd_text)
        except (ValueError, UnicodeError):
            return None
        return User(uid, email, hd) if hosted.email_allowed(email, hd) else None
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
    # Starlette's own parser (what `request.cookies` uses): it skips a cookie it cannot read and goes on. Python's SimpleCookie stops at the first one it
    # cannot parse (Google's own `g_state={"i_l":0}` is one), which hid the session cookie that came after it.
    value = cookie_parser(headers.get("cookie", "")).get(COOKIE)
    return read_cookie(hosted, value) if value is not None else None


def is_signed_in(hosted: Hosted, headers: Mapping[str, str]) -> bool:
    """`headers` has lower-case names. A valid cookie or a correct bearer token is enough."""
    return identify(hosted, headers) is not None


def current_user(request: Request) -> User:
    """Who this request is for: the person the sign-in middleware identified. Local mode has no sign-in and one person, the owner. On a hosted server a request
    nobody identified is refused: it is never taken for the owner just because nothing said otherwise (a route the middleware did not see, for example
    when the app is served under a path prefix, must not become the owner's)."""
    user = getattr(request.state, "user", None)
    if user is not None:
        return user
    if getattr(request.app.state, "hosted", None) is not None:
        raise HTTPException(401, "Sign in first.")
    return LOCAL_USER


class SpentNonces:
    """Nonces already used, remembered for as long as their cookie could still be sent. The browser is told to delete a used nonce cookie, but that is only
    a request: a copy of the cookie and the ticket would otherwise work again until the ten minutes ran out. Bounded, so a flood cannot grow it without end:
    every nonce lives the same time, so the oldest is the first to expire and the first to be forgotten (a flood that pushes one out early only lets a
    ticket made for that person be used once more, within its own ten minutes: it gives them nothing they did not already have)."""

    def __init__(self, limit: int = 10_000) -> None:
        self.limit = limit
        self._lock = threading.Lock()
        self._seen: OrderedDict[str, float] = OrderedDict()

    def claim(self, nonce: str, *, expires: float, now: float) -> bool:
        """True the first time a nonce is presented; False for every later time while it could still be valid."""
        with self._lock:
            while self._seen and next(iter(self._seen.values())) <= now:
                self._seen.popitem(last=False)
            if nonce in self._seen:
                return False
            self._seen[nonce] = expires
            while len(self._seen) > self.limit:
                self._seen.popitem(last=False)
            return True

    def __len__(self) -> int:
        with self._lock:
            return len(self._seen)


class LoginGuard:
    """After five wrong access tokens in five minutes, signing in BY TOKEN is locked for a minute. One guard for the whole server on purpose: it cannot
    be dodged by changing an address, and a long random token cannot be guessed at five tries a minute. It belongs to the access token alone: Google
    tickets neither count toward it nor clear it (a ticket is a signature from Google, so there is nothing to guess, and letting them touch this lock
    would give anybody a way to lock the owner out, or to reset a guesser's count with any Google account)."""

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
    (`request.state.user`), so no route has to work it out again. `blocked(user_id)` says whether the owner has turned a person off: it is asked on every request
    of a person (never the owner), so a block ends a session that is already signed in on its very next request."""

    def __init__(self, app, hosted: Hosted, blocked: Callable[[str], bool] | None = None) -> None:
        self.app = app
        self.hosted = hosted
        self.blocked = blocked

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        path = scope["path"]
        root = scope.get("root_path") or ""
        if root and path.startswith(root + "/"):  # served under a prefix (a proxy mount, --root-path): the route is matched without it, so the guard must be too
            path = path[len(root):]
        if scope["method"] == "OPTIONS" or not path.startswith("/api/") or path in PUBLIC_PATHS:
            await self.app(scope, receive, send)
            return
        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope["headers"]}
        user = identify(self.hosted, headers)
        # a primary-key read from the database: done in a thread, so a slow disk never holds up the server's other requests
        if user is not None and user.id != LOCAL_USER.id and self.blocked is not None and await run_in_threadpool(self.blocked, user.id):
            await JSONResponse({"detail": BLOCKED}, status_code=403)(scope, receive, send)
            return
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
    `users()` returns the store of people (made on first use, so a server that never uses Google never opens the database for it).
    `guard` is the access token's lock; Google sign-in has none of its own (see LoginGuard), and every attempt uses up its nonce instead."""
    r = APIRouter()
    spent = SpentNonces()

    @r.get("/auth/status")
    def status(request: Request) -> dict:
        if hosted is None:
            return {"required": False, "authenticated": True, "google_client_id": "", "user": None, "owner_login": False}
        who = identify(hosted, dict(request.headers))
        person = None
        if who is not None and who.id != LOCAL_USER.id and users is not None:
            record = users().get(who.id)
            if record is not None and record.blocked:  # turned off: not signed in, and the page can say why
                return {"required": True, "authenticated": False, "google_client_id": hosted.google_client_id, "user": None, "owner_login": True, "blocked": True}
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
        nonce = read_nonce(hosted, request.cookies.get(NONCE_COOKIE))
        if nonce:
            now = time.time()
            if not spent.claim(nonce, expires=now + NONCE_SECONDS, now=now):  # every attempt, good or bad, uses its nonce up: a replay finds none
                nonce = ""
        try:
            who = verify_credential(body.credential, client_id=hosted.google_client_id, nonce=nonce, key_for=keys)
        except GoogleAuthError as exc:
            if exc.code == "keys_unavailable":  # Google could not be reached: nobody guessed anything
                return JSONResponse({"detail": str(exc)}, status_code=503)
            return JSONResponse({"detail": str(exc)}, status_code=401)
        if not hosted.email_allowed(who.email, who.hd):
            detail = "That Google account is not allowed on this server. Ask the person who runs it to add your email address."
            domain = who.email.rsplit("@", 1)[-1]
            if "@" + domain in hosted.allowed_emails and who.hd != domain:
                detail += f" (Everyone at {domain} is allowed, but only with a Google Workspace account of that organisation, not a personal Google account.)"
            return JSONResponse({"detail": detail}, status_code=403)
        known = users().find_by_sub(who.sub)
        if known is not None and known.blocked:  # turned off: told so, and NOTHING about them is rewritten (name, picture, last sign-in)
            refused = JSONResponse({"detail": BLOCKED}, status_code=403)
            refused.delete_cookie(NONCE_COOKIE, path=NONCE_PATH)
            return refused
        record = users().upsert_google(who.sub, who.email, who.name, who.picture)
        if record.blocked:  # turned off between the look-up and the write (two requests at once)
            response = JSONResponse({"detail": BLOCKED}, status_code=403)
            response.delete_cookie(NONCE_COOKIE, path=NONCE_PATH)
            return response
        response = JSONResponse({"authenticated": True, "user": {"email": record.email, "name": record.name, "picture": record.picture}})
        response.set_cookie(
            COOKIE, make_cookie(hosted, user=User(record.id, record.email, who.hd)), max_age=hosted.session_days * 86400, httponly=True, samesite="lax",
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
