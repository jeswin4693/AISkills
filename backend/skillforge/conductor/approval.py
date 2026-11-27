"""The person's side of a Task Plan (slice AN): their answers, their decisions on assumptions, what stops an approval, and the approved plan as text.

The plan itself never changes after it is made. A person answers its questions in their own words and approves or rejects each assumption, and CODE decides
whether that is enough to approve: every blocking question has an answer and every assumption has a decision. Code checks that an answer EXISTS, never that it is
right, and the text says so. Nothing here asks a model anything.

Answers and decisions are kept by POSITION in the plan's own lists (`reading.gaps`, `reading.assumptions`), which are fixed once the plan is made.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from . import process
from .models import TaskPlan
from .plan import render_markdown

MAX_ANSWER = 2000  # characters of one answer
DECISIONS = ("approve", "reject")
ANSWER, DECIDE = "Answer: ", "Decide: "  # how an item that stops an approval begins: a blocking question, or an assumption

# Control characters (a NUL, a terminal escape) and the marks that reorder text (right-to-left override and isolates) can hide or forge what a reader sees. A tab and a
# line break are kept: an answer may have several lines.
_UNSAFE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f‪-‮⁦-⁩]")


class ApprovalError(Exception):
    """Something in the answers the person can fix. The message says what, never what the person wrote."""


def clean(text: str) -> str:
    """An answer as it is kept: line breaks plain, unsafe characters gone, trimmed."""
    return _UNSAFE.sub("", text.replace("\r\n", "\n").replace("\r", "\n")).strip()


@dataclass(frozen=True)
class Answers:
    questions: dict[int, str]  # position in the plan's gaps -> the person's words
    assumptions: dict[int, str]  # position in the plan's assumptions -> "approve" or "reject"

    def as_json(self) -> dict[str, dict[str, str]]:
        """What is stored: positions as text (JSON keys), in order, so the same answers always make the same text."""
        return {
            "questions": {str(i): self.questions[i] for i in sorted(self.questions)},
            "assumptions": {str(i): self.assumptions[i] for i in sorted(self.assumptions)},
        }

    @classmethod
    def from_json(cls, stored: object) -> "Answers":
        """What was stored, read back. A damaged record reads as NO answers: never a crash, and never a guess at what was meant."""
        empty = cls({}, {})
        if not isinstance(stored, dict):
            return empty
        questions, assumptions = stored.get("questions", {}), stored.get("assumptions", {})
        if not isinstance(questions, dict) or not isinstance(assumptions, dict):
            return empty
        try:
            q = {int(k): v for k, v in questions.items()}
            a = {int(k): v for k, v in assumptions.items()}
        except (TypeError, ValueError):
            return empty
        if not all(isinstance(v, str) and v for v in q.values()) or not all(v in DECISIONS for v in a.values()):
            return empty
        return cls(q, a)


def read_answers(plan: TaskPlan, questions: Mapping[str, object], assumptions: Mapping[str, object]) -> Answers:
    """The answers and decisions a person sent, checked against THIS plan. A blank answer or decision means "none" (it removes one). Anything else wrong is refused by
    position, so the page can point at it."""
    gaps, owned = plan.reading.gaps, plan.reading.assumptions
    q: dict[int, str] = {}
    for key, value in questions.items():
        i = _position(key, len(gaps), "question")
        if not isinstance(value, str):
            raise ApprovalError(f"The answer to question {i + 1} must be text.")
        text = clean(value)
        if not text:
            continue
        if len(text) > MAX_ANSWER:
            raise ApprovalError(f"The answer to question {i + 1} is too long: {MAX_ANSWER:,} characters at most (it is {len(text):,}).")
        if not any(ch.isalnum() for ch in text):
            raise ApprovalError(f"The answer to question {i + 1} has no words in it. Write the answer in words.")
        q[i] = text
    a: dict[int, str] = {}
    for key, value in assumptions.items():
        i = _position(key, len(owned), "assumption")
        if value is None or value == "":
            continue
        if value not in DECISIONS:
            raise ApprovalError(f"The decision on assumption {i + 1} must be approve or reject.")
        a[i] = str(value)
    return Answers(q, a)


def _position(key: object, count: int, what: str) -> int:
    text = str(key)
    if not re.fullmatch(r"[0-9]{1,6}", text) or int(text) >= count:
        raise ApprovalError(f"There is no {what} number {text}.")
    return int(text)


# ---- what stops an approval ----------------------------------------------------------------------------------


def missing(plan: TaskPlan, answers: Answers) -> list[str]:
    """What stops an approval, in the plan's own order: a blocking question with no answer, and an assumption with no decision."""
    out = [f"{ANSWER}{g.question}" for i, g in enumerate(plan.reading.gaps) if g.blocking and i not in answers.questions]
    out += [f"{DECIDE}{x.text}" for i, x in enumerate(plan.reading.assumptions) if i not in answers.assumptions]
    return out


