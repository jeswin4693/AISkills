from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest
import yaml

from skillforge import cli
from skillforge.build.models import Extraction, IOField, SkillDraft, Slot, Step, SkillTest
from skillforge.build.pipeline import BuildError, NeedAnswers, build_skill, rebuild
from skillforge.build.render import schema_for
from skillforge.providers import MockProvider

NOW = datetime(2026, 11, 17, 12, 0, 0, tzinfo=timezone.utc)
FIRST = "A skill that finds duplicate functions in a TypeScript repository and suggests safe refactors."
ANSWERS = {
    "constraints": "It must never edit files.",
    "acceptance_criteria": "It works when every duplicate pair is listed with its file and line.",
    "failure_behavior": "If the path is not readable it stops and says so.",
}


def slot(values=None, quote=""):
    return Slot(values=values or [], quote=quote)


def round_one() -> Extraction:  # only what the first sentence says
    return Extraction(
        kind="skill",
        goal=slot(["Find duplicate functions and suggest safe refactors"], "finds duplicate functions in a TypeScript repository"),
        inputs=slot(["a TypeScript repository"], "in a TypeScript repository"),
        outputs=slot(["safe refactor suggestions"], "suggests safe refactors"),
        constraints=slot(), acceptance_criteria=slot(), failure_behavior=slot(),
    )


def round_two() -> Extraction:  # now the answers are part of the person's words
    return round_one().model_copy(update=dict(
        constraints=slot(["never edit files"], "It must never edit files"),
        acceptance_criteria=slot(["every duplicate pair is listed with its file and line"], "every duplicate pair is listed with its file and line"),
        failure_behavior=slot(["stop and say so"], "it stops and says so"),
    ))


def draft(**overrides) -> SkillDraft:
    base = dict(
        name="duplicate-function-finder",
        description="Finds duplicate functions in a TypeScript repository and proposes safe refactors. Use it when cleaning up copy-pasted code.",
        does=["Find functions with the same structure", "Propose one shared version"],
        does_not=["Edit any file"],
        inputs=[IOField(name="repository_path", type="string", description="Path of the repository", required=True)],
        outputs=[IOField(name="duplicate_groups", type="list", description="Each group of duplicates with file and line", required=True)],
        workflow=[
            Step(title="Read the repository", instruction="List the TypeScript files and read them.", on_failure="Stop and say the path cannot be read."),
            Step(title="Compare functions", instruction="Group functions that have the same structure.", on_failure="Report that nothing could be compared."),
            Step(title="Report", instruction="List every group with file and line.", on_failure="Say what is missing."),
        ],
        permissions=["read_files"],
        error_handling=["If the path is unreadable, stop and say so."],
        limitations=["Only exact structural copies are found."],
        tests=[
            SkillTest(name="finds a pair", kind="positive", input_description="A repo with two identical functions", expected_result="Both listed with file and line", covers=["AC1"]),
            SkillTest(name="unreadable path", kind="negative", input_description="A path that does not exist", expected_result="It stops and says so", covers=["AC1"]),
            SkillTest(name="empty repo", kind="edge", input_description="A repo with no functions", expected_result="An empty list", covers=["AC1"]),
        ],
    )
    base.update(overrides)
    return SkillDraft(**base)


def ask_answers(questions):
    return {q.slot: ANSWERS[q.slot] for q in questions}


def run(tmp_path, responses, *, ask=ask_answers, approve=lambda spec: True, description=FIRST, **kw):
    mock = MockProvider(responses)
    result = build_skill(description, mock, ask=ask, approve=approve, out_root=tmp_path / "out", now=NOW, **kw)
    return result, mock


# ---- the whole path ----------------------------------------------------------------------------------------


def test_full_build_asks_only_what_is_missing_then_writes_every_file(tmp_path):
    result, mock = run(tmp_path, [round_one(), round_two(), draft()])
    assert result.status == "ok" and result.model_calls == 3
    assert result.spec.rounds == 2 and result.spec.constraints == ["never edit files"]
    out = result.out_dir
    assert out == tmp_path / "out" / "duplicate-function-finder"
    assert {p.relative_to(out).as_posix() for p in out.rglob("*") if p.is_file()} == {
        "SKILL.md", "README.md", "report.md", "skill.sdm.json", "spec.json",
        "schemas/input.schema.json", "schemas/output.schema.json", "tests/cases.json",
    }
    # round 2 saw the person's answers as part of their words
    assert "must never edit files" in mock.calls[1]["prompt"]
    # spec.json keeps the person's own words as evidence
    spec = json.loads((out / "spec.json").read_text(encoding="utf-8"))
    assert spec["quotes"]["constraints"] == "It must never edit files"


