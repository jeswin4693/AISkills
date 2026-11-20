"""Facts about file formats that belong to someone else (Claude Code), kept as data with the day they were read.

Formats change. A check built on these lists only WARNS ("may not be known to the Claude Code you run"), and only
structure fails a skill. When Claude Code adds a key, change the set below and the date: nothing else needs to move.
"""

from __future__ import annotations

# The front-matter keys of a skill's SKILL.md that Claude Code recognises, read on 2026-11-20 from
# https://code.claude.com/docs/en/skills. That page was read through a summarising fetch tool, so its wording is
# paraphrased: re-read the page before relying on an edge case. Claude Code itself ignores a key it does not know and
# does not report it; claude.ai uploads and the Skills API reject one (that is why a warning is worth showing).
SKILL_FORMAT_CHECKED_ON = "2026-11-20"
SKILL_FRONT_MATTER_KEYS = frozenset({
    "name", "description", "when_to_use", "argument-hint", "arguments", "disable-model-invocation", "user-invocable",
    "allowed-tools", "disallowed-tools", "model", "effort", "context", "agent", "background", "hooks", "paths", "shell",
    "metadata", "license", "compatibility",
})
