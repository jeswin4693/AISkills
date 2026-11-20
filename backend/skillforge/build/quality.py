"""What makes a generated skill work well and cost little, decided by code. No model, no I/O.

A skill is read by an agent in three tiers, and each costs tokens:

    always         the name and the description (the agent sees these for every skill, on every task)
    when used      SKILL.md (loaded when the description matches the task)
    only if asked  scripts, schemas, tests, README (the agent opens them only if SKILL.md sends it there)

So the description must be short *and* must say when to use the skill, or it never triggers. SKILL.md must hold what
changes the agent's behaviour and nothing it already knows. This module:

- builds the description from the model's one-sentence "what" and its trigger phrases (code composes it, so the
  "when" is never forgotten), and carries the person's approved requirement into SKILL.md word for word;
- checks the generated skill for the things that make instructions weak: no trigger phrases, an input the steps never
  use, an output no step produces, vague wording, steps too long to follow, requirement text that went missing;
- estimates what the skill costs to use.

These are heuristics and say so: a skill can pass all of them and still be a poor skill, and a good one can trip a
warning. They find the common, mechanical weaknesses. Whether the instructions are *right* is not decided here, and
test cases are still never run against an agent (see `not_run_checks`).
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from ..results import FAILED, PASSED, WARNING, CheckResult
from .models import RequirementSpec, SkillDefinition

MAX_DESCRIPTION = 1024
MAX_TRIGGERS = 5
MAX_TRIGGER_CHARS = 80
CHARS_PER_TOKEN = 4  # an estimate: real tokenizers differ by model and by language
LONG_STEP_WORDS = 60
HEAVY_DESCRIPTION_TOKENS = 150  # ~600 characters, paid on every task even when the skill is not used
HEAVY_SKILL_TOKENS = 2000  # ~8,000 characters, paid each time the skill is used

_NONE_LIKE = {"none", "n/a", "na", "nothing", "no", "not applicable", "no constraints", "none stated"}
_USE_WHEN = re.compile(r"\buse\b[^.]{0,30}\b(when|whenever|if|after|before)\b|\btriggers?\b[^.]{0,15}\b(when|on)\b", re.I)
_WHEN = re.compile(r"\bwhen(ever)?\b|\bif (the )?(user|you|someone|a person)\b", re.I)
_VAGUE = re.compile(
    r"\b(as (needed|appropriate|required|necessary|you see fit)|if (necessary|needed|applicable|appropriate)|"
    r"where (appropriate|possible|applicable)|appropriately|properly|best practices?|good practices?|"
    r"and so on|and so forth|high[- ]quality|carefully|thoroughly|as much as possible|etc\.)",
    re.I,
)


VAGUE = _VAGUE  # the same wording check, for the other kinds' builders


def norm(text: str) -> str:
    """Whitespace collapsed and case folded: how requirement text is compared with SKILL.md."""
    return " ".join(str(text).split()).casefold()


def is_none_like(text: str) -> bool:
    return norm(text).strip(" .") in _NONE_LIKE


def estimate_tokens(text: str) -> int:
    return -(-len(text) // CHARS_PER_TOKEN) if text else 0  # ceiling


# ---- the description ---------------------------------------------------------------------------------


def says_use_when(description: str) -> bool:
    """A clause such as "Use when ..." or "Use this after ...": what composing the description looks for."""
    return bool(_USE_WHEN.search(description))


def has_when_clause(description: str) -> bool:
    """Lenient: any mention of when. What the quality check accepts."""
    return says_use_when(description) or bool(_WHEN.search(description))


def clean_triggers(triggers: Sequence[str]) -> list[str]:
    """Short, distinct trigger phrases without trailing punctuation. At most five."""
    out: list[str] = []
    seen: set[str] = set()
    for raw in triggers:
        t = " ".join(str(raw).split()).strip(" .;,:!?\"'")
        if not t or len(t) > MAX_TRIGGER_CHARS or t.casefold() in seen:
            continue
        seen.add(t.casefold())
        out.append(t)
    return out[:MAX_TRIGGERS]


def _quoted_list(phrases: Sequence[str]) -> str:
    quoted = [f'"{p}"' for p in phrases]
    if len(quoted) <= 2:
        return " or ".join(quoted)
    return ", ".join(quoted[:-1]) + ", or " + quoted[-1]


USE_WHEN = "Use when the request involves"
USE_PROACTIVELY = "Use proactively when the request involves"  # how an agent is told it may be picked without being named


def compose_description(what: str, triggers: Sequence[str], limit: int = MAX_DESCRIPTION, lead: str = USE_WHEN) -> str:
    """'<what it does>. Use when the request involves "<phrase>", "<phrase>", or "<phrase>".' Built by code, so the
    "when" is never forgotten. No colon, so the front matter is plain text that any parser reads the same way.
    `lead` is the wording before the phrases: an agent says "Use proactively when ..." so Claude is more willing to hand it work.

    A description that already says when (an older skill, or a model that ignored the instruction) is left alone."""
    what = " ".join(what.split())
    if what and what[-1] not in ".!?":
        what += "."
    if says_use_when(what):
        return what[:limit].rstrip()
    chosen: list[str] = []
    for t in clean_triggers(triggers):
        if len(f"{what} {lead} {_quoted_list([*chosen, t])}.") > limit:
            break
        chosen.append(t)
    return f"{what} {lead} {_quoted_list(chosen)}." if chosen else what


# ---- what the agent is told, from the approved requirement -------------------------------------------


@dataclass
class Lines:
    """The parts of SKILL.md that come from the person's approved requirement, not from the model's wording."""

    rules: list[str]  # the person's constraints, word for word
    donts: list[str]  # what the design says the skill must not do
    done_when: list[str]  # the person's acceptance criteria, word for word
    failure: list[str]  # the person's failure behaviour first, then the model's error handling
    example_given: str = ""
    example_expect: str = ""

    def carried(self) -> list[str]:
        """The lines that are the person's own approved requirement: each must appear in SKILL.md."""
        return [*self.rules, *self.done_when, *self.failure[:1]]


