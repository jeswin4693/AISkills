"""Deterministic checks. A check is "passed" only if it ran and succeeded; the rest are listed as not run."""

from __future__ import annotations

import re
import yaml
from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError

from ..evaluate.grade import assertion_problem
from ..results import FAILED, NOT_RUN, PASSED, WARNING, CheckResult  # noqa: F401  (re-exported for callers)
from .models import SkillDefinition
from .render import schema_for
from .scriptfiles import script_path

SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
FIELD_NAME = re.compile(r"^[a-z][a-z0-9_]*$")
MAX_DESCRIPTION = 1024


def _result(name: str, problems: list[str], ok_detail: str = "") -> CheckResult:
    return CheckResult(name, FAILED, "; ".join(problems)) if problems else CheckResult(name, PASSED, ok_detail)


def run_checks(sdm: SkillDefinition) -> list[CheckResult]:
    """Structural checks on the definition itself."""
    out: list[CheckResult] = []

    out.append(_result(
        "name is a valid slug (lowercase letters, digits, hyphens)",
        [] if SLUG.match(sdm.name) and len(sdm.name) <= 64 else [f"'{sdm.name}' is not a valid name"],
    ))

    desc = " ".join(sdm.description.split())
    problems = []
    if not desc:
        problems.append("the description is empty")
    if len(desc) > MAX_DESCRIPTION:
        problems.append(f"the description has {len(desc)} characters, the limit is {MAX_DESCRIPTION}")
    out.append(_result("description is present and at most 1024 characters", problems, f"{len(desc)} characters"))

    problems = []
    for title, fields in (("input", sdm.inputs), ("output", sdm.outputs)):
        try:
            Draft202012Validator.check_schema(schema_for(title, fields))
        except SchemaError as exc:
            problems.append(f"{title} schema: {exc.message}")
    out.append(_result("input and output schemas are valid JSON Schema", problems))

    problems = []
    for title, fields in (("input", sdm.inputs), ("output", sdm.outputs)):
        names = [f.name for f in fields]
        bad = [n for n in names if not FIELD_NAME.match(n)]
        dupes = sorted({n for n in names if names.count(n) > 1})
        if bad:
            problems.append(f"{title} names not in snake_case: {', '.join(bad)}")
        if dupes:
            problems.append(f"{title} names repeated: {', '.join(dupes)}")
    if not sdm.outputs:
        problems.append("the skill declares no outputs")
    out.append(_result("field names are unique and snake_case", problems))

    problems = []
    if not sdm.workflow:
        problems.append("the workflow has no steps")
    for i, step in enumerate(sdm.workflow, start=1):
        if not step.instruction.strip() or not step.on_failure.strip():
            problems.append(f"step {i} lacks an instruction or a failure response")
    out.append(_result("workflow has steps and every step says what to do on failure", problems, f"{len(sdm.workflow)} steps"))

    covered = {c for t in sdm.tests for c in t.covers}
    uncovered = [i for i in sdm.acceptance_criteria if i not in covered]
    out.append(_result(
        "every acceptance criterion is covered by at least one test",
        [f"not covered: {', '.join(uncovered)}"] if uncovered else [],
        f"{len(sdm.acceptance_criteria)} criteria, {len(sdm.tests)} tests",
    ))
    unknown = sorted(c for c in covered if c not in sdm.acceptance_criteria)
    out.append(_result("tests only cite acceptance criteria that exist", [f"unknown: {', '.join(unknown)}"] if unknown else []))

    kinds = {t.kind for t in sdm.tests}
    missing = [k for k in ("positive", "negative") if k not in kinds]
    out.append(_result("tests include a positive case and a negative case", [f"missing a {k} test" for k in missing]))

    broken = [f"test '{t.name}': {p}" for t in sdm.tests for a in t.assertions if (p := assertion_problem(a))]
    out.append(_result("every test's checks are well formed and can be run", broken, f"{sum(len(t.assertions) for t in sdm.tests)} check(s)"))
    if sdm.scripts:
        out += _workflow_scripts(sdm)
    return out


