"""Slice AI: what the independent review found, each reproduced as a failing test before it was fixed (docs/per-person-keys.md).

Offline: the shared model is a MockProvider, no key and no network.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select
from test_accounts_isolation import World, start
from test_skill_build import FIRST, round_one, round_two

from skillforge.ai import AIService
from skillforge.builder import Builder, JobRunner, ModelOptions
from skillforge.db import Database, ModelCall
from skillforge.library import Library
from skillforge.providers import MockProvider

LIMIT = 2


@pytest.fixture
def shared_world(tmp_path):
    """A hosted server that shares its model: a person with no key of their own may make LIMIT calls a day on it."""
    made: list[World] = []

    def make(responses) -> World:
        w = World(tmp_path / f"w{len(made)}", responses, service=True, options=ModelOptions(shared_calls_per_day=LIMIT))
        made.append(w)
        return w

    (tmp_path / "w0").mkdir()
    yield make
    for w in made:
        w.close()


def allowance(client) -> dict:
    return client.get("/api/me/model").json()["allowance"]


def test_discarding_a_build_does_not_give_the_daily_allowance_back(shared_world):
    # Found by the independent review (Critical): `model_calls` is the allowance's ledger, and Discard deleted a build's rows, so
    # "start a build, discard it, start another" made the shared model free for as long as a person cared to do it.
    w = shared_world([round_two()] * 40)
    ada = w.person(1)
    for _ in range(6):
        sid = start(ada)
        assert ada.delete(f"/api/builds/{sid}").status_code == 200
    assert len(w.mock.calls) == LIMIT  # the model was asked LIMIT times, not once per build
    assert allowance(ada) == {"limit": LIMIT, "used": LIMIT}


def test_a_discard_changes_neither_the_count_nor_the_ledger_it_is_counted_from(shared_world):
    w = shared_world([round_two()] * 40)
    ada = w.person(1)
    uid = w.uid(1)
    sid = start(ada)
    before = w.builder.access.used_today(uid)
    assert before >= 1
    assert ada.delete(f"/api/builds/{sid}").status_code == 200
    assert w.builder.access.used_today(uid) == before
    with w.db.session() as s:
        rows = s.execute(select(ModelCall).where(ModelCall.user_id == uid)).scalars().all()
    assert len(rows) == before and {r.session_id for r in rows} == {None}  # kept (counts and timings only), no longer tied to a session that is gone


def test_a_discarded_sessions_usage_rows_are_kept_for_the_owner_too(tmp_path):
    # The same rule without any person: usage rows are a record of calls made, so throwing a build away does not unmake them.
    db = Database(f"sqlite:///{(tmp_path / 'u.db').as_posix()}")
    db.migrate()
    builder = Builder(db, Library(tmp_path / "library"), tmp_path / "builds", provider_factory=lambda: AIService.single(MockProvider([round_one()])),
                      runner=JobRunner(inline=True), sandbox_note=lambda: "unavailable. (test)")
    try:
        sid = builder.start(FIRST)["id"]
        builder.discard(sid)
        with db.session() as s:
            rows = s.execute(select(ModelCall)).scalars().all()
        assert len(rows) == 1 and rows[0].session_id is None and rows[0].user_id == "local"
    finally:
        db.close()
