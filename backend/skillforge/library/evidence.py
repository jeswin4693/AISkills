"""Citing places in a repository, rechecking them, and refreshing what was recorded: the library's side of evidence.

Evidence is one file, `evidence.json`, inside the stored folder, so it is versioned, covered by the manifest hash, exported with the
skill and carried by a rollback. Writing it makes a new version through the same checks as an import (`source_kind` "evidence");
reading it never changes anything. Nothing here runs a script or calls a model: the graph is read and compared.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from ..evidence import (
    EVIDENCE_FILE, MAX_REFS, Evidence, EvidenceError, RecheckReport, Ref, collect, evidence_bytes, node_of, read_evidence,
    recheck, resolve_ref,
)
from ..evidence import model as _model
from ..graph.model import RepoGraph
from ..kinds import get_kind
from .package import LibraryError
from .service import _failed, _gate
from .store import Library, Version


def _recorded(files: dict[str, bytes], name: str, tag: str) -> Evidence | None:
    try:
        return read_evidence(files)
    except EvidenceError as exc:
        raise LibraryError(f"{name} {tag}: {exc}") from exc


def _assemble(repo: str, focus: str | None, refs: list[Ref], fallback: Evidence | None) -> Evidence:
    """Evidence for `refs`, whose own time and commit are kept; the file's are those of the latest place recorded."""
    stamped = [r for r in refs if r.taken_at]
    newest = max(stamped, key=lambda r: r.taken_at or "") if stamped else None
    when = (newest.taken_at if newest else None) or (fallback.taken_at if fallback else "")
    commit = newest.commit if newest else (fallback.commit if fallback else None)
    dirty = newest.dirty if newest else (fallback.dirty if fallback else False)
    return Evidence(repo=repo, commit=commit, dirty=dirty, focus=focus, taken_at=when, refs=refs)


def _store(library: Library, name: str, base: Version, files: dict[str, bytes], ev: Evidence, note: str, now: datetime | None) -> tuple[Version, bool]:
    data = evidence_bytes(ev)
    if len(data) > _model.MAX_FILE_BYTES:  # the reader would refuse it: say so here, with the way out
        raise LibraryError(
            f"The evidence would be too large ({len(data) // 1000} KB; the limit is {_model.MAX_FILE_BYTES // 1000} KB). "
            f"Cite fewer places, the ones the skill's advice depends on."
        )
    new_files = {**files, EVIDENCE_FILE: data}
    checks = _gate(new_files, name, kind=library.kind)
    failed = _failed(checks)
    if failed:
        raise LibraryError(f"{name} would no longer pass the checks ({failed[0].name}: {failed[0].detail}), so the evidence was not stored.")
    return library.add(
        name, new_files, source_kind="evidence", source_label=ev.repo, note=note, skill_version=base.skill_version, checks=checks, now=now,
    )


def _read_latest(library: Library, name: str, version: int | None = None) -> tuple[Version, dict[str, bytes], Evidence | None]:
    v, files = library.read(name, version)
    return v, files, _recorded(files, name, v.tag)


# ---- cite --------------------------------------------------------------------------------------------


@dataclass
class CiteReport:
    name: str
    version: Version
    created: bool  # False when the same places were already recorded
    added: list[str]  # places recorded now
    kept: list[str]  # already recorded: their facts were left as they were (`refresh` records today's)
    skipped: list[tuple[str, str]]  # (asked for, why it was not recorded)
    ambiguous: list[tuple[str, list[str]]]  # (text, the places it could mean): never picked for the person
    evidence: Evidence


def _text_mentions(library: Library, g: RepoGraph, files: dict[str, bytes]) -> tuple[list[str], list[tuple[str, list[str]]]]:
    """The places the skill's own text names, found by the Task Plan's mention finder (code-shaped text that matches the graph)."""
    from ..conductor.mentions import find_mentions  # only this path needs it

    text = files.get(get_kind(library.kind).definition_file, b"").decode("utf-8", errors="replace")
    mentions = find_mentions(g, text)
    # `svc.py::parse` names a function, not also the file: a file is cited only when the text names the file itself
    qualified = {m.text.partition("::")[0] for m in mentions if m.kind == "symbol" and "::" in m.text}
    ids: list[str] = []
    ambiguous: list[tuple[str, list[str]]] = []
    for m in mentions:
        if m.kind == "file" and m.text in qualified:
            continue
        if m.ambiguous:
            ambiguous.append((m.text, list(m.options)))
        elif m.target:
            ids.append(m.target)
    return ids, ambiguous