SCRIPT_MENTION = re.compile(r"\bscripts/[A-Za-z0-9_./-]+\.[A-Za-z0-9]+")


def _model_text(sdm: SkillDefinition) -> str:
    """Everything the model wrote that ends up in SKILL.md."""
    parts = [sdm.description, *sdm.does, *sdm.does_not, *sdm.error_handling, *sdm.limitations]
    for step in sdm.workflow:
        parts += [step.title, step.instruction, step.on_failure]
    return "\n".join(parts)


def _workflow_scripts(sdm: SkillDefinition) -> list[CheckResult]:
    """The text may name only scripts that exist, and every script should be named by a step."""
    paths = {script_path(s): s for s in sdm.scripts}
    text = _model_text(sdm)
    invented = sorted({m for m in SCRIPT_MENTION.findall(text) if m not in paths})
    steps = "\n".join(f"{s.title}\n{s.instruction}\n{s.on_failure}" for s in sdm.workflow)
    unused = [p for p in paths if p not in steps]
    return [
        _result("the instructions name only scripts that exist", [f"names scripts that are not shipped: {', '.join(invented)}"] if invented else []),
        CheckResult("every script is used by a workflow step", WARNING, "no step mentions: " + ", ".join(unused))
        if unused else CheckResult("every script is used by a workflow step", PASSED, f"{len(paths)} script(s) named in the workflow"),
    ]


def check_rendered(files: dict[str, str], sdm: SkillDefinition) -> list[CheckResult]:
    """Checks on the generated files."""
    out: list[CheckResult] = []

    problems = []
    text = files.get("SKILL.md", "")
    match = re.match(r"---\n(.*?)\n---\n", text, re.DOTALL)
    if not match:
        problems.append("SKILL.md has no front matter")
    else:
        try:
            meta = yaml.safe_load(match.group(1)) or {}
        except yaml.YAMLError as exc:
            meta, problems = {}, [f"front matter is not valid YAML: {exc}"]
        if not problems and meta.get("name") != sdm.name:
            problems.append("the front matter name differs from the definition")
        if not problems and meta.get("description") != " ".join(sdm.description.split()):
            problems.append("the front matter description differs from the definition")
    out.append(_result("SKILL.md front matter parses back to the same name and description", problems))
    return out


def not_run_checks(sandbox_note: str | None = None, has_scripts: bool = False, evaluated: bool = False) -> list[CheckResult]:
    """What no code has checked. With scripts, the sandbox row is replaced by the real per-case results, and when the
    test cases were run against a model (`evaluated`) their own rows replace the "not run against an agent" row."""
    if has_scripts:
        first = CheckResult(
            "scripts tested on real project data", NOT_RUN,
            "The script cases use small samples written by the model. They show the scripts run in a locked sandbox "
            "and print the expected text on those samples. They do not show the scripts are right on your real files. "
            "The expected text is also chosen by the model, so a passing case can still be a weak test: read "
            "tests/script_cases.json. When an agent uses this skill, the scripts run on your machine (a different "
            "operating system can behave differently), not in the sandbox.",
        )
    else:
        note = f" Sandbox on this machine: {sandbox_note}" if sandbox_note else ""
        first = CheckResult(
            "scripts run in a sandbox", NOT_RUN, "This skill has no scripts, so there was nothing to run. To add some, build with helper scripts switched on (the checkbox in the web builder, or --scripts on the command line)." + note
        )
    agent = [] if evaluated else [CheckResult(
        "test cases executed against a real agent", NOT_RUN,
        "Not asked for. Build with --eval, or run `skillforge eval <folder>`, to run the test cases against a model (text-only skills). "
        "A model with no tools is not an agent: skills that read files or run commands cannot be run this way.",
    )]
    return [
        first,
        *agent,
        CheckResult("instructions free of conflicting rules", NOT_RUN, "Only structural checks exist. No semantic analyser has been built."),
        CheckResult("security review of the generated text", NOT_RUN, "Not automated. Read the instructions yourself before using the skill."),
    ]
