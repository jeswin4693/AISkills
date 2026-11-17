"""Deterministic checks. A check is "passed" only if it ran and succeeded; the rest are listed as not run."""

from __future__ import annotations

import re
import yaml
from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError

from ..results import FAILED, NOT_RUN, PASSED, WARNING, CheckResult  # noqa: F401  (re-exported for callers)
from .models import SkillDefinition
from .render import schema_for

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
    return out


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


def not_run_checks(sandbox_note: str | None = None) -> list[CheckResult]:
    sandbox = "This tool generates no scripts yet." + (f" Sandbox on this machine: {sandbox_note}" if sandbox_note else "")
    return [
        CheckResult("scripts run in a sandbox", NOT_RUN, sandbox),
        CheckResult("test cases executed against a real agent", NOT_RUN, "There is no agent test harness yet. The test cases are data only."),
        CheckResult("instructions free of conflicting rules", NOT_RUN, "Only structural checks exist. No semantic analyser has been built."),
        CheckResult("security review of the generated text", NOT_RUN, "Not automated. Read the instructions yourself before using the skill."),
    ]
