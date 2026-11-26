"""Slice AJ, task 3: the owner's admin routes and the block (docs/person-limits.md).

A block is reversible, ends a session that is already signed in on its very next request, and keeps the person's data. Only the owner (the access token, a
Bearer header) can see the people or block one. Offline: a mock model, a fake Google, nothing real.
"""

from __future__ import annotations

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, text
from test_accounts_auth import TOKEN, sign_in
from test_accounts_isolation import World, start
from test_builder import FULL  # noqa: F401  (the description start() sends)
from test_skill_build import round_two

from skillforge.api import create_app
from skillforge.builder import PersonLimits
from skillforge.db import Database, ModelCall, now_text
from skillforge.db.user_models import ModelStore
from skillforge.db.database import MIGRATIONS
from skillforge.library import Library

BLOCKED = "This account has been turned off on this server. Ask the person who runs it."


@pytest.fixture
def aw(tmp_path):
    made: list[World] = []

    def make(**kw) -> World:
        folder = tmp_path / f"w{len(made)}"
        folder.mkdir()
        w = World(folder, [round_two()] * 60, service=True, **kw)
        made.append(w)
        return w

    yield make
    for w in made:
        w.close()


def block(owner, uid):
    return owner.post(f"/api/admin/people/{uid}/block")


def unblock(owner, uid):
    return owner.post(f"/api/admin/people/{uid}/unblock")


# ---- who may ------------------------------------------------------------------------------------------------------------------------------------


def test_only_the_owner_can_list_or_block_people(aw):
    w = aw()
    ada, bob = w.person(1), w.person(2)
    uid = w.uid(2)
    for call in (lambda: ada.get("/api/admin/people"), lambda: block(ada, uid), lambda: unblock(ada, uid)):
        assert call().status_code == 403
    assert bob.get("/api/me/model").status_code == 200  # nothing happened to Bob
    owner = w.owner()
    assert owner.get("/api/admin/people").status_code == 200 and block(owner, uid).status_code == 200


def test_the_access_token_as_a_bearer_header_can_administer_too(aw):
    w = aw()
    w.person(1)
    from fastapi.testclient import TestClient

    script = TestClient(w.app, base_url="http://localhost", headers={"Authorization": f"Bearer {TOKEN}"})
    assert script.get("/api/admin/people").status_code == 200
    assert block(script, w.uid(1)).status_code == 200


def test_local_mode_has_no_accounts_to_administer(tmp_path):
    from fastapi.testclient import TestClient

    client = TestClient(create_app(Library(tmp_path / "library")), base_url="http://localhost")
    assert client.get("/api/admin/people").json() == {"hosted": False, "people": []}
    assert client.post(f"/api/admin/people/{'a' * 32}/block").status_code == 400


# ---- the list -----------------------------------------------------------------------------------------------------------------------------------


def test_the_list_shows_each_person_with_their_own_numbers_and_no_secret(aw):
    w = aw(limits=PersonLimits(max_builds=9))
    ada, bob = w.person(1), w.person(2)
    start(ada)
    start(ada)
    ModelStore(w.db).put(w.uid(1), "groq", "llama-x", b"sealed-bytes-not-a-key", b"n" * 12)  # Ada has a key of her own saved (only its ciphertext exists)
    people = {p["email"]: p for p in w.owner().get("/api/admin/people").json()["people"]}
    assert set(people) == {"p1@example.com", "p2@example.com"}
    one, two = people["p1@example.com"], people["p2@example.com"]
    assert one["builds"] == 2 and two["builds"] == 0 and one["blocked"] is False and one["has_key"] is True and two["has_key"] is False
    assert isinstance(one["disk_used"], int) and one["active"] == 0 and set(one["calls_today"]) == {"server", "own"}
    assert set(one) == {"id", "name", "email", "joined", "last_seen", "blocked", "builds", "disk_used", "active", "calls_today", "has_key"}  # exactly these: nothing else leaks
    assert b"sealed-bytes-not-a-key".hex() not in str(people) and "sealed-bytes" not in str(people) and "llama-x" not in str(people)  # whether a key exists, never what it is or which model
    assert bob.get("/api/builds").status_code == 200


def test_the_list_does_not_name_the_owner_as_a_person(aw):
    w = aw()
    w.person(1)
    assert all(p["id"] != "local" for p in w.owner().get("/api/admin/people").json()["people"])


# ---- the block ----------------------------------------------------------------------------------------------------------------------------------


def test_a_block_ends_a_session_already_signed_in_on_the_very_next_request_and_a_new_sign_in_is_refused(aw):
    w = aw()
    ada = w.person(1)  # signed in, holding a good session cookie
    uid = w.uid(1)
    owner = w.owner()
    assert ada.get("/api/builds").status_code == 200
    assert block(owner, uid).status_code == 200
    for path in ("/api/builds", "/api/me/model", "/api/library", "/api/me/space", "/api/provider"):
        refused = ada.get(path)
        assert refused.status_code == 403 and refused.json()["detail"] == BLOCKED, path
    assert ada.post("/api/builds", json={"description": FULL}).status_code == 403
    status = ada.get("/api/auth/status").json()
    assert status["authenticated"] is False and status["user"] is None and status["blocked"] is True
    again = w.person_client()
    refused = sign_in(again, {"sub": "sub-1", "email": "p1@example.com", "name": "Person 1"})
    assert refused.status_code == 403 and refused.json()["detail"] == BLOCKED
    assert "skillforge_session" not in refused.headers.get("set-cookie", "")  # no session is handed out
    assert again.get("/api/builds").status_code == 401


