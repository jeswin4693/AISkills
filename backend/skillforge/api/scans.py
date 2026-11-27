"""The behaviour scan over HTTP: which tasks a scan of a skill or agent would run, and runs of it that are kept and polled (docs/canary-scan.md).

A run asks the model of the person it belongs to (like a build does), so it works in the hosted version too: it reads that person's library, never a folder. A person's runs are
theirs alone; another person's is "no such scan", the same answer as for one that never existed.
"""

from __future__ import annotations

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel, Field

from ..builder.scans import DEFAULT_SCENARIOS, RUN_CAP, SCENARIO_CAP
from .builds import get_builder
from .scope import user_id


class ScanBody(BaseModel):
    name: str = Field(max_length=64)
    version: int | None = Field(default=None, ge=1, le=1_000_000)  # None: the latest
    runs: int = Field(default=1, ge=1, le=RUN_CAP)  # how many times each task is run: models vary, so repeating says more
    scenarios: int = Field(default=DEFAULT_SCENARIOS, ge=1, le=SCENARIO_CAP)  # the most tasks
    control: bool = True  # also run a task that produced something without the skill: it is what shows who is to blame
    draft: bool = True  # a model drafts one more task from the description (one more model call)
    kind: str = Field(default="skill", max_length=64)


def scans_router() -> APIRouter:
    r = APIRouter()

    # The static path is registered before /scans/{rid}, or "preview" would be read as a run id.
    @r.get("/scans/preview")
    def preview(
        request: Request, name: str = Query(max_length=64), version: int | None = Query(default=None, ge=1, le=1_000_000),
        kind: str = Query(default="skill", max_length=64), runs: int = Query(default=1, ge=1, le=RUN_CAP),
        scenarios: int = Query(default=DEFAULT_SCENARIOS, ge=1, le=SCENARIO_CAP), control: bool = True, draft: bool = True,
    ) -> dict:
        """The tasks a scan would run and the most model calls it could make. No model is asked."""
        return get_builder(request.app).scans.preview(name, version, kind, user=user_id(request), runs=runs, scenarios=scenarios, control=control, draft=draft)

    @r.post("/scans", status_code=201)
    def start(body: ScanBody, request: Request) -> dict:
        """Begin a scan. The model is asked in the background: poll the run. Only a skill or an agent can be scanned."""
        return get_builder(request.app).scans.start(
            body.name, body.version, body.runs, body.scenarios, body.control, body.draft, body.kind, user=user_id(request),
        )

    @r.get("/scans")
    def list_runs(
        request: Request, name: str | None = Query(default=None, max_length=64), version: int | None = Query(default=None, ge=1, le=1_000_000),
        kind: str | None = Query(default=None, max_length=64),
    ) -> list[dict]:
        """This person's scans, newest first, each with a short summary and without its heavy result. `kind` (skill or agent) keeps a skill's page from showing an agent's scans."""
        return get_builder(request.app).scans.list(name, version, user=user_id(request), kind=kind)

    @r.get("/scans/{rid}")
    def get_run(rid: str, request: Request) -> dict:
        return get_builder(request.app).scans.get(rid, user=user_id(request))

    @r.post("/scans/{rid}/retry")
    def retry(rid: str, request: Request) -> dict:
        return get_builder(request.app).scans.retry(rid, user=user_id(request))

    return r
