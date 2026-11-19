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
import re
import shutil
import uuid
from collections.abc import Callable
from dataclasses import asdict
from pathlib import Path

from sqlalchemy import delete, select, update

from ..build.models import RequirementSpec
from ..build.pipeline import (
    BuildError, BuildResult, apply_answers, build_from_spec, check_description, sandbox_note as default_sandbox_note,
    understand_round,
)
from ..build.requirements import Question
from ..build.scripts import ScriptRunner
from ..db import BuildSession, Database, Job, now_text
from ..graph.store import data_dir
from ..library import ImportReport, Library, LibraryError, import_skill
from ..providers import LLMProvider, ProviderError
from ..validate.static import read_dir
from .jobs import JobRunner
from .provider import env_provider

MAX_ROUNDS = 3
MAX_EVENTS = 50
MAX_REPORT = 200_000
_ID = re.compile(r"^[0-9a-f]{32}$")
log = logging.getLogger(__name__)


class BuilderError(Exception):
    """Something the person can act on."""


class SessionNotFound(BuilderError):
    pass


class WrongState(BuilderError):
    """The session is not at the step this action belongs to (or someone else just moved it)."""


class BadRequest(BuilderError):
    pass


def _summary(result: BuildResult) -> dict:
    ran = [c for c in result.checks if c.status != "not run"]
    failed = sum(c.status == "failed" for c in ran)
    warned = sum(c.status == "warning" for c in ran)
    report = (result.out_dir / "report.md").read_text(encoding="utf-8")[:MAX_REPORT]
    return {
        "status": result.status, "draft_reason": result.draft_reason, "name": result.sdm.name,
        "description": result.sdm.description, "folder": result.out_dir.name, "files": result.files,
        "scripts": len(result.sdm.scripts), "report_md": report,
        "counts": {"passed": len(ran) - failed - warned, "warning": warned, "failed": failed, "not_run": len(result.checks) - len(ran)},
        "checks": [asdict(c) for c in result.checks],
    }


