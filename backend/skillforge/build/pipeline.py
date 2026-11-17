"""Build: description -> questions -> approved spec -> design -> checks -> files + report."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from ..providers.base import LLMProvider
from .architect import criteria_ids, design
from .checks import FAILED, SLUG, CheckResult, check_rendered, not_run_checks, run_checks
from .models import Provenance, RequirementSpec, SkillDefinition, SkillDraft
from ..validate import validate_files
from .render import MAX_NAME, render_files, render_report, slugify, write_files
from .requirements import Question, check_completeness, extract_spec, questions_for


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
    status: str  # "ok": every check that ran passed. "draft": at least one failed.
    out_dir: Path
    sdm: SkillDefinition
    spec: RequirementSpec
    checks: list[CheckResult]
    files: list[str]
    model_calls: int = 0
    notes: list[str] = field(default_factory=list)


def _assemble(draft: SkillDraft, spec: RequirementSpec, provider: LLMProvider, now: datetime) -> SkillDefinition:
    name = slugify(draft.name)
    if not draft.name.strip():
        name = slugify(spec.goal)
    return SkillDefinition(
        **{**draft.model_dump(), "name": name},
        acceptance_criteria=criteria_ids(spec),
        provenance=Provenance(
            provider=provider.name, model=provider.model, rounds=spec.rounds,
            created_at=now.isoformat(timespec="seconds"), name_adjusted=name != draft.name,
        ),
    )


def finalize(
    sdm: SkillDefinition, spec: RequirementSpec, out_root: Path, *, force: bool, notes: list[str] | None = None,
    model_calls: int = 0, sandbox_note: str | None = None,
) -> BuildResult:
    """Render, run every check, write the report, then the files. No model is involved."""
    if not SLUG.match(sdm.name) or len(sdm.name) > MAX_NAME:  # the name becomes a folder name: never trust it
        raise BuildError(f"'{sdm.name}' is not a valid skill name (lowercase letters, digits and hyphens, max {MAX_NAME}).")
    notes = list(notes or [])
    files = render_files(sdm, spec)
    static = validate_files({path: text.encode("utf-8") for path, text in files.items()}, folder=sdm.name)
    checks = run_checks(sdm) + check_rendered(files, sdm) + static + not_run_checks(sandbox_note)
    if sdm.provenance.name_adjusted:
        notes.append(f"The model's name was changed to '{sdm.name}' because it was not a valid skill name.")
    files["report.md"] = render_report(sdm, checks, notes)
    out_dir = out_root / sdm.name
    try:
        write_files(out_dir, files, overwrite=force)
    except FileExistsError as exc:
        raise BuildError(str(exc)) from exc
    failed = any(c.status == FAILED for c in checks)
    return BuildResult("draft" if failed else "ok", out_dir, sdm, spec, checks, sorted(files), model_calls, notes)


def gather_spec(
    description: str, provider: LLMProvider, ask: Ask, max_rounds: int
) -> tuple[RequirementSpec, int, list[str]]:
    words = description.strip()
    if len(words) < 10:
        raise BuildError("Describe the skill you want in at least a sentence.")
    calls = 0
    notes: list[str] = []
    for round_no in range(1, max_rounds + 1):
        spec, extract_notes, used = extract_spec(provider, words, round_no)
        calls += used
        notes += [f"round {round_no}: {n}" for n in extract_notes]
        comp = check_completeness(spec)
        if comp.blockers:
            raise BuildError(" ".join(comp.blockers))
        if comp.complete:
            return spec, calls, notes
        if round_no == max_rounds:
            raise BuildError(
                f"The requirements are still incomplete after {max_rounds} rounds ({comp.score} answered). "
                f"Still missing: {', '.join(comp.missing)}."
            )
        questions = questions_for(comp.missing)
        answers = ask(questions)
        new = [answers.get(q.slot, "").strip() for q in questions]
        if not any(new):
            raise BuildError("No answers were given, so the requirements are still incomplete.")
        words += "\n" + "\n".join(a for a in new if a)
    raise BuildError("unreachable")  # pragma: no cover


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
) -> BuildResult:
    now = now or datetime.now(timezone.utc)
    spec, calls, notes = gather_spec(description, provider, ask, max_rounds)
    if not approve(spec):
        raise BuildError("The requirement was not approved, so nothing was built.")

    draft, used = design(provider, spec)
    calls += used
    sdm = _assemble(draft, spec, provider, now)
    failures = [f"{c.name}: {c.detail}" for c in run_checks(sdm) if c.status == FAILED]
    if failures:  # one repair attempt, fed the exact failures
        notes.append(f"The first design failed {len(failures)} check(s); the model was asked to fix them once.")
        draft, used = design(provider, spec, failures)
        calls += used
        sdm = _assemble(draft, spec, provider, now)
    return finalize(sdm, spec, out_root, force=force, notes=notes, model_calls=calls, sandbox_note=sandbox_note)


def rebuild(sdm_path: Path, out_root: Path, *, force: bool, sandbox_note: str | None = None) -> BuildResult:
    """Re-render a saved skill.sdm.json. No model call: the same definition always gives the same files."""
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
        sandbox_note=sandbox_note,
    )
