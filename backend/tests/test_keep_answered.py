"""An answered checklist item is kept between rounds (slice AK, task 3).

Each round the model reads ALL of the person's words again and fills in the checklist. A model that answers a little differently the second time can
leave out an item it backed in the first round (a real build lost "constraints" this way and asked for it again). Code keeps such an item, but only
when its quote is STILL in the person's own words, checked again against the current words: nothing is kept on the model's say-so.
"""

from __future__ import annotations

from test_skill_build import ANSWERS, FIRST, round_one, round_two, slot

from skillforge.build.models import RequirementSpec
from skillforge.build.pipeline import gather_spec, understand_round
from skillforge.build.requirements import keep_verified
from skillforge.providers import MockProvider

RULE = "It must never edit files."
WORDS = f"{FIRST} {RULE} {ANSWERS['acceptance_criteria']} {ANSWERS['failure_behavior']}"  # everything the person has said by round 2


def previous_with_constraints() -> RequirementSpec:
    return RequirementSpec(constraints=["never edit files"], quotes={"constraints": "It must never edit files"})


def round_two_without_constraints():
    """A round-two reading in which the model backs everything but the item it backed in round one."""
    return round_two().model_copy(update=dict(constraints=slot()))


def test_an_item_the_new_reading_dropped_is_kept_when_its_quote_is_still_in_the_words():
    new, notes = keep_verified(RequirementSpec(goal="g" * 12), previous_with_constraints(), WORDS)
    assert new.constraints == ["never edit files"] and new.quotes["constraints"] == "It must never edit files"
    assert len(notes) == 1 and notes[0].startswith("constraints: kept from the previous round")


def test_an_item_whose_quote_is_not_in_the_words_is_never_kept():
    previous = RequirementSpec(constraints=["x"], quotes={"constraints": "a rule nobody wrote"})
    new, notes = keep_verified(RequirementSpec(), previous, WORDS)
    assert new.constraints == [] and "constraints" not in new.quotes and notes == []


def test_an_item_the_new_reading_backed_is_not_replaced():
    new = RequirementSpec(constraints=["never run commands"], quotes={"constraints": "It must never edit files"})
    kept, notes = keep_verified(new, previous_with_constraints(), WORDS)
    assert kept.constraints == ["never run commands"] and notes == []


def test_with_nothing_before_nothing_changes():
    new = RequirementSpec(goal="g" * 12)
    kept, notes = keep_verified(new, None, WORDS)
    assert kept is new and kept.constraints == [] and kept.quotes == {} and notes == []


def test_an_old_slot_with_no_value_or_no_quote_is_not_kept():
    no_value = RequirementSpec(quotes={"constraints": "It must never edit files"})
    no_quote = RequirementSpec(constraints=["never edit files"])
    for previous in (no_value, no_quote):
        new, notes = keep_verified(RequirementSpec(), previous, WORDS)
        assert new.constraints == [] and "constraints" not in new.quotes and notes == []


def test_a_quote_made_of_whole_sentences_of_theirs_is_kept():
    quote = f"{RULE} {ANSWERS['failure_behavior']}"  # two of their sentences with another one between them in their words
    previous = RequirementSpec(constraints=["never edit files"], quotes={"constraints": quote})
    new, notes = keep_verified(RequirementSpec(), previous, WORDS)
    assert new.quotes["constraints"] == quote and len(notes) == 1


def test_goal_and_failure_behavior_are_kept_as_text_not_lists():
    previous = RequirementSpec(
        goal="Find duplicate functions", failure_behavior="stop and say so",
        quotes={"goal": "finds duplicate functions in a TypeScript repository", "failure_behavior": "it stops and says so"},
    )
    new, notes = keep_verified(RequirementSpec(), previous, WORDS)
    assert new.goal == "Find duplicate functions" and new.failure_behavior == "stop and say so" and len(notes) == 2


def test_the_new_readings_kind_rounds_and_words_stay():
    new = RequirementSpec(kind="agent", rounds=2, user_words=WORDS)
    kept, _ = keep_verified(new, previous_with_constraints(), WORDS)
    assert kept.kind == "agent" and kept.rounds == 2 and kept.user_words == WORDS


def test_understand_round_completes_with_a_kept_item_and_asks_for_it_without():
    r = understand_round(MockProvider([round_two_without_constraints()]), WORDS, 2, 3, previous=previous_with_constraints())
    assert r.state == "complete" and r.spec.constraints == ["never edit files"]
    assert any(n.startswith("round 2: constraints: kept from the previous round") for n in r.notes)
    r = understand_round(MockProvider([round_two_without_constraints()]), WORDS, 2, 3)
    assert r.state == "questions" and [q.slot for q in r.questions] == ["constraints"]


def test_the_command_line_conversation_keeps_an_item_across_rounds():
    round_one_with_rule = round_one().model_copy(update=dict(constraints=slot(["never edit files"], "It must never edit files")))
    asked: list[list[str]] = []

    def ask(questions):
        asked.append([q.slot for q in questions])
        return {q.slot: ANSWERS[q.slot] for q in questions}

    spec, _, notes = gather_spec(f"{FIRST} {RULE}", MockProvider([round_one_with_rule, round_two_without_constraints()]), ask, 3)
    assert asked == [["acceptance_criteria", "failure_behavior"]]  # constraints was never asked for again
    assert spec.constraints == ["never edit files"] and any("constraints: kept from the previous round" in n for n in notes)
