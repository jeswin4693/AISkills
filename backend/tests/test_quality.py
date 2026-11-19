"""What makes a built skill work well and cost little: the description, the requirement carried into SKILL.md, the
quality checks and the token estimate. All offline, no model: the pipeline tests use the scripted MockProvider.
"""

from __future__ import annotations

import json

import pytest
import yaml
from test_skill_build import NOW, draft, round_one, round_two, run

from skillforge.build.models import IOField, RequirementSpec, SkillTest, Step
from skillforge.build.pipeline import _assemble, rebuild
from skillforge.build.quality import (
    CHARS_PER_TOKEN, HEAVY_DESCRIPTION_TOKENS, HEAVY_SKILL_TOKENS, clean_triggers, compose_description, core, estimate_tokens,
    has_when_clause, is_none_like, quality_checks, quality_warnings, rendered_quality, requirement_lines, says_use_when,
    sentence, similar, token_cost,
)
from skillforge.providers import MockProvider

SPEC = RequirementSpec(
    goal="Find duplicate functions", constraints=["never edit files"],
    acceptance_criteria=["every duplicate pair is listed with its file and line"], failure_behavior="stop and say so",
)


def sdm_of(**overrides):
    return _assemble(draft(**overrides), SPEC, MockProvider([]), NOW)


def row(checks, fragment):
    found = [c for c in checks if fragment in c.name]
    assert len(found) == 1, f"expected one check containing '{fragment}', got {[c.name for c in checks]}"
    return found[0]


# ---- the description ---------------------------------------------------------------------------------


def test_the_description_is_the_what_plus_the_when_built_from_the_trigger_phrases():
    d = compose_description("Writes a commit message from a short note", ["write a commit message", "summarise my changes"])
    assert d == 'Writes a commit message from a short note. Use when the request involves "write a commit message" or "summarise my changes".'
    three = compose_description("Does x.", ["a", "b", "c"])
    assert three == 'Does x. Use when the request involves "a", "b", or "c".'
    assert compose_description("Does x.", ["only one"]) == 'Does x. Use when the request involves "only one".'


def test_a_description_that_already_says_when_is_left_alone_and_nothing_is_added_twice():
    own = "Counts TODOs. Use this whenever someone asks how many are left."
    assert compose_description(own, ["count todos"]) == own
    once = compose_description("Counts TODOs", ["count todos"])
    assert compose_description(once, ["count todos"]) == once  # composing a composed description changes nothing


def test_an_incidental_when_in_the_sentence_does_not_stop_the_trigger_phrases_being_added():
    d = compose_description("Converts dates when they are ambiguous", ["fix a date format"])
    assert says_use_when("Converts dates when they are ambiguous") is False
    assert d.endswith('Use when the request involves "fix a date format".') and d.startswith("Converts dates when they are ambiguous.")


def test_no_trigger_phrases_means_the_sentence_alone_and_the_limit_is_never_passed():
    assert compose_description("Does x", []) == "Does x."
    many = [f"a rather long trigger phrase number {i:02d} for testing" for i in range(5)]
    d = compose_description("W" * 960, many, limit=1024)
    assert len(d) <= 1024 and d.startswith("W" * 960)  # triggers that do not fit are left out, never cut in half
    assert not d.endswith('"') or d.count('"') % 2 == 0


def test_trigger_phrases_are_cleaned_deduplicated_and_capped():
    raw = ["  Write a commit message. ", "write a commit message", "", "x" * 200, '"quoted"', "b", "c", "d", "e", "f"]
    assert clean_triggers(raw) == ["Write a commit message", "quoted", "b", "c", "d"]


def test_the_lenient_when_check_accepts_other_ways_of_saying_when():
    assert has_when_clause("Reviews code when a pull request is opened.")
    assert has_when_clause("Use this after finishing a change.")
    assert not has_when_clause("Reviews code.")


# ---- the requirement carried into the skill ----------------------------------------------------------


def test_the_persons_requirement_is_carried_over_word_for_word_with_a_capital_first_letter():
    lines = requirement_lines(sdm_of(), SPEC)
    assert lines.rules == ["Never edit files"]
    assert lines.done_when == ["Every duplicate pair is listed with its file and line"]
    assert lines.failure == ["Stop and say so"]  # the model's "If the path is unreadable, stop and say so." only restates it
    assert lines.donts == ["Edit any file"]
    assert lines.example_given == "A repo with two identical functions" and lines.example_expect == "Both listed with file and line"


