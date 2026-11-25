"""The Quality Report: one version of one skill, assembled by code from what is stored. No model is asked, nothing is run, nothing is changed.

It puts in one place what was scattered: today's checks (the library's static checks, and, for a skill built here, the builder's own design and
written-file checks run again on the stored definition and spec), what each check was at import, the requirement against its tests, the cost, the
Testing Lab's result for this version, what changed since the previous version, what did NOT run, and what to do next.

It never says a skill is safe or good: it lists what ran, what it found, and what did not run (docs/quality-report.md).
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence

import yaml

from ..build.checks import check_rendered, run_checks
from ..build.models import RequirementSpec, SkillDefinition
from ..build.quality import HEAVY_DESCRIPTION_TOKENS, HEAVY_SKILL_TOKENS, estimate_tokens, quality_checks, rendered_quality
from ..evaluate import blocker, load_files, plan_cases, tests_of
from ..evidence import EvidenceError, read_evidence
from ..library import Library, LibraryError, Version, compare_with_risk
from ..results import FAILED, NOT_RUN, PASSED, WARNING, CheckResult
from ..validate.static import validate_files

MAX_SUGGESTIONS = 12
MAX_RISK_ITEMS = 8
DEFINITION_FILE = "skill.sdm.json"
SPEC_FILE = "spec.json"
GROUPS = (
    ("library", "Library checks: structure and safety"),
    ("design", "Design checks: instruction clarity and requirement coverage"),
    ("written", "The written files against the requirement"),
)
LIMITS = [
    "Passing these checks is not proof that a skill works or that it is safe: they read the files by syntax and patterns, and nothing here runs the skill.",
    "The design and requirement checks run only for a skill built here (they need its definition and spec files), and they hold the skill to the words it was built from, not to what happens when it is used.",
    "The token numbers are estimates at about four characters a token: real tokenizers differ by model and language.",
    "A Testing Lab result is one model, a small sample and seven kinds of check: it is evidence, not proof.",
]
_RANK = {PASSED: 0, NOT_RUN: 0, WARNING: 1, FAILED: 2}  # a check that did not run is never worse than one that passed (the rescan's own rule)
# What to do about a check that a stored skill can fail for a reason the check's own words do not give. Found on the author's real library: the two
# skills built on 2026-11-19 fail the first one, because the builder only started carrying the requirement into SKILL.md afterwards.
HINTS = {
    "the approved requirement reached SKILL.md word for word": (
        "If this skill was built before the builder carried the requirement into SKILL.md, build it again, or add those lines to SKILL.md yourself."
    ),
}
_CONCERNING = {"worse", "adds_nothing", "no_difference"}
_OUTCOME_WORDS = {
    "worse": "the skill made it worse", "adds_nothing": "the model did as well without the skill", "no_difference": "no difference with and without the skill",
    "too_few": "too few cases to say", "with_only": "run without the comparison", "helped": "the skill helped", "not_run": "nothing ran",
}


# ---- the checks, in three groups -------------------------------------------------------------------------------------------


def _row(c: CheckResult, was: str | None, change: str) -> dict:
    return {"name": c.name, "status": c.status, "detail": c.detail, "was": was, "change": change}


def _not_run_row(name: str, why: str) -> dict:
    return {"name": name, "status": NOT_RUN, "detail": why, "was": None, "change": "run_now"}


def library_rows(files: Mapping[str, bytes], stored: Sequence[Mapping[str, str]]) -> list[dict]:
    """Today's static checks, each with what the same check said at import: same, worse, better, or new (it did not exist then)."""
    was = {c["name"]: c["status"] for c in stored}
    rows = []
    for c in validate_files(files, kind="skill"):
        before = was.get(c.name)
        if before is None:
            change = "new"
        elif _RANK.get(c.status, 0) > _RANK.get(before, 0):
            change = "worse"
        elif _RANK.get(c.status, 0) < _RANK.get(before, 0):
            change = "better"
        else:
            change = "same"
        rows.append(_row(c, before, change))
    return rows


