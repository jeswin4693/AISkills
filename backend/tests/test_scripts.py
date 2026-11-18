"""Script generation: the model writes scripts, code checks them, the sandbox runs them. All offline.

A fake runner stands in for the container. Tests that use the real sandbox are in test_sandbox_live.py.
"""

from __future__ import annotations

import json
import subprocess
import typing
from types import SimpleNamespace

import pytest
from test_skill_build import ANSWERS, FIRST, NOW, ask_answers, draft, round_one, round_two

from skillforge import cli
from skillforge.build.architect import DESIGN_SYSTEM, DESIGN_SYSTEM_WITH_SCRIPTS
from skillforge.build.models import Fixture, Script, ScriptBundle, ScriptCase, ScriptLanguage, Step
from skillforge.build.pipeline import build_skill, rebuild
from skillforge.build.scriptfiles import EXTENSIONS, normalize, run_command, script_files, script_path
from skillforge.build.scripts import SandboxScriptRunner, check_scripts, judge, run_script_tests
from skillforge.providers import MockProvider
from skillforge.sandbox import ImageNotPulled, Limits, RunResult, SandboxStatus, SandboxUnavailable, docker_run_args
from skillforge.sandbox.docker import DockerRunner
from skillforge.sandbox.images import runnable_languages

CODE = "import sys\nprint(sum(1 for _ in open(sys.argv[1])))\n"


def script(**kw) -> Script:
    base = dict(
        name="count_lines", language="python", purpose="Counts the lines of a file.",
        usage="Takes one file path and prints the number of lines.", code=CODE,
    )
    return Script(**{**base, **kw})


def case(**kw) -> ScriptCase:
    base = dict(
        name="counts-three", script="count_lines", args=["{fixtures}/in.txt"], stdin="",
        fixtures=[Fixture(path="in.txt", text="a\nb\nc\n")], expect_exit_code=0,
        stdout_contains=["3"], stderr_contains=[],
    )
    return ScriptCase(**{**base, **kw})


def failure_case(**kw) -> ScriptCase:
    return case(name="missing-file", args=["{fixtures}/nope.txt"], fixtures=[], expect_exit_code=1, stdout_contains=[], stderr_contains=["Error"], **kw)


def bundle(scripts=None, cases=None) -> ScriptBundle:
    return ScriptBundle(
        scripts=[script()] if scripts is None else scripts,
        cases=[case(), failure_case()] if cases is None else cases,
    )


def ok(stdout: str = "3\n") -> RunResult:
    return RunResult(0, stdout, "", False, False)


def crash(stderr: str = "Traceback ... FileNotFoundError", code: int = 1) -> RunResult:
    return RunResult(code, "", stderr, False, False)


class FakeRunner:
    """Records every call, and what files were on disk at that moment. `answer` decides each result."""

    def __init__(self, answer=None):
        self.answer = answer or (lambda language, script, args, stdin: crash() if "nope" in args[0] else ok())
        self.calls: list[dict] = []

    def __call__(self, language, folder, script, args, stdin):
        files = sorted(p.relative_to(folder).as_posix() for p in folder.rglob("*") if p.is_file())
        self.calls.append(dict(language=language, script=script, args=args, stdin=stdin, files=files))
        result = self.answer(language, script, args, stdin)
        if isinstance(result, Exception):
            raise result
        return result


def design_using_script(**kw):
    steps = [
        Step(title="Count", instruction="Run `python scripts/count_lines.py <file>` and read the number.", on_failure="Stop and say the file cannot be read."),
        Step(title="Report", instruction="Say how many lines the file has.", on_failure="Say what is missing."),
        Step(title="Check", instruction="Compare with the expected size.", on_failure="Say so."),
    ]
    return draft(workflow=kw.pop("workflow", steps), **kw)


