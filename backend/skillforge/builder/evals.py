"""Testing Lab runs: a skill version's own test cases run against a model in the background, polled like a build.

The engine is the one `skillforge eval` uses (`evaluate/`): the model answers with the skill and without it, code grades the replies. What is
new here is only the bookkeeping: a run is a row in the database, so the result survives a reload, a second click cannot spend the quota twice,
and a run stays about the version it tested. A preview says what would run (and why a skill cannot be run) before any model is asked.
"""

from __future__ import annotations

import logging
import re
import threading
import uuid
from collections.abc import Callable

from sqlalchemy import select, update

from ..build.quality import estimate_tokens
from ..db import LOCAL_USER_ID, Database, EvalRun, now_text
from ..evaluate import LIMITS, MAX_CASES, MIN_CASES, Attempt, EvalReport, LoadedSkill, blocker, load_files, plan_cases, run_eval
from ..kinds import UnknownKind, get_kind
from ..library import Library, LibraryError, NotFound, Version
from ..providers import LLMProvider, ProviderError
from .errors import BadRequest, BuilderError, SessionNotFound, WrongState
from .jobs import JobRunner

RUN_CAP = 5  # a case is repeated at most this many times
MESSAGE_CAP = 2000  # characters of a test message kept in a view
REPLY_CAP = 3000  # characters of a model's reply kept in a result
_ID = re.compile(r"^[0-9a-f]{32}\Z")
_START = threading.Lock()  # one check-then-add at a time: two clicks cannot both start a run for the same version
log = logging.getLogger(__name__)


def _cut(text: str, limit: int) -> tuple[str, bool]:
    return (text[:limit], True) if len(text) > limit else (text, False)


CHECK_TEXT_CAP = 300  # a check's value, reason and detail: a skill saved before the editor can hold a value of any size, and a result must stay small
NOT_RETRYABLE = {"refused", "bad_request", "invalid_output", "too_long", "input_too_large", "budget"}  # asking again cannot help; fixing a key or a setting can


def _short(text: str) -> str:
    """A check's text for a view, with a mark where it was cut."""
    return text if len(text) <= CHECK_TEXT_CAP else text[:CHECK_TEXT_CAP] + "…"


def _attempt_view(attempt: Attempt) -> dict:
    tries = []
    for reply, results in zip(attempt.replies, attempt.results):
        text, cut = _cut(reply, REPLY_CAP)
        tries.append({
            "reply": text, "cut": cut, "passed": all(r.passed for r in results),
            "checks": [
                {"kind": r.kind, "value": _short(r.value), "why": _short(r.why), "passed": r.passed, "detail": _short(r.detail)} for r in results
            ],
        })
    return {"passed": attempt.passed, "runs": attempt.runs, "tries": tries}


def report_view(report: EvalReport) -> dict:
    """The report as plain data a page can read: the outcome as a code, the verdict as words, the counts, and every case with every reply and
    every check. Replies and messages are cut (and marked) so a stored result stays small."""
    w, wn = report.with_passed
    b, bn = report.baseline_passed
    cases = []
    for c in report.cases:
        message, message_cut = _cut(c.run_input, MESSAGE_CAP)
        cases.append({
            "name": c.name, "kind": c.kind, "message": message, "message_cut": message_cut,
            "with_skill": _attempt_view(c.with_skill), "baseline": _attempt_view(c.baseline) if c.baseline else None,
        })
    return {
        "outcome": report.outcome(), "verdict": report.verdict(), "limits": LIMITS, "runnable": report.runnable, "reason": report.reason,
        "runs": report.runs, "calls": report.calls, "skill_tokens": report.skill_tokens, "min_cases": MIN_CASES,
        "with_skill": {"passed": w, "total": wn}, "baseline": {"passed": b, "total": bn} if bn else None,
        "skipped": list(report.skipped), "cases": cases,
    }


def run_view(row: EvalRun, *, full: bool = True) -> dict:
    view = {
        "id": row.id, "status": row.status, "kind": row.kind, "name": row.name, "version": row.version, "tag": f"v{row.version}",
        "content_hash": row.content_hash, "runs": row.runs, "baseline": row.baseline,
        "progress": {"done": row.cases_done, "total": row.cases_total}, "error": row.error, "retryable": row.retryable,
        "created_at": row.created_at, "updated_at": row.updated_at,
    }
    if full:
        view["result"] = row.result
    else:
        res = row.result
        view["summary"] = None if not res else {
            "outcome": res["outcome"], "with_skill": res["with_skill"], "baseline": res["baseline"], "calls": res["calls"],
        }
    return view


