"""The agent builder, offline: understanding, the definition, the files, the checks and the build. A MockProvider
stands in for the model, so nothing here calls a hosted model."""

from __future__ import annotations

import json
from datetime import datetime, timezone

import yaml

from skillforge.build.agent import AgentDefinition, AgentDraft, AgentTest, assemble_agent, render_agent_files
from skillforge.build.models import SLOTS, Extraction, RequirementSpec, Slot
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


# ---- the definition, assembled by code and written as files --------------------------------------------

NOW = datetime(2026, 11, 20, 12, 0, 0, tzinfo=timezone.utc)
SPEC = RequirementSpec(
    kind="agent", goal="Review a pull request diff for security problems", inputs=["the diff as text"],
    outputs=["a list of findings"], constraints=["only read files, never edit them"],
    acceptance_criteria=["every finding names a file and a line"], failure_behavior="say that the diff is empty",
    user_words=WORDS, rounds=1,
)


def agent_test(name: str, kind: str, covers: list[str] | None = None) -> AgentTest:
    return AgentTest(name=name, kind=kind, input_description="a diff", expected_result="findings", covers=covers if covers is not None else ["AC1"])


def agent_draft(**overrides) -> AgentDraft:
    base = dict(
        name="pr-security-reviewer",
        description="Reviews a pull request diff for security problems and lists each finding.",
        triggers=["review this pull request", "check a diff for security problems", "audit changed code"],
        role="You are a security reviewer for pull request diffs.",
        process=["Read the diff you were given.", "List each change that could be a security problem.", "Report each one with its file and line."],
        output_format="A numbered list of findings. Each item names the file and the line.",
        rules=["Never guess a line number."], permissions=["read_files"], limitations=["Only reads the diff it is given."],
        tests=[agent_test("finds a flaw", "positive"), agent_test("empty diff", "negative"), agent_test("long diff", "edge")],
    )
    base.update(overrides)
    return AgentDraft(**base)


def assembled(**overrides) -> AgentDefinition:
    return assemble_agent(agent_draft(**overrides), SPEC, MockProvider([]), NOW)


def front_matter(text: str) -> dict:
    return yaml.safe_load(text.split("---\n")[1])


def test_tools_come_from_the_permissions_and_never_fall_below_read():
    read = ["Read", "Grep", "Glob"]
    assert assembled(permissions=[]).tools == read  # an empty or missing tools line would give the agent every tool
    assert assembled(permissions=["read_files"]).tools == read
    assert assembled(permissions=["run_commands", "read_files"]).tools == [*read, "Bash"]
    assert assembled(permissions=["network", "write_files"]).tools == [*read, "Edit", "Write", "WebFetch", "WebSearch"]
    assert assembled(permissions=[]).permissions == ["read_files"]


def test_the_agent_file_has_exactly_a_name_a_description_and_tools_in_its_front_matter():
    text = render_agent_files(assembled(permissions=["run_commands"]), SPEC)["AGENT.md"]
    meta = front_matter(text)
    assert list(meta) == ["name", "description", "tools"]  # never permissionMode, model, hooks or mcpServers
    assert meta["name"] == "pr-security-reviewer" and meta["tools"] == "Read, Grep, Glob, Bash"
    assert meta["description"].endswith('Use when the request involves "review this pull request", "check a diff for security problems", or "audit changed code".')


def test_the_name_is_made_safe_and_the_change_is_recorded():
    defn = assembled(name="PR Security Reviewer!")
    assert defn.name == "pr-security-reviewer" and defn.provenance.name_adjusted
    assert assembled(name=" ").name == "review-a-pull-request-diff-for-security-problems"[:40].strip("-")


def test_model_text_is_data_never_a_template_or_front_matter():
    nasty = 'Finds it: "quoted" ---\nname: evil\n{{ 7*7 }} {% evil %}'
    files = render_agent_files(assembled(description=nasty, role="{{ 7*7 }} You review.", process=["{{ 7*7 }}", "b", "c"], rules=["---"]), SPEC)
    text = files["AGENT.md"]
    meta = front_matter(text)
    assert list(meta) == ["name", "description", "tools"] and meta["name"] == "pr-security-reviewer"
    assert "49" not in text and "{{ 7*7 }}" in text and "49" not in files["README.md"]


def test_the_persons_own_lines_are_carried_word_for_word():
    text = render_agent_files(assembled(), SPEC)["AGENT.md"]
    for line in ("only read files, never edit them", "every finding names a file and a line", "say that the diff is empty"):
        assert line in text
    assert text.index("## Rules") < text.index("only read files, never edit them") < text.index("Never guess a line number.")
    assert "## Done when" in text and "## If something goes wrong" in text and "1. Read the diff you were given." in text


def test_a_rule_the_person_said_does_not_exist_is_not_written_down():
    spec = SPEC.model_copy(update=dict(constraints=["none"], failure_behavior="none"))
    text = render_agent_files(assemble_agent(agent_draft(rules=[]), spec, MockProvider([]), NOW), spec)["AGENT.md"]
    assert "## Rules" not in text and "## If something goes wrong" not in text


def test_the_build_writes_these_files_and_the_same_definition_gives_the_same_bytes():
    defn = assembled()
    files = render_agent_files(defn, SPEC)
    assert sorted(files) == ["AGENT.md", "README.md", "agent.sdm.json", "spec.json", "tests/cases.json"]
    assert render_agent_files(defn, SPEC) == files
    cases = json.loads(files["tests/cases.json"])
    assert [c["kind"] for c in cases] == ["positive", "negative", "edge"] and set(cases[0]) == {"name", "kind", "input_description", "expected_result", "covers"}
    assert AgentDefinition.model_validate_json(files["agent.sdm.json"]) == defn
    assert "Read, Grep, Glob" in files["README.md"] and "read files" in files["README.md"]  # what it can do, said by code
