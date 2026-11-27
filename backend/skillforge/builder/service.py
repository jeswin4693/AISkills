"""The skill builder as a conversation that survives across HTTP requests.

    working --> awaiting_answers --(answers)--> working --> ... --> awaiting_approval --(approve)--> working --> done
                                                                                                       \\--> failed (retry)

The rules of the command-line builder are the same, because the same functions run: completeness is decided by the
checklist in code, an answer counts only through a quote verified in the person's own words, nothing is built until
the person approves the requirement, and generated code is run only through the sandbox. What is new is only the
bookkeeping: the state lives in the database, and the two slow steps (reading the words, writing the skill) run as
background jobs the browser polls.
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import uuid
from collections.abc import Callable
from dataclasses import asdict
from pathlib import Path

from pydantic import ValidationError
from sqlalchemy import delete, func, select, update

from ..build.models import RequirementSpec
from ..build.pipeline import BuildError, apply_answers, check_description, sandbox_note as default_sandbox_note
from ..build.requirements import Question
from ..build.scripts import ScriptRunner
from ..db import LOCAL_USER_ID, BuildSession, Database, EvalRun, Job, ModelCall, ScanRun, SuggestRun, now_text
from ..graph.store import data_dir
from ..kinds import UnknownKind, get_kind
from ..library import ImportReport, Library, LibraryError, import_skill
from ..providers import LLMProvider, ProviderError
from ..validate.static import read_dir
from .errors import BadRequest, BuilderError, SessionNotFound, WrongState
from .evals import EvalRuns
from .jobs import JobRunner
from .limits import PersonLimits, PersonSpace
from .model_access import ModelAccess, ModelOptions
from .provider import env_provider
from .repository import check_seed, record_evidence, seed_view
from .retention import UsageRetention, keep_days_from_env
from .scans import ScanRuns
from .suggestions import SuggestRuns
from .usage import usage_summary

MAX_ROUNDS = 3
MAX_EVENTS = 50
_ID = re.compile(r"^[0-9a-f]{32}\Z")
log = logging.getLogger(__name__)


def partial_of(stored: object) -> RequirementSpec | None:
    """The partial requirement the last round left on a session, or None when there is none or the record is damaged. A damaged record keeps nothing and
    fails nothing: the round simply reads the person's words as it always did. (What it holds is checked again against the words before any of it is kept.)"""
    if not isinstance(stored, dict):
        return None
    try:
        return RequirementSpec.model_validate(stored)
    except ValidationError:
        return None


