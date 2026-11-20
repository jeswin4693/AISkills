"""Import, export, install and roll back skills. Every path that lets a skill in or out is gated by the static checks.

Nothing here runs a script on this machine. An import can ask the sandbox to re-run the skill's own test cases
(`test_scripts=True`); without a Linux sandbox those cases are reported as "not run", never as passed.
"""

from __future__ import annotations

import os
import shutil
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from ..build.models import SkillDefinition
from ..build.scriptfiles import script_files
from ..build.scripts import SANDBOX_ROW, ScriptRunner, check_scripts, run_script_tests
from ..kinds import get_kind
from ..kinds.skill import skill_name_of  # noqa: F401  (re-exported: the library has always offered it)
from ..results import FAILED, NOT_RUN, WARNING, CheckResult
from ..validate import validate_files
from .package import Conflict, LibraryError, NotFound, SkillSource, read_source, replace_dir, write_tree, zip_bytes
from .risk import RiskDiff, risk_diff
from .store import FileChange, Library, Version, diff_files


def _definition(files: Mapping[str, bytes]) -> SkillDefinition | None:
    try:
        return SkillDefinition.model_validate_json(files["skill.sdm.json"].decode("utf-8"))
    except (KeyError, UnicodeDecodeError, ValueError):
        return None


def _same_text(a: bytes | None, b: str) -> bool:
    return a is not None and a.decode("utf-8", errors="replace").replace("\r\n", "\n") == b


def retest_scripts(files: Mapping[str, bytes], runner: ScriptRunner | None = None) -> list[CheckResult]:
    """Run the skill's own script cases in the sandbox. Only skills built here carry cases (in skill.sdm.json).

    The cases are run from the definition, so first the folder's scripts must be exactly what the definition says:
    otherwise the test would not be testing what ships."""
    def not_run(why: str) -> list[CheckResult]:
        return [CheckResult(SANDBOX_ROW, NOT_RUN, why)]

    sdm = _definition(files)
    if sdm is None:
        return not_run("this skill has no readable skill.sdm.json, so it carries no test cases that can be run")
    if not sdm.scripts:
        return not_run("skill.sdm.json lists no scripts, but the folder has some")
    expected = script_files(sdm.scripts, sdm.script_cases)
    shipped = {rel for rel in files if rel.startswith("scripts/") or rel.startswith("tests/fixtures/")}
    differs = sorted({rel for rel, text in expected.items() if not _same_text(files.get(rel), text)} | (shipped - set(expected)))
    if differs:
        return not_run("the folder's scripts or fixtures differ from skill.sdm.json (" + ", ".join(differs[:4]) + "), so a re-test would not test what ships")
    structural = [c for c in check_scripts(sdm.scripts, sdm.script_cases) if c.status in (FAILED, WARNING)]
    return structural + run_script_tests(sdm.scripts, sdm.script_cases, runner).results


def _gate(
    files: Mapping[str, bytes], folder: str | None, problems: list[tuple[str, str]] | None = None, kind: str = "skill",
) -> list[CheckResult]:
    """Every static check, with the definition check of `kind`. `folder` is the folder name the thing sat in, or None
    when there was none to compare."""
    return validate_files(files, folder=folder, problems=problems, kind=kind)


def _failed(checks: list[CheckResult]) -> list[CheckResult]:
    return [c for c in checks if c.status == FAILED]


def check_source(src: SkillSource, kind: str = "skill") -> list[CheckResult]:
    """Every static check on a source, storing nothing and running nothing."""
    return _gate(src.files, src.folder, src.problems, kind)


@dataclass
class Comparison:
    older: Version
    newer: Version
    changes: list[FileChange]
    risk: RiskDiff  # what got riskier in those changes (library/risk.py)


def compare_with_risk(library: Library, name: str, frm: int | None = None, to: int | None = None) -> Comparison:
    """Two versions of a skill: the changed files, and what got riskier. Default: the latest against the one before it."""
    versions = library.versions(name)
    if not versions:
        raise NotFound(f"There is no skill named '{name}' in the library.")
    newer = library.pick(name, to) if to is not None else versions[-1]
    if frm is not None:
        older = library.pick(name, frm)
    else:
        before = [v for v in versions if v.version < newer.version]
        if not before:
            raise LibraryError(f"{name} {newer.tag} is the first version, so there is nothing before it. Give the older version.")
        older = before[-1]
    _, old_files = library.read(name, older.version)
    _, new_files = library.read(name, newer.version)
    return Comparison(older, newer, diff_files(old_files, new_files), risk_diff(old_files, new_files, older.tag, newer.tag, library.kind))