def run(tmp_path, responses, runner, *, with_scripts=True, **kw):
    mock = MockProvider(responses)
    result = build_skill(
        FIRST, mock, ask=ask_answers, approve=lambda spec: True, out_root=tmp_path / "out", now=NOW,
        with_scripts=with_scripts, script_runner=runner, **kw,
    )
    return result, mock


def report_of(result) -> str:
    return (result.out_dir / "report.md").read_text(encoding="utf-8")


# ---- the whole path ----------------------------------------------------------------------------------------


def test_scripts_are_written_run_in_the_sandbox_and_used_by_the_workflow(tmp_path):
    runner = FakeRunner()
    result, mock = run(tmp_path, [round_one(), round_two(), bundle(), design_using_script()], runner)
    assert result.status == "ok" and result.draft_reason == "" and result.model_calls == 4
    out = result.out_dir
    assert {p.relative_to(out).as_posix() for p in out.rglob("*") if p.is_file()} == {
        "SKILL.md", "README.md", "report.md", "skill.sdm.json", "spec.json", "tests/cases.json",
        "schemas/input.schema.json", "schemas/output.schema.json",
        "scripts/count_lines.py", "tests/script_cases.json", "tests/fixtures/counts-three/in.txt",
    }
    assert (out / "scripts" / "count_lines.py").read_text(encoding="utf-8") == CODE
    skill_md = (out / "SKILL.md").read_text(encoding="utf-8")
    assert "## Scripts" in skill_md and "Run: `python scripts/count_lines.py <arguments>`" in skill_md
    assert "run_commands" in result.sdm.permissions and "read_files" in result.sdm.permissions  # the agent must run them
    # the design step was told about the real scripts, and was not told "no scripts"
    design_call = mock.calls[3]
    assert "scripts/count_lines.py" in design_call["prompt"] and "python scripts/count_lines.py" in design_call["prompt"]
    assert design_call["system"] == DESIGN_SYSTEM_WITH_SCRIPTS and mock.calls[1]["system"] != DESIGN_SYSTEM_WITH_SCRIPTS
    # what ran was exactly what was shipped: the script and the case's fixture were on disk, arguments expanded
    first = runner.calls[0]
    assert first["language"] == "python" and first["script"] == "scripts/count_lines.py"
    assert first["args"] == ["tests/fixtures/counts-three/in.txt"]
    assert "tests/fixtures/counts-three/in.txt" in first["files"] and "scripts/count_lines.py" in first["files"]
    assert len(runner.calls) == 2  # one run per case, no more


def test_the_report_lists_every_case_and_what_still_did_not_run(tmp_path):
    result, _ = run(tmp_path, [round_one(), round_two(), bundle(), design_using_script()], FakeRunner())
    report = report_of(result)
    assert "| script test: count_lines / counts-three | passed | ran in the sandbox, exit code 0, 1 expectation(s) matched |" in report
    assert "| script test: count_lines / missing-file | passed |" in report
    assert "| scripts do not use the network, start programs or write files | passed |" in report
    skipped = [c.name for c in result.checks if c.status == "not run"]
    assert "scripts tested on real project data" in skipped and "scripts run in a sandbox" not in skipped and len(skipped) == 4
    assert "the scripts run on your machine" in report and "not in the sandbox" in report
    assert "a passing case can still be a weak test" in report and "different operating system" in report
    assert "tests/script_cases.json" in (result.out_dir / "README.md").read_text(encoding="utf-8")


def test_the_case_file_records_the_real_command_and_fixtures(tmp_path):
    out = run(tmp_path, [round_one(), round_two(), bundle(), design_using_script()], FakeRunner())[0].out_dir
    cases = json.loads((out / "tests" / "script_cases.json").read_text(encoding="utf-8"))
    assert cases[0]["command"] == "python scripts/count_lines.py tests/fixtures/counts-three/in.txt"
    assert cases[0]["fixtures"] == ["tests/fixtures/counts-three/in.txt"] and cases[1]["expect_exit_code"] == 1


