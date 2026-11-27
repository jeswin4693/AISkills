"""Slice AN: the person's side of a Task Plan, as pure logic (`conductor/approval.py`): what counts as an answer, what stops an approval, the fingerprint, and the
Markdown of the approved plan. Offline: a plan made with a mock model and no repository."""

from __future__ import annotations

import re

import pytest
from test_conductor import reading

from skillforge.conductor import make_plan, render_markdown
from skillforge.conductor.approval import (
    MAX_ANSWER, Answers, ApprovalError, answers_markdown, blocked_message, clean, fingerprint, missing, read_answers, render_approved, unanswered,
)
from skillforge.conductor.models import AssumptionMade, GapAsked
from skillforge.providers import MockProvider

TASK = "Add a --json option to the library list command. Do not change any other command."

GAPS = [
    GapAsked(question="What should the JSON look like?", why="It cannot be tested without it.", blocking=True),
    GapAsked(question="Which file holds the command?", why="The size cannot be measured.", blocking=True),
    GapAsked(question="Should the old output stay the default?", why="Scripts may read it.", blocking=False),
]
ASSUMPTIONS = [
    AssumptionMade(text="The option is off by default.", why="Nothing said otherwise."),
    AssumptionMade(text="The output goes to the terminal.", why="No file was named."),
]


@pytest.fixture
def plan():
    return make_plan(TASK, provider=MockProvider([reading(gaps=GAPS, assumptions=ASSUMPTIONS)]))


def test_the_fixture_plan_has_three_questions_blocking_first_and_two_assumptions(plan):
    assert [g.blocking for g in plan.reading.gaps] == [True, True, False]
    assert len(plan.reading.assumptions) == 2


# ---- what counts as an answer ---------------------------------------------------------------------------------


def test_an_answer_is_kept_by_the_position_of_its_question_trimmed_and_a_blank_one_is_dropped(plan):
    a = read_answers(plan, {"0": "  A list of names.  ", "1": "   ", "2": "Yes, keep it."}, {})
    assert a.questions == {0: "A list of names.", 2: "Yes, keep it."}


def test_a_line_break_inside_an_answer_is_kept_and_a_windows_one_becomes_a_plain_one(plan):
    a = read_answers(plan, {"0": "line one\r\nline two\n\nline four"}, {})
    assert a.questions[0] == "line one\nline two\n\nline four"


def test_a_position_that_is_not_a_question_of_this_plan_is_refused_by_name(plan):
    with pytest.raises(ApprovalError, match="no question number 3"):
        read_answers(plan, {"3": "anything"}, {})
    with pytest.raises(ApprovalError, match="no question number -1"):
        read_answers(plan, {"-1": "anything"}, {})
    with pytest.raises(ApprovalError, match="no question number first"):
        read_answers(plan, {"first": "anything"}, {})


def test_an_assumption_position_outside_the_plan_is_refused(plan):
    with pytest.raises(ApprovalError, match="no assumption number 2"):
        read_answers(plan, {}, {"2": "approve"})


def test_an_answer_may_be_exactly_the_longest_allowed_and_one_more_is_refused_with_the_number(plan):
    assert len(read_answers(plan, {"0": "a" * MAX_ANSWER}, {}).questions[0]) == MAX_ANSWER
    with pytest.raises(ApprovalError, match=r"2,000") as e:
        read_answers(plan, {"0": "a" * (MAX_ANSWER + 1)}, {})
    assert "question 1" in str(e.value)


def test_the_length_is_counted_after_trimming_not_before(plan):
    assert read_answers(plan, {"0": "  " + "a" * MAX_ANSWER + "  "}, {}).questions[0] == "a" * MAX_ANSWER


def test_an_answer_with_no_letter_or_digit_in_it_is_not_an_answer(plan):
    for text in ("???", "...", "-", "   ?  ", "!!! ... ???"):
        with pytest.raises(ApprovalError, match="words"):
            read_answers(plan, {"0": text}, {})
    assert read_answers(plan, {"0": "42"}, {}).questions[0] == "42"
    assert read_answers(plan, {"0": "é"}, {}).questions[0] == "é"  # a letter of any alphabet


def test_an_answer_that_is_not_text_is_refused(plan):
    with pytest.raises(ApprovalError, match="text"):
        read_answers(plan, {"0": 5}, {})  # type: ignore[dict-item]


def test_control_characters_and_text_direction_tricks_are_removed_from_an_answer(plan):
    dirty = "ok\x00 fine\x1b[31m‮ reversed⁦ done\x7f"
    cleaned = read_answers(plan, {"0": dirty}, {}).questions[0]
    assert cleaned == "ok fine[31m reversed done"
    assert clean("tab\tstays") == "tab\tstays"


# ---- decisions on assumptions ---------------------------------------------------------------------------------


