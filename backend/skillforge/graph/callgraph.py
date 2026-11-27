"""The function-level call graph (slice AL): one function, the functions that call it and the functions it calls, one level or two.

Computed from the graph by code (no model, nothing is run), like the folder map in `architecture.py`. The rules, all tested:

* Only **proven** calls (`resolved`) are drawn. A name-only match (`guess`) is counted and said, never drawn.
* A language whose calls the graph does not read (the `basic` level) says "not measured": it is never shown as "calls nothing".
* Functions in test files that call something are **counted, not drawn** (they show that it is tested, not how the program works), unless the
  function chosen is itself a test.
* The caps cut the weakest first (most call sites, then name), so the cut is stable; what was cut is counted (`over_limit`).
* The same graph gives the same answer whatever order it was built in: every list is sorted.

A call a function makes to itself is not here: the graph does not record one (`build.py` skips `target.id == sym.id`).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from . import languages
from .model import RepoGraph, Symbol
from .query import QueryError

CALLABLE_KINDS = ("function", "method", "class")  # a module is not something to ask "who calls it" about
MAX_DEPTH = 2
MAX_SIDE = 20  # functions drawn on one side of the chosen one, over both steps
LEVEL_CAP = {1: 10, 2: 5}  # neighbours of one function, by how many steps it is from the chosen one
MAX_MATCHES = 25  # search results shown


def _is_test(g: RepoGraph, symbol_id: str) -> bool:
    return g.files[g.symbols[symbol_id].file].is_test


def _measured(lang: str) -> bool:
    """Whether the graph resolves calls for this language (full and standard levels); the basic level only finds definitions."""
    return languages.level_of(lang) in ("full", "standard")


def _totals(g: RepoGraph, symbol_id: str) -> tuple[int, int, int]:
    """(proven callers that are not tests, proven callers that are tests, proven callees), each counted once per function. For a function that
    is itself a test, every caller counts as an ordinary one."""
    callers = {e.src for e in g.callers_of(symbol_id) if e.conf == "resolved" and e.src != symbol_id}
    tests = {c for c in callers if _is_test(g, c)} if not _is_test(g, symbol_id) else set()
    callees = {e.dst for e in g.callees_of(symbol_id) if e.conf == "resolved" and e.dst != symbol_id}
    return len(callers) - len(tests), len(tests), len(callees)


def _node(g: RepoGraph, sym: Symbol, role: str, column: int) -> dict[str, Any]:
    callers, tests, callees = _totals(g, sym.id)
    return {
        "id": sym.id, "name": sym.qualname, "kind": sym.kind, "file": sym.file, "line": sym.line, "lines": sym.end_line - sym.line + 1,
        "test": g.files[sym.file].is_test, "role": role, "column": column,
        "callers_total": callers, "tests_total": tests, "callees_total": callees,
    }


@dataclass
class _Side:
    shown: dict[str, int] = field(default_factory=dict)  # function id -> how many steps from the chosen one
    candidates: set[str] = field(default_factory=set)  # every proven neighbour that could have been drawn
    tests: set[str] = field(default_factory=set)  # neighbours in test files, skipped
    guess: set[tuple[str, str]] = field(default_factory=set)  # name-only links around the functions looked at, skipped


def _walk(g: RepoGraph, start: str, direction: str, depth: int, skip_tests: bool) -> _Side:
    """The functions up to `depth` steps from `start`, on one side (callers or callees), strongest first and capped."""
    side = _Side()
    budget = MAX_SIDE
    frontier = [start]
    for step in range(1, depth + 1):
        reached: list[str] = []
        for cur in frontier:
            weight: dict[str, int] = {}
            for e in g.callers_of(cur) if direction == "callers" else g.callees_of(cur):
                other = e.src if direction == "callers" else e.dst
                if other == start:
                    continue
                if e.conf != "resolved":
                    side.guess.add((e.src, e.dst))
                    continue
                if other in side.shown:
                    continue
                if skip_tests and _is_test(g, other):
                    side.tests.add(other)
                    continue
                weight[other] = weight.get(other, 0) + e.count
            side.candidates.update(weight)
            strongest = sorted(weight.items(), key=lambda kv: (-kv[1], g.symbols[kv[0]].qualname, kv[0]))
            for other, _ in strongest[: min(LEVEL_CAP[step], budget)]:
                side.shown[other] = step
                reached.append(other)
                budget -= 1
        frontier = reached
    return side


def call_graph(g: RepoGraph, symbol_id: str, depth: int = 1) -> dict[str, Any]:
    """What calls a function and what it calls. `symbol_id` is a graph id (`file::name`, from `search_functions`). `depth` is 1 or 2."""
    sym = g.symbols.get(symbol_id)
    if sym is None or sym.kind not in CALLABLE_KINDS:
        raise QueryError("That is not a function, method or class in this repository's graph. Search for it again.")
    depth = MAX_DEPTH if depth >= MAX_DEPTH else 1
    lang = g.files[sym.file].lang
    base: dict[str, Any] = {"depth": depth, "measured": _measured(lang), "language": lang, "level": languages.level_of(lang)}
    subject = _node(g, sym, "subject", 0)
    if not base["measured"]:
        return {"subject": subject, "nodes": [subject], "edges": [], **base, "calls": {"written": 0, "tied": 0},
                "left_out": {"guess": 0, "from_tests": 0, "over_limit": 0}}

    skip_tests = not g.files[sym.file].is_test
    up = _walk(g, sym.id, "callers", depth, skip_tests)
    down = _walk(g, sym.id, "callees", depth, skip_tests)
    placed: dict[str, tuple[str, int]] = {i: ("caller", -step) for i, step in up.shown.items()}
    for i, step in down.shown.items():  # a function on both sides is drawn once, on the callee side
        placed[i] = ("both" if i in up.shown else "callee", step)
    nodes = [subject] + [_node(g, g.symbols[i], role, column) for i, (role, column) in placed.items()]
    nodes.sort(key=lambda n: (n["column"], n["name"], n["id"]))

    inside = {n["id"] for n in nodes}
    edges = [
        {"from": e.src, "to": e.dst, "count": e.count}
        for i in inside for e in g.callees_of(i)
        if e.conf == "resolved" and e.dst in inside and e.dst != i
    ]
    edges.sort(key=lambda e: (e["from"], e["to"]))
    return {
        "subject": subject, "nodes": nodes, "edges": edges, **base,
        "calls": {"written": len(sym.calls), "tied": sum(e.count for e in g.callees_of(sym.id) if e.conf == "resolved")},
        "left_out": {
            "guess": len(up.guess | down.guess),
            "from_tests": len(up.tests | down.tests),
            "over_limit": len((up.candidates | down.candidates) - inside),
        },
    }


def search_functions(g: RepoGraph, text: str, limit: int = MAX_MATCHES) -> dict[str, Any]:
    """Functions, methods and classes whose name (or file) contains the text: an exact name first, then a name that starts with it, then one that
    contains it, then a file path that does; code before tests; then the most called."""
    needle = text.strip().lower()
    if not needle:
        return {"matches": [], "total": 0}
    found: list[tuple[tuple[Any, ...], dict[str, Any]]] = []
    for s in g.symbols.values():
        if s.kind not in CALLABLE_KINDS:
            continue
        qual, name = s.qualname.lower(), s.name.lower()
        if needle in (qual, name):
            rank = 0
        elif qual.startswith(needle) or name.startswith(needle):
            rank = 1
        elif needle in qual:
            rank = 2
        elif needle in s.file.lower():
            rank = 3
        else:
            continue
        callers, _, callees = _totals(g, s.id)
        is_test = g.files[s.file].is_test
        found.append(((rank, is_test, -callers, len(s.qualname), s.file, s.id), {
            "id": s.id, "name": s.qualname, "kind": s.kind, "file": s.file, "line": s.line, "test": is_test,
            "callers": callers, "callees": callees, "measured": _measured(g.files[s.file].lang),
        }))
    found.sort(key=lambda item: item[0])
    return {"matches": [m for _, m in found[:limit]], "total": len(found)}
