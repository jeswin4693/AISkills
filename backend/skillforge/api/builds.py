"""The skill builder over HTTP: a session you talk to across requests, with slow steps run as polled background jobs."""

from __future__ import annotations

from fastapi import APIRouter, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator

from ..ai.doctor import check_models
from ..builder import Builder, ModelOptions, env_provider, provider_status
from ..builder.keybox import KeyBox
from ..db import LOCAL_USER_ID
from ..providers import ProviderError
from .scope import user_id
from .views import import_view

MAX_DESCRIPTION = 10_000
MAX_ANSWER = 5_000
HOSTED_SEED_OFF = (
    "Starting from a repository is turned off in the hosted version: the evidence would be read from a folder on the server, "
    "not on your computer. Build without a repository, or use the local app."
)


class StartBody(BaseModel):
    description: str = Field(max_length=MAX_DESCRIPTION)
    with_scripts: bool = False
    kind: str = Field(default="skill", max_length=64)  # a registered kind; the builder refuses any other
    # Start from an idea about a repository: its folder, and the places in it the idea cited. The built skill or agent then carries
    # evidence of those places (docs/evidence.md). Off in the hosted version: the folder would be the server's.
    repo: str | None = Field(default=None, max_length=4096)
    focus: str | None = Field(default=None, max_length=400)
    evidence_nodes: list[str] = Field(default_factory=list, max_length=60)
    # Or, better: build from one idea of a stored suggestion run. The server then takes that run's folder and the idea's own cited
    # places, so a build cannot be about another repository than its idea was made for. Not together with repo / evidence_nodes.
    from_run: str | None = Field(default=None, max_length=64)
    idea: int | None = Field(default=None, ge=0, le=1000)

    @field_validator("evidence_nodes")
    @classmethod
    def short_nodes(cls, nodes: list[str]) -> list[str]:
        if any(len(n) > 400 for n in nodes):
            raise ValueError("a cited place is longer than 400 characters")
        return nodes


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


def model_options(hosted) -> ModelOptions:
    """What a hosted server lets its people do about models: keep a key of their own (sealed under the access token) and, if the host chooses, share the
    server's model with a daily cap. Local use has neither: there is only the owner."""
    if hosted is None:
        return ModelOptions()
    return ModelOptions(keybox=KeyBox(hosted.token), shared_calls_per_day=hosted.shared_calls_per_day)


def get_builder(app: FastAPI) -> Builder:
    """The builder, made on first use: a server that is only used for the library never opens the database."""
    with app.state.builder_lock:
        if app.state.builder is None:
            app.state.builder = Builder.default(app.state.library, app.state.libraries.for_user, model_options(app.state.hosted))
        return app.state.builder


def builds_router() -> APIRouter:
    r = APIRouter()

    def builder(request: Request) -> Builder:
        return get_builder(request.app)

    @r.get("/provider")
    def provider(request: Request) -> dict:
        """Is a model set up FOR THIS PERSON, and which. Never a key, and no call to the model. The owner (and everyone, in local use) sees the server's own
        model, as always; a signed-in person sees their own model, the shared one, or that none is set up for them."""
        who = user_id(request)
        if who != LOCAL_USER_ID:
            return builder(request).access.status_for(who)
        existing = request.app.state.builder
        return {**provider_status(existing.provider_factory if existing else env_provider), "source": "server", "allowance": None}

    @r.post("/provider/check")
    def provider_check(request: Request) -> dict:
        """One tiny call to each distinct model that is set up, so a person can see that each key and model really works.
        It uses a little quota, so it runs only when asked. Never returns a key. For a signed-in person it tries THEIR OWN model only."""
        who = user_id(request)
        if who != LOCAL_USER_ID:
            return builder(request).access.test(who)
        existing = request.app.state.builder
        factory = existing.provider_factory if existing else env_provider
        try:
            provider = factory()
        except ProviderError as exc:
            return {"configured": False, "detail": str(exc), "checks": []}
        return {"configured": True, "detail": "", "checks": check_models(provider)}

    @r.get("/builds")
    def list_builds(request: Request) -> list[dict]:
        return builder(request).list(user=user_id(request))

    @r.post("/builds", status_code=201)
    def start(body: StartBody, request: Request) -> dict:
        """Begin a session. The first reading of the words runs in the background: poll the session."""
        seed = None
        from_run = body.from_run is not None or body.idea is not None
        if body.repo or body.evidence_nodes or body.focus or from_run:
            if request.app.state.hosted is not None:
                raise HTTPException(403, HOSTED_SEED_OFF)
            if from_run:
                if body.from_run is None:
                    raise HTTPException(400, "Give from_run with idea: the suggestion run the idea belongs to.")
                if body.repo or body.evidence_nodes or body.focus:
                    raise HTTPException(400, "Give either from_run and idea, or repo and evidence_nodes, not both.")
                seed = builder(request).suggestions.seed_for(body.from_run, body.idea, user=user_id(request))
            else:
                seed = {"repo": body.repo, "focus": body.focus, "nodes": body.evidence_nodes}
        return builder(request).start(body.description, body.with_scripts, body.kind, seed, user=user_id(request))

    @r.get("/builds/{sid}")
    def get(sid: str, request: Request) -> dict:
        return builder(request).get(sid, user=user_id(request))

    @r.post("/builds/{sid}/answers")
    def answer(sid: str, body: AnswersBody, request: Request) -> dict:
        return builder(request).answer(sid, body.answers, user=user_id(request))

    @r.post("/builds/{sid}/approve")
    def approve(sid: str, request: Request) -> dict:
        """The person approves the requirement shown in the session. Only then is anything built."""
        return builder(request).approve(sid, user=user_id(request))

    @r.post("/builds/{sid}/retry")
    def retry(sid: str, request: Request) -> dict:
        return builder(request).retry(sid, user=user_id(request))

    @r.get("/builds/{sid}/files/{path:path}")
    def read_file(sid: str, path: str, request: Request) -> dict:
        return builder(request).read_file(sid, path, user=user_id(request))

    @r.post("/builds/{sid}/save")
    def save(sid: str, body: SaveBody, request: Request) -> JSONResponse:
        """Keep the built skill in the library, through the same checked import as any other skill (422 if refused)."""
        b, who = builder(request), user_id(request)
        report = b.save(sid, accept_draft=body.accept_draft, note=body.note, user=who)
        return JSONResponse({**import_view(report), "session": b.get(sid, user=who)}, status_code=422 if report.refused else 200)

    @r.delete("/builds/{sid}")
    def discard(sid: str, request: Request) -> dict:
        builder(request).discard(sid, user=user_id(request))
        return {"discarded": True}

    return r
