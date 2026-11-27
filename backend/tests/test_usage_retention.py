"""The usage table is cleaned, and today's rows never are (slice AK, task 2c).

`model_calls` keeps one row per attempt at a model (counts and timings, never a prompt). A discarded build keeps its rows (they are the daily allowance's
ledger), so the table only ever grew. Rows older than SKILLFORGE_USAGE_KEEP_DAYS days (default 90, 0 = keep for ever) are deleted once at start and then at
most once a day. The allowance reads only today's rows (UTC), so a clean-up must never reach them.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from skillforge.builder import Builder, JobRunner
from skillforge.builder import retention
from skillforge.builder.retention import DEFAULT_KEEP_DAYS, UsageRetention, keep_days_from_env, prune_usage
from skillforge.db import LOCAL_USER_ID, Database, ModelCall
from skillforge.library import Library
from skillforge.providers import MockProvider

NOW = datetime(2026, 11, 27, 10, 0, tzinfo=timezone.utc)
MIDNIGHT = "2026-11-27T00:00:00"  # the text the daily allowance compares created_at with (builder/model_access.py)
PERSON = "a" * 32


@pytest.fixture
def db(tmp_path):
    database = Database(f"sqlite:///{(tmp_path / 'r.db').as_posix()}")
    database.migrate()
    yield database
    database.close()


def add_call(db: Database, created_at: str, user: str = PERSON) -> None:
    with db.session() as s:
        s.add(ModelCall(created_at=created_at, task="act", tier="actor", provider="p", model="m", attempt=1, status="ok", error_kind="", latency_ms=1,
                        user_id=user, key_source="server"))


def remaining(db: Database) -> list[str]:
    with db.session() as s:
        return sorted(s.execute(select(ModelCall.created_at)).scalars().all())


def iso(moment: datetime) -> str:
    return moment.isoformat(timespec="milliseconds")


def test_rows_older_than_the_days_go_and_newer_ones_stay(db):
    old, inside, today = "2026-10-27T10:00:00.000+00:00", "2026-10-29T10:00:00.000+00:00", "2026-11-27T01:00:00.000+00:00"
    for t in (old, inside, today):
        add_call(db, t)
    assert prune_usage(db, 30, NOW) == 1
    assert remaining(db) == [inside, today]


@pytest.mark.parametrize("hour,minute", [(0, 0), (0, 5), (9, 30), (23, 59)])
def test_todays_rows_are_never_deleted_even_with_one_day_kept(db, hour, minute):
    midnight_row, old_row = "2026-11-27T00:00:00.000+00:00", "2026-11-25T08:00:00.000+00:00"
    add_call(db, midnight_row)
    add_call(db, old_row)
    prune_usage(db, 1, NOW.replace(hour=hour, minute=minute))
    assert remaining(db) == [midnight_row]


def test_zero_deletes_nothing(db):
    add_call(db, "2020-01-01T00:00:00.000+00:00")
    assert prune_usage(db, 0, NOW) == 0
    assert remaining(db) == ["2020-01-01T00:00:00.000+00:00"]


def test_the_allowance_count_is_unchanged_by_the_clean_up(db):
    for t in ("2026-01-01T09:00:00.000+00:00", "2026-11-27T00:00:00.000+00:00", "2026-11-27T09:00:00.000+00:00"):
        add_call(db, t)

    def counted_today() -> int:
        with db.session() as s:
            return len(s.execute(select(ModelCall).where(ModelCall.user_id == PERSON, ModelCall.created_at >= MIDNIGHT)).scalars().all())

    before = counted_today()
    assert prune_usage(db, 1, NOW) == 1
    assert counted_today() == before == 2


@pytest.mark.parametrize("text,expected,warns", [
    (None, DEFAULT_KEEP_DAYS, False), ("", DEFAULT_KEEP_DAYS, False), ("   ", DEFAULT_KEEP_DAYS, False),
    ("30", 30, False), (" 7 ", 7, False), ("0", 0, False), ("36500", 36500, False),
    ("-1", 0, True), ("abc", 0, True), ("1.5", 0, True), ("36501", 0, True),  # not understood: delete nothing, and say so once
])
def test_the_setting_is_read_safely(text, expected, warns, caplog):
    environ = {} if text is None else {"SKILLFORGE_USAGE_KEEP_DAYS": text}
    with caplog.at_level(logging.WARNING, logger=retention.__name__):
        assert keep_days_from_env(environ) == expected
    assert len(caplog.records) == (1 if warns else 0)


def test_the_default_is_ninety_days():
    assert DEFAULT_KEEP_DAYS == 90


class Clock:
    def __init__(self, now: datetime):
        self.now = now

    def __call__(self) -> datetime:
        return self.now


def test_run_if_due_runs_first_then_once_a_day(db):
    clock = Clock(NOW)
    clean = UsageRetention(db, 30, clock)
    old = "2026-01-01T10:00:00.000+00:00"
    add_call(db, old)
    assert clean.run_if_due() == 1 and remaining(db) == []
    add_call(db, old)
    assert clean.run_if_due() == 0 and remaining(db) == [old]  # the same moment: not due
    clock.now = NOW + timedelta(hours=23, minutes=59)
    assert clean.run_if_due() == 0 and remaining(db) == [old]
    clock.now = NOW + timedelta(hours=24)
    assert clean.run_if_due() == 1 and remaining(db) == []


def test_a_failing_clean_up_never_raises_and_waits_a_day(db, monkeypatch):
    clock = Clock(NOW)
    clean = UsageRetention(db, 30, clock)
    old = "2026-01-01T10:00:00.000+00:00"
    add_call(db, old)

    def boom(*args, **kwargs):
        raise RuntimeError("the database is locked")

    monkeypatch.setattr(retention, "prune_usage", boom)
    assert clean.run_if_due() == 0  # no exception reaches a person's build
    monkeypatch.undo()
    assert clean.run_if_due() == 0 and remaining(db) == [old]  # the failed attempt counts: not tried again before a day has passed
    clock.now = NOW + timedelta(hours=24)
    assert clean.run_if_due() == 1 and remaining(db) == []


def test_a_build_start_triggers_the_clean_up(tmp_path):
    database = Database(f"sqlite:///{(tmp_path / 'b.db').as_posix()}")
    database.migrate()
    builder = Builder(
        database, Library(tmp_path / "lib"), tmp_path / "builds", provider_factory=lambda: MockProvider([]), runner=JobRunner(inline=True),
        usage_keep_days=30,
    )
    try:
        add_call(database, "2020-01-01T00:00:00.000+00:00", LOCAL_USER_ID)
        builder.access.provider_for(LOCAL_USER_ID)  # every build, suggestion run and Lab run asks for its model here
        assert remaining(database) == []
    finally:
        builder.close()


def test_a_builder_made_without_a_setting_cleans_nothing(tmp_path):
    database = Database(f"sqlite:///{(tmp_path / 'c.db').as_posix()}")
    database.migrate()
    builder = Builder(database, Library(tmp_path / "lib"), tmp_path / "builds", provider_factory=lambda: MockProvider([]), runner=JobRunner(inline=True))
    try:
        add_call(database, "2020-01-01T00:00:00.000+00:00", LOCAL_USER_ID)
        builder.access.provider_for(LOCAL_USER_ID)
        assert remaining(database) == ["2020-01-01T00:00:00.000+00:00"]
    finally:
        builder.close()


def test_the_real_start_cleans_once(tmp_path, monkeypatch):
    monkeypatch.setenv("SKILLFORGE_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("SKILLFORGE_USAGE_KEEP_DAYS", "30")
    seed = Database()  # the real database file, in the data folder
    seed.migrate()
    today = iso(datetime.now(timezone.utc))
    add_call(seed, "2020-01-01T00:00:00.000+00:00", LOCAL_USER_ID)
    add_call(seed, today, LOCAL_USER_ID)
    seed.close()
    builder = Builder.default(Library(tmp_path / "library"))
    try:
        assert remaining(builder.db) == [today]  # the old row went at start, today's stayed
    finally:
        builder.close()
