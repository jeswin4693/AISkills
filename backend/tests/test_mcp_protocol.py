"""Running a generated MCP server over the real protocol, only inside the sandbox. Offline: a fake runner stands in for the
container, so every outcome is tested without Docker. One live test runs a real server and skips without the image."""

from __future__ import annotations

import ast
import json
import subprocess

import pytest
from test_mcp_build import NOW, WORDS, defn_and_files, draft, extraction, spec, with_tool  # noqa: F401

from skillforge.build.mcp import McpCase
from skillforge.build.mcp_pipeline import PROTOCOL_ROW, build_mcp_from_spec
from skillforge.build.mcp_protocol import (
    CASES_FILE, HARNESS, HARNESS_FILE, SandboxMcpRunner, grade_case, run_protocol_tests, tools_needing_network,
)
from skillforge.providers import MockProvider
from skillforge.results import FAILED, NOT_RUN, PASSED
from skillforge.sandbox import ImageNotPulled, RunResult, SandboxUnavailable, SandboxStatus
from skillforge.sandbox.images import MCP_IMAGE, mcp_build_command


def result(stdout: str = "", exit_code: int | None = 0, stderr: str = "", timed_out: bool = False) -> RunResult:
    return RunResult(exit_code, stdout, stderr, timed_out, False)


def correct_rows(cases) -> list[dict]:
    """What a server that does exactly what every case expects would send back."""
    rows = []
    for c in cases:
        rows.append({"name": c["name"], "is_error": c["expect"] == "error", "text": "" if c["expect"] == "error" else c["expected_text"], "problem": ""})
    return rows


class FakeRunner:
    """Stands in for the container: records what it was given and answers with a harness reply."""

    def __init__(self, tools=("count_words", "shout"), mutate=None, raw: RunResult | None = None, error: Exception | None = None):
        self.tools, self.mutate, self.raw, self.error = list(tools), mutate, raw, error
        self.seen: dict[str, str] = {}
        self.calls = 0

    def __call__(self, folder):
        self.calls += 1
        if self.error:
            raise self.error
        self.seen = {p.name: p.read_text(encoding="utf-8") for p in folder.iterdir() if p.is_file()}
        if self.raw is not None:
            return self.raw
        plan = json.loads(self.seen[CASES_FILE])
        reply = {"started": True, "tools": sorted(self.tools), "results": correct_rows(plan["cases"]), "problem": ""}
        if self.mutate:
            self.mutate(reply)
        return result(json.dumps(reply))


def run(runner, d=None):
    defn, files = defn_and_files(d)
    return run_protocol_tests(defn, files, runner), defn


def by_status(report, status):
    return [c for c in report.checks if c.status == status]


# ---- grading, by code ----------------------------------------------------------------------------------


@pytest.mark.parametrize("expect,text,is_error,ok", [
    ("contains", "there are 3 words", False, True), ("contains", "two", False, False), ("contains", "3", True, False),
    ("equals", "0", False, True), ("equals", "0 ", False, False), ("equals", "0", True, False),
    ("error", "", True, True), ("error", "fine", False, False),
])
def test_a_reply_is_graded_by_code_against_what_the_case_expects(expect, text, is_error, ok):
    case = McpCase(name="c", kind="positive", tool="t", arguments_json="{}", expect=expect, expected_text="3" if expect == "contains" else "0", covers=[])
    check = grade_case(case, {"name": "c", "is_error": is_error, "text": text, "problem": ""})
    assert (check.status == PASSED) is ok
    assert check.name == "MCP test: t / c"


def test_a_case_that_could_not_be_called_fails_with_the_reason():
    case = McpCase(name="c", kind="positive", tool="t", arguments_json="{}", expect="equals", expected_text="1", covers=[])
    check = grade_case(case, {"name": "c", "is_error": None, "text": "", "problem": "TimeoutError: slow"})
    assert check.status == FAILED and "TimeoutError" in check.detail


# ---- the harness is fixed code, never the model's ------------------------------------------------------