def compare(library: Library, name: str, frm: int | None = None, to: int | None = None) -> tuple[Version, Version, list[FileChange]]:
    """(older, newer, changes). Default: the latest version against the one before it."""
    c = compare_with_risk(library, name, frm, to)
    return c.older, c.newer, c.changes


# ---- import ------------------------------------------------------------------------------------------


@dataclass
class ImportReport:
    checks: list[CheckResult]
    name: str | None = None
    version: Version | None = None  # None when the skill was refused
    created: bool = False  # False: refused, or identical to the latest version
    previous: Version | None = None
    changes: list[FileChange] = field(default_factory=list)  # against the previous version
    risk: RiskDiff | None = None  # what got riskier against the previous version; None for a first version or no change

    @property
    def refused(self) -> bool:
        return self.version is None


def import_skill(
    source: Path, library: Library, *, test_scripts: bool = False, runner: ScriptRunner | None = None,
    note: str = "", now: datetime | None = None,
) -> ImportReport:
    """Read a folder or zip, run every static check, and keep it as the next version only if none failed.

    A refused skill leaves the library untouched."""
    return import_source(read_source(source), library, test_scripts=test_scripts, runner=runner, note=note, now=now)


def import_source(
    src: SkillSource, library: Library, *, test_scripts: bool = False, runner: ScriptRunner | None = None,
    note: str = "", now: datetime | None = None,
) -> ImportReport:
    """The same as import_skill, for a source that is already in memory (an upload)."""
    checks = check_source(src, library.kind)
    name = get_kind(library.kind).name_of(src.files)
    has_scripts = any(rel.startswith("scripts/") for rel in src.files)
    if has_scripts:
        if test_scripts and not _failed(checks):
            checks += retest_scripts(src.files, runner)
        else:
            why = "not asked for (add --test-scripts)" if not test_scripts else "the static checks failed first"
            checks.append(CheckResult(SANDBOX_ROW, NOT_RUN, why))
    if name is None or _failed(checks):
        return ImportReport(checks, name)
    previous = (library.versions(name) or [None])[-1]
    sdm = _definition(src.files)
    version, created = library.add(
        name, src.files, source_kind=src.kind, source_label=src.label, note=note,
        skill_version=sdm.version if sdm else "", checks=checks, now=now,
    )
    changes: list[FileChange] = []
    risk: RiskDiff | None = None
    if created and previous is not None:
        _, old_files = library.read(name, previous.version)
        changes = diff_files(old_files, src.files)
        risk = risk_diff(old_files, src.files, previous.tag, version.tag, library.kind)
    return ImportReport(checks, name, version, created, previous, changes, risk)


# ---- rollback ----------------------------------------------------------------------------------------


def rollback(library: Library, name: str, to: int, *, now: datetime | None = None) -> tuple[Version, bool]:
    """A new version with the content of an old one. History is never rewritten or deleted."""
    old, files = library.read(name, to)
    checks = _gate(files, name, kind=library.kind)
    if _failed(checks):
        raise LibraryError(f"{name} {old.tag} no longer passes the checks ({_failed(checks)[0].name}), so it was not restored.")
    return library.add(
        name, files, source_kind="rollback", source_label=old.tag, note=f"restored the content of {old.tag}",
        skill_version=old.skill_version, checks=checks, now=now,
    )


# ---- export ------------------------------------------------------------------------------------------


@dataclass
class Package:
    """One version as a zip, in memory."""

    version: Version
    data: bytes
    files: int
    dropped: list[str]
    has_scripts: bool

    @property
    def filename(self) -> str:
        return f"{self.version.name}-{self.version.tag}.zip"