class Builder:
    def __init__(
        self, database: Database, library: Library, builds_root: Path, *,
        provider_factory: Callable[[], LLMProvider] = env_provider, runner: JobRunner | None = None,
        sandbox_note: Callable[[], str] = default_sandbox_note, script_runner: ScriptRunner | None = None,
    ) -> None:
        self.db = database
        self.library = library
        self.builds_root = Path(builds_root)
        self.provider_factory = provider_factory
        self.runner = runner or JobRunner()
        self.sandbox_note = sandbox_note
        self.script_runner = script_runner

    @classmethod
    def default(cls, library: Library) -> "Builder":
        """The real thing: the SQLite file in the per-user data folder, migrated, with interrupted work marked."""
        db = Database()
        db.migrate()
        db.recover_interrupted()
        return cls(db, library, data_dir() / "builds")

    def close(self) -> None:
        self.runner.shutdown()
        self.db.close()

    # ---- reading ---------------------------------------------------------------------------------

    def _row(self, s, sid: str) -> BuildSession:
        row = s.get(BuildSession, sid) if _ID.match(sid or "") else None
        if row is None:
            raise SessionNotFound("There is no such builder session.")
        return row

    def _latest_job(self, s, sid: str) -> Job | None:
        return s.execute(select(Job).where(Job.session_id == sid).order_by(Job.id.desc()).limit(1)).scalars().first()

    def get(self, sid: str) -> dict:
        with self.db.session() as s:
            row = self._row(s, sid)
            job = self._latest_job(s, sid)
            return {
                "id": row.id, "status": row.status, "description": row.description, "round": row.round,
                "max_rounds": MAX_ROUNDS, "with_scripts": row.with_scripts, "questions": row.questions,
                "spec": row.spec, "result": row.result, "error": row.error, "retryable": row.retryable,
                "model_calls": row.model_calls, "notes": row.notes,
                "saved": {"name": row.saved_name, "version": row.saved_version} if row.saved_version else None,
                "created_at": row.created_at, "updated_at": row.updated_at,
                "job": None if job is None else {
                    "kind": job.kind, "status": job.status, "started_at": job.started_at,
                    "finished_at": job.finished_at, "events": job.events[-MAX_EVENTS:],
                },
            }

    def list(self, limit: int = 50) -> list[dict]:
        with self.db.session() as s:
            rows = s.execute(select(BuildSession).order_by(BuildSession.created_at.desc()).limit(limit)).scalars().all()
            return [
                {
                    "id": r.id, "status": r.status, "description": r.description[:140], "created_at": r.created_at,
                    "updated_at": r.updated_at, "skill": (r.result or {}).get("name", ""),
                    "draft": bool(r.result and r.result.get("status") == "draft"),
                    "saved": {"name": r.saved_name, "version": r.saved_version} if r.saved_version else None,
                }
                for r in rows
            ]

    def read_file(self, sid: str, path: str) -> dict:
        """One generated file, looked up by name among the files that were written. Never a path on the disk."""
        with self.db.session() as s:
            result = self._row(s, sid).result
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

    def start(self, description: str, with_scripts: bool = False) -> dict:
        try:
            words = check_description(description)
        except BuildError as exc:
            raise BadRequest(str(exc)) from exc
        sid, stamp = uuid.uuid4().hex, now_text()
        with self.db.session() as s:
            s.add(BuildSession(
                id=sid, created_at=stamp, updated_at=stamp, status="working", description=words, words=words,
                round=1, with_scripts=with_scripts, questions=[], error="", retryable=False, model_calls=0,
                notes=[], saved_name="", saved_version="",
            ))
            job_id = self._new_job(s, sid, "understand")
        self.runner.submit(self._execute, job_id)
        return self.get(sid)

    def answer(self, sid: str, answers: dict[str, str]) -> dict:
        with self.db.session() as s:
            row = self._row(s, sid)
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
            if not self._claim(s, sid, ("awaiting_answers",), status="working", words=words, round=row.round + 1,
                               questions=[], error="", retryable=False):
                raise WrongState("This session just moved on. Reload it.")
            job_id = self._new_job(s, sid, "understand")
        self.runner.submit(self._execute, job_id)
        return self.get(sid)

    def approve(self, sid: str) -> dict:
        with self.db.session() as s:
            self._row(s, sid)
            if not self._claim(s, sid, ("awaiting_approval",), status="working", error="", retryable=False):
                raise WrongState("There is no requirement waiting for approval in this session.")
            job_id = self._new_job(s, sid, "build")
        self.runner.submit(self._execute, job_id)
        return self.get(sid)

    def retry(self, sid: str) -> dict:
        with self.db.session() as s:
            row = self._row(s, sid)
            if row.status != "failed" or not row.retryable:
                raise WrongState("Only a step that failed for a reason that can pass (such as a missing key) can be retried.")
            last = self._latest_job(s, sid)
            kind = last.kind if last else "understand"
            if not self._claim(s, sid, ("failed",), status="working", error="", retryable=False):
                raise WrongState("This session just moved on. Reload it.")
            job_id = self._new_job(s, sid, kind)
        self.runner.submit(self._execute, job_id)
        return self.get(sid)

    # ---- actions that finish ---------------------------------------------------------------------

    def save(self, sid: str, *, accept_draft: bool = False, note: str = "") -> ImportReport:
        """Put the built skill into the library through the same checked import as any other skill."""
        with self.db.session() as s:
            row = self._row(s, sid)
            result = row.result
            if row.status != "done" or not result:
                raise WrongState("There is no finished skill in this session yet.")
        if result["status"] == "draft" and not accept_draft:
            why = result["draft_reason"] or f"{result['counts']['failed']} check(s) failed"
            raise WrongState(f"This skill is a DRAFT ({why}). Say accept_draft to keep it anyway.")
        folder = self.builds_root / sid / result["folder"]
        if not folder.is_dir():
            raise BuilderError("The generated files are no longer on disk. Build it again.")
        report = import_skill(folder, self.library, note=(note.strip() or f"built in the web builder ({sid[:8]})")[:200])
        if not report.refused:
            with self.db.session() as s:
                row = self._row(s, sid)
                row.saved_name, row.saved_version, row.updated_at = report.name, report.version.tag, now_text()
        return report

    def discard(self, sid: str) -> None:
        with self.db.session() as s:
            row = self._row(s, sid)
            if row.status == "working":
                raise WrongState("It is still running. Wait for it to finish, then discard it.")
            s.execute(delete(Job).where(Job.session_id == sid))
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
            (self._understand if kind == "understand" else self._build)(sid, progress)
            self._finish_job(job_id, "succeeded", "")
        except ProviderError as exc:  # a missing key or an unreachable model: running it again can help
            self._fail(sid, job_id, str(exc), True)
        except (BuildError, LibraryError) as exc:
            self._fail(sid, job_id, str(exc), False)
        except Exception as exc:  # noqa: BLE001 - recorded for the person, and logged for whoever runs the server
            log.exception("builder job %s failed", job_id)
            self._fail(sid, job_id, f"Unexpected error ({type(exc).__name__}): {str(exc)[:300]}", False)

    def _understand(self, sid: str, progress: Callable[[str], None]) -> None:
        with self.db.session() as s:
            row = self._row(s, sid)
            words, round_no = row.words, row.round
        provider = self.provider_factory()
        progress(f"Round {round_no}: reading your words and filling in the checklist")
        r = understand_round(provider, words, round_no, MAX_ROUNDS)
        with self.db.session() as s:
            row = self._row(s, sid)
            row.model_calls += r.calls
            row.notes = [*row.notes, *r.notes]
            row.updated_at = now_text()
            if r.state == "complete":
                row.spec, row.questions, row.status = r.spec.model_dump(), [], "awaiting_approval"
            elif r.state == "questions":
                row.questions, row.status = [asdict(q) for q in r.questions], "awaiting_answers"
        if r.state in ("blocked", "incomplete"):
            raise BuildError(r.message)

    def _build(self, sid: str, progress: Callable[[str], None]) -> None:
        with self.db.session() as s:
            row = self._row(s, sid)
            spec = RequirementSpec.model_validate(row.spec)
            with_scripts, calls, notes = row.with_scripts, row.model_calls, list(row.notes)
        provider = self.provider_factory()
        out_root = self.builds_root / sid
        shutil.rmtree(out_root, ignore_errors=True)  # this folder is ours alone; a retry starts clean
        result = build_from_spec(
            spec, provider, out_root=out_root, force=True, sandbox_note=self.sandbox_note(),
            with_scripts=with_scripts, script_runner=self.script_runner, calls=calls, notes=notes, progress=progress,
        )
        with self.db.session() as s:
            row = self._row(s, sid)
            row.result, row.model_calls, row.notes = _summary(result), result.model_calls, result.notes
            row.status, row.updated_at = "done", now_text()
