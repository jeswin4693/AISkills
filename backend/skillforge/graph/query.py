"""Questions to ask the graph. Every answer is computed from parsed code and git history, with its confidence."""

from __future__ import annotations

from collections import deque
from typing import Any

from .model import RepoGraph, Symbol

MIN_CLONE_SIZE = 30  # syntax nodes; smaller bodies (getters, one-liners) are not worth reporting
MIN_CLONE_LINES = 3  # one-line helpers that look alike are not worth merging


class QueryError(Exception):
    """The question cannot be answered as asked; the message says what to do."""


# ---- finding things ------------------------------------------------------------------------------------


def find_symbols(g: RepoGraph, target: str) -> list[Symbol]:
    t = target.strip().replace("\\", "/")
    if t in g.symbols:
        return [g.symbols[t]]
    syms = [s for s in g.symbols.values() if s.kind != "module"]
    if "::" in t:
        file_part, _, qual = t.partition("::")
        return [s for s in syms if s.qualname == qual and (s.file == file_part or s.file.endswith("/" + file_part))]
    exact = [s for s in syms if s.qualname == t]
    return exact or [s for s in syms if s.name == t]


def find_symbol(g: RepoGraph, target: str) -> Symbol:
    found = find_symbols(g, target)
    if not found:
        raise QueryError(f'Nothing matches "{target}". Search with the "symbols" command.')
    if len(found) > 1:
        non_test = [s for s in found if not g.files[s.file].is_test]
        if len(non_test) == 1:
            return non_test[0]
        listing = "; ".join(f"{s.file}::{s.qualname}" for s in found[:8])
        raise QueryError(f'"{target}" is ambiguous ({len(found)} matches): {listing}. Use file::name.')
    return found[0]


def find_file(g: RepoGraph, target: str) -> str | None:
    t = target.strip().replace("\\", "/").removeprefix("./")
    if t in g.files:
        return t
    matches = [p for p in g.files if p.endswith("/" + t)]
    return matches[0] if len(matches) == 1 else None


def _looks_like_file(target: str) -> bool:
    t = target.replace("\\", "/")
    return "::" not in t and ("/" in t or "." in t.rsplit("/", 1)[-1])


def _info(g: RepoGraph, s: Symbol, **extra: Any) -> dict[str, Any]:
    return {"id": s.id, "kind": s.kind, "name": s.qualname, "file": s.file, "line": s.line,
            "test": g.files[s.file].is_test, **extra}


def search_symbols(g: RepoGraph, text: str, limit: int = 30) -> list[dict[str, Any]]:
    needle = text.lower()
    hits = [
        s for s in g.symbols.values()
        if s.kind != "module" and (needle in s.qualname.lower() or needle in s.file.lower())
    ]
    hits.sort(key=lambda s: (g.files[s.file].is_test, len(s.qualname), s.file))
    return [_info(g, s, lines=s.end_line - s.line + 1) for s in hits[:limit]]


# ---- callers and callees -------------------------------------------------------------------------------


def _walk(g: RepoGraph, start: str, depth: int, direction: str, include_guesses: bool) -> list[dict[str, Any]]:
    seen: dict[str, tuple[int, str]] = {start: (0, "resolved")}
    queue = deque([start])
    out: list[dict[str, Any]] = []
    while queue:
        cur = queue.popleft()
        d, path_conf = seen[cur]
        if d >= depth:
            continue
        edges = g.callers_of(cur) if direction == "callers" else g.callees_of(cur)
        for e in edges:
            if e.conf == "guess" and not include_guesses:
                continue
            nxt = e.src if direction == "callers" else e.dst
            if nxt in seen:
                continue
            conf = "guess" if "guess" in (path_conf, e.conf) else "resolved"
            seen[nxt] = (d + 1, conf)
            queue.append(nxt)
            out.append(_info(g, g.symbols[nxt], depth=d + 1, conf=conf, times=e.count))
    return out


def _calls_query(g: RepoGraph, target: str, depth: int, include_guesses: bool, direction: str) -> dict[str, Any]:
    sym = find_symbol(g, target)
    results = _walk(g, sym.id, max(1, depth), direction, include_guesses)
    notes = []
    if any(r["conf"] == "guess" for r in results):
        notes.append("Entries marked 'guess' were matched by name only; check them before relying on them.")
    notes.append(
        f"Calls the parser could not pin to one target: {g.call_stats.get('ambiguous', 0)} ambiguous, "
        f"{g.call_stats.get('unresolved', 0)} unresolved. Dynamic calls are invisible to static analysis."
    )
    return {"target": _info(g, sym), "depth": depth, "results": results, "notes": notes}


def callers(g: RepoGraph, target: str, depth: int = 1, include_guesses: bool = True) -> dict[str, Any]:
    return _calls_query(g, target, depth, include_guesses, "callers")


def callees(g: RepoGraph, target: str, depth: int = 1, include_guesses: bool = True) -> dict[str, Any]:
    return _calls_query(g, target, depth, include_guesses, "callees")


# ---- impact --------------------------------------------------------------------------------------------