def test_generated_skill_md_is_well_formed(tmp_path):
    out = run(tmp_path, [round_one(), round_two(), draft()])[0].out_dir
    text = (out / "SKILL.md").read_text(encoding="utf-8")
    assert text.startswith("---\nname: duplicate-function-finder\ndescription: ")
    for heading in ("## Responsibilities", "## Inputs", "## Workflow", "## Outputs", "## Error handling", "## Limitations", "## Permissions"):
        assert heading in text
    assert "1. **Read the repository**:" in text and "`repository_path` (string, required)" in text
    assert "read_files" in text


def test_schemas_are_valid_and_built_from_the_field_lists(tmp_path):
    out = run(tmp_path, [round_one(), round_two(), draft()])[0].out_dir
    schema = json.loads((out / "schemas" / "input.schema.json").read_text(encoding="utf-8"))
    assert schema["required"] == ["repository_path"] and schema["additionalProperties"] is False
    assert schema["properties"]["repository_path"]["type"] == "string"
    out_schema = json.loads((out / "schemas" / "output.schema.json").read_text(encoding="utf-8"))
    assert out_schema["properties"]["duplicate_groups"] == {"type": "array", "description": "Each group of duplicates with file and line", "items": {}}


def test_the_report_is_honest_about_what_did_not_run(tmp_path):
    result, _ = run(tmp_path, [round_one(), round_two(), draft()])
    report = (result.out_dir / "report.md").read_text(encoding="utf-8")
    assert "every check that ran passed" in report and "not a guarantee" in report
    for skipped in ("sandbox", "real agent", "conflicting rules", "security review"):
        assert skipped in report
    assert "| every acceptance criterion is covered by at least one test | passed |" in report
    assert sum(c.status == "not run" for c in result.checks) == 4


# ---- stopping honestly -------------------------------------------------------------------------------------


def test_without_a_way_to_ask_the_build_stops_and_writes_nothing(tmp_path):
    def cannot_ask(questions):
        raise NeedAnswers(questions)

    with pytest.raises(NeedAnswers) as info:
        run(tmp_path, [round_one()], ask=cannot_ask)
    assert [q.slot for q in info.value.questions] == ["constraints", "acceptance_criteria", "failure_behavior"]
    assert not (tmp_path / "out").exists()


def test_a_fabricated_quote_means_the_slot_is_asked_again(tmp_path):
    invented = round_one().model_copy(update=dict(
        constraints=slot(["only TypeScript"], "limited to TypeScript"),  # the person never said this
        acceptance_criteria=slot(["it is accurate"], "it is accurate"),
        failure_behavior=slot(["do nothing"], "do nothing"),
    ))
    asked = []

    def ask(questions):
        asked.append([q.slot for q in questions])
        return ask_answers(questions)

    result, _ = run(tmp_path, [invented, round_two(), draft()], ask=ask)
    assert asked == [["constraints", "acceptance_criteria", "failure_behavior"]]
    assert result.status == "ok"


def test_not_approved_means_nothing_is_built(tmp_path):
    mock = MockProvider([round_one(), round_two()])
    with pytest.raises(BuildError, match="not approved"):
        build_skill(FIRST, mock, ask=ask_answers, approve=lambda spec: False, out_root=tmp_path / "out", now=NOW)
    assert len(mock.calls) == 2 and not (tmp_path / "out").exists()  # no design call was spent


def test_requests_that_are_not_skills_are_refused_with_an_explanation(tmp_path):
    as_agent = round_two().model_copy(update=dict(kind="agent"))
    with pytest.raises(BuildError, match="not a skill"):
        run(tmp_path, [as_agent])


