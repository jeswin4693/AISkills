"""The Node MCP server kind: a folder with a `server.ts` (a TypeScript MCP server, run by `node server.ts`) that installs as a folder copy, never into Claude's settings.

The model drafts the tools; code writes the server around them and checks it by reading it (`build/mcp_node_pipeline.py`). The server is only ever run through
the sandbox, and the command in its README starts it under Node's permission model. Installing copies the folder to a place the person chooses; the README has
the one command that adds it to Claude Code, and the app never runs it. A separate kind from the Python server, so the plugin composer (which lists the `mcp`
kind) cannot include one: a plugin cannot run `npm ci`.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path

from ..build.mcp import MCP_EXTRACT_SYSTEM, MCP_QUESTIONS
from ..build.mcp_node_pipeline import build_node_from_spec
from ..build.models import SLOTS, RequirementSpec
from ..build.pipeline import Round, understand_round
from ..build.scripts import ScriptRunner
from ..mcpnode import SERVER_FILE
from ..providers.base import LLMProvider
from ..validate.mcp_node import node_name_of
from .base import BuildOutcome, Kind, Slot
from .mcp import MCP_SLOT_LABELS, summarize_mcp


class McpNodeKind(Kind):
    key = "mcp-node"
    label = "MCP server (Node)"
    library_dir = "library-mcp-node"
    definition_file = SERVER_FILE
    personal_label = ""  # nothing is written into Claude's settings: a server is installed into a folder you choose
    install_targets = ("folder",)
    slots = tuple(Slot(key, MCP_SLOT_LABELS[key], MCP_QUESTIONS[key]) for key in SLOTS)

    def name_of(self, files: Mapping[str, bytes]) -> str | None:
        return node_name_of(files)

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
        result = build_node_from_spec(
            RequirementSpec.model_validate(spec), provider, out_root=out_root, force=True, calls=calls, notes=notes, progress=progress,
        )
        return BuildOutcome(summarize_mcp(result), result.model_calls, result.notes)