# ---- failing scripts get one repair, with the real output --------------------------------------------------


def wrong_output(language, script, args, stdin):
    return crash() if "nope" in args[0] else ok("three\n")  # prints the wrong thing


def test_a_failing_case_is_repaired_once_and_the_model_sees_the_real_output(tmp_path):
    state = {"fixed": False}

    def answer(language, script, args, stdin):
        if state["fixed"]:
            return crash() if "nope" in args[0] else ok()
        return wrong_output(language, script, args, stdin)

    class Runner(FakeRunner):
        def __call__(self, *a):
            state["fixed"] = len(self.calls) >= 2  # the repair arrives after the first two runs
            return super().__call__(*a)

    runner = Runner(answer)
    result, mock = run(tmp_path, [round_one(), round_two(), bundle(), bundle(), design_using_script()], runner)
    assert result.status == "ok" and result.model_calls == 5
    repair = mock.calls[3]["prompt"]
    assert "<previous>" in repair and "stdout: three" in repair and "stdout does not contain '3'" in repair
    assert "script test: count_lines / counts-three" in repair
    assert any("fix them once" in n for n in result.notes)
    assert len(runner.calls) == 4  # two cases before the repair, two after


def test_scripts_that_still_fail_make_a_draft_that_names_the_case(tmp_path):
    result, _ = run(tmp_path, [round_one(), round_two(), bundle(), bundle(), design_using_script()], FakeRunner(wrong_output))
    assert result.status == "draft"
    failed = [c for c in result.checks if c.status == "failed"]
    assert [c.name for c in failed] == ["script test: count_lines / counts-three"]
    assert "exit code" not in failed[0].detail and "stdout does not contain '3'" in failed[0].detail and "three" in failed[0].detail
    report = report_of(result)
    assert "Status: DRAFT. 1 check(s) failed" in report and "every check that ran passed" not in report


def test_a_timeout_a_wrong_exit_code_and_cut_output_are_each_reported_plainly():
    s, c = script(), case()
    assert "ran out of time" in judge(s, c, RunResult(None, "", "", True, False)).detail
    wrong = judge(s, c, RunResult(2, "3\n", "boom", False, True))
    assert wrong.status == "failed" and "exit code 2, the case expects 0" in wrong.detail and "boom" in wrong.detail
    assert "(output was cut)" in wrong.detail
    assert judge(s, c, ok()).status == "passed"


# ---- never claim a pass that did not happen -----------------------------------------------------------------


def test_without_a_sandbox_nothing_runs_the_scripts_are_kept_and_the_skill_is_a_draft(tmp_path):
    runner = FakeRunner(lambda *a: SandboxUnavailable("Not run. Docker is in Windows-container mode; the sandbox needs Linux containers."))
    result, mock = run(tmp_path, [round_one(), round_two(), bundle(), design_using_script()], runner)
    assert result.status == "draft" and "untested" in result.draft_reason and "Windows-container" in result.draft_reason
    assert len(mock.calls) == 4 and len(runner.calls) == 1  # no repair is wasted on something that could not run; it stopped at once
    row = next(c for c in result.checks if c.name == "script test cases run in the sandbox")
    assert row.status == "not run" and not any(c.name.startswith("script test: ") for c in result.checks)
    assert (result.out_dir / "scripts" / "count_lines.py").exists()  # the code is delivered, clearly marked untested
    report = report_of(result)
    assert "Status: DRAFT. This skill has scripts that were not all run in the sandbox" in report
    assert "every check that ran passed" not in report