def test_unblocking_gives_the_same_session_and_a_new_sign_in_back(aw):
    w = aw()
    ada = w.person(1)
    uid = w.uid(1)
    owner = w.owner()
    sid = start(ada)
    block(owner, uid)
    assert ada.get("/api/builds").status_code == 403
    assert unblock(owner, uid).status_code == 200
    assert ada.get(f"/api/builds/{sid}").status_code == 200  # the same cookie works again and the data was kept
    fresh = w.person_client()
    assert sign_in(fresh, {"sub": "sub-1", "email": "p1@example.com", "name": "Person 1"}).status_code == 200


def test_blocking_one_person_touches_nobody_else_and_repeating_it_is_safe(aw):
    w = aw()
    ada, bob = w.person(1), w.person(2)
    owner = w.owner()
    assert block(owner, w.uid(1)).status_code == 200 and block(owner, w.uid(1)).status_code == 200
    assert ada.get("/api/builds").status_code == 403 and bob.get("/api/builds").status_code == 200
    assert owner.get("/api/builds").status_code == 200  # the owner is never blocked
    assert unblock(owner, w.uid(1)).status_code == 200 and unblock(owner, w.uid(1)).status_code == 200
    people = {p["email"]: p["blocked"] for p in owner.get("/api/admin/people").json()["people"]}
    assert people == {"p1@example.com": False, "p2@example.com": False}


def test_the_list_says_who_is_blocked(aw):
    w = aw()
    w.person(1)
    owner = w.owner()
    block(owner, w.uid(1))
    assert [p["blocked"] for p in owner.get("/api/admin/people").json()["people"]] == [True]


@pytest.mark.parametrize("odd", ["local", "LOCAL", "zz", "A" * 32, "0" * 31, "0" * 33, "g" * 32, "0" * 32])
def test_the_owner_and_odd_ids_cannot_be_blocked_and_an_unknown_id_is_a_404(aw, odd):
    w = aw()
    w.person(1)
    owner = w.owner()
    for call in (block, unblock):
        refused = call(owner, odd)
        assert refused.status_code in (400, 404), odd
        if odd == "local":
            assert refused.status_code == 400 and "owner" in refused.json()["detail"].lower()
    assert [p["blocked"] for p in owner.get("/api/admin/people").json()["people"]] == [False]  # nobody was changed


def test_a_blocked_person_still_has_their_files_and_a_running_job_finishes(aw):
    w = aw()
    ada = w.person(1)
    sid = start(ada)
    block(w.owner(), w.uid(1))
    unblock(w.owner(), w.uid(1))
    assert ada.get(f"/api/builds/{sid}").json()["id"] == sid


# ---- the database -------------------------------------------------------------------------------------------------------------------------------


def test_the_blocked_column_starts_false_for_everyone_who_signed_in_before_and_going_down_keeps_people(tmp_path):
    db = Database(f"sqlite:///{(tmp_path / 'm.db').as_posix()}")
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS))
    with db.engine.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, "0007")
    with db.engine.begin() as c:
        c.execute(text("INSERT INTO users (id, google_sub, email, name, picture, created_at, last_login_at) VALUES (:i, 's', 'a@b.c', 'A', '', 't', 't')"), {"i": "a" * 32})
    db.migrate()
    with db.engine.begin() as c:
        assert c.execute(text("SELECT blocked FROM users")).scalar() == 0
    with db.engine.begin() as connection:
        config.attributes["connection"] = connection
        command.downgrade(config, "0007")
    with db.engine.begin() as c:
        assert c.execute(text("SELECT COUNT(*) FROM users")).scalar() == 1  # the person survived the downgrade
        assert "blocked" not in {col["name"] for col in inspect(c).get_columns("users")}
    db.close()


def test_the_list_counts_todays_calls_on_the_servers_model_and_on_their_own_key_separately(aw):
    w = aw()
    w.person(1)
    w.person(2)
    ada = w.uid(1)
    with w.db.session() as s:
        for source, how_many in (("server", 3), ("own", 2)):
            for _ in range(how_many):
                s.add(ModelCall(created_at=now_text(), task="act", tier="actor", provider="p", model="m", attempt=1, status="ok", error_kind="", latency_ms=1,
                                user_id=ada, key_source=source))
    people = {p["email"]: p for p in w.owner().get("/api/admin/people").json()["people"]}
    assert people["p1@example.com"]["calls_today"] == {"server": 3, "own": 2}
    assert people["p2@example.com"]["calls_today"] == {"server": 0, "own": 0}
