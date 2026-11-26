"""A person's model key, sealed so that the database holds only ciphertext (slice AI, docs/per-person-keys.md).

AES-256-GCM. The encryption key is derived (HKDF-SHA256) from the server's access token with a label of its own, so it is NOT the key that signs session cookies:
a leaked cookie key opens nothing here. The person's id is the associated data, so a sealed key copied into another person's row does not open for them.
Changing the access token makes every sealed key unreadable (the owner already knows that signs everyone out): the caller says "enter your key again".

Whoever runs the server holds the token, so they can open these keys. That is a limit of "bring your own key" on a server somebody else runs, and the docs say so.
"""

from __future__ import annotations

import os

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

NONCE_BYTES = 12
TAG_BYTES = 16
_LABEL = b"skillforge-user-keys-v1"  # not the cookie key's label (api/hosted.py), on purpose


class KeyBoxError(Exception):
    """A key could not be sealed or opened. The message never holds the key or the token."""


class KeyBox:
    def __init__(self, access_token: str) -> None:
        if not isinstance(access_token, str) or not access_token.strip():
            raise KeyBoxError("A key box needs the server's access token.")
        derived = HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=_LABEL).derive(access_token.encode("utf-8"))
        self._aead = AESGCM(derived)

    @staticmethod
    def _bound_to(user_id: str) -> bytes:
        return b"user:" + user_id.encode("utf-8")

    def seal(self, user_id: str, secret: str) -> tuple[bytes, bytes]:
        """(ciphertext, nonce). A fresh random nonce every time, so sealing the same key twice gives two different results."""
        nonce = os.urandom(NONCE_BYTES)
        return self._aead.encrypt(nonce, secret.encode("utf-8"), self._bound_to(user_id)), nonce

    def open(self, user_id: str, ciphertext: bytes, nonce: bytes) -> str:
        """The key, or KeyBoxError: another token, another person, a changed byte, or data that is not a sealed key at all."""
        refusal = KeyBoxError(
            "That saved key cannot be opened: the server's access token has changed since it was saved, or the stored data was altered. Enter the key again."
        )
        ciphertext, nonce = bytes(ciphertext), bytes(nonce)
        if len(nonce) != NONCE_BYTES or len(ciphertext) < TAG_BYTES:
            raise refusal
        try:
            return self._aead.decrypt(nonce, ciphertext, self._bound_to(user_id)).decode("utf-8")
        except (InvalidTag, UnicodeDecodeError):
            raise refusal from None