def test_a_missing_image_is_not_run_with_the_exact_command_to_fix_it_and_other_scripts_still_run(tmp_path):
    java = script(name="count_java", language="java", code="public class A { public static void main(String[] a) { System.out.println(3); } }\n")
    cases = [case(), failure_case(), case(name="java-counts", script="count_java")]

    def answer(language, script, args, stdin):
        if language == "java":
            return ImageNotPulled("eclipse-temurin:21-jdk", "wsl.exe --exec docker pull eclipse-temurin:21-jdk")
        return crash() if "nope" in args[0] else ok()

    runner = FakeRunner(answer)
    result, _ = run(tmp_path, [round_one(), round_two(), bundle([script(), java], cases), design_using_script()], runner)
    assert result.status == "draft"
    passed = [c.name for c in result.checks if c.name.startswith("script test: ") and c.status == "passed"]
    assert passed == ["script test: count_lines / counts-three", "script test: count_lines / missing-file"]
    row = next(c for c in result.checks if c.name == "script tests: count_java")
    assert row.status == "not run" and "wsl.exe --exec docker pull eclipse-temurin:21-jdk" in row.detail


def test_structurally_broken_scripts_are_never_run_and_nothing_escapes_the_folder(tmp_path):
    evil = bundle(cases=[case(fixtures=[Fixture(path="../../escape.txt", text="x")]), failure_case()])
    runner = FakeRunner()
    result, _ = run(tmp_path, [round_one(), round_two(), evil, evil, design_using_script()], runner)
    assert runner.calls == [] and result.status == "draft"
    failed = next(c for c in result.checks if c.status == "failed" and c.name.startswith("script test cases are complete"))
    assert "not a plain relative fixture path" in failed.detail
    assert not (tmp_path / "escape.txt").exists() and not list(tmp_path.rglob("escape.txt"))


@pytest.mark.parametrize("code, used", [
    ("import subprocess\nsubprocess.run(['ls'])\n", "run_commands"),
    ("import socket\nsocket.create_connection(('x', 1))\n", "network"),
    ("open('out.txt', 'w').write('x')\n", "write_files"),
])
def test_a_script_that_uses_the_network_other_programs_or_writes_files_is_refused(code, used):
    checks = check_scripts([script(code=code)], [case(), failure_case()])
    bad = next(c for c in checks if c.name == "scripts do not use the network, start programs or write files")
    assert bad.status == "failed" and used in bad.detail


def test_a_success_case_that_checks_nothing_is_refused_and_so_is_an_empty_fragment():
    weak = check_scripts([script()], [case(stdout_contains=[]), failure_case()])
    assert any(c.status == "failed" and "checks no output" in c.detail for c in weak)
    vacuous = check_scripts([script()], [case(stdout_contains=[" "]), failure_case()])
    assert any(c.status == "failed" and "empty or overlong" in c.detail for c in vacuous)


def test_every_script_needs_a_case_that_checks_its_output_and_cases_must_name_real_scripts():
    none = check_scripts([script()], [case(script="other")])
    assert any("runs 'other', which is not one of the scripts" in c.detail for c in none)
    assert any("script 'count_lines' has no test case" in c.detail for c in none)
    only_failures = check_scripts([script()], [failure_case()])
    assert any("no success case that checks what it prints" in c.detail for c in only_failures)


def test_a_script_without_a_failure_case_gets_a_warning_not_a_failure():
    checks = check_scripts([script()], [case()])
    warn = next(c for c in checks if c.name == "every script has a case where it is expected to fail")
    assert warn.status == "warning" and "count_lines" in warn.detail
    assert all(c.status != "failed" for c in checks)


# ---- names, paths and commands are decided by code ----------------------------------------------------------


def test_script_names_are_made_safe_by_code_and_the_cases_follow(tmp_path):
    messy = bundle([script(name="../Count Lines!!")], [case(script="../Count Lines!!"), failure_case(script="../Count Lines!!")])
    result, _ = run(tmp_path, [round_one(), round_two(), messy, design_using_script()], FakeRunner())
    assert result.sdm.scripts[0].name == "count_lines" and result.status == "ok"
    assert (result.out_dir / "scripts" / "count_lines.py").exists()
    assert any("'../Count Lines!!' was changed to 'count_lines'" in n for n in result.notes)


