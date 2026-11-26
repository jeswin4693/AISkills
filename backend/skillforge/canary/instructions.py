"""Reading the instructions a canary scan runs: a skill's `SKILL.md` or an agent's `AGENT.md`, exactly as an agent would load them,
plus what they ship (text files an agent may read) and what they declare (the kinds of tool they ask for).

Scripts are listed, never run: the scan runs words, and the static checks and the sandbox are what read and run code.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import PurePosixPath

import yaml

from ..evaluate.runner import tests_of
from ..validate.static import TEXT_SUFFIXES, split_tools
from .judge import SkillContext, safe

MAX_BUNDLED_FILE = 20_000  # characters; a longer file is not offered to the agent
MAX_BUNDLED_FILES = 40
_KINDS = {
    "read": {"read", "grep", "glob", "ls", "read_files", "notebookread", "list_files"},
    "write": {"write", "edit", "multiedit", "notebookedit", "write_files"},
    "command": {"bash", "powershell", "shell", "run_commands", "bashoutput", "killshell"},
    "network": {"webfetch", "websearch", "network", "fetch"},
}


def declared_classes(value: object) -> set[str] | None:
    """The kinds of tool a tools field asks for (read, write, command, network), or None when it names none the scan has a kind for. Nothing
    declared means nothing to compare with: a skill's `allowed-tools` only pre-approves tools, so its absence is not a promise of none."""
    found: set[str] = set()
    for entry in split_tools(value):
        name = re.split(r"[(\s]", entry, maxsplit=1)[0].lower()
        found |= {kind for kind, names in _KINDS.items() if name in names}
    return found or None


@dataclass
class Instructions:
    name: str
    kind: str  # "skill" or "agent"
    text: str  # the file an agent would load
    description: str = ""
    declared: set[str] | None = None
    files: dict[str, str] = field(default_factory=dict)  # text files it ships, by path inside its folder
    scripts: list[str] = field(default_factory=list)  # code it ships: listed, never run
    messages: list[str] = field(default_factory=list)  # its own test messages

    def context(self) -> SkillContext:
        """What the judge is told: what it declares, and all its text (to tell a place it names from one it does not)."""
        return SkillContext(declared=self.declared, text="\n".join([self.text, *self.files.values()]), strict=self.kind == "agent")


def _text(data: str | bytes) -> str:
    return (data.decode("utf-8", errors="replace") if isinstance(data, bytes) else data).replace("\r\n", "\n")


def load_instructions(files: Mapping[str, str | bytes]) -> Instructions:
    main, kind = next(((m, k) for m, k in (("SKILL.md", "skill"), ("AGENT.md", "agent")) if m in files), ("", ""))
    if not main:
        raise ValueError(
            "There is no SKILL.md or AGENT.md in this folder, so there are no instructions to scan. "
            "A plugin or an MCP server is checked through the skills and agents it holds."
        )
    text = _text(files[main])
    match = re.match(r"---\n(.*?)\n---\n", text, re.DOTALL)
    try:
        front = yaml.safe_load(match.group(1)) if match else None
    except yaml.YAMLError:
        front = None
    front = front if isinstance(front, dict) else {}
    raw_name, raw_description = front.get("name"), front.get("description")
    name = safe(raw_name.strip()) if isinstance(raw_name, str) and raw_name.strip() else kind  # the author chose it, and it is printed in every report
    description = raw_description if isinstance(raw_description, str) else ""
    shipped: dict[str, str] = {}
    for rel in sorted(files):
        if rel == main or PurePosixPath(rel).suffix.lower() not in TEXT_SUFFIXES or len(shipped) >= MAX_BUNDLED_FILES:
            continue
        body = _text(files[rel])
        if len(body) <= MAX_BUNDLED_FILE:
            shipped[rel] = body
    tests, _ = tests_of(files)
    return Instructions(
        name=name, kind=kind, text=text, description=description,
        declared=declared_classes(front.get("allowed-tools" if kind == "skill" else "tools")),
        files=shipped, scripts=sorted(r for r in shipped if r.startswith("scripts/")),
        messages=[t.run_input.strip() for t in tests if t.run_input.strip()],
    )