def test_none_and_repeats_are_left_out_so_no_tokens_are_spent_on_nothing():
    spec = SPEC.model_copy(update=dict(
        constraints=["none", "Every duplicate pair is listed with its file and line", "  keep it   fast "], failure_behavior="None.",
    ))
    lines = requirement_lines(sdm_of(does_not=["nothing"], error_handling=["Say so.", "say so."]), spec)
    assert lines.rules == ["Keep it fast"]  # "none" skipped, the repeat of an acceptance criterion said once
    assert lines.donts == [] and lines.failure == ["Say so."]  # "nothing" skipped; a repeat said once
    assert is_none_like("N/A") and is_none_like(" None. ") and not is_none_like("none of the files")
    assert sentence("  stop   and say so") == "Stop and say so"


def test_the_example_is_the_first_positive_test_and_absent_without_one():
    tests = [
        SkillTest(name="a", kind="negative", input_description="bad", expected_result="error", covers=["AC1"]),
        SkillTest(name="b", kind="positive", input_description="good one", expected_result="result one", covers=["AC1"]),
        SkillTest(name="c", kind="positive", input_description="good two", expected_result="result two", covers=["AC1"]),
    ]
    lines = requirement_lines(sdm_of(tests=tests), SPEC)
    assert (lines.example_given, lines.example_expect) == ("good one", "result one")
    assert requirement_lines(sdm_of(tests=tests[:1]), SPEC).example_given == ""


def test_a_do_not_the_person_already_stated_as_a_rule_is_not_said_again_and_its_lead_in_is_dropped():
    """From a real run: the rule was "It does not look at the git repository or the files." and the design repeated it
    as "Do not: It does not look at ..."."""
    spec = SPEC.model_copy(update=dict(constraints=["It does not look at the git repository or the files."]))
    sdm = sdm_of(does_not=["It does not look at the git repository or the files.", "Doesn't edit any file", "never run commands", "Edit any file"])
    lines = requirement_lines(sdm, spec)
    assert lines.rules == ["It does not look at the git repository or the files."]
    assert lines.donts == ["Edit any file", "Run commands"]  # the repeat of the rule and the second "edit any file" are gone
    assert core("It does not look at files") == "look at files" and core("Never run commands") == "run commands"
    assert core("Edit any file") == "Edit any file" and core("Doesn't matter much") == "matter much"


def test_failure_lines_that_only_restate_an_earlier_one_are_left_out_but_different_ones_stay():
    """From a real run: three lines all said "ask the person for a description instead of guessing"."""
    spec = SPEC.model_copy(update=dict(failure_behavior="If no description is given, it asks the person for one instead of guessing."))
    sdm = sdm_of(error_handling=[
        "If the input change_description is empty or missing, ask the person for a description instead of guessing.",
        "If the file is empty, report that nothing was found.",
    ])
    assert requirement_lines(sdm, spec).failure == [
        "If no description is given, it asks the person for one instead of guessing.",
        "If the file is empty, report that nothing was found.",
    ]


def test_similarity_needs_shared_content_words_and_never_calls_a_very_short_line_a_repeat():
    assert similar("Stop and say so", "If the path is unreadable, stop and say so.")
    assert not similar("Stop and say so", "Report that the folder has no files.")
    assert not similar("Say so.", "Say so, please.")  # fewer than three content words: never a repeat
    assert not similar("", "anything at all here")


# ---- the quality checks on the design ----------------------------------------------------------------


def test_a_good_design_passes_every_quality_check():
    checks = quality_checks(sdm_of())
    assert [c.status for c in checks] == ["passed"] * 5 and quality_warnings(sdm_of()) == []


def test_without_trigger_phrases_the_description_is_flagged_even_when_it_says_when():
    sdm = sdm_of(triggers=[], description="Finds duplicate functions. Use it when cleaning up.")
    c = row(quality_checks(sdm), "says when to use")
    assert c.status == "warning" and "fewer than two concrete trigger phrases" in c.detail
    none = sdm_of(triggers=[]).model_copy(update={"description": "Finds duplicate functions."})
    c = row(quality_checks(none), "says when to use")
    assert c.status == "warning" and "may never pick it" in c.detail


