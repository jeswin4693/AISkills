"""The Task Plan over HTTP (slice AM): a request planned before any work, as `python -m skillforge plan` does it.

It can read a folder on the machine the server runs on (and it asks that machine's model), so it is off in the hosted version like every route that
reads a folder. The person's own folder path is never sent back: a plan names the folder by its name, and a GitHub link as `owner/repo`.
"""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

from ..builder.plans import plan_task
from .builds import get_builder

HOSTED_OFF = (
    "The task plan is turned off in the hosted version: it can read a folder on the server, not on your computer, and it would use the server's model. "
    "Use the local app or the command line on your own computer."
)


class PlanBody(BaseModel):
    task: str = Field(min_length=1, max_length=8000)  # the request, in the person's own words
    repo: str | None = Field(default=None, max_length=4096)  # a folder on this computer or a public GitHub link; none or blank: no repository
    no_ai: bool = False  # send nothing to a model: only what the code can measure is planned
    kind: Literal["feature", "bugfix", "refactor", "migration", "docs", "investigation", "other"] | None = None  # replaces the model's guess
    tier: int | None = Field(default=None, ge=0, le=3)  # a tier can only be raised here: lowering one is a deliberate act of the command line
    budget: int | None = Field(default=None, ge=1, le=10_000_000)  # tokens the reading may cost
    sensitive: list[Annotated[str, Field(max_length=200)]] = Field(default_factory=list, max_length=10)  # path patterns that make a task tier 3


def plan_router() -> APIRouter:
    r = APIRouter()

    @r.post("/plan")
    async def plan(body: PlanBody, request: Request) -> dict:
        """Plan a task before doing it: what the request contains and does not say, its size from the code graph, the process, the rules and a token plan.
        One or two model calls unless `no_ai`; nothing is saved and nothing in the repository is changed or run."""
        if request.app.state.hosted is not None:
            raise HTTPException(403, HOSTED_OFF)
        return await run_in_threadpool(
            plan_task, body.task, body.repo, no_ai=body.no_ai, kind=body.kind, tier=body.tier, budget=body.budget, sensitive=body.sensitive,
            provider_factory=get_builder(request.app).provider_factory,
        )

    return r
