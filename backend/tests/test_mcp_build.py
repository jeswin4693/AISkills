"""The MCP server builder, offline: understanding, the design, the files, the checks and the build. A MockProvider stands in
for the model, so nothing here calls a hosted model and nothing runs generated code."""

from __future__ import annotations

import ast
import json
from datetime import datetime, timezone

import pytest

from skillforge.build.mcp import (
    MCP_DESIGN_SYSTEM, MCP_EXTRACT_SYSTEM, MCP_QUESTIONS, MCP_SDK_VERSION, McpCase, McpDraft, McpParam, McpTool,
    assemble_mcp, render_mcp_files,
)
from skillforge.build.mcp_pipeline import build_mcp_from_spec, check_mcp
from skillforge.build.models import SLOTS, Extraction, RequirementSpec, Slot
from skillforge.build.pipeline import BuildError, understand_round
from skillforge.providers import MockProvider
from skillforge.results import FAILED, NOT_RUN, PASSED, WARNING
from skillforge.validate import validate_files
from skillforge.validate.mcp import analyze_server

NOW = datetime(2026, 11, 20, 12, 0, tzinfo=timezone.utc)

WORDS = (
    "A server with two tools. count_words counts the words in a text. shout returns a text in capital letters. "
    "It only works on the text it is given. A text of three words gives 3, and shout on an empty text is an error. "
    "If the text is empty it raises an error."
)


def slot(values: list[str] | None = None, quote: str = "") -> Slot:
    return Slot(values=values or [], quote=quote)


def extraction(**changes: Slot) -> Extraction:
    base = dict(
        kind="tool",
        goal=slot(["Count the words in a text and return a text in capital letters"], "count_words counts the words in a text"),
        inputs=slot(["a text"], "the text it is given"),
        outputs=slot(["the count, or the capital letters"], "shout returns a text in capital letters"),
        constraints=slot(["only work on the text it is given"], "It only works on the text it is given"),
        acceptance_criteria=slot(["a text of three words gives 3", "shout on an empty text is an error"], "A text of three words gives 3, and shout on an empty text is an error"),
        failure_behavior=slot(["raise an error when the text is empty"], "If the text is empty it raises an error"),
    )
    base.update(changes)
    return Extraction(**base)


def spec() -> RequirementSpec:
    return RequirementSpec(
        kind="tool", goal="Count the words in a text and return a text in capital letters", inputs=["a text"],
        outputs=["the count, or the capital letters"], constraints=["only work on the text it is given"],
        acceptance_criteria=["a text of three words gives 3", "shout on an empty text is an error"],
        failure_behavior="raise an error when the text is empty", user_words=WORDS, rounds=1,
    )


def draft(**changes) -> McpDraft:
    base = dict(
        name="word-tools", description="Counts the words in a text and shouts a text.",
        tools=[
            McpTool(name="count_words", description="Count the words in a text and return the count as text.",
                    params=[McpParam(name="text", type="str", description="the text to count in")],
                    body=["words = text.split()", "return str(len(words))"]),
            McpTool(name="shout", description="Return the text in capital letters.",
                    params=[McpParam(name="text", type="str", description="the text to shout")],
                    body=["if not text.strip():", '    raise ValueError("text is empty")', "return text.upper()"]),
        ],
        permissions=[], env_vars=[],
        cases=[
            McpCase(name="three words", kind="positive", tool="count_words", arguments_json='{"text": "one two three"}', expect="contains", expected_text="3", covers=["AC1"]),
            McpCase(name="empty shout", kind="negative", tool="shout", arguments_json='{"text": ""}', expect="error", expected_text="", covers=["AC2"]),
            McpCase(name="no words", kind="edge", tool="count_words", arguments_json='{"text": ""}', expect="equals", expected_text="0", covers=["AC1"]),
        ],
        limitations=["Words are separated by white space only."],
    )
    base.update(changes)
    return McpDraft(**base)


def with_tool(**changes) -> McpTool:
    base = dict(name="extra", description="Do one more thing and return a text.", params=[McpParam(name="text", type="str", description="the text")], body=["return text"])
    base.update(changes)
    return McpTool(**base)


def extra_cases() -> list[McpCase]:
    """Cases for a design whose only tool is `extra`, so the cases are not what a test is about."""
    return [
        McpCase(name="ok", kind="positive", tool="extra", arguments_json='{"text": "a"}', expect="contains", expected_text="a", covers=["AC1"]),
        McpCase(name="refused", kind="negative", tool="extra", arguments_json='{"text": ""}', expect="error", expected_text="", covers=["AC2"]),
    ]


