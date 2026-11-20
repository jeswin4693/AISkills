"""The plugin composer over HTTP: preview what a plugin would hold and can do, and keep it in the plugin library.

Nothing here calls a model. A preview keeps nothing. Keeping goes through the same checked import as every other library entry,
so a plugin that fails its checks is refused (422) and a repeat of the same plugin makes no second version.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Literal

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from ..library import SkillSource, import_source
from ..library.plugin import ComponentRef, PluginPlan, compose_for_keeping
from ..validate.plugin import MANIFEST
from .views import checks_view, import_view


class ComponentBody(BaseModel):
    kind: Literal["skill", "agent"]
    name: str = Field(max_length=64)
    version: int | None = Field(default=None, ge=1)  # none: the latest


class PluginBody(BaseModel):
    name: str = Field(max_length=64)
    description: str = Field(max_length=1000)
    author: str = Field(default="", max_length=100)
    components: list[ComponentBody] = Field(min_length=1, max_length=50)


def _plan(request: Request, body: PluginBody) -> PluginPlan:
    return compose_for_keeping(
        request.app.state.library, [ComponentRef(c.kind, c.name, c.version) for c in body.components],
        name=body.name, description=body.description, author=body.author,
    )


def _view(plan: PluginPlan) -> dict:
    return {
        "name": plan.name, "version": plan.version, "components": plan.components, "manifest": plan.files[MANIFEST].decode("utf-8"),
        "files": [{"path": path, "bytes": len(data)} for path, data in plan.files.items()],
        "capabilities": asdict(plan.capabilities), "checks": checks_view(plan.checks), "failed": plan.failed,
    }


def plugins_router() -> APIRouter:
    r = APIRouter()

    @r.post("/plugins/preview")
    def preview(body: PluginBody, request: Request) -> dict:
        """The files, what the plugin can do on the machine, and every check. Keeps nothing."""
        return _view(_plan(request, body))

    @r.post("/plugins")
    def keep(body: PluginBody, request: Request) -> JSONResponse:
        """Keep it as the next version in the plugin library (422 when a check fails; nothing is kept then)."""
        plan = _plan(request, body)
        if plan.failed:
            return JSONResponse(  # the same shape as any other refusal, so one page reads them all
                {
                    "refused": True, "created": False, "name": plan.name, "version": None, "previous": None,
                    "checks": checks_view(plan.checks), "changes": [], "risk": None,
                    "capabilities": asdict(plan.capabilities), "components": plan.components,
                },
                status_code=422,
            )
        library = request.app.state.library.for_kind("plugin")
        source = SkillSource(plan.files, [], "composed", plan.name, plan.name)
        report = import_source(source, library, note=f"composed from {len(plan.components)} component(s)")
        return JSONResponse(
            {**import_view(report), "capabilities": asdict(plan.capabilities), "components": plan.components},
            status_code=422 if report.refused else 200,
        )

    return r
