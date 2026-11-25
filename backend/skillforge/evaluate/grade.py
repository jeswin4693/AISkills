"""Grade an agent's reply with simple checks that code runs. The model answers; code judges.

Seven kinds of check, all on plain text:

    contains, not_contains, starts_with     text, ignoring case
    regex                                   a short pattern (see the safety limits below)
    max_chars, max_lines                    the reply's size (blank lines are not counted)
    first_line_max_chars                    the first non-blank line, for a title or a heading

No check asks a model whether the reply is good: a model used as a judge can be talked into anything by the text it
is judging. The cost is that only what these seven can express is checked. Tone, correctness of facts and "is this a
good summary" are not, and the report says so.

A pattern written by a person or a model and run on text written by a model could hang the program (catastrophic backtracking:
`(a+)+$` against a long run of `a`). Python's `re` has no time limit and holds the interpreter while it runs, so two things are done:

  1. a pattern is refused up front, in plain words, when it is long or when a repeat contains another repeat or a choice between
     alternatives (read from the parsed pattern, not guessed from its text: `(a|aa)+$` is refused, `(\\d+)?kg` is not), and
  2. every pattern that is accepted is RUN IN A CHILD PROCESS with a time limit and killed when it is over, because no rule about the
     text of a pattern can see every slow one (`\\w*\\w*\\w*\\w*x` has no nesting at all). A pattern that is stopped fails its check and says so.

Only the first MAX_GRADED characters of a reply are searched.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from dataclasses import dataclass

from ..build.models import Assertion

try:  # the parsed form of a pattern; a private module, so a missing one must degrade to the text rules below, never break grading
    from re import _constants as _c
    from re import _parser as _sre_parser
except ImportError:  # pragma: no cover - only on a Python without these modules
    _c = _sre_parser = None  # type: ignore[assignment]

NUMERIC = {"max_chars", "max_lines", "first_line_max_chars"}
MAX_PATTERN = 80
MAX_GRADED = 20_000
MAX_NUMBER = 1_000_000
REGEX_TIMEOUT = 1.5  # seconds one pattern may take on one reply; an ordinary one takes microseconds, the child process about 0.07 s to start
_REPEATED_REPEAT = re.compile(r"[+*}]\s*\)\s*[+*{?]|\)\s*[+*]\s*[+*{]")  # (a+)+  (a*)*  (a+){2,}  (a|b*)+ ... (only used without the parser)
_GROUP_THEN_REPEAT = re.compile(r"\([^()]*[+*][^()]*\)\s*[+*{]")  # a group containing a repeat, itself repeated (same)
_CHILD = "import json, re, sys\nd = json.load(sys.stdin)\nsys.stdout.write(json.dumps(re.search(d['p'], d['t'], re.IGNORECASE) is not None))\n"


def _nodes(sub: object) -> list:
    return list(getattr(sub, "data", sub))  # a parsed pattern is a list of (op, argument) pairs, held in .data


def _repeat_ops() -> tuple:
    return tuple(getattr(_c, name) for name in ("MAX_REPEAT", "MIN_REPEAT", "POSSESSIVE_REPEAT") if hasattr(_c, name))


def _inner(op, arg) -> list:
    """The patterns nested directly inside one node: a repeat's body, a group, the alternatives of a choice, a look-around."""
    if op in _repeat_ops():
        return [arg[2]]
    if op == _c.SUBPATTERN:
        return [arg[3]]
    if op == _c.BRANCH:
        return list(arg[1])
    if op in (_c.ASSERT, _c.ASSERT_NOT):
        return [arg[1]]
    if hasattr(_c, "ATOMIC_GROUP") and op == _c.ATOMIC_GROUP:
        return [arg]
    if op == _c.GROUPREF_EXISTS:
        return [p for p in arg[1:] if p]
    return []


def _can_repeat(op, arg) -> bool:
    return op in _repeat_ops() and arg[1] > 1  # {0,1} is not a repeat that can multiply work; `*`, `+` and {2,} are


def _ambiguous(sub: object) -> bool:
    """Whether a pattern holds a repeat that can repeat, or a choice between alternatives, anywhere inside it."""
    for op, arg in _nodes(sub):
        if _can_repeat(op, arg) or op == _c.BRANCH:
            return True
        if any(_ambiguous(child) for child in _inner(op, arg)):
            return True
    return False


def _backtracks_exponentially(sub: object) -> bool:
    """A repeat that can repeat whose body can match in more than one way: (a+)+  (a|aa)*  (\\d|\\d\\d)+  (\\w+\\s?)*"""
    for op, arg in _nodes(sub):
        if _can_repeat(op, arg) and _ambiguous(arg[2]):
            return True
        if any(_backtracks_exponentially(child) for child in _inner(op, arg)):
            return True
    return False


def _repeats_a_repeat(value: str) -> bool:
    if _sre_parser is None:  # pragma: no cover
        return bool(_REPEATED_REPEAT.search(value) or _GROUP_THEN_REPEAT.search(value))
    try:
        return _backtracks_exponentially(_sre_parser.parse(value))
    except RecursionError:  # pragma: no cover - the length limit keeps a pattern far from this
        return True


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
        # isdigit() is also true for "²" and "①", which int() refuses, and int() itself refuses a string of more than 4,300 digits
        if not (value.isascii() and value.isdigit()) or len(value) > len(str(MAX_NUMBER)) or not 0 < int(value) <= MAX_NUMBER:
            return f"{a.kind} needs a whole number from 1 to {MAX_NUMBER}, not '{a.value[:40]}'"
    if a.kind == "regex":
        if len(value) > MAX_PATTERN:
            return f"the pattern '{value[:20]}...' is longer than {MAX_PATTERN} characters"
        try:
            re.compile(value, re.IGNORECASE)
        except re.error as exc:
            return f"the pattern '{value}' is not a valid regular expression ({exc})"
        if _repeats_a_repeat(value):
            return f"the pattern '{value}' repeats a repeat or chooses between alternatives inside a repeat, which can hang the checker: write it more simply"
    return None


def _search(pattern: str, text: str) -> tuple[bool | None, str]:
    """Whether the pattern is found in the text, judged in a child process that is killed after REGEX_TIMEOUT: (True or False, "") or
    (None, why it could not be judged). A check that could not be judged fails: it never passes without having run."""
    try:
        done = subprocess.run(
            [sys.executable, "-I", "-S", "-c", _CHILD], input=json.dumps({"p": pattern, "t": text}), capture_output=True, text=True,
            encoding="utf-8", timeout=REGEX_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        return None, f"the pattern {pattern} took too long on the reply (more than {REGEX_TIMEOUT:g} seconds) and was stopped: write it more simply"
    except (OSError, ValueError) as exc:
        return None, f"the pattern {pattern} could not be run ({type(exc).__name__})"
    try:
        found = json.loads(done.stdout) if done.returncode == 0 else None
    except ValueError:
        found = None
    if not isinstance(found, bool):
        return None, f"the pattern {pattern} could not be run"
    return found, ""


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
        found, why = _search(value, text[:MAX_GRADED])
        if found is None:
            return AssertionResult(a.kind, a.value, a.why, False, why)
        passed = found
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