class Builder:
    def __init__(
        self, database: Database, library: Library, builds_root: Path, *,
        provider_factory: Callable[[], LLMProvider] = env_provider, runner: JobRunner | None = None,
        sandbox_note: Callable[[], str] = default_sandbox_note, script_runner: ScriptRunner | None = None,
        library_for: Callable[[str], Library] | None = None, model_options: ModelOptions = ModelOptions(), limits: PersonLimits = PersonLimits(),
        usage_keep_days: int = 0,
    ) -> None:
        self.db = database
        self.library = library  # the owner's library
        self.library_for = library_for  # a person's library, by their id (the API sets it); without it only the owner has one
        self.builds_root = Path(builds_root)
        self.provider_factory = provider_factory  # the SERVER's model, the owner's; a person's is decided by `access`
        self.runner = runner or JobRunner()
        self.sandbox_note = sandbox_note
        self.script_runner = script_runner
        # Which model each person's calls use, and whether they may use it now (slice AI). It looks `provider_factory` up when asked, not once, because
        # the server's model can be changed while it runs (a fixed .env is seen at once).
        # Usage rows older than `usage_keep_days` are cleaned at most once a day (0: never; the real server sets it from the environment, see `default`).
        # It is asked whenever a build, a suggestion run or a Lab run picks its model. Today's rows are never touched: they are the daily allowance.
        self.retention = UsageRetention(self.db, usage_keep_days, model_options.clock)
        self.access = ModelAccess(self.db, lambda: self.provider_factory(), model_options, housekeeping=self.retention.run_if_due)
        # What each person uses and may use (slice AJ): disk, kept builds, runs working at once. The owner is never limited.
        self.space = PersonSpace(self.db, limits, self._person_folders)

    @classmethod
    def default(
        cls, library: Library, library_for: Callable[[str], Library] | None = None, model_options: ModelOptions = ModelOptions(), limits: PersonLimits = PersonLimits(),
        usage_keep_days: int | None = None,
    ) -> "Builder":
        """The real thing: the SQLite file in the per-user data folder, migrated, with interrupted work marked, and old usage rows cleaned once.

        `usage_keep_days` None reads SKILLFORGE_USAGE_KEEP_DAYS (default 90, 0 keeps everything): builder/retention.py."""
        db = Database()
        db.migrate()
        db.recover_interrupted()
        keep = keep_days_from_env(os.environ) if usage_keep_days is None else usage_keep_days
        builder = cls(db, library, data_dir() / "builds", library_for=library_for, model_options=model_options, limits=limits, usage_keep_days=keep)
        builder.retention.run_if_due()  # once at start; after this, at most once a day
        return builder

    def _person_folders(self, user_id: str) -> list[Path]:
        """Where a person's files are: their own folder (their library of every kind sits in it) and the folder of each build they have."""
        folders: list[Path] = []
        if self.library_for is not None and user_id != LOCAL_USER_ID:
            try:
                folders.append(self.library_for(user_id).root.parent)
            except LibraryError:
                pass
        with self.db.session() as s:
            ids = s.execute(select(BuildSession.id).where(BuildSession.user_id == user_id)).scalars().all()
        return folders + [self.builds_root / sid for sid in ids if _ID.match(sid)]

    def working_for(self, user_id: str) -> int:
        """How many things of this person are working right now: builds, Testing Lab runs, suggestion runs and behaviour scans. Deleting a library entry, or erasing a person,
        waits until this is 0 (a plugin build reads the library while it works, and a run that writes its result after its rows are gone would leave a stray one).
        This is not the limits' `active` count, which is about how many a person may run at once and does not include suggestion runs."""
        with self.db.session() as s:
            return sum(
                s.execute(select(func.count()).select_from(model).where(model.user_id == user_id, model.status == "working")).scalar_one()
                for model in (BuildSession, EvalRun, SuggestRun, ScanRun)
            )

    def drop_runs_of(self, user_id: str, kind: str, name: str) -> int:
        """Delete this person's Testing Lab runs and behaviour scans of one library entry of one kind, once that entry is deleted. A new entry of the same name starts
        again at v1, and the quality report matches Lab runs by name and version (a scan page does the same), so a finished run of the deleted entry would otherwise be
        shown as the new one's tested result. (The usage rows of those runs are not tied to them and stay: they are the allowance's ledger.)"""
        with self.db.session() as s:
            labs = s.execute(delete(EvalRun).where(EvalRun.user_id == user_id, EvalRun.kind == kind, EvalRun.name == name)).rowcount
            scans = s.execute(delete(ScanRun).where(ScanRun.user_id == user_id, ScanRun.kind == kind, ScanRun.name == name)).rowcount
        return labs + scans

    def _library(self, user_id: str) -> Library:
        """The library of whoever owns a session. Fails closed: with no resolver only the owner has a library, never a shared one for everybody."""
        if self.library_for is not None:
            return self.library_for(user_id)
        if user_id == LOCAL_USER_ID:
            return self.library
        raise BuilderError("There is no library for that user.")

    @property
    def suggestions(self) -> SuggestRuns:
        """Suggestion runs for a repository, sharing this builder's database, job runner and model."""
        return SuggestRuns(self.db, self.runner, self.access.provider_for)

    @property
    def scans(self) -> ScanRuns:
        """Behaviour scans of a skill or agent: its instructions run in a simulated agent loop in the background, sharing this builder's database, job runner, model and each person's library."""
        return ScanRuns(self.db, self.runner, self.access.provider_for, self.library, self._library, self.space)

    @property
    def evals(self) -> EvalRuns:
        """Testing Lab runs: a skill's test cases asked of a model in the background, sharing this builder's database, job runner, model and each person's library."""
        return EvalRuns(self.db, self.runner, self.access.provider_for, self.library, self._library, self.space)

    def close(self) -> None:
        self.runner.shutdown()
        self.db.close()

    # ---- reading ---------------------------------------------------------------------------------

    def _row(self, s, sid: str, user: str | None) -> BuildSession:
        """A session, if it is `user`'s. Someone else's is "no such session", the very answer for one that never existed: it must not say it is there.
        `user` has no default on purpose, so a caller cannot forget it; only the background jobs pass None (they act for the session's own owner)."""
        row = s.get(BuildSession, sid) if _ID.match(sid or "") else None
        if row is None or (user is not None and row.user_id != user):
            raise SessionNotFound("There is no such builder session.")
        return row

    def _latest_job(self, s, sid: str) -> Job | None:
        return s.execute(select(Job).where(Job.session_id == sid).order_by(Job.id.desc()).limit(1)).scalars().first()

    def get(self, sid: str, user: str = LOCAL_USER_ID) -> dict:
        with self.db.session() as s:
            row = self._row(s, sid, user)
            job = self._latest_job(s, sid)
            return {
                "id": row.id, "kind": row.kind, "status": row.status, "description": row.description, "round": row.round,
                "max_rounds": MAX_ROUNDS, "with_scripts": row.with_scripts, "questions": row.questions,
                "spec": row.spec, "result": row.result, "error": row.error, "retryable": row.retryable,
                "model_calls": row.model_calls, "notes": row.notes, "usage": usage_summary(self.db, sid),
                "saved": {"name": row.saved_name, "version": row.saved_version} if row.saved_version else None,
                "seed": seed_view(row.seed), "created_at": row.created_at, "updated_at": row.updated_at,
                "job": None if job is None else {
                    "kind": job.kind, "status": job.status, "started_at": job.started_at,
                    "finished_at": job.finished_at, "events": job.events[-MAX_EVENTS:],
                },
            }

    def list(self, limit: int = 50, user: str = LOCAL_USER_ID) -> list[dict]:
        with self.db.session() as s:
            rows = s.execute(
                select(BuildSession).where(BuildSession.user_id == user).order_by(BuildSession.created_at.desc()).limit(limit)
            ).scalars().all()
            return [
                {
                    "id": r.id, "kind": r.kind, "status": r.status, "description": r.description[:140], "created_at": r.created_at,
                    "updated_at": r.updated_at, "skill": (r.result or {}).get("name", ""),
                    "draft": bool(r.result and r.result.get("status") == "draft"),
                    "saved": {"name": r.saved_name, "version": r.saved_version} if r.saved_version else None,
                }
                for r in rows
            ]

    def read_file(self, sid: str, path: str, user: str = LOCAL_USER_ID) -> dict:
        """One generated file, looked up by name among the files that were written. Never a path on the disk."""
        with self.db.session() as s:
            result = self._row(s, sid, user).result
        if not result:
            raise SessionNotFound("This session has not written any files yet.")
        files, _ = read_dir(self.builds_root / sid / result["folder"])
        if path not in files:
            raise SessionNotFound(f"There is no generated file '{path}'.")
        try:
            return {"path": path, "binary": False, "text": files[path].decode("utf-8")}
        except UnicodeDecodeError:
            return {"path": path, "binary": True, "text": ""}

    # ---- actions that start work -----------------------------------------------------------------

    def _claim(self, s, sid: str, allowed: tuple[str, ...], **values) -> bool:
        """Move a session to a new state only if it is still in an allowed one: two clicks cannot both win."""
        r = s.execute(
            update(BuildSession).where(BuildSession.id == sid, BuildSession.status.in_(allowed))
            .values(updated_at=now_text(), **values)
        )
        return r.rowcount == 1

    def _new_job(self, s, sid: str, kind: str) -> int:
        job = Job(session_id=sid, kind=kind, status="queued", created_at=now_text(), events=[], error="")
        s.add(job)
        s.flush()
        return job.id

    def start(self, description: str, with_scripts: bool = False, kind: str = "skill", seed: dict | None = None, user: str = LOCAL_USER_ID) -> dict:
        """Begin a session. `seed` is {"repo", "focus", "nodes"} (and, for a GitHub link, "snapshot": the copy the idea was made from): a repository
        and the places in it the idea cited, so the built thing carries evidence of them (docs/evidence.md). A half-given or unusable seed is
        refused before anything starts."""
        try:
            spec = get_kind(kind)
            if not spec.conversational:
                raise BuildError(f"{spec.label}s are not built from a description: they are composed from what is already in the library.")
            words = check_description(description)
        except (UnknownKind, BuildError) as exc:
            raise BadRequest(str(exc)) from exc
        kept_seed = check_seed(kind, (seed or {}).get("repo"), (seed or {}).get("focus"), (seed or {}).get("nodes"), (seed or {}).get("snapshot"))
        sid, stamp = uuid.uuid4().hex, now_text()
        self.space.check_disk(user)  # before the lock: walking a big folder must never hold up anybody else's start
        with self.space.lock, self.db.session() as s:  # the lock is held until this is written, so two starts at once cannot both take the last place
            self.space.admit(user, new_build=True)
            s.add(BuildSession(
                id=sid, created_at=stamp, updated_at=stamp, status="working", description=words, words=words,
                round=1, with_scripts=with_scripts, questions=[], error="", retryable=False, model_calls=0,
                notes=[], saved_name="", saved_version="", kind=kind, seed=kept_seed, user_id=user,
            ))
            job_id = self._new_job(s, sid, "understand")
        self.runner.submit(self._execute, job_id)
        return self.get(sid, user)

    def answer(self, sid: str, answers: dict[str, str], user: str = LOCAL_USER_ID) -> dict:
        self.space.check_disk(user)
        with self.space.lock, self.db.session() as s:
            row = self._row(s, sid, user)
            if row.status != "awaiting_answers":
                raise WrongState("This session is not waiting for answers.")
            questions = [Question(**q) for q in row.questions]
            unknown = set(answers) - {q.slot for q in questions}
            if unknown:
                raise BadRequest("Not a question that was asked: " + ", ".join(sorted(unknown)))
            try:
                words = apply_answers(row.words, questions, answers)
            except BuildError as exc:
                raise BadRequest(str(exc)) from exc
            self.space.admit(user)
            if not self._claim(s, sid, ("awaiting_answers",), status="working", words=words, round=row.round + 1,
                               questions=[], error="", retryable=False):
                raise WrongState("This session just moved on. Reload it.")
            job_id = self._new_job(s, sid, "understand")
        self.runner.submit(self._execute, job_id)
        return self.get(sid, user)

    def approve(self, sid: str, user: str = LOCAL_USER_ID) -> dict:
        self.space.check_disk(user)
        with self.space.lock, self.db.session() as s:
            self._row(s, sid, user)
            self.space.admit(user)
            if not self._claim(s, sid, ("awaiting_approval",), status="working", error="", retryable=False):
                raise WrongState("There is no requirement waiting for approval in this session.")
            job_id = self._new_job(s, sid, "build")
        self.runner.submit(self._execute, job_id)
        return self.get(sid, user)

    def retry(self, sid: str, user: str = LOCAL_USER_ID) -> dict:
        self.space.check_disk(user)
        with self.space.lock, self.db.session() as s:
            row = self._row(s, sid, user)
            if row.status != "failed" or not row.retryable:
                raise WrongState("Only a step that failed for a reason that can pass (such as a missing key) can be retried.")
            last = self._latest_job(s, sid)
            kind = last.kind if last else "understand"
            self.space.admit(user)
            if not self._claim(s, sid, ("failed",), status="working", error="", retryable=False):
                raise WrongState("This session just moved on. Reload it.")
            job_id = self._new_job(s, sid, kind)
        self.runner.submit(self._execute, job_id)
        return self.get(sid, user)

    # ---- actions that finish ---------------------------------------------------------------------

    def save(self, sid: str, *, accept_draft: bool = False, note: str = "", user: str = LOCAL_USER_ID) -> ImportReport:
        """Put the built skill into the library through the same checked import as any other skill. It goes into the library of the person who owns the session."""
        self.space.check_disk(user)
        with self.db.session() as s:
            row = self._row(s, sid, user)
            result, kind = row.result, row.kind
            if row.status != "done" or not result:
                raise WrongState("There is no finished skill in this session yet.")
        if result["status"] == "draft" and not accept_draft:
            why = result["draft_reason"] or f"{result['counts']['failed']} check(s) failed"
            try:
                noun = get_kind(kind).label.lower()  # "skill", "agent", "mcp server": the message names what the person built
            except UnknownKind:
                noun = "skill"
            raise WrongState(f"This {noun} is a DRAFT ({why}). Say accept_draft to keep it anyway.")
        try:
            library = self._library(user).for_kind(kind)
        except UnknownKind as exc:
            raise BuilderError(str(exc)) from exc
        folder = self.builds_root / sid / result["folder"]
        if not folder.is_dir():
            raise BuilderError("The generated files are no longer on disk. Build it again.")
        report = import_skill(folder, library, note=(note.strip() or f"built in the web builder ({sid[:8]})")[:200])
        if not report.refused:
            with self.db.session() as s:
                row = self._row(s, sid, user)
                row.saved_name, row.saved_version, row.updated_at = report.name, report.version.tag, now_text()
        return report

    def discard(self, sid: str, user: str = LOCAL_USER_ID) -> None:
        with self.db.session() as s:
            row = self._row(s, sid, user)
            if row.status == "working":
                raise WrongState("It is still running. Wait for it to finish, then discard it.")
            s.execute(delete(Job).where(Job.session_id == sid))
            # The usage rows are a record of calls that were made, and a person's daily allowance on the server's model is counted from them (builder/model_access.py):
            # deleting them here gave the allowance back, so "start a build, discard it, start another" made the shared model free. They hold counts and timings only,
            # never a prompt or a reply, so they are kept, no longer tied to a session that is gone (the same as a suggestion run's or a Testing Lab run's rows).
            s.execute(update(ModelCall).where(ModelCall.session_id == sid).values(session_id=None))
            s.delete(row)
        shutil.rmtree(self.builds_root / sid, ignore_errors=True)  # sid is a checked 32-hex id, so this is our own folder

    # ---- the background jobs ---------------------------------------------------------------------

    def _event(self, job_id: int, message: str) -> None:
        with self.db.session() as s:
            job = s.get(Job, job_id)
            job.events = [*job.events, {"at": now_text(), "message": message}][-MAX_EVENTS * 2:]

    def _finish_job(self, job_id: int, status: str, error: str) -> None:
        with self.db.session() as s:
            job = s.get(Job, job_id)
            job.status, job.finished_at, job.error = status, now_text(), error

    def _fail(self, sid: str, job_id: int, message: str, retryable: bool) -> None:
        with self.db.session() as s:
            self._claim(s, sid, ("working",), status="failed", error=message, retryable=retryable)
        self._finish_job(job_id, "failed", message)

    def _execute(self, job_id: int) -> None:
        """Run one job and record how it ended. Never raises: a thread pool would swallow it."""
        with self.db.session() as s:
            job = s.get(Job, job_id)
            job.status, job.started_at = "running", now_text()
            sid, kind = job.session_id, job.kind
        progress = lambda message: self._event(job_id, message)  # noqa: E731
        try:
            (self._understand if kind == "understand" else self._build)(sid, progress, job_id)
            self._finish_job(job_id, "succeeded", "")
        except ProviderError as exc:  # a missing key or an unreachable model: running it again can help
            self._fail(sid, job_id, str(exc), True)
        except (BuildError, LibraryError, UnknownKind) as exc:
            self._fail(sid, job_id, str(exc), False)
        except Exception as exc:  # noqa: BLE001 - recorded for the person, and logged for whoever runs the server
            log.exception("builder job %s failed", job_id)
            self._fail(sid, job_id, f"Unexpected error ({type(exc).__name__}): {str(exc)[:300]}", False)

    def _provider(self, sid: str, job_id: int, user_id: str) -> LLMProvider:
        """The model for one job: whichever model this session's owner is to use, with every attempt counted for this session and for them."""
        return self.access.provider_for(user_id, session_id=sid, job_id=job_id)

    def _understand(self, sid: str, progress: Callable[[str], None], job_id: int) -> None:
        with self.db.session() as s:
            row = self._row(s, sid, None)  # a background job acts for the session's own owner
            words, round_no, kind_key, owner = row.words, row.round, row.kind, row.user_id
            previous = partial_of(row.partial_spec)
        kind = get_kind(kind_key)  # before the model is set up: a kind that is gone is not a missing key
        provider = self._provider(sid, job_id, owner)
        progress(f"Round {round_no}: reading your words and filling in the checklist")
        r = kind.understand(provider, words, round_no, MAX_ROUNDS, previous=previous)
        with self.db.session() as s:
            row = self._row(s, sid, None)
            row.model_calls += r.calls
            row.notes = [*row.notes, *r.notes]
            row.updated_at = now_text()
            if r.state == "complete":
                row.spec, row.questions, row.status = r.spec.model_dump(), [], "awaiting_approval"
            elif r.state == "questions":
                row.questions, row.status = [asdict(q) for q in r.questions], "awaiting_answers"
                row.partial_spec = r.spec.model_dump()  # the next round keeps from this whatever its model does not repeat (and the words still say)
        if r.state in ("blocked", "incomplete"):
            raise BuildError(r.message)

    def _build(self, sid: str, progress: Callable[[str], None], job_id: int) -> None:
        with self.db.session() as s:
            row = self._row(s, sid, None)
            spec, kind_key, seed, owner = row.spec, row.kind, row.seed, row.user_id
            with_scripts, calls, notes = row.with_scripts, row.model_calls, list(row.notes)
        kind = get_kind(kind_key)
        provider = self._provider(sid, job_id, owner)
        out_root = self.builds_root / sid
        shutil.rmtree(out_root, ignore_errors=True)  # this folder is ours alone; a retry starts clean
        outcome = kind.build(
            spec, provider, out_root=out_root, with_scripts=with_scripts, script_runner=self.script_runner,
            sandbox_note=self.sandbox_note(), calls=calls, notes=notes, progress=progress,
        )
        if seed:  # evidence of the code the idea cited, from the repository as it is now; a repository that is gone is a note, not a failure
            try:
                record_evidence(seed, out_root / outcome.summary["folder"], outcome.summary, outcome.notes)
            except Exception as exc:  # noqa: BLE001 - the thing is built and checked; evidence is an addition, so whatever goes wrong with it is a note
                log.exception("recording evidence for session %s failed", sid)
                outcome.notes.append(f"Evidence was not recorded: unexpected error ({type(exc).__name__}). The {kind_key} itself is built.")
        with self.db.session() as s:
            row = self._row(s, sid, None)
            row.result, row.model_calls, row.notes = outcome.summary, outcome.model_calls, outcome.notes
            row.status, row.updated_at = "done", now_text()
