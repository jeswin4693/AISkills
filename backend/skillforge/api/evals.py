"""The Testing Lab over HTTP: what a skill's test cases would do, and runs of them that are kept and polled.

A run asks the server's model (like a build does), so it works in the hosted version too: it reads the server's library, never a folder.
"""

from __future__ import annotations

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel, Field

from ..builder.evals import RUN_CAP
from .builds import get_builder


class RunBody(BaseModel):
    name: str = Field(max_length=64)
    version: int | None = Field(default=None, ge=1, le=1_000_000)  # None: the latest
    runs: int = Field(default=1, ge=1, le=RUN_CAP)  # how many times each case is asked: models vary, so repeating says more
    baseline: bool = True  # also ask without the skill: it is what shows whether the skill adds anything
    kind: str = Field(default="skill", max_length=64)


def evals_router() -> APIRouter:
    r = APIRouter()

    # The static path is registered before /evals/{rid}, or "preview" would be read as a run id.
    @r.get("/evals/preview")
    def preview(
        request: Request, name: str = Query(max_length=64), version: int | None = Query(default=None, ge=1, le=1_000_000),
        kind: str = Query(default="skill", max_length=64),
    ) -> dict:
        """What a run of this version would do (the cases, their checks, the number of model calls) or why it cannot be run. No model is asked."""
        return get_builder(request.app).evals.preview(name, version, kind)

    @r.post("/evals", status_code=201)
    def start(body: RunBody, request: Request) -> dict:
        """Begin a run. The model is asked in the background: poll the run. A skill that cannot be run is refused with the reason."""
        return get_builder(request.app).evals.start(body.name, body.version, body.runs, body.baseline, body.kind)

    @r.get("/evals")
    def list_runs(
        request: Request, name: str | None = Query(default=None, max_length=64), version: int | None = Query(default=None, ge=1, le=1_000_000),
    ) -> list[dict]:
        """Runs, newest first, each with a short summary and without its heavy result."""
        return get_builder(request.app).evals.list(name, version)

    @r.get("/evals/{rid}")
    def get_run(rid: str, request: Request) -> dict:
        return get_builder(request.app).evals.get(rid)

    @r.post("/evals/{rid}/retry")
    def retry(rid: str, request: Request) -> dict:
        return get_builder(request.app).evals.retry(rid)

    return r
