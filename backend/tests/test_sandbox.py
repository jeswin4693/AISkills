from __future__ import annotations

import subprocess
from types import SimpleNamespace

import pytest

from skillforge import cli
from skillforge.sandbox import DockerRunner, Limits, SandboxStatus, SandboxUnavailable, docker_run_args, probe_docker

AVAILABLE = SandboxStatus(True, "Docker is running Linux containers.", "linux")
UNAVAILABLE = SandboxStatus(False, "Docker is in Windows-container mode; the sandbox needs Linux containers.", "windows")


def fake_docker(stdout: str = "", returncode: int = 0, raises: Exception | None = None):
    def run(cmd, **kw):
        if raises:
            raise raises
        return SimpleNamespace(stdout=stdout, stderr="", returncode=returncode)

    return run


# ---- the hardened command ----------------------------------------------------------------------------------


def test_the_command_carries_every_hardening_flag(tmp_path):
    cmd = docker_run_args("python:3.13-slim", tmp_path, ["python", "scripts/run.py"], Limits(), "skillforge-abc123")
    joined = " ".join(cmd)
    for flag in ("--rm", "--network none", "--read-only", "--cap-drop ALL", "--security-opt no-new-privileges",
                 "--pids-limit 64", "--memory 256m", "--memory-swap 256m", "--cpus 1", "--ipc none",
                 "--user 65534:65534", "--pull never", "-w /skill"):
        assert flag in joined, flag
    assert "/tmp:rw,noexec,nosuid,size=16m" in joined  # the only writable place, and not executable
    assert f"{tmp_path.resolve()}:/skill:ro" in joined  # the skill is read-only
    assert cmd[0] == "docker" and cmd[-3:] == ["python:3.13-slim", "python", "scripts/run.py"]
    assert "--privileged" not in cmd and "host" not in joined


def test_arguments_stay_separate_list_items_so_no_shell_can_interpret_them(tmp_path):
    cmd = docker_run_args("python:3.13-slim", tmp_path, ["python", "-c", "print(1); rm -rf /"], Limits(), "n1")
    assert cmd[-1] == "print(1); rm -rf /"  # one argument, never split or run by a shell


@pytest.mark.parametrize("image", ["", "--privileged", "python 3.13", "-v /:/host alpine", "UPPER/case", "img;rm"])
def test_option_injection_through_the_image_is_refused(tmp_path, image):
    with pytest.raises(ValueError, match="image"):
        docker_run_args(image, tmp_path, ["python"], Limits(), "n1")


def test_bad_arguments_are_refused(tmp_path):
    with pytest.raises(ValueError, match="argv"):
        docker_run_args("python:3.13", tmp_path, [], Limits(), "n1")
    with pytest.raises(ValueError, match="argv"):
        docker_run_args("python:3.13", tmp_path, ["ok", 5], Limits(), "n1")  # type: ignore[list-item]
    with pytest.raises(ValueError, match="Not a directory"):
        docker_run_args("python:3.13", tmp_path / "nope", ["python"], Limits(), "n1")
    with pytest.raises(ValueError, match="container name"):
        docker_run_args("python:3.13", tmp_path, ["python"], Limits(), "bad name; x")


def test_an_image_pinned_by_digest_is_accepted(tmp_path):
    docker_run_args("python@sha256:" + "a" * 64, tmp_path, ["python"], Limits(), "n1")


# ---- is there a safe place to run? -------------------------------------------------------------------------


@pytest.mark.parametrize(
    "run, available, text",
    [
        (fake_docker("linux\n"), True, "Linux containers"),
        (fake_docker("windows\n"), False, "Windows-container mode"),
        (fake_docker("", returncode=1), False, "not running"),
        (fake_docker(raises=FileNotFoundError()), False, "not installed"),
        (fake_docker(raises=subprocess.TimeoutExpired("docker", 1)), False, "did not answer"),
        (fake_docker("freebsd\n"), False, "unexpected engine OS"),
    ],
)
def test_the_probe_only_says_yes_for_a_linux_engine(run, available, text):
    s = probe_docker(run=run)
    assert s.available is available and text in s.reason


# ---- fail closed -------------------------------------------------------------------------------------------


def test_without_a_linux_engine_nothing_runs_anywhere(tmp_path):
    calls = []
    runner = DockerRunner("python:3.13-slim", probe=lambda: UNAVAILABLE, runner=lambda *a, **k: calls.append(a))
    with pytest.raises(SandboxUnavailable, match="Not run. Docker is in Windows-container mode"):
        runner.run(tmp_path, ["python", "x.py"])
    assert calls == []  # not even a docker command was attempted, and certainly no host fallback


def test_a_run_is_always_a_docker_command_never_the_script_itself(tmp_path):
    seen = []

    def recording(cmd, **kw):
        seen.append(cmd)
        return SimpleNamespace(stdout=b"hello\n", stderr=b"", returncode=3)

    result = DockerRunner("python:3.13-slim", probe=lambda: AVAILABLE, runner=recording).run(tmp_path, ["python", "run.py"])
    assert result.exit_code == 3 and result.stdout == "hello\n" and not result.timed_out and not result.truncated
    assert len(seen) == 1 and seen[0][:2] == ["docker", "run"]


def test_a_timeout_kills_the_container_and_reports_it(tmp_path):
    seen = []

    def runner(cmd, **kw):
        seen.append(cmd)
        if cmd[1] == "run":
            raise subprocess.TimeoutExpired(cmd, 1, output=b"partial", stderr=b"")
        return SimpleNamespace(stdout=b"", stderr=b"", returncode=0)

    result = DockerRunner("python:3.13-slim", probe=lambda: AVAILABLE, runner=runner).run(tmp_path, ["python", "loop.py"])
    assert result.timed_out and result.exit_code is None and result.stdout == "partial"
    name = seen[0][seen[0].index("--name") + 1]
    assert seen[1] == ["docker", "kill", name]  # the same container is killed


def test_output_is_capped(tmp_path):
    runner = lambda cmd, **kw: SimpleNamespace(stdout=b"x" * 500, stderr=b"", returncode=0)  # noqa: E731
    result = DockerRunner("python:3.13-slim", Limits(max_output_bytes=100), probe=lambda: AVAILABLE, runner=runner).run(tmp_path, ["python"])
    assert len(result.stdout) == 100 and result.truncated


# ---- command line ------------------------------------------------------------------------------------------


def test_sandbox_status_command_and_a_probe_that_breaks_never_stops_a_build(monkeypatch, capsys):
    monkeypatch.setattr(cli, "probe_docker", lambda: UNAVAILABLE)
    assert cli.main(["sandbox-status"]) == 1
    out = capsys.readouterr().out
    assert "UNAVAILABLE" in out and "never run on this machine directly" in out

    monkeypatch.setattr(cli, "probe_docker", lambda: AVAILABLE)
    assert cli.main(["sandbox-status"]) == 0 and "AVAILABLE" in capsys.readouterr().out

    def boom():
        raise RuntimeError("docker exploded")

    monkeypatch.setattr(cli, "probe_docker", boom)
    assert cli._sandbox_note().startswith("unknown")