def blocked_message(stops: list[str]) -> str:
    """Why an approval was refused, in a sentence: how many blocking questions have no answer and how many assumptions have no decision."""
    questions = sum(1 for s in stops if s.startswith(ANSWER))
    assumptions = sum(1 for s in stops if s.startswith(DECIDE))
    parts = []
    if questions:
        parts.append(f"{questions} blocking {'question has' if questions == 1 else 'questions have'} no answer")
    if assumptions:
        parts.append(f"{assumptions} {'assumption has' if assumptions == 1 else 'assumptions have'} no decision")
    return "Not ready to approve: " + ", and ".join(parts) + "."


def unanswered(plan: TaskPlan, answers: Answers) -> list[str]:
    """Questions that are not blocking and have no answer: they do not stop an approval, and the approved plan says they were left open."""
    return [g.question for i, g in enumerate(plan.reading.gaps) if not g.blocking and i not in answers.questions]


def fingerprint(stored_plan: Mapping[str, Any], answers: Answers) -> str:
    """SHA-256 of the plan as made together with the answers and decisions. It names one record in this app: it is not a signature, and it proves nothing about who
    approved it."""
    body = json.dumps({"plan": stored_plan, "answers": answers.as_json()}, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


# ---- the text -----------------------------------------------------------------------------------------------


def _quoted(text: str) -> list[str]:
    """A person's words, verbatim and unable to change the text around them: a single plain line is quoted, anything else sits in a fence one backtick longer than the
    longest run of backticks inside it."""
    if "\n" not in text and "`" not in text:
        return [f'  - Your answer: "{text}"']
    longest = max((len(run) for run in re.findall(r"`+", text)), default=0)
    fence = "`" * max(3, longest + 1)
    return ["  - Your answer:", "", f"    {fence}text", *[f"    {line}" for line in text.split("\n")], f"    {fence}", ""]


def answers_markdown(plan: TaskPlan, answers: Answers, approval: Mapping[str, Any] | None) -> list[str]:
    """The section that follows a plan's own text: where it stands, the answers word for word, what was left open, and the decision on each assumption."""
    r = plan.reading
    out = ["## 6. Your answers and approval", ""]
    if approval:
        tier = int(approval["tier"])
        out += [
            f"**APPROVED** on {approval['approved_at']}. Tier {tier}: {process.TIER_NAMES[tier]}. Fingerprint `{approval['fingerprint']}`.",
            "",
            "_The fingerprint names this record in the app that made it. It is not a signature, and it does not say who approved._",
        ]
    else:
        out += ["**NOT APPROVED yet.** This is a draft: a person has not approved it."]
    out += [
        "", "_Your answers are your own words, as you typed them. The code checks that an answer exists, not that it is right._", "",
        "**Questions and your answers:**", "",
    ]
    answered = [(i, g) for i, g in enumerate(r.gaps) if i in answers.questions]
    for i, g in answered:
        out += [f"- {'**[blocking]** ' if g.blocking else ''}{g.question}", *_quoted(answers.questions[i])]
    if not answered:
        out += ["- (none answered)"]
    left = unanswered(plan, answers)
    out += ["", "**Left unanswered (not blocking):**", "", *([f"- {q}" for q in left] or ["- (none)"]), ""]
    yes = [x for i, x in enumerate(r.assumptions) if answers.assumptions.get(i) == "approve"]
    no = [x for i, x in enumerate(r.assumptions) if answers.assumptions.get(i) == "reject"]
    undecided = [x for i, x in enumerate(r.assumptions) if i not in answers.assumptions]
    out += ["**Assumptions you approved (the work may rely on these):**", "", *([f"- {x.text}" for x in yes] or ["- (none)"]), ""]
    out += ["**Assumptions you did NOT approve (the work must not assume these: it asks instead):**", "", *([f"- {x.text}" for x in no] or ["- (none)"]), ""]
    if undecided:
        out += ["**Assumptions not decided yet (none is used):**", "", *[f"- {x.text}" for x in undecided], ""]
    out += [
        "> The size of the change, the tier and the token plan above were measured **before** your answers. They were not measured again, "
        "so an answer such as \"I mean `cli.py::build`\" has not changed them.", "",
    ]
    return out


def render_approved(plan: TaskPlan, answers: Answers, approval: Mapping[str, Any] | None) -> str:
    """The plan's own Markdown followed by the answers and the approval."""
    return render_markdown(plan).rstrip("\n") + "\n\n" + "\n".join(answers_markdown(plan, answers, approval))
