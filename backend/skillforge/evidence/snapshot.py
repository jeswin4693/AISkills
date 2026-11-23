"""Record what the graph knows about the places a skill cites. Every fact is computed from parsed code, never by a model.

A name-only guess is never recorded as a caller or a callee (a guess counts toward nothing in this project), and for a language
whose calls are not resolved the lists stay empty and the reference says so (`measured` is False): "no callers" is only ever
said where the graph could have seen them. A list longer than the names kept is also recorded as a digest of the whole, so a
swapped caller in a long list is still a difference.
"""

from __future__ import annotations

import ast
import hashlib
import re
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from ..graph import languages, query
from ..graph.model import RepoGraph, Symbol
from .model import MAX_LIST, Evidence, Ref

MIN_SHAPE_SIZE = query.MIN_CLONE_SIZE  # a body shorter than this looks like many others: it is not matched by structure
MAX_DECORATOR_LINES = 40  # how far above a definition a decorator may start
_SHA = re.compile(r"[0-9a-f]{7,40}")


@dataclass
class Resolved:
    """What a person's text for a place came to: one graph node, or nothing (with the options when it was ambiguous)."""

    id: str | None
    options: list[str] = field(default_factory=list)


@dataclass
class Collected:
    evidence: Evidence
    skipped: list[tuple[str, str]]  # (what was asked for, why it was not recorded)


def resolve_ref(g: RepoGraph, text: str) -> Resolved:
    """One node for `text`, or none. Several matches are never picked between: they come back as options (a test file's function
    of the same name counts as one of them)."""
    ref = text.strip().replace("\\", "/")
    if not ref:
        return Resolved(None)
    if ref in g.files or ref in g.symbols:
        return Resolved(ref)
    if "::" not in ref and ("/" in ref or "." in ref.rsplit("/", 1)[-1]):
        path = query.find_file(g, ref)
        if path:
            return Resolved(path)
        several = sorted(p for p in g.files if p.endswith("/" + ref.removeprefix("./")))
        if several:
            return Resolved(None, several[:5])
    found = query.find_symbols(g, ref)
    if len(found) == 1:
        return Resolved(found[0].id)
    return Resolved(None, sorted(s.id for s in found)[:5])


def git_head(root: str | Path) -> str | None:
    """The short id of the repository's current commit, None outside git or when git is not there."""
    try:
        out = subprocess.run(["git", "-C", str(root), "rev-parse", "--short=12", "HEAD"], capture_output=True, timeout=15)
    except (OSError, subprocess.SubprocessError):
        return None
    text = out.stdout.decode("utf-8", errors="replace").strip()
    return text if out.returncode == 0 and _SHA.fullmatch(text) else None


def git_dirty(root: str | Path) -> bool:
    """Whether the folder has uncommitted changes (untracked files count: the graph reads them too). False outside git."""
    try:
        out = subprocess.run(["git", "-C", str(root), "status", "--porcelain", "--", "."], capture_output=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return False
    return out.returncode == 0 and bool(out.stdout.strip())


def is_measured(lang: str) -> bool:
    """Whether the graph resolves calls and imports for this language (full and standard levels), as the roadmap says."""
    return languages.level_of(lang) in ("full", "standard")


# ---- text hashes --------------------------------------------------------------------------------------


def _normalised(lines: list[str]) -> str:
    return "\n".join(line.rstrip() for line in lines)


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _read_lines(root: str | Path, rel: str) -> tuple[str, list[str]] | None:
    """The file's text and its lines. Lines are split on "\\n" only, as the graph counts them: str.splitlines() would also split on
    a form feed or U+2028, which shifts every line number after it."""
    try:
        data = (Path(root) / rel).read_bytes()
    except OSError:
        return None
    text = data.decode("utf-8-sig", errors="replace")
    return text, text.split("\n")


def _python_start(text: str, sym: Symbol) -> int | None:
    """The 1-based line where a Python definition starts, its decorators included (the graph's line is the `def` itself)."""
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError, RecursionError, MemoryError):
        return None
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.lineno == sym.line and node.name == sym.name:
            return min([d.lineno for d in node.decorator_list] + [node.lineno])
    return None


def _decorator_start(lines: list[str], def_idx: int) -> int:
    """For other languages: the 0-based index of the first decorator line above the definition at `def_idx` (lines that start with `@`,
    with the lines of a multi-line argument list between), or `def_idx` when there is none. A heuristic by text."""
    confirmed, depth = def_idx, 0
    for i in range(def_idx - 1, max(def_idx - 1 - MAX_DECORATOR_LINES, -1), -1):
        s = lines[i].strip()
        if not s:
            break
        depth += sum(s.count(c) for c in ")]}") - sum(s.count(c) for c in "([{")
        if depth > 0:  # inside the argument list of a decorator that began further up
            continue
        if s.startswith("@"):
            confirmed, depth = i, 0
        else:
            break
    return confirmed


def text_hash(root: str | Path, sym: Symbol) -> str | None:
    """A hash of the symbol's source text, its decorators included (trailing blanks and the line-ending style left out), None if
    the lines cannot be read."""
    got = _read_lines(root, sym.file)
    if got is None:
        return None
    text, lines = got
    start = None
    if sym.file.endswith((".py", ".pyw")):
        start = _python_start(text, sym)
    start = (start - 1) if start else _decorator_start(lines, max(sym.line - 1, 0))
    window = lines[max(start, 0): sym.end_line]
    return _hash(_normalised(window)) if window and "".join(window).strip() else None