class EvalRuns:
    def __init__(
        self, db: Database, runner: JobRunner, provider_for: Callable[[str], LLMProvider], library: Library,
        library_for: Callable[[str], Library] | None = None,
    ) -> None:
        self.db = db
        self.runner = runner
        self.provider_for = provider_for  # the model for a person's run, by their id (ModelAccess.provider_for)
        self.library = library  # the owner's
        self.library_for = library_for  # a person's, by id

    def _library(self, user: str) -> Library:
        """A person's library. Fails closed: with no resolver only the owner has one."""
        if self.library_for is not None:
            return self.library_for(user)
        if user == LOCAL_USER_ID:
            return self.library
        raise BuilderError("There is no library for that user.")

    # ---- what would run ---------------------------------------------------------------------------------

    def _load(self, name: str, version: int | None, kind: str, user: str) -> tuple[Version, LoadedSkill]:
        try:
            spec = get_kind(kind)
        except UnknownKind as exc:
            raise BadRequest(str(exc)) from exc
        if kind != "skill":
            raise BadRequest(f"Only skills can be tested here yet: a test case is a message sent to a model that has the skill, and {spec.label.lower()}s have no such harness.")
        v, files = self._library(user).for_kind(kind).read(name, version)  # this person's library; checks every file against the manifest first
        try:
            return v, load_files(files)
        except ValueError as exc:
            raise BadRequest(str(exc)) from exc

    def _preview(self, v: Version, skill: LoadedSkill, kind: str) -> dict:
        code, why = blocker(skill)
        planned, skipped = ([], []) if code else plan_cases(skill)
        if not code and not planned:
            code, why = "nothing_runnable", f"none of its {len(skill.tests)} test case(s) has a message to send and a check to run"
        cases = []
        for t in planned:
            message, message_cut = _cut(t.run_input, MESSAGE_CAP)
            cases.append({
                "name": t.name, "kind": t.kind, "message": message, "message_cut": message_cut,
                "checks": [{"kind": x.kind, "value": _short(x.value), "why": _short(x.why)} for x in t.assertions],
            })
        return {
            "name": v.name, "kind": kind, "version": v.version, "tag": v.tag, "content_hash": v.content_hash,
            "skill_tokens": estimate_tokens(skill.text),
            "runnable": not code, "blocker": code, "reason": why, "cases": cases, "skipped": skipped,
            "calls": {"per_run": len(planned), "per_run_with_baseline": 2 * len(planned)},
            "limits": {"max_cases": MAX_CASES, "min_cases": MIN_CASES, "max_runs": RUN_CAP},
        }

    def preview(self, name: str, version: int | None = None, kind: str = "skill", user: str = LOCAL_USER_ID) -> dict:
        """What a run of this version would do, and why not if it cannot. No model is asked."""
        v, skill = self._load(name, version, kind, user)
        return self._preview(v, skill, kind)

    # ---- runs --------------------------------------------------------------------------------------------

    def _row(self, s, rid: str, user: str | None) -> EvalRun:
        """A run, if it is `user`'s. Someone else's is "no such run", the very answer for one that never existed. `user` has no default so a caller cannot forget it;
        only the background job passes None (it acts for the run's own owner)."""
        row = s.get(EvalRun, rid) if _ID.match(rid or "") else None
        if row is None or (user is not None and row.user_id != user):
            raise SessionNotFound("There is no such test run.")
        return row

    def start(self, name: str, version: int | None = None, runs: int = 1, baseline: bool = True, kind: str = "skill", user: str = LOCAL_USER_ID) -> dict:
        v, skill = self._load(name, version, kind, user)
        plan = self._preview(v, skill, kind)
        if not plan["runnable"]:
            raise BadRequest(f"Nothing was run: {plan['reason']}.")
        rid, stamp = uuid.uuid4().hex, now_text()
        with _START, self.db.session() as s:
            running = s.execute(  # this person's own run: a second click never hands out somebody else's
                select(EvalRun).where(
                    EvalRun.status == "working", EvalRun.kind == kind, EvalRun.name == v.name, EvalRun.version == v.version, EvalRun.user_id == user,
                )
            ).scalars().first()
            if running is not None:  # a second click while the model is still being asked gets that run, not another one
                return run_view(running)
            s.add(EvalRun(
                id=rid, created_at=stamp, updated_at=stamp, status="working", kind=kind, name=v.name, version=v.version,
                content_hash=v.content_hash, runs=runs, baseline=baseline, cases_total=len(plan["cases"]), cases_done=0,
                result=None, error="", retryable=False, user_id=user,
            ))
        self.runner.submit(self._execute, rid)
        return self.get(rid, user)

    def get(self, rid: str, user: str = LOCAL_USER_ID) -> dict:
        with self.db.session() as s:
            return run_view(self._row(s, rid, user))

    def list(self, name: str | None = None, version: int | None = None, limit: int = 50, user: str = LOCAL_USER_ID) -> list[dict]:
        query = select(EvalRun).where(EvalRun.user_id == user).order_by(EvalRun.created_at.desc(), EvalRun.id.desc()).limit(limit)
        if name is not None:
            query = query.where(EvalRun.name == name)
        if version is not None:
            query = query.where(EvalRun.version == version)
        with self.db.session() as s:
            return [run_view(r, full=False) for r in s.execute(query).scalars().all()]

    def retry(self, rid: str, user: str = LOCAL_USER_ID) -> dict:
        with _START, self.db.session() as s:  # the same lock as start(): a retry is a run of that version, so it counts for "one run at a time"
            row = self._row(s, rid, user)
            going = s.execute(
                select(EvalRun).where(
                    EvalRun.status == "working", EvalRun.kind == row.kind, EvalRun.name == row.name, EvalRun.version == row.version, EvalRun.id != rid,
                    EvalRun.user_id == user,
                )
            ).scalars().first()
            if going is not None and row.status == "failed":
                raise WrongState("A run of this version is already going. Wait for it to finish, or open it from the list of earlier runs.")
            claimed = s.execute(
                update(EvalRun).where(EvalRun.id == rid, EvalRun.status == "failed")
                .values(status="working", error="", retryable=False, cases_done=0, result=None, updated_at=now_text())
            ).rowcount == 1
        if not claimed:
            raise WrongState("Only a run that failed can be run again.")
        self.runner.submit(self._execute, rid)
        return self.get(rid, user)

    def _progress(self, rid: str, done: int, total: int) -> None:
        try:  # progress is only for show: it must never stop a run
            with self.db.session() as s:
                s.execute(update(EvalRun).where(EvalRun.id == rid).values(cases_done=done, cases_total=total, updated_at=now_text()))
        except Exception:  # noqa: BLE001
            log.warning("could not record the progress of test run %s", rid, exc_info=True)

    def _finish(self, rid: str, status: str, *, result: dict | None = None, error: str = "", retryable: bool = False) -> None:
        values: dict = {"status": status, "result": result, "error": error, "retryable": retryable, "updated_at": now_text()}
        if result is not None:
            values["cases_done"] = values["cases_total"] = len(result["cases"])
        with self.db.session() as s:
            s.execute(update(EvalRun).where(EvalRun.id == rid).values(**values))

    def _execute(self, rid: str) -> None:
        """Run the cases and record how it ended. Never raises: a thread pool would swallow it."""
        with self.db.session() as s:
            row = self._row(s, rid, None)  # a background job acts for the run's own owner
            name, version, kind, runs, baseline, owner = row.name, row.version, row.kind, row.runs, row.baseline, row.user_id
        try:
            provider = self.provider_for(owner)  # whose spending this is: the person the run belongs to
            _, skill = self._load(name, version, kind, owner)
            report = run_eval(provider, skill, baseline=baseline, runs=runs, on_case=lambda done, total: self._progress(rid, done, total))
            self._finish(rid, "done", result=report_view(report))
        except ProviderError as exc:  # no model set up, a bad key, a busy or unreachable model: fixing that and running again can help; a refusal cannot
            self._finish(rid, "failed", error=str(exc), retryable=exc.kind not in NOT_RETRYABLE)
        except (BuilderError, LibraryError, NotFound) as exc:  # the version is gone or was changed on disk: said as the library says it
            self._finish(rid, "failed", error=str(exc))
        except Exception as exc:  # noqa: BLE001 - recorded without its text (it could hold a path), and logged for whoever runs the server
            log.exception("test run %s failed", rid)
            self._finish(rid, "failed", error=f"Unexpected error ({type(exc).__name__}). The server's log has the details.")
