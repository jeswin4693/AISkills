"""What each permission a skill declares means in Claude Code's tool names.

Code decides this, never the model. The list is explicit and always in the same order, so the same permissions give
the same bytes. The agent builder reuses it to write an agent's `tools` field.
"""

from __future__ import annotations

from collections.abc import Sequence

TOOLS_FOR: dict[str, tuple[str, ...]] = {
    "read_files": ("Read", "Grep", "Glob"),
    "write_files": ("Edit", "Write"),
    "run_commands": ("Bash",),
    "network": ("WebFetch", "WebSearch"),
}


def tools_for(permissions: Sequence[str]) -> list[str]:
    """The tools for these permissions, each once, in the order of TOOLS_FOR (not the order given)."""
    unknown = sorted(set(permissions) - set(TOOLS_FOR))
    if unknown:
        raise ValueError(f"Not a permission this app knows: {', '.join(unknown)}.")
    wanted = set(permissions)
    return [tool for permission, tools in TOOLS_FOR.items() if permission in wanted for tool in tools]
