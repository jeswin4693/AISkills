"""Slice X over HTTP: the Settings routes, the model lookup that now sees a changed `.env` at once, and the hosted version, where all of
it is off. The rule behind every test here: no answer and no error ever repeats a key."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from skillforge.api import create_app
from skillforge.api.hosted import Hosted
from skillforge.builder.provider import env_provider
from skillforge.library import Library
from skillforge.settings import EnvSettings

KEY = "AIzaSyAPI-KEY_0123456789abcdef"
TOKEN = "a-long-enough-access-token-1234567890"


@pytest.fixture(autouse=True)
def private_environment(monkeypatch):
    monkeypatch.setattr(os, "environ", dict(os.environ))


def make(tmp_path: Path, text: str | None = None, *, environ: dict | None = None, **kw):
    path = tmp_path / ".env"
    if text is not None:
        path.write_text(text, encoding="utf-8")
    settings = EnvSettings(path, environ if environ is not None else {})
    client = TestClient(create_app(Library(tmp_path / "library"), env_settings=settings, **kw), base_url="http://localhost")
    return client, settings, path


def row(body: dict, name: str) -> dict:
    return next(s for s in body["settings"] if s["name"] == name)


def test_the_page_can_read_what_is_set_and_which_model_is_in_use(tmp_path):
    client, _settings, _path = make(tmp_path, "LLM_MODEL=m1\n")
    r = client.get("/api/settings")
    assert r.status_code == 200
    body = r.json()
    assert body["file"] == ".env" and [g["key"] for g in body["groups"]][:2] == ["model", "keys"]
    assert row(body, "LLM_MODEL")["value"] == "m1" and row(body, "GOOGLE_API_KEY")["set"] is False
    assert body["status"]["configured"] is False and "LLM_PROVIDER" in body["status"]["detail"]


def test_a_save_writes_the_file_and_the_answer_is_the_new_state_with_no_key_in_it(tmp_path, monkeypatch):
    path = tmp_path / ".env"
    monkeypatch.setattr("skillforge.settings.store.default_env_file", lambda: path)
    settings = EnvSettings(path)
    client = TestClient(create_app(Library(tmp_path / "library"), env_settings=settings), base_url="http://localhost")
    r = client.post("/api/settings", json={"changes": {"LLM_PROVIDER": "gemini", "LLM_MODEL": "m-1", "GOOGLE_API_KEY": KEY}})
    assert r.status_code == 200
    body = r.json()
    assert KEY not in r.text and KEY[-6:] not in r.text
    assert row(body, "GOOGLE_API_KEY")["set"] is True and row(body, "GOOGLE_API_KEY")["source"] == "file" and "value" not in row(body, "GOOGLE_API_KEY")
    assert body["status"]["configured"] is True and body["status"]["provider"] == "gemini" and body["status"]["model"] == "m-1"
    assert f"GOOGLE_API_KEY={KEY}" in path.read_text(encoding="utf-8")
    again = client.get("/api/settings")
    assert KEY not in again.text and again.json()["status"]["model"] == "m-1"


def test_a_key_can_be_removed_again(tmp_path):
    client, _s, path = make(tmp_path, f"GOOGLE_API_KEY={KEY}\n")
    r = client.post("/api/settings", json={"changes": {"GOOGLE_API_KEY": None}})
    assert r.status_code == 200 and row(r.json(), "GOOGLE_API_KEY")["set"] is False and KEY not in path.read_text(encoding="utf-8")


def test_a_refused_value_is_a_400_that_names_the_setting_and_never_repeats_the_value(tmp_path):
    client, _s, path = make(tmp_path, "LLM_MODEL=keep\n")
    before = path.read_bytes()
    bad = "has a space and a secret"
    r = client.post("/api/settings", json={"changes": {"GOOGLE_API_KEY": bad, "LLM_MODEL": "fine", "OPENAI_API_KEY": KEY, "LLM_MAX_CALLS": "zero"}})
    assert r.status_code == 400
    body = r.json()
    assert {p["name"] for p in body["problems"]} == {"GOOGLE_API_KEY", "LLM_MAX_CALLS"} and "GOOGLE_API_KEY" in body["detail"]
    assert bad not in r.text and "secret" not in r.text.replace("a secret", "") and KEY not in r.text
    assert path.read_bytes() == before


def test_a_setting_that_comes_from_the_environment_cannot_be_changed(tmp_path):
    client, _s, path = make(tmp_path, "LLM_MODEL=file\n", environ={"LLM_MODEL": "env"})
    r = client.post("/api/settings", json={"changes": {"LLM_MODEL": "x"}})
    assert r.status_code == 400 and "environment" in r.json()["detail"] and path.read_text(encoding="utf-8") == "LLM_MODEL=file\n"


@pytest.mark.parametrize("body", [
    b"not json", b"[]", b"null", b'"text"', b'{"x": 1}', b'{"changes": []}', b'{"changes": {}}', b'{"changes": "LLM_MODEL=x"}',
    b'{"changes": {"LLM_MODEL": 5}}', b'{"changes": {"LLM_MODEL": {"a": 1}}}', b'{"changes": {"LLM_MODEL": ["x"]}}',
    b'{"changes": {"PATH": "x"}}', b'{"changes": {"SKILLFORGE_ACCESS_TOKEN": "a-long-enough-access-token-1234567890"}}',
    b"[" * 6000 + b"]" * 6000, b'{"changes": {"GOOGLE_API_KEY": 123456789012}}',
])
def test_a_malformed_or_forbidden_request_is_a_400_and_changes_nothing_and_echoes_nothing(tmp_path, body):
    client, _s, path = make(tmp_path)
    r = client.post("/api/settings", content=body, headers={"Content-Type": "application/json"})
    assert r.status_code == 400
    for fragment in ("123456789012", "a-long-enough", "LLM_MODEL=x"):
        assert fragment not in r.text
    assert not path.exists()


def test_a_request_that_is_too_large_is_refused_before_it_is_read(tmp_path):
    client, _s, path = make(tmp_path)
    r = client.post("/api/settings", content=b'{"changes": {"LLM_MODEL": "' + b"a" * 30_000 + b'"}}', headers={"Content-Type": "application/json"})
    assert r.status_code == 413 and not path.exists()


def test_a_page_on_another_site_cannot_change_a_setting(tmp_path):
    client, _s, path = make(tmp_path)
    r = client.post("/api/settings", json={"changes": {"LLM_MODEL": "x"}}, headers={"Origin": "http://evil.example"})
    assert r.status_code == 403 and not path.exists()
    ok = client.post("/api/settings", json={"changes": {"LLM_MODEL": "x"}}, headers={"Origin": "http://localhost:3000"})
    assert ok.status_code == 200 and path.exists()


def test_the_hosted_version_refuses_every_settings_route_and_writes_nothing(tmp_path):
    client, _s, path = make(tmp_path, "LLM_MODEL=keep\n", hosted=Hosted(token=TOKEN))
    assert client.post("/api/auth/login", json={"token": TOKEN}).status_code == 200
    before = path.read_bytes()
    g = client.get("/api/settings")
    p = client.post("/api/settings", json={"changes": {"LLM_MODEL": "x", "GOOGLE_API_KEY": KEY}})
    assert g.status_code == 403 and p.status_code == 403 and "hosted" in g.json()["detail"]
    assert KEY not in p.text and path.read_bytes() == before


def test_the_hosted_version_still_asks_for_the_sign_in_first(tmp_path):
    client, _s, _p = make(tmp_path, hosted=Hosted(token=TOKEN))
    assert client.get("/api/settings").status_code == 401 and client.post("/api/settings", json={"changes": {"LLM_MODEL": "x"}}).status_code == 401


# ---- the model lookup ---------------------------------------------------------------------------------------------


def test_the_model_lookup_sees_a_changed_env_file_without_a_restart(tmp_path, monkeypatch):
    path = tmp_path / ".env"
    monkeypatch.setattr("skillforge.settings.store.default_env_file", lambda: path)
    path.write_text("LLM_PROVIDER=gemini\nLLM_MODEL=first\nGOOGLE_API_KEY=k1\n", encoding="utf-8")
    assert env_provider().model == "first"
    path.write_text("LLM_PROVIDER=gemini\nLLM_MODEL=second\nGOOGLE_API_KEY=k1\n", encoding="utf-8")
    assert env_provider().model == "second"


def test_a_real_environment_variable_still_wins_over_the_file(tmp_path, monkeypatch):
    path = tmp_path / ".env"
    monkeypatch.setattr("skillforge.settings.store.default_env_file", lambda: path)
    monkeypatch.setenv("LLM_MODEL", "from-environment")
    path.write_text("LLM_PROVIDER=gemini\nLLM_MODEL=from-file\nGOOGLE_API_KEY=k1\n", encoding="utf-8")
    assert env_provider().model == "from-environment"


def test_the_check_route_uses_what_was_just_saved(tmp_path, monkeypatch):
    path = tmp_path / ".env"
    monkeypatch.setattr("skillforge.settings.store.default_env_file", lambda: path)
    client = TestClient(create_app(Library(tmp_path / "library"), env_settings=EnvSettings(path)), base_url="http://localhost")
    assert client.post("/api/provider/check").json()["configured"] is False
    client.post("/api/settings", json={"changes": {"LLM_PROVIDER": "gemini", "LLM_MODEL": "m-2", "GOOGLE_API_KEY": KEY}})
    status = client.get("/api/provider").json()
    assert status["configured"] is True and status["model"] == "m-2" and KEY not in json.dumps(status)
