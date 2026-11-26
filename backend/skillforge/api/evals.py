"""The Testing Lab over HTTP: what a skill's test cases would do, and runs of them that are kept and polled.

A run asks the server's model (like a build does), so it works in the hosted version too: it reads the server's library, never a folder.
"""

from __future__ import annotations

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator

from ..build.models import Assertion, AssertionKind, TestKind
from ..builder import cases as case_editor
from ..builder.evals import RUN_CAP
from .builds import get_builder
from .scope import user_id, user_library
from .views import import_view


class RunBody(BaseModel):
    name: str = Field(max_length=64)
    version: int | None = Field(default=None, ge=1, le=1_000_000)  # None: the latest
    runs: int = Field(default=1, ge=1, le=RUN_CAP)  # how many times each case is asked: models vary, so repeating says more
    baseline: bool = True  # also ask without the skill: it is what shows whether the skill adds anything
    kind: str = Field(default="skill", max_length=64)


class CheckBody(BaseModel):
    kind: AssertionKind  # one of the seven checks code can run on a reply
    value: str = Field(max_length=case_editor.MAX_VALUE)
    why: str = Field(default="", max_length=case_editor.MAX_WHY)


class CaseBody(BaseModel):
    name: str = Field(max_length=case_editor.MAX_NAME)
    kind: TestKind
    message: str = Field(max_length=case_editor.MAX_MESSAGE)  # the exact message sent to the model
    checks: list[CheckBody] = Field(max_length=case_editor.MAX_CHECKS)
    covers: list[str] = Field(default_factory=list, max_length=case_editor.MAX_COVERS)  # ids of the acceptance criteria it checks, kept as they were

    @field_validator("covers")
    @classmethod
    def short_ids(cls, covers: list[str]) -> list[str]:
        if any(len(c) > case_editor.MAX_COVER for c in covers):
            raise ValueError(f"an id of a criterion is longer than {case_editor.MAX_COVER} characters")
        return covers


class CasesBody(BaseModel):
    base_version: int = Field(ge=1, le=1_000_000)  # the version that was edited: it must still be the latest
    cases: list[CaseBody] = Field(max_length=case_editor.MAX_CASES)
    note: str = Field(default="", max_length=200)


def evals_router() -> APIRouter:
    r = APIRouter()

    @r.get("/library/{name}/tests")
    def read_cases(
        name: str, request: Request, version: int | None = Query(default=None, ge=1, le=1_000_000),
    ) -> dict:
        """Every test case of a skill version (the ones that cannot be run too), and what an editor needs to know about it."""
        return case_editor.view_cases(user_library(request), name, version)

    # A POST and not a PUT: this API's CORS policy allows GET, POST and DELETE only, so a browser could not send a PUT.
    @r.post("/library/{name}/tests")
    def save_cases(name: str, body: CasesBody, request: Request) -> JSONResponse:
        """Keep these test cases as a NEW version, through the library's checked import (422 if a check refuses it). Only the latest version
        can be edited (409 otherwise), and a case that could not be run is a 400 that names it."""
        drafts = [
            case_editor.CaseDraft(
                c.name, c.kind, c.message, [Assertion(kind=k.kind, value=k.value, why=k.why) for k in c.checks], list(c.covers),
            )
            for c in body.cases
        ]
        report = case_editor.save_cases(user_library(request), name, body.base_version, drafts, body.note)
        return JSONResponse(import_view(report), status_code=422 if report.refused else 200)

    # The static path is registered before /evals/{rid}, or "preview" would be read as a run id.
    @r.get("/evals/preview")
    def preview(
        request: Request, name: str = Query(max_length=64), version: int | None = Query(default=None, ge=1, le=1_000_000),
        kind: str = Query(default="skill", max_length=64),
    ) -> dict:
        """What a run of this version would do (the cases, their checks, the number of model calls) or why it cannot be run. No model is asked."""
        return get_builder(request.app).evals.preview(name, version, kind, user=user_id(request))

    @r.post("/evals", status_code=201)
    def start(body: RunBody, request: Request) -> dict:
        """Begin a run. The model is asked in the background: poll the run. A skill that cannot be run is refused with the reason."""
        return get_builder(request.app).evals.start(body.name, body.version, body.runs, body.baseline, body.kind, user=user_id(request))

    @r.get("/evals")
    def list_runs(
        request: Request, name: str | None = Query(default=None, max_length=64), version: int | None = Query(default=None, ge=1, le=1_000_000),
    ) -> list[dict]:
        """Runs, newest first, each with a short summary and without its heavy result."""
        return get_builder(request.app).evals.list(name, version, user=user_id(request))

    @r.get("/evals/{rid}")
    def get_run(rid: str, request: Request) -> dict:
        return get_builder(request.app).evals.get(rid, user=user_id(request))

    @r.post("/evals/{rid}/retry")
    def retry(rid: str, request: Request) -> dict:
        return get_builder(request.app).evals.retry(rid, user=user_id(request))

    return r
