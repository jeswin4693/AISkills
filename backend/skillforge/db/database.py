"""Engine, sessions and migrations. SQLite in the per-user data folder by default; any SQLAlchemy URL works.

Set SKILLFORGE_DATABASE_URL to use another database (for example PostgreSQL, with its driver installed). The tables
are created by Alembic migrations that run when the app starts, never by `create_all`, so the schema has one history.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine, event, select, update
from sqlalchemy.engine import URL
from sqlalchemy.orm import Session, sessionmaker

from ..graph.store import data_dir
from .models import Job, BuildSession

MIGRATIONS = Path(__file__).parent / "migrations"


def default_url() -> str | URL:
    env = os.environ.get("SKILLFORGE_DATABASE_URL", "").strip()
    if env:
        return env
    return URL.create("sqlite", database=str(data_dir() / "skillforge.db"))


def now_text() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


class Database:
    def __init__(self, url: str | URL | None = None) -> None:
        url = url or default_url()
        self.engine: Engine = create_engine(url)
        if self.engine.dialect.name == "sqlite":
            if self.engine.url.database not in (None, "", ":memory:"):
                Path(self.engine.url.database).parent.mkdir(parents=True, exist_ok=True)
            event.listen(self.engine, "connect", _sqlite_settings)
        self._sessions = sessionmaker(self.engine, expire_on_commit=False)

    @contextmanager
    def session(self) -> Iterator[Session]:
        """One short transaction: committed when the block ends, rolled back if it raises."""
        s = self._sessions()
        try:
            yield s
            s.commit()
        except BaseException:
            s.rollback()
            raise
        finally:
            s.close()

    def migrate(self, revision: str = "head") -> None:
        """Bring the schema to the latest version (or to `revision`). Safe to run on every start."""
        config = Config()
        config.set_main_option("script_location", str(MIGRATIONS))
        with self.engine.begin() as connection:
            config.attributes["connection"] = connection
            command.upgrade(config, revision)

    def recover_interrupted(self) -> int:
        """After a restart nothing is really running: mark the work that was, so the person can retry it."""
        stamp = now_text()
        with self.session() as s:
            jobs = s.execute(select(Job).where(Job.status.in_(("queued", "running")))).scalars().all()
            for job in jobs:
                job.status, job.finished_at = "failed", stamp
                job.error = "The server stopped while this was running."
            s.execute(
                update(BuildSession).where(BuildSession.status == "working").values(
                    status="failed", retryable=True, updated_at=stamp,
                    error="The server stopped while this was running. Retry to run that step again.",
                )
            )
            return len(jobs)

    def close(self) -> None:
        self.engine.dispose()


def _sqlite_settings(dbapi_connection, _record) -> None:
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")  # SQLite ignores foreign keys unless asked
    cursor.execute("PRAGMA busy_timeout=5000")  # wait for a short lock instead of failing at once
    cursor.execute("PRAGMA journal_mode=WAL")  # readers do not block the one writer
    cursor.close()