def sentence(text: str) -> str:
    """The words with whitespace collapsed and the first letter capitalised. Nothing else is changed."""
    t = " ".join(str(text).split())
    return t[:1].upper() + t[1:]


_NEGATION = re.compile(r"^(?:it |the skill |this skill )?(?:does not|doesn't|will not|won't|must not|should not|cannot|can't|never)\s+", re.I)
_STOP = {
    "a", "an", "the", "if", "is", "are", "it", "its", "for", "of", "or", "and", "to", "no", "not", "in", "on", "at", "be",
    "this", "that", "then", "with", "you", "they", "them", "their", "any", "do", "does",
}
SIMILAR = 0.4  # share of content words two lines have in common before the later one is treated as a repeat


def core(text: str) -> str:
    """What a "does not" line forbids, without the lead-in: "It does not look at files" becomes "look at files"."""
    return _NEGATION.sub("", " ".join(str(text).split())).strip()


def _content(text: str) -> set[str]:
    words = re.findall(r"[a-z0-9_]+", text.casefold())
    return {w.rstrip("s") if len(w) > 3 else w for w in words if w not in _STOP}


def similar(a: str, b: str, threshold: float = SIMILAR) -> bool:
    """Two lines that say nearly the same thing: most of their content words are shared. Heuristic, and conservative:
    a line with fewer than three content words is never called a repeat."""
    x, y = _content(a), _content(b)
    return len(x) >= 3 and len(y) >= 3 and len(x & y) / len(x | y) >= threshold


