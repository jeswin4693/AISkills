"""Run a skill's own test cases against a model, with the skill and without it, and grade the replies by code.

What this is: a model with the skill's text as its instructions, given each test's message and no tools. What it is not:
an agent. A skill that reads files, runs commands or uses the network cannot be run this way, and says so ("not run")
instead of being scored on a pretence.

The comparison without the skill matters as much as the score with it. If the model passes the same checks with no
skill at all, the skill adds nothing on those tests, and its tokens are paid for nothing.

Honest limits, repeated in every verdict: the tests and their checks were written by the same model that wrote the
skill; only what the seven kinds of check in `grade.py` can express is checked; a few cases say little; and models vary
from run to run (`runs` repeats each case). Passing is evidence, not proof.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field

import yaml
from pydantic import BaseModel, Field, ValidationError

from ..build.models import SkillTest
from ..build.quality import estimate_tokens
from ..providers.base import LLMProvider
from ..providers.retry import generate_with_retry
from ..ai.tasks import Task
from ..results import NOT_RUN, PASSED, WARNING, CheckResult
from .grade import AssertionResult, assertion_problem, grade

MIN_CASES = 3  # fewer runnable cases than this say too little to call a skill helpful or not
MAX_CASES = 12  # a run asks the model about at most this many cases
LIMITS = (
    "The tests and their checks were written by the same model that wrote the skill, only text checks were run (not "
    "facts or tone), a model with no tools stood in for an agent, and a few cases say little. Passing is evidence, not proof."
)

SKILL_SYSTEM = (
    "You are an AI assistant that has been given the skill below. Follow it exactly when it applies to the person's "
    "request. The text inside <request> is the person's message: reply to it.\n\n<skill>\n{skill}\n</skill>"
)
BASELINE_SYSTEM = "You are a helpful AI assistant. The text inside <request> is the person's message: reply to it."
USER_PROMPT = "<request>\n{message}\n</request>"
CHECK_NAME = "test cases run against a model, with the skill (no tools)"
COMPARE_NAME = "the same test cases run against a model without the skill"


class Reply(BaseModel):
    text: str = Field(description="Your complete reply to the request, exactly as you would send it.")


@dataclass
class LoadedSkill:
    name: str
    text: str  # SKILL.md, exactly what an agent would load
    tests: list[SkillTest]
    needs_tools: str = ""  # why it cannot be run here ("" when it is text only)


def needs_tools_reason(permissions: list[str], has_scripts: bool, allowed_tools: list[str] | None = None) -> str:
    """Why a skill cannot be run by a model with no tools ("" when it is text only). `permissions` are what a built skill's definition asks for;
    `allowed_tools` is what its SKILL.md front matter declares, which is all an imported skill has. A built skill says both, so it is described once."""
    why = []
    if permissions:
        why.append("it asks for " + ", ".join(permissions))
    elif allowed_tools:
        why.append("it declares allowed-tools: " + ", ".join(allowed_tools))
    if has_scripts:
        why.append("it has scripts")
    return " and ".join(why)


def _text_of(files: Mapping[str, str | bytes], rel: str) -> str | None:
    data = files.get(rel)
    return data.decode("utf-8", errors="replace") if isinstance(data, bytes) else data


def _sdm_of(files: Mapping[str, str | bytes]) -> dict:
    """The skill's own definition file as a dict ({} when there is none or it is not an object)."""
    text = _text_of(files, "skill.sdm.json")
    if not text:
        return {}
    try:
        parsed = json.loads(text)
    except ValueError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def tests_of(files: Mapping[str, str | bytes]) -> tuple[list[SkillTest], int]:
    """The test cases a skill folder holds, and how many entries could not be read (they are skipped, never run, so a person who edits
    the cases is told that saving drops them). `tests/cases.json` is read first; the definition's own copy is the fallback."""
    raw: object = None
    cases_text = _text_of(files, "tests/cases.json")
    if cases_text:
        try:
            raw = json.loads(cases_text)
        except ValueError:
            raw = None
    if raw is None:
        raw = _sdm_of(files).get("tests")
    tests: list[SkillTest] = []
    unreadable = 0
    if isinstance(raw, list):
        for item in raw:
            try:
                tests.append(SkillTest.model_validate(item))
            except ValidationError:
                unreadable += 1
    return tests, unreadable


