"""Signing in with Google: who may, how a session carries a person, and every way it can go wrong.

Offline: a test signs its own tickets (see test_google_auth.py) and the server is handed that key instead of Google's.
"""

from __future__ import annotations

import re

import pytest
from fastapi import Request
from fastapi.testclient import TestClient
from sqlalchemy import text
from test_google_auth import CLIENT, OTHER, keys, ticket

from skillforge.api import create_app
from skillforge.api.builds import get_builder
from skillforge.api.hosted import (
    COOKIE, LOCAL_USER, NONCE_COOKIE, Hosted, HostedConfigError, User, current_user, identify, make_cookie, make_nonce, read_cookie, read_nonce,
)
from skillforge.library import Library

TOKEN = "a-long-enough-access-token-1234567890"
ADA = "ada.lovelace@example.com"
UID = "a" * 32


def hosted(**kw) -> Hosted:
    kw.setdefault("google_client_id", CLIENT)
    kw.setdefault("allowed_emails", frozenset({ADA}))
    return Hosted(token=kw.pop("token", TOKEN), **kw)


def make_client(tmp_path, h: Hosted | None = None, fetch=keys, base="http://localhost") -> TestClient:
    app = create_app(Library(tmp_path / "library"), hosted=h if h is not None else hosted(), google_keys=fetch)

    @app.get("/api/whoami")
    def whoami(request: Request) -> dict:
        who = current_user(request)
        return {"id": who.id, "email": who.email}

    return TestClient(app, base_url=base)


def sign_in(client: TestClient, claims: dict | None = None, nonce: str | None = None):
    """The page's whole dance: ask for a nonce, get a ticket that carries it, post the ticket."""
    got = client.get("/api/auth/nonce").json()["nonce"]
    return client.post("/api/auth/google", json={"credential": ticket({"nonce": nonce if nonce is not None else got, **(claims or {})})})


# ---- configuration ------------------------------------------------------------------------------------


def env(**kw) -> dict:
    base = {"SKILLFORGE_MODE": "hosted", "SKILLFORGE_ACCESS_TOKEN": TOKEN, "SKILLFORGE_GOOGLE_CLIENT_ID": CLIENT, "SKILLFORGE_ALLOWED_EMAILS": ADA}
    base.update(kw)
    return {k: v for k, v in base.items() if v is not None}


def test_google_sign_in_is_set_up_from_two_settings():
    h = Hosted.from_env(env(SKILLFORGE_ALLOWED_EMAILS="  Ada.Lovelace@Example.com , @team.example.org ,, bob@example.com "))
    assert h is not None and h.google_client_id == CLIENT
    assert h.allowed_emails == frozenset({ADA, "@team.example.org", "bob@example.com"}) and h.google


def test_without_google_settings_nothing_about_google_is_on():
    h = Hosted.from_env(env(SKILLFORGE_GOOGLE_CLIENT_ID=None, SKILLFORGE_ALLOWED_EMAILS=None))
    assert h is not None and not h.google and h.google_client_id == "" and h.allowed_emails == frozenset()


def test_a_client_id_with_nobody_allowed_refuses_to_start_because_signing_in_is_not_being_welcome():
    with pytest.raises(HostedConfigError, match="SKILLFORGE_ALLOWED_EMAILS"):
        Hosted.from_env(env(SKILLFORGE_ALLOWED_EMAILS=None))
    with pytest.raises(HostedConfigError, match="SKILLFORGE_ALLOWED_EMAILS"):
        Hosted.from_env(env(SKILLFORGE_ALLOWED_EMAILS=" , "))


def test_an_allow_list_without_a_client_id_refuses_to_start():
    with pytest.raises(HostedConfigError, match="SKILLFORGE_GOOGLE_CLIENT_ID"):
        Hosted.from_env(env(SKILLFORGE_GOOGLE_CLIENT_ID=None))


@pytest.mark.parametrize("wrong, why", [
    ("GOCSPX-abcdefghijklmnopqrstuvwx", "secret"),  # the client SECRET pasted by mistake
    ("not-a-client-id", "apps.googleusercontent.com"),
    ("1234.apps.googleusercontent.com extra", "apps.googleusercontent.com"),
])
def test_a_client_id_that_is_not_one_is_refused_and_a_pasted_secret_is_named_as_one(wrong, why):
    with pytest.raises(HostedConfigError, match=why):
        Hosted.from_env(env(SKILLFORGE_GOOGLE_CLIENT_ID=wrong))


