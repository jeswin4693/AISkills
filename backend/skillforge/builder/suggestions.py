"""Suggestion runs: ideas for a repository, asked of a model in the background and polled like a build.

The same code as `skillforge suggest` runs (the graph, a review pass and an ideas pass, grounding that drops what cites nothing real);
what is new is only the bookkeeping: a run is a row in the database, so the result survives a reload and a click cannot spend the
quota twice. The repository's path stays in the row; the pages are shown the folder's name.
"""

from __future__ import annotations

import logging
import re
import threading
import uuid
from collections.abc import Callable

from sqlalchemy import select, update

from ..db import Database, SuggestRun, now_text
from ..graph.build import build_graph
from ..providers import LLMProvider, ProviderError
from ..suggest.pipeline import suggest as run_suggest
from .errors import BadRequest, SessionNotFound, WrongState
from .jobs import JobRunner
from .repository import check_repo, clean_focus, folder_name, read_failure

_ID = re.compile(r"^[0-9a-f]{32}\Z")
_START = threading.Lock()  # one check-then-add at a time: two clicks cannot both start a run for the same folder
log = logging.getLogger(__name__)


def run_view(row: SuggestRun) -> dict:
    return {
        "id": row.id, "status": row.status, "repo": row.repo_name, "focus": row.focus, "with_ideas": row.with_ideas,
        "result": row.result, "error": row.error, "retryable": row.retryable, "created_at": row.created_at, "updated_at": row.updated_at,
    }


class SuggestRuns:
    def __init__(self, db: Database, runner: JobRunner, provider_factory: Callable[[], LLMProvider]) -> None:
        self.db = db
        self.runner = runner
        self.provider_factory = provider_factory

    def _row(self, s, rid: str) -> SuggestRun:
        row = s.get(SuggestRun, rid) if _ID.match(rid or "") else None
        if row is None:
            raise SessionNotFound("There is no such suggestion run.")
        return row

    def start(self, path: object, focus: object = None, with_ideas: bool = True) -> dict:
        folder = check_repo(path)  # before any model is asked
        focus_text = clean_focus(focus)
        rid, stamp = uuid.uuid4().hex, now_text()
        with _START, self.db.session() as s:
            running = s.execute(
                select(SuggestRun).where(SuggestRun.status == "working", SuggestRun.repo == str(folder), SuggestRun.focus == focus_text)
            ).scalars().first()
            if running is not None:  # a second click while the model is still being asked gets that run, not another one
                return run_view(running)
            s.add(SuggestRun(
                id=rid, created_at=stamp, updated_at=stamp, status="working", repo=str(folder), repo_name=folder_name(folder),
                focus=focus_text, with_ideas=with_ideas, result=None, error="", retryable=False,
            ))
        self.runner.submit(self._execute, rid)
        return self.get(rid)

    def seed_for(self, rid: str, idea: object) -> dict:
        """The seed for a build from one idea of a finished run: the run's own folder and focus, and the places that idea cited.
        Nothing comes from the page, so a build can only ever be about the repository its idea was made for."""
        with self.db.session() as s:
            row = self._row(s, rid)
            if row.status != "done" or not row.result:
                raise BadRequest("That suggestion run is not finished (or it failed), so there is nothing to build from.")
            repo, focus, ideas = row.repo, row.focus, list(row.result.get("suggestions", []))
        if not isinstance(idea, int) or isinstance(idea, bool) or not 0 <= idea < len(ideas):
            raise BadRequest("Say which idea of the run to build from: idea is its position in the run, counting from 0.")
        item = ideas[idea]
        if item.get("category") not in ("skill", "automation") or not item.get("evidence_nodes"):
            raise BadRequest("Only a skill or automation idea that cites a place can start a build.")
        return {"repo": repo, "focus": focus, "nodes": list(item["evidence_nodes"])}

    def get(self, rid: str) -> dict:
        with self.db.session() as s:
            return run_view(self._row(s, rid))

    def list(self, limit: int = 30) -> list[dict]:
        with self.db.session() as s:
            rows = s.execute(select(SuggestRun).order_by(SuggestRun.created_at.desc()).limit(limit)).scalars().all()
            return [
                {**{k: v for k, v in run_view(r).items() if k != "result"}, "ideas": len((r.result or {}).get("suggestions", []))}
                for r in rows
            ]

    def retry(self, rid: str) -> dict:
        with self.db.session() as s:
            self._row(s, rid)
            claimed = s.execute(
                update(SuggestRun).where(SuggestRun.id == rid, SuggestRun.status == "failed")
                .values(status="working", error="", retryable=False, updated_at=now_text())
            ).rowcount == 1
        if not claimed:
            raise WrongState("Only a run that failed can be run again.")
        self.runner.submit(self._execute, rid)
        return self.get(rid)

    def _finish(self, rid: str, status: str, *, result: dict | None = None, error: str = "", retryable: bool = False) -> None:
        with self.db.session() as s:
            s.execute(
                update(SuggestRun).where(SuggestRun.id == rid)
                .values(status=status, result=result, error=error, retryable=retryable, updated_at=now_text())
            )

    def _execute(self, rid: str) -> None:
        """Run one suggestion pass and record how it ended. Never raises: a thread pool would swallow it."""
        with self.db.session() as s:
            row = self._row(s, rid)
            repo, focus, with_ideas = row.repo, row.focus, row.with_ideas
        try:
            provider = self.provider_factory()
            try:
                g = build_graph(repo, focus=focus)
            except (OSError, ValueError) as exc:  # only reading the folder: a ValueError later is not the folder's fault
                self._finish(rid, "failed", error=read_failure(exc))
                return
            self._finish(rid, "done", result=run_suggest(g, provider, with_ideas=with_ideas).to_dict())
        except ProviderError as exc:  # a missing key or an unreachable model: running it again can help
            self._finish(rid, "failed", error=str(exc), retryable=True)
        except Exception as exc:  # noqa: BLE001 - recorded for the person (without text that could hold a path), and logged for whoever runs the server
            log.exception("suggestion run %s failed", rid)
            self._finish(rid, "failed", error=f"Unexpected error ({type(exc).__name__}). The server's log has the details.")