def test_the_file_name_and_command_come_from_the_language_table_not_from_the_model():
    assert set(typing.get_args(ScriptLanguage)) == set(runnable_languages()) == set(EXTENSIONS)
    for lang in typing.get_args(ScriptLanguage):
        s = script(language=lang)
        assert script_path(s) == f"scripts/count_lines{EXTENSIONS[lang]}"
    assert run_command(script(language="typescript")) == "node --experimental-strip-types scripts/count_lines.ts"
    assert run_command(script(language="java")) == "java scripts/count_lines.java"


def test_model_written_text_is_data_it_is_never_evaluated_as_a_template(tmp_path):
    nasty = script(purpose="Counts {{ 7*7 }} lines {% evil %}", code="print('{{ 7*7 }}')  # {% x %}\n")
    shell = bundle([nasty], [case(stdout_contains=["49"], args=[]), failure_case()])
    answer = lambda language, script, args, stdin: crash() if args and "nope" in args[0] else ok("49\n")  # noqa: E731
    result, _ = run(tmp_path, [round_one(), round_two(), shell, design_using_script()], FakeRunner(answer))
    assert result.status == "ok"
    skill_md = (result.out_dir / "SKILL.md").read_text(encoding="utf-8")
    assert "Counts {{ 7*7 }} lines {% evil %}" in skill_md
    assert (result.out_dir / "scripts" / "count_lines.py").read_text(encoding="utf-8") == "print('{{ 7*7 }}')  # {% x %}\n"


def test_normalize_unifies_line_endings_and_ends_the_file_with_a_newline():
    s, _, _ = normalize([script(code="print(1)\r\nprint(2)")], [])
    assert s[0].code == "print(1)\nprint(2)\n"


# ---- the design step must use real scripts ------------------------------------------------------------------


def test_a_workflow_that_names_a_script_that_does_not_exist_is_sent_back_once(tmp_path):
    ghost = design_using_script(workflow=[
        Step(title="Count", instruction="Run `python scripts/ghost.py` and read the number.", on_failure="Stop."),
        Step(title="Report", instruction="Say it.", on_failure="Say what is missing."),
        Step(title="Check", instruction="Compare.", on_failure="Say so."),
    ])
    result, mock = run(tmp_path, [round_one(), round_two(), bundle(), ghost, design_using_script()], FakeRunner())
    assert result.status == "ok" and result.model_calls == 5
    assert "names scripts that are not shipped: scripts/ghost.py" in mock.calls[4]["prompt"]


def test_a_script_no_step_uses_is_a_warning(tmp_path):
    result, _ = run(tmp_path, [round_one(), round_two(), bundle(), draft()], FakeRunner())
    warn = [c for c in result.checks if c.status == "warning"]
    assert [c.name for c in warn] == ["every script is used by a workflow step"] and result.status == "ok"


# ---- when the model writes no scripts, or scripts are not asked for ----------------------------------------


def test_asking_for_scripts_when_the_model_writes_none_gives_an_ordinary_skill(tmp_path):
    result, mock = run(tmp_path, [round_one(), round_two(), ScriptBundle(scripts=[], cases=[]), draft()], FakeRunner())
    assert result.status == "ok" and result.sdm.scripts == [] and any("needs no scripts" in n for n in result.notes)
    assert mock.calls[3]["system"] == DESIGN_SYSTEM  # the model was not told about scripts that do not exist
    assert not (result.out_dir / "scripts").exists()
    assert "scripts run in a sandbox" in [c.name for c in result.checks if c.status == "not run"]


def test_without_the_scripts_option_no_script_step_happens_and_nothing_probes_the_sandbox(tmp_path):
    runner = FakeRunner()
    result, mock = run(tmp_path, [round_one(), round_two(), draft()], runner, with_scripts=False)
    assert result.status == "ok" and result.model_calls == 3 and runner.calls == [] and result.sdm.scripts == []


