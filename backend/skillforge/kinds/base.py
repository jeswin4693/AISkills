"""What a "kind" is: one thing this app can build, keep in the library and install (today a skill).

A kind names its own checklist (the slots the requirement must fill), the folder it keeps its library in, where it
installs, and how to read its name from its files. The builder, the library and the API ask the registry about a kind
instead of hardcoding "skill", so a new kind is added by registering one, not by changing them.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # only names for the annotations: the builder, not this module, runs the pipeline
    from ..build.models import RequirementSpec
    from ..build.pipeline import Round
    from ..build.scripts import ScriptRunner
    from ..providers.base import LLMProvider


@dataclass(frozen=True)
class Slot:
    """One answer the requirement must have: its key, the label the screen shows, and the question to ask."""

    key: str
    label: str
    question: str


class UnknownKind(ValueError):
    """The name given is not a registered kind."""


@dataclass
class BuildOutcome:
    """What a kind's build leaves for the builder to store: the summary the pages read, and what it cost."""

    summary: dict  # stored as the session's result; needs status, draft_reason, folder, counts.failed, files, checks
    model_calls: int
    notes: list[str]


class Kind(ABC):
    key: str
    label: str
    library_dir: str
    definition_file: str  # the file that defines the thing (SKILL.md): checked first, and shown first by the web pages
    slots: tuple[Slot, ...]
    conversational: bool = True  # False for a kind that is composed from the library, not described in words
    personal_label: str = ""  # how the personal install folder is shown to a person, such as "~/.claude/skills"
    tools_field: str = "allowed-tools"  # the front-matter key that lists the tools it grants: what the risk diff compares
    install_file: str | None = None  # set when installing writes only this file, as <name><suffix> (an agent), not the folder
    install_targets: tuple[str, ...] = ("personal", "folder")

    @abstractmethod
    def name_of(self, files: Mapping[str, bytes]) -> str | None:
        """The safe name this kind's files declare, or None when it is missing or not a safe name."""

    @abstractmethod
    def personal_dir(self) -> Path:
        """The folder that "install for me" writes into."""

    @abstractmethod
    def understand(
        self, provider: LLMProvider, words: str, round_no: int, max_rounds: int, previous: RequirementSpec | None = None,
    ) -> Round:
        """One round of reading the person's words against this kind's checklist. `previous` is the partial requirement of the round before:
        an item it had answered that this reading does not repeat is kept when its quote is still in the person's words."""

    @abstractmethod
    def build(
        self, spec: dict, provider: LLMProvider, *, out_root: Path, with_scripts: bool, script_runner: ScriptRunner | None,
        sandbox_note: str, calls: int, notes: list[str], progress: Callable[[str], None],
    ) -> BuildOutcome:
        """Everything after the person approved `spec`: write this kind's files into `out_root` and say what happened."""
