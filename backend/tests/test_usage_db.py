"""What each model call cost, kept per builder session. Counts and timings only: never a prompt or a reply."""

from __future__ import annotations

import pytest
from sqlalchemy import select
from test_skill_build import FIRST, round_one

from skillforge.ai import AIService, UsageRecord
from skillforge.builder import Builder, JobRunner
from skillforge.builder.usage import DbUsageRecorder, usage_summary
from skillforge.db import BuildSession, Database, ModelCall
from skillforge.library import Library
from skillforge.providers import MockProvider


@pytest.fixture
def db(tmp_path):
    database = Database(f"sqlite:///{(tmp_path / 'u.db').as_posix()}")
    database.migrate()
    yield database
    database.close()


def add_session(db, sid="a" * 32):
    with db.session() as s:
        s.add(BuildSession(id=sid, created_at="t", updated_at="t", status="done", description="d", words="d", round=1,
                           with_scripts=False, questions=[], error="", retryable=False, model_calls=0, notes=[],
                           saved_name="", saved_version=""))
    return sid


def row(status="ok", tokens=(11, 7), model="m1", attempt=1, error_kind=""):
    return UsageRecord("extract", "fast", "gemini", model, attempt, status, error_kind, tokens[0] if tokens else None,
                       tokens[1] if tokens else None, 120)


def test_the_recorder_writes_one_row_per_attempt(db):
    sid = add_session(db)
    rec = DbUsageRecorder(db, sid, 7)
    rec.record(row("error", None, attempt=1, error_kind="overloaded"))
    rec.record(row("ok", (11, 7), attempt=2))
    with db.session() as s:
        rows = s.execute(select(ModelCall).order_by(ModelCall.id)).scalars().all()
    assert [(r.session_id, r.job_id, r.attempt, r.status, r.error_kind, r.input_tokens) for r in rows] == [
        (sid, 7, 1, "error", "overloaded", None), (sid, 7, 2, "ok", "", 11),
    ]
    assert rows[1].task == "extract" and rows[1].tier == "fast" and rows[1].provider == "gemini" and rows[1].latency_ms == 120 and rows[1].created_at


def test_the_summary_adds_tokens_counts_failures_and_lists_models(db):
    sid = add_session(db)
    rec = DbUsageRecorder(db, sid, 1)
    rec.record(row("error", None, error_kind="timeout"))
    rec.record(row("ok", (11, 7), model="m1"))
    rec.record(row("ok", (5, 3), model="m2"))
    assert usage_summary(db, sid) == {"calls": 3, "errors": 1, "input_tokens": 16, "output_tokens": 10, "models": ["m1", "m2"]}


def test_tokens_stay_none_when_no_provider_reported_any(db):
    sid = add_session(db)
    DbUsageRecorder(db, sid, 1).record(row("ok", None))
    assert usage_summary(db, sid) == {"calls": 1, "errors": 0, "input_tokens": None, "output_tokens": None, "models": ["m1"]}
    assert usage_summary(db, add_session(db, "b" * 32)) == {"calls": 0, "errors": 0, "input_tokens": None, "output_tokens": None, "models": []}


def test_deleting_a_session_deletes_its_usage(db):
    sid = add_session(db)
    DbUsageRecorder(db, sid, 1).record(row())
    with db.session() as s:
        s.delete(s.get(BuildSession, sid))
    with db.session() as s:
        assert s.execute(select(ModelCall)).scalars().all() == []


def builder_with(tmp_path, db, provider):
    return Builder(db, Library(tmp_path / "library"), tmp_path / "builds", provider_factory=lambda: provider,
                   runner=JobRunner(inline=True), sandbox_note=lambda: "unavailable. (test)")


def test_a_builder_job_records_usage_and_the_session_carries_it(tmp_path, db):
    builder = builder_with(tmp_path, db, AIService.single(MockProvider([round_one()])))
    session = builder.start(FIRST)
    usage = builder.get(session["id"])["usage"]
    assert session["status"] == "awaiting_answers"
    assert usage["calls"] == 1 and usage["errors"] == 0 and usage["models"] == ["mock-1"]
    with db.session() as s:
        stored = s.execute(select(ModelCall)).scalars().all()
    assert len(stored) == 1 and stored[0].session_id == session["id"] and stored[0].job_id and stored[0].task == "extract"


def test_no_prompt_or_reply_text_is_stored(tmp_path, db):
    builder = builder_with(tmp_path, db, AIService.single(MockProvider([round_one()])))
    builder.start(FIRST)
    with db.session() as s:
        stored = s.execute(select(ModelCall)).scalars().all()
    assert {c.name for c in ModelCall.__table__.columns} == {
        "id", "session_id", "job_id", "user_id", "created_at", "task", "tier", "provider", "model", "attempt", "status", "error_kind",
        "input_tokens", "output_tokens", "latency_ms", "key_source",
    }  # user_id (accounts slice) is the random id of whose quota a call used, key_source (slice AI) is "server" or "own": ids and labels, never text a person typed
    assert {r.user_id for r in stored} == {"local"}  # a local build's calls belong to the owner
    words = FIRST.split()[:4]
    assert all(w not in " ".join(str(getattr(r, c.name)) for c in ModelCall.__table__.columns) for r in stored for w in words if len(w) > 4)


def test_a_plain_provider_records_nothing_and_the_session_says_so(tmp_path, db):
    builder = builder_with(tmp_path, db, MockProvider([round_one()]))
    session = builder.start(FIRST)
    assert builder.get(session["id"])["usage"]["calls"] == 0


def test_discarding_a_session_keeps_its_usage_but_lets_go_of_the_session(tmp_path, db):
    # It used to delete the rows. They are the ledger a person's daily allowance is counted from (slice AI), so a discard must not give the calls back:
    # tests/test_model_review.py. The session's own summary is empty once it is gone.
    builder = builder_with(tmp_path, db, AIService.single(MockProvider([round_one()])))
    sid = builder.start(FIRST)["id"]
    builder.discard(sid)
    with db.session() as s:
        kept = s.execute(select(ModelCall)).scalars().all()
    assert len(kept) == 1 and kept[0].session_id is None
    assert usage_summary(db, sid)["calls"] == 0