def package_skill(library: Library, name: str, version: int | None, *, without_spec: bool = False) -> Package:
    """One version as a zip with a single `<name>/` folder, ready to share. It is checked again first."""
    v, files = library.read(name, version)
    failed = _failed(_gate(files, name, kind=library.kind))
    if failed:
        raise LibraryError(f"{name} {v.tag} no longer passes the checks ({failed[0].name}), so it was not exported.")
    dropped: list[str] = []
    if without_spec and "spec.json" in files:  # spec.json holds the requester's own words
        files = {rel: d for rel, d in files.items() if rel != "spec.json"}
        dropped.append("spec.json")
    return Package(v, zip_bytes(name, files), len(files), dropped, any(rel.startswith("scripts/") for rel in files))


@dataclass
class ExportReport:
    path: Path
    version: Version
    files: int
    dropped: list[str]
    has_scripts: bool


def export_skill(
    library: Library, name: str, version: int | None, out: Path | None, *, without_spec: bool = False, force: bool = False,
) -> ExportReport:
    """Write one version as a zip file. Never overwrites a file unless force is given."""
    pkg = package_skill(library, name, version, without_spec=without_spec)
    target = Path(out) if out else Path.cwd() / pkg.filename
    if target.exists() and not force:
        raise Conflict(f"{target} already exists. Use --force to replace it, or choose another --out.")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(pkg.data)
    return ExportReport(target, pkg.version, pkg.files, pkg.dropped, pkg.has_scripts)


# ---- install -----------------------------------------------------------------------------------------


@dataclass
class InstallReport:
    path: Path
    version: Version
    backup: Path | None
    has_scripts: bool


def _install_file(
    library: Library, v: Version, data: bytes, name: str, suffix: str, folder: Path, *, force: bool, now: datetime | None,
) -> InstallReport:
    """One file of the version, written as `<folder>/<name><suffix>`: how a subagent is installed. An existing file is never
    replaced unless force is given, and then it is copied to the library's backups first."""
    target = folder / f"{name}{suffix}"
    backup: Path | None = None
    if target.is_symlink():
        raise LibraryError(f"{target} is a link. It was left alone.")
    if target.exists():
        if not force:
            raise Conflict(f"{target} already exists. Use --force to replace it (the old copy is saved to a backup first).")
        stamp = (now or datetime.now(timezone.utc)).strftime("%Y%m%d-%H%M%S")
        backup = library.backups / f"{name}-{stamp}{suffix}"
        backup.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(target, backup)
    folder.mkdir(parents=True, exist_ok=True)
    handle, staging = tempfile.mkstemp(prefix=f".{name}-", suffix=".tmp", dir=folder)  # written aside, then moved into place
    try:
        with os.fdopen(handle, "wb") as out:
            out.write(data)
        os.replace(staging, target)
    except BaseException:
        Path(staging).unlink(missing_ok=True)
        raise
    return InstallReport(target, v, backup, False)


def install_skill(
    library: Library, name: str, version: int | None, skills_dir: Path, *, force: bool = False, now: datetime | None = None,
) -> InstallReport:
    """Copy one version to `<skills_dir>/<name>`, where an agent such as Claude Code reads skills. Checked again first.

    An existing folder is never touched unless force is given, and then it is copied to the library's backups first."""
    v, files = library.read(name, version)
    failed = _failed(_gate(files, name, kind=library.kind))
    if failed:
        raise LibraryError(f"{name} {v.tag} no longer passes the checks ({failed[0].name}), so it was not installed.")
    skills_dir = Path(skills_dir)
    kind = get_kind(library.kind)
    if kind.install_file:  # an agent is installed as one file, not as a folder
        return _install_file(library, v, files[kind.install_file], name, Path(kind.install_file).suffix, skills_dir, force=force, now=now)
    target = skills_dir / name
    backup: Path | None = None
    if target.is_symlink():
        raise LibraryError(f"{target} is a link. It was left alone.")
    if target.exists():
        if not force:
            raise Conflict(f"{target} already exists. Use --force to replace it (the old copy is saved to a backup first).")
        stamp = (now or datetime.now(timezone.utc)).strftime("%Y%m%d-%H%M%S")
        backup = library.backups / f"{name}-{stamp}"
        shutil.copytree(target, backup, symlinks=True)
    skills_dir.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{name}-", dir=skills_dir))  # built aside, then moved into place
    try:
        write_tree(staging, files)
        if target.exists():
            shutil.rmtree(target)
        replace_dir(staging, target)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return InstallReport(target, v, backup, any(rel.startswith("scripts/") for rel in files))