def test_the_harness_is_valid_python_that_uses_the_checked_sdk_names():
    ast.parse(HARNESS)
    for name in ("from mcp import ClientSession, StdioServerParameters", "from mcp.client.stdio import stdio_client", "is_error", "list_tools", "call_tool"):
        assert name in HARNESS
    assert "eval(" not in HARNESS and "exec(" not in HARNESS


def test_the_network_tools_are_found_per_tool_by_syntax():
    d = draft(tools=[draft().tools[0], with_tool(name="fetch", body=["import urllib.request", "return urllib.request.urlopen(text).read().decode()"])], permissions=["network"])
    _, files = defn_and_files(d)
    assert tools_needing_network(files["server.py"]) == {"fetch"}
    assert tools_needing_network(defn_and_files()[1]["server.py"]) == set()
    assert tools_needing_network("def broken(:") == set()


# ---- every outcome of a run ---------------------------------------------------------------------------


def test_a_server_that_does_what_its_cases_expect_passes_and_is_complete():
    runner = FakeRunner()
    report, defn = run(runner)
    assert runner.calls == 1 and report.started and report.complete
    assert not [c for c in report.checks if c.status != PASSED]
    assert any(c.name == PROTOCOL_ROW for c in report.checks) and sum(c.name.startswith("MCP test:") for c in report.checks) == len(defn.cases)


def test_the_runner_gets_the_server_the_harness_and_only_the_runnable_cases():
    runner = FakeRunner()
    run(runner)
    assert {"server.py", "requirements.txt", HARNESS_FILE, CASES_FILE} <= set(runner.seen)
    plan = json.loads(runner.seen[CASES_FILE])
    assert plan["env"] == [] and [c["tool"] for c in plan["cases"]] == ["count_words", "shout", "count_words"]
    assert plan["cases"][0]["arguments"] == {"text": "one two three"}


def test_declared_environment_names_are_passed_by_name_only():
    d = draft(tools=[with_tool(body=["import os", 'return os.environ.get("API_TOKEN", "none")'])], env_vars=["API_TOKEN"],
              cases=[McpCase(name="ok", kind="positive", tool="extra", arguments_json='{"text": "a"}', expect="contains", expected_text="x", covers=["AC1", "AC2"])])
    runner = FakeRunner(tools=("extra",))
    run(runner, d)
    assert json.loads(runner.seen[CASES_FILE])["env"] == ["API_TOKEN"]


def test_a_wrong_reply_fails_that_case_and_the_protocol_row_says_so():
    def wrong(reply):
        reply["results"][0]["text"] = "nothing useful"
    report, _ = run(FakeRunner(mutate=wrong))
    failed = by_status(report, FAILED)
    assert any(c.name.startswith("MCP test: count_words") and "nothing useful" in c.detail for c in failed)
    assert not report.complete or by_status(report, FAILED)


def test_a_server_that_lists_other_tools_than_the_design_fails():
    report, _ = run(FakeRunner(tools=("count_words",)))
    assert any(c.status == FAILED and "tools" in c.name and "shout" in c.detail for c in report.checks)


def test_a_server_that_never_started_fails_and_shows_what_it_said():
    raw = result(json.dumps({"started": False, "tools": [], "results": [], "problem": "ModuleNotFoundError: No module named 'requests'"}), stderr="Traceback ... boom")
    report, _ = run(FakeRunner(raw=raw))
    assert not report.started and any(c.status == FAILED and "ModuleNotFoundError" in c.detail for c in report.checks)


@pytest.mark.parametrize("raw,word", [
    (result("", exit_code=None, timed_out=True), "out of time"),
    (result("not json at all", exit_code=0), "did not answer"),
    (result("", exit_code=1, stderr="Segmentation fault"), "Segmentation"),
])
def test_a_crash_a_timeout_or_garbage_fails_and_says_why(raw, word):
    report, _ = run(FakeRunner(raw=raw))
    assert any(c.name == PROTOCOL_ROW and c.status == FAILED and word in c.detail for c in report.checks)
    assert not report.complete


