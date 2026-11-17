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
