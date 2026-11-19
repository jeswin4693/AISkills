"""How library and import objects are written as JSON. Shared by the library and builder routes."""

from __future__ import annotations

from dataclasses import asdict

from ..library.service import ImportReport
from ..library.store import Version


def version_view(v: Version) -> dict:
    return {**asdict(v), "tag": v.tag}


def checks_view(checks) -> list[dict]:
    return [asdict(c) for c in checks]


def import_view(r: ImportReport) -> dict:
    return {
        "refused": r.refused, "created": r.created, "name": r.name,
        "version": version_view(r.version) if r.version else None,
        "previous": r.previous.tag if r.previous else None,
        "checks": checks_view(r.checks), "changes": [asdict(c) for c in r.changes],
    }
