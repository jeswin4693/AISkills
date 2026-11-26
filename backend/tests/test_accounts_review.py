"""Fixes for the independent review of the accounts slice (2026-11-26, a fresh reviewer, no Critical finding).

Each test here failed on the reviewed code first (commit daa4fb4), for the reason the reviewer gave; the reviewer's report is model output, so every claim was
reproduced as a failing test before anything was changed. Numbers are the reviewer's finding numbers.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
from fastapi import HTTPException, Request
from fastapi.testclient import TestClient
from sqlalchemy import text
from test_accounts_auth import ADA, TOKEN, UID, hosted, make_client, sign_in
from test_google_auth import CLIENT, OTHER, check, ticket

from skillforge.api import create_app
from skillforge.api.hosted import COOKIE, LOCAL_USER, NONCE_COOKIE, Hosted, User, current_user, identify, make_cookie, read_cookie
from skillforge.library import Library


def wrong_token(c: TestClient) -> int:
    return c.post("/api/auth/login", json={"token": "wrong"}).status_code


def right_token(c: TestClient) -> int:
    return c.post("/api/auth/login", json={"token": TOKEN}).status_code


# ---- 1 and 2: the lock on wrong access tokens belongs to the access token alone ---------------------------------


def test_1_a_good_google_sign_in_does_not_wipe_the_count_of_wrong_access_tokens(tmp_path):
    c = make_client(tmp_path)
    for _ in range(4):
        assert wrong_token(c) == 401
    assert sign_in(c).status_code == 200  # somebody (or an attacker with any allowed Google account) signs in with Google in between
    assert wrong_token(c) == 401  # the fifth wrong token ...
    assert right_token(c) == 429  # ... still locks sign-in by token: the Google sign-in did not give the guesser a fresh count


def test_2_wrong_google_tickets_never_lock_the_owners_access_token_sign_in(tmp_path):
    c = make_client(tmp_path)
    for _ in range(25):  # an anonymous visitor needs no account for this
        assert sign_in(c, {"aud": "another.apps.googleusercontent.com"}).status_code == 401
    assert right_token(c) == 200


def test_2_wrong_google_tickets_do_not_lock_people_out_of_google_sign_in_either(tmp_path):
    c = make_client(tmp_path)
    for _ in range(25):
        assert sign_in(c, {"aud": "another.apps.googleusercontent.com"}).status_code == 401
    assert sign_in(c).status_code == 200  # nothing can be brute-forced about a ticket (it is a signature from Google), so there is nothing to lock


def test_2_wrong_access_tokens_still_lock_the_token_for_a_minute(tmp_path):
    c = make_client(tmp_path)
    for _ in range(5):
        assert wrong_token(c) == 401
    locked = right_token(c)
    assert locked == 429
    assert sign_in(c).status_code == 200  # the lock is the token's: Google sign-in is a different door


# ---- 6: a nonce really is single use, on the server ------------------------------------------------------------------


def test_6_a_ticket_and_its_nonce_cookie_cannot_be_used_a_second_time_by_anyone(tmp_path):
    c = make_client(tmp_path)
    nonce = c.get("/api/auth/nonce").json()["nonce"]
    cookie = c.cookies.get(NONCE_COOKIE)
    credential = ticket({"nonce": nonce})
    assert c.post("/api/auth/google", json={"credential": credential}).status_code == 200
    copy = TestClient(c.app, base_url="http://localhost")  # another browser that holds a copy of the same nonce cookie
    replay = copy.post("/api/auth/google", json={"credential": credential}, headers={"cookie": f"{NONCE_COOKIE}={cookie}"})
    assert replay.status_code == 401


def test_6_even_a_refused_attempt_uses_up_the_nonce(tmp_path):
    c = make_client(tmp_path)
    nonce = c.get("/api/auth/nonce").json()["nonce"]
    assert c.post("/api/auth/google", json={"credential": ticket({"nonce": nonce}, key=OTHER)}).status_code == 401  # forged
    assert c.post("/api/auth/google", json={"credential": ticket({"nonce": nonce})}).status_code == 401  # a good ticket, same nonce: spent


def test_6_remembering_used_nonces_is_bounded_and_forgets_the_expired():
    from skillforge.api.hosted import SpentNonces

    spent = SpentNonces(limit=3)
    assert spent.claim("a", expires=100, now=0) is True
    assert spent.claim("a", expires=100, now=1) is False
    assert spent.claim("a", expires=100, now=101) is True  # past its expiry the cookie is dead anyway, so it need not be remembered
    for i in range(10):
        spent.claim(f"n{i}", expires=1_000 + i, now=2)
    assert len(spent) <= 3  # a flood cannot grow it without bound


# ---- 3: another cookie on the site must not hide the session -------------------------------------------------------


@pytest.mark.parametrize("first", ['g_state={"i_l":0}', "_analytics=a b c", 'x="unterminated'])
def test_3_the_session_is_found_whatever_other_cookies_the_site_has_in_front_of_it(first):
    h = hosted()
    owner = make_cookie(h)
    person = make_cookie(h, user=User(UID, ADA))
    assert identify(h, {"cookie": f"{first}; {COOKIE}={owner}"}) == LOCAL_USER
    assert identify(h, {"cookie": f"{first}; {COOKIE}={person}"}) == User(UID, ADA)


def test_3_the_same_through_the_real_server(tmp_path):
    h = hosted()
    c = make_client(tmp_path, h)
    r = TestClient(c.app, base_url="http://localhost").get("/api/whoami", headers={"cookie": f'g_state={{"i_l":0}}; {COOKIE}={make_cookie(h, user=User(UID, ADA))}'})
    assert r.status_code == 200 and r.json()["email"] == ADA


# ---- 4: a whole-domain entry means that company's Workspace, not anyone who typed an address at that domain --------------


def test_4_a_ticket_says_which_workspace_domain_the_account_belongs_to():
    assert check(ticket({"hd": "Example.COM"})).hd == "example.com"
    assert check(ticket()).hd == ""  # a personal account has no `hd`
    for odd in (5, ["example.com"], "x" * 300, "not a domain!", "example.com\x1b[2J"):
        assert check(ticket({"hd": odd})).hd == "", odd


@pytest.mark.parametrize(
    "email,hd,entries,allowed",
    [
        ("bob@example.com", "", {"@example.com"}, False),  # a personal Google account that merely uses a company address
        ("bob@example.com", "example.com", {"@example.com"}, True),
        ("bob@example.com", "other.org", {"@example.com"}, False),
        ("bob@sub.example.com", "example.com", {"@example.com"}, False),  # still not a subdomain
        ("bob@example.com", "", {"bob@example.com"}, True),  # an exact address is the owner's own choice of that person: no workspace needed
        ("bob@example.com", "", {"*"}, True),
    ],
)
def test_4_a_domain_entry_wants_a_workspace_account_of_that_domain(email, hd, entries, allowed):
    assert Hosted(token=TOKEN, google_client_id=CLIENT, allowed_emails=frozenset(entries)).email_allowed(email, hd) is allowed


def test_4_signing_in_through_a_domain_entry_needs_the_workspace_claim(tmp_path):
    c = make_client(tmp_path, hosted(allowed_emails=frozenset({"@example.com"})))
    refused = sign_in(c, {"email": "bob@example.com"})  # no `hd`
    assert refused.status_code == 403
    assert "Workspace" in refused.json()["detail"]  # a person at a listed company who used a personal account is told why, not just "not allowed"
    stranger = sign_in(c, {"email": "carol@elsewhere.example"})
    assert stranger.status_code == 403 and "Workspace" not in stranger.json()["detail"]  # and someone at an unlisted domain is not told which domains are
    assert c.get("/api/whoami").status_code == 401  # a refused attempt leaves nobody signed in
    ok = sign_in(c, {"email": "bob@example.com", "hd": "example.com"})
    assert ok.status_code == 200
    assert c.get("/api/whoami").json()["email"] == "bob@example.com"  # and the session keeps working


def test_4_the_session_remembers_how_a_person_got_in_so_a_domain_entry_cannot_stand_in_for_a_removed_address():
    both = hosted(allowed_emails=frozenset({ADA, "@example.com"}))
    by_address = make_cookie(both, now=1_000.0, user=User(UID, ADA))  # she got in by her exact address: no workspace claim
    assert read_cookie(both, by_address, now=1_001.0) is not None
    only_domain = hosted(allowed_emails=frozenset({"@example.com"}))
    assert read_cookie(only_domain, by_address, now=1_001.0) is None  # her address was taken off; the domain entry needs a claim she never had
    by_workspace = make_cookie(only_domain, now=1_000.0, user=User(UID, ADA, "example.com"))
    assert read_cookie(only_domain, by_workspace, now=1_001.0) == User(UID, ADA, "example.com")
    assert read_cookie(hosted(allowed_emails=frozenset({"@other.org"})), by_workspace, now=1_001.0) is None  # the domain entry was removed


# ---- 5: going back down a migration must not delete anything ----------------------------------------------------------


def _fill(connection, table: str, given: dict) -> None:
    """A row with every required column filled, so the test does not depend on the table's exact shape."""
    row = {}
    for _cid, name, typ, notnull, _default, pk in connection.execute(text(f"PRAGMA table_info({table})")):
        if name in given:
            row[name] = given[name]
        elif pk and typ.upper() == "INTEGER":
            continue
        elif notnull:
            row[name] = 0 if typ.upper() in ("INTEGER", "BOOLEAN") else ("[]" if typ.upper() == "JSON" else "x")
    connection.execute(text(f"INSERT INTO {table} ({','.join(row)}) VALUES ({','.join(':' + k for k in row)})"), row)


