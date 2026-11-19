"""Build: description -> questions -> approved spec -> design -> checks -> files + report."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from ..providers.base import LLMProvider
from .architect import criteria_ids, design
from .checks import FAILED, NOT_RUN, SLUG, CheckResult, check_rendered, not_run_checks, run_checks
from .models import Provenance, RequirementSpec, Script, ScriptCase, SkillDefinition, SkillDraft
from ..sandbox import probe_sandbox
from ..validate import validate_files
from .render import MAX_NAME, render_files, render_report, slugify, write_files
from .requirements import Question, check_completeness, extract_spec, questions_for
from .scripts import ScriptReport, ScriptRunner, build_scripts, check_scripts, run_script_tests


def sandbox_note(probe: Callable[[], object] | None = None) -> str:
    """What the report says about the sandbox on this machine. A failed probe must never stop a build."""
    try:
        s = (probe or probe_sandbox)()
    except Exception as exc:  # noqa: BLE001
        return f"unknown ({type(exc).__name__})"
    return f"{'available' if s.available else 'unavailable'}. {s.reason}"


class BuildError(Exception):
    """The build stopped for a reason the user can act on. Nothing misleading was written."""


class NeedAnswers(BuildError):
    def __init__(self, questions: list[Question]) -> None:
        self.questions = questions
        super().__init__("More details are needed: " + ", ".join(q.slot for q in questions))


Ask = Callable[[list[Question]], dict[str, str]]
Approve = Callable[[RequirementSpec], bool]


@dataclass
class BuildResult:
    status: str  # "ok": every check that ran passed. "draft": a check failed, or the scripts were never run.
    out_dir: Path
    sdm: SkillDefinition
    spec: RequirementSpec
    checks: list[CheckResult]
    files: list[str]
    model_calls: int = 0
    notes: list[str] = field(default_factory=list)
    draft_reason: str = ""  # why it is a draft when no check failed (untested scripts)


def _assemble(
    draft: SkillDraft, spec: RequirementSpec, provider: LLMProvider, now: datetime,
    scripts: list[Script] | None = None, cases: list[ScriptCase] | None = None,
) -> SkillDefinition:
    name = slugify(draft.name)
    if not draft.name.strip():
        name = slugify(spec.goal)
    permissions = list(draft.permissions)
    if scripts and "run_commands" not in permissions:  # the agent has to run the scripts
        permissions.append("run_commands")
    return SkillDefinition(
        **{**draft.model_dump(), "name": name, "permissions": permissions},
        acceptance_criteria=criteria_ids(spec),
        provenance=Provenance(
            provider=provider.name, model=provider.model, rounds=spec.rounds,
            created_at=now.isoformat(timespec="seconds"), name_adjusted=name != draft.name,
        ),
        scripts=scripts or [],
        script_cases=cases or [],
    )


def _untested_reason(sdm: SkillDefinition, report: ScriptReport | None) -> str:
    """Scripts that never ran in the sandbox make the skill a draft, even though no check failed."""
    if not sdm.scripts or (report is not None and report.complete):
        return ""
    why = "; ".join(c.detail for c in (report.results if report else []) if c.status == NOT_RUN)
    return "This skill has scripts that were not all run in the sandbox, so they are untested." + (f" {why}" if why else "")


def finalize(
    sdm: SkillDefinition, spec: RequirementSpec, out_root: Path, *, force: bool, notes: list[str] | None = None,
    model_calls: int = 0, sandbox_note: str | None = None, script_report: ScriptReport | None = None,
    script_runner: ScriptRunner | None = None,
) -> BuildResult:
    """Render, run every check, write the report, then the files. No model is involved.

    Scripts are run in the sandbox here unless a report from the script step is passed in (the same scripts, already run)."""
    if not SLUG.match(sdm.name) or len(sdm.name) > MAX_NAME:  # the name becomes a folder name: never trust it
        raise BuildError(f"'{sdm.name}' is not a valid skill name (lowercase letters, digits and hyphens, max {MAX_NAME}).")
    notes = list(notes or [])
    files = render_files(sdm, spec)
    static = validate_files({path: text.encode("utf-8") for path, text in files.items()}, folder=sdm.name)
    if sdm.scripts and script_report is None:
        script_report = run_script_tests(sdm.scripts, sdm.script_cases, script_runner)
    script_rows = check_scripts(sdm.scripts, sdm.script_cases) + (script_report.results if script_report else [])
    checks = (
        run_checks(sdm) + check_rendered(files, sdm) + static + script_rows
        + not_run_checks(sandbox_note, has_scripts=bool(sdm.scripts))
    )
    if sdm.provenance.name_adjusted:
        notes.append(f"The model's name was changed to '{sdm.name}' because it was not a valid skill name.")
    reason = _untested_reason(sdm, script_report)
    files["report.md"] = render_report(sdm, checks, notes, reason)
    out_dir = out_root / sdm.name
    try:
        write_files(out_dir, files, overwrite=force)
    except FileExistsError as exc:
        raise BuildError(str(exc)) from exc
    failed = any(c.status == FAILED for c in checks)
    return BuildResult(
        "draft" if failed or reason else "ok", out_dir, sdm, spec, checks, sorted(files), model_calls, notes, reason,
    )


def check_description(description: str) -> str:
    words = description.strip()
    if len(words) < 10:
        raise BuildError("Describe the skill you want in at least a sentence.")
    return words


@dataclass
class Round:
    """What one round of reading the person's words found. `state` says what happens next."""

    state: str  # "complete": ready for approval. "questions": ask them. "blocked": cannot be built. "incomplete": out of rounds.
    spec: RequirementSpec
    notes: list[str]
    calls: int
    questions: list[Question] = field(default_factory=list)
    message: str = ""  # why it is blocked or incomplete


