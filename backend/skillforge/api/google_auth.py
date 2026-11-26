"""Checking a "Sign in with Google" ticket (an ID token) on the server.

The browser's Google button hands the page a signed ticket. The page posts it here, and this module decides whether to believe it. A ticket is accepted
only when ALL of these hold, and each failure has its own code (for a test or a log; the message shown to a person never repeats the ticket):

  * it is signed with RS256 by a key Google publishes (the `none` algorithm and the HS256-with-the-public-key trick are refused before any key is used),
  * it was made for THIS app: `aud` is our Client ID, as one string (a ticket for several apps is refused even if ours is one of them),
  * Google issued it (`iss`), it has not expired, and it was not issued in the future,
  * it is about an email address Google has verified,
  * it carries the nonce this server issued for this sign-in attempt, so a stolen ticket cannot be replayed into another browser.

No Google client secret is used anywhere: the ticket is verified against Google's PUBLIC keys. The Client ID is public too (the page needs it).
"""

from __future__ import annotations

import hmac
import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import jwt

GOOGLE_CERTS_URL = "https://www.googleapis.com/oauth2/v3/certs"
GOOGLE_ISSUERS = ("accounts.google.com", "https://accounts.google.com")
LEEWAY_SECONDS = 10  # a little clock difference between Google's servers and ours
MAX_NAME = 200
MAX_PICTURE = 500
MAX_EMAIL = 320
_CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f​-‏  ‪-‮⁠-⁤⁦-⁩﻿]")

_MESSAGES = {
    "expired": "That Google sign-in has expired. Try again.",
    "not_yet_valid": "That Google sign-in is not valid yet. Check that your clock is right, then try again.",
    "nonce": "That sign-in attempt is no longer valid. Reload the page and try again.",
    "email_not_verified": "Google says this email address is not verified, so it cannot be used to sign in.",
    "keys_unavailable": "Could not reach Google to check your sign-in. Try again in a moment.",
    "not_configured": "Sign in with Google is not set up on this server.",
}
_GENERIC = "That Google sign-in could not be verified."


class GoogleAuthError(Exception):
    """A ticket that is not believed. `code` says why (for tests and logs); `str(error)` is safe to show a person and never contains the ticket."""

    def __init__(self, code: str) -> None:
        super().__init__(_MESSAGES.get(code, _GENERIC))
        self.code = code


@dataclass(frozen=True)
class GoogleIdentity:
    sub: str  # Google's stable id for the account (never changes, unlike an email)
    email: str  # lower-case
    name: str
    picture: str  # an https address, or ""
    hd: str = ""  # the Google Workspace domain the account belongs to (lower-case), or "": a personal account has none, whatever its email looks like


class GoogleKeys:
    """Google's published signing keys, fetched over https the first time a ticket is checked and kept for an hour (PyJWT's client does the caching).
    Nothing is fetched when this is made."""

    def __init__(self, url: str = GOOGLE_CERTS_URL) -> None:
        self.url = url
        self._client = jwt.PyJWKClient(url, cache_keys=True, lifespan=3600, timeout=10)

    def key_for(self, credential: str) -> Any:
        return self._client.get_signing_key_from_jwt(credential).key

    __call__ = key_for


def _plain(text: object, limit: int) -> str:
    return _CONTROL.sub(" ", text).strip()[:limit] if isinstance(text, str) else ""


_DOMAIN = re.compile(r"[a-z0-9](?:[a-z0-9.-]{0,251}[a-z0-9])?\Z")


def _workspace_domain(value: object) -> str:
    """The `hd` claim as a plain lower-case domain, or "" when it is missing or not shaped like one (it is compared with the list, never shown)."""
    if not isinstance(value, str):
        return ""
    domain = value.strip().lower()
    return domain if _DOMAIN.match(domain) else ""


def verify_credential(credential: str, *, client_id: str, nonce: str, key_for: Callable[[str], Any]) -> GoogleIdentity:
    """The person a ticket is about, or GoogleAuthError. `key_for(ticket)` returns the public key that signed it (the real one asks Google)."""
    if not client_id:
        raise GoogleAuthError("not_configured")
    if not nonce:  # a missing nonce cookie must never let a ticket through
        raise GoogleAuthError("nonce")
    try:
        header = jwt.get_unverified_header(credential)
    except (jwt.PyJWTError, ValueError, TypeError, UnicodeError) as exc:
        raise GoogleAuthError("malformed") from exc
    if header.get("alg") != "RS256":  # before any key is touched: this is what stops `none` and the HS256-with-the-public-key trick
        raise GoogleAuthError("algorithm")
    try:
        key = key_for(credential)
    except jwt.PyJWKClientConnectionError as exc:
        raise GoogleAuthError("keys_unavailable") from exc
    except (jwt.PyJWTError, KeyError, ValueError, TypeError) as exc:  # a key id Google does not publish: the ticket is not one of Google's
        raise GoogleAuthError("signature") from exc
    try:
        claims = jwt.decode(
            credential, key, algorithms=["RS256"], leeway=LEEWAY_SECONDS,
            options={"require": ["exp", "iat", "iss", "aud", "sub"], "verify_aud": False, "verify_iss": False},  # audience and issuer are checked below, strictly
        )
    except jwt.ExpiredSignatureError as exc:
        raise GoogleAuthError("expired") from exc
    except (jwt.ImmatureSignatureError, jwt.InvalidIssuedAtError) as exc:
        raise GoogleAuthError("not_yet_valid") from exc
    except jwt.MissingRequiredClaimError as exc:
        raise GoogleAuthError("malformed") from exc
    except jwt.InvalidSignatureError as exc:
        raise GoogleAuthError("signature") from exc
    except (jwt.PyJWTError, ValueError, TypeError, UnicodeError) as exc:
        raise GoogleAuthError("signature" if credential.endswith(".") else "malformed") from exc
    if claims.get("iss") not in GOOGLE_ISSUERS:
        raise GoogleAuthError("issuer")
    audience = claims.get("aud")
    if not (isinstance(audience, str) and hmac.compare_digest(audience.encode("utf-8"), client_id.encode("utf-8"))):
        raise GoogleAuthError("audience")
    email, sub = claims.get("email"), claims.get("sub")
    if not (isinstance(email, str) and email.strip()) or len(email) > MAX_EMAIL:
        raise GoogleAuthError("email_missing")
    if claims.get("email_verified") not in (True, "true"):
        raise GoogleAuthError("email_not_verified")
    if not (isinstance(sub, str) and sub.strip()) or len(sub) > 255:
        raise GoogleAuthError("malformed")
    ticket_nonce = claims.get("nonce")
    if not (isinstance(ticket_nonce, str) and ticket_nonce and hmac.compare_digest(ticket_nonce.encode("utf-8"), nonce.encode("utf-8"))):
        raise GoogleAuthError("nonce")
    email = email.strip().lower()
    picture = claims.get("picture")
    return GoogleIdentity(
        sub=sub.strip(), email=email, name=_plain(claims.get("name"), MAX_NAME) or email.split("@")[0],
        picture=picture if isinstance(picture, str) and picture.startswith("https://") and len(picture) <= MAX_PICTURE else "",
        hd=_workspace_domain(claims.get("hd")),
    )
