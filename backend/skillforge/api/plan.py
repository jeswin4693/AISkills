"""The Task Plan over HTTP: a request planned before any work, as `python -m skillforge plan` does it (slice AM), and kept, answered and approved (slice AN).

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
from .scope import user_id

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


class AnswersBody(BaseModel):
    """The answers and decisions of a plan, all of them: what is left out is removed. Positions are those the plan's own `questions` and `assumptions` list. The limits here only
    keep a request small; what an answer may be is decided (and said in words) by `conductor/approval.py`."""

    rev: int = Field(ge=0, le=1_000_000)  # the state the person was looking at
    questions: dict[Annotated[str, Field(max_length=12)], Annotated[str, Field(max_length=20_000)]] = Field(default_factory=dict, max_length=100)
    assumptions: dict[Annotated[str, Field(max_length=12)], Annotated[str | None, Field(max_length=16)]] = Field(default_factory=dict, max_length=100)


class ApproveBody(BaseModel):
    rev: int = Field(ge=0, le=1_000_000)  # the state the person was looking at: an approval is of what they saw


def _off(request: Request) -> None:
    if request.app.state.hosted is not None:
        raise HTTPException(403, HOSTED_OFF)


def plan_router() -> APIRouter:
    r = APIRouter()

    @r.post("/plan")
    async def plan(body: PlanBody, request: Request) -> dict:
        """Plan a task before doing it: what the request contains and does not say, its size from the code graph, the process, the rules and a token plan.
        One or two model calls unless `no_ai`; nothing is saved and nothing in the repository is changed or run."""
        _off(request)
        return await run_in_threadpool(
            plan_task, body.task, body.repo, no_ai=body.no_ai, kind=body.kind, tier=body.tier, budget=body.budget, sensitive=body.sensitive,
            provider_factory=get_builder(request.app).provider_factory,
        )

    return r


def plans_router() -> APIRouter:
    """Plans that are kept: made, listed, answered, approved, reopened and deleted. Nothing here asks a model except making the plan."""
    r = APIRouter()

    @r.post("/plans", status_code=201)
    async def keep(body: PlanBody, request: Request) -> dict:
        """Make a plan as `POST /api/plan` does and keep it. It is refused before the model is asked when the person already keeps the most plans."""
        _off(request)
        builder, user = get_builder(request.app), user_id(request)

        def work() -> dict:
            builder.plans.check_room(user)
            made = plan_task(
                body.task, body.repo, no_ai=body.no_ai, kind=body.kind, tier=body.tier, budget=body.budget, sensitive=body.sensitive,
                provider_factory=builder.provider_factory,
            )
            return builder.plans.keep(made, user)

        return await run_in_threadpool(work)

    @r.get("/plans")
    def list_plans(request: Request) -> list[dict]:
        """This person's kept plans, newest first: a short summary of each, without the plan."""
        _off(request)
        return get_builder(request.app).plans.list(user=user_id(request))

    @r.get("/plans/{pid}")
    def get_plan(pid: str, request: Request) -> dict:
        _off(request)
        return get_builder(request.app).plans.get(pid, user=user_id(request))

    @r.post("/plans/{pid}/answers")
    def save_answers(pid: str, body: AnswersBody, request: Request) -> dict:
        """Replace the answers and decisions (a POST, not a PUT: the CORS policy allows GET, POST and DELETE). `rev` is the state the person saw; 409 if it moved."""
        _off(request)
        return get_builder(request.app).plans.save_answers(pid, body.rev, body.questions, body.assumptions, user=user_id(request))

    @r.post("/plans/{pid}/approve")
    def approve(pid: str, body: ApproveBody, request: Request) -> dict:
        """Approve the state `rev` names. 409 with `missing` while a blocking question has no answer or an assumption has no decision."""
        _off(request)
        return get_builder(request.app).plans.approve(pid, body.rev, user=user_id(request))

    @r.post("/plans/{pid}/reopen")
    def reopen(pid: str, request: Request) -> dict:
        """Withdraw an approval so the answers can be changed. The answers stay; the log records it."""
        _off(request)
        return get_builder(request.app).plans.reopen(pid, user=user_id(request))

    @r.delete("/plans/{pid}")
    def delete(pid: str, request: Request) -> dict:
        _off(request)
        get_builder(request.app).plans.delete(pid, user=user_id(request))
        return {"deleted": True}

    return r