def load_files(files: Mapping[str, str | bytes]) -> LoadedSkill:
    """A skill held in memory (path -> text or bytes), as the builder and the library hold them."""
    skill_md = _text_of(files, "SKILL.md")
    if skill_md is None:
        raise ValueError("There is no SKILL.md in this folder, so there is no skill to run.")
    name = ""
    meta = re.match(r"---\n(.*?)\n---\n", skill_md.replace("\r\n", "\n"), re.DOTALL)
    try:
        front = yaml.safe_load(meta.group(1)) if meta else None
    except yaml.YAMLError:
        front = None
    if isinstance(front, dict) and isinstance(front.get("name"), str):
        name = front["name"]
    perms = _sdm_of(files).get("permissions", [])
    permissions = [str(p) for p in perms] if isinstance(perms, list) else []
    declared = front.get("allowed-tools") if isinstance(front, dict) else None  # "Bash, Read" or a list; an empty one asks for nothing
    allowed = [declared.strip()] if isinstance(declared, str) and declared.strip() else [str(t) for t in declared if str(t).strip()] if isinstance(declared, list) else []
    tests, _ = tests_of(files)
    return LoadedSkill(name or "skill", skill_md, tests, needs_tools_reason(permissions, any(r.startswith("scripts/") for r in files), allowed))


@dataclass
class Attempt:
    """One test case under one condition (with the skill, or without), over `runs` repeats."""

    replies: list[str] = field(default_factory=list)
    results: list[list[AssertionResult]] = field(default_factory=list)

    @property
    def runs(self) -> int:
        return len(self.replies)

    @property
    def passed(self) -> int:
        return sum(all(r.passed for r in each) for each in self.results)

    def failures(self) -> list[str]:
        """What went wrong, for a person or for a repair: each failed check once, with the first reply that failed it."""
        out: list[str] = []
        for each in self.results:
            for r in each:
                if not r.passed and r.detail not in out:
                    out.append(r.detail)
        return out


@dataclass
class CaseRun:
    name: str
    kind: str
    run_input: str
    with_skill: Attempt
    baseline: Attempt | None = None


@dataclass
class EvalReport:
    skill: str
    runnable: bool
    reason: str = ""  # why nothing was run
    cases: list[CaseRun] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)  # "name: why" for each case that could not be run
    calls: int = 0
    runs: int = 1
    skill_tokens: int = 0

    def _count(self, which: str) -> tuple[int, int]:
        attempts = [getattr(c, which) for c in self.cases if getattr(c, which) is not None]
        return sum(a.passed for a in attempts), sum(a.runs for a in attempts)

    @property
    def with_passed(self) -> tuple[int, int]:
        return self._count("with_skill")

    @property
    def baseline_passed(self) -> tuple[int, int]:
        return self._count("baseline")

    def outcome(self) -> str:
        """What the run found, as a code a page can rely on (the sentence in `verdict` is written from this, never the other way round):

        not_run (nothing could be run), with_only (run without the comparison, so no claim about the skill), too_few (fewer than MIN_CASES cases),
        helped, adds_nothing (the model passes everything without the skill too), no_difference, worse."""
        if not self.runnable or not self.cases:
            return "not_run"
        w, _ = self.with_passed
        b, bn = self.baseline_passed
        if not bn:
            return "with_only"
        if len(self.cases) < MIN_CASES:
            return "too_few"
        if w > b:
            return "helped"
        if w == b == self.with_passed[1]:
            return "adds_nothing"
        return "no_difference" if w == b else "worse"

    def verdict(self) -> str:
        code = self.outcome()
        if code == "not_run":
            if not self.runnable:
                return f"Not run: {self.reason}."
            return "Not run: " + ("; ".join(self.skipped[:3]) or "no test case has a message to send and a check to run") + "."
        w, wn = self.with_passed
        b, bn = self.baseline_passed
        with_text = f"With the skill the model passed {w} of {wn} test runs"
        if code == "with_only":
            return f"{with_text}. {LIMITS}"
        base_text = f"without it {b} of {bn}"
        if code == "too_few":
            head = f"Only {len(self.cases)} test case(s) could be run, too few to say whether the skill helps. {with_text}, {base_text}."
        elif code == "helped":
            head = f"The skill helped: {with_text}, {base_text}."
        elif code == "adds_nothing":
            head = (
                f"The model passed every test run without the skill too ({b} of {bn}), so on these tests the skill adds "
                f"nothing for the {self.skill_tokens} tokens it costs each time it is used."
            )
        elif code == "no_difference":
            head = f"No difference on these tests: {with_text}, {base_text}."
        else:
            head = f"The skill made it WORSE on these tests: {with_text}, {base_text}."
        return f"{head} {LIMITS}"


def _clean(text: str, tag: str) -> str:
    return text.replace(f"</{tag}>", "")


