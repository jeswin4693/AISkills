"""A repository over HTTP: what its graph says, ideas for it asked of a model in the background, and a guide to how it works read from its docs.

All of them read a folder on the machine the server runs on, so all are off in the hosted version (the folder would be the server's, not
the person's), like installing into a folder. The path a person types is never sent back: pages are shown the folder's name.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

from ..builder.guides import guide_repo
from ..builder.repository import analyze_repo, explore_calls, find_functions
from .builds import get_builder
from .scope import user_id

HOSTED_OFF = (
    "Reading a repository is turned off in the hosted version: it would read a folder on the server, not on your computer. "
    "Use the local app or the command line on your own computer."
)


class AnalyzeBody(BaseModel):
    path: str = Field(max_length=4096)  # an absolute folder on this computer
    focus: str | None = Field(default=None, max_length=400)  # only read this folder of the repository


class SuggestBody(AnalyzeBody):
    with_ideas: bool = True  # False: only the review pass (half the model calls)


class FunctionSearchBody(AnalyzeBody):
    query: str = Field(max_length=200)  # part of a function's name


class CallsBody(AnalyzeBody):
    symbol: str = Field(max_length=1000)  # a graph id from the search, such as `core.py::shared`
    depth: int = Field(default=1, ge=1, le=2)  # steps to follow: the functions around it, or those around those


def repos_router() -> APIRouter:
    r = APIRouter()

    def local_only(request: Request) -> None:
        if request.app.state.hosted is not None:
            raise HTTPException(403, HOSTED_OFF)

    @r.post("/repos/analyze")
    async def analyze(body: AnalyzeBody, request: Request) -> dict:
        """The graph's facts about a folder: size, languages and their honest levels, hotspots, dead-code candidates. No model."""
        local_only(request)
        return await run_in_threadpool(analyze_repo, body.path, body.focus)

    @r.post("/repos/functions")
    async def functions(body: FunctionSearchBody, request: Request) -> dict:
        """Search a repository's functions by name, to pick one to draw. No model. The graph is the same cached read as `analyze`."""
        local_only(request)
        return await run_in_threadpool(find_functions, body.path, body.focus, body.query)

    @r.post("/repos/calls")
    async def calls(body: CallsBody, request: Request) -> dict:
        """One function drawn with who calls it and what it calls (proven calls only), one step or two. No model, nothing is run."""
        local_only(request)
        return await run_in_threadpool(explore_calls, body.path, body.focus, body.symbol, body.depth)

    @r.post("/repos/guide")
    async def guide(body: AnalyzeBody, request: Request) -> dict:
        """How the project works, drawn from its README and docs: parts in layers and the routes an action takes through them. One model call,
        asked now (this request waits for it) and not saved. Every quote is checked against the documents by code. No README: no model is asked."""
        local_only(request)
        return await run_in_threadpool(guide_repo, body.path, body.focus, get_builder(request.app).provider_factory)

    @r.post("/suggestions", status_code=201)
    def start(body: SuggestBody, request: Request) -> dict:
        """Begin a run of the suggestions for a folder. The model is asked in the background: poll the run."""
        local_only(request)
        return get_builder(request.app).suggestions.start(body.path, body.focus, body.with_ideas, user=user_id(request))

    @r.get("/suggestions")
    def list_runs(request: Request) -> list[dict]:
        return get_builder(request.app).suggestions.list(user=user_id(request))

    @r.get("/suggestions/{rid}")
    def get_run(rid: str, request: Request) -> dict:
        return get_builder(request.app).suggestions.get(rid, user=user_id(request))

    @r.post("/suggestions/{rid}/retry")
    def retry(rid: str, request: Request) -> dict:
        local_only(request)
        return get_builder(request.app).suggestions.retry(rid, user=user_id(request))

    return r
