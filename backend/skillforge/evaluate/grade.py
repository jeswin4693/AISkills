"""Grade an agent's reply with simple checks that code runs. The model answers; code judges.

Seven kinds of check, all on plain text:

    contains, not_contains, starts_with     text, ignoring case
    regex                                   a short pattern (see the safety limits below)
    max_chars, max_lines                    the reply's size (blank lines are not counted)
    first_line_max_chars                    the first non-blank line, for a title or a heading

No check asks a model whether the reply is good: a model used as a judge can be talked into anything by the text it
is judging. The cost is that only what these seven can express is checked. Tone, correctness of facts and "is this a
good summary" are not, and the report says so.

A pattern written by a model and run on text written by a model could hang the program (catastrophic backtracking:
`(a+)+$` against a long run of `a`). Python's `re` has no time limit, so a pattern is refused when it is long or repeats
a repeat, and only the first MAX_GRADED characters of a reply are searched.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from ..build.models import Assertion

NUMERIC = {"max_chars", "max_lines", "first_line_max_chars"}
MAX_PATTERN = 80
MAX_GRADED = 20_000
MAX_NUMBER = 1_000_000
_REPEATED_REPEAT = re.compile(r"[+*}]\s*\)\s*[+*{?]|\)\s*[+*]\s*[+*{]")  # (a+)+  (a*)*  (a+){2,}  (a|b*)+ ...
_GROUP_THEN_REPEAT = re.compile(r"\([^()]*[+*][^()]*\)\s*[+*{]")  # a group containing a repeat, itself repeated


@dataclass
class AssertionResult:
    kind: str
    value: str
    why: str
    passed: bool
    detail: str


def assertion_problem(a: Assertion) -> str | None:
    """Why this check cannot be run (a person or a repair should fix it), or None when it is well formed."""
    value = a.value.strip()
    if not value:
        return f"{a.kind} has no value"
    if a.kind in NUMERIC:
        if not value.isdigit() or not 0 < int(value) <= MAX_NUMBER:
            return f"{a.kind} needs a whole number from 1 to {MAX_NUMBER}, not '{a.value}'"
    if a.kind == "regex":
        if len(value) > MAX_PATTERN:
            return f"the pattern '{value[:20]}...' is longer than {MAX_PATTERN} characters"
        if _REPEATED_REPEAT.search(value) or _GROUP_THEN_REPEAT.search(value):
            return f"the pattern '{value}' repeats a repeat, which can hang the checker: write it more simply"
        try:
            re.compile(value, re.IGNORECASE)
        except re.error as exc:
            return f"the pattern '{value}' is not a valid regular expression ({exc})"
    return None


def _lines(text: str) -> list[str]:
    return [ln for ln in text.splitlines() if ln.strip()]


def check_assertion(a: Assertion, reply: str) -> AssertionResult:
    problem = assertion_problem(a)
    if problem:
        return AssertionResult(a.kind, a.value, a.why, False, f"could not be checked: {problem}")
    text = reply.strip()
    value = a.value.strip()
    folded = text.casefold()
    passed, detail = False, ""
    if a.kind == "contains":
        passed = value.casefold() in folded
        detail = "" if passed else f'the reply does not contain "{value}"'
    elif a.kind == "not_contains":
        passed = value.casefold() not in folded
        detail = "" if passed else f'the reply contains "{value}", which it must not'
    elif a.kind == "starts_with":
        passed = folded.startswith(value.casefold())
        detail = "" if passed else f'the reply starts with "{text[:30]}", not "{value}"'
    elif a.kind == "regex":
        passed = re.search(value, text[:MAX_GRADED], re.IGNORECASE) is not None
        detail = "" if passed else f"the reply does not match the pattern {value}"
    elif a.kind == "max_chars":
        passed = len(text) <= int(value)
        detail = "" if passed else f"the reply is {len(text)} characters, the limit is {value}"
    elif a.kind == "max_lines":
        n = len(_lines(text))
        passed = n <= int(value)
        detail = "" if passed else f"the reply has {n} lines, the limit is {value}"
    elif a.kind == "first_line_max_chars":
        first = (_lines(text) or [""])[0].strip()
        passed = len(first) <= int(value)
        detail = "" if passed else f"the first line is {len(first)} characters, the limit is {value}"
    return AssertionResult(a.kind, a.value, a.why, passed, detail)


def grade(assertions: list[Assertion], reply: str) -> list[AssertionResult]:
    """Every check, in order. A reply passes only when all of them do."""
    return [check_assertion(a, reply) for a in assertions]
