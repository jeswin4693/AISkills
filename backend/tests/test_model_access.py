"""Which model a person's calls use, and whether they may use it now (slice AI, docs/per-person-keys.md).

Offline: a fake `build` stands in for the real provider (and records exactly what it was given), and the server's own model is a fake too.
"""

from __future__ import annotations

import json
import threading
import time
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select
from test_accounts_auth import env
from test_ai_service import Answer, Fake, gen

from skillforge.ai import AIService
from skillforge.ai.tasks import Task
from skillforge.api.hosted import Hosted, HostedConfigError
from skillforge.builder.keybox import KeyBox
from skillforge.builder.model_access import ModelAccess, ModelAccessError, ModelOptions
from skillforge.db import LOCAL_USER_ID, Database, ModelCall
from skillforge.db.users import UserStore
from skillforge.providers import ProviderError
from skillforge.settings import SettingsError

TOKEN = "a-long-enough-access-token-1234567890"
KEY = "AIzaSyDistinctiveFakeKeyForTests_0123456789"
NOON = datetime(2026, 11, 26, 12, 0, tzinfo=timezone.utc)


class Slow(Fake):
    """A model that takes a moment to answer, so several runs are really in flight together."""

    def __init__(self, *args, delay: float = 0.0, **kwargs):
        super().__init__(*args, **kwargs)
        self.delay = delay

    def generate(self, *args, **kwargs):
        time.sleep(self.delay)
        return super().generate(*args, **kwargs)


class World:
    def __init__(self, tmp_path, *, shared: int = 0, keybox: bool = True, token: str = TOKEN, clock=None, delay: float = 0.0):
        self.db = Database(f"sqlite:///{(tmp_path / 'a.db').as_posix()}")
        self.db.migrate()
        self.built: list[dict] = []
        self.server = Slow([gen()] * 60, name="server", model="server-1", delay=delay)
        self.own = Fake([gen()] * 60, name="own", model="own-1")

        def build(env_mapping):
            self.built.append(dict(env_mapping))
            return AIService.single(self.own)

        self.options = ModelOptions(
            keybox=KeyBox(token) if keybox else None, shared_calls_per_day=shared, build=build, clock=clock or (lambda: datetime.now(timezone.utc)),
        )
        self.access = ModelAccess(self.db, lambda: AIService.single(self.server), self.options)
        self.users = UserStore(self.db)

    def person(self, n: int = 1) -> str:
        return self.users.upsert_google(f"sub-{n}", f"p{n}@example.com", f"P{n}").id

    def rows(self, user: str) -> list[tuple]:
        with self.db.session() as s:
            found = s.execute(select(ModelCall).where(ModelCall.user_id == user).order_by(ModelCall.id)).scalars().all()
            return [(r.key_source, r.task, r.status, r.session_id) for r in found]

    def add_row(self, user: str, created_at: datetime, source: str = "server", status: str = "ok") -> None:
        with self.db.session() as s:
            s.add(ModelCall(created_at=created_at.isoformat(timespec="milliseconds"), task="act", tier="actor", provider="p", model="m", attempt=1, status=status,
                            error_kind="", latency_ms=1, user_id=user, key_source=source))


def another(tmp_path, name: str, **kw) -> World:
    """A second world (its own database) inside one test."""
    (tmp_path / name).mkdir()
    return World(tmp_path / name, **kw)


def ask(provider) -> None:
    provider.generate(Task.DESIGN, Answer, "p")


@pytest.fixture
def world(tmp_path):
    w = World(tmp_path)
    yield w
    w.db.close()


# ---- the owner ----------------------------------------------------------------------------------------


def test_the_owner_uses_the_servers_model_and_is_never_capped_or_looked_up(tmp_path, monkeypatch):
    w = World(tmp_path, shared=1)
    monkeypatch.setattr(w.access.store, "get", lambda *_: pytest.fail("the owner has no stored model to look up"))
    for _ in range(5):  # a cap of 1 would have stopped a person after one
        ask(w.access.provider_for(LOCAL_USER_ID))
    assert len(w.server.calls) == 5 and w.built == []
    assert [r[0] for r in w.rows(LOCAL_USER_ID)] == ["server"] * 5  # recorded now for every kind of run, not only builder jobs
    w.db.close()