def requirement_lines(sdm: SkillDefinition, spec: RequirementSpec) -> Lines:
    done = [sentence(t) for t in sdm.acceptance_criteria.values() if t.strip() and not is_none_like(t)]
    seen = {norm(t) for t in done}  # a constraint that repeats a criterion is said once
    rules: list[str] = []
    for c in spec.constraints:
        if c.strip() and not is_none_like(c) and norm(c) not in seen:
            rules.append(sentence(c))
            seen.add(norm(c))
    said = {norm(core(r)) for r in rules}  # a "do not" the person already stated as a rule is not said again
    donts: list[str] = []
    for d in sdm.does_not:
        c = core(d)
        if c.strip() and not is_none_like(c) and norm(c) not in said:
            donts.append(sentence(c))
            said.add(norm(c))
    failure: list[str] = []
    if spec.failure_behavior.strip() and not is_none_like(spec.failure_behavior):
        failure.append(sentence(spec.failure_behavior))
    for e in sdm.error_handling:  # the person's own line first; a later line that only repeats an earlier one is left out
        if e.strip() and not is_none_like(e) and not any(norm(e) == norm(f) or similar(e, f) for f in failure):
            failure.append(sentence(e))
    positive = next((t for t in sdm.tests if t.kind == "positive"), None)
    return Lines(
        rules, donts, done, failure,
        " ".join(positive.input_description.split()) if positive else "",
        " ".join(positive.expected_result.split()) if positive else "",
    )


# ---- checks on the design (before any file is written) -----------------------------------------------


def _steps_text(sdm: SkillDefinition) -> str:
    return "\n".join(f"{s.title}\n{s.instruction}\n{s.on_failure}" for s in sdm.workflow)


def _mentions(text: str, field_name: str) -> bool:
    """The field's exact name, or its name as words (`changes_description` or "changes description")."""
    exact = re.search(rf"(?<![A-Za-z0-9_]){re.escape(field_name)}(?![A-Za-z0-9_])", text)
    return bool(exact) or norm(field_name.replace("_", " ")) in norm(text)


def quality_checks(sdm: SkillDefinition) -> list[CheckResult]:
    """Heuristics on the design. They warn: a person should read them, and the one repair attempt is asked to fix them."""
    out: list[CheckResult] = []

    name = "the description says when to use the skill, with concrete trigger phrases"
    triggers = clean_triggers(sdm.triggers)
    if not has_when_clause(sdm.description):
        out.append(CheckResult(name, WARNING, "the description does not say when to use the skill, so an agent may never pick it. Add a clause that starts with 'Use when'."))
    elif len(triggers) < 2:
        out.append(CheckResult(name, WARNING, "the description says when, but gives fewer than two concrete trigger phrases (what a person would actually say)."))
    else:
        out.append(CheckResult(name, PASSED, f"{len(triggers)} trigger phrases"))

    text = _steps_text(sdm)
    name = "every input and output is named in the workflow"
    unused_in = [f.name for f in sdm.inputs if not _mentions(text, f.name)]
    unused_out = [f.name for f in sdm.outputs if not _mentions(text, f.name)]
    problems = []
    if unused_in:
        problems.append("no step uses the input " + ", ".join(f"`{n}`" for n in unused_in) + " (the agent may ignore it)")
    if unused_out:
        problems.append("no step produces the output " + ", ".join(f"`{n}`" for n in unused_out) + " (nothing says how to make it)")
    out.append(CheckResult(name, WARNING, "; ".join(problems)) if problems else CheckResult(name, PASSED, f"{len(sdm.inputs)} inputs, {len(sdm.outputs)} outputs"))

    name = "the workflow avoids vague wording"
    vague: list[str] = []
    for i, s in enumerate(sdm.workflow, start=1):
        found = sorted({m.group(0).lower() for m in _VAGUE.finditer(f"{s.instruction} {s.on_failure}")})
        if found:
            vague.append(f"step {i}: " + ", ".join(f"'{f}'" for f in found))
    out.append(CheckResult(name, WARNING, "; ".join(vague) + ". Say exactly what to do instead.") if vague else CheckResult(name, PASSED))

    positive = next((t for t in sdm.tests if t.kind == "positive"), None)
    if positive is not None:  # an agent copies its examples, so a garbled one teaches the wrong thing
        name = "the worked example does not repeat itself"
        words = re.findall(r"\w+", positive.expected_result.casefold())
        seen_runs: set[tuple[str, ...]] = set()
        repeated = ""
        for i in range(len(words) - 3):
            run = tuple(words[i:i + 4])
            if run in seen_runs:
                repeated = " ".join(run)
                break
            seen_runs.add(run)
        out.append(
            CheckResult(name, WARNING, f"the expected output of the first positive test says '{repeated}' twice. An agent copies its examples: write one clean, literal expected output.")
            if repeated else CheckResult(name, PASSED)
        )

    if not sdm.permissions and not sdm.scripts:  # text only: a model can stand in for an agent, so its tests can be run
        name = "every test can be run against a model and graded by code"
        unrunnable = [t.name for t in sdm.tests if not t.run_input.strip() or not t.assertions]
        out.append(
            CheckResult(name, WARNING, "no message to send or no check to run in: " + ", ".join(unrunnable) + ". Without them a test cannot be run, so nobody learns whether the skill works.")
            if unrunnable else CheckResult(name, PASSED, f"{len(sdm.tests)} test(s)")
        )

    name = "every workflow step is short enough to follow"
    long_steps = [f"step {i} ({len(s.instruction.split())} words)" for i, s in enumerate(sdm.workflow, start=1) if len(s.instruction.split()) > LONG_STEP_WORDS]
    out.append(
        CheckResult(name, WARNING, ", ".join(long_steps) + f" is longer than {LONG_STEP_WORDS} words. Split it, or cut what the agent already knows.")
        if long_steps else CheckResult(name, PASSED, f"at most {LONG_STEP_WORDS} words each")
    )
    return out


