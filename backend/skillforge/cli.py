"""Command line.  Run from the backend folder:  python -m skillforge graph <command> <repo> [options]"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from dataclasses import asdict
from typing import Any

from pathlib import Path

from dotenv import load_dotenv

from .build.models import SLOTS, RequirementSpec
from .build.pipeline import BuildError, BuildResult, NeedAnswers, build_skill, rebuild, sandbox_note
from .build.requirements import Question
from .conductor import PlanError
from .evaluate import load_files, run_eval
from .evidence import EVIDENCE_FILE, MAX_REFS, STATUSES, RecheckReport, collect, evidence_bytes, fit, safe
from .graph import query
from .graph.build import build_graph
from .library import Library, LibraryError, compare_with_risk, export_skill, import_skill, install_skill, rescan, rollback
from .library.evidence import CiteReport, RefreshReport, cite, evidence_focus, recheck_version, refresh
from .ai import service_from_env
from .ai.doctor import check_models, describe
from .providers import LLMProvider, ProviderError
from .sandbox import probe_sandbox
from .sandbox.docker import _decode as _decode_engine_text
from .sandbox.images import MCP_DOCKERFILE, MCP_IMAGE, MCP_NODE_DOCKERFILE, MCP_NODE_IMAGE, mcp_build_command
from .suggest.facts import collect_facts
from .suggest.pipeline import SuggestReport
from .suggest.pipeline import suggest as run_suggest
from .validate import validate_skill_dir
from .validate.static import read_dir

REPO_ROOT = Path(__file__).resolve().parents[2]


# ---- a repository given as the link of a public GitHub repository (docs/cli-github-links.md) ---------------------------------


class RepoError(Exception):
    """A repository argument that could not be read: a link that is refused, a repository GitHub does not have, GitHub out of reach.
    It is said as one line, `error: ...`, with exit code 2."""


_LINKISH = re.compile(r"^[A-Za-z][A-Za-z0-9+.\-]*://")  # the builder's own check (builder/github.py), repeated here so a folder does not import the builder


def _looks_like_link(text: str) -> bool:
    lowered = text.strip().lower()
    return bool(_LINKISH.match(text.strip())) or lowered.startswith(("github.com/", "www.github.com/")) or lowered in ("github.com", "www.github.com")


# what the page says too, in words: why files of a downloaded repository were left out
_LEFT_OUT = {
    "not_source": ("file in a language or format the graph does not read", "files in languages or formats the graph does not read"),
    "ignored_dir": ("file in a folder such as node_modules", "files in folders such as node_modules"),
    "too_large": ("file over 1 MB", "files over 1 MB"),
    "link": ("link or special file", "links or special files"),
    "unsafe_name": ("file with a name that cannot be written safely", "files with names that cannot be written safely"),
    "duplicate": ("file whose name repeats another's", "files whose names repeat another's"),
    "limit": ("file over the size or count limit", "files over the size or count limit"),
    "path_too_long": ("path too long for this disk", "paths too long for this disk"),
    "unwritable": ("file this disk could not hold", "files this disk could not hold"),
    "unreadable": ("unreadable file", "unreadable files"),
}


def _source_lines(view: dict[str, Any], now: float | None = None) -> list[str]:
    """What a person is told about a repository read from a link: where it came from, how old the copy is, what was left out, and that git
    history is missing. `view` is `builder.repository.source_view(...)` of a link."""
    from datetime import datetime, timezone

    where = f"branch {view['ref']}" if view.get("ref") else "default branch"
    files = view["files"]
    if view["reused"]:
        taken = datetime.strptime(view["fetched_at"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).timestamp()
        minutes = max(0, int(((time.time() if now is None else now) - taken) // 60))
        age = f"a copy from {minutes} minute{'' if minutes == 1 else 's'} ago" if minutes else "a copy from a moment ago"
    else:
        age = "downloaded just now"
    lines = [f"Read {view['owner']}/{view['repo']} from GitHub ({where}): {files} source file{'' if files == 1 else 's'} kept ({view['bytes'] / 1_000_000:.1f} MB), {age}."]
    left = [f"{n} {_LEFT_OUT[reason][0 if n == 1 else 1]}" for reason, n in sorted(view["skipped"].items(), key=lambda kv: list(_LEFT_OUT).index(kv[0]) if kv[0] in _LEFT_OUT else 99) if n]
    if left:
        lines.append("Left out: " + ", ".join(left) + ".")
    lines.append("Nothing was run. Git history is not downloaded, so facts that come from it (how often a file changes) are missing.")
    return lines


def _repo_arg(text: str | None, *, fresh: bool = False, extra: str = "") -> str | None:
    """The folder to read for a repository argument. A folder (or nothing) is returned as it was typed and costs nothing; the link of a public
    GitHub repository is downloaded (the page's own code and limits: `resolve_repo`), a note about it goes to stderr (stdout stays what the command
    prints), and the folder of the copy is returned. `fresh` downloads again instead of reusing a young copy. A link that is refused, or
    GitHub being out of reach, is a `RepoError`."""
    if not text:
        return None
    if not _looks_like_link(text):
        return text
    from .builder.errors import BuilderError
    from .builder.repository import resolve_repo, source_view

    try:
        found = resolve_repo(text, fresh=fresh)
    except BuilderError as exc:
        raise RepoError(str(exc)) from None
    view = source_view(found)
    if view["kind"] != "github":
        return str(found.folder)
    for line in [*_source_lines(view), *([extra] if extra else [])]:
        print(line, file=sys.stderr)
    return str(found.folder)


def _link_label(text: str | None) -> str | None:
    """`owner/repo` (and the branch) for a link, None for a folder: what `graph stats` shows instead of the folder of the downloaded copy."""
    if not text or not _looks_like_link(text):
        return None
    from .builder.errors import BuilderError
    from .builder.github import parse_link

    try:
        link = parse_link(text)
    except BuilderError:
        return None
    return None if link is None else link.name + (f" (branch {link.ref})" if link.ref else "")


def _loc(item: dict[str, Any]) -> str:
    return f"{item['file']}:{item['line']}" if "line" in item else item["file"]


def _render_stats(r: dict[str, Any]) -> str:
    levels = r.get("language_levels", {})
    langs = ", ".join(f"{k} {v} ({levels.get(k, '?')})" for k, v in sorted(r["languages"].items())) or "none"
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


def provider_from_env() -> LLMProvider:
    """The model service for this run. The commands look it up by this name, so a test can replace it."""
    return service_from_env()


def _run_suggest(args: argparse.Namespace) -> int:
    load_dotenv(REPO_ROOT / ".env")  # real environment variables win over the file
    g = build_graph(_repo_arg(args.repo), focus=args.focus, use_cache=not args.no_cache, with_history=not args.no_history)
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


_HOP_WORDS = {
    "confirmed": "the code imports it", "both_ways": "the code imports both ways", "reversed": "the code imports the other way",
    "same_folder": "one folder, so imports cannot tell", "not_measured": "imports are not read for this language", "docs_only": "only the docs say so",
    "step_dropped": "a step between these two could not be checked, so they are not joined",
}
_WHERE = {"in_code": "folder found in the code", "docs_only": "in the docs, not found in the code", "external": "outside this repository"}


def _hop_line(hop: dict[str, Any]) -> str:
    text = _HOP_WORDS[hop["status"]]
    if hop["status"] == "both_ways":
        return f"{text} ({hop['forward']} file pairs one way, {hop['reverse']} the other)"
    if hop["status"] in ("confirmed", "reversed"):
        n = hop["forward"] or hop["reverse"]
        return f"{text} ({n} file pair{'s' if n != 1 else ''}, for example {hop['evidence'][0]['importer']} imports {hop['evidence'][0]['imported']})"
    return text


def _render_guide(r: dict[str, Any]) -> str:
    """The guide as an outline: layers, parts with the quote that proves each, and the routes with what is known about every hop."""
    if r["status"] == "no_docs":
        return "\n".join([f"No README or docs found for {r['name']}.", *r["notes"]])
    lines = [f"How {r['name']} works, read from {', '.join(d['path'] for d in r['docs'])} ({r['provider']}/{r['model']})"]
    if r["status"] == "thin":
        return "\n".join([*lines, "", *r["notes"][:1]])
    named = {p["id"]: p for p in r["parts"]}
    for layer in r["layers"]:
        here = [p for p in r["parts"] if p["layer"] == layer["id"]]
        if not here:
            continue
        lines += ["", layer["label"].upper()]
        for p in here:
            place = _WHERE[p["status"]] + (f": {p['folder']} ({p['files']} file{'s' if p['files'] != 1 else ''})" if p["status"] == "in_code" else "")
            lines += [f"  {p['name']}: {p['summary']}", f"      {place}", f"      docs say: \"{p['quote']['text']}\" ({p['quote']['source']}:{p['quote']['line']})"]
            if not p["quote"]["on_topic"]:
                lines.append("      (the quote does not mention this part)")
            if p["read_first"]["files"]:
                lines.append("      read first: " + ", ".join(f["path"] for f in p["read_first"]["files"][:2]))
    for j in r["journeys"]:
        lines += ["", f"JOURNEY: {j['title']}"]
        for i, s in enumerate(j["steps"]):
            lines.append(f"  {i + 1}. {named[s['part']]['name']}: {s['does']}")
            if i < len(j["hops"]):
                lines.append(f"       -> {_hop_line(j['hops'][i])}")
    if r["dropped"]:
        lines += ["", f"{len(r['dropped'])} item(s) were dropped: the quote was not in the docs, or a limit was reached."]
    return "\n".join([*lines, "", *r["notes"]])


def _run_guide(args: argparse.Namespace) -> int:
    load_dotenv(REPO_ROOT / ".env")  # real environment variables win over the file
    from .builder.errors import BuilderError
    from .builder.guides import guide_repo

    try:
        answer = guide_repo(args.repo, args.focus, lambda: provider_from_env())  # looked up by name when called, so a test can replace it
    except BuilderError as exc:
        raise RepoError(str(exc)) from None
    if answer["source"]["kind"] == "github":
        for line in _source_lines(answer["source"]):
            print(line, file=sys.stderr)
    print(json.dumps(answer, indent=2) if args.json else _render_guide(answer))
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
    if r.status == "ok":
        head = f"Skill '{r.sdm.name}' written to {r.out_dir}"
    elif failed:
        head = f"DRAFT skill '{r.sdm.name}' written to {r.out_dir}: {len(failed)} check(s) failed"
    else:
        head = f"DRAFT skill '{r.sdm.name}' written to {r.out_dir}: its scripts were not all run in the sandbox"
    counts = f"{len(ran) - len(failed) - len(warned)} passed, "
    counts += f"{len(warned)} warning(s), " if warned else ""
    lines = [head, f"Checks: {counts}{len(failed)} failed, {len(skipped)} not run"]
    lines += [f"  FAILED: {c.name}: {c.detail}" for c in failed]
    lines += [f"  warning: {c.name}: {c.detail}" for c in warned]
    lines += [f"  not run: {c.name}" + (f" ({c.detail})" if c.name.startswith("script test") else "") for c in skipped]
    if r.sdm.scripts:
        ran_cases = [c for c in ran if c.name.startswith("script test: ")]
        lines.append(
            f"Scripts: {len(r.sdm.scripts)} written, {sum(c.status == 'passed' for c in ran_cases)} of "
            f"{len(r.sdm.script_cases)} case(s) passed in the sandbox"
        )
    if r.draft_reason:
        lines.append(f"  {r.draft_reason}")
    if r.tokens:
        lines.append(
            f"Cost to use (estimate): about {r.tokens.always} tokens always loaded (name and description), "
            f"{r.tokens.when_used} more when the agent uses the skill."
        )
    if r.evaluation is not None:
        lines.append("Test cases run against the model: " + r.evaluation.verdict())
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


def _chosen_idea(args: argparse.Namespace) -> dict | None:
    """The idea of the suggest report that --pick chose (the description step has already checked the choice), or None."""
    if not args.from_suggestions:
        return None
    data = json.loads(Path(args.from_suggestions).read_text(encoding="utf-8"))
    ideas = [s for s in data.get("suggestions", []) if str(s.get("skill_requirement", "")).strip()]
    return ideas[args.pick - 1] if args.pick and 1 <= args.pick <= len(ideas) else None


def _evidence_lines(args: argparse.Namespace, idea: dict | None, graph, out_dir: Path) -> list[str]:
    """Record the chosen idea's cited places as the new skill's evidence (the facts the graph has now), and say what happened."""
    if idea is None:
        return ["note: --repo only applies to --from-suggestions, so nothing was cited."] if args.repo else []
    nodes = [n for n in idea.get("evidence_nodes", []) if isinstance(n, str)]
    if not nodes:
        return []
    if graph is None:
        return [
            f"Evidence was not recorded: the idea cites {len(nodes)} place(s) in the repository. "
            f"Give --repo PATH to record them with the facts the graph has, so `library recheck` can say later what changed."
        ]
    got = collect(graph, nodes[:MAX_REFS], focus=args.focus or None)
    ev, too_big = fit(got.evidence)  # nothing is written that the next import would refuse for its size
    lines = []
    if ev.refs:
        (out_dir / EVIDENCE_FILE).write_bytes(evidence_bytes(ev))
        lines.append(
            f"Evidence: the skill cites {len(ev.refs)} place(s) in '{safe(ev.repo)}' ({EVIDENCE_FILE} in its folder). "
            f"After importing it, `library recheck NAME --repo PATH` says what changed in that code."
        )
    lines += [f"  not in the graph, so not recorded: {safe(text)}" for text, _ in got.skipped]
    if len(nodes) > MAX_REFS:
        lines.append(f"  only the first {MAX_REFS} of {len(nodes)} places were recorded.")
    if too_big:
        lines.append(f"  only the first {len(ev.refs)} of the places were recorded: the file would be too large to read back ({too_big} left out).")
    return lines


def _sandbox_note() -> str:
    """What the report says about the sandbox on this machine. A failed probe must never stop a build."""
    return sandbox_note(probe_sandbox)  # looked up here, so a test can replace cli.probe_sandbox


def _run_build(args: argparse.Namespace) -> int:
    load_dotenv(REPO_ROOT / ".env")
    description = _description_from_args(args)
    idea = _chosen_idea(args)
    graph = build_graph(_repo_arg(args.repo), focus=args.focus, with_history=False) if args.repo and idea is not None else None  # a bad path or link stops here, before a model is asked
    provider = provider_from_env()
    result = build_skill(
        description, provider,
        ask=_make_ask(args.answers),
        approve=(lambda spec: True) if args.yes else _interactive_approve,
        out_root=Path(args.out) if args.out else REPO_ROOT / "generated-skills",
        force=args.force, max_rounds=args.max_rounds, sandbox_note=_sandbox_note(), with_scripts=args.scripts,
        evaluate=args.eval, eval_runs=args.eval_runs,
    )
    print(_render_build(result))
    for line in _evidence_lines(args, idea, graph, Path(result.out_dir)):
        print(line)
    return 0 if result.status == "ok" else 1


def _render_eval(report) -> str:
    if not report.runnable or not report.cases:
        return report.verdict() + "".join(f"\n  skipped {s}" for s in report.skipped)
    lines = [f"Skill '{report.skill}' (about {report.skill_tokens} tokens each time it is used): {len(report.cases)} test case(s) run, {report.calls} model call(s)"]
    for c in report.cases:
        base = f", without it {c.baseline.passed}/{c.baseline.runs}" if c.baseline else ""
        lines.append(f"  [{c.kind}] {c.name}: with the skill {c.with_skill.passed}/{c.with_skill.runs}{base}")
        lines += [f"      with the skill: {f}" for f in c.with_skill.failures()]
        if c.baseline:
            lines += [f"      without it: {f}" for f in c.baseline.failures()]
    lines += [f"  skipped {s}" for s in report.skipped]
    lines.append(report.verdict())
    return "\n".join(lines)


def _run_eval(args: argparse.Namespace) -> int:
    load_dotenv(REPO_ROOT / ".env")
    if bool(args.folder) == bool(args.library):
        raise ValueError("Give either a skill folder or --library NAME.")
    if args.library:
        _, files = Library().read(args.library, args.version)
    else:
        path = Path(args.folder)
        if not path.is_dir():
            raise NotADirectoryError(f"Not a directory: {path}")
        files, problems = read_dir(path)
        if problems:
            raise ValueError(f"The folder cannot be read safely: {problems[0][1]}")
    skill = load_files(files)
    report = run_eval(provider_from_env(), skill, baseline=not args.no_baseline, runs=args.runs)
    if args.json:
        print(json.dumps(asdict(report) | {"verdict": report.verdict()}, indent=2))
    else:
        print(_render_eval(report))
    if not report.runnable or not report.cases:
        return 2
    return 0 if all(c.with_skill.passed == c.with_skill.runs for c in report.cases) else 1


def _canary_files(args: argparse.Namespace) -> dict:
    """The files of the skill or agent to scan: a folder, or a library entry."""
    if bool(args.folder) == bool(args.library):
        raise ValueError("Give either a skill folder or --library NAME.")
    if args.library:
        return Library(kind=args.kind).read(args.library, args.version)[1]
    path = Path(args.folder)
    if not path.is_dir():
        raise NotADirectoryError(f"Not a directory: {path}")
    files, problems = read_dir(path)
    if problems:
        raise ValueError(f"The folder cannot be read safely: {problems[0][1]}")
    return files


def _run_canary_measure(args: argparse.Namespace) -> int:
    """Scan the built-in corpus of known-bad and known-good skills and set the result beside what the static checks say."""
    from .canary.corpus import CORPUS, measure
    from .canary.render import render_measurement

    if args.folder or args.library:
        raise ValueError("--measure scans the built-in corpus: give it no skill folder and no --library.")
    corpus = tuple(CORPUS)
    if args.only:
        known = {s.name: s for s in CORPUS}
        unknown = [name for name in args.only if name not in known]
        if unknown:
            raise ValueError(f"No such corpus skill: {', '.join(unknown)}. Choose from: {', '.join(known)}.")
        corpus = tuple(known[name] for name in args.only)
    runs, cap = min(max(1, args.runs), 5), min(max(1, args.scenarios or 4), 8)
    print(
        f"Measuring the behaviour scan on {len(corpus)} skill(s) of the built-in corpus, {cap} task(s) each. The skills were written by the author of the scan, "
        "so the numbers are optimistic. The tools are fake and nothing real is touched.",
        file=sys.stderr,
    )
    result = measure(
        provider_from_env(), corpus, runs=runs, max_scenarios=cap, control=not args.no_control,
        on_skill=lambda done, total, name: print(f"  [{done}/{total}] {name}", file=sys.stderr),
    )
    print(json.dumps(result.to_dict(), indent=2) if args.json else render_measurement(result))
    return 2 if result.summary()["not_run"] == len(result.results) else 0


def _run_canary(args: argparse.Namespace) -> int:
    from .canary.instructions import load_instructions  # only this command needs the scan, so no other command pays for loading it
    from .canary.render import render_report
    from .canary.runner import preview, run_canary

    load_dotenv(REPO_ROOT / ".env")
    if args.measure:
        return _run_canary_measure(args)
    instructions = load_instructions(_canary_files(args))
    runs, cap, control = min(max(1, args.runs), 5), min(max(1, args.scenarios or 5), 8), not args.no_control
    plan = preview(instructions, runs=runs, max_scenarios=cap, control=control)
    n = len(plan.scenarios)
    print(
        f"Behaviour scan of {instructions.kind} '{instructions.name}': {n} task(s) x {runs} run(s), at most {plan.max_calls} model calls "
        f"(usually about {n * runs * 3}). The tools are fake and nothing real is touched.",
        file=sys.stderr,
    )
    report = run_canary(
        provider_from_env(), instructions, runs=runs, max_scenarios=cap, control=control, draft=not args.no_draft,
        on_scenario=lambda done, total: print(f"  [{done}/{total}] task run finished", file=sys.stderr),
    )
    print(json.dumps(report.to_dict(), indent=2) if args.json else render_report(report))
    return {"nothing_observed": 0, "flagged": 1, "unclear": 1, "caution": 1}.get(report.outcome(), 2)


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


def _run_languages(args: argparse.Namespace) -> int:
    from .graph import languages

    names = sorted(set(languages.EXTENSIONS.values()), key=lambda n: (["full", "standard", "basic"].index(languages.level_of(n)), n))
    if args.download or args.download_all:
        wanted = [n for n in names if args.download_all or languages.level_of(n) == "standard"]
        for n in wanted:
            parser, why = languages.get_parser(n)
            print(f"{'ok  ' if parser else 'FAIL'} {n}" + ("" if parser else f": {why}"))
        print()
    print(f"{'LEVEL':9} {'LANGUAGE':12} {'GRAMMAR':28} EXTENSIONS")
    for n in names:
        info = languages.info(n)
        print(f"{info.level:9} {n:12} {languages.grammar_status(n):28} {' '.join(info.extensions)}")
    print(
        "\nfull: imports and calls resolved by scope. standard: functions, classes, imports and calls, links labelled\n"
        "resolved or guess. basic: definitions and duplicate detection only. Other file types are not parsed.\n"
        "Grammars other than Python/TypeScript/JavaScript download on first use (SKILLFORGE_OFFLINE=1 forbids it)."
    )
    return 0


def _run_plan(args: argparse.Namespace) -> int:
    from .conductor import PlanError, make_plan, render_markdown  # noqa: F401  (PlanError is caught in main)

    if args.prompt and args.file:
        raise ValueError("Give the task as text or with --file, not both.")
    text = Path(args.file).read_text(encoding="utf-8") if args.file else args.prompt
    if not text:
        raise ValueError("Give the task in words, or with --file FILE.")
    # a copy of a GitHub repository holds only source files: its CLAUDE.md and AGENTS.md are not in it, and the plan must say so
    folder = _repo_arg(args.repo, extra="CLAUDE.md and AGENTS.md are not downloaded, so the rules they hold are not read.")
    provider = None
    if not args.no_ai:
        load_dotenv(REPO_ROOT / ".env")  # real environment variables win over the file
        provider = provider_from_env()
        print(
            "Sent to the model: your task text" + (", the names and places (not the contents) of the files and functions it mentions, "
            "file and language counts, and the lines of the repository's CLAUDE.md / AGENTS.md." if args.repo else ".")
            + " Use --no-ai to send nothing.", file=sys.stderr,
        )
    plan = make_plan(
        text, provider=provider, repo=folder, task_type=args.type, tier=args.tier, allow_lower=args.allow_lower,
        budget=args.budget, sensitive=tuple(args.sensitive or ()),
    )
    out = json.dumps(plan.model_dump(), indent=2) if args.json else render_markdown(plan)
    if args.save:
        Path(args.save).write_text(out, encoding="utf-8", newline="\n")
        print(f"Saved to {args.save}", file=sys.stderr)
    print(out)
    return 0


def _run_serve(args: argparse.Namespace) -> int:
    import uvicorn  # only needed here, so the other commands never import the web server

    from .api import create_app
    from .api.builds import builder_options
    from .api.hosted import Hosted, HostedConfigError
    from .builder import Builder

    try:
        hosted = Hosted.from_env(os.environ)
    except HostedConfigError as exc:
        raise ValueError(str(exc)) from exc
    if args.host not in ("127.0.0.1", "localhost", "::1") and hosted is None:
        raise ValueError(
            f"Listening on {args.host} would let other machines reach an API that has no sign-in. "
            "Set SKILLFORGE_MODE=hosted and SKILLFORGE_ACCESS_TOKEN first (docs/hosting.md), or leave --host out."
        )
    library = Library()
    # Opens and migrates the database now, and marks work a crash left half-done. The model options are what a hosted server lets its people do about models
    # (keep a key of their own, share the server's model up to a daily cap): without them Settings -> My model answers "cannot keep personal model keys".
    builder = Builder.default(library, **builder_options(hosted))
    if hosted is None:
        print(f"SkillForge API on http://{args.host}:{args.port}/api/docs  (this machine only; Ctrl+C stops it)")
    else:
        print(f"SkillForge API (hosted version: sign-in required) on {args.host}:{args.port}  (Ctrl+C stops it)")
    uvicorn.run(create_app(library, builder=builder, hosted=hosted), host=args.host, port=args.port, log_level="info")
    return 0


def _render_models(info: dict, checks: list[dict] | None) -> str:
    lines = ["Models set up", f"  default        {info['default']['provider']} / {info['default']['model']}"]
    for t in info["tiers"]:
        if (t["provider"], t["model"]) != (info["default"]["provider"], info["default"]["model"]):
            lines.append(f"  {t['tier'] + ' tier':<14} {t['provider']} / {t['model']}")
    for f in info["fallbacks"]:
        lines.append(f"  {'backup':<14} {f['provider']} / {f['model']}   (asked when the one before cannot answer)")
    if info["escalation"]:
        lines.append(f"  {'stronger':<14} {info['escalation']['provider']} / {info['escalation']['model']}   (asked once if a design still fails its checks)")
    lines.append("Keys found for: " + (", ".join(info["keys_present"]) or "none"))
    lines += [f"  note: {u['hint']}" for u in info["unused"]]
    if checks is not None:
        lines.append("Checks (one tiny call each):")
        for c in checks:
            who = f"{c['provider']}/{c['model']}"
            if c["ok"]:
                tokens = f"{c['input_tokens']} in / {c['output_tokens']} out" if c["input_tokens"] is not None else "no token counts"
                lines.append(f"  OK      {who}  ({', '.join(c['roles'])})  {c['latency_ms'] / 1000:.1f} s, {tokens}")
            else:
                lines.append(f"  FAILED  {who}  ({', '.join(c['roles'])})  {c['kind']}: {c['detail']}")
    return "\n".join(lines)


def _run_models(args: argparse.Namespace) -> int:
    load_dotenv(REPO_ROOT / ".env")  # real environment variables win over the file
    service = provider_from_env()
    info = describe(service, os.environ)
    checks = check_models(service) if args.test else None
    print(json.dumps({**info, "checks": checks}, indent=2) if args.json else _render_models(info, checks))
    return 0 if checks is None or all(c["ok"] for c in checks) else 1


def _run_sandbox_status(args: argparse.Namespace) -> int:
    s = probe_sandbox()
    print(("AVAILABLE: " if s.available else "UNAVAILABLE: ") + s.reason)
    if not s.available:
        print("Scripts will not be run anywhere until a Linux container engine is available. They are never run on this machine directly.")
    return 0 if s.available else 1


def _build_image(image: str, dockerfile: str, base: str) -> int:
    s = probe_sandbox()
    if not s.available:
        print("UNAVAILABLE: " + s.reason)
        print("The image is built with Docker, so a Linux container engine is needed first (docs/sandbox-wsl.md).")
        return 1
    print(f"Building {image} from {base} and the pinned SDK (one time, needs a network; this can take a minute)...")
    done = subprocess.run(mcp_build_command(s, image), input=dockerfile.encode("utf-8"), capture_output=True, timeout=900)
    shown = [ln for text in (done.stdout, done.stderr) for ln in _decode_engine_text(text).splitlines() if ln.strip()]
    for line in shown[-8:]:
        print(line)
    print(f"{image} is ready." if done.returncode == 0 else f"The build failed (exit code {done.returncode}).")
    return done.returncode


def _run_sandbox_build_mcp(args: argparse.Namespace) -> int:
    """Build the one image that Python MCP servers are tested in. Needs a network, once; testing a server never builds or pulls anything."""
    return _build_image(MCP_IMAGE, MCP_DOCKERFILE, "python:3.13-slim")


def _run_sandbox_build_mcp_node(args: argparse.Namespace) -> int:
    """Build the one image that Node (TypeScript) MCP servers are tested in. Same rules as the Python one."""
    return _build_image(MCP_NODE_IMAGE, MCP_NODE_DOCKERFILE, "node:24-slim")


def _when(stamp: str) -> str:
    return stamp[:16].replace("T", " ")


def _render_check_lines(checks: list) -> list[str]:
    lines = [f"  FAILED: {c.name}: {c.detail}" for c in checks if c.status == "failed"]
    lines += [f"  warning: {c.name}: {c.detail}" for c in checks if c.status == "warning"]
    lines += [f"  not run: {c.name}" + (f" ({c.detail})" if c.detail else "") for c in checks if c.status == "not run"]
    return lines


def _render_changes(changes: list, with_text: bool) -> list[str]:
    lines = []
    for c in changes:
        lines.append(f"  {c.status:8} {c.path}" + ("  (binary)" if c.binary else ""))
        if with_text and c.text:
            lines += ["    " + t for t in c.text.splitlines()]
    return lines


_RISK_HEADLINE = {
    "more_risk": "MORE RISK", "look": "worth a look", "less_risk": "less risk",
    "no_new_risk": "no new risk found by these checks",
}


def _render_risk(risk) -> list[str]:
    """What got riskier between two versions (library/risk.py), in words, riskiest first."""
    counts = f"{risk.count('riskier')} riskier, {risk.count('look')} to look at, {risk.count('safer')} safer"
    lines = [f"Risk {risk.older} -> {risk.newer}: {_RISK_HEADLINE[risk.level]} ({counts})"]
    lines += [f"  {c.direction + ':':8} {c.detail}" for c in risk.changes]
    return lines + [f"  {risk.note}"]


def _render_rescan(scans: list) -> str:
    if not scans:
        return "No skills yet. Add one with: library import <folder or .zip>"
    lines = [f"Checked {len(scans)} stored version(s) again with today's checks. Nothing was changed, and nothing was run."]
    for s in scans:
        label = f"{s.name} {s.tag}".strip()
        if s.status == "damaged":
            lines.append(f"  {label:34} DAMAGED: {s.message}")
            continue
        lines.append(f"  {label:34} {s.status.upper() if s.status != 'same' else 'same'}")
        for f in s.findings:
            was = "did not exist at import" if f.was == "found now" else f"was {f.was} at import"
            lines.append(f"      {'FAILED' if f.status == 'failed' else 'warning'}: {f.name} ({was})" + (f": {f.detail}" if f.detail else ""))
    tally = {k: sum(s.status == k for s in scans) for k in ("same", "worse", "failing", "damaged")}
    lines.append("Result: " + ", ".join(f"{n} {k}" for k, n in tally.items()))
    if tally["failing"]:
        lines.append("A failing version would be refused if imported today, and export and install refuse it. Import a fixed version.")
    lines.append("Static checks only: passing is not proof that a skill is safe.")
    return "\n".join(lines)


def _render_import(r) -> str:
    ran = [c for c in r.checks if c.status != "not run"]
    failed = [c for c in ran if c.status == "failed"]
    warned = [c for c in ran if c.status == "warning"]
    counts = f"{len(ran) - len(failed) - len(warned)} passed, {len(warned)} warning(s), {len(failed)} failed, {len(r.checks) - len(ran)} not run"
    if r.refused:
        lines = [f"Refused: nothing was added to the library. Checks: {counts}"]
        if r.name is None and not failed:
            lines.append("  FAILED: SKILL.md has no usable name")
        return "\n".join(lines + _render_check_lines(r.checks))
    v = r.version
    if not r.created:
        head = f"Unchanged: '{r.name}' is identical to {v.tag} in the library, so no new version was made."
    elif r.previous is None:
        head = f"Imported '{r.name}' as {v.tag} (first version)."
    else:
        head = f"Imported '{r.name}' as {v.tag} (new version after {r.previous.tag}; {len(r.changes)} file(s) differ)."
    lines = [head, f"Checks: {counts}", *_render_check_lines(r.checks)]
    if r.created and r.risk is not None:
        lines += _render_risk(r.risk)
    if r.created and r.changes:
        lines += ["Changes since " + r.previous.tag + ":", *_render_changes(r.changes, with_text=False)]
    lines.append("Static checks only: nothing was run unless a line above says so, and passing is not proof the skill is safe.")
    return "\n".join(lines)


def _render_cite(r: CiteReport, repo_arg: str) -> str:
    head = f"Recorded {len(r.added)} place(s) as evidence of '{r.name}' ({r.version.tag}, from '{r.evidence.repo}')." if r.created else (
        f"Nothing new: those places were already recorded for '{r.name}', so no new version was made."
    )
    lines = [head]
    lines += [f"  + {i}" for i in r.added]
    if r.kept:
        lines.append(f"  already recorded, facts left as they were (use `library refresh` to record today's): {', '.join(r.kept)}")
    lines += [f"Not recorded: {text} ({why})" for text, why in r.skipped]
    lines += [
        f"Could mean more than one place, so none was chosen: {text} -> {', '.join(options)} (use --ref FILE::NAME)"
        for text, options in r.ambiguous
    ]
    lines.append(f"Later, `library recheck {r.name} --repo {repo_arg}` says what changed in the code these places name.")
    return "\n".join(lines)


def _render_recheck(r: RecheckReport) -> str:
    return "\n".join(safe(line) for line in _recheck_lines(r).split("\n"))  # names from a repository are never shown raw


def _recheck_lines(r: RecheckReport) -> str:
    when = f"recorded {r.taken_at[:10]}" + (f" at commit {r.recorded_commit}" if r.recorded_commit else "") + (
        " plus uncommitted changes" if r.recorded_commit and r.recorded_dirty else "")
    now = f"; the repository is now at commit {r.current_commit}" + (" plus uncommitted changes" if r.current_dirty else "") if (
        r.current_commit and (r.current_commit != r.recorded_commit or r.current_dirty != r.recorded_dirty)) else ""
    lines = [f"{r.skill} {r.version}: {len(r.findings)} place(s) cited from '{r.repo}' ({when}{now})"]
    lines.append("Result: " + ", ".join(f"{n} {s}" for s, n in r.counts.items()) if r.counts else "Result: nothing is cited")
    for status in STATUSES[:-1]:
        for f in (x for x in r.findings if x.status == status):
            lines.append(f"  {status.upper():8} {f.ref}" + (f"   (recorded {f.recorded})" if f.recorded else ""))
            lines += [f"      - {d}" for d in f.details]
            if f.candidates and len(f.candidates) > 1:
                lines.append(f"      places that look like it: {', '.join(f.candidates)}")
            lines += [f"      not compared: {n}" for n in f.not_measured]
    holding = [f for f in r.findings if f.status == "holds"]
    if holding:
        lines.append("  holds: " + ", ".join(f.ref for f in holding))
        lines += [f"      {f.ref}: not compared: {n}" for f in holding for n in f.not_measured]
    lines += [f"note: {n}" for n in r.notes]
    lines.append(r.limits)
    return "\n".join(lines)


def _render_refresh(r: RefreshReport, repo_arg: str) -> str:
    lines = []
    if r.created:
        lines.append(f"Recorded today's facts for '{r.name}' as {r.version.tag}: {len(r.updated)} updated, {len(r.unchanged)} unchanged.")
        lines += [f"  updated: {i}" for i in r.updated]
    else:
        lines.append(f"Nothing changed: every place that still exists has the facts that were recorded, so no new version was made.")
    if r.dropped:
        lines.append(f"Dropped (they were gone): {', '.join(r.dropped)}")
    if r.kept_missing:
        lines.append(
            f"Gone from the repository, still recorded and still flagged by `library recheck`: {', '.join(r.kept_missing)}. "
            f"After you have updated the skill, `library refresh {r.name} --repo {repo_arg} --drop-missing` removes them."
        )
    lines.append("Refresh records today's facts as the new baseline: do it after you have read the skill against the changed code.")
    return "\n".join(lines)


def _focus_of(args: argparse.Namespace, lib: Library, version: int | None = None) -> str | None:
    """The folder to read: the one asked for (an empty one clears it), else the one the evidence was recorded with, so everything
    recorded together is read the same way."""
    return args.focus if args.focus is not None else evidence_focus(lib, args.name, version)


def _run_evidence(args: argparse.Namespace, lib: Library) -> int:
    cmd = args.command
    if cmd == "cite":
        if not args.ref and not args.from_text:
            raise LibraryError("Say what to cite: --ref FILE_OR_FUNCTION (repeat it for more places) or --from-text (the places the skill's own text names).")
        focus = _focus_of(args, lib)
        g = build_graph(_repo_arg(args.repo, fresh=True), focus=focus or None, with_history=False)  # fresh: what is cited is the code as it is now
        print(_render_cite(cite(lib, args.name, g, args.ref or [], from_text=args.from_text, focus=focus or None, note=args.note or ""), args.repo))
        return 0
    if cmd == "recheck":
        focus = _focus_of(args, lib, args.version)
        g = build_graph(_repo_arg(args.repo, fresh=True), focus=focus or None, with_history=False)  # fresh: what changed is the point
        report = recheck_version(lib, args.name, g, args.version, focus=focus or None)
        if args.json:
            print(json.dumps(report.to_dict(), indent=2))
        else:
            print(_render_recheck(report))
        return 0 if report.ok else 1
    focus = _focus_of(args, lib)
    g = build_graph(_repo_arg(args.repo, fresh=True), focus=focus or None, with_history=False)  # fresh: today's facts are recorded
    print(_render_refresh(refresh(lib, args.name, g, drop_missing=args.drop_missing, focus=focus or "", note=args.note or ""), args.repo))
    return 0


def _run_library(args: argparse.Namespace) -> int:
    lib = Library()
    cmd = args.command
    if cmd in ("cite", "recheck", "refresh"):
        return _run_evidence(args, lib)
    if cmd == "import":
        report = import_skill(Path(args.source), lib, test_scripts=args.test_scripts, note=args.note or "")
        print(_render_import(report))
        return 1 if report.refused else 0
    if cmd == "list":
        names = lib.names()
        print(f"Library: {lib.root}")
        if not names:
            print("No skills yet. Add one with: library import <folder or .zip>")
        for name in names:
            try:
                versions = lib.versions(name)
                latest = versions[-1]
                print(f"  {name:30} {latest.tag:5} {len(versions)} version(s), updated {_when(latest.created_at)}")
            except (LibraryError, IndexError) as exc:
                print(f"  {name:30} DAMAGED: {exc}")
        return 0
    if cmd == "versions":
        versions = lib.versions(args.name)
        if not versions:
            raise LibraryError(f"There is no skill named '{args.name}' in the library.")
        for v in reversed(versions):
            extra = f"  skill version {v.skill_version}" if v.skill_version else ""
            note = f"  \"{v.note}\"" if v.note else ""
            print(
                f"{v.tag:5} {_when(v.created_at)}  from {v.source_kind} {v.source_label}{extra}{note}\n"
                f"      {len(v.files)} file(s), content {v.content_hash[:12]}; checks: {v.count('passed')} passed, "
                f"{v.count('warning')} warning(s), {v.count('failed')} failed, {v.count('not run')} not run"
            )
        return 0
    if cmd == "diff":
        c = compare_with_risk(lib, args.name, args.frm, args.to)
        print(f"{args.name}: {c.older.tag} -> {c.newer.tag}: " + (f"{len(c.changes)} file(s) differ" if c.changes else "identical"))
        if c.changes:
            print("\n".join(_render_risk(c.risk)))
        print("\n".join(_render_changes(c.changes, with_text=True)))
        return 0
    if cmd == "rescan":
        scans = rescan(lib, args.name, args.version)
        print(_render_rescan(scans))
        return 1 if any(s.status in ("failing", "damaged") for s in scans) else 0
    if cmd == "rollback":
        version, created = rollback(lib, args.name, args.to)
        if created:
            print(f"Restored: '{args.name}' is now {version.tag}, with the content of v{args.to}. Older versions are kept.")
        else:
            print(f"Nothing to do: the latest version of '{args.name}' already has the content of v{args.to}.")
        return 0
    if cmd == "export":
        r = export_skill(
            lib, args.name, args.version, Path(args.out) if args.out else None, without_spec=args.without_spec,
            without_evidence=args.without_evidence, force=args.force,
        )
        print(f"Exported '{args.name}' {r.version.tag} ({r.files} file(s)) to {r.path}")
        if r.dropped:
            print(f"Left out on request: {', '.join(r.dropped)}")
        if "spec.json" in r.version.files and "spec.json" not in r.dropped:
            print("It includes spec.json, which holds the words of the person who asked for the skill. Use --without-spec to leave it out.")
        if EVIDENCE_FILE in r.version.files and EVIDENCE_FILE not in r.dropped:
            print(f"It includes {EVIDENCE_FILE}, which names the files and functions of the repository the skill cites. Use --without-evidence to leave it out.")
        if r.has_scripts:
            print("This skill has scripts. Whoever uses it should read them first: an agent runs them on that machine, not in a sandbox.")
        return 0
    # install
    skills_dir = Path.home() / ".claude" / "skills" if args.personal else Path.cwd() / ".claude" / "skills" if args.project else Path(args.to)
    r = install_skill(lib, args.name, args.version, skills_dir, force=args.force)
    print(f"Installed '{args.name}' {r.version.tag} to {r.path}")
    if r.left_out:
        print(f"{', '.join(r.left_out)} stays in the library: it names the files and functions of the repository the skill cites.")
    if r.backup:
        print(f"The folder that was there was copied to {r.backup} first.")
    if r.has_scripts:
        print("This skill has scripts. When an agent uses it they run on this machine, not in the sandbox. Read them first.")
    return 0


def _add_common(p: argparse.ArgumentParser) -> None:
    p.add_argument("repo", help="path of the repository to analyse, or the link of a public GitHub repository (https://github.com/owner/repo)")
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

    gd = area.add_parser("guide", help="how a project works, read from its README and docs: parts, layers and routes, each checked (needs a provider key)")
    gd.add_argument("repo", help="path of the repository, or the link of a public GitHub repository (https://github.com/owner/repo)")
    gd.add_argument("--focus", help="only this folder of the repository")
    gd.add_argument("--json", action="store_true", help="print machine-readable JSON")

    b = area.add_parser("build", help="turn a requirement into a skill folder (needs a provider key)")
    b.add_argument("description", nargs="?", help="what the skill should do, in plain English")
    b.add_argument("--from-suggestions", metavar="REPORT.json", help="start from a skill idea in a suggest report")
    b.add_argument("--pick", type=int, help="which idea of the report to build (1, 2, ...)")
    b.add_argument("--answers", metavar="FILE.json", help="answers to the follow-up questions, for non-interactive use")
    b.add_argument("--yes", action="store_true", help="approve the requirement without asking")
    b.add_argument("--out", help="where skill folders go (default: generated-skills/ in this repository)")
    b.add_argument("--force", action="store_true", help="replace an existing skill folder")
    b.add_argument("--max-rounds", type=int, default=3, help="most question rounds before giving up")
    b.add_argument("--scripts", action="store_true", help="also write helper scripts and test them in the sandbox (needs a Linux sandbox)")
    b.add_argument("--eval", action="store_true", help="also run the skill's own test cases against the model, with and without the skill (text-only skills; about 2 model calls per test)")
    b.add_argument("--eval-runs", type=int, default=1, metavar="N", help="with --eval: repeat each test N times, because models vary")
    b.add_argument("--repo", metavar="PATH_OR_LINK", help="with --from-suggestions: the repository the idea is about (a folder, or the link of a public GitHub repository); the places the idea cites are recorded as the skill's evidence (evidence.json)")
    b.add_argument("--focus", help="with --repo: only read this folder of the repository")

    ev = area.add_parser("eval", help="run a skill's own test cases against a model, with and without the skill (text-only skills)")
    ev.add_argument("folder", nargs="?", help="a skill folder (the one with SKILL.md)")
    ev.add_argument("--library", metavar="NAME", help="a skill in the library, instead of a folder")
    ev.add_argument("--version", type=int, metavar="N", help="with --library: which version (default: the latest)")
    ev.add_argument("--no-baseline", action="store_true", help="only run with the skill: half the model calls, but no comparison")
    ev.add_argument("--runs", type=int, default=1, metavar="N", help="repeat each test N times, because models vary")
    ev.add_argument("--json", action="store_true", help="print the result as JSON")

    cn = area.add_parser(
        "canary",
        help="behaviour scan: watch what a model does with a skill's or agent's instructions, on fake tools and planted fake secrets (needs a provider key)",
    )
    cn.add_argument("folder", nargs="?", help="a skill or agent folder (the one with SKILL.md or AGENT.md)")
    cn.add_argument("--library", metavar="NAME", help="a skill or agent in the library, instead of a folder")
    cn.add_argument("--kind", choices=["skill", "agent"], default="skill", help="with --library: which library (default: skill)")
    cn.add_argument("--version", type=int, metavar="N", help="with --library: which version (default: the latest)")
    cn.add_argument("--runs", type=int, default=1, metavar="N", help="repeat each task N times (1 to 5), because models vary")
    cn.add_argument("--scenarios", type=int, default=None, metavar="N", help="how many tasks to give the agent (1 to 8; default 5, or 4 with --measure)")
    cn.add_argument("--measure", action="store_true", help="instead of one skill, scan the built-in corpus of known-bad and known-good skills and compare with the static checks")
    cn.add_argument("--only", nargs="+", metavar="NAME", help="with --measure: only these corpus skills")
    cn.add_argument("--no-control", action="store_true", help="do not re-run a task that found something without the skill (cheaper, but a finding is not compared)")
    cn.add_argument("--no-draft", action="store_true", help="do not ask a model to draft tasks from the description (one model call less)")
    cn.add_argument("--json", action="store_true", help="print the result as JSON")

    r = area.add_parser("render", help="re-render a skill folder from its skill.sdm.json (no AI)")
    r.add_argument("sdm", help="path of a skill.sdm.json")
    r.add_argument("--out", help="where skill folders go (default: generated-skills/ in this repository)")
    r.add_argument("--force", action="store_true", help="replace an existing skill folder")

    v = area.add_parser("validate", help="static safety and structure checks on any skill folder (runs nothing)")
    v.add_argument("folder", help="path of a skill folder (the one with SKILL.md)")
    v.add_argument("--json", action="store_true", help="print machine-readable JSON")

    area.add_parser("sandbox-status", help="is a safe place to run skill scripts available on this machine?")
    area.add_parser("sandbox-build-mcp", help="build, once, the image that generated Python MCP servers are tested in (needs Docker and a network)")
    area.add_parser("sandbox-build-mcp-node", help="build, once, the image that generated Node (TypeScript) MCP servers are tested in (needs Docker and a network)")
    md = area.add_parser("models", help="which models are set up, which keys are unused; with --test, ask each model one tiny question")
    md.add_argument("--test", action="store_true", help="make one tiny call to each model (uses a little of your quota)")
    md.add_argument("--json", action="store_true")

    pl = area.add_parser("plan", help="plan a task before doing it: scope, size, process, rules, token use (reads and changes nothing)")
    pl.add_argument("prompt", nargs="?", help="the task, in your own words")
    pl.add_argument("--file", help="read the task from a text file")
    pl.add_argument("--repo", help="the repository the task is about, a folder or the link of a public GitHub repository: measures the size of the change and finds its rules (a link has no CLAUDE.md or AGENTS.md: only source files are downloaded)")
    pl.add_argument("--no-ai", action="store_true", help="send nothing to a model: plan only what code can measure")
    pl.add_argument("--type", choices=["feature", "bugfix", "refactor", "migration", "docs", "investigation", "other"], help="the kind of task (needed with --no-ai; otherwise the model reads it)")
    pl.add_argument("--tier", type=int, choices=[0, 1, 2, 3], help="ask for at least this much process (it can only raise the tier)")
    pl.add_argument("--allow-lower", action="store_true", help="let --tier LOWER the tier the evidence gives (an explicit confirmation, recorded in the plan)")
    pl.add_argument("--budget", type=int, help="tokens of context to read (default depends on the tier)")
    pl.add_argument("--sensitive", action="append", metavar="GLOB", help="a path pattern that counts as sensitive, such as 'src/billing/*' (repeatable)")
    pl.add_argument("--json", action="store_true", help="print the plan as JSON")
    pl.add_argument("--save", metavar="FILE", help="also write the plan to this file")

    sv = area.add_parser("serve", help="start the local HTTP API for the web UI (127.0.0.1 only)")
    sv.add_argument("--port", type=int, default=8000)
    sv.add_argument("--host", default="127.0.0.1", help="the address to listen on; anything but this machine needs SKILLFORGE_MODE=hosted (docs/hosting.md)")

    lib = area.add_parser("library", help="keep skills as versions: import (checked first), diff, rollback, export, install")
    ops = lib.add_subparsers(dest="command", required=True)
    p = ops.add_parser("import", help="check a skill folder or .zip and keep it as the next version (refused if a check fails)")
    p.add_argument("source", help="a skill folder (the one with SKILL.md) or a .zip of one")
    p.add_argument("--test-scripts", action="store_true", help="also re-run the skill's own script cases in the Linux sandbox")
    p.add_argument("--note", help="a short note stored with the version")
    ops.add_parser("list", help="the skills in the library")
    p = ops.add_parser("versions", help="every version of one skill")
    p.add_argument("name")
    p = ops.add_parser("diff", help="what changed between two versions, and what got riskier (default: the latest and the one before)")
    p.add_argument("name")
    p.add_argument("--from", dest="frm", type=int, metavar="N", help="the older version number")
    p.add_argument("--to", type=int, metavar="N", help="the newer version number")
    p = ops.add_parser("rescan", help="check the stored versions again with today's checks and say which are now worse (changes nothing)")
    p.add_argument("name", nargs="?", help="one skill; default: every skill in the library")
    p.add_argument("--version", type=int, metavar="N", help="only this version (needs the name)")
    for name, helptext in (
        ("cite", "record places in a repository (files, functions) as the skill's evidence, with the facts the graph has now (a new version)"),
        ("recheck", "say what changed in the code a skill cites (reads the repository, changes nothing, exit 1 if anything is gone, moved or changed)"),
        ("refresh", "record today's facts for the cited places that still exist, after you have read the skill against the changed code (a new version)"),
    ):
        p = ops.add_parser(name, help=helptext)
        p.add_argument("name")
        p.add_argument("--repo", required=True, metavar="PATH_OR_LINK", help="the repository the skill's evidence is about: a folder, or the link of a public GitHub repository (downloaded fresh each time)")
        p.add_argument("--focus", help="only read this folder of the repository (default: the one the evidence was recorded with)")
        if name == "cite":
            p.add_argument("--ref", action="append", metavar="FILE_OR_FUNCTION", help="a place to cite: a file, a function name, or FILE::NAME (repeat for more)")
            p.add_argument("--from-text", action="store_true", help="also cite the files and functions the skill's own text names (an ambiguous name is listed, never picked)")
        if name == "recheck":
            p.add_argument("--version", type=int, metavar="N", help="default: the latest")
            p.add_argument("--json", action="store_true", help="print the result as JSON")
        if name == "refresh":
            p.add_argument("--drop-missing", action="store_true", help="also remove the places that are gone from the repository")
        if name != "recheck":
            p.add_argument("--note", help="a short note stored with the new version")
    p = ops.add_parser("rollback", help="make a new version with the content of an old one (nothing is deleted)")
    p.add_argument("name")
    p.add_argument("--to", type=int, required=True, metavar="N", help="the version whose content to restore")
    p = ops.add_parser("export", help="write a version as a .zip to share (checked again first)")
    p.add_argument("name")
    p.add_argument("--version", type=int, metavar="N", help="default: the latest")
    p.add_argument("--out", help="the .zip to write (default: NAME-vN.zip in the current folder)")
    p.add_argument("--without-spec", action="store_true", help="leave out spec.json, which holds the requester's own words")
    p.add_argument("--without-evidence", action="store_true", help="leave out evidence.json, which names the files and functions of the repository the skill cites")
    p.add_argument("--force", action="store_true", help="replace an existing .zip")
    p = ops.add_parser("install", help="copy a version to a skills folder where an agent reads it (checked again first)")
    p.add_argument("name")
    p.add_argument("--version", type=int, metavar="N", help="default: the latest")
    where = p.add_mutually_exclusive_group(required=True)
    where.add_argument("--personal", action="store_true", help="~/.claude/skills: every Claude Code session on this machine")
    where.add_argument("--project", action="store_true", help=".claude/skills in the current folder: this project only")
    where.add_argument("--to", metavar="DIR", help="any skills folder; the skill goes to DIR/NAME")
    p.add_argument("--force", action="store_true", help="replace an existing folder (the old one is copied to a backup first)")

    lg = area.add_parser("languages", help="which programming languages are supported, and how deeply")
    lg.add_argument("--download", action="store_true", help="fetch the grammars of the standard languages now")
    lg.add_argument("--download-all", action="store_true", help="fetch every grammar in the table now")
    return parser


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    args = _parser().parse_args(argv)
    if args.area in ("suggest", "guide", "build", "render", "validate", "sandbox-status", "sandbox-build-mcp", "sandbox-build-mcp-node", "languages", "library", "serve", "plan", "eval", "canary", "models"):
        handler = {
            "suggest": _run_suggest, "guide": _run_guide, "build": _run_build, "render": _run_render,
            "validate": _run_validate, "sandbox-status": _run_sandbox_status, "sandbox-build-mcp": _run_sandbox_build_mcp, "sandbox-build-mcp-node": _run_sandbox_build_mcp_node, "languages": _run_languages,
            "library": _run_library, "serve": _run_serve, "plan": _run_plan, "eval": _run_eval, "canary": _run_canary, "models": _run_models,
        }[args.area]
        try:
            return handler(args)
        except NeedAnswers as exc:
            print(_need_answers_message(exc), file=sys.stderr)
            return 2
        except (ProviderError, BuildError, LibraryError, query.QueryError, NotADirectoryError, OSError, ValueError, PlanError, RepoError) as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
    try:
        g = build_graph(_repo_arg(args.repo), focus=args.focus, use_cache=not args.no_cache, with_history=not args.no_history)
        cmd = args.command
        if cmd == "stats":
            result, render = query.stats(g), _render_stats
            result["root"] = _link_label(args.repo) or result["root"]  # a link shows owner/repo, not the folder its copy is kept in
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
    except (query.QueryError, NotADirectoryError, RepoError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2) if args.json else render(result))
    return 0