def impact(g: RepoGraph, target: str, depth: int = 3) -> dict[str, Any]:
    """What could a change to a file or function reach? Dependents, tests, and files that change together."""
    path = find_file(g, target) if _looks_like_file(target) else None
    if path is not None:
        seeds = [s.id for s in g.files[path].symbols if s.kind != "module"]
        subject = {"kind": "file", "name": path, "file": path}
    else:
        sym = find_symbol(g, target)
        path = sym.file
        seeds = [sym.id]
        subject = {"kind": sym.kind, "name": sym.qualname, "file": sym.file, "line": sym.line}

    affected: dict[str, dict[str, Any]] = {}

    def note(p: str, d: int, via: str, conf: str) -> None:
        if p == path:
            return
        cur = affected.get(p)
        if cur is None or d < cur["depth"]:
            affected[p] = {"path": p, "depth": d, "via": via, "conf": conf, "test": g.files[p].is_test}

    frontier, seen_files = {path}, {path}
    for d in range(1, depth + 1):
        nxt: set[str] = set()
        for p in frontier:
            for e in g.importers_of(p):
                if e.src not in seen_files:
                    seen_files.add(e.src)
                    nxt.add(e.src)
                    note(e.src, d, "imports", "resolved")
        frontier = nxt
    for sid in seeds:
        for r in _walk(g, sid, depth, "callers", True):
            note(r["file"], r["depth"], "calls", r["conf"])

    dependents = sorted(affected.values(), key=lambda a: (a["depth"], a["path"]))
    # Only proven links count toward risk and test coverage; name-only matches are listed as "possible".
    possible = [a for a in dependents if a["conf"] == "guess"]
    tests = [a for a in dependents if a["test"] and a["conf"] == "resolved"]
    non_test = [a for a in dependents if not a["test"] and a["conf"] == "resolved"]
    importers = {e.src for e in g.importers_of(path)} | {e.dst for e in g.imports_of(path)}
    hidden = []
    for a, b, shared, conf in g.co_change:
        if path not in (a, b):
            continue
        partner = b if a == path else a
        if conf >= 0.3 and partner not in affected and partner not in importers:
            hidden.append({"path": partner, "shared_commits": shared, "confidence": conf})
    strong = [h for h in hidden if h["confidence"] >= 0.5]
    score = min(20, len(non_test)) + 2 * len(strong) + (0 if tests else 4)
    level = "low" if score < 5 else "medium" if score < 12 else "high"

    notes: list[str] = []
    if possible:
        notes.append(
            f"{len(possible)} more file(s) are linked only by a name match. They are listed as possible and "
            "do not count toward the risk score."
        )
    if g.gaps.get(path):
        notes.append(f"{len(g.gaps[path])} relative import(s) in this file match no file: {', '.join(g.gaps[path][:3])}.")
    if g.commits is None:
        notes.append("No git history, so files that change together are unknown.")
    notes.append(
        f"{g.call_stats.get('ambiguous', 0)} call(s) in the repository are ambiguous and cannot be followed."
    )
    return {
        "subject": subject,
        "depth": depth,
        "dependents": dependents,
        "tests_tied": [a["path"] for a in tests],
        "hidden_coupling": hidden[:10],
        "risk": {
            "level": level,
            "score": score,
            "factors": {"non_test_dependents": len(non_test), "strong_hidden_coupling": len(strong),
                        "no_test_tied": not tests, "possible_dependents": len(possible)},
        },
        "notes": notes,
    }


# ---- paths ---------------------------------------------------------------------------------------------


def find_path(g: RepoGraph, source: str, dest: str, include_guesses: bool = True) -> dict[str, Any]:
    """Shortest chain of calls (or, for two files, of imports) from `source` to `dest`."""
    fa = find_file(g, source) if _looks_like_file(source) else None
    fb = find_file(g, dest) if _looks_like_file(dest) else None
    if fa and fb:
        kind, start, goal = "imports", fa, fb
        neighbours = lambda n: [(e.dst, "resolved") for e in g.imports_of(n)]  # noqa: E731
        label = lambda n: {"path": n}  # noqa: E731
    else:
        kind = "calls"
        start, goal = find_symbol(g, source).id, find_symbol(g, dest).id
        neighbours = lambda n: [  # noqa: E731
            (e.dst, e.conf) for e in g.callees_of(n) if include_guesses or e.conf != "guess"
        ]
        label = lambda n: _info(g, g.symbols[n])  # noqa: E731

    prev: dict[str, tuple[str | None, str]] = {start: (None, "resolved")}
    queue = deque([start])
    while queue and goal not in prev:
        cur = queue.popleft()
        for nxt, conf in neighbours(cur):
            if nxt not in prev:
                prev[nxt] = (cur, conf)
                queue.append(nxt)
    if goal not in prev:
        return {"found": False, "kind": kind, "path": [], "hops": 0, "uses_guess": False}
    chain, uses_guess, node = [], False, goal
    while node is not None:
        parent, conf = prev[node]
        uses_guess = uses_guess or conf == "guess"
        chain.append(label(node))
        node = parent
    chain.reverse()
    return {"found": True, "kind": kind, "path": chain, "hops": len(chain) - 1, "uses_guess": uses_guess}


