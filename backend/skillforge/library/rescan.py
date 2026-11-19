"""Check every stored version again with today's checks.

A skill is checked when it is imported. Checks improve, and a skill that passed last month may not pass this month's
rules. A scan that happens only once is a scan an attacker can wait out, so `rescan` runs the current static checks on
versions already in the library and says which ones are now worse than they were. It changes nothing: stored versions
are never edited (history only grows), and nothing is run.

For each version one of:

    same      no check is worse than it was at import
    worse     a check that passed at import now warns, or a check that did not exist then warns
    failing   a check fails today: this version would be refused if it were imported now, and export and install refuse it
    damaged   the stored files no longer match their manifest (edited behind the library's back), so nothing was checked
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from ..results import FAILED, CheckResult
from ..validate import validate_files
from .package import LibraryError, NotFound
from .store import Library, Version

SAME, WORSE, FAILING, DAMAGED = "same", "worse", "failing", "damaged"
_RANK = {"passed": 0, "not run": 0, "warning": 1, "failed": 2}
_FOUND_NOW = "found now"


@dataclass
class Finding:
    status: str  # warning or failed
    name: str
    detail: str
    was: str  # what this check said at import: passed, warning, failed, or "found now" for a check that did not exist then


@dataclass
class VersionScan:
    name: str
    tag: str  # "" when the skill's manifests could not be read at all
    status: str  # same, worse, failing, damaged
    findings: list[Finding] = field(default_factory=list)
    message: str = ""  # for damaged: why


def checks_worse(stored: Sequence[dict[str, str]], today: Sequence[CheckResult]) -> list[Finding]:
    """The checks of today that are worse than the same check was at import. A check that did not exist then counts as
    having passed, so a rule added later shows up here. A check that did not run is never worse."""
    was = {c["name"]: c["status"] for c in stored}
    out: list[Finding] = []
    for c in today:
        before = was.get(c.name)
        if _RANK[c.status] > _RANK.get(before or "passed", 0):
            out.append(Finding(c.status, c.name, c.detail, before or _FOUND_NOW))
    return out


def scan_version(library: Library, name: str, v: Version) -> VersionScan:
    try:
        _, files = library.read(name, v.version)  # also proves the files still match the manifest
    except LibraryError as exc:
        return VersionScan(name, v.tag, DAMAGED, message=str(exc))
    findings = checks_worse(v.checks, validate_files(files))
    findings.sort(key=lambda f: f.status != FAILED)
    status = FAILING if any(f.status == FAILED for f in findings) else WORSE if findings else SAME
    return VersionScan(name, v.tag, status, findings)


def rescan(library: Library, name: str | None = None, version: int | None = None) -> list[VersionScan]:
    """Today's checks on every stored version (of one skill, or of all). Newest version of each skill first."""
    if version is not None and name is None:
        raise LibraryError("Give the skill name when you give a version.")
    names = [name] if name else library.names()
    out: list[VersionScan] = []
    for n in names:
        try:
            versions = library.versions(n)
        except LibraryError as exc:  # a manifest that cannot be read: report it, and go on with the other skills
            out.append(VersionScan(n, "", DAMAGED, message=str(exc)))
            continue
        if not versions:
            if name:
                raise NotFound(f"There is no skill named '{n}' in the library. See: library list")
            continue
        if version is not None:
            versions = [library.pick(n, version)]
        out += [scan_version(library, n, v) for v in reversed(versions)]
    return out