# ---- the same definition renders the same bytes, and render re-tests ----------------------------------------


def test_render_rebuilds_identical_files_and_runs_the_script_cases_again(tmp_path):
    first = run(tmp_path, [round_one(), round_two(), bundle(), design_using_script()], FakeRunner())[0]
    runner = FakeRunner()
    again = rebuild(first.out_dir / "skill.sdm.json", tmp_path / "again", force=False, script_runner=runner)
    assert again.status == "ok" and len(runner.calls) == 2  # the cases really ran again
    for rel in ("SKILL.md", "README.md", "scripts/count_lines.py", "tests/script_cases.json",
                "tests/fixtures/counts-three/in.txt", "skill.sdm.json"):
        assert (first.out_dir / rel).read_bytes() == (again.out_dir / rel).read_bytes(), rel


def test_a_saved_skill_without_scripts_still_loads_and_renders(tmp_path):
    first = run(tmp_path, [round_one(), round_two(), draft()], FakeRunner(), with_scripts=False)[0]
    data = json.loads((first.out_dir / "skill.sdm.json").read_text(encoding="utf-8"))
    del data["scripts"], data["script_cases"]  # a definition saved before this feature existed
    (first.out_dir / "skill.sdm.json").write_text(json.dumps(data), encoding="utf-8")
    assert rebuild(first.out_dir / "skill.sdm.json", tmp_path / "again", force=False).status == "ok"


def test_the_script_files_are_listed_in_a_fixed_order_with_their_fixtures():
    files = script_files([script()], [case(), failure_case()])
    assert list(files) == ["scripts/count_lines.py", "tests/fixtures/counts-three/in.txt", "tests/script_cases.json"]


# ---- the real runner: probes once, never fetches images, never runs without a sandbox -----------------------

AVAILABLE = SandboxStatus(True, "Docker is running Linux containers.", "linux")
NOT_AVAILABLE = SandboxStatus(False, "Docker is not installed or not on PATH.")


def test_the_real_runner_probes_once_for_many_runs(tmp_path):
    probes, commands = [], []

    def execute(cmd, **kw):
        commands.append(cmd)
        return SimpleNamespace(stdout=b"3\n", stderr=b"", returncode=0)

    runner = SandboxScriptRunner(probe=lambda: probes.append(1) or AVAILABLE, execute=execute)
    for _ in range(3):
        assert runner("python", tmp_path, "scripts/a.py", ["x.txt"], "").stdout == "3\n"
    assert len(probes) == 1 and len(commands) == 3
    assert commands[0][-3:] == ["python", "/skill/scripts/a.py", "x.txt"]  # case arguments follow the script, as list items
    assert "-i" not in commands[0]  # no input, so the container's input stays closed


def test_input_is_piped_in_only_when_a_case_gives_some(tmp_path):
    seen = {}

    def execute(cmd, **kw):
        seen.update(cmd=cmd, kw=kw)
        return SimpleNamespace(stdout=b"", stderr=b"", returncode=0)

    SandboxScriptRunner(probe=lambda: AVAILABLE, execute=execute)("python", tmp_path, "scripts/a.py", [], "hello\n")
    assert "-i" in seen["cmd"] and seen["kw"]["input"] == b"hello\n"
    assert seen["cmd"].index("-i") < seen["cmd"].index("python:3.13-slim")  # a docker option, not a script argument


def test_the_run_command_has_no_input_flag_unless_asked(tmp_path):
    assert "-i" not in docker_run_args("python:3.13-slim", tmp_path, ["python"], Limits(), "n1")
    assert "-i" in docker_run_args("python:3.13-slim", tmp_path, ["python"], Limits(), "n1", stdin=True)