def test_an_assumption_is_approved_or_not_approved_and_a_blank_decision_leaves_it_undecided(plan):
    a = read_answers(plan, {}, {"0": "approve", "1": "reject"})
    assert a.assumptions == {0: "approve", 1: "reject"}
    b = read_answers(plan, {}, {"0": None, "1": ""})  # type: ignore[dict-item]
    assert b.assumptions == {}


def test_any_other_decision_is_refused_and_named(plan):
    for bad in ("yes", "APPROVE", "approved", "maybe"):
        with pytest.raises(ApprovalError, match="approve or reject"):
            read_answers(plan, {}, {"0": bad})


# ---- what stops an approval -----------------------------------------------------------------------------------


def test_with_nothing_answered_every_blocking_question_and_every_assumption_stops_the_approval_in_the_plans_order(plan):
    stops = missing(plan, Answers({}, {}))
    assert stops == [
        "Answer: What should the JSON look like?", "Answer: Which file holds the command?",
        "Decide: The option is off by default.", "Decide: The output goes to the terminal.",
    ]


def test_an_answered_blocking_question_and_a_decided_assumption_stop_being_listed(plan):
    stops = missing(plan, Answers({0: "names"}, {1: "reject"}))
    assert stops == ["Answer: Which file holds the command?", "Decide: The option is off by default."]


def test_a_question_that_is_not_blocking_never_stops_an_approval_but_is_listed_as_unanswered(plan):
    a = Answers({0: "x1", 1: "x2"}, {0: "approve", 1: "approve"})
    assert missing(plan, a) == []
    assert unanswered(plan, a) == ["Should the old output stay the default?"]
    assert unanswered(plan, Answers({0: "x1", 1: "x2", 2: "x3"}, {})) == []


def test_a_plan_with_no_questions_and_no_assumptions_has_nothing_that_stops_it():
    bare = make_plan(TASK, provider=MockProvider([reading()]))
    assert missing(bare, Answers({}, {})) == [] and unanswered(bare, Answers({}, {})) == []


def test_a_plan_made_with_no_model_has_no_assumptions_to_decide_and_only_the_graphs_questions():
    facts = make_plan(TASK, task_type="feature")
    assert facts.mode == "facts only" and missing(facts, Answers({}, {})) == []


def test_the_refusal_says_how_many_blocking_questions_and_assumptions_are_missing_in_the_singular_and_the_plural(plan):
    assert blocked_message(missing(plan, Answers({}, {}))) == "Not ready to approve: 2 blocking questions have no answer, and 2 assumptions have no decision."
    assert blocked_message(missing(plan, Answers({0: "n1"}, {}))) == "Not ready to approve: 1 blocking question has no answer, and 2 assumptions have no decision."
    assert blocked_message(missing(plan, Answers({0: "n1", 1: "n2"}, {0: "approve"}))) == "Not ready to approve: 1 assumption has no decision."
    assert blocked_message(missing(plan, Answers({0: "n1"}, {0: "approve", 1: "reject"}))) == "Not ready to approve: 1 blocking question has no answer."


# ---- the fingerprint ------------------------------------------------------------------------------------------


def test_the_fingerprint_is_64_hex_characters_and_the_same_for_the_same_record(plan):
    stored = plan.model_dump()
    a = Answers({0: "names"}, {0: "approve"})
    f = fingerprint(stored, a)
    assert re.fullmatch(r"[0-9a-f]{64}", f) and f == fingerprint(stored, Answers({0: "names"}, {0: "approve"}))


def test_the_fingerprint_changes_with_an_answer_a_decision_or_the_plan(plan):
    stored = plan.model_dump()
    base = fingerprint(stored, Answers({0: "names"}, {0: "approve"}))
    assert fingerprint(stored, Answers({0: "Names"}, {0: "approve"})) != base
    assert fingerprint(stored, Answers({0: "names"}, {0: "reject"})) != base
    assert fingerprint(stored, Answers({0: "names", 1: "x"}, {0: "approve"})) != base
    assert fingerprint({**stored, "prompt": stored["prompt"] + " Also this."}, Answers({0: "names"}, {0: "approve"})) != base


def test_the_order_the_answers_were_written_in_does_not_change_the_fingerprint(plan):
    stored = plan.model_dump()
    assert fingerprint(stored, Answers({0: "a1", 1: "b1"}, {0: "approve", 1: "reject"})) == fingerprint(stored, Answers({1: "b1", 0: "a1"}, {1: "reject", 0: "approve"}))


def test_an_answer_cannot_be_moved_to_another_question_without_changing_the_fingerprint(plan):
    stored = plan.model_dump()
    assert fingerprint(stored, Answers({0: "same"}, {})) != fingerprint(stored, Answers({1: "same"}, {}))
    assert fingerprint(stored, Answers({0: "same"}, {})) != fingerprint(stored, Answers({}, {0: "approve"}))