def definition_of(files: Mapping[str, bytes]) -> tuple[SkillDefinition | None, str]:
    """The skill's definition file, or why there is none to use."""
    if DEFINITION_FILE not in files:
        return None, f"this skill has no definition file ({DEFINITION_FILE}), so it was not built here and these checks cannot run"
    try:
        return SkillDefinition.model_validate_json(files[DEFINITION_FILE].decode("utf-8")), ""
    except (UnicodeDecodeError, ValueError) as exc:
        return None, f"{DEFINITION_FILE} cannot be read as a skill definition ({type(exc).__name__}), so these checks cannot run"


def spec_of(files: Mapping[str, bytes]) -> tuple[RequirementSpec | None, str]:
    if SPEC_FILE not in files:
        return None, f"there is no {SPEC_FILE} (the approved requirement)"
    try:
        return RequirementSpec.model_validate_json(files[SPEC_FILE].decode("utf-8")), ""
    except (UnicodeDecodeError, ValueError) as exc:
        return None, f"{SPEC_FILE} cannot be read as a requirement ({type(exc).__name__})"


def _text_files(files: Mapping[str, bytes]) -> dict[str, str]:
    """The files as text, with Windows line endings read as the same thing as Unix ones: the builder's checks were written for files the builder
    generated (always "\\n"), and a skill edited by hand on Windows must not be reported as having no front matter."""
    return {rel: data.decode("utf-8", errors="replace").replace("\r\n", "\n") for rel, data in files.items()}


def _run_now(name: str, run) -> list[dict]:
    """Run a group of the builder's checks; one that cannot run is a row that did not run, with its reason, never a crash."""
    try:
        return [_row(c, None, "run_now") for c in run()]
    except Exception as exc:  # noqa: BLE001 - said in the row, not hidden
        return [_not_run_row(name, f"the checks could not run on this skill ({type(exc).__name__})")]


def design_rows(sdm: SkillDefinition | None, why: str) -> list[dict]:
    if sdm is None:
        return [_not_run_row("The design checks (instruction clarity, requirement coverage, tests)", why)]
    return _run_now("The design checks", lambda: [*run_checks(sdm), *quality_checks(sdm)])


def written_rows(files: Mapping[str, bytes], sdm: SkillDefinition | None, sdm_why: str, spec: RequirementSpec | None, spec_why: str) -> list[dict]:
    if sdm is None:
        return [_not_run_row("The written files against the requirement", sdm_why)]
    if spec is None:
        return [_not_run_row("The written files against the requirement", spec_why + ", so the requirement cannot be compared with SKILL.md")]
    text = _text_files(files)
    return _run_now("The written files against the requirement", lambda: [*check_rendered(text, sdm), *rendered_quality(text, sdm, spec)])


# ---- the requirement against its tests ---------------------------------------------------------------------------------


def requirement_coverage(files: Mapping[str, bytes], sdm: SkillDefinition | None, spec: RequirementSpec | None) -> dict:
    """Each acceptance criterion with the tests that cite it. The criteria come from the definition, else from the spec (numbered in order), else
    there are none: a skill that records no requirement is said to, and none is invented."""
    if sdm is not None:
        source, criteria = "definition", list(sdm.acceptance_criteria.items())
    elif spec is not None:
        source, criteria = "spec", [(f"AC{i}", text) for i, text in enumerate(spec.acceptance_criteria, start=1)]
    else:
        source, criteria = "none", []
    tests, _ = tests_of(files)
    known = {cid for cid, _ in criteria}
    rows = []
    for cid, text in criteria:
        cited = [t for t in tests if cid in t.covers]
        rows.append({"id": cid, "text": text, "tests": [t.name for t in cited], "runnable": sum(bool(t.run_input.strip() and t.assertions) for t in cited)})
    unknown = [{"test": t.name, "ids": [c for c in t.covers if c not in known]} for t in tests if source != "none" and any(c not in known for c in t.covers)]
    return {"source": source, "criteria": rows, "uncovered": [r["id"] for r in rows if not r["tests"]], "unknown_cites": unknown}


def tests_summary(files: Mapping[str, bytes]) -> dict:
    """How many cases there are and how many the Testing Lab can run, and why the rest cannot (the same rules the Lab uses)."""
    skill = load_files(files)
    code, why = blocker(skill)
    planned, skipped = plan_cases(skill)
    if not code and skill.tests and not planned:
        code, why = "nothing_runnable", f"none of its {len(skill.tests)} test case(s) has a message to send and a check to run"
    return {"total": len(skill.tests), "runnable": 0 if code in ("needs_tools", "nothing_runnable") else len(planned), "blocker": code, "reason": why, "skipped": skipped}