def defn_and_files(d: McpDraft | None = None):
    defn = assemble_mcp(d or draft(), spec(), MockProvider([]), NOW)
    return defn, render_mcp_files(defn, spec())


def results(d: McpDraft) -> dict[str, tuple[str, str]]:
    defn, files = defn_and_files(d)
    return {c.name: (c.status, c.detail) for c in check_mcp(defn, spec(), files)}


def failed(d: McpDraft) -> list[str]:
    return [name for name, (status, _) in results(d).items() if status == FAILED]


def warned(d: McpDraft) -> list[str]:
    return [name for name, (status, _) in results(d).items() if status == WARNING]


# ---- understanding -----------------------------------------------------------------------------------


def test_a_server_request_is_complete_when_the_builder_is_not_skill_only():
    r = understand_round(MockProvider([extraction()]), WORDS, 1, 3, questions=MCP_QUESTIONS, extract_system=MCP_EXTRACT_SYSTEM, skill_only=False)
    assert r.state == "complete" and r.spec.goal.startswith("Count the words")


def test_the_questions_and_the_extraction_prompt_are_worded_for_a_server():
    assert set(MCP_QUESTIONS) == set(SLOTS)
    mock = MockProvider([extraction(constraints=slot(), failure_behavior=slot())])
    r = understand_round(mock, WORDS, 1, 3, questions=MCP_QUESTIONS, extract_system=MCP_EXTRACT_SYSTEM, skill_only=False)
    assert [q.slot for q in r.questions] == ["constraints", "failure_behavior"]
    assert "network" in r.questions[0].text and "environment variable" in MCP_QUESTIONS["constraints"].lower() + MCP_QUESTIONS["inputs"].lower()
    assert mock.calls[0]["system"] == MCP_EXTRACT_SYSTEM and "MCP server" in MCP_EXTRACT_SYSTEM


def test_the_design_prompt_states_the_rules_code_enforces():
    for rule in ("standard library", "return a string", "environment variable", "network", "never write"):
        assert rule in MCP_DESIGN_SYSTEM.lower()


# ---- the definition, assembled by code ----------------------------------------------------------------


def test_the_name_is_made_safe_and_the_definition_carries_what_code_decided():
    defn = assemble_mcp(draft(name="Word Tools!!"), spec(), MockProvider([]), NOW)
    assert defn.name == "word-tools" and defn.provenance.name_adjusted
    assert defn.sdk == MCP_SDK_VERSION == "2.3.0" and defn.kind == "mcp" and defn.version == "0.1.0"
    assert defn.acceptance_criteria == {"AC1": "a text of three words gives 3", "AC2": "shout on an empty text is an error"}


def test_the_files_are_exactly_these():
    _, files = defn_and_files()
    assert sorted(files) == ["README.md", "mcp.sdm.json", "requirements.txt", "server.py", "spec.json", "tests/cases.json"]
    assert files["requirements.txt"] == "mcp==2.3.0\n"


def test_server_py_is_written_by_code_from_the_design():
    _, files = defn_and_files()
    source = files["server.py"]
    ast.parse(source)
    assert "from mcp.server.mcpserver import MCPServer" in source
    assert 'mcp = MCPServer("word-tools", instructions="Counts the words in a text and shouts a text.")' in source
    assert "def count_words(text: str) -> str:" in source and "def shout(text: str) -> str:" in source
    assert "        raise ValueError(\"text is empty\")" in source  # the model's lines are indented by code
    assert source.rstrip().endswith('if __name__ == "__main__":\n    mcp.run()')
    assert "Args:\n        text: the text to count in" in source


def test_the_generated_server_passes_its_own_checks_and_the_folder_checks():
    defn, files = defn_and_files()
    static = validate_files({p: t.encode() for p, t in files.items()}, folder="word-tools", kind="mcp")
    assert all(c.status == PASSED for c in static), [(c.name, c.detail) for c in static if c.status != PASSED]
    facts = analyze_server(files["server.py"])
    assert [t.name for t in facts.tools] == ["count_words", "shout"] and facts.calls_run and facts.capabilities == set()


def test_tool_annotations_are_decided_by_code_from_what_the_code_does():
    _, files = defn_and_files()
    assert files["server.py"].count("ToolAnnotations(read_only_hint=True, open_world_hint=False)") == 2
    net = draft(tools=[with_tool(body=["import urllib.request", "return urllib.request.urlopen(text).read().decode()"])], permissions=["network"])
    _, net_files = defn_and_files(net)
    assert "ToolAnnotations(read_only_hint=True, open_world_hint=True)" in net_files["server.py"]


