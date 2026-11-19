"""How library and import objects are written as JSON. Shared by the library and builder routes."""

from __future__ import annotations

from dataclasses import asdict

from ..library.rescan import DAMAGED, FAILING, SAME, WORSE, VersionScan
from ..library.risk import LOOK, RISKIER, SAFER, RiskDiff
from ..library.service import ImportReport
from ..library.store import Version


def version_view(v: Version) -> dict:
    return {**asdict(v), "tag": v.tag}


def checks_view(checks) -> list[dict]:
    return [asdict(c) for c in checks]


def risk_view(r: RiskDiff) -> dict:
    return {
        **asdict(r), "level": r.level,
        "counts": {"riskier": r.count(RISKIER), "look": r.count(LOOK), "safer": r.count(SAFER)},
    }


def rescan_view(scans: list[VersionScan]) -> dict:
    counts = {s: sum(x.status == s for x in scans) for s in (SAME, WORSE, FAILING, DAMAGED)}
    return {"ok": counts[SAME] == len(scans), "counts": counts, "versions": [asdict(s) for s in scans]}


def import_view(r: ImportReport) -> dict:
    return {
        "refused": r.refused, "created": r.created, "name": r.name,
        "version": version_view(r.version) if r.version else None,
        "previous": r.previous.tag if r.previous else None,
        "checks": checks_view(r.checks), "changes": [asdict(c) for c in r.changes],
        "risk": risk_view(r.risk) if r.risk else None,
    }