def test_an_unpulled_image_is_a_clear_not_run_never_a_failure_and_never_a_download(tmp_path):
    def execute(cmd, **kw):
        assert "--pull" in cmd and cmd[cmd.index("--pull") + 1] == "never"
        return SimpleNamespace(stdout=b"", stderr=b"Unable to find image 'python:3.13-slim' locally", returncode=125)

    runner = SandboxScriptRunner(probe=lambda: AVAILABLE, execute=execute)
    with pytest.raises(ImageNotPulled, match="docker pull python:3.13-slim") as info:
        runner("python", tmp_path, "scripts/a.py", [], "")
    assert info.value.image == "python:3.13-slim"


def test_without_a_sandbox_the_real_runner_raises_and_runs_nothing(tmp_path):
    commands = []
    runner = SandboxScriptRunner(probe=lambda: NOT_AVAILABLE, execute=lambda *a, **k: commands.append(a))
    with pytest.raises(SandboxUnavailable, match="Not run. Docker is not installed"):
        runner("python", tmp_path, "scripts/a.py", [], "")
    assert commands == []


def test_the_docker_runner_pipes_input_and_still_kills_a_timed_out_container(tmp_path):
    seen = []

    def execute(cmd, **kw):
        seen.append((cmd, kw))
        if cmd[1] == "run":
            raise subprocess.TimeoutExpired(cmd, 1, output=b"", stderr=b"")
        return SimpleNamespace(stdout=b"", stderr=b"", returncode=0)

    result = DockerRunner("python:3.13-slim", probe=lambda: AVAILABLE, runner=execute).run(tmp_path, ["python"], "text")
    assert result.timed_out and seen[0][1]["input"] == b"text" and seen[1][0][1] == "kill"


# ---- command line --------------------------------------------------------------------------------------------


def cli_build(monkeypatch, capsys, tmp_path, responses, runner):
    monkeypatch.setattr(cli, "provider_from_env", lambda: MockProvider(responses))
    monkeypatch.setattr("skillforge.build.scripts.SandboxScriptRunner", lambda: runner)
    answers = tmp_path / "answers.json"
    answers.write_text(json.dumps(ANSWERS), encoding="utf-8")
    code = cli.main(["build", FIRST, "--answers", str(answers), "--yes", "--scripts", "--out", str(tmp_path / "skills")])
    return code, capsys.readouterr().out


def test_cli_scripts_option_builds_tests_and_summarises(monkeypatch, capsys, tmp_path):
    code, out = cli_build(monkeypatch, capsys, tmp_path, [round_one(), round_two(), bundle(), design_using_script()], FakeRunner())
    assert code == 0 and "Skill 'duplicate-function-finder' written to" in out
    assert "Scripts: 1 written, 2 of 2 case(s) passed in the sandbox" in out and "4 not run" in out


def test_cli_untested_scripts_exit_with_code_1_and_say_why(monkeypatch, capsys, tmp_path):
    runner = FakeRunner(lambda *a: SandboxUnavailable("Not run. Docker is not installed or not on PATH."))
    code, out = cli_build(monkeypatch, capsys, tmp_path, [round_one(), round_two(), bundle(), design_using_script()], runner)
    assert code == 1 and "its scripts were not all run in the sandbox" in out
    assert "Docker is not installed or not on PATH" in out and "FAILED:" not in out


def test_an_engine_that_disappears_midway_keeps_the_cases_that_ran_and_marks_the_rest_untested():
    def answer(language, script, args, stdin):
        return SandboxUnavailable("Not run. Docker did not answer in time.") if "nope" in args[0] else ok()

    report = run_script_tests([script()], [case(), failure_case()], FakeRunner(answer))
    assert [c.status for c in report.results] == ["passed", "not run"]
    assert report.tested and not report.complete  # so the skill is still a draft: not every case ran


def test_run_script_tests_with_no_scripts_does_nothing():
    runner = FakeRunner()
    report = run_script_tests([], [], runner)
    assert report.results == [] and not report.tested and runner.calls == []