def test_awkward_text_cannot_break_out_of_the_file():
    nasty = draft(description='Says """hello""" with a \\ backslash', tools=[with_tool(description='Does "x" and """y""" \\ z')])
    _, files = defn_and_files(nasty)
    ast.parse(files["server.py"])
    assert analyze_server(files["server.py"]).tools[0].described


def test_a_name_with_no_letters_falls_back_to_the_goal_not_to_skill():
    defn = assemble_mcp(draft(name="!!!"), spec(), MockProvider([]), NOW)
    assert defn.name.startswith("count-the-words") and defn.provenance.name_adjusted


def test_the_cases_file_has_real_json_arguments():
    _, files = defn_and_files()
    cases = json.loads(files["tests/cases.json"])
    assert cases[0] == {"name": "three words", "kind": "positive", "tool": "count_words", "arguments": {"text": "one two three"}, "expect": "contains", "expected_text": "3", "covers": ["AC1"]}
    assert cases[1]["expect"] == "error"


def test_the_readme_has_the_exact_command_the_persons_words_and_the_limits():
    _, files = defn_and_files(draft(env_vars=["WEATHER_API_KEY"], permissions=["network"], tools=[with_tool(body=["import os", 'key = os.environ.get("WEATHER_API_KEY", "")', "return key"])]))
    readme = files["README.md"]
    assert 'claude mcp add word-tools -e WEATHER_API_KEY=<your value> -- python "<full path to>\\server.py"' in readme
    assert "only work on the text it is given" in readme and "raise an error when the text is empty" in readme
    assert "a text of three words gives 3" in readme and "Words are separated by white space only." in readme
    assert "never write a key into server.py" in readme.lower() and "pip install -r requirements.txt" in readme
    assert "network" in readme.lower().split("what it can do on your machine")[1].split("##")[0]


# ---- the checks ----------------------------------------------------------------------------------------


def test_a_good_design_passes_every_check():
    got = results(draft())
    assert {s for s, _ in got.values()} == {PASSED}, [(n, d) for n, (s, d) in got.items() if s != PASSED]


def test_undeclared_network_is_a_failure_and_declared_network_passes():
    net = [with_tool(body=["import urllib.request", "return urllib.request.urlopen(text).read().decode()"])]
    assert any("permission" in n for n in failed(draft(tools=net)))
    assert not failed(draft(tools=net, permissions=["network"], cases=extra_cases()))
    assert any("permission" in n for n in warned(draft(permissions=["network"])))  # declared but not used


def test_what_the_builder_does_not_offer_fails_even_when_declared():
    assert any("permission" in n for n in failed(draft(permissions=["write_files"])))
    assert any("permission" in n for n in failed(draft(permissions=["run_commands"])))
    writing = [with_tool(body=['open("o.txt", "w").write(text)', "return text"])]
    assert failed(draft(tools=writing, permissions=["read_files"]))


def test_a_package_outside_the_standard_library_fails_in_the_builder():
    bad = [with_tool(body=["import requests", "return requests.get(text).text"])]
    assert any("imported" in n for n in failed(draft(tools=bad)))


def test_secrets_are_names_only():
    use = [with_tool(body=["import os", 'return os.environ.get("API_TOKEN", "")'])]
    assert any("environment" in n for n in failed(draft(tools=use)))  # read but not declared
    assert not failed(draft(tools=use, env_vars=["API_TOKEN"], cases=extra_cases()))
    assert any("environment" in n for n in failed(draft(env_vars=["api token=abc"])))  # a name, never a value
    computed = [with_tool(body=["import os", "return os.environ.get(text, '')"])]
    assert any("environment" in n for n in failed(draft(tools=computed, env_vars=["API_TOKEN"])))
    assert any("environment" in n for n in warned(draft(env_vars=["API_TOKEN"])))  # declared but never read


def test_a_key_in_the_persons_words_or_the_code_fails_and_is_never_repeated():
    key = "sk-" + "a1" * 12
    leaky = [with_tool(body=[f'return "{key}"'])]
    got = results(draft(tools=leaky))
    assert any(s == FAILED and "key" in n for n, (s, _) in got.items())
    assert all(key not in detail for _, detail in got.values())
    risky_spec = spec().model_copy(update={"constraints": [f"use the key {key}"]})
    defn = assemble_mcp(draft(), risky_spec, MockProvider([]), NOW)
    checks = check_mcp(defn, risky_spec, render_mcp_files(defn, risky_spec))
    assert any(c.status == FAILED and "key" in c.name for c in checks) and all(key not in c.detail for c in checks)


