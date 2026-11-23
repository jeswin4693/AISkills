"""Persist parsed file records, so a repository is only re-parsed where files changed (the graph's memory)."""

from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
import time
from dataclasses import asdict
from pathlib import Path

from .model import SCHEMA_VERSION, CallSite, FileRecord, ImportRef, Symbol


def data_dir() -> Path:
    """Where caches live: SKILLFORGE_DATA_DIR, else the per-user data folder. Never inside any repository."""
    env = os.environ.get("SKILLFORGE_DATA_DIR")
    if env:
        return Path(env)
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
    return base / "skillforge"


def cache_path(root: Path) -> Path:
    digest = hashlib.sha1(str(root).lower().encode()).hexdigest()[:10]
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in root.name)[:40] or "repo"
    return data_dir() / "graphs" / f"{safe}-{digest}.json"


def _symbol(d: dict) -> Symbol:
    d = dict(d)
    d["calls"] = [CallSite(**c) for c in d.get("calls", [])]
    return Symbol(**d)


def _record(d: dict) -> FileRecord:
    d = dict(d)
    d["symbols"] = [_symbol(s) for s in d.get("symbols", [])]
    d["imports"] = [
        ImportRef(i["module"], [tuple(n) for n in i["names"]], i["line"], i["level"]) for i in d.get("imports", [])
    ]
    return FileRecord(**d)


def load_records(path: Path) -> dict[str, FileRecord]:
    """Cached records, or {} when there is no cache, it is unreadable, or it was written by another schema."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("schema") != SCHEMA_VERSION:
            return {}
        return {p: _record(r) for p, r in data["files"].items()}
    except (OSError, ValueError, KeyError, TypeError):
        return {}


def save_records(path: Path, records: dict[str, FileRecord]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"schema": SCHEMA_VERSION, "files": {p: asdict(r) for p, r in records.items()}}
    # Each write has its own temporary file: two requests reading the same repository at once (the web page can do that) must not
    # share one. The cache only makes the next read faster, so a replace that cannot be done is given up on, not raised.
    fd, name = tempfile.mkstemp(dir=path.parent, prefix=path.stem + ".", suffix=".tmp")
    tmp = Path(name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as out:
            out.write(json.dumps(payload, separators=(",", ":")))
        for attempt in range(6):
            try:
                tmp.replace(path)
                return
            except PermissionError:  # Windows: another reader or writer has the file open for a moment
                time.sleep(0.02 * (attempt + 1))
    finally:
        tmp.unlink(missing_ok=True)