@pytest.mark.parametrize("email, allowed", [
    (ADA, True), ("ADA.LOVELACE@EXAMPLE.COM", True), (" ada.lovelace@example.com ", True), ("bob@example.com", False), ("", False),
    ("ada.lovelace@example.com.evil.com", False), ("xada.lovelace@example.com", False), ("ada.lovelace@example.comx", False),
])
def test_only_listed_addresses_are_allowed_whatever_their_case(email, allowed):
    assert hosted().email_allowed(email) is allowed


@pytest.mark.parametrize("email, allowed", [
    ("anyone@team.example.org", True), ("Anyone@TEAM.example.org", True), ("a@sub.team.example.org", False), ("a@team.example.org.evil.com", False),
    ("a@evilteam.example.org", False), ("team.example.org", False), ("a@b@team.example.org", False),
])
def test_a_domain_entry_allows_that_domain_only(email, allowed):
    # The address-shape rules, for a person Google says belongs to the listed Workspace. (Without that claim a domain entry lets nobody in: test_accounts_review.py, finding 4.)
    assert hosted(allowed_emails=frozenset({"@team.example.org"})).email_allowed(email, "team.example.org") is allowed


def test_a_star_allows_any_google_account_but_not_nothing():
    h = hosted(allowed_emails=frozenset({"*"}))
    assert h.email_allowed("anyone@anywhere.example") and not h.email_allowed("") and not h.email_allowed("   ")


# ---- the session cookie carries a person --------------------------------------------------------------


def test_a_person_survives_the_cookie_round_trip():
    h = hosted()
    value = make_cookie(h, now=1_000.0, user=User(UID, ADA))
    assert value.startswith("v2.") and ADA not in value  # the email is encoded, not written out
    assert read_cookie(h, value, now=1_001.0) == User(UID, ADA)


def test_the_owner_cookie_is_the_old_cookie_and_means_the_owner():
    h = hosted()
    assert make_cookie(h, now=1_000.0).startswith("v1.") and make_cookie(h, now=1_000.0, user=LOCAL_USER).startswith("v1.")
    assert read_cookie(h, make_cookie(h, now=1_000.0), now=1_001.0) == LOCAL_USER


def test_a_person_cookie_is_refused_when_expired_tampered_or_signed_with_another_token():
    h = hosted()
    value = make_cookie(h, now=1_000.0, user=User(UID, ADA))
    assert read_cookie(h, value, now=1_000.0 + h.session_days * 86400 + 1) is None
    assert read_cookie(hosted(token="another-long-enough-token-0987654321"), value, now=1_001.0) is None
    head, _, sig = value.rpartition(".")
    assert read_cookie(h, f"{head}.{'0' * len(sig)}", now=1_001.0) is None
    parts = value.split(".")
    for index, change in ((1, "b" * 32), (2, "AAAA"), (3, "9" + parts[3])):  # another person, another email, another expiry: all under the same signature
        forged = ".".join(parts[:index] + [change] + parts[index + 1:])
        assert read_cookie(h, forged, now=1_001.0) is None, index


@pytest.mark.parametrize("junk", ["", "x", "v2", "v2.a.b.c.d", "v2." + "g" * 32 + ".QQ.9999999999.sig", "v3.x.y.z.w", "....", None, 5])
def test_garbage_is_never_a_person(junk):
    assert read_cookie(hosted(), junk, now=1.0) is None


def test_taking_someone_off_the_list_ends_their_session_at_once():
    value = make_cookie(hosted(), now=1_000.0, user=User(UID, ADA))
    assert read_cookie(hosted(), value, now=1_001.0) is not None
    assert read_cookie(hosted(allowed_emails=frozenset({"bob@example.com"})), value, now=1_001.0) is None


