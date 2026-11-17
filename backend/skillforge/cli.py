"""Command line.  Run from the backend folder:  python -m skillforge graph <command> <repo> [options]"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from pathlib import Path

from dotenv import load_dotenv

from .build.models import SLOTS, RequirementSpec
from .build.pipeline import BuildError, BuildResult, NeedAnswers, build_skill, rebuild
from .build.requirements import Question
from .graph import query
from .graph.build import build_graph
from .providers import ProviderError, provider_from_env
from .sandbox import probe_sandbox
from .suggest.facts import collect_facts
from .suggest.pipeline import SuggestReport
from .suggest.pipeline import suggest as run_suggest
from .validate import validate_skill_dir

REPO_ROOT = Path(__file__).resolve().parents[2]


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


def _node(g_nodes: list[str], limit: int = 4) -> str:
    shown = ", ".join(g_nodes[:limit])
    return shown + (f" (+{len(g_nodes) - limit} more)" if len(g_nodes) > limit else "")


def _render_facts(facts: list) -> str:
    lines = []
    for f in facts:
        lines.append(f"{f.id:4} [{f.kind}] {f.summary}")
        if f.nodes:
            lines.append(f"       nodes: {_node(f.nodes)}")
    return "\n".join(lines)


def _render_suggestions(r: SuggestReport) -> str:
    lines = [
        f"Suggestions for {r.repo} ({r.provider}/{r.model}): {len(r.suggestions)} kept, {len(r.dropped)} dropped"
        + f", {r.attempts} model call(s)"
    ]
    for i, g in enumerate(r.suggestions, start=1):
        s = g.suggestion
        lines.append(f"\n{i}. [{s.category} | {s.confidence}] {s.title}")
        lines.append(f"   Why:      {s.rationale}")
        lines.append(f"   Evidence: {_node(g.evidence_nodes)}")
        lines.append(f"   Next:     {s.next_step}")
        if s.skill_requirement.strip():
            lines.append(f"   As a skill requirement: {s.skill_requirement}")
        if g.ignored_evidence:
            lines.append(f"   (ignored citations that match nothing: {', '.join(g.ignored_evidence[:3])})")
        if g.unverified_numbers:
            lines.append(f"   (CHECK: numbers not found in the facts: {', '.join(g.unverified_numbers[:5])})")
    if r.dropped:
        lines.append("\nDropped:")
        lines += [f"  - {d.title}: {d.reason}" for d in r.dropped]
    lines += [f"\nnote: {n}" for n in r.notes]
    return "\n".join(lines)


def _run_suggest(args: argparse.Namespace) -> int:
    load_dotenv(REPO_ROOT / ".env")  # real environment variables win over the file
    g = build_graph(args.repo, focus=args.focus, use_cache=not args.no_cache, with_history=not args.no_history)
    if args.facts_only:
        facts = collect_facts(g)
        print(json.dumps([f.__dict__ for f in facts], indent=2) if args.json else _render_facts(facts))
        return 0
    report = run_suggest(
        g, provider_from_env(), max_suggestions=args.max, max_ideas=args.max_ideas, with_ideas=not args.no_ideas
    )
    if args.save:
        Path(args.save).write_text(json.dumps(report.to_dict(), indent=2), encoding="utf-8")
    print(json.dumps(report.to_dict(), indent=2) if args.json else _render_suggestions(report))
    return 0


def _render_spec(spec: RequirementSpec) -> str:
    lines = ["Requirement (in your words, as I understood them):"]
    lines.append(f"  Goal:        {spec.goal}")
    lines.append(f"  Inputs:      {'; '.join(spec.inputs)}")
    lines.append(f"  Outputs:     {'; '.join(spec.outputs)}")
    lines.append(f"  Constraints: {'; '.join(spec.constraints)}")
    for i, c in enumerate(spec.acceptance_criteria, start=1):
        lines.append(f"  Works when ({i}): {c}")
    lines.append(f"  On failure:  {spec.failure_behavior}")
    return "\n".join(lines)


def _render_build(r: BuildResult) -> str:
    ran = [c for c in r.checks if c.status != "not run"]
    failed = [c for c in ran if c.status == "failed"]
    warned = [c for c in ran if c.status == "warning"]
    skipped = [c for c in r.checks if c.status == "not run"]
    head = (
        f"Skill '{r.sdm.name}' written to {r.out_dir}"
        if r.status == "ok"
        else f"DRAFT skill '{r.sdm.name}' written to {r.out_dir}: {len(failed)} check(s) failed"
    )
    counts = f"{len(ran) - len(failed) - len(warned)} passed, "
    counts += f"{len(warned)} warning(s), " if warned else ""
    lines = [head, f"Checks: {counts}{len(failed)} failed, {len(skipped)} not run"]
    lines += [f"  FAILED: {c.name}: {c.detail}" for c in failed]
    lines += [f"  warning: {c.name}: {c.detail}" for c in warned]
    lines += [f"  not run: {c.name}" for c in skipped]
    lines += [f"note: {n}" for n in r.notes]
    lines.append("Read report.md in that folder before using the skill. It lists what was not checked.")
    return "\n".join(lines)


def _need_answers_message(exc: NeedAnswers) -> str:
    lines = ["error: I need more details, and cannot ask here (no terminal). Questions:"]
    lines += [f"  [{q.slot}] {q.text}" for q in exc.questions]
    keys = ", ".join(f'"{q.slot}": "..."' for q in exc.questions)
    lines.append(f"Answer them in a JSON file like {{{keys}}} and run again with --answers FILE.json")
    return "\n".join(lines)


def _make_ask(answers_file: str | None):
    if answers_file:
        data = json.loads(Path(answers_file).read_text(encoding="utf-8"))
        known = {k: str(v) for k, v in data.items() if k in SLOTS}

        def from_file(questions: list[Question]) -> dict[str, str]:
            given = {q.slot: known.get(q.slot, "") for q in questions}
            if not any(given.values()):
                raise NeedAnswers(questions)
            return given

        return from_file

    def interactive(questions: list[Question]) -> dict[str, str]:
        if not sys.stdin.isatty():
            raise NeedAnswers(questions)
        print("\nI need a few more details:")
        return {q.slot: input(f"\n{q.text}\n> ") for q in questions}

    return interactive


def _interactive_approve(spec: RequirementSpec) -> bool:
    if not sys.stdin.isatty():
        raise BuildError("Approval needs a person. Read the requirement above, then run again with --yes.")
    print("\n" + _render_spec(spec))
    return input("\nApprove this requirement and build the skill? [y/N] ").strip().lower() in ("y", "yes")


def _description_from_args(args: argparse.Namespace) -> str:
    if args.from_suggestions:
        data = json.loads(Path(args.from_suggestions).read_text(encoding="utf-8"))
        ideas = [s for s in data.get("suggestions", []) if str(s.get("skill_requirement", "")).strip()]
        if not ideas:
            raise BuildError("That report has no skill or automation idea with a requirement text.")
        if args.pick is None or not 1 <= args.pick <= len(ideas):
            listing = "\n".join(f"  {i}. {s['title']}" for i, s in enumerate(ideas, start=1))
            raise BuildError(f"Choose one idea with --pick N:\n{listing}")
        return ideas[args.pick - 1]["skill_requirement"]
    if not args.description:
        raise BuildError("Give a description, or --from-suggestions REPORT.json --pick N.")
    return args.description


def _sandbox_note() -> str:
    """What the report says about the sandbox on this machine. A failed probe must never stop a build."""
    try:
        s = probe_sandbox()
    except Exception as exc:  # noqa: BLE001
        return f"unknown ({type(exc).__name__})"
    return f"{'available' if s.available else 'unavailable'}. {s.reason}"


def _run_build(args: argparse.Namespace) -> int:
    load_dotenv(REPO_ROOT / ".env")
    description = _description_from_args(args)
    provider = provider_from_env()
    result = build_skill(
        description, provider,
        ask=_make_ask(args.answers),
        approve=(lambda spec: True) if args.yes else _interactive_approve,
        out_root=Path(args.out) if args.out else REPO_ROOT / "generated-skills",
        force=args.force, max_rounds=args.max_rounds, sandbox_note=_sandbox_note(),
    )
    print(_render_build(result))
    return 0 if result.status == "ok" else 1


def _run_render(args: argparse.Namespace) -> int:
    result = rebuild(
        Path(args.sdm), Path(args.out) if args.out else REPO_ROOT / "generated-skills", force=args.force,
        sandbox_note=_sandbox_note(),
    )
    print(_render_build(result))
    return 0 if result.status == "ok" else 1


def _run_validate(args: argparse.Namespace) -> int:
    path = Path(args.folder)
    if not path.is_dir():
        raise NotADirectoryError(f"Not a directory: {path}")
    results = validate_skill_dir(path)
    failed = [c for c in results if c.status == "failed"]
    if args.json:
        print(json.dumps([c.__dict__ for c in results], indent=2))
    else:
        for c in results:
            print(f"{c.status.upper():8} {c.name}" + (f"  ({c.detail})" if c.detail else ""))
        warned = sum(c.status == "warning" for c in results)
        print(f"\n{len(results) - len(failed) - warned} passed, {warned} warning(s), {len(failed)} failed. "
              "Static checks only: nothing was run, and passing is not proof the skill is safe.")
    return 1 if failed else 0


def _run_sandbox_status(args: argparse.Namespace) -> int:
    s = probe_sandbox()
    print(("AVAILABLE: " if s.available else "UNAVAILABLE: ") + s.reason)
    if not s.available:
        print("Scripts will not be run anywhere until a Linux container engine is available. They are never run on this machine directly.")
    return 0 if s.available else 1


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

    sg = area.add_parser("suggest", help="AI ideas for a repository, grounded in its graph (needs a provider key)")
    _add_common(sg)
    sg.add_argument("--max", type=int, default=8, help="most review suggestions to keep")
    sg.add_argument("--max-ideas", type=int, default=3, help="most skill / automation ideas to keep")
    sg.add_argument("--no-ideas", action="store_true", help="skip the second pass that proposes skills and automations")
    sg.add_argument("--facts-only", action="store_true", help="print the facts and stop: no AI, no key")
    sg.add_argument("--save", help="also write the JSON report to this file")

    b = area.add_parser("build", help="turn a requirement into a skill folder (needs a provider key)")
    b.add_argument("description", nargs="?", help="what the skill should do, in plain English")
    b.add_argument("--from-suggestions", metavar="REPORT.json", help="start from a skill idea in a suggest report")
    b.add_argument("--pick", type=int, help="which idea of the report to build (1, 2, ...)")
    b.add_argument("--answers", metavar="FILE.json", help="answers to the follow-up questions, for non-interactive use")
    b.add_argument("--yes", action="store_true", help="approve the requirement without asking")
    b.add_argument("--out", help="where skill folders go (default: generated-skills/ in this repository)")
    b.add_argument("--force", action="store_true", help="replace an existing skill folder")
    b.add_argument("--max-rounds", type=int, default=3, help="most question rounds before giving up")

    r = area.add_parser("render", help="re-render a skill folder from its skill.sdm.json (no AI)")
    r.add_argument("sdm", help="path of a skill.sdm.json")
    r.add_argument("--out", help="where skill folders go (default: generated-skills/ in this repository)")
    r.add_argument("--force", action="store_true", help="replace an existing skill folder")

    v = area.add_parser("validate", help="static safety and structure checks on any skill folder (runs nothing)")
    v.add_argument("folder", help="path of a skill folder (the one with SKILL.md)")
    v.add_argument("--json", action="store_true", help="print machine-readable JSON")

    area.add_parser("sandbox-status", help="is a safe place to run skill scripts available on this machine?")
    return parser


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    args = _parser().parse_args(argv)
    if args.area in ("suggest", "build", "render", "validate", "sandbox-status"):
        handler = {
            "suggest": _run_suggest, "build": _run_build, "render": _run_render,
            "validate": _run_validate, "sandbox-status": _run_sandbox_status,
        }[args.area]
        try:
            return handler(args)
        except NeedAnswers as exc:
            print(_need_answers_message(exc), file=sys.stderr)
            return 2
        except (ProviderError, BuildError, query.QueryError, NotADirectoryError, OSError, ValueError) as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
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