# ---- cost ---------------------------------------------------------------------------------------------------------------------


def token_summary(files: Mapping[str, bytes]) -> dict:
    """What the skill costs to use, estimated: always loaded (name and description), loaded when used (SKILL.md), on demand (every other file).
    It needs only SKILL.md and the other files, so it works for any skill."""
    skill_md = files.get("SKILL.md", b"").decode("utf-8", errors="replace")
    meta = re.match(r"---\n(.*?)\n---\n", skill_md.replace("\r\n", "\n"), re.DOTALL)
    try:
        front = yaml.safe_load(meta.group(1)) if meta else None
    except yaml.YAMLError:
        front = None
    front = front if isinstance(front, dict) else {}
    name, description = str(front.get("name", "")), " ".join(str(front.get("description", "")).split())
    always = estimate_tokens(f"{name} {description}")
    when_used = estimate_tokens(skill_md)
    on_demand = sum(estimate_tokens(data.decode("utf-8", errors="replace")) for rel, data in files.items() if rel not in ("SKILL.md", "report.md"))
    heavy = []
    if always > HEAVY_DESCRIPTION_TOKENS:
        heavy.append(f"the description is paid on every task: shorten it below about {HEAVY_DESCRIPTION_TOKENS} tokens")
    if when_used > HEAVY_SKILL_TOKENS:
        heavy.append("SKILL.md is long: move detail the agent rarely needs into a file it opens on demand, or cut it")
    return {"always": always, "when_used": when_used, "on_demand": on_demand, "heavy": heavy}


# ---- the Testing Lab, changes, evidence -----------------------------------------------------------------------------------


def _run_view(r: Mapping) -> dict:
    s = r["summary"]
    return {"id": r["id"], "tag": r["tag"], "outcome": s["outcome"], "with_skill": s["with_skill"], "baseline": s["baseline"], "calls": s["calls"], "runs": r["runs"], "created_at": r["created_at"]}


def lab_summary(runs: Sequence[Mapping], version: int) -> dict:
    """The Testing Lab's result for THIS version. `runs` are the Lab's run summaries for the skill, newest first. A run of another version is never
    shown as this version's: it is said to be of an older version."""
    mine = [r for r in runs if r["version"] == version]
    done = next((r for r in mine if r["status"] == "done" and r.get("summary")), None)
    if done:
        return {"state": "this_version", "run": _run_view(done), "other": None}
    if any(r["status"] == "working" for r in mine):
        return {"state": "running", "run": None, "other": None}
    if mine and mine[0]["status"] == "failed":
        return {"state": "failed", "run": None, "other": None, "error": mine[0].get("error", "")}
    other = next((r for r in runs if r["version"] != version and r["status"] == "done" and r.get("summary")), None)
    if other:
        return {"state": "older_version", "run": None, "other": _run_view(other)}
    return {"state": "never_run", "run": None, "other": None}


def changes_since_previous(library: Library, name: str, v: Version) -> dict | None:
    """The library's own risk diff against the version before this one (None for a first version)."""
    before = [x for x in library.versions(name) if x.version < v.version]
    if not before:
        return None
    risk = compare_with_risk(library, name, before[-1].version, v.version).risk
    items = [{"direction": c.direction, "kind": c.kind, "detail": c.detail, "path": c.path} for c in risk.changes]
    return {
        "from": before[-1].tag, "to": v.tag, "from_version": before[-1].version, "to_version": v.version, "level": risk.level, "note": risk.note,
        "counts": {d: risk.count(d) for d in ("riskier", "look", "safer")}, "items": items[:MAX_RISK_ITEMS], "more": max(0, len(items) - MAX_RISK_ITEMS),
    }


def evidence_summary(files: Mapping[str, bytes]) -> dict | None:
    """The repository a skill cites and how many places, as the skill's own page shows them. A damaged evidence file is the library group's row."""
    try:
        ev = read_evidence(files)
    except EvidenceError:
        return None
    return None if ev is None else {"repo": ev.repo, "places": len(ev.refs), "taken_at": ev.taken_at, "commit": ev.commit, "dirty": ev.dirty}