def test_a_person_cookie_means_nothing_on_a_server_that_has_no_google_sign_in():
    value = make_cookie(hosted(), now=1_000.0, user=User(UID, ADA))
    assert read_cookie(Hosted(token=TOKEN), value, now=1_001.0) is None
    # An empty list refuses for its own reason. With a list that would admit anyone, only "Google sign-in is off" can refuse.
    assert read_cookie(Hosted(token=TOKEN, allowed_emails=frozenset({"*"})), value, now=1_001.0) is None


def test_a_person_id_that_is_not_one_we_made_cannot_be_put_in_a_cookie():
    with pytest.raises(ValueError):
        make_cookie(hosted(), now=1_000.0, user=User("../../etc/passwd", ADA))


def test_identify_accepts_a_cookie_or_the_bearer_token_and_the_bearer_is_the_owner():
    h = hosted()
    cookie = make_cookie(h, now=None, user=User(UID, ADA))
    assert identify(h, {"cookie": f"{COOKIE}={cookie}"}) == User(UID, ADA)
    assert identify(h, {"authorization": f"Bearer {TOKEN}"}) == LOCAL_USER
    assert identify(h, {"authorization": "Bearer wrong"}) is None and identify(h, {}) is None


# ---- the nonce ----------------------------------------------------------------------------------------


def test_a_nonce_comes_back_only_from_the_cookie_that_was_signed_for_it():
    h = hosted()
    nonce, cookie = make_nonce(h, now=1_000.0)
    assert len(nonce) >= 24 and read_nonce(h, cookie, now=1_001.0) == nonce
    assert read_nonce(h, cookie, now=1_000.0 + 601) == ""  # ten minutes at most
    assert read_nonce(hosted(token="another-long-enough-token-0987654321"), cookie, now=1_001.0) == ""
    head, _, sig = cookie.rpartition(".")
    assert read_nonce(h, f"{head}.{'0' * len(sig)}", now=1_001.0) == ""
    assert read_nonce(h, make_cookie(h, now=1_000.0), now=1_001.0) == ""  # a session cookie is not a nonce, and the other way round
    assert {make_nonce(h)[0] for _ in range(20)} and len({make_nonce(h)[0] for _ in range(20)}) == 20


# ---- the routes ---------------------------------------------------------------------------------------


def test_the_page_is_told_whether_to_show_google_and_which_client_id_but_nothing_secret(tmp_path):
    c = make_client(tmp_path)
    body = c.get("/api/auth/status").json()
    assert body == {"required": True, "authenticated": False, "google_client_id": CLIENT, "user": None, "owner_login": True}
    assert TOKEN not in c.get("/api/auth/status").text


def test_the_local_server_says_it_needs_no_sign_in_and_knows_no_google(tmp_path):
    app = create_app(Library(tmp_path / "library"))
    body = TestClient(app, base_url="http://localhost").get("/api/auth/status").json()
    assert body["required"] is False and body["authenticated"] is True and body["google_client_id"] == "" and body["user"] is None


def test_a_server_with_only_the_token_shows_no_google_button(tmp_path):
    c = make_client(tmp_path, h=Hosted(token=TOKEN))
    assert c.get("/api/auth/status").json()["google_client_id"] == ""


def test_the_nonce_route_issues_a_nonce_in_a_cookie_the_page_cannot_read(tmp_path):
    c = make_client(tmp_path)
    r = c.get("/api/auth/nonce")
    assert r.status_code == 200 and len(r.json()["nonce"]) >= 24
    cookie = r.headers["set-cookie"].lower()
    assert NONCE_COOKIE in cookie and "httponly" in cookie and "samesite=lax" in cookie
    assert c.get("/api/auth/nonce").json()["nonce"] != r.json()["nonce"]


def test_a_person_on_the_list_signs_in_and_every_later_request_knows_who_they_are(tmp_path):
    c = make_client(tmp_path)
    assert c.get("/api/whoami").status_code == 401
    r = sign_in(c)
    body = r.json()
    assert r.status_code == 200 and body["authenticated"] is True
    assert body["user"] == {"email": ADA, "name": "Ada Lovelace", "picture": "https://lh3.googleusercontent.com/a/photo"}
    assert COOKIE in r.headers["set-cookie"] and "httponly" in r.headers["set-cookie"].lower()
    who = c.get("/api/whoami").json()
    assert re.fullmatch(r"[0-9a-f]{32}", who["id"]) and who["email"] == ADA
    status = c.get("/api/auth/status").json()
    assert status["authenticated"] is True and status["user"]["email"] == ADA and status["user"]["name"] == "Ada Lovelace"


