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
    kind: Mapped[str] = mapped_column(String(16), default="skill", server_default="skill")  # a key of skillforge.kinds
    parent_id: Mapped[str | None] = mapped_column(String(32), nullable=True)  # a plugin's child build; no foreign key: SQLite cannot add one
    # A repository the build was started from: {"repo": absolute folder, "focus": str | None, "nodes": [graph nodes the idea cited]}.
    # The folder is used when the build ends, to record evidence; the pages are only ever shown its name.
    seed: Mapped[dict | None] = mapped_column(JSON, nullable=True)


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


class SuggestRun(Base):
    """One run of the suggestions for a repository, polled like a build. The result is the report as plain data."""

    __tablename__ = "suggest_runs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    created_at: Mapped[str] = mapped_column(String(32))
    updated_at: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(16), index=True)  # working, done, failed
    repo: Mapped[str] = mapped_column(Text)  # the absolute folder; never sent back to the pages
    repo_name: Mapped[str] = mapped_column(String(200))
    focus: Mapped[str | None] = mapped_column(Text, nullable=True)
    with_ideas: Mapped[bool] = mapped_column(Boolean, default=True)
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error: Mapped[str] = mapped_column(Text, default="")
    retryable: Mapped[bool] = mapped_column(Boolean, default=False)


class EvalRun(Base):
    """One run of a skill version's test cases in the Testing Lab, polled like a build. The result is a plain view of the report, kept as data.

    A run belongs to one version and says which content it tested (`content_hash`): a newer version later does not change what this run is about."""

    __tablename__ = "eval_runs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    created_at: Mapped[str] = mapped_column(String(32))
    updated_at: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(16), index=True)  # working, done, failed
    kind: Mapped[str] = mapped_column(String(16))  # a key of skillforge.kinds (only skills can be run so far)
    name: Mapped[str] = mapped_column(String(64), index=True)
    version: Mapped[int] = mapped_column(Integer)
    content_hash: Mapped[str] = mapped_column(String(64))  # of the version that was tested
    runs: Mapped[int] = mapped_column(Integer)  # how many times each case is repeated
    baseline: Mapped[bool] = mapped_column(Boolean)  # also run the same cases without the skill
    cases_total: Mapped[int] = mapped_column(Integer, default=0)
    cases_done: Mapped[int] = mapped_column(Integer, default=0)
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error: Mapped[str] = mapped_column(Text, default="")
    retryable: Mapped[bool] = mapped_column(Boolean, default=False)


class ModelCall(Base):
    """One HTTP attempt at a model, for the session that asked for it. Counts and timings only: never a prompt or a reply."""

    __tablename__ = "model_calls"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str | None] = mapped_column(ForeignKey("build_sessions.id", ondelete="CASCADE"), index=True, nullable=True)
    job_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[str] = mapped_column(String(32))
    task: Mapped[str] = mapped_column(String(16))  # extract, select, design, suggest, code, act
    tier: Mapped[str] = mapped_column(String(16))  # fast, design, code, actor, escalation
    provider: Mapped[str] = mapped_column(String(32))
    model: Mapped[str] = mapped_column(String(128))
    attempt: Mapped[int] = mapped_column(Integer)  # 1 for the first try of a call, 2 for the next, ...
    status: Mapped[str] = mapped_column(String(8))  # ok or error
    error_kind: Mapped[str] = mapped_column(String(16), default="")
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)  # null: the provider did not say
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    latency_ms: Mapped[int] = mapped_column(Integer)