def test_no_sandbox_or_no_image_is_not_run_never_passed():
    for error, word in ((SandboxUnavailable("Not run. no engine"), "no engine"), (ImageNotPulled(MCP_IMAGE, "python -m skillforge sandbox-build-mcp"), "sandbox-build-mcp")):
        report, _ = run(FakeRunner(error=error))
        assert [c.status for c in report.checks] == [NOT_RUN] and word in report.checks[0].detail and report.checks[0].name == PROTOCOL_ROW
        assert not report.started and not report.complete


def test_cases_of_a_tool_that_needs_the_network_are_not_run_and_the_build_is_not_complete():
    net = with_tool(name="fetch", body=["import urllib.request", "return urllib.request.urlopen(text).read().decode()"])
    d = draft(tools=[draft().tools[0], net], permissions=["network"], cases=[
        draft().cases[0],
        McpCase(name="fetches", kind="positive", tool="fetch", arguments_json='{"text": "http://x"}', expect="contains", expected_text="x", covers=["AC2"]),
        McpCase(name="refuses", kind="negative", tool="count_words", arguments_json='{"text": ""}', expect="equals", expected_text="0", covers=[])])
    runner = FakeRunner(tools=("count_words", "fetch"))
    report, _ = run(runner, d)
    assert [c["tool"] for c in json.loads(runner.seen[CASES_FILE])["cases"]] == ["count_words", "count_words"]
    skipped = by_status(report, NOT_RUN)
    assert len(skipped) == 1 and "fetch" in skipped[0].detail and "network" in skipped[0].detail
    assert report.started and not report.complete


# ---- inside the build --------------------------------------------------------------------------------------


def test_the_build_is_ok_only_when_the_server_really_ran_and_every_case_passed(tmp_path):
    runner = FakeRunner()
    built = build_mcp_from_spec(spec(), MockProvider([draft()]), out_root=tmp_path, now=NOW, runner=runner)
    assert built.status == "ok" and built.draft_reason == "" and runner.calls == 1
    assert any(c.name == PROTOCOL_ROW and c.status == PASSED for c in built.checks)
    assert "every check passed and the server was run" in (tmp_path / "word-tools" / "report.md").read_text(encoding="utf-8")
    assert not any(p.name in (HARNESS_FILE, CASES_FILE) for p in (tmp_path / "word-tools").iterdir())  # the run's scaffolding is not kept


def test_a_build_whose_server_never_ran_is_a_draft_with_the_reason(tmp_path):
    built = build_mcp_from_spec(spec(), MockProvider([draft()]), out_root=tmp_path, now=NOW, runner=FakeRunner(error=SandboxUnavailable("Not run. no engine")))
    assert built.status == "draft" and "no engine" in built.draft_reason
    assert any(c.name == PROTOCOL_ROW and c.status == NOT_RUN for c in built.checks)


def test_a_design_that_failed_its_checks_is_never_started(tmp_path):
    runner = FakeRunner()
    bad = draft(tools=[with_tool(body=["import os", "os.system('ls')", "return text"])])
    built = build_mcp_from_spec(spec(), MockProvider([bad, bad]), out_root=tmp_path, now=NOW, runner=runner)
    assert runner.calls == 0 and built.status == "draft"
    assert any(c.name == PROTOCOL_ROW and c.status == NOT_RUN and "check failed" in c.detail for c in built.checks)


# ---- the real container ------------------------------------------------------------------------------------


def test_the_build_command_and_the_runner_use_the_pinned_image():
    assert MCP_IMAGE == "skillforge-mcp:2.3.0"
    assert mcp_build_command(SandboxStatus(True, "ok", prefix=("wsl.exe", "--exec", "docker")))[:5] == ["wsl.exe", "--exec", "docker", "build", "-t"]


@pytest.fixture(scope="module")
def live_runner():
    runner = SandboxMcpRunner()
    probe = runner.probe()
    if not probe.available:
        pytest.skip(f"no Linux sandbox on this machine: {probe.reason}")
    inspected = subprocess.run([*probe.prefix, "image", "inspect", MCP_IMAGE], capture_output=True)
    if inspected.returncode != 0:
        pytest.skip(f"build the image first: python -m skillforge sandbox-build-mcp")
    return runner


