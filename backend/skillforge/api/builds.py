"""The skill builder over HTTP: a session you talk to across requests, with slow steps run as polled background jobs."""

from __future__ import annotations

from fastapi import APIRouter, FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator

from ..ai.doctor import check_models
from ..builder import Builder, env_provider, provider_status
from ..providers import ProviderError
from .views import import_view

MAX_DESCRIPTION = 10_000
MAX_ANSWER = 5_000


class StartBody(BaseModel):
    description: str = Field(max_length=MAX_DESCRIPTION)
    with_scripts: bool = False
    kind: str = Field(default="skill", max_length=64)  # a registered kind; the builder refuses any other


class AnswersBody(BaseModel):
    answers: dict[str, str]

    @field_validator("answers")
    @classmethod
    def not_too_long(cls, answers: dict[str, str]) -> dict[str, str]:
        if any(len(a) > MAX_ANSWER for a in answers.values()):
            raise ValueError(f"an answer is longer than {MAX_ANSWER} characters")
        return answers


class SaveBody(BaseModel):
    accept_draft: bool = False
    note: str = Field(default="", max_length=200)


def get_builder(app: FastAPI) -> Builder:
    """The builder, made on first use: a server that is only used for the library never opens the database."""
    with app.state.builder_lock:
        if app.state.builder is None:
            app.state.builder = Builder.default(app.state.library)
        return app.state.builder


def builds_router() -> APIRouter:
    r = APIRouter()

    def builder(request: Request) -> Builder:
        return get_builder(request.app)

    @r.get("/provider")
    def provider(request: Request) -> dict:
        """Is a model set up, and which. Never a key, and no call to the model."""
        existing = request.app.state.builder
        return provider_status(existing.provider_factory if existing else env_provider)

    @r.post("/provider/check")
    def provider_check(request: Request) -> dict:
        """One tiny call to each distinct model that is set up, so a person can see that each key and model really works.
        It uses a little quota, so it runs only when asked. Never returns a key."""
        existing = request.app.state.builder
        factory = existing.provider_factory if existing else env_provider
        try:
            provider = factory()
        except ProviderError as exc:
            return {"configured": False, "detail": str(exc), "checks": []}
        return {"configured": True, "detail": "", "checks": check_models(provider)}

    @r.get("/builds")
    def list_builds(request: Request) -> list[dict]:
        return builder(request).list()

    @r.post("/builds", status_code=201)
    def start(body: StartBody, request: Request) -> dict:
        """Begin a session. The first reading of the words runs in the background: poll the session."""
        return builder(request).start(body.description, body.with_scripts, body.kind)

    @r.get("/builds/{sid}")
    def get(sid: str, request: Request) -> dict:
        return builder(request).get(sid)

    @r.post("/builds/{sid}/answers")
    def answer(sid: str, body: AnswersBody, request: Request) -> dict:
        return builder(request).answer(sid, body.answers)

    @r.post("/builds/{sid}/approve")
    def approve(sid: str, request: Request) -> dict:
        """The person approves the requirement shown in the session. Only then is anything built."""
        return builder(request).approve(sid)

    @r.post("/builds/{sid}/retry")
    def retry(sid: str, request: Request) -> dict:
        return builder(request).retry(sid)

    @r.get("/builds/{sid}/files/{path:path}")
    def read_file(sid: str, path: str, request: Request) -> dict:
        return builder(request).read_file(sid, path)

    @r.post("/builds/{sid}/save")
    def save(sid: str, body: SaveBody, request: Request) -> JSONResponse:
        """Keep the built skill in the library, through the same checked import as any other skill (422 if refused)."""
        b = builder(request)
        report = b.save(sid, accept_draft=body.accept_draft, note=body.note)
        return JSONResponse({**import_view(report), "session": b.get(sid)}, status_code=422 if report.refused else 200)

    @r.delete("/builds/{sid}")
    def discard(sid: str, request: Request) -> dict:
        builder(request).discard(sid)
        return {"discarded": True}

    return r