def cite(
    library: Library, name: str, g: RepoGraph, refs: list[str] | tuple[str, ...] = (), *, from_text: bool = False,
    focus: str | None = None, note: str = "", now: datetime | None = None,
) -> CiteReport:
    """Record places in the repository `g` as evidence of the stored skill `name` (a new version). A place already recorded keeps
    the facts it has; one that is not in the graph is reported, never recorded; an ambiguous name is listed, never picked."""
    v, files, existing = _read_latest(library, name)
    here = Path(g.root).name
    if existing is not None and existing.repo != here:
        raise LibraryError(
            f"The evidence of {name} was recorded from '{existing.repo}', and this folder is '{here}'. "
            f"Cite places in the same repository, or start again with a skill that has no evidence."
        )
    if existing is not None and (existing.focus or None) != (focus or None):
        raise LibraryError(
            f"The evidence of {name} was recorded with the focus {existing.focus or 'the whole repository'!r} and this graph was read with "
            f"{focus or 'the whole repository'!r}. Places recorded together must be read the same way: use the same --focus."
        )
    asked: list[str] = []
    skipped: list[tuple[str, str]] = []
    ambiguous: list[tuple[str, list[str]]] = []
    for text in refs:
        found = resolve_ref(g, text)
        if found.id:
            asked.append(found.id)
        elif found.options:
            ambiguous.append((text, found.options))
        else:
            skipped.append((text, "it matches nothing in the repository's graph"))
    if from_text:
        ids, unclear = _text_mentions(library, g, files)
        asked += ids
        ambiguous += unclear

    have = {r.id for r in existing.refs} if existing else set()
    nodes = list(dict.fromkeys(node_of(g, i) for i in asked))
    kept = [n for n in nodes if n in have]
    new_nodes = [n for n in nodes if n not in have]
    if len(have) + len(new_nodes) > MAX_REFS:
        raise LibraryError(
            f"A skill can cite at most {MAX_REFS} places, and this would make {len(have) + len(new_nodes)}. "
            f"A skill that needs more is too wide to check: cite the places its advice depends on."
        )
    got = collect(g, new_nodes, focus=focus, now=now)
    skipped += got.skipped
    if not got.evidence.refs and not kept:
        why = [f"{t}: could mean {', '.join(o)}" for t, o in ambiguous] + [f"{t}: {w}" for t, w in skipped]
        raise LibraryError(
            "There is nothing to record. " + ("; ".join(why) if why else "the skill's text names no file or function that exists in this repository.")
        )
    merged = _assemble(here, focus or None, (existing.refs if existing else []) + got.evidence.refs, existing)
    version, created = _store(library, name, v, files, merged, note or "cited places in " + here, now)
    return CiteReport(name, version, created, [r.id for r in got.evidence.refs], kept, skipped, ambiguous, merged)


# ---- recheck -----------------------------------------------------------------------------------------


def evidence_focus(library: Library, name: str, version: int | None = None) -> str | None:
    """The folder the stored evidence's graph was limited to, so a recheck reads the same part of the repository."""
    ev = _read_latest(library, name, version)[2]
    return ev.focus if ev else None


def recheck_version(library: Library, name: str, g: RepoGraph, version: int | None = None, **kw: object) -> RecheckReport:
    """Today's graph against the evidence stored with a version (default: the latest). Changes nothing. `focus=` is the folder `g`
    was limited to; the report says so when it is not the one the evidence was recorded with."""
    v, _, ev = _read_latest(library, name, version)
    if ev is None:
        raise LibraryError(f"{name} {v.tag} has no evidence. Add some with: library cite {name} --repo <path> --ref <file or function>")
    report = recheck(ev, g, **kw)
    report.skill, report.version = name, v.tag
    return report


# ---- refresh -----------------------------------------------------------------------------------------


@dataclass
class RefreshReport:
    name: str
    version: Version
    created: bool
    updated: list[str] = field(default_factory=list)  # recorded again because a fact differed
    unchanged: list[str] = field(default_factory=list)
    kept_missing: list[str] = field(default_factory=list)  # gone from the repository, still recorded (and still flagged)
    dropped: list[str] = field(default_factory=list)  # gone, and removed on request


def _facts(ref: Ref) -> dict:
    """What a refresh compares: the facts, not when or at which commit they were read, whether the tree was dirty then, or where
    in the file the place sat (a line that only moved is no change)."""
    return ref.model_dump(exclude={"taken_at", "commit", "dirty", "line", "end_line", "lines"})


def refresh(
    library: Library, name: str, g: RepoGraph, *, drop_missing: bool = False, focus: str | None = None, note: str = "",
    now: datetime | None = None,
) -> RefreshReport:
    """Record today's facts for the places that still exist. Meant for after a person has read the skill against the changed code:
    nothing is accepted by itself. A place that is gone stays recorded (and flagged) unless `drop_missing` is given."""
    v, files, existing = _read_latest(library, name)
    if existing is None:
        raise LibraryError(f"{name} {v.tag} has no evidence to refresh. Add some with: library cite {name} --repo <path> --ref <file or function>")
    new_focus = existing.focus if focus is None else (focus or None)  # "" clears it
    present = [r.id for r in existing.refs if r.id in g.files or (r.id in g.symbols and g.symbols[r.id].kind != "module")]
    today = {r.id: r for r in collect(g, present, focus=new_focus, now=now).evidence.refs}
    out = RefreshReport(name, v, False)
    refs: list[Ref] = []
    for old in existing.refs:
        new = today.get(old.id)
        if new is None:
            if drop_missing:
                out.dropped.append(old.id)
            else:
                out.kept_missing.append(old.id)
                refs.append(old)
        elif _facts(new) == _facts(old):
            out.unchanged.append(old.id)
            refs.append(old)
        else:
            out.updated.append(old.id)
            refs.append(new)
    if not refs:
        raise LibraryError(f"Dropping what is gone would remove every place {name} cites. Cite the new places first, or leave the evidence as it is.")
    merged = _assemble(existing.repo, new_focus, refs, existing)
    out.version, out.created = _store(library, name, v, files, merged, note or "refreshed the recorded facts", now)
    return out
