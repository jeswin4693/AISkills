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

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel

from .. import __version__
from ..builder import Builder, BuilderError, SessionNotFound, WrongState
from ..graph import languages
from ..kinds import UnknownKind, all_kinds, get_kind
from ..library import (
    Conflict, Library, LibraryError, NotFound, check_source, compare_with_risk, import_source, install_skill, package_skill,
    read_zip_bytes, rescan, rollback,
)
from ..sandbox import probe_sandbox
from .builds import builds_router
from .hosted import AuthMiddleware, Hosted, LoginGuard, auth_router
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


def kind_of(kind: str = "skill") -> str:
    """The kind named in `?kind=` (skills when it is left out). One that is not registered is a 400 naming the kinds there are."""
    try:
        get_kind(kind)
    except UnknownKind as exc:
        raise HTTPException(400, str(exc)) from exc
    return kind


def library_for(request: Request, kind: str = Depends(kind_of)) -> Library:
    """The library of that kind, next to the skill library."""
    return request.app.state.library.for_kind(kind)


def _label(request: Request) -> str:
    """The upload's file name as the person's browser gave it: kept only as a short plain name."""
    name = Path(request.query_params.get("filename", "upload.zip").replace("\\", "/")).name
    return "".join(c for c in name if c.isprintable())[:100] or "upload.zip"


