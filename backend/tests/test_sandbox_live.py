"""Real-container tests: they prove the locks work. Skipped unless a Linux sandbox exists on this machine.

To enable them, get Docker running Linux containers (see docs/sandbox-wsl.md) and pre-pull the image:
    docker pull python:3.13-slim
"""

from __future__ import annotations

import time

import pytest

from skillforge.sandbox import DockerRunner, Limits, probe_sandbox

IMAGE = "python:3.13-slim"


@pytest.fixture(scope="module")
def status():
    s = probe_sandbox()
    if not s.available:
        pytest.skip(f"no Linux sandbox on this machine: {s.reason}")
    return s


def run_python(tmp_path, code: str, **limits):
    (tmp_path / "scripts").mkdir(exist_ok=True)
    (tmp_path / "scripts" / "t.py").write_text(code, encoding="utf-8")
    result = DockerRunner(IMAGE, Limits(**limits)).run(tmp_path, ["python", "/skill/scripts/t.py"])
    if result.exit_code == 125 and "Unable to find image" in result.stderr:
        pytest.skip(f"pre-pull the image first: docker pull {IMAGE}")
    return result


def test_a_script_runs_and_its_output_comes_back(status, tmp_path):
    r = run_python(tmp_path, "print('hello from the box')")
    assert r.exit_code == 0 and "hello from the box" in r.stdout and not r.timed_out


def test_the_network_is_cut_off(status, tmp_path):
    r = run_python(tmp_path, (
        "import socket\n"
        "try:\n    socket.create_connection(('1.1.1.1', 53), timeout=3); print('CONNECTED')\n"
        "except OSError:\n    print('BLOCKED')\n"
    ))
    assert "BLOCKED" in r.stdout and "CONNECTED" not in r.stdout


def test_the_skill_folder_and_root_file_system_are_read_only_but_tmp_is_writable(status, tmp_path):
    r = run_python(tmp_path, (
        "def can_write(p):\n"
        "    try:\n        open(p, 'w').write('x'); return True\n    except OSError:\n        return False\n"
        "print('skill', can_write('/skill/new.txt'))\n"
        "print('etc', can_write('/etc/new.txt'))\n"
        "print('tmp', can_write('/tmp/new.txt'))\n"
    ))
    assert "skill False" in r.stdout and "etc False" in r.stdout and "tmp True" in r.stdout
    assert not (tmp_path / "new.txt").exists()  # nothing reached the real folder


def test_the_script_runs_as_an_unprivileged_user(status, tmp_path):
    r = run_python(tmp_path, "import os\nprint('uid', os.getuid())")
    assert "uid 65534" in r.stdout


def test_a_runaway_process_is_killed_at_the_time_limit(status, tmp_path):
    started = time.time()
    r = run_python(tmp_path, "import time\ntime.sleep(120)", timeout_s=4)
    assert r.timed_out and r.exit_code is None
    assert time.time() - started < 60


def test_a_memory_hog_is_stopped(status, tmp_path):
    r = run_python(tmp_path, "data = bytearray(600 * 1024 * 1024)\nprint('ALLOCATED')", memory="64m")
    assert "ALLOCATED" not in r.stdout and r.exit_code != 0


def test_a_fork_bomb_hits_the_process_limit(status, tmp_path):
    r = run_python(tmp_path, (
        "import subprocess\nprocs = []\n"
        "try:\n    for _ in range(300):\n        procs.append(subprocess.Popen(['sleep', '5']))\n    print('UNLIMITED')\n"
        "except OSError:\n    print('LIMITED', len(procs))\n"
    ), pids=32)
    assert "LIMITED" in r.stdout and "UNLIMITED" not in r.stdout


# ---- every runnable language runs in the same locked box ---------------------------------------------------

from skillforge.sandbox.images import command_for  # noqa: E402

PROGRAMS = {
    "python": ("s.py", "print('hello from python')"),
    "javascript": ("s.js", "console.log('hello from javascript')"),
    "typescript": ("s.ts", "const n: number = 1;\nconsole.log('hello from typescript', n);"),
    "bash": ("s.sh", "echo hello from bash"),
    "ruby": ("s.rb", "puts 'hello from ruby'"),
    "php": ("s.php", "<?php echo 'hello from php';"),
    "java": ("Hi.java", 'public class Hi { public static void main(String[] a) { System.out.println("hello from java"); } }'),
}


@pytest.mark.parametrize("lang", sorted(PROGRAMS))
def test_each_interpreter_language_runs_with_no_network(status, tmp_path, lang):
    filename, source = PROGRAMS[lang]
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / filename).write_text(source, encoding="utf-8")
    image, argv = command_for(lang, f"scripts/{filename}")
    result = DockerRunner(image, Limits(timeout_s=90)).run(tmp_path, argv)
    if result.exit_code == 125 and "Unable to find image" in result.stderr:
        pytest.skip(f"pre-pull the image first: docker pull {image}")
    assert result.exit_code == 0, result.stderr[-300:]
    assert f"hello from {lang}" in result.stdout


# ---- generated scripts and their cases, run through the same box --------------------------------------------