def test_signing_in_again_is_the_same_person(tmp_path):
    c = make_client(tmp_path)
    sign_in(c)
    first = c.get("/api/whoami").json()["id"]
    c.post("/api/auth/logout")
    sign_in(c)
    assert c.get("/api/whoami").json()["id"] == first


def test_the_person_is_recorded_in_the_database_once(tmp_path):
    c = make_client(tmp_path)
    sign_in(c)
    sign_in(c)
    with get_builder(c.app).db.session() as s:
        assert s.execute(text("SELECT count(*) FROM users")).scalar() == 1


def test_someone_not_on_the_list_is_refused_kindly_and_leaves_no_trace(tmp_path):
    c = make_client(tmp_path, h=hosted(allowed_emails=frozenset({"bob@example.com"})))
    r = sign_in(c)
    assert r.status_code == 403 and "not allowed" in r.json()["detail"] and "add your email" in r.json()["detail"]
    assert COOKIE not in r.headers.get("set-cookie", "")
    assert c.get("/api/auth/status").json()["authenticated"] is False
    with get_builder(c.app).db.session() as s:
        assert s.execute(text("SELECT count(*) FROM users")).scalar() == 0


def test_a_whole_domain_or_a_star_lets_those_people_in(tmp_path):
    assert sign_in(make_client(tmp_path, h=hosted(allowed_emails=frozenset({"@example.com"}))), {"hd": "example.com"}).status_code == 200  # a Workspace account of that domain


def test_a_star_lets_in_any_google_account(tmp_path):
    assert sign_in(make_client(tmp_path, h=hosted(allowed_emails=frozenset({"*"}))), {"email": "stranger@elsewhere.example"}).status_code == 200


@pytest.mark.parametrize("claims, why", [
    ({"aud": "another.apps.googleusercontent.com"}, "another app"),
    ({"iss": "https://evil.example.com"}, "another issuer"),
    ({"email_verified": False}, "an unverified email"),
    ({"exp": 1, "iat": 0}, "an expired ticket"),
])
def test_a_ticket_that_is_not_believed_is_refused_and_nobody_is_signed_in(tmp_path, claims, why):
    c = make_client(tmp_path)
    r = sign_in(c, claims)
    assert r.status_code == 401, why
    assert COOKIE not in r.headers.get("set-cookie", "") and c.get("/api/whoami").status_code == 401


def test_a_forged_ticket_is_refused_and_the_answer_never_repeats_it(tmp_path):
    c = make_client(tmp_path)
    nonce = c.get("/api/auth/nonce").json()["nonce"]
    forged = ticket({"nonce": nonce}, key=OTHER)
    r = c.post("/api/auth/google", json={"credential": forged})
    assert r.status_code == 401 and forged not in r.text and r.json()["detail"] == "That Google sign-in could not be verified."


def test_a_ticket_for_another_browsers_attempt_is_refused_so_a_stolen_one_cannot_be_replayed(tmp_path):
    thief = make_client(tmp_path)
    r = sign_in(thief, nonce="the-nonce-of-someone-elses-attempt")
    assert r.status_code == 401 and "no longer valid" in r.json()["detail"]
    victim = make_client(tmp_path)
    credential = ticket({"nonce": victim.get("/api/auth/nonce").json()["nonce"]})
    assert TestClient(victim.app, base_url="http://localhost").post("/api/auth/google", json={"credential": credential}).status_code == 401  # no nonce cookie here


def test_a_ticket_with_no_nonce_cookie_at_all_is_refused(tmp_path):
    c = make_client(tmp_path)
    assert c.post("/api/auth/google", json={"credential": ticket()}).status_code == 401


def test_a_nonce_is_used_once(tmp_path):
    c = make_client(tmp_path)
    nonce = c.get("/api/auth/nonce").json()["nonce"]
    credential = ticket({"nonce": nonce})
    assert c.post("/api/auth/google", json={"credential": credential}).status_code == 200
    # No sign-out in between (that would clear the nonce cookie too): only the server's own clearing of it on use stands in the way of a replay.
    assert c.post("/api/auth/google", json={"credential": credential}).status_code == 401


