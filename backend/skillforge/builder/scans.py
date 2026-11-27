"""Behaviour scan runs: a skill's or agent's instructions run in a simulated agent loop in the background, polled like a build (slice AK, docs/canary-scan.md).

The engine is the one `skillforge canary` uses (`canary/`): a model acts one structured step at a time on fake tools with planted fake secrets, and CODE judges every call and the
final reply. What is new here is only the bookkeeping, the same as for the Testing Lab (`evals.py`): a run is a row, so the result survives a reload, a second click cannot spend
the quota twice, and a run stays about the version it scanned. A preview says which tasks would run and the most model calls BEFORE any model is asked.

Nothing here decides anything about a skill: the outcome is the engine's code (`flagged`, `unclear`, `caution`, `incomplete`, `nothing_observed`, `not_run`), kept as it is. The run
spends the model of the person it belongs to, counts toward their runs at once, and is theirs alone (another person's run is "no such run").
"""

from __future__ import annotations

import logging
import re
import threading
import uuid
from collections.abc import Callable
from contextlib import nullcontext

from sqlalchemy import select, update

from ..canary.instructions import Instructions, load_instructions
from ..canary.judge import SEVERITIES, safe
from ..canary.runner import LIMITS, MAX_TURNS, CanaryReport, run_canary
from ..canary.runner import preview as engine_preview
from ..db import LOCAL_USER_ID, Database, ScanRun, now_text
from ..kinds import UnknownKind, get_kind
from ..library import Library, LibraryError, NotFound, Version
from ..providers import LLMProvider, ProviderError
from .errors import BadRequest, BuilderError, SessionNotFound, WrongState
from .evals import NOT_RETRYABLE
from .jobs import JobRunner
from .limits import PersonSpace

RUN_CAP = 3  # a task is run at most this many times (the command line allows 5: a stored result holds every transcript)
SCENARIO_CAP = 6  # tasks at most (the command line allows 8)
DEFAULT_SCENARIOS = 5
CALL_CAP = 500  # characters of one value of a tool call kept in a stored result
RESULT_CAP = 600  # characters of one tool result
TEXT_CAP = 2000  # characters of a task message or of the model's final reply
SCANNABLE = ("skill", "agent")  # what `load_instructions` accepts
_ID = re.compile(r"^[0-9a-f]{32}\Z")
_START = threading.Lock()  # one check-then-add at a time: two clicks cannot both start a run for the same version
log = logging.getLogger(__name__)


def _cut(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit] + "…"


def report_view(report: CanaryReport) -> dict:
    """The report as plain data a page can read: the outcome as a code, the verdict as words, every task with every step and finding, what did not run, and the limits sentence.
    Long text is cut (and marked with `…`) so a stored result stays small; the report the engine made is not changed (this works on a copy)."""
    view = report.to_dict()  # `asdict` copies every level
    for group in ("runs", "controls"):
        for run in view[group]:
            run["scenario"]["message"] = _cut(run["scenario"]["message"], TEXT_CAP)
            run["reply"] = _cut(run["reply"], TEXT_CAP)
            for turn in run["turns"]:
                # Written out visibly first (a NUL, a terminal escape or a right-to-left override can hide or reorder text, and some databases refuse a NUL), then cut.
                turn["call"] = {k: _cut(safe(v), CALL_CAP) if isinstance(v, str) else v for k, v in turn["call"].items()}
                turn["result"] = _cut(safe(turn["result"]), RESULT_CAP)
    view["limits"] = LIMITS
    return view


def _summary(result: dict | None) -> dict | None:
    """What the list of runs shows: the outcome, the calls, how many serious findings, and how many task runs finished."""
    if not result:
        return None
    serious = SEVERITIES.index("medium")
    runs = result["runs"]
    return {
        "outcome": result["outcome"], "calls": result["calls"],
        "findings": sum(1 for r in runs for o in r["observations"] if o["severity"] in SEVERITIES and SEVERITIES.index(o["severity"]) >= serious),
        "finished": sum(1 for r in runs if r["finished"] and not r["error"]), "total": len(runs),
    }


def run_view(row: ScanRun, *, full: bool = True) -> dict:
    view = {
        "id": row.id, "status": row.status, "kind": row.kind, "name": row.name, "version": row.version, "tag": f"v{row.version}", "content_hash": row.content_hash,
        "runs": row.runs, "scenarios": row.scenarios, "control": row.control, "draft": row.draft,
        "progress": {"done": row.tasks_done, "total": row.tasks_total}, "error": row.error, "retryable": row.retryable,
        "created_at": row.created_at, "updated_at": row.updated_at,
    }
    if full:
        view["result"] = row.result
    else:
        view["summary"] = _summary(row.result)
    return view


def _clamp(runs: int, scenarios: int) -> tuple[int, int]:
    """The route bounds these; a caller that does not gets the same bounds."""
    return min(max(1, runs), RUN_CAP), min(max(1, scenarios), SCENARIO_CAP)


