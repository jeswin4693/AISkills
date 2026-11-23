"""The kinds this app builds. Insertion order is the order a screen lists them in.

`kinds` imports `build` and `validate` only; `library` (and later the builder and the API) import `kinds`, never
the reverse.
"""

from __future__ import annotations

from .agent import AgentKind
from .base import Kind, Slot, UnknownKind
from .mcp import McpKind
from .mcp_node import McpNodeKind
from .plugin import PluginKind
from .skill import SkillKind

KINDS: dict[str, Kind] = {"skill": SkillKind(), "agent": AgentKind(), "plugin": PluginKind(), "mcp": McpKind(), "mcp-node": McpNodeKind()}


def get_kind(key: str) -> Kind:
    try:
        return KINDS[key]
    except KeyError:
        raise UnknownKind(f"'{key}' is not a kind this app builds. It builds: {', '.join(KINDS)}.") from None


def all_kinds() -> list[Kind]:
    return list(KINDS.values())


__all__ = ["AgentKind", "KINDS", "Kind", "McpKind", "McpNodeKind", "PluginKind", "Slot", "SkillKind", "UnknownKind", "all_kinds", "get_kind"]
