"""The definition check of a plugin: `.claude-plugin/plugin.json` and what sits beside it.

It plays the part for a plugin that the `SKILL.md` check plays for a skill; every other static check still runs on the whole
folder. Nothing here runs anything. A plugin is only as safe as what it contains, so the check:
- runs every nested skill and agent through that kind's OWN checks (a plugin from outside, or a component stored before a check
  existed, must not carry a failing one in);
- lists what the code it ships can do (the shared script checks look at a top-level `scripts/` folder only, and a plugin keeps its
  code under `skills/<name>/`, in any folder);
- warns about what a v1 plugin should not carry (hooks, MCP servers, settings, executables), because they run on the machine;
- refuses a marketplace entry that points anywhere but this folder.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import PurePosixPath

from ..results import FAILED, PASSED, WARNING, CheckResult
from .static import JS_LANGS, MAX_NAME, PY_SUFFIXES, SLUG, script_capabilities, validate_files

MANIFEST = ".claude-plugin/plugin.json"
MARKETPLACE = ".claude-plugin/marketplace.json"
RESERVED_PREFIXES = ("claude-", "anthropic-")  # Claude Code refuses plugin names that start like this
MANIFEST_CHECK = "plugin.json exists and is a valid plugin manifest"
MARKETPLACE_CHECK = "the marketplace entry matches the manifest"
CONTENTS_CHECK = "the plugin contains a skill or an agent"
SCRIPTS_CHECK = "scripts shipped inside the plugin"
EXTRAS_CHECK = "no hooks, MCP servers, settings or executables beyond skills and agents"
CODE_SUFFIXES = {
    ".py", ".js", ".mjs", ".cjs", ".ts", ".sh", ".bash", ".zsh", ".ps1", ".bat", ".cmd", ".rb", ".php", ".pl", ".lua", ".java",
    ".go", ".rs", ".c", ".cc", ".cpp", ".cs", ".kt",
}
EXTRA_FILES = {"hooks.json", ".mcp.json", ".lsp.json", "settings.json", "settings.local.json"}  # what a v1 plugin should not carry
EXTRA_MANIFEST_KEYS = ("hooks", "mcpServers", "lspServers")


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


def shipped_code(files: Mapping[str, bytes]) -> dict[str, bytes]:
    """Every file that can run on the machine: code in any folder, anything under `scripts/` or `bin/`."""
    out: dict[str, bytes] = {}
    for rel, data in files.items():
        path = PurePosixPath(rel)
        if path.suffix.lower() in CODE_SUFFIXES or "scripts" in path.parts[:-1] or "bin" in path.parts[:-1]:
            out[rel] = data
    return out


def components(files: Mapping[str, bytes]) -> list[tuple[str, str, dict[str, bytes]]]:
    """(kind, name, that component's own files) for each skill and agent inside a plugin folder."""
    skills: dict[str, dict[str, bytes]] = {}
    agents: list[tuple[str, str, dict[str, bytes]]] = []
    for rel, data in files.items():
        parts = PurePosixPath(rel).parts
        if len(parts) >= 3 and parts[0] == "skills":
            skills.setdefault(parts[1], {})["/".join(parts[2:])] = data
        elif len(parts) == 2 and parts[0] == "agents" and rel.endswith(".md"):
            agents.append(("agent", PurePosixPath(rel).stem, {"AGENT.md": data}))
    return [("skill", name, sub) for name, sub in sorted(skills.items())] + sorted(agents, key=lambda a: a[1])


def _component_rows(files: Mapping[str, bytes]) -> list[CheckResult]:
    rows: list[CheckResult] = []
    for kind, name, sub in components(files):
        label = f"{kind} '{name}' passes its own checks"
        got = validate_files(sub, folder=name, kind=kind)
        bad = [f"{c.name}: {c.detail}".strip(": ") for c in got if c.status == FAILED]
        warn = [f"{c.name}: {c.detail}".strip(": ") for c in got if c.status == WARNING]
        if bad:
            rows.append(CheckResult(label, FAILED, "; ".join(bad)))
        elif warn:
            rows.append(CheckResult(label, WARNING, "; ".join(warn)))
        else:
            rows.append(CheckResult(label, PASSED, f"{len(got)} checks"))
    return rows


def _extras_row(files: Mapping[str, bytes], manifest: dict) -> CheckResult:
    found = sorted(rel for rel in files if PurePosixPath(rel).name in EXTRA_FILES or PurePosixPath(rel).parts[0] == "bin")
    keys = [k for k in EXTRA_MANIFEST_KEYS if k in manifest]
    if not found and not keys:
        return CheckResult(EXTRAS_CHECK, PASSED, "none")
    parts = []
    if found:
        parts.append("files: " + ", ".join(found[:8]) + (f" and {len(found) - 8} more" if len(found) > 8 else ""))
    if keys:
        parts.append("the manifest declares " + ", ".join(keys))
    return CheckResult(EXTRAS_CHECK, WARNING, "; ".join(parts) + ". These run or load on your machine when the plugin is used: read them before installing.")


def _script_row(files: Mapping[str, bytes]) -> CheckResult:
    scripts = shipped_code(files)
    if not scripts:
        return CheckResult(SCRIPTS_CHECK, PASSED, "this plugin ships no code")
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
            entry = next(e for e in entries if isinstance(e, dict) and e.get("name") == manifest.get("name"))
            if entry.get("source") != "./":
                shown = json.dumps(entry.get("source"))[:80]
                out.append(CheckResult(MARKETPLACE_CHECK, FAILED, f"the entry's source is {shown}, not this folder (\"./\"): it would install code from somewhere else"))
            else:
                out.append(CheckResult(MARKETPLACE_CHECK, PASSED))
    has_skill = any(PurePosixPath(rel).match("skills/*/SKILL.md") for rel in files)
    has_agent = any(PurePosixPath(rel).parent.as_posix() == "agents" and rel.endswith(".md") for rel in files)
    out.append(CheckResult(CONTENTS_CHECK, PASSED) if has_skill or has_agent else CheckResult(CONTENTS_CHECK, FAILED, "there is no skills/<name>/SKILL.md and no agents/<name>.md in it"))
    out += _component_rows(files)
    out.append(_extras_row(files, manifest))
    out.append(_script_row(files))
    return out
