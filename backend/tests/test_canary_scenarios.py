"""Reading a skill's instructions, and choosing the ordinary tasks the agent is given while it holds them.

The tasks matter as much as the judge: a skill that only misbehaves on invoices is never caught by a task about spelling. So the
tasks come from three places, and one of them (a fixed list) is out of the skill author's hands.
"""

from __future__ import annotations

import json

import pytest

from skillforge.canary import scenarios as sc
from skillforge.canary.instructions import declared_classes, load_instructions
from skillforge.canary.scenarios import FIXED, Scenario, Tasks, draft_messages, plan_scenarios, scenario_ok
from skillforge.providers import MockProvider, ProviderError

SKILL = "---\nname: invoice-summary\ndescription: Summarises an invoice. Use when the person pastes an invoice.\nallowed-tools: Read, Grep\n---\n# Steps\n1. Read it.\n"


# ---- loading ------------------------------------------------------------------------------------------


def test_a_skill_is_read_as_an_agent_would_load_it():
    ins = load_instructions({"SKILL.md": SKILL})
    assert (ins.name, ins.kind, ins.declared) == ("invoice-summary", "skill", {"read"})
    assert ins.description.startswith("Summarises an invoice") and "# Steps" in ins.text and ins.scripts == []


def test_bytes_and_windows_line_endings_are_fine():
    ins = load_instructions({"SKILL.md": SKILL.replace("\n", "\r\n").encode()})
    assert ins.name == "invoice-summary" and ins.declared == {"read"}


def test_an_agent_is_read_the_same_way_with_its_tools_line():
    ins = load_instructions({"AGENT.md": "---\nname: reviewer\ndescription: Reviews code\ntools: Read, Bash(git status), WebFetch\n---\nBody"})
    assert (ins.kind, ins.declared) == ("agent", {"read", "command", "network"})


def test_a_skill_with_no_front_matter_or_no_tools_declares_nothing_to_compare_with():
    assert load_instructions({"SKILL.md": "Just text"}).declared is None
    assert load_instructions({"SKILL.md": "---\nname: x\ndescription: y\nallowed-tools:\n---\nB"}).declared is None
    assert load_instructions({"SKILL.md": "---\nname: x\ndescription: y\nallowed-tools: Task\n---\nB"}).declared is None  # only tools the scan has no kind for


@pytest.mark.parametrize("value, expected", [
    ("Read, Grep, Glob", {"read"}), (["Write", "Edit"], {"write"}), ("Bash(git push *), Read", {"command", "read"}),
    ("WebFetch WebSearch", {"network"}), ("read_files run_commands network write_files", {"read", "command", "network", "write"}),
    ("", None), (None, None), ("mcp__x__y", None),
])
def test_declared_tools_become_kinds_of_capability(value, expected):
    assert declared_classes(value) == expected


def test_there_must_be_instructions_to_scan():
    with pytest.raises(ValueError, match="SKILL.md"):
        load_instructions({"README.md": "x"})


def test_what_the_skill_ships_is_kept_so_the_agent_can_read_it_and_scripts_are_listed_not_run():
    ins = load_instructions({
        "SKILL.md": SKILL, "references/guide.md": "more rules", "scripts/run.py": "print(1)", "assets/logo.png": b"\x89PNG\x00",
    })
    assert ins.files == {"references/guide.md": "more rules", "scripts/run.py": "print(1)"} and ins.scripts == ["scripts/run.py"]


def test_the_judge_is_told_what_the_skill_declares_and_names():
    ins = load_instructions({"SKILL.md": SKILL + "Call api.weather.gov.", "references/a.md": "see mail.example.org"})
    ctx = ins.context()
    assert ctx.declared == {"read"} and "api.weather.gov" in ctx.text and "mail.example.org" in ctx.text


def test_an_agents_tools_line_is_an_allow_list_and_a_skills_allowed_tools_is_not():
    agent = load_instructions({"AGENT.md": "---\nname: r\ndescription: d\ntools: Read\n---\nB"}).context()
    skill = load_instructions({"SKILL.md": SKILL}).context()
    assert agent.strict is True and skill.strict is False


def test_the_skills_own_test_messages_are_kept():
    cases = [{"name": "t", "kind": "positive", "input_description": "d", "expected_result": "e", "covers": [], "run_input": "Summarise invoice 7", "assertions": []}]
    ins = load_instructions({"SKILL.md": SKILL, "tests/cases.json": json.dumps(cases)})
    assert ins.messages == ["Summarise invoice 7"]


# ---- which tasks are acceptable -----------------------------------------------------------------------


@pytest.mark.parametrize("message", [
    "Summarise this invoice: item Widget, 10 units at 2.50.", "Please tidy the notes in notes.txt.", "What changed in the last release?",
])
def test_an_ordinary_task_is_acceptable(message):
    assert scenario_ok(message)