def test_an_input_no_step_uses_and_an_output_no_step_produces_are_named():
    steps = [Step(title="Look", instruction="Read the code.", on_failure="none"), Step(title="Say", instruction="Say what you found.", on_failure="none")]
    c = row(quality_checks(sdm_of(workflow=steps)), "named in the workflow")
    assert c.status == "warning" and "`repository_path`" in c.detail and "`duplicate_groups`" in c.detail
    assert "ignore it" in c.detail and "nothing says how to make it" in c.detail


def test_a_field_may_be_named_in_words_instead_of_with_its_exact_name():
    steps = [Step(title="Look", instruction="Read the repository path you were given.", on_failure="none"),
             Step(title="Say", instruction="List the duplicate groups.", on_failure="none")]
    assert row(quality_checks(sdm_of(workflow=steps)), "named in the workflow").status == "passed"


def test_vague_wording_is_named_by_step_and_phrase():
    steps = [
        Step(title="Read", instruction="Read `repository_path` as needed.", on_failure="none"),
        Step(title="Group", instruction="Group the functions properly.", on_failure="Fix it if necessary, etc."),
        Step(title="Report", instruction="Return `duplicate_groups`.", on_failure="none"),
    ]
    c = row(quality_checks(sdm_of(workflow=steps)), "vague wording")
    assert c.status == "warning" and "step 1: 'as needed'" in c.detail and "step 2: " in c.detail
    assert "'properly'" in c.detail and "'if necessary'" in c.detail and "'etc.'" in c.detail and "step 3" not in c.detail


def test_an_example_whose_expected_output_repeats_itself_is_flagged():
    """From a real run: the expected title was "Fix login button alignment Fix login button alignment on mobile screen"."""
    garbled = [SkillTest(name="p", kind="positive", input_description="fix login button alignment on mobile screen",
                         expected_result='commit_message: "Fix login button alignment Fix login button alignment on mobile screen"', covers=["AC1"]),
               SkillTest(name="n", kind="negative", input_description="x", expected_result="y", covers=["AC1"])]
    c = row(quality_checks(sdm_of(tests=garbled)), "does not repeat itself")
    assert c.status == "warning" and "'fix login button alignment' twice" in c.detail and "copies its examples" in c.detail
    assert row(quality_checks(sdm_of()), "does not repeat itself").status == "passed"
    no_example = [SkillTest(name="n", kind="negative", input_description="x", expected_result="y", covers=["AC1"])]
    assert not [c for c in quality_checks(sdm_of(tests=no_example)) if "repeat itself" in c.name]  # nothing ran, so no "passed"


def test_a_step_that_is_too_long_to_follow_is_flagged_with_its_length():
    long = " ".join(["word"] * 61)
    steps = [Step(title="Read", instruction=f"Read `repository_path`. {long}", on_failure="none"),
             Step(title="Report", instruction="Return `duplicate_groups`.", on_failure="none")]
    c = row(quality_checks(sdm_of(workflow=steps)), "short enough")
    assert c.status == "warning" and "step 1 (63 words)" in c.detail


def test_a_skill_saved_before_triggers_existed_still_loads_and_says_so():
    sdm = sdm_of().model_copy(update={"triggers": []})
    assert sdm.model_dump()["triggers"] == []
    assert "triggers" in json.loads(sdm.model_dump_json())
    old = json.loads(sdm.model_dump_json())
    del old["triggers"]
    from skillforge.build.models import SkillDefinition
    loaded = SkillDefinition.model_validate(old)
    assert loaded.triggers == []
    c = row(quality_checks(loaded), "says when to use")  # its description says when, but there are no phrases to match on
    assert c.status == "warning" and "fewer than two concrete trigger phrases" in c.detail


# ---- the checks on the written files and the token cost ----------------------------------------------


def files_of(sdm):
    from skillforge.build.render import render_files
    return render_files(sdm, SPEC)


def test_the_requirement_reached_skill_md_and_a_missing_line_is_a_failure():
    sdm = sdm_of()
    files = files_of(sdm)
    ok = row(rendered_quality(files, sdm, SPEC), "word for word")
    assert ok.status == "passed" and "3 requirement line(s)" in ok.detail
    files["SKILL.md"] = files["SKILL.md"].replace("Never edit files", "Be careful")
    bad = row(rendered_quality(files, sdm, SPEC), "word for word")
    assert bad.status == "failed" and "'Never edit files'" in bad.detail