def understand_round(provider: LLMProvider, words: str, round_no: int, max_rounds: int) -> Round:
    """One extraction plus the checklist. Completeness is decided here, by code; the model only extracts."""
    spec, extract_notes, used = extract_spec(provider, words, round_no)
    notes = [f"round {round_no}: {n}" for n in extract_notes]
    comp = check_completeness(spec)
    if comp.blockers:
        return Round("blocked", spec, notes, used, message=" ".join(comp.blockers))
    if comp.complete:
        return Round("complete", spec, notes, used)
    if round_no >= max_rounds:
        message = (
            f"The requirements are still incomplete after {max_rounds} rounds ({comp.score} answered). "
            f"Still missing: {', '.join(comp.missing)}."
        )
        return Round("incomplete", spec, notes, used, message=message)
    return Round("questions", spec, notes, used, questions=questions_for(comp.missing))


def apply_answers(words: str, questions: list[Question], answers: dict[str, str]) -> str:
    """The person's words so far, plus their answers. Extraction runs again on all of it, so every quote is
    still checked against what they really wrote."""
    new = [answers.get(q.slot, "").strip() for q in questions]
    if not any(new):
        raise BuildError("No answers were given, so the requirements are still incomplete.")
    return words + "\n" + "\n".join(a for a in new if a)


def gather_spec(
    description: str, provider: LLMProvider, ask: Ask, max_rounds: int
) -> tuple[RequirementSpec, int, list[str]]:
    words = check_description(description)
    calls = 0
    notes: list[str] = []
    for round_no in range(1, max_rounds + 1):
        r = understand_round(provider, words, round_no, max_rounds)
        calls += r.calls
        notes += r.notes
        if r.state in ("blocked", "incomplete"):
            raise BuildError(r.message)
        if r.state == "complete":
            return r.spec, calls, notes
        words = apply_answers(words, r.questions, ask(r.questions))
    raise BuildError("unreachable")  # pragma: no cover


Progress = Callable[[str], None]


def build_from_spec(
    spec: RequirementSpec,
    provider: LLMProvider,
    *,
    out_root: Path,
    force: bool = False,
    now: datetime | None = None,
    sandbox_note: str | None = None,
    with_scripts: bool = False,
    script_runner: ScriptRunner | None = None,
    calls: int = 0,
    notes: list[str] | None = None,
    progress: Progress | None = None,
) -> BuildResult:
    """Everything after the person approved the requirement: scripts, design, one repair, checks, files."""
    now = now or datetime.now(timezone.utc)
    say = progress or (lambda message: None)
    notes = list(notes or [])
    scripts: list[Script] = []
    cases: list[ScriptCase] = []
    script_report: ScriptReport | None = None
    if with_scripts:  # scripts first: the workflow is then written around the scripts that really exist
        say("Writing helper scripts and running their test cases in the sandbox")
        scripts, cases, script_report, used, script_notes = build_scripts(provider, spec, script_runner)
        calls += used
        notes += script_notes
    say("Designing the skill from your approved requirement")
    draft, used = design(provider, spec, scripts=scripts)
    calls += used
    sdm = _assemble(draft, spec, provider, now, scripts, cases)
    failures = [f"{c.name}: {c.detail}" for c in run_checks(sdm) if c.status == FAILED]
    if failures:  # one repair attempt, fed the exact failures
        say(f"The design failed {len(failures)} check(s); asking the model to fix them once")
        notes.append(f"The first design failed {len(failures)} check(s); the model was asked to fix them once.")
        draft, used = design(provider, spec, failures, scripts=scripts)
        calls += used
        sdm = _assemble(draft, spec, provider, now, scripts, cases)
    say("Writing the files and running every check")
    return finalize(
        sdm, spec, out_root, force=force, notes=notes, model_calls=calls, sandbox_note=sandbox_note,
        script_report=script_report, script_runner=script_runner,
    )


def build_skill(
    description: str,
    provider: LLMProvider,
    *,
    ask: Ask,
    approve: Approve,
    out_root: Path,
    force: bool = False,
    max_rounds: int = 3,
    now: datetime | None = None,
    sandbox_note: str | None = None,
    with_scripts: bool = False,
    script_runner: ScriptRunner | None = None,
) -> BuildResult:
    spec, calls, notes = gather_spec(description, provider, ask, max_rounds)
    if not approve(spec):
        raise BuildError("The requirement was not approved, so nothing was built.")
    return build_from_spec(
        spec, provider, out_root=out_root, force=force, now=now, sandbox_note=sandbox_note,
        with_scripts=with_scripts, script_runner=script_runner, calls=calls, notes=notes,
    )


def rebuild(
    sdm_path: Path, out_root: Path, *, force: bool, sandbox_note: str | None = None,
    script_runner: ScriptRunner | None = None,
) -> BuildResult:
    """Re-render a saved skill.sdm.json. No model call: the same definition always gives the same files.

    A skill with scripts has its script cases run again in the sandbox, so `render` doubles as a re-test."""
    try:
        sdm = SkillDefinition.model_validate_json(sdm_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise BuildError(f"Cannot read a skill definition from {sdm_path}: {exc}") from exc
    spec_path = sdm_path.with_name("spec.json")
    if spec_path.exists():
        spec = RequirementSpec.model_validate_json(spec_path.read_text(encoding="utf-8"))
    else:
        spec = RequirementSpec(goal=sdm.description, acceptance_criteria=list(sdm.acceptance_criteria.values()))
    return finalize(
        sdm, spec, out_root, force=force, notes=["Re-rendered from a saved definition; no model was used."],
        sandbox_note=sandbox_note, script_runner=script_runner,
    )