def quality_warnings(sdm: SkillDefinition) -> list[str]:
    """What the repair attempt is told, from the design alone."""
    return [f"{c.name}: {c.detail}" for c in quality_checks(sdm) if c.status != PASSED]


# ---- checks on the written files ---------------------------------------------------------------------


@dataclass
class TokenCost:
    always: int  # name + description: in the agent's context for every task
    when_used: int  # SKILL.md: loaded when the description matches
    on_demand: int  # every other file: read only if SKILL.md sends the agent there


def token_cost(files: Mapping[str, str], sdm: SkillDefinition) -> TokenCost:
    other = sum(estimate_tokens(text) for rel, text in files.items() if rel not in ("SKILL.md", "report.md"))
    return TokenCost(
        estimate_tokens(f"{sdm.name} {' '.join(sdm.description.split())}"), estimate_tokens(files.get("SKILL.md", "")), other,
    )


def rendered_quality(files: Mapping[str, str], sdm: SkillDefinition, spec: RequirementSpec) -> list[CheckResult]:
    """Checks on SKILL.md as written: the requirement reached it, it has an example, and what it costs."""
    out: list[CheckResult] = []
    skill = norm(files.get("SKILL.md", ""))
    lines = requirement_lines(sdm, spec)

    name = "the approved requirement reached SKILL.md word for word"
    carried = lines.carried()
    missing = [t for t in carried if norm(t) not in skill]
    out.append(
        CheckResult(name, FAILED, "missing from SKILL.md: " + "; ".join(f"'{m}'" for m in missing[:3]))
        if missing else CheckResult(name, PASSED, f"{len(carried)} requirement line(s) carried over")
    )

    name = "SKILL.md includes a worked example"
    has_example = "## Example" in files.get("SKILL.md", "")
    out.append(
        CheckResult(name, PASSED, "from the positive test case")
        if has_example else CheckResult(name, WARNING, "there is no positive test case to take an example from, so the agent has none to copy")
    )

    cost = token_cost(files, sdm)
    name = "token cost of using the skill (an estimate)"
    detail = (
        f"about {cost.always} tokens always loaded (name and description) and {cost.when_used} when the skill is used (SKILL.md); "
        f"{cost.on_demand} more sit in other files the agent opens only if it needs them. Estimated at {CHARS_PER_TOKEN} characters per token."
    )
    heavy = []
    if cost.always > HEAVY_DESCRIPTION_TOKENS:
        heavy.append(f"the description is paid on every task: shorten it below about {HEAVY_DESCRIPTION_TOKENS} tokens")
    if cost.when_used > HEAVY_SKILL_TOKENS:
        heavy.append("SKILL.md is long: move detail the agent rarely needs into a file it opens on demand, or cut it")
    out.append(CheckResult(name, WARNING, "; ".join(heavy) + ". " + detail) if heavy else CheckResult(name, PASSED, detail))
    return out