def create_app(
    library: Library | None = None, origins: list[str] | None = None, builder: Builder | None = None,
    hosted: Hosted | None = None,
) -> FastAPI:
    """`builder` is made on first use when not given, so the library endpoints never need the database.

    `hosted` turns on the hosted version (docs/hosting.md): a sign-in in front of the API, no install into server folders, no
    interactive docs. Without it everything is as it always was: local only, no sign-in."""

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        yield
        if app.state.builder is not None:  # stop taking work; a job that is mid-run is marked failed on the next start
            app.state.builder.close()

    app = FastAPI(
        title="SkillForge AI", version=__version__, lifespan=lifespan,
        docs_url=None if hosted else "/api/docs", openapi_url=None if hosted else "/api/openapi.json",
    )
    app.state.hosted = hosted
    app.state.library = library or (builder.library if builder else Library())
    app.state.builder = builder
    app.state.builder_lock = threading.Lock()
    trusted = allowed_origins(origins)
    app.add_middleware(
        CORSMiddleware, allow_origins=trusted, allow_methods=["GET", "POST", "DELETE"], allow_headers=["Content-Type"],
        expose_headers=["Content-Disposition"],
    )
    if hosted is not None:
        app.add_middleware(AuthMiddleware, hosted=hosted)
    app.add_middleware(LocalOnlyMiddleware, origins=trusted, hosts=hosted.allowed_hosts if hosted else None)  # added last, so it runs first

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
        return {"status": "ok", "version": __version__, "mode": "hosted" if hosted else "local"}

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

    @api.get("/kinds")
    def kinds() -> list[dict]:
        """What this app builds: each kind's checklist (labels and questions) and where it can be installed."""
        return [
            {"key": k.key, "label": k.label, "definition_file": k.definition_file, "install_targets": list(k.install_targets),
             "personal_label": k.personal_label, "installs_as_file": bool(k.install_file), "conversational": k.conversational,
             "slots": [asdict(s) for s in k.slots]}
            for k in all_kinds()
        ]

    @api.post("/validate")
    async def validate(request: Request, kind: str = Depends(kind_of)) -> dict:
        """Check an uploaded .zip. Nothing is stored and nothing is run."""
        src = read_zip_bytes(await read_upload(request), _label(request))
        checks = check_source(src, kind)
        return {"checks": _checks(checks), "failed": sum(c.status == "failed" for c in checks), "files": len(src.files)}

    @api.get("/library")
    def list_skills(lib: Library = Depends(library_for)) -> list[dict]:
        out = []
        for name in lib.names():
            try:
                versions = lib.versions(name)
                out.append({"name": name, "versions": len(versions), "latest": _version(versions[-1]) if versions else None})
            except LibraryError as exc:
                out.append({"name": name, "versions": 0, "latest": None, "error": str(exc)})
        return out

    @api.post("/library/import")
    async def import_skill_upload(
        request: Request, note: str = "", test_scripts: bool = False, lib: Library = Depends(library_for),
    ) -> JSONResponse:
        """Check an uploaded .zip and keep it as the next version. 422 when a check fails; nothing is stored then.

        With test_scripts the skill's own cases run in the sandbox and this request waits for them."""
        src = read_zip_bytes(await read_upload(request), _label(request))
        report = await run_in_threadpool(import_source, src, lib, test_scripts=test_scripts, note=note[:200])
        return JSONResponse(_import_report(report), status_code=422 if report.refused else 200)

    @api.get("/library/{name}")
    def versions(name: str, lib: Library = Depends(library_for)) -> dict:
        found = lib.versions(name)
        if not found:
            raise NotFound(f"There is no skill named '{name}' in the library.")
        return {"name": name, "versions": [_version(v) for v in reversed(found)]}

    @api.get("/library/{name}/diff")
    def diff(name: str, frm: int | None = None, to: int | None = None, lib: Library = Depends(library_for)) -> dict:
        c = compare_with_risk(lib, name, frm, to)
        return {"name": name, "from": c.older.tag, "to": c.newer.tag, "changes": [asdict(x) for x in c.changes], "risk": _risk(c.risk)}

    @api.get("/rescan")
    def rescan_library(name: str | None = None, version: int | None = None, lib: Library = Depends(library_for)) -> dict:
        """Today's static checks on versions already stored, and which of them are now worse. Reads only; nothing is
        changed or run. Without `name` it covers every skill."""
        return _rescan(rescan(lib, name, version))

    @api.get("/library/{name}/versions/{number}/files/{path:path}")
    def read_file(name: str, number: int, path: str, lib: Library = Depends(library_for)) -> dict:
        """One stored file, after every file of that version was checked against its manifest."""
        v, files = lib.read(name, number)
        if path not in files:  # a lookup in what was read, never a path on the disk
            raise NotFound(f"{name} {v.tag} has no file '{path}'.")
        try:
            return {"path": path, "binary": False, "text": files[path].decode("utf-8")}
        except UnicodeDecodeError:
            return {"path": path, "binary": True, "text": ""}

    @api.post("/library/{name}/rollback")
    def roll_back(name: str, body: RollbackBody, lib: Library = Depends(library_for)) -> dict:
        version, created = rollback(lib, name, body.to)
        return {"created": created, "version": _version(version)}

    @api.get("/library/{name}/export")
    def export(name: str, version: int | None = None, without_spec: bool = False, lib: Library = Depends(library_for)) -> Response:
        pkg = package_skill(lib, name, version, without_spec=without_spec)
        return Response(
            pkg.data, media_type="application/zip",
            headers={"Content-Disposition": f'attachment; filename="{pkg.filename}"', "X-Skill-Has-Scripts": str(pkg.has_scripts).lower()},
        )

    @api.post("/library/{name}/install")
    def install(name: str, body: InstallBody, lib: Library = Depends(library_for)) -> dict:
        if hosted is not None:  # this would write into a folder on the server, which is not where anyone's agent reads skills
            raise HTTPException(403, "Installing into a folder on the server is turned off in the hosted version. Use Export to download the zip, and install it on your own computer.")
        kind = get_kind(lib.kind)
        if body.target not in kind.install_targets:
            raise HTTPException(400, f"{kind.label}s can be installed to: {', '.join(kind.install_targets)}.")
        if body.target == "personal":
            folder = get_kind(lib.kind).personal_dir()
        elif body.folder and Path(body.folder).is_absolute():
            folder = Path(body.folder)
        else:
            raise HTTPException(400, "For target 'folder', give folder as an absolute path.")
        r = install_skill(lib, name, body.version, folder, force=body.force)
        return {
            "path": str(r.path), "version": _version(r.version), "backup": str(r.backup) if r.backup else None,
            "has_scripts": r.has_scripts,
        }

    api.include_router(auth_router(hosted, LoginGuard()))
    api.include_router(builds_router())
    app.include_router(api)
    return app