def test_tool_and_parameter_names_must_be_valid_and_unique():
    assert any("names" in n for n in failed(draft(tools=[with_tool(name="Bad Name")])))
    assert any("names" in n for n in failed(draft(tools=[with_tool(), with_tool()])))
    assert any("names" in n for n in failed(draft(tools=[with_tool(params=[McpParam(name="class", type="str", description="x")])])))
    assert any("names" in n for n in failed(draft(tools=[with_tool(params=[McpParam(name="a", type="str", description="x"), McpParam(name="a", type="int", description="y")])])))
    assert any("tools" in n for n in failed(draft(tools=[])))


def test_every_tool_must_return_text():
    assert any("return" in n for n in failed(draft(tools=[with_tool(body=["x = 1"])])))
    assert any("parses" in n or "syntax" in n.lower() for n in failed(draft(tools=[with_tool(body=["return ("])])))


def test_cases_are_checked_against_the_design():
    bad_tool = draft(cases=[McpCase(name="x", kind="positive", tool="nope", arguments_json="{}", expect="equals", expected_text="1", covers=["AC1", "AC2"])])
    assert any("cases" in n for n in failed(bad_tool))
    wrong_keys = draft(cases=[McpCase(name="x", kind="positive", tool="shout", arguments_json='{"wrong": "x"}', expect="equals", expected_text="X", covers=["AC1", "AC2"]),
                              McpCase(name="n", kind="negative", tool="shout", arguments_json='{"text": ""}', expect="error", expected_text="", covers=[])])
    assert any("arguments" in n for n in failed(wrong_keys))
    not_json = draft(cases=[McpCase(name="x", kind="positive", tool="shout", arguments_json="{oops", expect="equals", expected_text="X", covers=["AC1", "AC2"])])
    assert any("arguments" in n for n in failed(not_json))
    wrong_type = draft(cases=[McpCase(name="x", kind="positive", tool="shout", arguments_json='{"text": 5}', expect="equals", expected_text="X", covers=["AC1", "AC2"])])
    assert any("arguments" in n for n in failed(wrong_type))


def test_every_acceptance_criterion_needs_a_case_and_there_must_be_a_negative_case():
    only_ac1 = draft(cases=[draft().cases[0], draft().cases[2]])
    names = failed(only_ac1)
    assert any("criterion" in n for n in names) and any("negative" in n for n in names)
    assert any("real acceptance criterion" in n for n in warned(draft(cases=[*draft().cases, McpCase(name="z", kind="edge", tool="shout", arguments_json='{"text": "a"}', expect="equals", expected_text="A", covers=["AC9"])])))


def test_the_persons_words_must_reach_the_files():
    defn, files = defn_and_files()
    files["README.md"] = files["README.md"].replace("only work on the text it is given", "")
    assert any(c.status == FAILED and "word for word" in c.name for c in check_mcp(defn, spec(), files))


def test_vague_wording_in_a_tool_description_is_a_warning():
    assert any("vague" in n for n in warned(draft(tools=[with_tool(description="Handles the text as needed, etc.")])))


# ---- the build -----------------------------------------------------------------------------------------


def test_a_clean_design_costs_one_model_call_and_writes_the_files(tmp_path):
    mock = MockProvider([draft()])
    result = build_mcp_from_spec(spec(), mock, out_root=tmp_path, now=NOW)
    assert len(mock.calls) == 1 and result.model_calls == 1
    assert (tmp_path / "word-tools" / "server.py").is_file() and (tmp_path / "word-tools" / "report.md").is_file()
    assert result.files == sorted(result.files) and "report.md" in result.files
    assert not [c for c in result.checks if c.status == FAILED]


def test_a_failed_check_makes_one_repair_and_a_better_design_is_kept(tmp_path):
    bad = draft(tools=[with_tool(body=["import requests", "return requests.get(text).text"])])
    mock = MockProvider([bad, draft()])
    result = build_mcp_from_spec(spec(), mock, out_root=tmp_path, now=NOW)
    assert len(mock.calls) == 2 and "Your previous design did not pass" in mock.calls[1]["prompt"]
    assert result.status == "ok" or all(c.status != FAILED for c in result.checks if c.status != NOT_RUN)
    assert any("fix them once" in n for n in result.notes)


def test_a_worse_repair_is_discarded(tmp_path):
    one_failure = draft(tools=[with_tool(body=["import requests", "return requests.get(text).text"])])
    worse = draft(tools=[with_tool(body=["import requests", "return requests.get(text).text"]), with_tool(name="other", body=["x = 1"])])
    result = build_mcp_from_spec(spec(), MockProvider([one_failure, worse]), out_root=tmp_path, now=NOW)
    assert "second design was worse" in " ".join(result.notes) and result.status == "draft"


