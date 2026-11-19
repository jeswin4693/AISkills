"""The local HTTP API. Every endpoint calls code that already exists and is already tested; nothing is reimplemented.

Rules (see docs/ui-and-database-plan.md): it answers only on localhost, an upload is read into memory under a hard cap
and never unpacked to disk, no endpoint returns an API key, and nothing runs a script except through the sandbox.
"""

from __future__ import annotations

import threading
from contextlib import asynccontextmanager
from dataclasses import asdict
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, FastAPI, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel

from .. import __version__
from ..builder import Builder, BuilderError, SessionNotFound, WrongState
from ..graph import languages
from ..library import (
    Conflict, Library, LibraryError, NotFound, check_source, compare_with_risk, import_source, install_skill, package_skill,
    read_zip_bytes, rescan, rollback,
)
from ..sandbox import probe_sandbox
from .builds import builds_router
from .security import LocalOnlyMiddleware, allowed_origins
from .views import checks_view as _checks
from .views import import_view as _import_report
from .views import rescan_view as _rescan
from .views import risk_view as _risk
from .views import version_view as _version

MAX_UPLOAD = 6_000_000  # bytes of zip; the library's own limits on what it holds when unpacked still apply


class RollbackBody(BaseModel):
    to: int


class InstallBody(BaseModel):
    version: int | None = None
    target: Literal["personal", "folder"]
    folder: str | None = None  # an absolute path, required when target is "folder"
    force: bool = False


async def read_upload(request: Request) -> bytes:
    """The request body, refused as soon as it is over the cap (the declared size is not trusted either)."""
    declared = request.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > MAX_UPLOAD:
        raise HTTPException(413, f"The upload is over {MAX_UPLOAD} bytes.")
    body = bytearray()
    async for chunk in request.stream():
        body += chunk
        if len(body) > MAX_UPLOAD:
            raise HTTPException(413, f"The upload is over {MAX_UPLOAD} bytes.")
    if not body:
        raise HTTPException(400, "Send the skill as a .zip in the request body.")
    return bytes(body)


def _library(request: Request) -> Library:
    return request.app.state.library


def _label(request: Request) -> str:
    """The upload's file name as the person's browser gave it: kept only as a short plain name."""
    name = Path(request.query_params.get("filename", "upload.zip").replace("\\", "/")).name
    return "".join(c for c in name if c.isprintable())[:100] or "upload.zip"