# ---- a person with their own model --------------------------------------------------------------------


def test_a_person_with_a_saved_model_gets_a_provider_built_with_exactly_their_key_and_no_other(world):
    ada = world.person()
    world.access.save(ada, "groq", "llama-x", f" {KEY} \n")
    ask(world.access.provider_for(ada))
    assert world.built == [{"LLM_PROVIDER": "groq", "LLM_MODEL": "llama-x", "GROQ_API_KEY": KEY}]  # nothing of the server's environment comes along
    assert len(world.own.calls) == 1 and world.server.calls == []


def test_calls_on_their_own_key_are_recorded_as_theirs_and_never_use_the_servers_allowance(tmp_path):
    w = World(tmp_path, shared=2)
    ada = w.person()
    w.access.save(ada, "gemini", "g", KEY)
    for _ in range(5):
        ask(w.access.provider_for(ada, session_id=None))
    assert [r[0] for r in w.rows(ada)] == ["own"] * 5
    assert w.access.used_today(ada) == 0
    w.access.remove(ada)  # back to the shared model: today's own-key calls must not eat the allowance
    ask(w.access.provider_for(ada))
    assert w.access.used_today(ada) == 1
    w.db.close()


def test_a_call_made_for_no_session_is_recorded_with_no_session(world):
    ada = world.person()
    world.access.save(ada, "gemini", "g", KEY)
    ask(world.access.provider_for(ada))
    assert world.rows(ada)[0][3] is None  # a suggestion or Testing Lab run has no builder session: it is still the person's spending


# ---- a person with no model of their own --------------------------------------------------------------


def test_with_sharing_off_a_person_with_no_key_is_told_to_add_one(world):
    with pytest.raises(ProviderError) as caught:
        world.access.provider_for(world.person())
    assert caught.value.kind == "auth" and caught.value.retryable and "Settings" in str(caught.value)
    assert world.server.calls == []  # and the owner's model was never borrowed


def test_with_sharing_on_a_person_uses_the_servers_model_up_to_the_allowance_and_then_is_stopped(tmp_path):
    w = World(tmp_path, shared=3)
    ada = w.person()
    provider = w.access.provider_for(ada)
    for _ in range(3):
        ask(provider)
    with pytest.raises(ProviderError) as caught:
        ask(provider)
    assert caught.value.kind == "allowance" and caught.value.retryable
    assert "3" in str(caught.value) and "midnight UTC" in str(caught.value) and "Settings" in str(caught.value)
    assert len(w.server.calls) == 3  # the fourth attempt was never sent
    assert [r[0] for r in w.rows(ada)] == ["server"] * 3
    w.db.close()


def test_the_allowance_counts_only_that_persons_server_calls_from_today_utc(tmp_path):
    w = World(tmp_path, shared=10, clock=lambda: NOON)
    ada, bob = w.person(1), w.person(2)
    for _ in range(2):
        w.add_row(ada, NOON - timedelta(hours=1))
    for _ in range(5):
        w.add_row(ada, NOON - timedelta(days=1))  # yesterday
    for _ in range(7):
        w.add_row(ada, NOON - timedelta(hours=1), source="own")  # her own key
    for _ in range(4):
        w.add_row(bob, NOON - timedelta(hours=1))
    assert w.access.used_today(ada) == 2 and w.access.used_today(bob) == 4
    w.db.close()


def test_the_day_begins_at_midnight_utc_whatever_the_servers_own_time_zone(tmp_path):
    just_before = datetime(2026, 11, 26, 23, 59, 59, tzinfo=timezone(timedelta(hours=-5)))  # 04:59:59 UTC the next day
    w = World(tmp_path, shared=10, clock=lambda: just_before)
    ada = w.person()
    w.add_row(ada, datetime(2026, 11, 27, 0, 0, 1, tzinfo=timezone.utc))
    w.add_row(ada, datetime(2026, 11, 26, 23, 59, 59, tzinfo=timezone.utc))  # the day before in UTC
    assert w.access.used_today(ada) == 1
    w.db.close()


