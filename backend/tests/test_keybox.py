"""A person's model key is sealed under the access token and bound to the person (slice AI, docs/per-person-keys.md).

Pure and offline: no database, no network.
"""

from __future__ import annotations

import hashlib

import pytest
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from skillforge.builder.keybox import KeyBox, KeyBoxError

TOKEN = "a-long-enough-access-token-1234567890"
ADA = "a" * 32
BOB = "b" * 32
KEY = "AIzaSyDistinctiveFakeKeyForTests_0123456789"


def test_a_sealed_key_opens_for_the_same_person_and_token():
    box = KeyBox(TOKEN)
    ciphertext, nonce = box.seal(ADA, KEY)
    assert box.open(ADA, ciphertext, nonce) == KEY


def test_the_ciphertext_does_not_contain_the_key():
    ciphertext, nonce = KeyBox(TOKEN).seal(ADA, KEY)
    assert KEY.encode() not in ciphertext and KEY[:8].encode() not in ciphertext + nonce


def test_another_persons_id_cannot_open_it():
    box = KeyBox(TOKEN)
    ciphertext, nonce = box.seal(ADA, KEY)  # the id is the associated data: a copy of Ada's row in Bob's is useless
    with pytest.raises(KeyBoxError):
        box.open(BOB, ciphertext, nonce)


def test_another_access_token_cannot_open_it():
    ciphertext, nonce = KeyBox(TOKEN).seal(ADA, KEY)
    with pytest.raises(KeyBoxError):
        KeyBox(TOKEN + "x").open(ADA, ciphertext, nonce)


def test_a_flipped_byte_is_refused():
    box = KeyBox(TOKEN)
    ciphertext, nonce = box.seal(ADA, KEY)
    with pytest.raises(KeyBoxError):
        box.open(ADA, bytes([ciphertext[0] ^ 1]) + ciphertext[1:], nonce)
    with pytest.raises(KeyBoxError):
        box.open(ADA, ciphertext, bytes([nonce[0] ^ 1]) + nonce[1:])


def test_two_seals_of_the_same_key_differ():
    box = KeyBox(TOKEN)
    assert box.seal(ADA, KEY) != box.seal(ADA, KEY)  # a fresh nonce every time


def test_an_error_never_repeats_the_key_or_the_token():
    ciphertext, nonce = KeyBox(TOKEN).seal(ADA, KEY)
    with pytest.raises(KeyBoxError) as caught:
        KeyBox(TOKEN + "x").open(ADA, ciphertext, nonce)
    text = str(caught.value)
    assert KEY not in text and TOKEN not in text


def test_a_token_that_is_empty_is_refused_at_construction():
    for empty in ("", "   "):
        with pytest.raises(KeyBoxError):
            KeyBox(empty)


def test_nonsense_input_is_a_keybox_error_not_a_crash():
    box = KeyBox(TOKEN)
    for ciphertext, nonce in ((b"", b""), (b"x" * 5, b"y" * 12), (b"x" * 40, b"short"), (b"x" * 40, b"")):
        with pytest.raises(KeyBoxError):
            box.open(ADA, ciphertext, nonce)


def test_the_cookie_signing_key_cannot_open_a_sealed_key():
    # The two keys come from the same token with different labels: a leaked cookie key must not unlock the stored keys.
    ciphertext, nonce = KeyBox(TOKEN).seal(ADA, KEY)
    cookie_key = hashlib.sha256(b"skillforge-session-v1\0" + TOKEN.encode()).digest()
    with pytest.raises(Exception):  # noqa: B017 - any failure to decrypt is the point
        AESGCM(cookie_key).decrypt(nonce, ciphertext, b"user:" + ADA.encode())