# ---- what did not run, what needs a look, what to do ----------------------------------------------------------------------


def not_run_list(groups: Sequence[Mapping], lab: Mapping, files: Mapping[str, bytes]) -> list[dict]:
    out = [{"what": r["name"], "why": r["detail"]} for g in groups for r in g["rows"] if r["status"] == NOT_RUN]
    if lab["state"] in ("never_run", "older_version", "failed"):
        out.append({"what": "The Testing Lab on this version", "why": "it has not been run (or its last run did not finish), so nobody knows whether the skill helps"})
    has_scripts = any(rel.startswith("scripts/") for rel in files)
    out.append({
        "what": "Scripts run in a sandbox",
        "why": "this skill has no scripts, so there is nothing to run" if not has_scripts else "the library only reads scripts: import with --test-scripts runs them in the sandbox",
    })
    out.append({"what": "A real agent using the skill", "why": "the Testing Lab asks a model with no tools, which is not an agent; installing the skill and using it is the test that matters"})
    out.append({"what": "A review of the instructions for conflicting rules", "why": "only structural checks exist: no semantic analyser has been built"})
    out.append({"what": "A security review of the text", "why": "not automated: read the instructions yourself before using the skill"})
    return out


def _count(groups: Sequence[Mapping]) -> dict:
    every = [r["status"] for g in groups for r in g["rows"]]
    return {"failed": every.count(FAILED), "warnings": every.count(WARNING), "not_run": every.count(NOT_RUN), "passed": every.count(PASSED)}


def _looks(report: Mapping) -> int:
    """How many things are worth a look although nothing failed."""
    lab, changes = report["lab"], report["changes"]
    n = report["headline"]["warnings"] + len(report["requirements"]["uncovered"]) + len(report["requirements"]["unknown_cites"])
    n += 1 if lab["state"] == "this_version" and lab["run"]["outcome"] in _CONCERNING else 0
    n += 1 if changes and changes["level"] in ("more_risk", "look") else 0
    n += len(report["tokens"]["heavy"]) if not any(r["name"].startswith("token cost") and r["status"] == WARNING for g in report["groups"] for r in g["rows"]) else 0
    return n


def attention(report: Mapping, not_run: int) -> dict:
    """One sentence, worded from what ran. Never "safe", never a green "all good": when nothing was found it says what that covers and what did not run."""
    failed = report["headline"]["failed"]
    if failed:
        return {"tone": "bad", "text": f"{failed} check{'s' if failed != 1 else ''} failed today. {'Fix it' if failed == 1 else 'Fix those'} first."}
    looks = _looks(report)
    if looks:
        return {"tone": "warn", "text": f"Nothing failed, but {looks} thing{'s are' if looks != 1 else ' is'} worth a look (below)."}
    return {"tone": "info", "text": f"Nothing was found by the checks that ran. {not_run} thing{'s' if not_run != 1 else ''} did not run: they are listed below."}


