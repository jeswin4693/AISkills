"""Checking a "Sign in with Google" ticket (an ID token). Every check is made offline: a test makes its own RSA key and signs its own tickets,
and hands the checker that key in place of Google's published ones. A ticket is accepted only when it is signed by the key, made for THIS app,
issued by Google, not expired, about a verified email, and carries the nonce the server issued for this attempt.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from skillforge.api.google_auth import GoogleAuthError, GoogleIdentity, GoogleKeys, verify_credential

CLIENT = "111111111111-example.apps.googleusercontent.com"
KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
OTHER = rsa.generate_private_key(public_exponent=65537, key_size=2048)


def keys(_credential: str):
    return KEY.public_key()


def ticket(claims: dict | None = None, *, key=KEY, algorithm: str = "RS256", headers: dict | None = None, drop: tuple[str, ...] = ()) -> str:
    now = int(time.time())
    body = {
        "iss": "https://accounts.google.com", "aud": CLIENT, "sub": "110169484474386276334", "email": "Ada.Lovelace@Example.com", "email_verified": True,
        "name": "Ada Lovelace", "picture": "https://lh3.googleusercontent.com/a/photo", "iat": now - 10, "exp": now + 3600, "nonce": "N-123",
    }
    body.update(claims or {})
    for name in drop:
        body.pop(name, None)
    return jwt.encode(body, key, algorithm=algorithm, headers={"kid": "test-key", **(headers or {})})


def check(credential: str, nonce: str = "N-123", client: str = CLIENT, fetch=keys) -> GoogleIdentity:
    return verify_credential(credential, client_id=client, nonce=nonce, key_for=fetch)


def refused(credential: str, code: str, **kwargs) -> None:
    with pytest.raises(GoogleAuthError) as caught:
        check(credential, **kwargs)
    assert caught.value.code == code
    assert credential not in str(caught.value)  # a message never repeats the ticket


# ---- a good ticket ------------------------------------------------------------------------------------


def test_a_good_ticket_gives_who_signed_in():
    who = check(ticket())
    assert (who.sub, who.email, who.name) == ("110169484474386276334", "ada.lovelace@example.com", "Ada Lovelace")  # the email is lower-cased
    assert who.picture == "https://lh3.googleusercontent.com/a/photo"


@pytest.mark.parametrize("issuer", ["https://accounts.google.com", "accounts.google.com"])
def test_both_spellings_of_googles_issuer_are_accepted(issuer):
    assert check(ticket({"iss": issuer})).email


def test_email_verified_may_be_the_string_true_as_older_tickets_wrote_it():
    assert check(ticket({"email_verified": "true"})).email


# ---- every way a ticket can be wrong ------------------------------------------------------------------


def test_a_ticket_made_for_another_app_is_refused():
    refused(ticket({"aud": "someone-elses-client.apps.googleusercontent.com"}), "audience")


def test_a_ticket_for_several_apps_is_refused_even_if_ours_is_one_of_them():
    refused(ticket({"aud": [CLIENT, "other.apps.googleusercontent.com"]}), "audience")


def test_a_ticket_with_no_audience_is_refused():
    refused(ticket(drop=("aud",)), "malformed")


@pytest.mark.parametrize("issuer", ["https://evil.example.com", "accounts.google.com.evil.com", "", "https://accounts.google.com/"])
def test_a_ticket_from_another_issuer_is_refused(issuer):
    refused(ticket({"iss": issuer}), "issuer")


def test_an_expired_ticket_is_refused():
    refused(ticket({"exp": int(time.time()) - 3600, "iat": int(time.time()) - 7200}), "expired")


def test_a_ticket_issued_in_the_future_is_refused():
    refused(ticket({"iat": int(time.time()) + 3600, "exp": int(time.time()) + 7200}), "not_yet_valid")


def test_a_ticket_signed_by_another_key_is_refused():
    refused(ticket(key=OTHER), "signature")


def test_a_ticket_with_its_signature_cut_off_is_refused():
    head, body, _ = ticket().split(".")
    refused(f"{head}.{body}.", "signature")


def test_a_ticket_whose_claims_were_changed_after_signing_is_refused():
    head, body, signature = ticket().split(".")
    claims = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
    claims["email"] = "admin@example.com"
    forged = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=")
    refused(f"{head}.{forged}.{signature}", "signature")


def test_the_none_algorithm_is_refused():
    unsigned = jwt.encode({"iss": "accounts.google.com", "aud": CLIENT, "sub": "1", "email": "a@b.c", "email_verified": True, "nonce": "N-123",
                           "iat": int(time.time()) - 5, "exp": int(time.time()) + 600}, key=None, algorithm="none")
    refused(unsigned, "algorithm")


def test_an_hmac_ticket_signed_with_the_public_key_as_the_secret_is_refused():
    # The classic confusion attack: HS256 with the (public) RSA key used as the shared secret. PyJWT refuses to even CREATE such a token, so it is forged by hand,
    # as an attacker would. The checker only ever allows RS256, and says so before any key is used.
    public_pem = KEY.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
    now = int(time.time())

    def part(data: dict) -> str:
        return base64.urlsafe_b64encode(json.dumps(data).encode()).decode().rstrip("=")

    signing_input = part({"alg": "HS256", "typ": "JWT", "kid": "test-key"}) + "." + part(
        {"iss": "https://accounts.google.com", "aud": CLIENT, "sub": "1", "email": "a@b.c", "email_verified": True, "nonce": "N-123", "iat": now - 5, "exp": now + 600}
    )
    signature = base64.urlsafe_b64encode(hmac.new(public_pem, signing_input.encode(), hashlib.sha256).digest()).decode().rstrip("=")
    refused(f"{signing_input}.{signature}", "algorithm")


@pytest.mark.parametrize("claims", [{"email_verified": False}, {"email_verified": "false"}, {"email_verified": None}])
def test_an_unverified_email_is_refused(claims):
    refused(ticket(claims), "email_not_verified")


def test_a_ticket_without_an_email_is_refused():
    refused(ticket(drop=("email",)), "email_missing")


def test_a_ticket_without_a_subject_is_refused():
    refused(ticket(drop=("sub",)), "malformed")


@pytest.mark.parametrize("nonce", ["", "N-124", "n-123"])
def test_a_ticket_with_the_wrong_nonce_is_refused(nonce):
    refused(ticket({"nonce": nonce}), "nonce")


def test_a_ticket_with_no_nonce_is_refused():
    refused(ticket(drop=("nonce",)), "nonce")


def test_asking_with_no_nonce_is_refused_so_a_missing_cookie_never_lets_a_ticket_through():
    refused(ticket(), "nonce", nonce="")


def test_a_request_with_no_nonce_never_asks_google_for_keys():
    asked: list[str] = []

    def spy(credential: str):
        asked.append(credential)
        return KEY.public_key()

    refused(ticket(), "nonce", nonce="", fetch=spy)
    assert asked == []  # someone with no nonce cookie cannot make this server start a network fetch


@pytest.mark.parametrize("garbage", ["", "not a ticket", "a.b.c", "....", "x" * 5000, "\x00\x01\x02"])
def test_garbage_is_refused_without_a_crash(garbage):
    with pytest.raises(GoogleAuthError):
        check(garbage)


def test_a_client_id_that_is_not_set_refuses_everything():
    with pytest.raises(GoogleAuthError):
        check(ticket(), client="")


# ---- Googles keys -------------------------------------------------------------------------------------


def test_keys_that_cannot_be_fetched_are_a_separate_error_from_a_forged_ticket():
    def down(_credential):
        raise jwt.PyJWKClientConnectionError("could not reach the keys")

    refused(ticket(), "keys_unavailable", fetch=down)


def test_a_key_id_that_google_does_not_publish_is_a_bad_signature_not_an_outage():
    def unknown(_credential):
        raise jwt.PyJWKClientError("Unable to find a signing key that matches: 'x'")

    refused(ticket(), "signature", fetch=unknown)


def test_the_real_key_fetcher_reads_googles_published_keys_from_the_right_address():
    fetcher = GoogleKeys()
    assert fetcher.url == "https://www.googleapis.com/oauth2/v3/certs"  # nothing is fetched until a ticket is checked


# ---- what is kept about the person --------------------------------------------------------------------


def test_the_name_and_picture_are_kept_short_and_plain():
    who = check(ticket({"name": "A" * 500 + "\x1b[2J", "picture": "http://insecure.example.com/p.png"}))
    assert len(who.name) <= 200 and "\x1b" not in who.name
    assert who.picture == ""  # only an https picture is kept


def test_control_characters_and_hidden_direction_marks_inside_a_name_are_replaced():
    # In the MIDDLE of a short name: stripping the ends and cutting to the limit cannot remove these, only the replacement can.
    who = check(ticket({"name": "Ada\x1b[2J\x07 Love‮lace​⁦x"}))
    assert all(ch.isprintable() for ch in who.name), repr(who.name)
    assert who.name.startswith("Ada") and "Love" in who.name and "lace" in who.name  # the visible words are kept


def test_a_missing_name_falls_back_to_the_part_of_the_email_before_the_at():
    who = check(ticket(drop=("name", "picture")))
    assert who.name == "ada.lovelace" and who.picture == ""