def test_the_allowance_is_enforced_on_every_attempt_so_providers_made_separately_share_it(tmp_path):
    w = World(tmp_path, shared=2)
    ada = w.person()
    first, second = w.access.provider_for(ada), w.access.provider_for(ada)  # two runs started at the same moment
    ask(first)
    ask(second)
    with pytest.raises(ProviderError):
        ask(first)  # the count is of rows, not of what one provider remembers
    with pytest.raises(ProviderError):
        ask(second)
    assert len(w.server.calls) == 2
    w.db.close()


def test_runs_started_at_the_same_moment_cannot_each_take_the_whole_allowance(tmp_path):
    w = World(tmp_path, shared=3, delay=0.05)  # each answer takes 50 ms: all six really are in flight together
    ada = w.person()
    done: list[int] = []
    refused: list[str] = []

    def run() -> None:
        try:
            ask(w.access.provider_for(ada))
            done.append(1)
        except ProviderError as exc:
            refused.append(exc.kind)

    threads = [threading.Thread(target=run) for _ in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(done) == 3 and refused == ["allowance"] * 3  # exactly the allowance, not six
    assert len(w.server.calls) == 3 and w.access.used_today(ada) == 3
    w.db.close()


def test_a_slot_that_was_never_released_is_forgotten_after_a_while(tmp_path):
    w = World(tmp_path, shared=1)
    ada = w.person()
    w.access._inflight[ada] = [time.monotonic() - 10_000]  # an attempt that died without writing its row, long ago
    ask(w.access.provider_for(ada))  # must not be locked out for ever by it
    w.db.close()


def test_a_cache_hit_costs_nothing_so_it_neither_counts_nor_gives_back_a_slot(tmp_path):
    w = World(tmp_path, shared=2, clock=lambda: NOON)
    ada = w.person()
    for _ in range(5):
        w.add_row(ada, NOON - timedelta(hours=1), status="cache")  # never reached a model
    assert w.access.used_today(ada) == 0
    w.db.close()


# ---- the key itself -----------------------------------------------------------------------------------


def test_deleting_a_key_while_a_run_is_using_it_leaves_that_run_working_and_the_next_one_on_the_fallback(world):
    ada = world.person()
    world.access.save(ada, "gemini", "g", KEY)
    running = world.access.provider_for(ada)
    world.access.remove(ada)
    ask(running)  # it already holds its key
    with pytest.raises(ProviderError):
        world.access.provider_for(ada)  # sharing is off: nothing to fall back on


def test_a_changed_access_token_makes_the_key_unreadable_with_a_retryable_error_and_no_key_text(tmp_path):
    w = World(tmp_path)
    ada = w.person()
    w.access.save(ada, "gemini", "g", KEY)
    changed = ModelAccess(w.db, lambda: AIService.single(w.server), ModelOptions(keybox=KeyBox(TOKEN + "-changed"), build=w.options.build))
    view = changed.my_model(ada)
    assert view["key_saved"] is True and view["key_readable"] is False and "again" in view["message"].lower()
    with pytest.raises(ProviderError) as caught:
        changed.provider_for(ada)
    assert caught.value.kind == "auth" and caught.value.retryable and KEY not in str(caught.value) and TOKEN not in str(caught.value)
    assert changed.status_for(ada)["configured"] is False  # said, not a 500
    w.db.close()


def test_save_refuses_what_the_rules_refuse_the_owner_and_a_server_with_no_key_box(tmp_path):
    w = World(tmp_path)
    ada = w.person()
    with pytest.raises(SettingsError):
        w.access.save(ada, "custom", "m", KEY)
    with pytest.raises(ModelAccessError):
        w.access.save(LOCAL_USER_ID, "gemini", "g", KEY)
    with pytest.raises(ModelAccessError):
        w.access.remove(LOCAL_USER_ID)
    bare = another(tmp_path, "bare", keybox=False)
    with pytest.raises(ModelAccessError):
        bare.access.save(bare.person(), "gemini", "g", KEY)
    for each in (w, bare):
        each.db.close()


def test_nothing_the_access_object_returns_holds_the_key_or_its_ciphertext(world):
    ada = world.person()
    world.access.save(ada, "gemini", "g", KEY)
    stored = world.access.store.get(ada)
    shown = json.dumps([world.access.my_model(ada), world.access.status_for(ada), world.access.test(ada)], default=str)
    assert KEY not in shown and KEY[:8] not in shown and repr(stored.key_ciphertext) not in shown and stored.key_ciphertext.hex() not in shown


# ---- what the pages are shown -------------------------------------------------------------------------


def test_my_model_says_what_applies_to_each_kind_of_person(tmp_path):
    w = World(tmp_path, shared=5)
    ada, bob = w.person(1), w.person(2)
    owner = w.access.my_model(LOCAL_USER_ID)
    assert owner["mode"] == "owner" and owner["allowance"] is None and not owner["key_saved"]
    shared = w.access.my_model(ada)
    assert shared["mode"] == "shared" and shared["allowance"] == {"limit": 5, "used": 0} and shared["providers"] and "custom" not in shared["providers"]
    w.access.save(bob, "openai", "gpt-x", KEY)
    own = w.access.my_model(bob)
    assert own["mode"] == "own" and (own["provider"], own["model"]) == ("openai", "gpt-x") and own["key_saved"] and own["key_readable"] and own["key_saved_at"]
    assert own["allowance"] is None
    none = another(tmp_path, "none", shared=0)
    assert none.access.my_model(none.person())["mode"] == "none"
    for each in (w, none):
        each.db.close()


def test_status_for_says_which_model_serves_the_person_and_where_it_comes_from(tmp_path):
    w = World(tmp_path, shared=5)
    ada, bob = w.person(1), w.person(2)
    server = w.access.status_for(ada)
    assert server["configured"] and server["source"] == "server" and server["allowance"] == {"limit": 5, "used": 0}
    w.access.save(bob, "gemini", "g-own", KEY)
    own = w.access.status_for(bob)
    assert own["configured"] and own["source"] == "own" and own["model"] == "own-1" and own["allowance"] is None
    assert w.access.status_for(LOCAL_USER_ID)["source"] == "server"
    w.db.close()
    closed = another(tmp_path, "closed", shared=0)
    none = closed.access.status_for(closed.person())
    assert none["configured"] is False and none["source"] == "none" and "Settings" in none["detail"]
    closed.db.close()


def test_the_test_button_tries_only_the_persons_own_model(tmp_path):
    w = World(tmp_path, shared=5)
    ada = w.person()
    nothing = w.access.test(ada)
    assert nothing["configured"] is False and nothing["checks"] == [] and w.server.calls == []  # the server's model is never tried for a person
    w.access.save(ada, "gemini", "g", KEY)
    result = w.access.test(ada)
    assert result["configured"] is True and len(result["checks"]) == 1 and w.server.calls == []
    assert w.access.test(LOCAL_USER_ID)["configured"] is False  # the owner has the Settings page's own check
    w.db.close()


# ---- the server's setting -----------------------------------------------------------------------------


def test_the_shared_allowance_is_a_server_setting_that_refuses_nonsense():
    assert Hosted.from_env(env()).shared_calls_per_day == 0
    assert Hosted.from_env(env(SKILLFORGE_SHARED_KEY_CALLS_PER_DAY="25")).shared_calls_per_day == 25
    assert Hosted.from_env(env(SKILLFORGE_SHARED_KEY_CALLS_PER_DAY="0")).shared_calls_per_day == 0
    for bad in ("-1", "abc", "1.5", "10000000", " "):
        if bad.strip():
            with pytest.raises(HostedConfigError, match="SKILLFORGE_SHARED_KEY_CALLS_PER_DAY"):
                Hosted.from_env(env(SKILLFORGE_SHARED_KEY_CALLS_PER_DAY=bad))
    with pytest.raises(HostedConfigError, match="SKILLFORGE_SHARED_KEY_CALLS_PER_DAY"):  # nobody but the owner can sign in without Google: it would do nothing
        Hosted.from_env(env(SKILLFORGE_SHARED_KEY_CALLS_PER_DAY="5", SKILLFORGE_GOOGLE_CLIENT_ID=None, SKILLFORGE_ALLOWED_EMAILS=None))
