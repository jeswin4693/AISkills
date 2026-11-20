"""What a "kind" is: one thing this app can build, keep in the library and install (today a skill).

A kind names its own checklist (the slots the requirement must fill), the folder it keeps its library in, where it
installs, and how to read its name from its files. The builder, the library and the API ask the registry about a kind
instead of hardcoding "skill", so a new kind is added by registering one, not by changing them.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Slot:
    """One answer the requirement must have: its key, the label the screen shows, and the question to ask."""

    key: str
    label: str
    question: str


class UnknownKind(ValueError):
    """The name given is not a registered kind."""


class Kind(ABC):
    key: str
    label: str
    library_dir: str
    slots: tuple[Slot, ...]
    install_targets: tuple[str, ...] = ("personal", "folder")

    @abstractmethod
    def name_of(self, files: Mapping[str, bytes]) -> str | None:
        """The safe name this kind's files declare, or None when it is missing or not a safe name."""

    @abstractmethod
    def personal_dir(self) -> Path:
        """The folder that "install for me" writes into."""
