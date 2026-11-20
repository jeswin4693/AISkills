"""The agent builder, offline: understanding, the definition, the files, the checks and the build. A MockProvider
stands in for the model, so nothing here calls a hosted model."""

from __future__ import annotations

from skillforge.build.models import SLOTS, Extraction, Slot
from skillforge.build.pipeline import understand_round
from skillforge.providers import MockProvider

WORDS = (
    "An agent that reviews a pull request diff for security problems. It receives the diff as text. "
    "It returns a list of findings. It may only read files and must never edit them. "
    "It works when every finding names a file and a line. If the diff is empty it says so."
)


def slot(values: list[str] | None = None, quote: str = "") -> Slot:
    return Slot(values=values or [], quote=quote)


def agent_extraction(**changes: Slot) -> Extraction:
    """Everything in WORDS, each item with a quote that really is in WORDS. `changes` swaps an item (an empty slot() drops it)."""
    base = dict(
        kind="agent",
        goal=slot(["Review a pull request diff for security problems"], "reviews a pull request diff for security problems"),
        inputs=slot(["the diff as text"], "receives the diff as text"),
        outputs=slot(["a list of findings"], "returns a list of findings"),
        constraints=slot(["only read files, never edit them"], "may only read files and must never edit them"),
        acceptance_criteria=slot(["every finding names a file and a line"], "every finding names a file and a line"),
        failure_behavior=slot(["say that the diff is empty"], "If the diff is empty it says so"),
    )
    base.update(changes)
    return Extraction(**base)


# ---- understanding, for any kind ---------------------------------------------------------------------


def test_an_agent_request_is_complete_when_the_builder_is_not_skill_only():
    r = understand_round(MockProvider([agent_extraction()]), WORDS, 1, 3, skill_only=False)
    assert r.state == "complete" and r.spec.kind == "agent" and r.spec.goal.startswith("Review a pull request")


def test_the_skill_builder_still_refuses_an_agent_request():
    r = understand_round(MockProvider([agent_extraction()]), WORDS, 1, 3)
    assert r.state == "blocked" and "not a skill" in r.message


def test_the_questions_and_the_extraction_prompt_use_the_wording_that_is_passed_in():
    wording = {slot_name: f"AGENT WORDING for {slot_name}?" for slot_name in SLOTS}
    mock = MockProvider([agent_extraction(constraints=slot(), failure_behavior=slot())])
    r = understand_round(mock, WORDS, 1, 3, questions=wording, extract_system="AGENT EXTRACT SYSTEM", skill_only=False)
    assert r.state == "questions"
    assert [(q.slot, q.text) for q in r.questions] == [(s, wording[s]) for s in ("constraints", "failure_behavior")]
    assert mock.calls[0]["system"] == "AGENT EXTRACT SYSTEM"
