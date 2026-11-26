"""Slice AK, task 1: the six small fixes the independent review of slice AJ left (docs/superpowers/specs/2026-11-26-completion-batch-design.md).

Offline: fakes only, no key, no network.
"""

from __future__ import annotations

import asyncio
import importlib.util
from pathlib import Path

import pytest
from test_accounts_auth import env, sign_in
from test_admin_block import aw, block  # noqa: F401  (the fixture, and the helper)
from test_ai_service import Answer as Ans
from test_ai_service import Fake, gen, service
from test_model_access import KEY, World as ModelWorld

from skillforge.ai.tasks import Task
from skillforge.api.hosted import Hosted
from skillforge.builder import ModelAccess, ModelOptions
from skillforge.builder.keybox import KeyBox
from skillforge.db import Database
from skillforge.db.users import UserStore
from skillforge.library import Library
from skillforge.providers import ProviderError

ROOT = Path(__file__).resolve().parents[2]


def people(owner) -> dict[str, dict]:
    return {p["id"]: p for p in owner.get("/api/admin/people").json()["people"]}


# ---- (a) a refused sign-in changes nothing -------------------------------------------------------------------------------------------------------


def test_a_turned_off_persons_refused_sign_in_changes_nothing_about_them(aw):
    w = aw()
    w.person(1)
    uid = w.uid(1)
    owner = w.owner()
    before = people(owner)[uid]
    block(owner, uid)
    refused = sign_in(w.person_client(), {"sub": "sub-1", "email": "p1@example.com", "name": "Renamed While Blocked", "picture": "https://example.com/new.png"})
    assert refused.status_code == 403
    after = people(owner)[uid]
    assert (after["name"], after["email"], after["last_seen"]) == (before["name"], before["email"], before["last_seen"])


def test_a_person_who_is_not_turned_off_is_still_updated_by_signing_in_again(aw):
    w = aw()
    w.person(1)
    uid = w.uid(1)
    owner = w.owner()
    assert sign_in(w.person_client(), {"sub": "sub-1", "email": "p1@example.com", "name": "A New Name"}).status_code == 200
    assert people(owner)[uid]["name"] == "A New Name"


# ---- (c) turned-off people first, and the list says when it is cut ---------------------------------------------------------------------------------


def test_the_list_puts_turned_off_people_first_and_counts_everybody(aw):
    w = aw()
    for n in (1, 2, 3):
        w.person(n)
    store = UserStore(w.db)
    store.set_blocked(w.uid(1), True)  # the OLDEST sign-in, and turned off
    shown = store.all(limit=2)
    assert [p.email for p in shown] == ["p1@example.com", "p3@example.com"]  # the turned-off one first, then the latest sign-in
    assert store.count() == 3


def test_the_people_route_says_how_many_there_are_when_it_shows_fewer(aw, monkeypatch):
    from skillforge.api import admin

    w = aw()
    for n in (1, 2, 3):
        w.person(n)
    owner = w.owner()
    assert owner.get("/api/admin/people").json()["total"] == 3
    monkeypatch.setattr(admin, "PEOPLE_LIMIT", 2)
    cut = owner.get("/api/admin/people").json()
    assert len(cut["people"]) == 2 and cut["total"] == 3


# ---- (d) the block lookup is not done on the event loop -------------------------------------------------------------------------------------------


def test_the_block_lookup_does_not_run_on_the_event_loop(aw, monkeypatch):
    w = aw()
    ada = w.person(1)
    seen: list[str] = []
    real = UserStore.is_blocked

    def watching(self, user_id):
        try:
            asyncio.get_running_loop()
            seen.append("on the loop")
        except RuntimeError:
            seen.append("off the loop")
        return real(self, user_id)

    monkeypatch.setattr(UserStore, "is_blocked", watching)
    assert ada.get("/api/builds").status_code == 200
    assert seen and set(seen) == {"off the loop"}


# ---- (e) the browser check's launcher makes its builder the way the real serve does -----------------------------------------------------------------


def test_the_launcher_of_the_browser_check_gives_its_builder_the_limits_and_the_key_box(monkeypatch, tmp_path):
    monkeypatch.setenv("SKILLFORGE_DATA_DIR", str(tmp_path / "data"))
    spec = importlib.util.spec_from_file_location("hosted_server_under_test", ROOT / "frontend" / "e2e" / "hosted_server.py")
    launcher = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(launcher)
    hosted = Hosted.from_env(env(SKILLFORGE_PERSON_MAX_BUILDS="3", SKILLFORGE_PERSON_DISK_MB="9"))
    db = Database(f"sqlite:///{(tmp_path / 'l.db').as_posix()}")
    db.migrate()
    builder = launcher.make_builder(hosted, Library(tmp_path / "library"), db, tmp_path / "builds")
    try:
        assert builder.space.limits == hosted.person_limits and builder.space.limits.max_builds == 3
        assert builder.access.options.keybox is not None
    finally:
        db.close()


# ---- (f) a person on the shared model is not told about owner settings ------------------------------------------------------------------------------


def test_a_person_on_the_servers_model_is_not_pointed_at_owner_settings_and_the_owner_still_is(tmp_path):
    w = ModelWorld(tmp_path, shared=10)
    ada = w.person()
    server = Fake([gen(), gen()], name="server", model="server-1")
    access = ModelAccess(w.db, lambda: service(server, max_calls=1), ModelOptions(keybox=KeyBox("a-long-enough-access-token-1234567890"), shared_calls_per_day=10))
    person = access.provider_for(ada, session_id=None, job_id=None)
    person.generate(Task.DESIGN, Ans, "p")
    with pytest.raises(ProviderError) as caught:
        person.generate(Task.DESIGN, Ans, "p")  # the server's own call budget is spent
    assert "LLM_MAX_CALLS" not in str(caught.value) and "model calls" in str(caught.value) and caught.value.kind == "budget"

    owner = access.provider_for("local", session_id=None, job_id=None)
    owner.generate(Task.DESIGN, Ans, "p")
    with pytest.raises(ProviderError) as owners:
        owner.generate(Task.DESIGN, Ans, "p")
    assert "LLM_MAX_CALLS" in str(owners.value)  # the owner has that setting and is told its name
    assert KEY not in str(caught.value)
