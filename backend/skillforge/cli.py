"""Command line.  Run from the backend folder:  python -m skillforge graph <command> <repo> [options]"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from .graph import query
from .graph.build import build_graph


def _loc(item: dict[str, Any]) -> str:
    return f"{item['file']}:{item['line']}" if "line" in item else item["file"]


def _render_stats(r: dict[str, Any]) -> str:
    langs = ", ".join(f"{k} {v}" for k, v in sorted(r["languages"].items())) or "none"
    symbols = ", ".join(f"{k} {v}" for k, v in sorted(r["symbols"].items())) or "none"
    edges = ", ".join(f"{k} {v}" for k, v in sorted(r["edges"].items())) or "none"
    calls = r["call_sites"]
    lines = [
        f"Repository: {r['root']}",
        f"Files: {r['files']} ({r['test_files']} tests), {r['lines']} lines. Languages: {langs}",
        f"Symbols: {symbols}",
        f"Edges: {edges}",
        "Call sites: " + ", ".join(f"{k} {v}" for k, v in calls.items()),
        f"Unresolved relative imports: {r['unresolved_imports']}. Files with parse problems: {r['parse_problems']}",
        "Git: " + (f"{r['commits_read']} commits read, {r['co_change_pairs']} co-change pairs"
                   if r["commits_read"] is not None else "not a git repository"),
    ]
    lines += r["notes"]
    return "\n".join(lines)


def _render_symbols(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "No matches."
    return "\n".join(f"{r['kind']:8} {r['name']:40} {_loc(r)}  ({r['lines']} lines)" for r in rows)


def _render_calls(r: dict[str, Any], word: str) -> str:
    t = r["target"]
    lines = [f"{word} of {t['name']} ({_loc(t)}), up to {r['depth']} step(s):"]
    if not r["results"]:
        lines.append("  none found")
    for x in r["results"]:
        flag = "  [guess]" if x["conf"] == "guess" else ""
        lines.append(f"  {'  ' * (x['depth'] - 1)}{x['name']}  {_loc(x)}{flag}")
    lines += [f"note: {n}" for n in r["notes"]]
    return "\n".join(lines)


def _render_impact(r: dict[str, Any]) -> str:
    s, risk = r["subject"], r["risk"]
    lines = [f"Impact of changing {s['kind']} {s['name']}: risk {risk['level'].upper()} (score {risk['score']})"]
    f = risk["factors"]
    lines.append(
        f"  {f['non_test_dependents']} non-test dependent file(s), {f['strong_hidden_coupling']} strongly coupled "
        f"by history, tests tied: {'none' if f['no_test_tied'] else len(r['tests_tied'])}"
    )
    for a in r["dependents"][:25]:
        flag = "  [guess]" if a["conf"] == "guess" else ""
        lines.append(f"  depth {a['depth']}  {a['path']}  via {a['via']}{'  (test)' if a['test'] else ''}{flag}")
    if len(r["dependents"]) > 25:
        lines.append(f"  ... and {len(r['dependents']) - 25} more")
    for h in r["hidden_coupling"][:5]:
        lines.append(f"  changes together: {h['path']}  ({h['shared_commits']} commits, {int(h['confidence'] * 100)}%)")
    lines += [f"note: {n}" for n in r["notes"]]
    return "\n".join(lines)


def _render_path(r: dict[str, Any]) -> str:
    if not r["found"]:
        return f"No {r['kind']} path found."
    names = [p.get("name") or p["path"] for p in r["path"]]
    suffix = "  [includes a name-only guess]" if r["uses_guess"] else ""
    return f"{r['hops']} hop(s) via {r['kind']}:\n  " + "\n  -> ".join(names) + suffix


def _render_hotspots(r: dict[str, Any]) -> str:
    lines = ["Most depended-on code (callers, distinct):"]
    for x in r["core_symbols"]:
        lines.append(f"  {x['fan_in']:3} callers  {x['name']:36} {_loc(x)}")
    lines.append("Risky files (importers x commits):")
    for x in r["risky_files"]:
        lines.append(f"  score {x['score']:4}  {x['path']}  ({x['importers']} importers, {x['commits']} commits)")
    lines.append(f"note: {r['note']}")
    return "\n".join(lines)


def _render_duplicates(r: dict[str, Any]) -> str:
    if not r["groups"]:
        return f"No duplicate functions of {r['min_size']}+ syntax nodes found.\nnote: {r['note']}"
    lines = []
    for grp in r["groups"]:
        where = "across files" if grp["cross_file"] else "in one file"
        lines.append(f"{grp['copies']} copies, size {grp['size']} ({where}):")
        lines += [f"  {m['name']}  {_loc(m)}  ({m['lines']} lines)" for m in grp["members"]]
    lines.append(f"note: {r['note']}")
    return "\n".join(lines)


def _render_dead(r: dict[str, Any]) -> str:
    lines = [f"Internal functions nothing visibly uses ({len(r['internal'])}):"]
    lines += [f"  {x['name']}  {_loc(x)}  ({x['lines']} lines)" for x in r["internal"][:40]]
    lines.append(f"Exported but unused inside this repository ({len(r['exported'])}):")
    lines += [f"  {x['name']}  {_loc(x)}  ({x['lines']} lines)" for x in r["exported"][:40]]
    lines.append(f"note: {r['note']}")
    return "\n".join(lines)


def _add_common(p: argparse.ArgumentParser) -> None:
    p.add_argument("repo", help="path of the repository to analyse")
    p.add_argument("--focus", help="only analyse this folder of the repository")
    p.add_argument("--no-cache", action="store_true", help="do not read or write the parse cache")
    p.add_argument("--no-history", action="store_true", help="do not read git history")
    p.add_argument("--json", action="store_true", help="print machine-readable JSON")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="skillforge", description="SkillForge AI")
    area = parser.add_subparsers(dest="area", required=True)
    graph = area.add_parser("graph", help="understand a repository: functions, calls, imports, impact")
    cmds = graph.add_subparsers(dest="command", required=True)

    p = cmds.add_parser("stats", help="size and shape of the repository graph")
    _add_common(p)
    p = cmds.add_parser("symbols", help="search functions and classes by name or file")
    _add_common(p)
    p.add_argument("text")
    for name, helptext in (("callers", "who calls a function"), ("callees", "what a function calls")):
        p = cmds.add_parser(name, help=helptext)
        _add_common(p)
        p.add_argument("target", help="function name, Class.method, or file::name")
        p.add_argument("--depth", type=int, default=1)
        p.add_argument("--no-guesses", action="store_true", help="leave out name-only matches")
    p = cmds.add_parser("impact", help="what a change to a file or function could reach")
    _add_common(p)
    p.add_argument("target")
    p.add_argument("--depth", type=int, default=3)
    p = cmds.add_parser("path", help="shortest chain of calls (or imports, for two files)")
    _add_common(p)
    p.add_argument("source")
    p.add_argument("dest")
    p = cmds.add_parser("hotspots", help="most depended-on code and risky files")
    _add_common(p)
    p.add_argument("--top", type=int, default=15)
    p = cmds.add_parser("duplicates", help="functions with the same structure")
    _add_common(p)
    p.add_argument("--min-size", type=int, default=query.MIN_CLONE_SIZE)
    p.add_argument("--min-lines", type=int, default=query.MIN_CLONE_LINES)
    p.add_argument("--include-tests", action="store_true")
    p = cmds.add_parser("dead", help="functions nothing visibly uses (candidates)")
    _add_common(p)
    return parser


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    args = _parser().parse_args(argv)
    try:
        g = build_graph(args.repo, focus=args.focus, use_cache=not args.no_cache, with_history=not args.no_history)
        cmd = args.command
        if cmd == "stats":
            result, render = query.stats(g), _render_stats
        elif cmd == "symbols":
            result, render = query.search_symbols(g, args.text), _render_symbols
        elif cmd in ("callers", "callees"):
            fn = query.callers if cmd == "callers" else query.callees
            result = fn(g, args.target, args.depth, include_guesses=not args.no_guesses)
            word = "Callers" if cmd == "callers" else "Callees"
            render = lambda r: _render_calls(r, word)  # noqa: E731
        elif cmd == "impact":
            result, render = query.impact(g, args.target, args.depth), _render_impact
        elif cmd == "path":
            result, render = query.find_path(g, args.source, args.dest), _render_path
        elif cmd == "hotspots":
            result, render = query.hotspots(g, args.top), _render_hotspots
        elif cmd == "duplicates":
            result = query.duplicates(g, args.min_size, args.include_tests, args.min_lines)
            render = _render_duplicates
        else:
            result, render = query.dead_candidates(g), _render_dead
    except (query.QueryError, NotADirectoryError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2) if args.json else render(result))
    return 0
