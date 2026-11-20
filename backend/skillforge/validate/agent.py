"""The definition check of an agent: an `AGENT.md` whose front matter is a Claude Code subagent definition.

It plays the part for an agent that the `SKILL.md` check plays for a skill: every other static check still runs on the
folder. Nothing here runs anything. A missing `tools` line fails, because Claude Code gives an agent that has none every
tool. Settings that skip approval or run code only warn: a person has to read them, and they may be intended.
"""

from __future__ import annotations

import re
from collections.abc import Mapping

import yaml

from ..results import FAILED, PASSED, WARNING, CheckResult
from .static import MAX_DESCRIPTION, MAX_NAME, SLUG

DEFINITION_FILE = "AGENT.md"
DEFINITION_CHECK = "AGENT.md exists and its front matter is valid"
TOOLS_CHECK = "tools are listed explicitly (an agent without a tools line can use every tool)"
RUNS_CODE_CHECK = "no setting that skips approval or runs code (permissionMode bypassPermissions, hooks, mcpServers)"
FOLDER_CHECK = "folder name matches the agent name"
BEYOND_READING_CHECK = "no tools beyond reading and searching files"
READING_TOOLS = ("Read", "Grep", "Glob")


def _tools(value: object) -> list[str]:
    parts = value.split(",") if isinstance(value, str) else [str(p) for p in value] if isinstance(value, list) else []
    return [p.strip() for p in parts if p.strip()]


def _read(files: Mapping[str, bytes]) -> tuple[dict | None, str, str]:
    """(front matter, body, why it could not be read). The front matter is None when there is a reason."""
    if DEFINITION_FILE not in files:
        return None, "", f"there is no {DEFINITION_FILE} at the top of the folder"
    try:
        text = files[DEFINITION_FILE].decode("utf-8").replace("\r\n", "\n")
    except UnicodeDecodeError:
        return None, "", f"{DEFINITION_FILE} is not valid UTF-8"
    match = re.match(r"---\n(.*?)\n---\n", text, re.DOTALL)
    if not match:
        return None, "", f"{DEFINITION_FILE} has no front matter between --- lines"
    try:
        meta = yaml.safe_load(match.group(1))
    except yaml.YAMLError as exc:
        return None, "", f"front matter is not valid YAML: {exc}"
    if not isinstance(meta, dict):
        return None, "", "front matter is not a set of key: value pairs"
    return meta, text[match.end():], ""


def check_agent_md(files: Mapping[str, bytes], folder: str | None) -> list[CheckResult]:
    meta, body, why = _read(files)
    if meta is None:
        return [CheckResult(DEFINITION_CHECK, FAILED, why)]
    problems: list[str] = []
    name, description = meta.get("name"), meta.get("description")
    if not isinstance(name, str) or not SLUG.match(name) or len(name) > MAX_NAME:
        problems.append(f"name must be lowercase letters, digits and hyphens, at most {MAX_NAME} characters")
    if not isinstance(description, str) or not description.strip():
        problems.append("description is missing or empty")
    elif len(" ".join(description.split())) > MAX_DESCRIPTION:
        problems.append(f"description is longer than {MAX_DESCRIPTION} characters")
    if not body.strip():
        problems.append("there are no instructions after the front matter")
    out = [CheckResult(DEFINITION_CHECK, FAILED, "; ".join(problems)) if problems else CheckResult(DEFINITION_CHECK, PASSED)]
    out.append(
        CheckResult(TOOLS_CHECK, PASSED, ", ".join(_tools(meta.get("tools")))) if _tools(meta.get("tools"))
        else CheckResult(TOOLS_CHECK, FAILED, "there is no `tools` line, or it is empty, so Claude Code would give this agent every tool")
    )
    extra = [t for t in _tools(meta.get("tools")) if t not in READING_TOOLS]
    out.append(
        CheckResult(
            BEYOND_READING_CHECK, WARNING,
            ", ".join(extra) + ": Edit and Write change files, Bash runs any shell command, WebFetch and WebSearch reach the network. "
            "Make sure you meant to give the agent these.",
        ) if extra else CheckResult(BEYOND_READING_CHECK, PASSED, "it can only read and search files")
    )
    risky = [key for key in ("hooks", "mcpServers") if key in meta]
    if meta.get("permissionMode") == "bypassPermissions":
        risky.insert(0, "permissionMode: bypassPermissions")
    out.append(
        CheckResult(
            RUNS_CODE_CHECK, WARNING,
            "the agent sets " + ", ".join(risky) + ": it can run without asking or run code on this machine. Read it before installing it.",
        ) if risky else CheckResult(RUNS_CODE_CHECK, PASSED)
    )
    if folder is not None and isinstance(name, str):
        out.append(
            CheckResult(FOLDER_CHECK, PASSED) if name == folder
            else CheckResult(FOLDER_CHECK, WARNING, f"folder '{folder}' but name is '{name}'")
        )
    return out