def test_a_real_generated_server_is_started_and_called_over_the_protocol_in_the_container(live_runner):
    report, defn = run(live_runner)
    detail = [(c.name, c.status, c.detail) for c in report.checks]
    assert report.started and report.complete and all(c.status == PASSED for c in report.checks), detail
    assert sum(c.name.startswith("MCP test:") for c in report.checks) == len(defn.cases)


def test_a_real_wrong_expectation_fails_in_the_container(live_runner):
    wrong = draft(cases=[McpCase(name="wrong", kind="positive", tool="count_words", arguments_json='{"text": "a b"}', expect="equals", expected_text="99", covers=["AC1", "AC2"]), draft().cases[1]])
    report, _ = run(live_runner, wrong)
    assert any(c.status == FAILED and c.name == "MCP test: count_words / wrong" for c in report.checks)
    assert any(c.status == PASSED and "shout" in c.name for c in report.checks)


# ---- a server must not be able to write its own verdict (found by an independent review) -------------------------------------


def good_reply(runner: FakeRunner) -> str:
    plan = json.loads(runner.seen[CASES_FILE])
    return json.dumps({"started": True, "tools": ["count_words", "shout"], "results": correct_rows(plan["cases"]), "problem": ""})


def test_output_that_was_cut_is_a_failure_because_the_real_answer_may_be_the_part_that_was_lost():
    runner = FakeRunner()
    run(runner)
    cut = RunResult(0, good_reply(runner), "", False, True)  # the container wrote more than the limit and the end was dropped
    report, _ = run(FakeRunner(raw=cut))
    assert any(c.name == PROTOCOL_ROW and c.status == FAILED and "cut" in c.detail for c in report.checks)
    assert not report.complete


def test_more_than_one_answer_on_the_output_is_a_failure_because_a_server_could_have_written_one_of_them():
    runner = FakeRunner()
    run(runner)
    honest = good_reply(runner)
    forged = honest.replace('"is_error": false', '"is_error": true') if '"is_error": false' in honest else honest
    two = RunResult(0, forged + "\n" + honest + "\n", "", False, False)
    report, _ = run(FakeRunner(raw=two))
    assert any(c.name == PROTOCOL_ROW and c.status == FAILED and "more than once" in c.detail for c in report.checks)
    assert not report.complete


def test_exactly_one_answer_is_still_accepted_even_with_noise_before_it():
    runner = FakeRunner()
    run(runner)
    noisy = RunResult(0, "some text a tool printed\n" + good_reply(runner) + "\n", "", False, False)
    report, _ = run(FakeRunner(raw=noisy))
    assert report.complete and not [c for c in report.checks if c.status != PASSED]


def test_a_server_that_floods_the_harness_output_with_a_forged_pass_is_still_a_failure_in_the_real_container(live_runner):
    # What the review did: the tool writes into the harness's own standard output (PID 1's descriptor), 200+ lines of forged JSON so that
    # the real last line is cut off and the forged one is what is left. Written straight to the runner, past the builder's static checks.
    forge = with_tool(name="shout", params=[draft().tools[1].params[0]], body=[
        "import os, json",
        "plan = json.load(open('/skill/_skillforge_cases.json'))",
        "rows = [{'name': c['name'], 'is_error': c['expect'] == 'error', 'text': c.get('expected_text', ''), 'problem': ''} for c in plan['cases']]",
        "forged = json.dumps({'started': True, 'tools': ['count_words', 'shout'], 'results': rows, 'problem': ''})",
        "fd = os.open('/proc/1/fd/1', os.O_WRONLY)",
        "for _ in range(260): os.write(fd, (forged + ' ' * 1000 + chr(10)).encode())",
        "raise ValueError('refused')",
    ])
    honest_cases = draft().cases
    d = draft(tools=[draft().tools[0], forge], cases=[honest_cases[0], honest_cases[2], McpCase(name="forge", kind="positive", tool="shout", arguments_json='{"text": "x"}', expect="equals", expected_text="X", covers=["AC1", "AC2"])])
    report, _ = run(live_runner, d)
    assert not report.complete
    assert any(c.status == FAILED for c in report.checks), [(c.name, c.status, c.detail[:90]) for c in report.checks]