def file_text_hash(root: str | Path, rel: str) -> str | None:
    """A hash of a whole file's text (trailing blanks, trailing blank lines and the line-ending style left out)."""
    got = _read_lines(root, rel)
    return None if got is None else _hash(_normalised(got[1]).rstrip())


# ---- lists --------------------------------------------------------------------------------------------


def digest(values: set[str]) -> str:
    """A digest of a whole set of names, so a list cut at MAX_LIST is still compared as a whole."""
    return _hash("\n".join(sorted(values)))


def _cut(values: set[str]) -> tuple[list[str], int]:
    ordered = sorted(values)
    return ordered[:MAX_LIST], len(ordered)


def callers_of(g: RepoGraph, symbol_id: str) -> set[str]:
    return {e.src for e in g.callers_of(symbol_id) if e.conf == "resolved"}


def callees_of(g: RepoGraph, symbol_id: str) -> set[str]:
    return {e.dst for e in g.callees_of(symbol_id) if e.conf == "resolved"}


def file_symbols(g: RepoGraph, path: str) -> set[str]:
    return {s.qualname for s in g.symbols.values() if s.file == path and s.kind != "module"}


def class_members(g: RepoGraph, sym: Symbol) -> set[str]:
    """The methods (and nested classes) of a class, as their qualified names."""
    return {s.qualname for s in g.symbols.values() if s.file == sym.file and s.parent == sym.qualname}


def importers_of(g: RepoGraph, path: str) -> set[str]:
    return {e.src for e in g.importers_of(path)}


def imports_of(g: RepoGraph, path: str) -> set[str]:
    return {e.dst for e in g.imports_of(path)}


def _symbol_ref(g: RepoGraph, sym: Symbol) -> Ref:
    lang = g.files[sym.file].lang
    measured = is_measured(lang)
    callers, callees = (callers_of(g, sym.id), callees_of(g, sym.id)) if measured else (set(), set())
    members = class_members(g, sym) if sym.kind == "class" else set()
    digests = {name: digest(values) for name, values in (("callers", callers), ("callees", callees), ("members", members)) if values}
    callers_kept, callers_total = _cut(callers)
    callees_kept, callees_total = _cut(callees)
    members_kept, members_total = _cut(members)
    return Ref(
        id=sym.id, kind="symbol", file=sym.file, lang=lang, measured=measured, symbol_kind=sym.kind, line=sym.line,
        end_line=sym.end_line, exported=sym.exported, decorated=sym.decorated, shape=sym.shape, size=sym.size,
        text_hash=text_hash(g.root, sym), bases=list(sym.bases[:MAX_LIST]), callers=callers_kept, callers_total=callers_total,
        callees=callees_kept, callees_total=callees_total, members=members_kept, members_total=members_total, digests=digests,
    )


def _file_ref(g: RepoGraph, path: str) -> Ref:
    rec = g.files[path]
    measured = is_measured(rec.lang)
    symbols = file_symbols(g, path)
    importers, imports = (importers_of(g, path), imports_of(g, path)) if measured else (set(), set())
    digests = {name: digest(values) for name, values in (("symbols", symbols), ("importers", importers), ("imports", imports)) if values}
    symbols_kept, symbols_total = _cut(symbols)
    importers_kept, importers_total = _cut(importers)
    imports_kept, imports_total = _cut(imports)
    return Ref(
        id=path, kind="file", file=path, lang=rec.lang, measured=measured, lines=rec.lines, text_hash=file_text_hash(g.root, path),
        symbols=symbols_kept, symbols_total=symbols_total, importers=importers_kept, importers_total=importers_total,
        imports=imports_kept, imports_total=imports_total, digests=digests,
    )


def node_of(g: RepoGraph, text: str) -> str:
    """The graph node a cited text is recorded as: a module symbol is recorded as its file."""
    sym = g.symbols.get(text)
    return sym.file if sym is not None and sym.kind == "module" else text


def collect(g: RepoGraph, ids: list[str], *, focus: str | None = None, now: datetime | None = None) -> Collected:
    """Evidence for the graph nodes `ids` (as written in the graph: a file path or `file::name`). What is not in the graph is
    reported in `skipped` and never recorded. A module symbol is recorded as its file."""
    refs: list[Ref] = []
    skipped: list[tuple[str, str]] = []
    seen: set[str] = set()
    for text in ids:
        node = node_of(g, text)
        if node in seen:
            continue
        try:
            if node in g.files:
                refs.append(_file_ref(g, node))
            elif node in g.symbols:
                refs.append(_symbol_ref(g, g.symbols[node]))
            else:
                skipped.append((text, "it is not in the repository's graph"))
                continue
        except ValueError:  # the strict model refused it: a name with control, hidden or direction-changing characters
            skipped.append((ascii(text), "its name has control, hidden or direction-changing characters, which evidence does not keep"))
            continue
        seen.add(node)
    stamp = (now or datetime.now(timezone.utc)).isoformat(timespec="seconds")
    commit = git_head(g.root)  # once: each starts a program
    dirty = git_dirty(g.root) if commit else False
    for ref in refs:
        ref.taken_at, ref.commit, ref.dirty = stamp, commit, dirty
    return Collected(Evidence(repo=Path(g.root).name, commit=commit, dirty=dirty, focus=focus, taken_at=stamp, refs=refs), skipped)
