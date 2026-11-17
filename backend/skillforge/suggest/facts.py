"""Turn the graph into a short, numbered fact sheet. Facts are computed by code, never by the model."""

from __future__ import annotations

from dataclasses import dataclass, field

from ..graph import query
from ..graph.model import RepoGraph


@dataclass
class Fact:
    id: str  # "F1", "F2", ...
    kind: str
    summary: str
    nodes: list[str] = field(default_factory=list)  # file paths or symbol ids that back the fact


def clean(text: str, limit: int = 160) -> str:
    """Names and paths come from the analysed repository and may be hostile. One line, no markup characters."""
    text = "".join(ch if ch.isprintable() else " " for ch in str(text))
    text = " ".join(text.split())
    return text.replace("<", "(").replace(">", ")").replace("`", "'")[:limit]


def collect_facts(g: RepoGraph, per_kind: int = 6) -> list[Fact]:
    raw: list[tuple[str, str, list[str]]] = []  # (kind, summary, nodes)

    s = query.stats(g)
    langs = ", ".join(f"{k} {v}" for k, v in sorted(s["languages"].items()))
    git = f"{s['commits_read']} commits read" if s["commits_read"] is not None else "no git history"
    raw.append((
        "overview",
        f"{s['files']} files ({s['test_files']} test files), {s['lines']} lines; {langs}; "
        f"{sum(s['symbols'].values())} symbols; {git}.",
        [],
    ))

    hot = query.hotspots(g, per_kind)
    for r in hot["core_symbols"]:
        raw.append((
            "core",
            f"{clean(r['name'])} ({clean(r['file'])}:{r['line']}) is called from {r['fan_in']} distinct places "
            f"by non-test code.",
            [r["id"]],
        ))
    for r in hot["risky_files"]:
        raw.append((
            "risky_file",
            f"{clean(r['path'])} is imported by {r['importers']} files and was changed in {r['commits']} commits.",
            [r["path"]],
        ))

    for grp in query.duplicates(g)["groups"][:per_kind]:
        where = "; ".join(f"{clean(m['name'])} ({clean(m['file'])}:{m['line']})" for m in grp["members"][:4])
        raw.append((
            "duplicate",
            f"{grp['copies']} functions have the same structure (size {grp['size']} syntax nodes): {where}.",
            [m["id"] for m in grp["members"]],
        ))

    dead = query.dead_candidates(g)
    for r in dead["internal"][:per_kind]:
        raw.append((
            "dead_candidate",
            f"CANDIDATE only: {clean(r['name'])} ({clean(r['file'])}:{r['line']}, {r['lines']} lines) is never "
            f"called or referenced inside the repository.",
            [r["id"]],
        ))

    hubs = sorted(
        (p for p, rec in g.files.items() if not rec.is_test),
        key=lambda p: (-len({e.src for e in g.importers_of(p)}), p),
    )
    untested = 0
    for path in hubs[:30]:
        importers = len({e.src for e in g.importers_of(path)})
        if importers < 2 or untested >= per_kind:
            break
        if not query.impact(g, path, depth=2)["tests_tied"]:
            untested += 1
            raw.append((
                "untested_hub",
                f"{clean(path)} is imported by {importers} files but no test file reaches it (proven links only).",
                [path],
            ))

    shown = 0
    for a, b, shared, conf in g.co_change:
        if shown >= per_kind:
            break
        if conf < 0.5 or shared < 3:
            continue
        linked = {e.dst for e in g.imports_of(a)} | {e.dst for e in g.imports_of(b)}
        if a in linked or b in linked:  # one imports the other: that coupling is visible, not hidden
            continue
        shown += 1
        raw.append((
            "hidden_coupling",
            f"{clean(a)} and {clean(b)} changed together in {shared} commits ({int(conf * 100)}%) "
            f"but neither imports the other.",
            [a, b],
        ))

    big = sorted(
        (s_ for s_ in g.symbols.values()
         if s_.kind in ("function", "method") and not g.files[s_.file].is_test),
        key=lambda s_: (-s_.size, s_.id),
    )[:per_kind]
    for sym in big:
        raw.append((
            "large_function",
            f"{clean(sym.qualname)} ({clean(sym.file)}:{sym.line}) is large: {sym.end_line - sym.line + 1} lines, "
            f"{sym.size} syntax nodes, calls {len({e.dst for e in g.callees_of(sym.id)})} other functions.",
            [sym.id],
        ))

    for path, gaps in list(g.gaps.items())[:per_kind]:
        raw.append((
            "import_gap",
            f"{clean(path)} has {len(gaps)} relative import(s) that match no file, e.g. {clean(gaps[0])}.",
            [path],
        ))

    return [Fact(f"F{i}", kind, summary, nodes) for i, (kind, summary, nodes) in enumerate(raw, start=1)]