def test_5_downgrading_the_accounts_migration_keeps_every_job_and_usage_row():
    from alembic import command
    from alembic.config import Config

    from skillforge.db.database import MIGRATIONS, Database

    db = Database(f"sqlite:///{Path(tempfile.mkdtemp(prefix='mig_')) / 'x.db'}")
    try:
        db.migrate()
        with db.engine.begin() as c:
            _fill(c, "build_sessions", {"id": "s1"})
            _fill(c, "jobs", {"session_id": "s1"})
            _fill(c, "model_calls", {"session_id": "s1"})
        config = Config()
        config.set_main_option("script_location", str(MIGRATIONS))
        with db.engine.begin() as connection:
            config.attributes["connection"] = connection
            command.downgrade(config, "0005")
        with db.engine.begin() as c:
            counts = {t: c.execute(text(f"SELECT COUNT(*) FROM {t}")).scalar() for t in ("build_sessions", "jobs", "model_calls")}
            columns = {row[1] for row in c.execute(text("PRAGMA table_info(build_sessions)"))}
        assert counts == {"build_sessions": 1, "jobs": 1, "model_calls": 1}, counts  # the batch rebuild used to cascade-delete the children
        assert "user_id" not in columns  # and the downgrade really did go down
        with db.engine.begin() as connection:
            config.attributes["connection"] = connection
            command.upgrade(config, "head")
        with db.engine.begin() as c:
            assert c.execute(text("SELECT user_id FROM build_sessions")).scalar() == "local"
            assert c.execute(text("SELECT COUNT(*) FROM jobs")).scalar() == 1
    finally:
        db.close()


