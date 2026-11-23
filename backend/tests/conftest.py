from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from skillforge.graph.build import build_graph


@pytest.fixture(autouse=True)
def isolated_data_dir(tmp_path_factory, monkeypatch):
    """Caches never touch the real data directory during tests."""
    monkeypatch.setenv("SKILLFORGE_DATA_DIR", str(tmp_path_factory.mktemp("sf-data")))


@pytest.fixture(autouse=True)
def never_reach_a_real_provider(monkeypatch, tmp_path_factory):
    """No test may read the real .env or hold a real key, so no test can call a hosted model by accident."""
    monkeypatch.setattr("skillforge.cli.load_dotenv", lambda *a, **k: False)
    monkeypatch.setattr("skillforge.settings.store.default_env_file", lambda: tmp_path_factory.mktemp("no-env") / ".env")  # a file that is not there
    for var in ("LLM_PROVIDER", "LLM_MODEL", "GOOGLE_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY"):
        monkeypatch.delenv(var, raising=False)


@pytest.fixture(autouse=True)
def never_start_a_container_by_accident(monkeypatch):
    """A built MCP server is started in the sandbox. An offline test that does not hand in its own runner gets "no sandbox", so
    no test ever starts a container by accident. The live tests pass a real runner themselves."""
    from skillforge.sandbox import SandboxUnavailable

    class NoSandbox:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def __call__(self, folder):
            raise SandboxUnavailable("Not run. Tests never start a container.")

    monkeypatch.setattr("skillforge.build.mcp_protocol.SandboxMcpRunner", NoSandbox)


def write_files(root: Path, files: dict[str, str]) -> Path:
    for rel, text in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    return root


@pytest.fixture
def repo(tmp_path):
    """repo({...files}) -> path of a throwaway repository (no git)."""
    counter = {"n": 0}

    def make(files: dict[str, str]) -> Path:
        counter["n"] += 1
        return write_files(tmp_path / f"repo{counter['n']}", files)

    return make


@pytest.fixture
def graph(repo):
    """graph({...files}) -> RepoGraph built without cache or git history."""

    def make(files: dict[str, str], **kwargs):
        kwargs.setdefault("use_cache", False)
        kwargs.setdefault("with_history", False)
        return build_graph(repo(files), **kwargs)

    return make


def git(root: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@example.com", "-C", str(root), *args],
        check=True, capture_output=True,
    )


def commit_all(root: Path, message: str) -> None:
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", message)


def touch_later(path: Path, seconds: int = 5) -> None:
    """Make the file look modified, whatever the file system's timestamp resolution."""
    st = path.stat()
    os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns + seconds * 1_000_000_000))
