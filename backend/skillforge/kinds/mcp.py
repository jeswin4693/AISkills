"""The MCP server kind: a folder with a `server.py` (a Python MCP server) that installs as a folder copy, never into Claude's settings.

The model drafts the tools; code writes the server around them and checks it by reading it (`build/mcp_pipeline.py`). The server is
only ever run through the sandbox. Installing copies the folder to a place the person chooses; the README has the one command that
adds it to Claude Code, and the app never runs it.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import asdict
from pathlib import Path

from ..build.mcp import MCP_EXTRACT_SYSTEM, MCP_QUESTIONS
from ..build.mcp_pipeline import McpBuildResult, build_mcp_from_spec
from ..build.models import SLOTS, RequirementSpec
from ..build.pipeline import Round, understand_round
from ..build.scripts import ScriptRunner
from ..providers.base import LLMProvider
from ..validate.mcp import mcp_name_of
from .base import BuildOutcome, Kind, Slot
from .skill import MAX_REPORT

MCP_SLOT_LABELS = {
    "goal": "What it lets Claude do",
    "inputs": "What each tool is given",
    "outputs": "What each tool returns",
    "constraints": "Rules it must follow",
    "acceptance_criteria": "How we will know it works",
    "failure_behavior": "When a tool cannot finish",
}


def summarize_mcp(result: McpBuildResult) -> dict:
    """The build result as the plain dict a session stores and the pages read (the same shape as a skill's)."""
    ran = [c for c in result.checks if c.status != "not run"]
    failed = sum(c.status == "failed" for c in ran)
    warned = sum(c.status == "warning" for c in ran)
    report = (result.out_dir / "report.md").read_text(encoding="utf-8")[:MAX_REPORT]
    return {
        "status": result.status, "draft_reason": result.draft_reason, "name": result.definition.name,
        "description": result.definition.description, "folder": result.out_dir.name, "files": result.files,
        "scripts": 0, "report_md": report,
        "counts": {"passed": len(ran) - failed - warned, "warning": warned, "failed": failed, "not_run": len(result.checks) - len(ran)},
        "checks": [asdict(c) for c in result.checks],
        "tokens": None,  # the token cost estimate is skill-only so far
    }


class McpKind(Kind):
    key = "mcp"
    label = "MCP server"
    library_dir = "library-mcp"
    definition_file = "server.py"
    personal_label = ""  # nothing is written into Claude's settings: an MCP server is installed into a folder you choose
    install_targets = ("folder",)
    slots = tuple(Slot(key, MCP_SLOT_LABELS[key], MCP_QUESTIONS[key]) for key in SLOTS)

    def name_of(self, files: Mapping[str, bytes]) -> str | None:
        return mcp_name_of(files)

    def personal_dir(self) -> Path:
        raise ValueError("An MCP server is installed into a folder you choose; adding it to Claude Code is a command you run.")

    def understand(
        self, provider: LLMProvider, words: str, round_no: int, max_rounds: int, previous: RequirementSpec | None = None,
    ) -> Round:
        # the person chose to build a server, so what the extraction calls the request never blocks it
        return understand_round(
            provider, words, round_no, max_rounds, questions=MCP_QUESTIONS, extract_system=MCP_EXTRACT_SYSTEM, skill_only=False,
            previous=previous,
        )

    def build(
        self, spec: dict, provider: LLMProvider, *, out_root: Path, with_scripts: bool, script_runner: ScriptRunner | None,
        sandbox_note: str, calls: int, notes: list[str], progress: Callable[[str], None],
    ) -> BuildOutcome:
        # a server has no helper scripts, so with_scripts and script_runner do not apply
        result = build_mcp_from_spec(
            RequirementSpec.model_validate(spec), provider, out_root=out_root, force=True, calls=calls, notes=notes, progress=progress,
        )
        return BuildOutcome(summarize_mcp(result), result.model_calls, result.notes)
