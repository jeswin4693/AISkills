"""The database tables. Times are ISO 8601 text (UTC), so they read the same in SQLite and PostgreSQL.

The skill library itself is NOT here: it stays as files with SHA-256 manifests (docs/library.md). The database holds
what changes while someone is working: builder sessions and the background jobs that serve them.
"""

from __future__ import annotations

from sqlalchemy import JSON, Boolean, ForeignKey, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

STATUSES = ("working", "awaiting_answers", "awaiting_approval", "done", "failed")
JOB_KINDS = ("understand", "build")
JOB_STATUSES = ("queued", "running", "succeeded", "failed")


class Base(DeclarativeBase):
    pass


class BuildSession(Base):
    """One conversation with the skill builder, from the first description to a saved skill."""

    __tablename__ = "build_sessions"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)  # a random hex id; also the name of its folder
    created_at: Mapped[str] = mapped_column(String(32))
    updated_at: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(24), index=True)
    description: Mapped[str] = mapped_column(Text)  # what the person first typed
    words: Mapped[str] = mapped_column(Text)  # everything the person typed so far; extraction runs on all of it
    round: Mapped[int] = mapped_column(Integer, default=1)
    with_scripts: Mapped[bool] = mapped_column(Boolean, default=False)
    questions: Mapped[list] = mapped_column(JSON, default=list)  # [{"slot", "text"}] while awaiting answers
    spec: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # the RequirementSpec awaiting approval
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # a summary of the build, when it is done
    error: Mapped[str] = mapped_column(Text, default="")
    retryable: Mapped[bool] = mapped_column(Boolean, default=False)  # True when running the same step again can help
    model_calls: Mapped[int] = mapped_column(Integer, default=0)
    notes: Mapped[list] = mapped_column(JSON, default=list)
    saved_name: Mapped[str] = mapped_column(String(64), default="")  # set once the skill is in the library
    saved_version: Mapped[str] = mapped_column(String(16), default="")


class Job(Base):
    """One unit of background work for a session: reading the words (understand) or writing the skill (build)."""

    __tablename__ = "jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)  # a sequence: a higher id is a later job
    session_id: Mapped[str] = mapped_column(ForeignKey("build_sessions.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(16), index=True)
    created_at: Mapped[str] = mapped_column(String(32))
    started_at: Mapped[str | None] = mapped_column(String(32), nullable=True)
    finished_at: Mapped[str | None] = mapped_column(String(32), nullable=True)
    events: Mapped[list] = mapped_column(JSON, default=list)  # [{"at", "message"}] progress the UI can show
    error: Mapped[str] = mapped_column(Text, default="")
