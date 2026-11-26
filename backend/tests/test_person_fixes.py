"""Slice AJ, task 1: the small fixes the independent review and the owner's real tests found (docs/superpowers/specs/2026-11-26-person-limits-and-admin-design.md).

Offline: fakes only, no key, no network.
"""

from __future__ import annotations

import json

import pytest
from sqlalchemy import select
from test_ai_service import Fake, Recorder, service
from test_ai_service import Answer as Ans
from test_me_model_api import GOOD, server  # noqa: F401  (the fixture)
from test_model_access import KEY, World

from skillforge.ai import AIService
from skillforge.ai.tasks import Task
from skillforge.builder.keybox import KeyBox
from skillforge.builder.model_access import ModelAccess, ModelOptions
from skillforge.db import ModelCall
from skillforge.providers import ProviderError
from skillforge.settings import SettingsError, check_person_model


def problems_of(exc: SettingsError) -> dict[str, str]:
    return {p["name"]: p["message"] for p in exc.problems}


# ---- (c) Bearer with a colon ---------------------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("bad", ["Bearer:" + KEY, "bearer: " + KEY, "BEARER:abc", "Bearer " + KEY, "bearer"])
def test_a_key_that_starts_with_bearer_is_refused_whatever_separates_it(bad):
    with pytest.raises(SettingsError) as caught:
        check_person_model("groq", "model-x", bad)
    assert "Bearer" in problems_of(caught.value)["key"]


def test_a_key_that_merely_begins_with_those_letters_is_still_a_key():
    assert check_person_model("groq", "model-x", "bearerOfGoodKey123")[2] == "bearerOfGoodKey123"


# ---- (d) no ".env" advice for a person ----------------------------------------------------------------------------------------------------------


def test_the_unsafe_characters_refusal_for_a_person_does_not_send_them_to_a_file_they_do_not_have():
    with pytest.raises(SettingsError) as caught:
        check_person_model("groq", "bad model!", "a key with spaces")
    said = " ".join(problems_of(caught.value).values())
    assert ".env" not in said and "Only letters, digits" in said


# ---- (a) an empty key box keeps the saved key ---------------------------------------------------------------------------------------------------


def test_saving_with_the_key_box_empty_keeps_the_saved_key_and_changes_the_model(tmp_path):
    w = World(tmp_path)
    ada = w.person()
    w.access.save(ada, "groq", "model-one", KEY)
    view = w.access.save(ada, "groq", "model-two", "")
    assert view["model"] == "model-two" and view["key_saved"] is True
    assert w.access._open(ada, w.access.store.get(ada)) == KEY  # the very same key, not a blank one


def test_changing_the_provider_with_the_key_box_empty_asks_for_the_key_and_changes_nothing(tmp_path):
    w = World(tmp_path)
    ada = w.person()
    w.access.save(ada, "groq", "model-one", KEY)
    with pytest.raises(SettingsError) as caught:
        w.access.save(ada, "openai", "model-two", "")
    assert "new provider" in problems_of(caught.value)["key"]
    stored = w.access.store.get(ada)
    assert (stored.provider, stored.model) == ("groq", "model-one")


def test_an_empty_key_with_nothing_saved_is_still_refused(tmp_path):
    w = World(tmp_path)
    with pytest.raises(SettingsError) as caught:
        w.access.save(w.person(), "groq", "model-one", "")
    assert problems_of(caught.value)["key"] == "Paste your key."


def test_a_saved_key_that_can_no_longer_be_opened_is_not_kept_by_an_empty_box(tmp_path):
    w = World(tmp_path)
    ada = w.person()
    w.access.save(ada, "groq", "model-one", KEY)
    changed = ModelAccess(w.db, lambda: AIService.single(w.server), ModelOptions(keybox=KeyBox("a-different-access-token-0987654321"), build=w.options.build))
    with pytest.raises(SettingsError) as caught:
        changed.save(ada, "groq", "model-two", "")
    assert "Paste your key" in problems_of(caught.value)["key"]


def test_the_route_accepts_an_empty_key_for_a_saved_one_and_refuses_it_when_nothing_is_saved(server):
    w = server()
    ada = w.person(1)
    assert ada.post("/api/me/model", json={**GOOD, "key": ""}).status_code == 400
    assert ada.post("/api/me/model", json=GOOD).status_code == 200
    again = ada.post("/api/me/model", json={**GOOD, "model": "llama-y", "key": ""})
    assert again.status_code == 200 and again.json()["model"] == "llama-y" and again.json()["key_saved"] is True


# ---- (f) an attempt that fails with an error that is not a provider error is still recorded -----------------------------------------------------


class Weird(Fake):
    def generate(self, *args, **kwargs):
        raise RuntimeError("the provider's library broke")


def test_an_attempt_that_fails_with_an_unexpected_error_leaves_a_row_and_is_still_raised():
    rec = Recorder()
    svc = service(Weird([])).with_recorder(rec)
    with pytest.raises(RuntimeError):
        svc.generate(Task.DESIGN, Ans, "p")
    assert [(r.status, r.error_kind) for r in rec.rows] == [("error", "other")]  # a call somebody paid for is counted


def test_such_a_row_counts_against_a_persons_allowance(tmp_path):
    w = World(tmp_path, shared=2)
    ada = w.person()
    w.server.generate = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("the provider's library broke"))
    for _ in range(2):
        provider = w.access.provider_for(ada, session_id=None, job_id=None)
        with pytest.raises(RuntimeError):
            provider.generate(Task.DESIGN, Ans, "p")
    assert w.access.used_today(ada) == 2
    with w.db.session() as s:
        assert {r.error_kind for r in s.execute(select(ModelCall)).scalars()} == {"other"}


# ---- (e) a person's provider errors do not point at a .env file ---------------------------------------------------------------------------------


def test_a_rejected_key_of_a_persons_own_says_where_to_fix_it_in_the_app(tmp_path):
    w = World(tmp_path)
    ada = w.person()
    w.access.save(ada, "groq", "model-one", KEY)
    w.own.results = [ProviderError("The API key was rejected (401). Check GROQ_API_KEY in .env.", kind="auth", retryable=False)]
    shown = json.dumps(w.access.test(ada))
    assert ".env" not in shown and "Settings" in shown and KEY not in shown


def test_a_missing_model_of_a_persons_own_says_where_to_fix_it_in_the_app(tmp_path):
    w = World(tmp_path)
    ada = w.person()
    w.access.save(ada, "groq", "model-one", KEY)
    w.own.results = [ProviderError("Model 'model-one' was not found.\nCheck LLM_MODEL in .env. A model can appear in the list and still be retired.", kind="model_missing", retryable=False)]
    shown = json.dumps(w.access.test(ada))
    assert ".env" not in shown and "Settings" in shown


def test_the_servers_own_model_keeps_its_env_advice_for_the_owner(tmp_path):
    w = World(tmp_path)
    svc = w.access.provider_for("local", session_id=None, job_id=None)
    w.server.results = [ProviderError("The API key was rejected (401). Check GROQ_API_KEY in .env.", kind="auth", retryable=False)]
    with pytest.raises(ProviderError) as caught:
        svc.generate(Task.DESIGN, Ans, "p")
    assert "GROQ_API_KEY in .env" in str(caught.value)  # the owner has that file
