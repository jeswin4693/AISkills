"""Build an agent from an approved requirement: design, one repair, checks, files, report.

Same shape as the skill build and the same rules: completeness and every check are decided by code, a repair is kept only if
it is not worse, a check is "passed" only if it ran, and the report says what did not run. An agent has no scripts, so its
only draft reason is a failed check.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from ..providers.base import LLMProvider
from ..results import FAILED, NOT_RUN, PASSED, WARNING, CheckResult
from ..validate import validate_files
from .agent import TOOL_MEANING, AgentDefinition, assemble_agent, design_agent, person_lines, render_agent_files
from .models import RequirementSpec
from .pipeline import BuildError
from .quality import LONG_STEP_WORDS, VAGUE, has_when_clause, norm
from ..validate.static import MAX_DESCRIPTION, SLUG
from .render import MAX_NAME, write_files
from .tools import tools_for

MAX_STEPS = 7
INFO_CHECK = "what the agent can do beyond reading files"  # for a person to read: never a problem the model can repair
NOT_RUN_CHECK = "the agent's test cases were run against a model"
Progress = Callable[[str], None]


@dataclass
class AgentBuildResult:
    status: str  # "ok": every check that ran passed. "draft": a check failed.
    out_dir: Path
    definition: AgentDefinition
    spec: RequirementSpec
    checks: list[CheckResult]
    files: list[str]
    model_calls: int = 0
    notes: list[str] = field(default_factory=list)
    draft_reason: str = ""  # an agent has no scripts to leave untested, so this stays empty


def check_agent(defn: AgentDefinition, spec: RequirementSpec, files: dict[str, str]) -> list[CheckResult]:
    """Everything code can say about a design and its rendered AGENT.md. Failures are structural; wording is a warning."""
    out: list[CheckResult] = []

    def row(name: str, problems: list[str], ok_detail: str = "", status: str = FAILED) -> None:
        out.append(CheckResult(name, status, "; ".join(problems)) if problems else CheckResult(name, PASSED, ok_detail))

    row("the agent name is a valid name", [] if SLUG.match(defn.name) and len(defn.name) <= MAX_NAME else
        [f"'{defn.name}' is not lowercase letters, digits and hyphens of at most {MAX_NAME} characters"])
    description = " ".join(defn.description.split())
    row("description is present and within the limit",
        ([] if description else ["the description is empty"]) + ([f"longer than {MAX_DESCRIPTION} characters"] if len(description) > MAX_DESCRIPTION else []))
    row("description says when to hand work to the agent", [] if has_when_clause(description) else ["no trigger phrase: the main conversation cannot tell when to use it"], status=WARNING)
    row("a role, steps and a report format are written",
        [p for p, bad in (("no role", not defn.role.strip()), ("no steps", not defn.process), ("no report format", not defn.output_format.strip())) if bad])
    row("the tools line is explicit and matches the permissions",
        [] if defn.tools and defn.tools == tools_for(defn.permissions) else ["the tools line is empty or differs from what the permissions give"],
        ", ".join(defn.tools))
    ids, covered = set(defn.acceptance_criteria), {c for t in defn.tests for c in t.covers}
    row("every acceptance criterion is covered by a test", [f"{i} has no test" for i in sorted(ids - covered)], f"{len(ids)} criteria")
    row("test ids all refer to a real acceptance criterion", [f"unknown id {i}" for i in sorted(covered - ids)], status=WARNING)
    kinds = {t.kind for t in defn.tests}
    row("there is a positive and a negative test", [f"no {k} test" for k in ("positive", "negative") if k not in kinds])
    text = norm(files.get("AGENT.md", ""))
    missing = [line for group in person_lines(spec).values() for line in group if norm(line) not in text]
    row("the person's rules, criteria and failure behaviour are in AGENT.md word for word", [f'missing: "{m}"' for m in missing])
    prose = " ".join([*defn.process, defn.output_format, *defn.rules])
    found = sorted({m.group(0).lower() for m in VAGUE.finditer(prose)})
    row("no vague wording in the instructions", [f"vague: {', '.join(found)}"] if found else [], status=WARNING)
    long_steps = [i for i, s in enumerate(defn.process, start=1) if len(s.split()) > LONG_STEP_WORDS]
    row("steps are few and short",
        ([f"{len(defn.process)} steps (at most {MAX_STEPS})"] if len(defn.process) > MAX_STEPS else [])
        + ([f"step {', '.join(map(str, long_steps))} is over {LONG_STEP_WORDS} words"] if long_steps else []), status=WARNING)
    extra = [t for t in defn.tools if t not in ("Read", "Grep", "Glob")]
    out.append(
        CheckResult(INFO_CHECK, WARNING, "; ".join(f"{t}: {TOOL_MEANING.get(t, 'a tool')}" for t in extra) + ". Make sure the requirement asked for this.")
        if extra else CheckResult(INFO_CHECK, PASSED, "it can only read and search files")
    )
    return out


def _problems(checks: Sequence[CheckResult]) -> list[str]:
    return [f"{c.name}: {c.detail}" for c in checks if c.status in (FAILED, WARNING) and c.name != INFO_CHECK]


def _score(defn: AgentDefinition, spec: RequirementSpec) -> tuple[int, int]:
    """(failed checks, warnings): smaller is better, and a failure outweighs any number of warnings."""
    checks = [c for c in check_agent(defn, spec, render_agent_files(defn, spec)) if c.name != INFO_CHECK]
    return (sum(c.status == FAILED for c in checks), sum(c.status == WARNING for c in checks))


def _report(defn: AgentDefinition, checks: Sequence[CheckResult], notes: Sequence[str], status: str) -> str:
    ran = [c for c in checks if c.status != NOT_RUN]
    failed = [c for c in ran if c.status == FAILED]
    warned = [c for c in ran if c.status == WARNING]
    skipped = [c for c in checks if c.status == NOT_RUN]
    head = defn.name.replace("-", " ").title()
    lines = [
        f"# Build report: {head}", "",
        "Status: " + ("every check that ran passed." if status == "ok" else "DRAFT: a check failed, so read it before keeping this agent."), "",
        f"{len(ran) - len(failed) - len(warned)} passed, {len(warned)} warning(s), {len(failed)} failed, {len(skipped)} not run.", "",
    ]
    for title, group in (("Failed", failed), ("Warnings (read these)", warned), ("Not run", skipped)):
        if group:
            lines += [f"## {title}", ""] + [f"- {c.name}: {c.detail}" if c.detail else f"- {c.name}" for c in group] + [""]
    lines += ["## Passed", ""] + [f"- {c.name}" for c in ran if c.status == PASSED] + [""]
    if notes:
        lines += ["## Notes", ""] + [f"- {n}" for n in notes] + [""]
    lines += ["Passing these checks is not proof that the agent works well: they read the file, they do not run it.", ""]
    return "\n".join(lines)


def build_agent_from_spec(
    spec: RequirementSpec, provider: LLMProvider, *, out_root: Path, force: bool = False, now: datetime | None = None,
    calls: int = 0, notes: list[str] | None = None, progress: Progress | None = None,
) -> AgentBuildResult:
    """Everything after the person approved the requirement. Costs one model call, or two when the first design had problems."""
    now = now or datetime.now(timezone.utc)
    say = progress or (lambda message: None)
    notes = list(notes or [])
    say("Designing the agent from your approved requirement")
    draft, used = design_agent(provider, spec)
    calls += used
    defn = assemble_agent(draft, spec, provider, now)
    problems = _problems(check_agent(defn, spec, render_agent_files(defn, spec)))
    if problems:
        say(f"The design has {len(problems)} problem(s); asking the model to fix them once")
        first = _score(defn, spec)
        draft, used = design_agent(provider, spec, problems)
        calls += used
        second = assemble_agent(draft, spec, provider, now)
        if _score(second, spec) <= first:
            defn = second
            now_score = _score(defn, spec)
            notes.append(
                f"The first design had {len(problems)} problem(s); the model was asked to fix them once. "
                f"Failed checks and warnings went from {first[0]} and {first[1]} to {now_score[0]} and {now_score[1]}."
            )
        else:  # a repair must never make the agent worse
            notes.append(f"The first design had {len(problems)} problem(s); the model was asked to fix them once, but its second design was worse, so the first was kept.")
    say("Writing the files and running every check")
    if not SLUG.match(defn.name) or len(defn.name) > MAX_NAME:  # the name becomes a folder name: never trust it
        raise BuildError(f"'{defn.name}' is not a valid agent name (lowercase letters, digits and hyphens, max {MAX_NAME}).")
    if defn.provenance.name_adjusted:
        notes.append(f"The model's name was changed to '{defn.name}' because it was not a valid name.")
    files = render_agent_files(defn, spec)
    static = validate_files({path: text.encode("utf-8") for path, text in files.items()}, folder=defn.name, kind="agent")
    checks = [*check_agent(defn, spec, files), *static, CheckResult(NOT_RUN_CHECK, NOT_RUN, "agent test cases are not run yet: they describe a correct run, nothing has checked one")]
    status = "draft" if any(c.status == FAILED for c in checks) else "ok"
    files["report.md"] = _report(defn, checks, notes, status)
    out_dir = out_root / defn.name
    try:
        write_files(out_dir, files, overwrite=force)
    except FileExistsError as exc:
        raise BuildError(str(exc)) from exc
    return AgentBuildResult(status, out_dir, defn, spec, checks, sorted(files), calls, notes)
