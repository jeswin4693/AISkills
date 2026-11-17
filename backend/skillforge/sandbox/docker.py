"""Docker sandbox: a hardened command builder and a runner that fails closed.

Fail closed means: if no Linux container engine is available, `run` raises `SandboxUnavailable`. There is no
fallback that runs the script on the host, and no flag that turns the check off.
"""

from __future__ import annotations

import re
import subprocess
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

IMAGE = re.compile(r"^[a-z0-9][a-z0-9._/-]*(:[A-Za-z0-9._-]+)?(@sha256:[0-9a-f]{64})?$")
NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")


class SandboxUnavailable(Exception):
    """There is no safe place to run this. The script was NOT run anywhere."""


@dataclass(frozen=True)
class SandboxStatus:
    available: bool
    reason: str
    engine_os: str | None = None


@dataclass(frozen=True)
class Limits:
    memory: str = "256m"
    cpus: str = "1"
    pids: int = 64
    timeout_s: int = 30
    max_output_bytes: int = 200_000
    tmpfs_size: str = "16m"


@dataclass
class RunResult:
    exit_code: int | None  # None when the run timed out
    stdout: str
    stderr: str
    timed_out: bool
    truncated: bool


def probe_docker(timeout: float = 8.0, run: Callable = subprocess.run) -> SandboxStatus:
    """Is there a Docker engine that runs Linux containers? Anything else means no sandbox."""
    try:
        out = run(["docker", "version", "--format", "{{.Server.Os}}"], capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError:
        return SandboxStatus(False, "Docker is not installed or not on PATH.")
    except (subprocess.TimeoutExpired, OSError):
        return SandboxStatus(False, "Docker did not answer in time.")
    if out.returncode != 0:
        return SandboxStatus(False, "Docker is installed but its engine is not running or not reachable.")
    engine = (out.stdout or "").strip().lower()
    if engine == "linux":
        return SandboxStatus(True, "Docker is running Linux containers.", "linux")
    if engine == "windows":
        return SandboxStatus(False, "Docker is in Windows-container mode; the sandbox needs Linux containers.", "windows")
    return SandboxStatus(False, f"Docker reports an unexpected engine OS: {engine or 'unknown'}.", engine or None)


def docker_run_args(image: str, host_dir: Path, argv: list[str], limits: Limits, name: str) -> list[str]:
    """The exact `docker run` command. A list, never a shell string, so nothing is ever interpreted by a shell."""
    if not IMAGE.match(image):
        raise ValueError(f"Not a valid image reference: {image!r}")
    if not NAME.match(name):
        raise ValueError(f"Not a valid container name: {name!r}")
    if not argv or not all(isinstance(a, str) and "\x00" not in a for a in argv):
        raise ValueError("argv must be a non-empty list of strings")
    host_dir = Path(host_dir).resolve()
    if not host_dir.is_dir():
        raise ValueError(f"Not a directory: {host_dir}")
    return [
        "docker", "run", "--rm", "--name", name,
        "--pull", "never",  # never reach the network to fetch an image at run time
        "--network", "none",  # the script cannot talk to anything
        "--read-only",  # the root file system cannot be written
        "--cap-drop", "ALL",  # no Linux capabilities
        "--security-opt", "no-new-privileges",
        "--pids-limit", str(limits.pids),  # no fork bombs
        "--memory", limits.memory, "--memory-swap", limits.memory,
        "--cpus", limits.cpus,
        "--ipc", "none",
        "--user", "65534:65534",  # nobody
        "--tmpfs", f"/tmp:rw,noexec,nosuid,size={limits.tmpfs_size}",  # the only writable place, and not executable
        "--env", "HOME=/tmp",
        "-v", f"{host_dir}:/skill:ro",  # the skill is mounted read-only
        "-w", "/skill",
        image, *argv,
    ]


def _clip(data: bytes | str | None, limit: int) -> tuple[str, bool]:
    raw = data if isinstance(data, bytes) else (data or "").encode("utf-8", "replace")
    return raw[:limit].decode("utf-8", "replace"), len(raw) > limit


class DockerRunner:
    def __init__(
        self,
        image: str,
        limits: Limits | None = None,
        *,
        probe: Callable[[], SandboxStatus] = probe_docker,
        runner: Callable = subprocess.run,
    ) -> None:
        self.image = image
        self.limits = limits or Limits()
        self._probe = probe
        self._runner = runner

    def run(self, skill_dir: Path, argv: list[str]) -> RunResult:
        status = self._probe()
        if not status.available:
            raise SandboxUnavailable(f"Not run. {status.reason}")
        name = f"skillforge-{uuid.uuid4().hex[:12]}"
        cmd = docker_run_args(self.image, skill_dir, argv, self.limits, name)
        try:
            proc = self._runner(cmd, capture_output=True, timeout=self.limits.timeout_s)
        except subprocess.TimeoutExpired as exc:
            self._runner(["docker", "kill", name], capture_output=True, timeout=10)
            out, t1 = _clip(exc.stdout, self.limits.max_output_bytes)
            err, t2 = _clip(exc.stderr, self.limits.max_output_bytes)
            return RunResult(None, out, err, True, t1 or t2)
        out, t1 = _clip(proc.stdout, self.limits.max_output_bytes)
        err, t2 = _clip(proc.stderr, self.limits.max_output_bytes)
        return RunResult(proc.returncode, out, err, False, t1 or t2)