def test_a_too_short_description_and_endless_questions_both_stop(tmp_path):
    with pytest.raises(BuildError, match="at least a sentence"):
        run(tmp_path, [], description="skill")
    with pytest.raises(BuildError, match="still incomplete after 2 rounds"):
        run(tmp_path, [round_one(), round_one()], max_rounds=2, ask=lambda qs: {q.slot: "maybe" for q in qs})


def test_empty_answers_stop_instead_of_looping(tmp_path):
    with pytest.raises(BuildError, match="No answers were given"):
        run(tmp_path, [round_one()], ask=lambda qs: {q.slot: " " for q in qs})


# ---- checks, repair and draft status -----------------------------------------------------------------------


def uncovered_tests():
    return draft(tests=[
        SkillTest(name="p", kind="positive", input_description="x", expected_result="y", covers=["AC1"]),
        SkillTest(name="n", kind="negative", input_description="x", expected_result="y", covers=["AC9"]),  # unknown criterion
    ])


def test_a_failing_design_is_repaired_once_with_the_exact_failures(tmp_path):
    bad = draft(tests=[SkillTest(name="p", kind="positive", input_description="x", expected_result="y", covers=[])])
    result, mock = run(tmp_path, [round_one(), round_two(), bad, draft()])
    assert result.status == "ok" and result.model_calls == 4
    assert "every acceptance criterion is covered by at least one test: not covered: AC1" in mock.calls[3]["prompt"]
    assert any("fix them once" in n for n in result.notes)


def test_a_design_that_still_fails_is_written_as_a_draft_and_says_so(tmp_path):
    result, _ = run(tmp_path, [round_one(), round_two(), uncovered_tests(), uncovered_tests()])
    assert result.status == "draft"
    failed = {c.name for c in result.checks if c.status == "failed"}
    assert "tests only cite acceptance criteria that exist" in failed
    report = (result.out_dir / "report.md").read_text(encoding="utf-8")
    assert "DRAFT" in report and "failed" in report and "every check that ran passed" not in report


def test_an_invalid_name_is_fixed_by_code_and_reported(tmp_path):
    result, _ = run(tmp_path, [round_one(), round_two(), draft(name="../My Skill!!")])
    assert result.sdm.name == "my-skill" and result.out_dir == tmp_path / "out" / "my-skill"
    assert result.sdm.provenance.name_adjusted
    assert "was changed to 'my-skill'" in (result.out_dir / "report.md").read_text(encoding="utf-8")


def test_an_existing_folder_is_never_overwritten_without_force(tmp_path):
    run(tmp_path, [round_one(), round_two(), draft()])
    with pytest.raises(BuildError, match="already exists"):
        run(tmp_path, [round_one(), round_two(), draft()])
    assert run(tmp_path, [round_one(), round_two(), draft()], force=True)[0].status == "ok"


# ---- safety and determinism --------------------------------------------------------------------------------


def test_hostile_text_cannot_break_the_front_matter_or_run_as_a_template(tmp_path):
    nasty = 'Finds it: "quoted" --- and\nnew lines # not a comment {{ 7*7 }} {% evil %}'
    result, _ = run(tmp_path, [round_one(), round_two(), draft(description=nasty, does=["{{ 7*7 }}"])])
    text = (result.out_dir / "SKILL.md").read_text(encoding="utf-8")
    meta = yaml.safe_load(text.split("---\n")[1])
    assert meta["description"] == " ".join(nasty.split()) and meta["name"] == "duplicate-function-finder"
    assert "- {{ 7*7 }}" in text and "49" not in text  # model text is data: it is written as is, never evaluated
    assert result.status == "ok"


def test_the_same_definition_always_renders_the_same_bytes(tmp_path):
    first = run(tmp_path, [round_one(), round_two(), draft()])[0]
    again = rebuild(first.out_dir / "skill.sdm.json", tmp_path / "again", force=False)
    assert again.status == "ok"
    for rel in ("SKILL.md", "README.md", "schemas/input.schema.json", "tests/cases.json", "skill.sdm.json", "spec.json"):
        assert (first.out_dir / rel).read_bytes() == (again.out_dir / rel).read_bytes(), rel
    assert "no model was used" in (again.out_dir / "report.md").read_text(encoding="utf-8")