class ScanRuns:
    def __init__(
        self, db: Database, runner: JobRunner, provider_for: Callable[[str], LLMProvider], library: Library,
        library_for: Callable[[str], Library] | None = None, space: PersonSpace | None = None,
    ) -> None:
        self.db = db
        self.space = space  # per-person limits; None: no limits
        self.runner = runner
        self.provider_for = provider_for  # the model for a person's run, by their id (ModelAccess.provider_for)
        self.library = library  # the owner's
        self.library_for = library_for  # a person's, by id

    def _room(self):
        """The admission lock of per-person limits, held with the start lock so a scan and a build cannot both take the last place."""
        return self.space.lock if self.space is not None else nullcontext()

    def _admit(self, user: str) -> None:
        if self.space is not None:
            self.space.admit(user)  # the counts only: a scan writes next to nothing to disk

    def _library(self, user: str) -> Library:
        """A person's library. Fails closed: with no resolver only the owner has one."""
        if self.library_for is not None:
            return self.library_for(user)
        if user == LOCAL_USER_ID:
            return self.library
        raise BuilderError("There is no library for that user.")

    # ---- what would run ---------------------------------------------------------------------------------

    def _load(self, name: str, version: int | None, kind: str, user: str) -> tuple[Version, Instructions]:
        try:
            spec = get_kind(kind)
        except UnknownKind as exc:
            raise BadRequest(str(exc)) from exc
        if kind not in SCANNABLE:
            raise BadRequest(
                f"Only skills and agents can be scanned: the scan runs the instructions an agent loads, and {spec.label.lower()}s have none. "
                "A plugin or an MCP server is checked through the skills and agents it holds."
            )
        v, files = self._library(user).for_kind(kind).read(name, version)  # this person's library; checks every file against the manifest first
        try:
            return v, load_instructions(files)
        except ValueError as exc:  # no SKILL.md or AGENT.md: said as the engine says it
            raise BadRequest(str(exc)) from exc

    def preview(
        self, name: str, version: int | None = None, kind: str = "skill", user: str = LOCAL_USER_ID, runs: int = 1,
        scenarios: int = DEFAULT_SCENARIOS, control: bool = True, draft: bool = True,
    ) -> dict:
        """The tasks that would run and the most model calls, before any model is asked. A task a model would draft from the description is not in the list (`draft` says one more call)."""
        v, instructions = self._load(name, version, kind, user)
        runs, scenarios = _clamp(runs, scenarios)
        plan = engine_preview(instructions, runs=runs, max_scenarios=scenarios, control=control)
        # With a drafted task the engine plans up to three from a model's answer, and they take the place of fixed tasks so that `scenarios` run in all: the list below cannot say
        # which, but the most there can be is known. (Without the draft the list is exactly what runs.)
        most_tasks = scenarios if draft else len(plan.scenarios)
        max_calls = most_tasks * runs * MAX_TURNS * (2 if control else 1) + (1 if draft else 0)
        return {
            "name": v.name, "kind": kind, "version": v.version, "tag": v.tag, "content_hash": v.content_hash,
            "tasks": [{"id": s.id, "message": _cut(s.message, TEXT_CAP), "source": s.source} for s in plan.scenarios],
            "runs": runs, "scenarios": scenarios, "control": control, "draft": draft, "max_tasks": most_tasks, "max_calls": max_calls,
            "declared": sorted(instructions.declared) if instructions.declared is not None else None, "scripts": list(instructions.scripts),
            "limits": {"max_runs": RUN_CAP, "max_scenarios": SCENARIO_CAP, "default_scenarios": DEFAULT_SCENARIOS}, "limits_text": LIMITS,
        }

    # ---- runs -------------------------------------------------------------------------------------------

    def _row(self, s, rid: str, user: str | None) -> ScanRun:
        """A run, if it is `user`'s. Someone else's is "no such run", the very answer for one that never existed. `user` has no default so a caller cannot forget it;
        only the background job passes None (it acts for the run's own owner)."""
        row = s.get(ScanRun, rid) if _ID.match(rid or "") else None
        if row is None or (user is not None and row.user_id != user):
            raise SessionNotFound("There is no such scan.")
        return row

    def start(
        self, name: str, version: int | None = None, runs: int = 1, scenarios: int = DEFAULT_SCENARIOS, control: bool = True, draft: bool = True,
        kind: str = "skill", user: str = LOCAL_USER_ID,
    ) -> dict:
        v, instructions = self._load(name, version, kind, user)
        runs, scenarios = _clamp(runs, scenarios)
        plan = engine_preview(instructions, runs=runs, max_scenarios=scenarios, control=control)
        rid, stamp = uuid.uuid4().hex, now_text()
        with _START, self._room(), self.db.session() as s:
            running = s.execute(  # this person's own run: a second click never hands out somebody else's
                select(ScanRun).where(
                    ScanRun.status == "working", ScanRun.kind == kind, ScanRun.name == v.name, ScanRun.version == v.version, ScanRun.user_id == user,
                )
            ).scalars().first()
            if running is not None:  # a second click while the model is still being asked gets that run, not another
                return run_view(running)
            self._admit(user)
            s.add(ScanRun(
                id=rid, created_at=stamp, updated_at=stamp, status="working", kind=kind, name=v.name, version=v.version, content_hash=v.content_hash, runs=runs,
                scenarios=scenarios, control=control, draft=draft, tasks_total=len(plan.scenarios) * runs, tasks_done=0, result=None, error="", retryable=False, user_id=user,
            ))
        self.runner.submit(self._execute, rid)
        return self.get(rid, user)

    def get(self, rid: str, user: str = LOCAL_USER_ID) -> dict:
        with self.db.session() as s:
            return run_view(self._row(s, rid, user))

    def list(self, name: str | None = None, version: int | None = None, limit: int = 50, user: str = LOCAL_USER_ID, kind: str | None = None) -> list[dict]:
        """This person's scans, newest first. Libraries are per kind, so a skill and an agent can have one name and one version number: ask for the kind."""
        query = select(ScanRun).where(ScanRun.user_id == user).order_by(ScanRun.created_at.desc(), ScanRun.id.desc()).limit(limit)
        if kind is not None:
            query = query.where(ScanRun.kind == kind)
        if name is not None:
            query = query.where(ScanRun.name == name)
        if version is not None:
            query = query.where(ScanRun.version == version)
        with self.db.session() as s:
            return [run_view(r, full=False) for r in s.execute(query).scalars().all()]

    def retry(self, rid: str, user: str = LOCAL_USER_ID) -> dict:
        with _START, self._room(), self.db.session() as s:  # the same locks as start(): a retry is a run, so it counts for "one at a time" and for the person's places
            row = self._row(s, rid, user)
            going = s.execute(
                select(ScanRun).where(
                    ScanRun.status == "working", ScanRun.kind == row.kind, ScanRun.name == row.name, ScanRun.version == row.version, ScanRun.id != rid, ScanRun.user_id == user,
                )
            ).scalars().first()
            if going is not None and row.status == "failed":
                raise WrongState("A scan of this version is already going. Wait for it to finish, or open it from the list of earlier scans.")
            if row.status == "failed":
                self._admit(user)
            claimed = s.execute(
                update(ScanRun).where(ScanRun.id == rid, ScanRun.status == "failed")
                .values(status="working", error="", retryable=False, tasks_done=0, result=None, updated_at=now_text())
            ).rowcount == 1
        if not claimed:
            raise WrongState("Only a scan that failed can be run again.")
        self.runner.submit(self._execute, rid)
        return self.get(rid, user)

    # ---- the background run -----------------------------------------------------------------------------

    def _progress(self, rid: str, done: int, total: int) -> None:
        try:  # progress is only for show: it must never stop a run
            with self.db.session() as s:
                s.execute(update(ScanRun).where(ScanRun.id == rid).values(tasks_done=done, tasks_total=total, updated_at=now_text()))
        except Exception:  # noqa: BLE001
            log.warning("could not record the progress of scan %s", rid, exc_info=True)

    def _finish(self, rid: str, status: str, *, result: dict | None = None, error: str = "", retryable: bool = False) -> None:
        values: dict = {"status": status, "result": result, "error": error, "retryable": retryable, "updated_at": now_text()}
        if result is not None:
            values["tasks_done"] = values["tasks_total"] = len(result["runs"])
        with self.db.session() as s:
            s.execute(update(ScanRun).where(ScanRun.id == rid).values(**values))

    def _execute(self, rid: str) -> None:
        """Run the scan and record how it ended. Never raises: a thread pool would swallow it."""
        with self.db.session() as s:
            row = self._row(s, rid, None)  # a background job acts for the run's own owner
            name, version, kind, runs, scenarios, control, draft, owner = row.name, row.version, row.kind, row.runs, row.scenarios, row.control, row.draft, row.user_id
        try:
            provider = self.provider_for(owner)  # whose spending this is: the person the run belongs to
            _, instructions = self._load(name, version, kind, owner)
            report = run_canary(
                provider, instructions, runs=runs, max_scenarios=scenarios, control=control, draft=draft,
                on_scenario=lambda done, total: self._progress(rid, done, total),
            )
            self._finish(rid, "done", result=report_view(report))
        except ProviderError as exc:  # no model set up, a bad key, a busy or unreachable model: fixing that and running again can help; a refusal cannot
            self._finish(rid, "failed", error=str(exc), retryable=exc.kind not in NOT_RETRYABLE)
        except (BuilderError, LibraryError, NotFound) as exc:  # the version is gone or was changed on disk: said as the library says it
            self._finish(rid, "failed", error=str(exc))
        except Exception as exc:  # noqa: BLE001 - recorded without its text (it could hold a path), and logged for whoever runs the server
            log.exception("scan %s failed", rid)
            self._finish(rid, "failed", error=f"Unexpected error ({type(exc).__name__}). The server's log has the details.")
