"""The plugin composer over HTTP: preview what a plugin would hold and can do, and keep it in the plugin library.

Nothing here calls a model. A preview keeps nothing. Keeping goes through the same checked import as every other library entry,
so a plugin that fails its checks is refused (422) and a repeat of the same plugin makes no second version.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Annotated, Literal

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from ..hookcatalog.catalogue import CATALOGUE
from ..library import SkillSource, import_source
from ..library.plugin import ComponentRef, PluginPlan, compose_for_keeping
from ..validate.plugin import MANIFEST
from .views import checks_view, import_view


OptionValues = Annotated[list[Annotated[str, Field(max_length=100)]], Field(max_length=20)]  # the catalogue holds the real limits; these only bound a request


class ComponentBody(BaseModel):
    kind: Literal["skill", "agent", "mcp", "hook"]  # a hook is named by its id in the catalogue
    name: str = Field(max_length=64)
    version: int | None = Field(default=None, ge=1)  # none: the latest. A hook has no version
    options: dict[Annotated[str, Field(max_length=40)], OptionValues] = Field(default_factory=dict, max_length=5)  # only a hook has options


class PluginBody(BaseModel):
    name: str = Field(max_length=64)
    description: str = Field(max_length=1000)
    author: str = Field(default="", max_length=100)
    components: list[ComponentBody] = Field(min_length=1, max_length=50)


def _plan(request: Request, body: PluginBody) -> PluginPlan:
    return compose_for_keeping(
        request.app.state.library, [ComponentRef(c.kind, c.name, c.version, c.options or None) for c in body.components],
        name=body.name, description=body.description, author=body.author,
    )


def _view(plan: PluginPlan) -> dict:
    return {
        "name": plan.name, "version": plan.version, "components": plan.components, "manifest": plan.files[MANIFEST].decode("utf-8"),
        "files": [{"path": path, "bytes": len(data)} for path, data in plan.files.items()],
        "capabilities": asdict(plan.capabilities), "checks": checks_view(plan.checks), "failed": plan.failed,
    }


def _hook_view(entry) -> dict:
    """A catalogue hook as the page needs it. How an option reaches the script (its flag) stays inside; the pattern is shown so the page can
    hint early, and the server remains the one that decides."""
    return {
        "id": entry.id, "title": entry.title, "summary": entry.summary, "event": entry.event, "matcher": entry.matcher, "effect": entry.effect,
        "sees": entry.sees, "timeout": entry.timeout, "powers": sorted(entry.powers), "revision": entry.revision,
        "options": [
            {"key": o.key, "label": o.label, "help": o.help, "max_items": o.max_items, "max_length": o.max_length, "pattern": o.pattern.pattern}
            for o in entry.options
        ],
    }


def plugins_router() -> APIRouter:
    r = APIRouter()

    @r.get("/hooks")
    def hooks() -> list[dict]:
        """The hooks a plugin may carry: the only ones. Each is a fixed script from SkillForge with typed options."""
        return [_hook_view(entry) for entry in CATALOGUE.values()]

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
