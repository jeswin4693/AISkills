"""The agent builder, offline: understanding, the definition, the files, the checks and the build. A MockProvider
stands in for the model, so nothing here calls a hosted model."""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest
import yaml

from skillforge.build.agent import (
    AGENT_DESIGN_SYSTEM, AgentDefinition, AgentDraft, AgentTest, assemble_agent, render_agent_files,
)
from skillforge.build.agent_pipeline import build_agent_from_spec, check_agent
from skillforge.build.models import SLOTS, Extraction, RequirementSpec, Slot
from skillforge.build.pipeline import BuildError, understand_round
from skillforge.providers import MockProvider
from skillforge.results import FAILED, NOT_RUN, PASSED, WARNING

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


# ---- the checks and the whole build ------------------------------------------------------------------


def build(tmp_path, responses, **kw):
    mock = MockProvider(responses)
    return build_agent_from_spec(SPEC, mock, out_root=tmp_path / "out", now=NOW, **kw), mock


def one(checks, fragment: str):
    found = [c for c in checks if fragment in c.name]
    assert len(found) == 1, f"expected one check containing '{fragment}', got {[c.name for c in checks]}"
    return found[0]


def uncovered_tests() -> list[AgentTest]:
    return [agent_test("finds a flaw", "positive", []), agent_test("empty diff", "negative", []), agent_test("long diff", "edge", [])]


def test_a_clean_design_builds_every_file_and_is_ok(tmp_path):
    result, mock = build(tmp_path, [agent_draft()])
    assert result.status == "ok" and result.model_calls == 1 and result.draft_reason == ""
    assert result.files == ["AGENT.md", "README.md", "agent.sdm.json", "report.md", "spec.json", "tests/cases.json"]
    assert (tmp_path / "out" / "pr-security-reviewer" / "AGENT.md").read_text(encoding="utf-8").startswith("---\nname: pr-security-reviewer\n")
    assert not [c for c in result.checks if c.status == FAILED]
    assert one(result.checks, "AGENT.md exists and its front matter is valid").status == PASSED  # the shared static checks ran
    assert one(result.checks, "test cases were run").status == NOT_RUN  # what did not run is said, never counted as passed
    prompt = mock.calls[0]["prompt"]
    assert "<requirement>" in prompt and "Review a pull request diff" in prompt and mock.calls[0]["system"] == AGENT_DESIGN_SYSTEM
    report = (tmp_path / "out" / "pr-security-reviewer" / "report.md").read_text(encoding="utf-8")
    assert report.startswith("# Build report: Pr Security Reviewer") and "not run" in report.lower()


def test_an_uncovered_acceptance_criterion_is_a_failed_check_and_gets_one_repair(tmp_path):
    result, mock = build(tmp_path, [agent_draft(tests=uncovered_tests()), agent_draft()])
    assert result.status == "ok" and result.model_calls == 2
    assert "did not pass these automatic checks" in mock.calls[1]["prompt"] and "AC1" in mock.calls[1]["prompt"]
    assert any("fix them once" in n for n in result.notes)


def test_a_repair_that_is_worse_is_discarded(tmp_path):
    result, _ = build(tmp_path, [agent_draft(tests=uncovered_tests()), agent_draft(tests=[])])
    assert result.status == "draft" and result.model_calls == 2
    assert one(result.checks, "acceptance criterion is covered").status == FAILED
    assert any("worse" in n and "first was kept" in n for n in result.notes)
    assert len(result.definition.tests) == 3  # the first design, not the empty one


def test_a_check_fails_when_the_persons_own_lines_are_not_in_the_file():
    defn = assembled()
    files = render_agent_files(defn, SPEC)
    files["AGENT.md"] = files["AGENT.md"].replace("every finding names a file and a line", "something else")
    found = one(check_agent(defn, SPEC, files), "word for word")
    assert found.status == FAILED and "every finding names a file and a line" in found.detail
    assert one(check_agent(defn, SPEC, render_agent_files(defn, SPEC)), "word for word").status == PASSED


def test_what_an_agent_can_do_beyond_reading_is_flagged_for_a_person_to_read():
    checks = check_agent(assembled(permissions=["run_commands", "network"]), SPEC, render_agent_files(assembled(permissions=["run_commands", "network"]), SPEC))
    found = one(checks, "what the agent can do beyond reading files")
    assert found.status == WARNING and "Bash" in found.detail and "WebFetch" in found.detail
    assert one(check_agent(assembled(), SPEC, render_agent_files(assembled(), SPEC)), "what the agent can do beyond reading files").status == PASSED


def test_vague_wording_and_too_many_or_too_long_steps_only_warn():
    vague = assembled(process=["Read the diff as needed.", "b", "c"])
    assert one(check_agent(vague, SPEC, render_agent_files(vague, SPEC)), "vague wording").status == WARNING
    many = assembled(process=[f"Step {i}." for i in range(8)])
    assert one(check_agent(many, SPEC, render_agent_files(many, SPEC)), "steps are few and short").status == WARNING
    long = assembled(process=["word " * 61, "b", "c"])
    assert one(check_agent(long, SPEC, render_agent_files(long, SPEC)), "steps are few and short").status == WARNING
    fine = assembled()
    assert one(check_agent(fine, SPEC, render_agent_files(fine, SPEC)), "vague wording").status == PASSED


def test_a_design_without_a_positive_or_a_negative_test_fails():
    defn = assembled(tests=[agent_test("only edge", "edge")])
    found = one(check_agent(defn, SPEC, render_agent_files(defn, SPEC)), "positive and a negative test")
    assert found.status == FAILED


def test_an_existing_folder_is_never_overwritten_without_force(tmp_path):
    build(tmp_path, [agent_draft()])
    with pytest.raises(BuildError, match="already exists"):
        build(tmp_path, [agent_draft()])
    assert build(tmp_path, [agent_draft()], force=True)[0].status == "ok"


def test_progress_is_reported_in_plain_words(tmp_path):
    said: list[str] = []
    build(tmp_path, [agent_draft()], progress=said.append)
    assert said[0].startswith("Designing the agent") and said[-1] == "Writing the files and running every check"