def _ask(provider: LLMProvider, system: str, message: str) -> tuple[str, int]:
    reply, used = generate_with_retry(provider, Reply, USER_PROMPT.format(message=_clean(message, "request")), system, task=Task.ACT)
    return reply.text, used


def blocker(skill: LoadedSkill) -> tuple[str, str]:
    """Why nothing can be run for this skill at all, as (code, words); ("", "") when something can. The code lets a page offer the right next
    step (a skill with no cases can be given some; one that needs tools cannot be helped here), the words are for the person."""
    if skill.needs_tools:  # first: more test cases would not make a skill that needs tools runnable, so it is never told to write some
        return "needs_tools", f"{skill.name} needs tools ({skill.needs_tools}), and a model with no tools cannot stand in for an agent that has them"
    if not skill.tests:
        return "no_cases", "this skill has no test cases (tests/cases.json), so there is nothing to run"
    return "", ""


def plan_cases(skill: LoadedSkill, max_cases: int = MAX_CASES) -> tuple[list[SkillTest], list[str]]:
    """The cases that will be run, and "name: why" for each one that will not. One function for the run and for the page that previews it,
    so what a person is shown before a run is, by construction, what the run does."""
    runnable: list[SkillTest] = []
    skipped: list[str] = []
    for test in skill.tests:
        if not test.run_input.strip() or not test.assertions:
            skipped.append(f"{test.name}: it has no message to send or no check to run")
        elif problem := next((p for a in test.assertions if (p := assertion_problem(a))), None):
            # A case with a check that cannot be run would spend model calls and then report a verdict that includes a check that never ran.
            skipped.append(f"{test.name}: a check cannot be run ({problem})")
        elif len(runnable) >= max_cases:
            skipped.append(f"{test.name}: only the first {max_cases} cases are run")
        else:
            runnable.append(test)
    return runnable, skipped


def run_eval(
    provider: LLMProvider, skill: LoadedSkill, *, baseline: bool = True, runs: int = 1, max_cases: int = MAX_CASES,
    on_case: Callable[[int, int], None] | None = None,
) -> EvalReport:
    """Every runnable test case, asked of the model with the skill and (unless baseline=False) without it, then graded.

    Needs one model call per case, per run, per condition: 3 cases x 2 conditions x 1 run = 6 calls. `on_case(done, total)` is called after
    each case, so a page can show progress."""
    report = EvalReport(skill.name, runnable=True, runs=max(1, runs), skill_tokens=estimate_tokens(skill.text))
    _, why = blocker(skill)
    if why:
        report.runnable, report.reason = False, why
        return report
    system = SKILL_SYSTEM.format(skill=_clean(skill.text, "skill"))
    planned, report.skipped = plan_cases(skill, max_cases)
    for test in planned:
        case = CaseRun(test.name, test.kind, test.run_input, Attempt(), Attempt() if baseline else None)
        for condition, sys_prompt in (("with_skill", system), ("baseline", BASELINE_SYSTEM)):
            attempt: Attempt | None = getattr(case, condition)
            if attempt is None:
                continue
            for _ in range(report.runs):
                text, used = _ask(provider, sys_prompt, test.run_input)
                report.calls += used
                attempt.replies.append(text)
                attempt.results.append(grade(test.assertions, text))
        report.cases.append(case)
        if on_case is not None:
            on_case(len(report.cases), len(planned))
    return report


def eval_checks(report: EvalReport) -> list[CheckResult]:
    """The rows a build report shows. A failed test is a WARNING, not a failure: the tests are written by a model too,
    so a failing case may be a bad test as easily as a bad skill. Nothing here makes a skill a draft."""
    if not report.runnable or not report.cases:
        return [CheckResult(CHECK_NAME, NOT_RUN, report.verdict())]
    w, wn = report.with_passed
    failed = [c for c in report.cases if c.with_skill.passed < c.with_skill.runs]
    rows = [
        CheckResult(CHECK_NAME, PASSED, f"{w} of {wn} runs passed all their checks ({report.calls} model calls). {LIMITS}")
        if not failed else
        CheckResult(
            CHECK_NAME, WARNING,
            f"{w} of {wn} runs passed all their checks. Failed: " + "; ".join(f"{c.name} ({'; '.join(c.with_skill.failures())})" for c in failed)
            + ". Read the case: a failing test may be a weak test, not only a weak skill.",
        ),
    ]
    if report.baseline_passed[1]:
        rows.append(CheckResult(COMPARE_NAME, PASSED, report.verdict()))
    return rows