# ---- stored answers read back ---------------------------------------------------------------------------------


def test_answers_survive_being_stored_and_read_back():
    a = Answers({2: "later", 0: "first"}, {1: "reject"})
    assert a.as_json() == {"questions": {"0": "first", "2": "later"}, "assumptions": {"1": "reject"}}
    assert Answers.from_json(a.as_json()) == a


@pytest.mark.parametrize("stored", [None, "text", [], {}, {"questions": "x"}, {"questions": {"a": "b"}}, {"questions": {"0": 5}}, {"assumptions": {"0": "maybe"}}])
def test_a_damaged_record_reads_back_as_no_answers_never_as_a_crash_or_a_guess(stored):
    assert Answers.from_json(stored) == Answers({}, {})


# ---- the Markdown ---------------------------------------------------------------------------------------------


def test_the_section_holds_the_answers_word_for_word_and_says_they_are_not_checked_for_being_right(plan):
    text = "\n".join(answers_markdown(plan, Answers({0: "A list of names, one per line"}, {0: "approve", 1: "reject"}), None))
    assert "## 6. Your answers and approval" in text
    assert "A list of names, one per line" in text and "What should the JSON look like?" in text
    assert "not that it is right" in text
    assert "NOT APPROVED" in text and "fingerprint" not in text.lower()


def test_unanswered_questions_and_the_two_kinds_of_assumption_are_listed_apart(plan):
    text = "\n".join(answers_markdown(plan, Answers({0: "names"}, {0: "approve", 1: "reject"}), None))
    assert text.index("Left unanswered") < text.index("Should the old output stay the default?")
    before, after = text.split("**Assumptions you approved")[1].split("**Assumptions you did NOT approve")
    assert "The option is off by default." in before and "The output goes to the terminal." not in before
    assert "The output goes to the terminal." in after and "The option is off by default." not in after
    assert "not decided yet" not in text  # both were decided, so that heading is not shown


def test_the_blocking_marker_is_shown_on_a_blocking_question_and_not_on_the_other(plan):
    text = "\n".join(answers_markdown(plan, Answers({0: "x1", 2: "x3"}, {}), None))
    first = next(line for line in text.splitlines() if "What should the JSON look like?" in line)
    third = next(line for line in text.splitlines() if "Should the old output stay the default?" in line)
    assert "blocking" in first.lower() and "blocking" not in third.lower()


def test_an_approved_plan_says_when_what_tier_and_its_fingerprint_and_that_size_was_not_measured_again(plan):
    approval = {"approved_at": "2026-11-27T10:00:00+00:00", "fingerprint": "ab" * 32, "tier": 2}
    text = "\n".join(answers_markdown(plan, Answers({0: "a1", 1: "a2"}, {0: "approve", 1: "approve"}), approval))
    assert "APPROVED" in text and "NOT APPROVED" not in text and "2026-11-27T10:00:00+00:00" in text and "ab" * 32 in text
    assert "Tier 2" in text and "not measured again" in text.lower()
    assert "not a signature" in text.lower()


def test_a_single_line_answer_is_quoted_and_a_multi_line_one_sits_in_a_fence_longer_than_any_run_of_backticks_in_it(plan):
    text = "\n".join(answers_markdown(plan, Answers({0: "one line", 1: "first\n```\n# not a heading\n````\nlast"}, {}), None))
    assert '"one line"' in text
    lines = text.splitlines()
    opening = next(i for i, line in enumerate(lines) if line.strip().startswith("`````"))  # one more than the longest run (4)
    fence = re.match(r"`+", lines[opening].strip()).group(0)  # the opening line is the fence and the label "text"
    assert fence == "`" * 5
    closing = next(i for i in range(opening + 1, len(lines)) if lines[i].strip() == fence)
    inside = [line.strip() for line in lines[opening + 1:closing]]
    assert inside == ["first", "```", "# not a heading", "````", "last"]  # every line of the answer, untouched, and nothing of the answer outside the fence
    assert all(line.strip() != fence for line in lines[closing + 1:])


def test_an_answer_with_a_backtick_in_one_line_is_fenced_too_so_it_cannot_break_out(plan):
    text = "\n".join(answers_markdown(plan, Answers({0: "use `build` here"}, {}), None))
    assert "use `build` here" in text and "```" in text


def test_the_approved_plan_is_the_plans_own_text_followed_by_the_section(plan):
    a = Answers({0: "a1", 1: "a2"}, {0: "approve", 1: "reject"})
    whole = render_approved(plan, a, None)
    assert whole.startswith(render_markdown(plan))
    assert whole.rstrip().endswith("\n".join(answers_markdown(plan, a, None)).rstrip()[-40:])
    assert whole.index("## What was NOT checked") < whole.index("## 6. Your answers and approval")
