"""The Quality Report over HTTP: one version of one skill, assembled by code from what is stored (docs/quality-report.md). A GET: it changes nothing."""

from __future__ import annotations

from fastapi import APIRouter, Query, Request

from ..builder.errors import BadRequest
from ..builder.quality_report import build_report
from .builds import get_builder
from .scope import user_id, user_library


def quality_router() -> APIRouter:
    r = APIRouter()

    @r.get("/library/{name}/quality")
    def quality(
        name: str, request: Request, version: int | None = Query(default=None, ge=1, le=1_000_000), kind: str = Query(default="skill", max_length=64),
    ) -> dict:
        """Today's checks on a stored version, the requirement against its tests, the cost, the Testing Lab's result, what changed since the last
        version, what did not run, and what to do next. No model is asked and nothing is run. 400 for a version changed on disk or a kind that is
        not a skill, 404 for an unknown skill or version."""
        if kind != "skill":
            raise BadRequest(f"Only skills have a quality report here yet: a {kind} has its own definition file and no test harness.")
        runs = get_builder(request.app).evals.list(name, None, 200, user=user_id(request))
        return build_report(user_library(request), name, version, runs)

    return r