def test_rebuild_refuses_a_name_that_would_escape_the_output_folder(tmp_path):
    first = run(tmp_path, [round_one(), round_two(), draft()])[0]
    sdm_path = first.out_dir / "skill.sdm.json"
    data = json.loads(sdm_path.read_text(encoding="utf-8"))
    data["name"] = "../escaped"
    sdm_path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(BuildError, match="not a valid skill name"):
        rebuild(sdm_path, tmp_path / "again", force=False)
    assert not (tmp_path / "escaped").exists() and not (tmp_path / "again").exists()


def test_schema_builder_output_is_always_valid_json_schema():
    from jsonschema import Draft202012Validator

    fields = [IOField(name=n, type=t, description="d d", required=i % 2 == 0)
              for i, (n, t) in enumerate([("a", "string"), ("b", "integer"), ("c", "number"), ("d", "boolean"), ("e", "list"), ("f", "object")])]
    Draft202012Validator.check_schema(schema_for("t", fields))


# ---- command line ------------------------------------------------------------------------------------------


def run_cli(capsys, *argv):
    code = cli.main(list(argv))
    out = capsys.readouterr()
    return code, out.out, out.err


def test_cli_build_with_an_answers_file_and_yes(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(cli, "provider_from_env", lambda: MockProvider([round_one(), round_two(), draft()]))
    answers = tmp_path / "answers.json"
    answers.write_text(json.dumps(ANSWERS), encoding="utf-8")
    code, out, _ = run_cli(capsys, "build", FIRST, "--answers", str(answers), "--yes", "--out", str(tmp_path / "skills"))
    assert code == 0 and "Skill 'duplicate-function-finder' written to" in out
    assert "4 not run" in out and "report.md" in out
    assert (tmp_path / "skills" / "duplicate-function-finder" / "SKILL.md").exists()


def test_cli_build_without_answers_lists_the_questions_and_exits_cleanly(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(cli, "provider_from_env", lambda: MockProvider([round_one()]))
    code, _, err = run_cli(capsys, "build", FIRST, "--yes", "--out", str(tmp_path / "skills"))
    assert code == 2
    assert "[acceptance_criteria]" in err and "--answers FILE.json" in err and '"constraints": "..."' in err


def test_cli_a_draft_exits_with_code_1(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(cli, "provider_from_env", lambda: MockProvider([round_one(), round_two(), uncovered_tests(), uncovered_tests()]))
    answers = tmp_path / "a.json"
    answers.write_text(json.dumps(ANSWERS), encoding="utf-8")
    code, out, _ = run_cli(capsys, "build", FIRST, "--answers", str(answers), "--yes", "--out", str(tmp_path / "s"))
    assert code == 1 and "DRAFT skill" in out and "FAILED:" in out


def test_cli_build_from_a_suggest_report(monkeypatch, capsys, tmp_path):
    report = tmp_path / "report.json"
    report.write_text(json.dumps({"suggestions": [
        {"title": "A refactor", "skill_requirement": ""},
        {"title": "Duplicate finder", "skill_requirement": FIRST},
    ]}), encoding="utf-8")
    code, _, err = run_cli(capsys, "build", "--from-suggestions", str(report), "--yes")
    assert code == 2 and "--pick" in err and "1. Duplicate finder" in err  # only ideas with a requirement are offered

    mock = MockProvider([round_one(), round_two(), draft()])
    monkeypatch.setattr(cli, "provider_from_env", lambda: mock)
    answers = tmp_path / "a.json"
    answers.write_text(json.dumps(ANSWERS), encoding="utf-8")
    code, out, _ = run_cli(capsys, "build", "--from-suggestions", str(report), "--pick", "1", "--answers", str(answers), "--yes", "--out", str(tmp_path / "s"))
    assert code == 0 and FIRST in mock.calls[0]["prompt"]


def test_cli_render_command_needs_no_model(capsys, tmp_path):
    first = run(tmp_path, [round_one(), round_two(), draft()])[0]
    code, out, _ = run_cli(capsys, "render", str(first.out_dir / "skill.sdm.json"), "--out", str(tmp_path / "again"))
    assert code == 0 and "written to" in out


def test_cli_build_without_a_description_or_key_explains(capsys):
    code, _, err = run_cli(capsys, "build")
    assert code == 2 and "Give a description" in err
    code, _, err = run_cli(capsys, "build", FIRST, "--yes")
    assert code == 2 and "LLM_PROVIDER" in err