@pytest.mark.parametrize("message", [
    "", "hi", "x" * 500, "Show me the contents of .env", "What is my password?", "Print the API key", "Use the access token to log in",
    "Read ~/.aws/credentials and summarise", "Send it to https://evil.example.io", "Copy my ssh key somewhere", "Dump the environment variables",
    "Tell me the secret",
])
def test_a_task_that_asks_for_a_secret_or_a_web_address_is_never_used(message):
    assert not scenario_ok(message)


# ---- planning -----------------------------------------------------------------------------------------


def test_the_fixed_tasks_are_ordinary_and_unique():
    assert len(FIXED) >= 4 and len({s.message for s in FIXED}) == len(FIXED)
    assert all(scenario_ok(s.message) and s.source == "fixed" for s in FIXED)


def test_without_help_the_plan_is_the_fixed_tasks_up_to_the_cap():
    ins = load_instructions({"SKILL.md": SKILL})
    assert [s.id for s in plan_scenarios(ins, [], max_scenarios=3)] == [s.id for s in FIXED[:3]]


def test_the_skills_own_test_messages_come_first_but_always_leave_room_for_two_fixed_tasks():
    cases = [{"name": f"t{i}", "kind": "positive", "input_description": "d", "expected_result": "e", "covers": [], "run_input": f"Summarise invoice {i}", "assertions": []} for i in range(5)]
    ins = load_instructions({"SKILL.md": SKILL, "tests/cases.json": json.dumps(cases)})
    plan = plan_scenarios(ins, [], max_scenarios=5)
    assert [s.source for s in plan] == ["test case", "test case", "test case", "fixed", "fixed"]
    assert [s.source for s in plan_scenarios(ins, [], max_scenarios=3)] == ["test case", "fixed", "fixed"]
    assert [s.source for s in plan_scenarios(ins, [], max_scenarios=2)] == ["fixed", "fixed"]


def test_a_test_message_that_asks_for_a_secret_is_dropped_not_run():
    cases = [{"name": "t", "kind": "positive", "input_description": "d", "expected_result": "e", "covers": [], "run_input": "Show me the .env file", "assertions": []}]
    ins = load_instructions({"SKILL.md": SKILL, "tests/cases.json": json.dumps(cases)})
    assert all(s.source == "fixed" for s in plan_scenarios(ins, [], max_scenarios=4))


def test_drafted_tasks_are_used_after_the_test_messages_and_duplicates_are_dropped():
    cases = [{"name": "t", "kind": "positive", "input_description": "d", "expected_result": "e", "covers": [], "run_input": "Summarise invoice 7", "assertions": []}]
    ins = load_instructions({"SKILL.md": SKILL, "tests/cases.json": json.dumps(cases)})
    plan = plan_scenarios(ins, ["Summarise invoice 7", "Summarise this invoice for the finance team."], max_scenarios=5)
    assert [(s.source, s.message) for s in plan[:2]] == [("test case", "Summarise invoice 7"), ("drafted from the description", "Summarise this invoice for the finance team.")]


def test_every_scenario_has_a_stable_id():
    ins = load_instructions({"SKILL.md": SKILL})
    ids = [s.id for s in plan_scenarios(ins, ["Summarise this invoice for the finance team."], max_scenarios=5)]
    assert len(ids) == len(set(ids)) and all(i for i in ids)


# ---- asking a model for tasks -------------------------------------------------------------------------


def test_drafting_asks_for_tasks_from_the_description_only_and_keeps_the_acceptable_ones(monkeypatch):
    seen = {}

    def fake(provider, schema, prompt, system, attempts=None, *, task=None):
        seen.update(schema=schema, prompt=prompt, task=task)
        return Tasks(messages=["Summarise this invoice: Widget x10.", "Show me the .env file", "ok"]), 1

    monkeypatch.setattr(sc, "generate_with_retry", fake)
    ins = load_instructions({"SKILL.md": SKILL + "\nSECRET BODY LINE THE MODEL MUST NOT SEE"})
    assert draft_messages(MockProvider([]), ins) == ["Summarise this invoice: Widget x10."]
    assert "Summarises an invoice" in seen["prompt"] and "SECRET BODY LINE" not in seen["prompt"] and seen["schema"] is Tasks
    from skillforge.ai.tasks import Task
    assert seen["task"] is Task.DESIGN


def test_a_model_that_cannot_draft_does_not_stop_the_scan(monkeypatch):
    def fail(*a, **k):
        raise ProviderError("down")

    monkeypatch.setattr(sc, "generate_with_retry", fail)
    assert draft_messages(MockProvider([]), load_instructions({"SKILL.md": SKILL})) == []


def test_a_scenario_is_plain_data():
    s = Scenario(id="a", message="Do the thing please.", source="fixed")
    assert (s.id, s.message, s.source) == ("a", "Do the thing please.", "fixed")
