"""The plugin kind: a folder with `.claude-plugin/plugin.json` that is composed from skills and agents already in the library.

A plugin is not described in words and checked by a conversation: nothing here asks a model. It is assembled by
`library/plugin.py`, and installing it means copying the folder to a place the person chooses, from where Claude Code adds it.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path

from ..build.models import RequirementSpec
from ..build.pipeline import BuildError, Round
from ..build.scripts import ScriptRunner
from ..providers.base import LLMProvider
from ..validate.plugin import plugin_name_of
from .base import BuildOutcome, Kind

COMPOSED = "A plugin is composed from the skills and agents in the library: use the plugin composer, not the builder."


class PluginKind(Kind):
    key = "plugin"
    label = "Plugin"
    library_dir = "library-plugin"
    definition_file = ".claude-plugin/plugin.json"
    slots = ()
    install_targets = ("folder",)  # Claude Code adds a plugin from a folder; nothing is written into its settings
    conversational = False

    def name_of(self, files: Mapping[str, bytes]) -> str | None:
        return plugin_name_of(files)

    def personal_dir(self) -> Path:
        raise ValueError("A plugin is installed from a folder you choose.")

    def understand(
        self, provider: LLMProvider, words: str, round_no: int, max_rounds: int, previous: RequirementSpec | None = None,
    ) -> Round:
        raise BuildError(COMPOSED)

    def build(
        self, spec: dict, provider: LLMProvider, *, out_root: Path, with_scripts: bool, script_runner: ScriptRunner | None,
        sandbox_note: str, calls: int, notes: list[str], progress: Callable[[str], None],
    ) -> BuildOutcome:
        raise BuildError(COMPOSED)