def suggestions(report: Mapping, version: int) -> list[dict]:
    """What to do next, in an order that puts a failure first. Worked out from the gaps above, by code."""
    out: list[dict] = []
    skill = {"page": "skill"}
    lab = {"page": "lab", "version": version}
    rows = [r for g in report["groups"] for r in g["rows"]]
    for r in rows:
        if r["status"] == FAILED:
            hint = HINTS.get(r["name"], "")
            out.append({"kind": "fix", "text": f"Fix: {r['name']}. {r['detail']} {hint}".strip(), "link": skill})
    req = report["requirements"]
    for u in req["unknown_cites"]:
        out.append({"kind": "fix", "text": f"The test '{u['test']}' cites {', '.join(u['ids'])}, which {'is not a criterion' if len(u['ids']) == 1 else 'are not criteria'} of this skill: correct it or remove it.", "link": lab})
    for c in req["criteria"]:
        if not c["tests"]:
            out.append({"kind": "write", "text": f"Write a test for {c['id']}: {c['text']}", "link": lab})
    tests = report["tests"]
    if tests["blocker"] in ("no_cases", "nothing_runnable"):
        out.append({"kind": "write", "text": "Write test cases so the Testing Lab can run this skill: a message to send and the checks the reply must pass.", "link": lab})
    elif tests["blocker"] == "needs_tools":
        out.append({"kind": "read", "text": "This skill needs tools, so the Testing Lab cannot run it. Install it and use it for real: that is the test that matters.", "link": None})
    lab_state = report["lab"]
    runnable = tests["runnable"] > 0
    if lab_state["state"] == "never_run" and runnable:
        out.append({"kind": "run", "text": "Run its tests in the Testing Lab: they have not been run on this version.", "link": lab})
    elif lab_state["state"] == "older_version" and runnable:
        out.append({"kind": "run", "text": f"Only {lab_state['other']['tag']} was run in the Testing Lab. Run this version too.", "link": lab})
    elif lab_state["state"] == "failed":
        out.append({"kind": "run", "text": "The last Testing Lab run of this version did not finish. Run it again.", "link": lab})
    elif lab_state["state"] == "this_version":
        outcome = lab_state["run"]["outcome"]
        if outcome in _CONCERNING:
            out.append({"kind": "read", "text": f"The last Testing Lab run found: {_OUTCOME_WORDS[outcome]}. Read the failed cases in the Lab before trusting the skill.", "link": lab})
        elif outcome == "too_few":
            out.append({"kind": "write", "text": "The last Testing Lab run had too few cases to say whether the skill helps. Add more.", "link": lab})
        elif outcome == "with_only":
            out.append({"kind": "run", "text": "The last Testing Lab run had no comparison. Run it again with the comparison ticked.", "link": lab})
    for r in rows:
        if r["status"] == WARNING:
            out.append({"kind": "read", "text": f"Read: {r['name']}. {r['detail']}".strip(), "link": skill})
    warned = any(r["name"].startswith("token cost") and r["status"] == WARNING for r in rows)
    if not warned:
        for h in report["tokens"]["heavy"]:
            out.append({"kind": "shorten", "text": h[0].upper() + h[1:] + ".", "link": None})
    ch = report["changes"]
    if ch and ch["level"] in ("more_risk", "look"):
        out.append({"kind": "read", "text": f"Changes since {ch['from']} got riskier or are worth a look: read them.", "link": {"page": "compare", "from": ch["from_version"], "to": ch["to_version"]}})
    return out


# ---- the report ---------------------------------------------------------------------------------------------------------------


def build_report(library: Library, name: str, version: int | None, runs: Sequence[Mapping]) -> dict:
    """The report for one version. `runs` are the Testing Lab's run summaries for this skill (newest first). The version is read through the library,
    which checks every file against its manifest first: a changed version is refused, not reported."""
    v, files = library.read(name, version)
    try:
        tests = tests_summary(files)
    except ValueError as exc:  # no SKILL.md: the library would not have kept it
        raise LibraryError(f"{name} {v.tag}: {exc}") from exc
    sdm, sdm_why = definition_of(files)
    spec, spec_why = spec_of(files)
    groups = [
        {"key": "library", "title": GROUPS[0][1], "rows": library_rows(files, v.checks)},
        {"key": "design", "title": GROUPS[1][1], "rows": design_rows(sdm, sdm_why)},
        {"key": "written", "title": GROUPS[2][1], "rows": written_rows(files, sdm, sdm_why, spec, spec_why)},
    ]
    lab = lab_summary(runs, v.version)
    report: dict = {
        "name": v.name, "version": v.version, "tag": v.tag, "latest": library.versions(name)[-1].version == v.version, "versions": len(library.versions(name)),
        "created_at": v.created_at, "source_kind": v.source_kind, "source_label": v.source_label, "note": v.note, "content_hash": v.content_hash,
        "headline": _count(groups), "groups": groups, "requirements": requirement_coverage(files, sdm, spec), "tests": tests,
        "tokens": token_summary(files), "lab": lab, "changes": changes_since_previous(library, name, v), "evidence": evidence_summary(files),
    }
    report["not_run"] = not_run_list(groups, lab, files)
    report["attention"] = attention(report, len(report["not_run"]))
    every = suggestions(report, v.version)
    report["suggestions"], report["suggestions_more"] = every[:MAX_SUGGESTIONS], max(0, len(every) - MAX_SUGGESTIONS)
    report["limits"] = list(LIMITS)
    return report
