"""Scan runs are stored (slice AK, task 5): the table, and the places that must know a scan is running work.

A behaviour scan is a polled background run like a build or a Testing Lab run, so it is kept in the database (migration 0010) and joins what already counts running work:
the limit on runs at once, the wait before a delete or an erase, and recovery after a restart.
"""

from __future__ import annotations

from sqlalchemy import inspect, select

from skillforge.db import Database, ScanRun, now_text

COLUMNS = {
    "id", "created_at", "updated_at", "status", "kind", "name", "version", "content_hash", "runs", "scenarios", "control", "draft", "tasks_total", "tasks_done",
    "result", "error", "retryable", "user_id",
}


def scan_row(rid: str, status: str, **kw) -> ScanRun:
    stamp = now_text()
    base = dict(
        id=rid, created_at=stamp, updated_at=stamp, status=status, kind="skill", name="foo", version=1, content_hash="h", runs=1, scenarios=5, control=True, draft=True,
        tasks_total=5, tasks_done=2, result=None, error="", retryable=False, user_id="local",
    )
    return ScanRun(**{**base, **kw})


def test_the_migration_creates_scan_runs_with_its_indexes(tmp_path):
    db = Database(f"sqlite:///{(tmp_path / 'm.db').as_posix()}")
    try:
        db.migrate("0009")
        assert "scan_runs" not in inspect(db.engine).get_table_names()
        db.migrate()
        inspector = inspect(db.engine)
        columns = {c["name"]: c for c in inspector.get_columns("scan_runs")}
        assert set(columns) == COLUMNS
        assert columns["result"]["nullable"] is True and columns["user_id"]["nullable"] is False and columns["error"]["nullable"] is False
        assert {("status",), ("name",), ("user_id",)} <= {tuple(i["column_names"]) for i in inspector.get_indexes("scan_runs")}
    finally:
        db.close()


def test_a_scan_run_left_working_is_failed_and_retryable_after_a_restart(tmp_path):
    db = Database(f"sqlite:///{(tmp_path / 'r.db').as_posix()}")
    try:
        db.migrate()
        with db.session() as s:
            s.add(scan_row("a" * 32, "working"))
            s.add(scan_row("b" * 32, "done"))
        assert db.recover_interrupted() == 1
        with db.session() as s:
            rows = {r.id: r for r in s.execute(select(ScanRun)).scalars()}
        stopped = rows["a" * 32]
        assert stopped.status == "failed" and stopped.retryable is True and "server stopped" in stopped.error
        assert rows["b" * 32].status == "done" and rows["b" * 32].error == "" and rows["b" * 32].retryable is False
    finally:
        db.close()