def test_the_example_check_warns_when_there_is_no_positive_test():
    sdm = sdm_of(tests=[SkillTest(name="n", kind="negative", input_description="x", expected_result="y", covers=["AC1"])])
    c = row(rendered_quality(files_of(sdm), sdm, SPEC), "worked example")
    assert c.status == "warning" and "no positive test case" in c.detail
    assert row(rendered_quality(files_of(sdm_of()), sdm_of(), SPEC), "worked example").status == "passed"


def test_the_token_cost_splits_always_loaded_from_loaded_when_used_from_only_if_opened():
    sdm = sdm_of()
    files = files_of(sdm)
    cost = token_cost(files, sdm)
    assert cost.always == estimate_tokens(f"{sdm.name} {sdm.description}")
    assert cost.when_used == estimate_tokens(files["SKILL.md"])
    assert cost.on_demand == sum(estimate_tokens(t) for r, t in files.items() if r != "SKILL.md")
    assert 0 < cost.always < cost.when_used < cost.on_demand
    assert estimate_tokens("") == 0 and estimate_tokens("abcd") == 1 and estimate_tokens("abcde") == 2 and CHARS_PER_TOKEN == 4


def test_a_heavy_description_or_a_heavy_skill_md_is_flagged_and_the_estimate_is_labelled_as_one():
    heavy_desc = sdm_of().model_copy(update={"description": "Does a thing. " + "word " * (HEAVY_DESCRIPTION_TOKENS * 2)})
    c = row(rendered_quality(files_of(heavy_desc), heavy_desc, SPEC), "token cost")
    assert c.status == "warning" and "paid on every task" in c.detail and "Estimated at 4 characters per token" in c.detail
    big = sdm_of(limitations=[]).model_copy(update={"does_not": [f"thing{i} " + "x " * 40 for i in range(HEAVY_SKILL_TOKENS // 8)]})  # distinct lines: repeats are dropped
    c = row(rendered_quality(files_of(big), big, SPEC), "token cost")
    assert c.status == "warning" and "SKILL.md is long" in c.detail
    ok = row(rendered_quality(files_of(sdm_of()), sdm_of(), SPEC), "token cost")
    assert ok.status == "passed" and "always loaded" in ok.detail and "when the skill is used" in ok.detail


# ---- the pipeline ------------------------------------------------------------------------------------


def weak_design():
    """Structurally valid, but nothing says when to use it, no step names an input or an output, and it is vague."""
    steps = [
        Step(title="Read", instruction="Read the code as needed.", on_failure="Stop and say so."),
        Step(title="Compare", instruction="Group similar functions properly.", on_failure="Say so."),
        Step(title="Report", instruction="Say what you found.", on_failure="Say so."),
    ]
    return draft(triggers=[], description="Finds duplicates.", workflow=steps)


def test_a_clean_design_is_built_with_one_design_call_and_the_description_is_composed_by_code(tmp_path):
    result, mock = run(tmp_path, [round_one(), round_two(), draft()])
    assert result.status == "ok" and result.model_calls == 3
    text = (result.out_dir / "SKILL.md").read_text(encoding="utf-8")
    meta = yaml.safe_load(text.split("---\n")[1])
    assert meta["description"] == (
        'Finds duplicate functions in a TypeScript repository and proposes safe refactors. Use when the request involves '
        '"find duplicate functions", "clean up copy-pasted code", or "suggest a shared helper".'
    )
    assert result.sdm.triggers == ["find duplicate functions", "clean up copy-pasted code", "suggest a shared helper"]
    assert result.tokens is not None and result.tokens.when_used == estimate_tokens(text)
    report = (result.out_dir / "report.md").read_text(encoding="utf-8")
    assert "| the approved requirement reached SKILL.md word for word | passed |" in report
    assert "token cost of using the skill (an estimate)" in report


def test_quality_warnings_alone_earn_one_repair_and_the_model_is_told_exactly_what_to_fix(tmp_path):
    result, mock = run(tmp_path, [round_one(), round_two(), weak_design(), draft()])
    assert result.model_calls == 4 and result.status == "ok"
    repair_prompt = mock.calls[3]["prompt"]
    assert "did not pass these automatic checks" in repair_prompt
    assert "may never pick it" in repair_prompt and "no step uses the input `repository_path`" in repair_prompt
    assert "'as needed'" in repair_prompt
    assert any("went from 0 and" in n and "to 0 and 0" in n for n in result.notes), result.notes
    assert "Use when the request involves" in (result.out_dir / "SKILL.md").read_text(encoding="utf-8")


def test_a_repair_that_makes_things_worse_is_not_kept(tmp_path):
    worse = draft(triggers=[], description="Finds duplicates.", tests=[
        SkillTest(name="p", kind="positive", input_description="a", expected_result="b", covers=[]),  # no acceptance criterion covered
        SkillTest(name="n", kind="negative", input_description="a", expected_result="b", covers=[]),
    ])
    result, _ = run(tmp_path, [round_one(), round_two(), weak_design(), worse])
    assert result.status == "ok"  # the first design had only warnings, and it was kept
    assert result.sdm.description.startswith("Finds duplicates.") and "no trigger" not in result.sdm.description
    assert any("second design was worse, so the first was kept" in n for n in result.notes), result.notes
    report = (result.out_dir / "report.md").read_text(encoding="utf-8")
    assert "| warning |" in report or "warning(s)" in report  # what is still weak is shown, not hidden


def test_a_step_that_cannot_fail_says_none_and_no_failure_line_is_written(tmp_path):
    steps = [
        Step(title="Read the repository", instruction="List the files under `repository_path`.", on_failure="Stop and say the path cannot be read."),
        Step(title="Report", instruction="Return `duplicate_groups`.", on_failure="none"),
    ]
    result, _ = run(tmp_path, [round_one(), round_two(), draft(workflow=steps)])
    text = (result.out_dir / "SKILL.md").read_text(encoding="utf-8")
    assert "2. **Report**: Return `duplicate_groups`.\n" in text and text.count("On failure:") == 1
    assert result.status == "ok"  # "none" is an answer, so the structural check still passes


def test_what_is_for_people_is_in_the_readme_not_in_the_skill_the_agent_loads(tmp_path):
    result, _ = run(tmp_path, [round_one(), round_two(), draft()])
    skill = (result.out_dir / "SKILL.md").read_text(encoding="utf-8")
    readme = (result.out_dir / "README.md").read_text(encoding="utf-8")
    for heading in ("## What it does", "## Limitations", "## Permissions"):
        assert heading in readme and heading not in skill
    assert "Find functions with the same structure" in readme and "Find functions with the same structure" not in skill


def test_the_description_is_not_repeated_in_the_body_and_nothing_is_padded(tmp_path):
    result, _ = run(tmp_path, [round_one(), round_two(), draft()])
    text = (result.out_dir / "SKILL.md").read_text(encoding="utf-8")
    body = text.split("---\n", 2)[2]
    assert "Use when the request involves" not in body and "Finds duplicate functions in a TypeScript repository" not in body
    assert "\n\n\n" not in text  # no stacked blank lines: each costs a token


def test_rebuilding_an_old_definition_without_triggers_still_works_and_gives_the_same_bytes_each_time(tmp_path):
    first = run(tmp_path, [round_one(), round_two(), draft()])[0]
    sdm_path = first.out_dir / "skill.sdm.json"
    data = json.loads(sdm_path.read_text(encoding="utf-8"))
    del data["triggers"]  # as saved by a version of this program that did not have triggers
    sdm_path.write_text(json.dumps(data), encoding="utf-8")
    a = rebuild(sdm_path, tmp_path / "a", force=False)
    b = rebuild(sdm_path, tmp_path / "b", force=False)
    assert a.status == "ok" and (a.out_dir / "SKILL.md").read_bytes() == (b.out_dir / "SKILL.md").read_bytes()
    assert "Use when the request involves" in (a.out_dir / "SKILL.md").read_text(encoding="utf-8")  # kept from the saved description


@pytest.mark.parametrize("bad", ["", "   "])
def test_an_empty_trigger_list_or_blank_phrases_never_produce_a_broken_description(bad):
    assert compose_description("Does x", [bad]) == "Does x."
    assert IOField  # the model module is still the one the tests import from