# ---- found by driving the sign-in screen at phone size: a refusal must be readable by the page ---------------------------


def test_phone_a_trusted_page_on_another_address_can_read_the_401_and_an_untrusted_one_cannot(tmp_path):
    # The documented setup with the pages served from a different address than the API (SKILLFORGE_UI_ORIGINS). The sign-in middleware's own 401 used to be
    # answered outside the CORS layer, so the browser reported "blocked by CORS policy" and the page could not tell "sign in" from "the server is down".
    app = create_app(Library(tmp_path / "library"), origins=["http://ui.example:3000"], hosted=hosted())
    c = TestClient(app, base_url="http://localhost")
    trusted = c.get("/api/library", headers={"origin": "http://ui.example:3000"})
    assert trusted.status_code == 401
    assert trusted.headers.get("access-control-allow-origin") == "http://ui.example:3000"
    stranger = c.get("/api/library", headers={"origin": "http://evil.example"})
    assert stranger.headers.get("access-control-allow-origin") is None  # a page on any other site is told nothing, not even by a 401


# ---- 7: a request nobody identified is never the owner ----------------------------------------------------------------


def test_7_a_hosted_request_that_the_sign_in_middleware_never_saw_is_refused_not_made_the_owner(tmp_path):
    app = create_app(Library(tmp_path / "library"), hosted=hosted())
    request = Request({"type": "http", "app": app, "headers": [], "method": "GET", "path": "/api/x", "query_string": b""})
    with pytest.raises(HTTPException) as caught:
        current_user(request)
    assert caught.value.status_code == 401


def test_7_local_mode_has_no_sign_in_and_the_one_person_is_the_owner(tmp_path):
    app = create_app(Library(tmp_path / "library"))
    request = Request({"type": "http", "app": app, "headers": [], "method": "GET", "path": "/api/x", "query_string": b""})
    assert current_user(request) == LOCAL_USER


def test_7_the_middleware_still_guards_every_route_when_the_app_is_served_under_a_path_prefix(tmp_path):
    c = make_client(tmp_path)

    @c.app.get("/api/open-if-unguarded")  # a route that never asks who is calling, so only the middleware can protect it
    def unguarded() -> dict:
        return {"secret": 1}

    prefixed = TestClient(c.app, base_url="http://localhost", root_path="/app")
    assert prefixed.get("/app/api/open-if-unguarded").status_code == 401
    assert prefixed.get("/app/api/whoami").status_code == 401
    assert prefixed.get("/app/api/library").status_code == 401
    ok = prefixed.get("/app/api/whoami", headers={"authorization": f"Bearer {TOKEN}"})  # and signing in still works behind the prefix
    assert ok.status_code == 200 and ok.json()["id"] == "local"