from skillforge.build.models import Fixture, Script, ScriptCase  # noqa: E402
from skillforge.build.scripts import SandboxScriptRunner, run_script_tests  # noqa: E402


def live_case(**kw) -> ScriptCase:
    base = dict(
        name="counts-three", script="count_lines", args=["{fixtures}/in.txt"], stdin="",
        fixtures=[Fixture(path="in.txt", text="a\nb\nc\n")], expect_exit_code=0, stdout_contains=["3"], stderr_contains=[],
    )
    return ScriptCase(**{**base, **kw})


COUNT_PY = (
    "import sys\n"
    "try:\n    print(sum(1 for _ in open(sys.argv[1])))\n"
    "except OSError as exc:\n    print('Error:', exc, file=sys.stderr); sys.exit(1)\n"
)


def live_script(**kw) -> Script:
    base = dict(name="count_lines", language="python", purpose="Counts lines.", usage="path", code=COUNT_PY)
    return Script(**{**base, **kw})


def test_input_text_reaches_the_script_through_the_container(status, tmp_path):
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "t.py").write_text("import sys\nprint('got:', sys.stdin.read().strip())\n", encoding="utf-8")
    r = DockerRunner(IMAGE).run(tmp_path, ["python", "/skill/scripts/t.py"], "hello\nthere")
    assert r.exit_code == 0 and "got: hello\nthere" in r.stdout
    quiet = DockerRunner(IMAGE).run(tmp_path, ["python", "/skill/scripts/t.py"])  # no input: the script sees end of input at once
    assert quiet.exit_code == 0 and "got:" in quiet.stdout and not quiet.timed_out


def test_generated_script_cases_really_run_pass_and_fail_for_the_right_reasons(status):
    cases = [
        live_case(),
        live_case(name="missing-file", args=["{fixtures}/nope.txt"], fixtures=[], expect_exit_code=1, stdout_contains=[], stderr_contains=["Error"]),
        live_case(name="wrong-expectation", stdout_contains=["99"]),  # the script prints 3, so this one must fail
    ]
    report = run_script_tests([live_script()], cases, SandboxScriptRunner())
    by_case = {c.name.split(" / ")[1]: c for c in report.results}
    if all(c.status == "not run" for c in report.results):
        pytest.skip(report.results[0].detail)
    assert by_case["counts-three"].status == "passed" and by_case["missing-file"].status == "passed"
    assert by_case["wrong-expectation"].status == "failed" and "stdout does not contain '99'" in by_case["wrong-expectation"].detail
    assert "stdout: 3" in by_case["wrong-expectation"].detail  # the real output is quoted back
    assert report.tested and report.complete


def test_a_script_that_tries_the_network_or_to_write_is_stopped_by_the_box_not_just_by_the_checks(status):
    sneaky = live_script(code=(
        "import socket, sys\n"
        "try:\n    socket.create_connection(('1.1.1.1', 53), timeout=3); print('CONNECTED')\n"
        "except OSError:\n    print('NO-NETWORK')\n"
        "try:\n    open('/skill/x.txt', 'w'); print('WROTE')\nexcept OSError:\n    print('READ-ONLY')\n"
    ))
    # Run the runner directly: the structural check would refuse this script, and this proves the box would too.
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / "scripts").mkdir()
        (Path(tmp) / "scripts" / "count_lines.py").write_text(sneaky.code, encoding="utf-8")
        r = SandboxScriptRunner()("python", Path(tmp), "scripts/count_lines.py", [], "")
    assert "NO-NETWORK" in r.stdout and "READ-ONLY" in r.stdout and "CONNECTED" not in r.stdout and "WROTE" not in r.stdout


def test_a_java_script_whose_file_name_differs_from_its_class_runs(status):
    java = live_script(
        name="count_lines", language="java",
        code=(
            "import java.nio.file.*;\nimport java.util.*;\n"
            "public class Whatever {\n"
            "  public static void main(String[] args) throws Exception {\n"
            "    List<String> lines = Files.readAllLines(Path.of(args[0]));\n"
            "    System.out.println(lines.size());\n  }\n}\n"
        ),
    )
    report = run_script_tests([java], [live_case(), live_case(name="no-file", args=["{fixtures}/nope.txt"], fixtures=[], expect_exit_code=1, stdout_contains=[], stderr_contains=["Exception"])], SandboxScriptRunner())
    if all(c.status == "not run" for c in report.results):
        pytest.skip(report.results[0].detail)
    assert [c.status for c in report.results] == ["passed", "passed"], [c.detail for c in report.results]


def test_a_typescript_script_runs_with_arguments_and_fixtures(status):
    ts = live_script(
        name="count_lines", language="typescript",
        code=(
            "import { readFileSync } from 'node:fs';\n"
            "const text: string = readFileSync(process.argv[2], 'utf8');\n"
            "console.log(text.split(String.fromCharCode(10)).filter((l: string) => l.length > 0).length);\n"
        ),
    )
    report = run_script_tests([ts], [live_case()], SandboxScriptRunner())
    if all(c.status == "not run" for c in report.results):
        pytest.skip(report.results[0].detail)
    assert [c.status for c in report.results] == ["passed"], [c.detail for c in report.results]