# ---- repository-level questions ------------------------------------------------------------------------


def hotspots(g: RepoGraph, top: int = 15) -> dict[str, Any]:
    core = []
    for s in g.symbols.values():
        if s.kind not in ("function", "method", "class") or g.files[s.file].is_test:
            continue
        # callers in test files show that something is tested, not that it is depended on
        callers_ = {e.src for e in g.callers_of(s.id) if not g.files[g.symbols[e.src].file].is_test}
        if callers_:
            callees_ = {e.dst for e in g.callees_of(s.id)}
            core.append(_info(g, s, fan_in=len(callers_), fan_out=len(callees_), size=s.size))
    core.sort(key=lambda r: (-r["fan_in"], -r["size"], r["id"]))

    risky = []
    for p, rec in g.files.items():
        if rec.is_test:
            continue
        importers = len({e.src for e in g.importers_of(p)})
        churn = g.churn.get(p, 0)
        if importers and churn:
            risky.append({"path": p, "importers": importers, "commits": churn, "score": importers * churn})
    risky.sort(key=lambda r: (-r["score"], r["path"]))
    note = "Score = files that import it x commits that touched it. Needs git history." if g.commits else (
        "No git history, so churn-based ranking is empty."
    )
    return {"core_symbols": core[:top], "risky_files": risky[:top], "note": note}


def duplicates(
    g: RepoGraph, min_size: int = MIN_CLONE_SIZE, include_tests: bool = False, min_lines: int = MIN_CLONE_LINES
) -> dict[str, Any]:
    """Groups of functions with the same structure. Names and literal values are ignored (type-2 clones)."""
    groups: dict[str, list[Symbol]] = {}
    for s in g.symbols.values():
        if s.kind not in ("function", "method") or not s.shape or s.size < min_size:
            continue
        if s.end_line - s.line + 1 < min_lines:
            continue
        if s.name.startswith("__") and s.name.endswith("__"):
            continue
        if g.files[s.file].is_test and not include_tests:
            continue
        groups.setdefault(s.shape, []).append(s)
    out = []
    for shape, members in groups.items():
        if len(members) < 2:
            continue
        members.sort(key=lambda s: (s.file, s.line))
        out.append({
            "shape": shape,
            "size": members[0].size,
            "copies": len(members),
            "cross_file": len({m.file for m in members}) > 1,
            "members": [_info(g, m, lines=m.end_line - m.line + 1) for m in members],
        })
    out.sort(key=lambda grp: (-(grp["size"] * (grp["copies"] - 1)), grp["shape"]))
    return {
        "min_size": min_size,
        "groups": out,
        "note": "Same structure with names and values ignored. Near-duplicates (a few changed lines) are not detected yet.",
    }


def dead_candidates(g: RepoGraph) -> dict[str, Any]:
    """Functions nothing visibly uses. Candidates only: dynamic use, frameworks and public APIs are invisible here."""
    used_names: set[str] = set()
    for rec in g.files.values():
        used_names.update(rec.refs)
    internal, public = [], []
    for s in g.symbols.values():
        if s.kind not in ("function", "method") or g.files[s.file].is_test or s.decorated:
            continue
        if (s.name.startswith("__") and s.name.endswith("__")) or s.name == "main":
            continue
        if g.callers_of(s.id) or s.name in used_names or s.name in g.loose_names:
            continue
        (public if s.exported else internal).append(_info(g, s, lines=s.end_line - s.line + 1))
    key = lambda r: (-r["lines"], r["id"])  # noqa: E731
    internal.sort(key=key)
    public.sort(key=key)
    return {
        "internal": internal,
        "exported": public,
        "note": "Candidates, not proof. 'exported' ones may be public API or used from outside this repository.",
    }


def stats(g: RepoGraph) -> dict[str, Any]:
    kinds: dict[str, int] = {}
    for s in g.symbols.values():
        kinds[s.kind] = kinds.get(s.kind, 0) + 1
    langs: dict[str, int] = {}
    for rec in g.files.values():
        langs[rec.lang] = langs.get(rec.lang, 0) + 1
    edge_counts: dict[str, int] = {}
    for e in g.edges:
        key = e.kind if e.conf == "resolved" else f"{e.kind} ({e.conf})"
        edge_counts[key] = edge_counts.get(key, 0) + 1
    return {
        "root": g.root,
        "files": len(g.files),
        "test_files": sum(1 for r in g.files.values() if r.is_test),
        "lines": sum(r.lines for r in g.files.values()),
        "languages": langs,
        "symbols": kinds,
        "edges": edge_counts,
        "call_sites": g.call_stats,
        "unresolved_imports": sum(len(v) for v in g.gaps.values()),
        "parse_problems": sum(1 for r in g.files.values() if r.error),
        "commits_read": g.commits,
        "co_change_pairs": len(g.co_change),
        "notes": g.notes,
    }