def create_app(library: Library | None = None, origins: list[str] | None = None, builder: Builder | None = None) -> FastAPI:
    """`builder` is made on first use when not given, so the library endpoints never need the database."""

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        yield
        if app.state.builder is not None:  # stop taking work; a job that is mid-run is marked failed on the next start
            app.state.builder.close()

    app = FastAPI(
        title="SkillForge AI", version=__version__, docs_url="/api/docs", openapi_url="/api/openapi.json", lifespan=lifespan,
    )
    app.state.library = library or (builder.library if builder else Library())
    app.state.builder = builder
    app.state.builder_lock = threading.Lock()
    trusted = allowed_origins(origins)
    app.add_middleware(
        CORSMiddleware, allow_origins=trusted, allow_methods=["GET", "POST", "DELETE"], allow_headers=["Content-Type"],
        expose_headers=["Content-Disposition"],
    )
    app.add_middleware(LocalOnlyMiddleware, origins=trusted)  # added last, so it runs first

    @app.exception_handler(SessionNotFound)
    async def session_not_found(_: Request, exc: SessionNotFound) -> JSONResponse:
        return JSONResponse({"detail": str(exc)}, status_code=404)

    @app.exception_handler(WrongState)
    async def wrong_state(_: Request, exc: WrongState) -> JSONResponse:
        return JSONResponse({"detail": str(exc)}, status_code=409)

    @app.exception_handler(BuilderError)  # BadRequest and anything else the person can fix
    async def builder_error(_: Request, exc: BuilderError) -> JSONResponse:
        return JSONResponse({"detail": str(exc)}, status_code=400)

    @app.exception_handler(NotFound)
    async def not_found(_: Request, exc: NotFound) -> JSONResponse:
        return JSONResponse({"detail": str(exc)}, status_code=404)

    @app.exception_handler(Conflict)
    async def conflict(_: Request, exc: Conflict) -> JSONResponse:
        return JSONResponse({"detail": str(exc)}, status_code=409)

    @app.exception_handler(LibraryError)
    async def library_error(_: Request, exc: LibraryError) -> JSONResponse:
        return JSONResponse({"detail": str(exc)}, status_code=400)

    api = APIRouter(prefix="/api")

    @api.get("/health")
    def health() -> dict:
        return {"status": "ok", "version": __version__}

    @api.get("/sandbox")
    def sandbox() -> dict:
        s = probe_sandbox()
        return {"available": s.available, "reason": s.reason}

    @api.get("/languages")
    def language_table() -> list[dict]:
        names = sorted(set(languages.EXTENSIONS.values()), key=lambda n: (["full", "standard", "basic"].index(languages.level_of(n)), n))
        return [
            {"name": n, "level": languages.level_of(n), "grammar": languages.grammar_status(n), "extensions": list(languages.info(n).extensions)}
            for n in names
        ]

    @api.post("/validate")
    async def validate(request: Request) -> dict:
        """Check an uploaded .zip. Nothing is stored and nothing is run."""
        src = read_zip_bytes(await read_upload(request), _label(request))
        checks = check_source(src)
        return {"checks": _checks(checks), "failed": sum(c.status == "failed" for c in checks), "files": len(src.files)}

    @api.get("/library")
    def list_skills(request: Request) -> list[dict]:
        lib, out = _library(request), []
        for name in lib.names():
            try:
                versions = lib.versions(name)
                out.append({"name": name, "versions": len(versions), "latest": _version(versions[-1]) if versions else None})
            except LibraryError as exc:
                out.append({"name": name, "versions": 0, "latest": None, "error": str(exc)})
        return out

    @api.post("/library/import")
    async def import_skill_upload(request: Request, note: str = "", test_scripts: bool = False) -> JSONResponse:
        """Check an uploaded .zip and keep it as the next version. 422 when a check fails; nothing is stored then.

        With test_scripts the skill's own cases run in the sandbox and this request waits for them."""
        src = read_zip_bytes(await read_upload(request), _label(request))
        report = await run_in_threadpool(import_source, src, _library(request), test_scripts=test_scripts, note=note[:200])
        return JSONResponse(_import_report(report), status_code=422 if report.refused else 200)

    @api.get("/library/{name}")
    def versions(name: str, request: Request) -> dict:
        found = _library(request).versions(name)
        if not found:
            raise NotFound(f"There is no skill named '{name}' in the library.")
        return {"name": name, "versions": [_version(v) for v in reversed(found)]}

    @api.get("/library/{name}/diff")
    def diff(name: str, request: Request, frm: int | None = None, to: int | None = None) -> dict:
        c = compare_with_risk(_library(request), name, frm, to)
        return {"name": name, "from": c.older.tag, "to": c.newer.tag, "changes": [asdict(x) for x in c.changes], "risk": _risk(c.risk)}

    @api.get("/rescan")
    def rescan_library(request: Request, name: str | None = None, version: int | None = None) -> dict:
        """Today's static checks on versions already stored, and which of them are now worse. Reads only; nothing is
        changed or run. Without `name` it covers every skill."""
        return _rescan(rescan(_library(request), name, version))

    @api.get("/library/{name}/versions/{number}/files/{path:path}")
    def read_file(name: str, number: int, path: str, request: Request) -> dict:
        """One stored file, after every file of that version was checked against its manifest."""
        v, files = _library(request).read(name, number)
        if path not in files:  # a lookup in what was read, never a path on the disk
            raise NotFound(f"{name} {v.tag} has no file '{path}'.")
        try:
            return {"path": path, "binary": False, "text": files[path].decode("utf-8")}
        except UnicodeDecodeError:
            return {"path": path, "binary": True, "text": ""}

    @api.post("/library/{name}/rollback")
    def roll_back(name: str, body: RollbackBody, request: Request) -> dict:
        version, created = rollback(_library(request), name, body.to)
        return {"created": created, "version": _version(version)}

    @api.get("/library/{name}/export")
    def export(name: str, request: Request, version: int | None = None, without_spec: bool = False) -> Response:
        pkg = package_skill(_library(request), name, version, without_spec=without_spec)
        return Response(
            pkg.data, media_type="application/zip",
            headers={"Content-Disposition": f'attachment; filename="{pkg.filename}"', "X-Skill-Has-Scripts": str(pkg.has_scripts).lower()},
        )

    @api.post("/library/{name}/install")
    def install(name: str, body: InstallBody, request: Request) -> dict:
        if body.target == "personal":
            folder = Path.home() / ".claude" / "skills"
        elif body.folder and Path(body.folder).is_absolute():
            folder = Path(body.folder)
        else:
            raise HTTPException(400, "For target 'folder', give folder as an absolute path.")
        r = install_skill(_library(request), name, body.version, folder, force=body.force)
        return {
            "path": str(r.path), "version": _version(r.version), "backup": str(r.backup) if r.backup else None,
            "has_scripts": r.has_scripts,
        }

    api.include_router(builds_router())
    app.include_router(api)
    return app
