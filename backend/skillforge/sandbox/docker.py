"""Docker sandbox: a hardened command builder and a runner that fails closed.

Fail closed means: if no Linux container engine is available, `run` raises `SandboxUnavailable`. There is no
fallback that runs the script on the host, and no flag that turns the check off.
"""

from __future__ import annotations

import os
import re
import subprocess
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath

IMAGE = re.compile(r"^[a-z0-9][a-z0-9._/-]*(:[A-Za-z0-9._-]+)?(@sha256:[0-9a-f]{64})?$")
NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
DOCKER = ("docker",)


class SandboxUnavailable(Exception):
    """There is no safe place to run this. The script was NOT run anywhere."""


class ImageNotPulled(SandboxUnavailable):
    """The engine works but this language's image is not on the machine. Images are never fetched at run time."""

    def __init__(self, image: str, pull_command: str) -> None:
        self.image = image
        self.pull_command = pull_command
        super().__init__(f"Not run. The image {image} is not on this machine yet. Fetch it once with: {pull_command}")


@dataclass(frozen=True)
class SandboxStatus:
    available: bool
    reason: str
    engine_os: str | None = None
    prefix: tuple[str, ...] = DOCKER  # how to reach docker: ("docker",) or ("wsl.exe", "--exec", "docker")
    wsl: bool = False  # True when docker runs inside WSL, so host paths must be mapped to /mnt/<drive>/...


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


def _decode(data: bytes | str | None) -> str:
    """wsl.exe writes UTF-16 text; other tools write UTF-8. Return plain text either way."""
    if data is None:
        return ""
    if isinstance(data, str):
        return data
    return data.decode("utf-16-le", "replace") if b"\x00" in data else data.decode("utf-8", "replace")


def _engine_status(out, prefix: tuple[str, ...], wsl: bool, where: str) -> SandboxStatus:
    if out.returncode != 0:
        detail = " ".join((_decode(getattr(out, "stdout", None)) + _decode(getattr(out, "stderr", None))).split()).lower()
        if wsl and "no installed distributions" in detail:
            return SandboxStatus(False, "WSL is installed but has no Linux distribution yet (see docs/sandbox-wsl.md).", None, prefix, wsl)
        if wsl and "not installed" in detail:
            return SandboxStatus(False, "The Windows Subsystem for Linux is not installed.", None, prefix, wsl)
        if wsl:
            return SandboxStatus(False, "WSL is installed but Docker is not running inside it (or no Linux distribution exists).", None, prefix, wsl)
        return SandboxStatus(False, "Docker is installed but its engine is not running or not reachable.", None, prefix, wsl)
    engine = _decode(out.stdout).strip().lower()
    if engine == "linux":
        return SandboxStatus(True, f"{where} is running Linux containers.", "linux", prefix, wsl)
    if engine == "windows":
        return SandboxStatus(False, f"{where} is in Windows-container mode; the sandbox needs Linux containers.", "windows", prefix, wsl)
    return SandboxStatus(False, f"{where} reports an unexpected engine OS: {engine or 'unknown'}.", engine or None, prefix, wsl)


def probe_docker(timeout: float = 8.0, run: Callable = subprocess.run) -> SandboxStatus:
    """Is there a native Docker engine that runs Linux containers? Anything else means no sandbox from it."""
    try:
        out = run([*DOCKER, "version", "--format", "{{.Server.Os}}"], capture_output=True, timeout=timeout)
    except FileNotFoundError:
        return SandboxStatus(False, "Docker is not installed or not on PATH.")
    except (subprocess.TimeoutExpired, OSError):
        return SandboxStatus(False, "Docker did not answer in time.")
    return _engine_status(out, DOCKER, False, "Docker")


def probe_wsl_docker(timeout: float = 20.0, run: Callable = subprocess.run, distro: str | None = None) -> SandboxStatus:
    """Is there Docker inside WSL? `--exec` runs it directly, with no shell between us and docker."""
    prefix = ("wsl.exe", *(("-d", distro) if distro else ()), "--exec", "docker")
    try:
        out = run([*prefix, "version", "--format", "{{.Server.Os}}"], capture_output=True, timeout=timeout)
    except FileNotFoundError:
        return SandboxStatus(False, "WSL is not available on this machine (wsl.exe not found).", None, prefix, True)
    except (subprocess.TimeoutExpired, OSError):
        return SandboxStatus(False, "WSL did not answer in time.", None, prefix, True)
    return _engine_status(out, prefix, True, "Docker inside WSL")


def probe_sandbox(
    timeout: float = 8.0, run: Callable = subprocess.run, distro: str | None = None
) -> SandboxStatus:
    """The first safe place found: native Docker with Linux containers, else Docker inside WSL."""
    native = probe_docker(timeout, run)
    if native.available:
        return native
    wsl = probe_wsl_docker(timeout + 12, run, distro or os.environ.get("SKILLFORGE_WSL_DISTRO") or None)
    if wsl.available:
        return wsl
    return SandboxStatus(False, f"{native.reason} WSL: {wsl.reason}", native.engine_os)


def to_wsl_path(path: str) -> str:
    """C:\\Users\\me\\x -> /mnt/c/Users/me/x. Only plain drive paths can be mapped."""
    p = PureWindowsPath(path)
    if not p.drive or len(p.drive) != 2 or p.drive[1] != ":":
        raise ValueError(f"Cannot map this path into WSL: {path}")
    return "/mnt/" + p.drive[0].lower() + "/" + "/".join(p.parts[1:])


def docker_run_args(
    image: str, host_dir: Path, argv: list[str], limits: Limits, name: str,
    *, prefix: tuple[str, ...] = DOCKER, wsl_paths: bool = False, stdin: bool = False,
) -> list[str]:
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
    mount = to_wsl_path(str(host_dir)) if wsl_paths else str(host_dir)
    return [
        *prefix, "run", "--rm", *(["-i"] if stdin else []), "--name", name,  # -i only when text is piped in
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
        "-v", f"{mount}:/skill:ro",  # the skill is mounted read-only
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
        probe: Callable[[], SandboxStatus] = probe_sandbox,
        runner: Callable = subprocess.run,
    ) -> None:
        self.image = image
        self.limits = limits or Limits()
        self._probe = probe
        self._runner = runner

    def run(self, skill_dir: Path, argv: list[str], stdin: str | None = None) -> RunResult:
        """Run `argv` in the box. `stdin` is text piped to the program; None (or empty) means no input at all."""
        status = self._probe()
        if not status.available:
            raise SandboxUnavailable(f"Not run. {status.reason}")
        name = f"skillforge-{uuid.uuid4().hex[:12]}"
        piped = stdin.encode("utf-8") if stdin else None
        cmd = docker_run_args(
            self.image, skill_dir, argv, self.limits, name,
            prefix=status.prefix, wsl_paths=status.wsl, stdin=piped is not None,
        )
        extra = {"input": piped} if piped is not None else {}
        try:
            proc = self._runner(cmd, capture_output=True, timeout=self.limits.timeout_s, **extra)
        except subprocess.TimeoutExpired as exc:
            self._runner([*status.prefix, "kill", name], capture_output=True, timeout=10)
            out, t1 = _clip(exc.stdout, self.limits.max_output_bytes)
            err, t2 = _clip(exc.stderr, self.limits.max_output_bytes)
            return RunResult(None, out, err, True, t1 or t2)
        out, t1 = _clip(proc.stdout, self.limits.max_output_bytes)
        err, t2 = _clip(proc.stderr, self.limits.max_output_bytes)
        return RunResult(proc.returncode, out, err, False, t1 or t2)
