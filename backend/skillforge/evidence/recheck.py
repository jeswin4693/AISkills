"""Compare the facts recorded for a skill with today's graph, and say what changed. No model, nothing is run.

One verdict per cited place, worst first:

    missing  the cited thing is gone (a candidate may be listed, never chosen)
    moved    it is gone, and exactly one place looks like it now: a candidate, never applied for you
    changed  it is there, and a recorded fact differs: its structure, kind, export or decorators, a class's bases or methods,
             its resolved callers or callees, a file's symbols or importers
    edited   the facts are the same but the text differs (a name, a value, a comment, the body of a function in a cited file)
    holds    every recorded fact is the same, and so is the text

A line number that only moved is never a change. A language whose calls the graph does not resolve says "not measured" instead
of "no callers". A list too long to keep by name is compared by a digest of the whole. This checks that cited facts still hold,
not that the skill's advice is right. Every name shown comes out escaped (`safe`): a repository's file names are not trusted.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path, PurePosixPath

from ..graph.model import RepoGraph, Symbol
from .model import MAX_LIST, Evidence, Ref, safe
from .snapshot import (
    MIN_SHAPE_SIZE, callees_of, callers_of, class_members, digest, file_symbols, file_text_hash, git_dirty, git_head,
    importers_of, imports_of, is_measured, text_hash,
)

STATUSES = ("missing", "moved", "changed", "edited", "holds")  # worst first
LIMITS = (
    "This checks that the places the skill cites are still there and still look the same to the graph: that they exist, their "
    "structure, decorators, resolved callers and callees, a class's bases and methods, a file's symbols and importers, and that their "
    "text is the same. It checks that cited facts still hold, not that the skill's advice is right, and a value written in the "
    "skill's prose is only noticed as an edit to the code."
)
SHOW = 3  # names listed in a sentence
_UNSET = object()


@dataclass
class Finding:
    ref: str
    kind: str  # "file" | "symbol"
    status: str
    details: list[str] = field(default_factory=list)
    candidates: list[str] = field(default_factory=list)  # where a missing thing may be now: a guess, labelled as one
    not_measured: list[str] = field(default_factory=list)  # facts that were not compared, and why
    recorded: str = ""  # when the compared facts were recorded, such as "2026-11-23, commit 3fa9c1"


@dataclass
class RecheckReport:
    repo: str
    taken_at: str
    recorded_commit: str | None
    current_commit: str | None
    findings: list[Finding]
    notes: list[str] = field(default_factory=list)
    limits: str = LIMITS
    skill: str = ""  # set by the library when the evidence came from a stored version
    version: str = ""
    recorded_dirty: bool = False  # the working tree had uncommitted changes when the evidence was recorded
    current_dirty: bool = False  # ... and has them now

    @property
    def counts(self) -> dict[str, int]:
        return {s: n for s in STATUSES if (n := sum(f.status == s for f in self.findings))}

    @property
    def ok(self) -> bool:
        """True when nothing the skill cites is gone, moved or changed (an edit that kept the facts is not a failure)."""
        return all(f.status in ("holds", "edited") for f in self.findings)

    def to_dict(self) -> dict:
        """The report as plain data, for `--json` and the API."""
        return {
            "skill": self.skill, "version": self.version, "repo": self.repo, "taken_at": self.taken_at,
            "recorded_commit": self.recorded_commit, "current_commit": self.current_commit, "ok": self.ok,
            "recorded_dirty": self.recorded_dirty, "current_dirty": self.current_dirty,
            "counts": self.counts, "findings": [asdict(f) for f in self.findings], "notes": self.notes, "limits": self.limits,
        }


def _plural(n: int, word: str) -> str:
    return f"{n} {word}" + ("" if n == 1 else "s")


def _names(values: list[str] | set[str]) -> str:
    ordered = sorted(values)
    shown = ", ".join(safe(v) for v in ordered[:SHOW])
    return shown + (f" and {len(ordered) - SHOW} more" if len(ordered) > SHOW else "")


def _delta(old: Ref, name: str, now: set[str], lead: str, noun: str) -> str | None:
    """One sentence when the recorded list `name` differs from today's, None when it is the same. A list that was cut is compared by
    its digest (or, in a file written before digests, by its count)."""
    recorded: list[str] = getattr(old, name)
    total: int = getattr(old, f"{name}_total")
    sentence = f"{lead} {_plural(len(now), noun)}, was {total}"
    if old.truncated(name):
        digest_then = old.digests.get(name)
        same = digest(now) == digest_then if digest_then else len(now) == total
        if same:
            return None
        return f"{sentence} (the recorded list was cut at {len(recorded)}, so which ones changed is not known)"
    added, gone = now - set(recorded), set(recorded) - now
    if not added and not gone:
        return None
    parts = ([f"new: {_names(added)}"] if added else []) + ([f"gone: {_names(gone)}"] if gone else [])
    return f"{sentence} ({'; '.join(parts)})"


# ---- a symbol ----------------------------------------------------------------------------------------


def _symbol_candidates(g: RepoGraph, old: Ref) -> tuple[list[str], list[str]]:
    """(by structure, by name): other places that may be what was cited. Only a guess, and said to be."""
    by_shape: list[str] = []
    if old.shape and old.size >= MIN_SHAPE_SIZE:
        by_shape = [s.id for s in g.symbols.values() if s.id != old.id and s.kind == old.symbol_kind and s.shape == old.shape]
    qualname = old.id.partition("::")[2]
    by_name = [s.id for s in g.symbols.values() if s.id != old.id and s.kind != "module" and s.qualname == qualname and s.file != old.file]
    return sorted(by_shape), sorted(by_name)


def _missing_symbol(g: RepoGraph, old: Ref) -> Finding:
    f = Finding(old.id, "symbol", "missing")
    f.details.append(
        f"it is no longer in {old.file}, which still exists" if old.file in g.files
        else f"its file {old.file} is not in the graph (deleted, moved, or outside the analysed folders)"
    )
    by_shape, by_name = _symbol_candidates(g, old)
    candidates = sorted(set(by_shape) | set(by_name))
    f.candidates = [safe(c) for c in candidates[:5]]
    if len(candidates) == 1:
        c = candidates[0]
        why = "the same body structure" if c in by_shape else "the same name"
        f.status = "moved"
        f.details.append(f"it may have moved or been renamed: {safe(c)} has {why} (a candidate, not a fact: check it before relying on it)")
    elif candidates:
        f.details.append(f"{len(candidates)} places look like it ({_names(candidates)}); none is chosen for you")
    return f


def _check_symbol(g: RepoGraph, old: Ref, sym: Symbol) -> Finding:
    f = Finding(old.id, "symbol", "holds")
    changed: list[str] = []
    if old.symbol_kind and old.symbol_kind != sym.kind:
        changed.append(f"it was a {old.symbol_kind}, now a {sym.kind}")
    if old.exported != sym.exported:
        changed.append("it is no longer exported" if old.exported else "it is exported now")
    if old.decorated != sym.decorated:
        changed.append("its decorator was removed" if old.decorated else "a decorator was added")
    structure_differs = bool(old.shape and sym.shape and old.shape != sym.shape)
    if structure_differs:
        changed.append(f"its code structure changed (was {old.size} syntax nodes, now {sym.size})")
    if sym.kind == "class" or old.symbol_kind == "class":
        if old.bases != list(sym.bases[:MAX_LIST]):
            changed.append(f"its base classes changed (was {safe(', '.join(old.bases)) or 'none'}, now {safe(', '.join(sym.bases[:MAX_LIST])) or 'none'})")
        sentence = _delta(old, "members", class_members(g, sym), "it now has", "method")
        if sentence:
            changed.append(sentence)
    cur_measured = is_measured(g.files[sym.file].lang)
    if old.measured and cur_measured:
        for sentence in (
            _delta(old, "callers", callers_of(g, sym.id), "it now has", "resolved caller"),
            _delta(old, "callees", callees_of(g, sym.id), "it now calls", "resolved function"),
        ):
            if sentence:
                changed.append(sentence)
    else:
        f.not_measured.append("callers and callees: not measured (this language has no resolved calls in the graph)")
    if changed:
        f.status, f.details = "changed", changed
        return f
    current = text_hash(g.root, sym)
    if old.text_hash and current and old.text_hash != current:
        f.status = "edited"
        f.details.append(
            "its structure is the same but its text differs (a name, a value or a comment changed)" if old.shape and sym.shape
            else "its text differs (a name, a value or a comment changed; the graph has no structure hash for this kind of place)"
        )
    return f


# ---- a file ------------------------------------------------------------------------------------------


def _missing_file(g: RepoGraph, old: Ref) -> Finding:
    f = Finding(old.id, "file", "missing", [f"{old.id} is not in the graph (deleted, moved, or outside the analysed folders)"])
    base = PurePosixPath(old.id).name
    same = sorted(p for p in g.files if p != old.id and PurePosixPath(p).name == base)
    f.candidates = [safe(p) for p in same[:5]]
    if len(same) == 1:
        f.status = "moved"
        f.details.append(f"it may have moved: {safe(same[0])} has the same file name (a candidate, not a fact: check it before relying on it)")
    elif same:
        f.details.append(f"{len(same)} files have that name ({_names(same)}); none is chosen for you")
    return f


def _check_file(g: RepoGraph, old: Ref) -> Finding:
    f = Finding(old.id, "file", "holds")
    rec = g.files[old.id]
    changed: list[str] = []
    if rec.error:
        f.not_measured.append(f"symbols: not compared (the file had a parse problem: {safe(rec.error[:80])})")
    else:
        sentence = _delta(old, "symbols", file_symbols(g, old.id), "it now has", "symbol")
        if sentence:
            changed.append(sentence)
    if old.measured and is_measured(rec.lang):
        for sentence in (
            _delta(old, "importers", importers_of(g, old.id), "it is now imported by", "file"),
            _delta(old, "imports", imports_of(g, old.id), "it now imports", "file"),
        ):
            if sentence:
                changed.append(sentence)
    else:
        f.not_measured.append("importers and imports: not measured (this language has no resolved imports in the graph)")
    if changed:
        f.status, f.details = "changed", changed
        return f
    current = file_text_hash(g.root, old.id)
    if old.text_hash and current and old.text_hash != current:
        f.status = "edited"
        f.details.append("the file's text differs (its symbols and the files around it are the same: a body, a value or a comment changed)")
    return f


# ---- the whole check ---------------------------------------------------------------------------------


def _recorded(ev: Evidence, ref: Ref) -> str:
    when, commit = (ref.taken_at or ev.taken_at), (ref.commit or ev.commit)
    return when[:10] + (f", commit {commit}" if commit else "") + (" plus uncommitted changes" if commit and ref.dirty else "")


def recheck(ev: Evidence, g: RepoGraph, *, focus: object = _UNSET) -> RecheckReport:
    """Today's graph against `ev`. `focus` is the folder `g` was limited to: when it is given and is not the one the evidence was
    recorded with, the report says so, because a different part of the repository can give different verdicts."""
    findings: list[Finding] = []
    for old in ev.refs:
        if old.kind == "file":
            found = _check_file(g, old) if old.id in g.files else _missing_file(g, old)
        else:
            sym = g.symbols.get(old.id)
            found = _check_symbol(g, old, sym) if sym is not None and sym.kind != "module" else _missing_symbol(g, old)
        found.recorded = _recorded(ev, old)
        findings.append(found)
    here = Path(g.root).name  # only the folder's name is compared: a person's paths are not kept
    notes: list[str] = []
    if ev.repo != here:
        notes.append(f"The evidence was recorded from '{safe(ev.repo)}' and this folder is '{safe(here)}': check that it is the same repository.")
    if focus is not _UNSET and (focus or None) != (ev.focus or None):
        notes.append(
            f"The evidence was recorded with the focus {safe(ev.focus) if ev.focus else 'the whole repository'!r} and this check read "
            f"{safe(str(focus)) if focus else 'the whole repository'!r}: a different part of the repository can give different verdicts."
        )
    commits = sorted({r.commit or ev.commit or "" for r in ev.refs} - {""})
    if len(commits) > 1:
        notes.append(f"The places were recorded at different commits ({', '.join(commits)}): each is compared with today's code, not with the others.")
    current = git_head(g.root)
    current_dirty = git_dirty(g.root) if current else False
    recorded_dirty = ev.dirty or any(r.dirty for r in ev.refs)
    if recorded_dirty or current_dirty:
        notes.append(
            "A commit id does not describe a working tree with uncommitted changes: "
            + " and ".join(s for s, on in (("the evidence was recorded from one", recorded_dirty), ("the repository has some now", current_dirty)) if on)
            + ", so a difference reported here may come from changes that are not in any commit."
        )
    report = RecheckReport(ev.repo, ev.taken_at, ev.commit, current, findings, notes)
    report.recorded_dirty, report.current_dirty = recorded_dirty, current_dirty
    return report