def test_the_protocol_run_is_reported_as_not_run_until_it_happens(tmp_path):
    result = build_mcp_from_spec(spec(), MockProvider([draft()]), out_root=tmp_path, now=NOW)
    assert any(c.status == NOT_RUN and "MCP protocol" in c.name for c in result.checks)
    assert result.status == "draft" and "never" in result.draft_reason.lower()


def test_an_existing_folder_is_not_overwritten_unless_forced(tmp_path):
    build_mcp_from_spec(spec(), MockProvider([draft()]), out_root=tmp_path, now=NOW)
    with pytest.raises(BuildError, match="already exists"):
        build_mcp_from_spec(spec(), MockProvider([draft()]), out_root=tmp_path, now=NOW)
    build_mcp_from_spec(spec(), MockProvider([draft()]), out_root=tmp_path, now=NOW, force=True)


# ---- what a real model got wrong the first time it was tried: code that uses a module it never imports ---------


def test_a_tool_that_uses_a_module_it_never_imports_fails_in_the_builder():
    missing = [with_tool(body=['return os.environ.get("API_TOKEN", "")'])]
    got = failed(draft(tools=missing, env_vars=["API_TOKEN"], cases=extra_cases()))
    assert any("defined" in n for n in got)
    fixed = [with_tool(body=["import os", 'return os.environ.get("API_TOKEN", "")'])]
    assert not failed(draft(tools=fixed, env_vars=["API_TOKEN"], cases=extra_cases()))


def test_missing_imports_make_network_use_invisible_so_the_check_must_not_depend_on_them():
    # without the import the code reader cannot see the network; the undefined name is what must stop the build
    hidden = [with_tool(body=['return urllib.request.urlopen(text).read().decode()'])]
    assert any("defined" in n for n in failed(draft(tools=hidden, permissions=["network"], cases=extra_cases())))


def test_the_design_prompt_tells_the_model_to_write_its_own_imports():
    text = MCP_DESIGN_SYSTEM.lower()
    assert "nothing is imported for you" in text and "import os" in text and "first lines of the body" in text


# ---- the second thing a real model got wrong: a tool that pretends --------------------------------------------


def test_an_import_that_is_never_used_fails_because_it_means_the_tool_was_stubbed():
    stub = [with_tool(body=["import urllib.request", "import os", 'key = os.environ.get("API_TOKEN", "")', 'return "simple"'])]
    got = failed(draft(tools=stub, permissions=["network"], env_vars=["API_TOKEN"], cases=extra_cases()))
    assert any("import" in n and "used" in n for n in got)
    used = [with_tool(body=["import os", 'return os.environ.get("API_TOKEN", "")'])]
    assert not any("import" in n and "used" in n for n in failed(draft(tools=used, env_vars=["API_TOKEN"], cases=extra_cases())))


@pytest.mark.parametrize("word", ["simulated", "placeholder", "dummy data", "fake", "mock", "hard-coded", "stub"])
def test_a_tool_that_returns_made_up_data_fails(word):
    pretend = [with_tool(body=[f'return "The answer is 20 ({word})"'])]
    assert any("made-up" in n for n in failed(draft(tools=pretend, cases=extra_cases())))


def test_honest_wording_is_not_mistaken_for_made_up_data():
    fine = [with_tool(body=["# count the words and return the number", 'return str(len(text.split())) + " words"'])]
    assert not any("made-up" in n for n in failed(draft(tools=fine, cases=extra_cases())))


def test_the_design_prompt_forbids_inventing_data():
    text = MCP_DESIGN_SYSTEM.lower()
    assert "never invent" in text and "simulate" in text and "raise" in text and "not run" in text


# ---- annotations are decided per tool ----------------------------------------------------------------------


def decorator_of(source: str, tool: str) -> str:
    return source[: source.index(f"def {tool}(")].splitlines()[-1]


def test_a_tool_is_marked_open_world_only_when_its_own_code_reaches_the_network():
    net = with_tool(name="fetch", body=["import urllib.request", "return urllib.request.urlopen(text).read().decode()"])
    d = draft(tools=[draft().tools[0], net], permissions=["network"], cases=[draft().cases[0], draft().cases[1].model_copy(update={"tool": "count_words"})])
    _, files = defn_and_files(d)
    assert "open_world_hint=False" in decorator_of(files["server.py"], "count_words")
    assert "open_world_hint=True" in decorator_of(files["server.py"], "fetch")
    assert "read_only_hint=True" in decorator_of(files["server.py"], "fetch")  # it reads from the network, it does not write
