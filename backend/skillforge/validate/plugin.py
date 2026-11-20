"""The definition check of a plugin: `.claude-plugin/plugin.json` and what sits beside it.

It plays the part for a plugin that the `SKILL.md` check plays for a skill; every other static check still runs on the whole
folder. Nothing here runs anything. A plugin is only as safe as what it contains, so the check also lists what its scripts can do:
the shared script checks look at a top-level `scripts/` folder only, and a plugin keeps its scripts under `skills/<name>/scripts/`.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import PurePosixPath

from ..results import FAILED, PASSED, WARNING, CheckResult
from .static import JS_LANGS, MAX_NAME, PY_SUFFIXES, SLUG, script_capabilities

MANIFEST = ".claude-plugin/plugin.json"
MARKETPLACE = ".claude-plugin/marketplace.json"
RESERVED_PREFIXES = ("claude-", "anthropic-")  # Claude Code refuses plugin names that start like this
MANIFEST_CHECK = "plugin.json exists and is a valid plugin manifest"
MARKETPLACE_CHECK = "the marketplace entry matches the manifest"
CONTENTS_CHECK = "the plugin contains a skill or an agent"
SCRIPTS_CHECK = "scripts shipped inside the plugin"


def name_problem(name: object) -> str:
    """Why this cannot be a plugin name ("" when it can)."""
    if not isinstance(name, str) or not SLUG.match(name) or len(name) > MAX_NAME:
        return f"name must be lowercase letters, digits and hyphens, at most {MAX_NAME} characters"
    for prefix in RESERVED_PREFIXES:
        if name.startswith(prefix):
            return f"names that start with '{prefix}' are reserved, so Claude Code refuses them"
    return ""


def _json(files: Mapping[str, bytes], path: str) -> tuple[object, str]:
    try:
        return json.loads(files[path].decode("utf-8")), ""
    except UnicodeDecodeError:
        return None, f"{path} is not valid UTF-8"
    except ValueError as exc:
        return None, f"{path} is not valid JSON ({exc})"


def plugin_name_of(files: Mapping[str, bytes]) -> str | None:
    """The plugin's name when the manifest gives a usable one, else None."""
    if MANIFEST not in files:
        return None
    data, why = _json(files, MANIFEST)
    name = data.get("name") if isinstance(data, dict) and not why else None
    return name if isinstance(name, str) and not name_problem(name) else None


def _script_row(files: Mapping[str, bytes]) -> CheckResult:
    scripts = {rel: data for rel, data in files.items() if "scripts" in PurePosixPath(rel).parts[:-1]}
    if not scripts:
        return CheckResult(SCRIPTS_CHECK, PASSED, "this plugin has no scripts")
    caps: set[str] = set()
    unanalysed: list[str] = []
    for rel, data in sorted(scripts.items()):
        suffix = PurePosixPath(rel).suffix.lower()
        if suffix in PY_SUFFIXES or suffix in JS_LANGS:
            found, dynamic = script_capabilities(rel, data)
            caps |= found
            if dynamic:
                unanalysed.append(f"{rel} (uses {', '.join(sorted(dynamic))})")
        else:
            unanalysed.append(rel)
    shipped = f"{len(scripts)} script{'s' if len(scripts) != 1 else ''}"
    if not caps and not unanalysed:
        return CheckResult(SCRIPTS_CHECK, PASSED, f"{shipped}; by syntax none uses the network, commands or file writes")
    parts = [f"{shipped} run on this machine when the plugin is used"]
    if caps:
        parts.append("they can use: " + ", ".join(sorted(c.replace("_", " ") for c in caps)))
    if unanalysed:
        parts.append("not analysed: " + ", ".join(unanalysed[:5]))
    return CheckResult(SCRIPTS_CHECK, WARNING, "; ".join(parts) + ". Read them before installing.")


def check_plugin_json(files: Mapping[str, bytes], folder: str | None) -> list[CheckResult]:
    if MANIFEST not in files:
        return [CheckResult(MANIFEST_CHECK, FAILED, f"there is no {MANIFEST} in the folder")]
    manifest, why = _json(files, MANIFEST)
    if why or not isinstance(manifest, dict):
        return [CheckResult(MANIFEST_CHECK, FAILED, why or "the manifest is not a JSON object")]
    problems: list[str] = []
    if name_problem(manifest.get("name")):
        problems.append(name_problem(manifest.get("name")))
    for key in ("version", "description"):
        if key in manifest and not isinstance(manifest[key], str):
            problems.append(f"{key} must be text")
    out = [CheckResult(MANIFEST_CHECK, FAILED, "; ".join(problems)) if problems else CheckResult(MANIFEST_CHECK, PASSED)]
    if MARKETPLACE in files:
        market, why = _json(files, MARKETPLACE)
        entries = market.get("plugins") if isinstance(market, dict) and not why else None
        names = [e.get("name") for e in entries if isinstance(e, dict)] if isinstance(entries, list) else []
        if why or not isinstance(market, dict):
            out.append(CheckResult(MARKETPLACE_CHECK, FAILED, why or "the marketplace file is not a JSON object"))
        elif manifest.get("name") not in names:
            out.append(CheckResult(MARKETPLACE_CHECK, FAILED, f"no entry in the marketplace is named '{manifest.get('name')}' (it lists: {', '.join(map(str, names)) or 'nothing'})"))
        else:
            out.append(CheckResult(MARKETPLACE_CHECK, PASSED))
    has_skill = any(PurePosixPath(rel).match("skills/*/SKILL.md") for rel in files)
    has_agent = any(PurePosixPath(rel).parent.as_posix() == "agents" and rel.endswith(".md") for rel in files)
    out.append(CheckResult(CONTENTS_CHECK, PASSED) if has_skill or has_agent else CheckResult(CONTENTS_CHECK, FAILED, "there is no skills/<name>/SKILL.md and no agents/<name>.md in it"))
    out.append(_script_row(files))
    return out
