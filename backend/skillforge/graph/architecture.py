"""The architecture map: a repository's top-level folders as boxes, and the proven imports between them as arrows.

Everything here is computed from the graph. No model takes part and nothing is run. What is deliberately NOT drawn:
a `guess` link (name only), and an import written by a test file (a tests folder would point at every box). Both are
counted and said, never hidden. The answer is the same for the same repository, whatever order the graph was built in.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from . import languages
from .files import is_test_support_path
from .model import RepoGraph

MIN_BOXES = 6  # fewer top folders than this: look one level deeper, so the picture shows structure and not just "backend" and "tests"
MAX_LEVELS = 3  # folder levels a box name may have (a/b/c)
MAX_BOXES = 14  # more folders than this: the smallest fold into one "other" box
MAX_FILES_LISTED = 12  # files a box names (the biggest by lines)
MAX_FUNCTIONS_LISTED = 3  # functions a box names (the biggest by size)
ROOT_LABEL = "(root)"
ONE_PLACE = "Everything sits in one place, so the map is a single box."


def architecture(g: RepoGraph, max_boxes: int = MAX_BOXES) -> dict[str, Any]:
    """The map as plain data. Boxes carry an id that is their position after sorting (m0, m1, ...), never their name, so a real folder
    called "(root)" or "(other)" cannot be mistaken for a box the code made."""
    paths = sorted(g.files)
    depth = _base_depth(paths)
    levels = _levels(paths, depth)
    groups: dict[str | None, list[str]] = {}
    for path in paths:
        groups.setdefault(_folder_of(path, depth, levels), []).append(path)

    boxes = _boxes(g, groups, max(2, max_boxes))
    owner = {p: box["id"] for box in boxes for key in box["_keys"] for p in groups[key]}
    arrows, guesses, from_tests = _arrows(g, owner, {box["id"]: i for i, box in enumerate(boxes)})
    cycles, column, columns, back = _layout([box["id"] for box in boxes], arrows)
    for a in arrows:
        a["back"] = (a["from"], a["to"]) in back

    levels = {lang: languages.level_of(lang) for lang in sorted({r.lang for r in g.files.values()})}
    unread = [lang for lang in levels if not _reads_imports(lang)]  # languages here whose imports are not turned into file links
    modules = [
        {k: box[k] for k in ("id", "label", "kind", "files", "lines", "test_files", "tests_only", "symbols", "languages", "measured")}
        | {"column": column[box["id"]]} | {k: box[k] for k in ("top_functions", "file_list", "members")}
        for box in boxes
    ]
    measured = any(m["measured"] for m in modules)
    return {
        "base": "/".join(paths[0].split("/")[:depth]) if paths else "",
        "modules": modules,
        "arrows": arrows,
        "cycles": cycles,
        "columns": columns,
        "measured": measured,
        "language_levels": levels,
        "imports_not_read": unread,
        "left_out": {"guess": len(guesses), "from_tests": len(from_tests)},
        "notes": _notes(len(modules), measured, unread),
    }


def _base_depth(paths: list[str]) -> int:
    """How many leading folders every file shares (a `src/` or a focus folder), so the map shows what is inside it. A file at the top of
    the repository, or two different first folders, stops it."""
    parts = [p.split("/") for p in paths]
    depth = 0
    while parts and all(len(s) > depth + 1 for s in parts) and len({s[depth] for s in parts}) == 1:
        depth += 1
    return depth


def _folder_of(path: str, base: int, levels: int) -> str | None:
    """The box a file belongs to: its folder, cut to `levels` folders below the shared base (a file deeper than that stays in the box at the
    cut). None for a file directly in the base."""
    folders = path.split("/")[base:-1]
    return "/".join(folders[:levels]) if folders else None


def _levels(paths: list[str], base: int) -> int:
    """How many folder levels name a box: the fewest that give at least MIN_BOXES boxes. A repository whose top is just `backend` and `tests`
    is drawn one level down, or the map would be two boxes and no arrows. If no level gets there, the one with the most boxes (the first, on a tie)."""
    best, most = 1, 0
    for levels in range(1, MAX_LEVELS + 1):
        boxes = len({_folder_of(p, base, levels) for p in paths})
        if boxes >= MIN_BOXES:
            return levels
        if boxes > most:
            best, most = levels, boxes
    return best


@lru_cache(maxsize=None)
def _reads_imports(lang: str) -> bool:
    """Whether the graph turns this language's imports into links between files. The full-level languages do, and a standard one does when its
    imports map to files. C# is standard, but `using Acme.B;` names a namespace and not a file, so the graph makes no import link for it: its
    boxes must not look like folders that depend on nothing."""
    level = languages.level_of(lang)
    return level == "full" or (level == "standard" and languages.info(lang).import_style != "none")


def reads_imports(lang: str) -> bool:
    """Public name of `_reads_imports`: the guide asks it too, so a hop it cannot confirm is said to be "not measured", not "not imported"."""
    return _reads_imports(lang)


def _summary(g: RepoGraph, paths: list[str]) -> dict[str, Any]:
    recs = [g.files[p] for p in paths]
    langs: dict[str, int] = {}
    for r in recs:
        langs[r.lang] = langs.get(r.lang, 0) + 1
    biggest = sorted(
        (s for r in recs if not r.is_test for s in r.symbols if s.kind in ("function", "method")),
        key=lambda s: (-s.size, s.file, s.line, s.name),
    )
    tests = sum(1 for r in recs if r.is_test)
    return {
        # test_files stays the graph's own count (it adds up to the headline); tests_only also counts scaffolding, so an e2e box is tagged "tests"
        "files": len(recs), "lines": sum(r.lines for r in recs), "test_files": tests,
        "tests_only": all(r.is_test or is_test_support_path(r.path) for r in recs),
        "symbols": sum(len(r.symbols) for r in recs), "languages": dict(sorted(langs.items())),
        "measured": any(_reads_imports(lang) for lang in langs),
        "top_functions": [{"name": s.name, "file": s.file, "line": s.line, "size": s.size} for s in biggest[:MAX_FUNCTIONS_LISTED]],
    }


def _boxes(g: RepoGraph, groups: dict[str | None, list[str]], limit: int) -> list[dict[str, Any]]:
    label = lambda key: ROOT_LABEL if key is None else key  # noqa: E731
    ranked = sorted(groups, key=lambda k: (-len(groups[k]), label(k)))
    keep, folded = (ranked, []) if len(ranked) <= limit else (ranked[: limit - 1], ranked[limit - 1:])
    boxes = []
    for key in keep:
        ranked_files = sorted(groups[key], key=lambda p: (-g.files[p].lines, p))
        boxes.append({
            "label": label(key), "kind": "root" if key is None else "folder", **_summary(g, groups[key]), "members": [],
            "file_list": [{"path": p, "lines": g.files[p].lines} for p in ranked_files[:MAX_FILES_LISTED]], "_keys": [key],
        })
    if folded:
        boxes.append({
            "label": f"(other: {len(folded)} more)", "kind": "other", **_summary(g, sorted(p for k in folded for p in groups[k])),
            "members": sorted(label(k) for k in folded), "file_list": [], "_keys": folded,
        })
    boxes.sort(key=lambda b: (b["label"], b["kind"]))
    for i, box in enumerate(boxes):
        box["id"] = f"m{i}"
    return boxes


def _arrows(g: RepoGraph, owner: dict[str, str], rank: dict[str, int]) -> tuple[list[dict[str, Any]], set, set]:
    """One arrow per (importing box, imported box), counted in distinct file pairs. Only proven imports between two different boxes, and
    not from a test file; the guesses and the test imports that were left out are returned so the page can say how many."""
    pairs: dict[tuple[str, str], set[tuple[str, str]]] = {}
    guesses: set[tuple[str, str]] = set()
    from_tests: set[tuple[str, str]] = set()
    for e in g.edges:
        if e.kind != "imports" or e.src not in owner or e.dst not in owner or owner[e.src] == owner[e.dst]:
            continue
        if e.conf != "resolved":
            guesses.add((e.src, e.dst))
        elif g.files[e.src].is_test or is_test_support_path(e.src):  # a test, or scaffolding: an e2e suite or a test server
            from_tests.add((e.src, e.dst))
        else:
            pairs.setdefault((owner[e.src], owner[e.dst]), set()).add((e.src, e.dst))
    arrows = [{"from": a, "to": b, "count": len(files)} for (a, b), files in pairs.items()]
    arrows.sort(key=lambda a: (-a["count"], rank[a["from"]], rank[a["to"]]))
    return arrows, guesses, from_tests


def _layout(ids: list[str], arrows: list[dict[str, Any]]) -> tuple[list[list[str]], dict[str, int], int, set[tuple[str, str]]]:
    """Cycle groups, a column for every box, and the arrows that point back.

    One left-to-right order: groups of boxes that import each other come in topological order (what imports others first), and inside a group
    the box that mostly imports comes before the one that is mostly imported (more imports out than in, within the group). An arrow against that
    order is a "back" arrow: it is the weaker direction, the one that closes the loop. With no cycle there are none. A box's column is the longest
    chain of forward arrows that reaches it."""
    rank = {b: i for i, b in enumerate(ids)}
    succ: dict[str, list[str]] = {b: [] for b in ids}
    weight: dict[tuple[str, str], int] = {}
    for a in arrows:
        succ[a["from"]].append(a["to"])
        weight[(a["from"], a["to"])] = a["count"]
    for b in ids:
        succ[b].sort(key=rank.__getitem__)
    groups = _components(ids, succ)  # Tarjan lists a group only after every group it reaches: sinks first
    order: list[str] = []
    for group in reversed(groups):  # sources first
        if len(group) > 1:
            inside = set(group)
            flow = dict.fromkeys(group, 0)
            for (src, dst), n in weight.items():
                if src in inside and dst in inside:
                    flow[src] += n
                    flow[dst] -= n
            group = sorted(group, key=lambda b: (-flow[b], rank[b]))
        order.extend(group)
    position = {b: i for i, b in enumerate(order)}
    level = dict.fromkeys(ids, 0)
    for b in order:  # every forward arrow into b comes from an earlier box, so b's level is final here
        for nxt in succ[b]:
            if position[nxt] > position[b]:
                level[nxt] = max(level[nxt], level[b] + 1)
    back = {pair for pair in weight if position[pair[0]] > position[pair[1]]}
    cycles = sorted((sorted(grp, key=rank.__getitem__) for grp in groups if len(grp) > 1), key=lambda grp: rank[grp[0]])
    return cycles, level, (max(level.values()) + 1 if level else 0), back


def _components(nodes: list[str], succ: dict[str, list[str]]) -> list[list[str]]:
    """Strongly connected groups (Tarjan), written without recursion so a deep repository cannot reach Python's recursion limit."""
    index: dict[str, int] = {}
    low: dict[str, int] = {}
    on_stack: set[str] = set()
    stack: list[str] = []
    out: list[list[str]] = []
    for start in nodes:
        if start in index:
            continue
        index[start] = low[start] = len(index)
        stack.append(start)
        on_stack.add(start)
        work = [(start, iter(succ[start]))]
        while work:
            node, following = work[-1]
            descended = False
            for nxt in following:
                if nxt not in index:
                    index[nxt] = low[nxt] = len(index)
                    stack.append(nxt)
                    on_stack.add(nxt)
                    work.append((nxt, iter(succ[nxt])))
                    descended = True
                    break
                if nxt in on_stack:
                    low[node] = min(low[node], index[nxt])
            if descended:
                continue
            work.pop()
            if work:
                low[work[-1][0]] = min(low[work[-1][0]], low[node])
            if low[node] == index[node]:
                group = []
                while True:
                    member = stack.pop()
                    on_stack.discard(member)
                    group.append(member)
                    if member == node:
                        break
                out.append(group)
    return out


def _notes(boxes: int, measured: bool, unread: list[str]) -> list[str]:
    """Only what the page cannot work out from the numbers: nothing to show, and nothing measured."""
    notes = []
    if boxes == 1:
        notes.append(ONE_PLACE)
    if boxes and not measured:
        notes.append(f"Imports are not measured for any language here ({', '.join(unread)}), so no arrows are drawn.")
    return notes