def test_google_being_unreachable_is_a_503_not_a_wrong_ticket_and_is_not_counted_against_anyone(tmp_path):
    import jwt

    def down(_credential):
        raise jwt.PyJWKClientConnectionError("down")

    c = make_client(tmp_path, fetch=down)
    for _ in range(7):
        r = sign_in(c)
        assert r.status_code == 503 and "reach Google" in r.json()["detail"]
    assert c.post("/api/auth/login", json={"token": "wrong"}).status_code == 401  # still not locked


# (A test here used to say that five wrong Google tickets lock every sign-in for a minute. The independent review showed that was a lever for anybody to lock
# the owner out, and that a good Google sign-in cleared a token guesser's count: wrong tickets now touch no lock, see test_accounts_review.py, findings 1, 2 and 6.)


def test_asking_to_sign_in_with_google_on_a_server_without_it_is_a_clear_400(tmp_path):
    c = make_client(tmp_path, h=Hosted(token=TOKEN))
    r = c.post("/api/auth/google", json={"credential": "x"})
    assert r.status_code == 400 and "not set up" in r.json()["detail"]
    assert TestClient(create_app(Library(tmp_path / "l2")), base_url="http://localhost").post("/api/auth/google", json={"credential": "x"}).status_code == 400


def test_an_oversized_or_missing_credential_is_a_422_that_does_not_echo_it(tmp_path):
    c = make_client(tmp_path)
    assert c.post("/api/auth/google", json={}).status_code == 422
    r = c.post("/api/auth/google", json={"credential": "x" * 20_000})
    assert r.status_code == 422 and "x" * 100 not in r.text


def test_the_access_token_still_signs_the_owner_in_and_the_bearer_is_the_owner_too(tmp_path):
    c = make_client(tmp_path)
    assert c.post("/api/auth/login", json={"token": TOKEN}).status_code == 200
    assert c.get("/api/whoami").json() == {"id": "local", "email": ""}
    fresh = make_client(tmp_path)
    assert fresh.get("/api/whoami", headers={"Authorization": f"Bearer {TOKEN}"}).json()["id"] == "local"


def test_signing_out_clears_the_session_and_the_nonce(tmp_path):
    c = make_client(tmp_path)
    sign_in(c)
    r = c.post("/api/auth/logout")
    assert r.status_code == 200 and c.get("/api/whoami").status_code == 401
    assert COOKIE in r.headers["set-cookie"] and NONCE_COOKIE in r.headers["set-cookie"]


def test_changing_the_access_token_signs_every_google_session_out_too(tmp_path):
    c = make_client(tmp_path)
    sign_in(c)
    other = make_client(tmp_path, h=hosted(token="another-long-enough-token-0987654321"))
    other.cookies.update(c.cookies)
    assert other.get("/api/whoami").status_code == 401


def test_a_removed_person_is_refused_on_their_very_next_request(tmp_path):
    c = make_client(tmp_path)
    sign_in(c)
    assert c.get("/api/whoami").status_code == 200
    stricter = make_client(tmp_path, h=hosted(allowed_emails=frozenset({"bob@example.com"})))
    stricter.cookies.update(c.cookies)
    assert stricter.get("/api/whoami").status_code == 401


def test_the_secure_flag_is_set_behind_https(tmp_path):
    # Over plain http a Secure cookie is (rightly) never sent back, so this runs over an https address.
    c = make_client(tmp_path, h=hosted(secure_cookie=True), base="https://localhost")
    assert "secure" in c.get("/api/auth/nonce").headers["set-cookie"].lower()
    r = sign_in(c)
    assert r.status_code == 200 and "secure" in r.headers["set-cookie"].lower()


def test_over_plain_http_a_server_that_demands_secure_cookies_cannot_be_signed_in_to_by_accident(tmp_path):
    c = make_client(tmp_path, h=hosted(secure_cookie=True), base="http://localhost")
    assert sign_in(c).status_code == 401  # the nonce cookie never came back, so the ticket is not believed
