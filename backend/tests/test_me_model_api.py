"""GET/POST/DELETE /api/me/model and the test route (slice AI): a person keeps a model of their own; nobody ever sees a key, not even its end.

Every response and every log line of every call is searched for the key.
"""

from __future__ import annotations

import logging

import pytest
from fastapi.testclient import TestClient
from test_model_wiring import ADA_KEY, BOB_KEY, keyed_world

from skillforge.api import create_app
from skillforge.ai.doctor import Ping
from skillforge.builder import Builder, JobRunner
from skillforge.db import Database
from skillforge.library import Library
from skillforge.providers import MockProvider

GOOD = {"provider": "groq", "model": "llama-x", "key": ADA_KEY}


@pytest.fixture
def server(tmp_path):
    made = []

    def make(mocks=None, **options):
        w, built = keyed_world(tmp_path / f"s{len(made)}", mocks or {ADA_KEY: MockProvider([Ping(reply="ok")]), BOB_KEY: MockProvider([])}, **options)
        made.append(w)
        return w

    (tmp_path / "s0").mkdir()
    yield make
    for w in made:
        w.close()


def shown(*responses) -> str:
    return " ".join(r.text for r in responses)


def test_a_person_saves_a_model_and_sees_that_a_key_is_saved_but_never_the_key(server, caplog):
    caplog.set_level(logging.DEBUG)
    w = server()
    ada = w.person(1)
    first = ada.get("/api/me/model")
    assert first.status_code == 200 and first.json()["mode"] == "none" and first.json()["key_saved"] is False
    saved = ada.post("/api/me/model", json=GOOD)
    assert saved.status_code == 200
    body = saved.json()
    assert body["mode"] == "own" and body["provider"] == "groq" and body["model"] == "llama-x" and body["key_saved"] is True and body["key_saved_at"]
    again = ada.get("/api/me/model")
    assert again.json() == body
    everything = shown(first, saved, again, ada.get("/api/provider"))
    assert ADA_KEY not in everything and ADA_KEY[:8] not in everything
    assert ADA_KEY not in caplog.text and ADA_KEY[:8] not in caplog.text  # nor in any log line the server wrote on the way


def test_nobody_else_sees_or_uses_it(server):
    w = server()
    ada, bob = w.person(1), w.person(2)
    ada.post("/api/me/model", json=GOOD)
    seen = bob.get("/api/me/model")
    assert seen.json()["mode"] == "none" and seen.json()["provider"] == "" and seen.json()["key_saved"] is False
    assert bob.get("/api/provider").json()["source"] == "none"
    assert ADA_KEY not in shown(seen, bob.get("/api/provider"))
    bob.delete("/api/me/model")  # Bob removing HIS model must not touch Ada's
    assert ada.get("/api/me/model").json()["key_saved"] is True


def test_a_refused_value_names_the_field_and_never_repeats_the_key(server):
    w = server()
    ada = w.person(1)
    custom = ada.post("/api/me/model", json={**GOOD, "provider": "custom"})
    assert custom.status_code == 400 and {p["name"] for p in custom.json()["problems"]} == {"provider"}
    quoted = ada.post("/api/me/model", json={**GOOD, "key": f'"{ADA_KEY}"'})
    assert quoted.status_code == 400 and {p["name"] for p in quoted.json()["problems"]} == {"key"}
    bearer = ada.post("/api/me/model", json={**GOOD, "key": f"Bearer {ADA_KEY}"})
    assert bearer.status_code == 400
    assert ADA_KEY not in shown(custom, quoted, bearer)
    assert ada.get("/api/me/model").json()["key_saved"] is False  # a refused save stores nothing


def test_a_malformed_body_is_a_422_that_does_not_echo_the_key(server):
    w = server()
    ada = w.person(1)
    wrong_type = ada.post("/api/me/model", json={"provider": "groq", "model": 5, "key": ADA_KEY})
    missing = ada.post("/api/me/model", json={"provider": "groq", "key": ADA_KEY})
    huge = ada.post("/api/me/model", json={**GOOD, "key": ADA_KEY * 500})
    not_json = ada.post("/api/me/model", content=f"{ADA_KEY}".encode(), headers={"content-type": "application/json"})
    for r in (wrong_type, missing, huge, not_json):
        assert r.status_code == 422, r.text
    assert ADA_KEY not in shown(wrong_type, missing, huge, not_json)


def test_deleting_is_safe_to_repeat(server):
    w = server()
    ada = w.person(1)
    ada.post("/api/me/model", json=GOOD)
    first, second = ada.delete("/api/me/model"), ada.delete("/api/me/model")
    assert first.status_code == second.status_code == 200
    assert first.json()["mode"] == second.json()["mode"] == "none" and first.json()["key_saved"] is False


def test_the_owner_is_told_their_model_is_set_elsewhere_and_cannot_save_one_here(server):
    w = server()
    owner = w.owner()
    assert owner.get("/api/me/model").json()["mode"] == "owner"
    for call in (lambda: owner.post("/api/me/model", json=GOOD), lambda: owner.delete("/api/me/model")):
        r = call()
        assert r.status_code == 403 and "owner" in r.json()["detail"].lower()
        assert ADA_KEY not in r.text


def test_nothing_works_without_signing_in(server):
    w = server()
    stranger = TestClient(w.app, base_url="http://localhost")
    for r in (stranger.get("/api/me/model"), stranger.post("/api/me/model", json=GOOD), stranger.delete("/api/me/model"), stranger.post("/api/me/model/test")):
        assert r.status_code == 401


def test_only_get_post_and_delete_exist(server):
    w = server()
    ada = w.person(1)
    for method in (ada.put, ada.patch):
        assert method("/api/me/model", json=GOOD).status_code == 405  # the API's CORS policy allows GET, POST and DELETE only


def test_the_test_button_tries_only_the_persons_own_model(server):
    w = server()
    ada = w.person(1)
    nothing = ada.post("/api/me/model/test").json()
    assert nothing["configured"] is False and nothing["checks"] == [] and w.mock.calls == []
    ada.post("/api/me/model", json=GOOD)
    result = ada.post("/api/me/model/test").json()
    assert result["configured"] is True and result["checks"][0]["ok"] is True and w.mock.calls == []
    assert ADA_KEY not in str(result)


def test_without_accounts_everyone_is_the_owner_and_nothing_can_be_saved(tmp_path):
    db = Database(f"sqlite:///{(tmp_path / 'l.db').as_posix()}")
    db.migrate()
    library = Library(tmp_path / "library")
    builder = Builder(db, library, tmp_path / "builds", provider_factory=lambda: MockProvider([]), runner=JobRunner(inline=True))
    client = TestClient(create_app(library, builder=builder), base_url="http://localhost")
    assert client.get("/api/me/model").json()["mode"] == "owner"
    assert client.post("/api/me/model", json=GOOD).status_code == 403
    assert client.delete("/api/me/model").status_code == 403
    builder.close()
