"""Compose a Claude Code plugin from skills and agents that are already in the library.

No model is involved: a plugin is an assembly, and everything about it is decided by code. Each component is read through the
library, which proves its files against their SHA-256 manifest; the plugin's own check then runs every component through that
kind's own checks, so a damaged or failing component fails the plugin and is refused when it is kept. What the plugin can do on the machine (the tools its skills and agents grant, the
scripts it ships and what those can do) is computed from the files and shown before anything is kept or installed.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import PurePosixPath

from ..results import FAILED, CheckResult
from ..validate import validate_files
from ..validate.plugin import MANIFEST, MARKETPLACE, name_problem, shipped_code
from ..validate.static import JS_LANGS, PY_SUFFIXES, script_capabilities, split_tools
from .package import MAX_ENTRIES, LibraryError
from .risk import _front_matter
from .store import Library, content_hash

COMPONENT_KINDS = ("skill", "agent")
LEFT_OUT = {"spec.json"}  # the requester's own words stay in the library
MAX_DESCRIPTION = 1000
_SEMVER = re.compile(r"^(\d+)\.(\d+)\.(\d+)\Z")
MAX_AUTHOR = 100
DEFAULT_AUTHOR = "me"  # `claude plugin validate --strict` wants an author, and the local marketplace already names an owner
TOOL_NOTES = {
    "Bash": "run any shell command", "Edit": "change existing files", "Write": "create or overwrite files",
    "WebFetch": "fetch web pages", "WebSearch": "search the web",
}
READ_TOOLS = {"Read", "Grep", "Glob"}


class PluginError(LibraryError):
    """The plugin cannot be made from what was asked for."""


@dataclass(frozen=True)
class ComponentRef:
    kind: str  # "skill" or "agent"
    name: str
    version: int | None = None  # None: the latest


@dataclass
class Capabilities:
    tools: list[str]  # every tool any skill or agent in it grants
    by_component: list[dict]  # {"kind", "name", "tools", "scripts", "script_capabilities"} for each
    scripts: list[str]  # plugin-relative paths
    script_capabilities: list[str]  # network, run_commands, write_files: what the scripts use, by syntax only
    hooks: list[str] = field(default_factory=list)  # the components that declare hooks in their front matter
    mcp_servers: list[str] = field(default_factory=list)  # the components that declare MCP servers in their front matter
    notes: list[str] = field(default_factory=list)  # the same, in plain sentences


@dataclass
class PluginPlan:
    name: str
    version: str
    files: dict[str, bytes]
    capabilities: Capabilities
    components: list[dict]  # {"kind", "name", "version"} as they were read
    checks: list[CheckResult]

    @property
    def failed(self) -> bool:
        return any(c.status == FAILED for c in self.checks)


def _json(data: object) -> bytes:
    return (json.dumps(data, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def _inside(path: str) -> str:
    """A component file's path, refused if it could leave the plugin folder (the library gate already forbids this)."""
    parts = PurePosixPath(path).parts
    if not parts or ".." in parts or path.startswith("/") or "\\" in path:
        raise PluginError(f"'{path}' points outside the plugin folder.")
    return path


def _capabilities(kinds_files: list[tuple[ComponentRef, dict[str, bytes]]]) -> Capabilities:
    """What the plugin can do, by reading the files. A tool is named by what comes before a bracket (`Bash(git *)` is Bash); a tool
    SkillForge cannot describe is named, never called read-only; hooks, MCP servers and a bypassed approval in a component's front
    matter are listed; and code in ANY folder of a skill counts as shipped code, not only `scripts/`."""
    by: list[dict] = []
    all_tools: set[str] = set()
    all_scripts: list[str] = []
    all_caps: set[str] = set()
    unanalysed: list[str] = []
    granted_by: dict[str, list[str]] = {}
    hooks: list[str] = []
    servers: list[str] = []
    bypass: list[str] = []
    for ref, files in kinds_files:
        definition = "SKILL.md" if ref.kind == "skill" else "AGENT.md"
        key = "allowed-tools" if ref.kind == "skill" else "tools"
        meta = _front_matter(files, definition)[0]
        tools = sorted({entry.split("(")[0].strip() for entry in split_tools(meta.get(key)) if entry.split("(")[0].strip()})
        who = f"{ref.kind} {ref.name}"
        if meta.get("hooks"):
            hooks.append(who)
        if meta.get("mcpServers") or meta.get("mcp_servers"):
            servers.append(who)
        if str(meta.get("permissionMode", "")) == "bypassPermissions":
            bypass.append(who)
        scripts: list[str] = []
        caps: set[str] = set()
        if ref.kind == "skill":
            for rel, data in sorted(shipped_code(files).items()):
                path = f"skills/{ref.name}/{rel}"
                scripts.append(path)
                suffix = PurePosixPath(rel).suffix.lower()
                if suffix in PY_SUFFIXES or suffix in JS_LANGS:
                    found, dynamic = script_capabilities(rel, data)
                    caps |= found
                    if dynamic:
                        unanalysed.append(path)
                else:
                    unanalysed.append(path)
        by.append({"kind": ref.kind, "name": ref.name, "tools": tools, "scripts": scripts, "script_capabilities": sorted(caps)})
        all_tools |= set(tools)
        all_scripts += scripts
        all_caps |= caps
        for tool in tools:
            granted_by.setdefault(tool, []).append(ref.name)
    notes: list[str] = []
    for tool in sorted(all_tools):
        who = ", ".join(sorted(set(granted_by[tool])))
        if tool in TOOL_NOTES:
            notes.append(f"It can {TOOL_NOTES[tool]} ({tool}), from {who}.")
        elif tool not in READ_TOOLS:
            notes.append(f"It can use {tool}, which SkillForge cannot describe, from {who}: read what it does.")
    notes += [f"The {who} declares hooks: commands that run on this machine when it is used. Read them." for who in hooks]
    notes += [f"The {who} declares MCP servers: programs it starts or connects to. Read them." for who in servers]
    notes += [f"The {who} skips permission prompts (permissionMode: bypassPermissions)." for who in bypass]
    if all_scripts:
        n = len(all_scripts)
        used = ", ".join(sorted(c.replace("_", " ") for c in all_caps)) or "nothing risky by syntax"
        notes.append(f"It ships {n} script{'s that run' if n != 1 else ' that runs'} on this machine and can use: {used}.")
    if unanalysed:
        notes.append("These could not be analysed, so read them: " + ", ".join(unanalysed) + ".")
    if not notes:
        notes.append("It can only read and search files.")
    return Capabilities(sorted(all_tools), by, all_scripts, sorted(all_caps), hooks, servers, notes)


def _readme(name: str, description: str, version: str, plan: list[dict], caps: Capabilities) -> str:
    market = f"{name}-local"
    lines = [f"# {name.replace('-', ' ').title()}", "", description.strip(), "", f"Version {version}. Made with SkillForge from skills and agents in its library.", "",
             "## What is inside", ""]
    lines += [f"- {c['kind']} `{c['name']}` ({c['version']})" for c in plan]
    lines += ["", "## What it can do on your machine", "", "Worked out by code from the files, never chosen by a model.", ""]
    lines += [f"- {note}" for note in caps.notes]
    lines += [
        "", "## Add it to Claude Code", "", "Run these two commands, with the path of this folder:", "",
        "```", f'claude plugin marketplace add "<path to this folder>"', f"claude plugin install {name}@{market}", "```", "",
        "SkillForge never writes Claude's settings: adding the plugin is your command.", "",
    ]
    return "\n".join(lines)


def compose_plugin(
    library: Library, components: list[ComponentRef], *, name: str, description: str, version: str = "0.1.0", author: str = "",
) -> PluginPlan:
    """The files of a plugin made of `components`, with what it can do and every check. Nothing is written anywhere."""
    problem = name_problem(name)
    if problem:
        raise PluginError(f"'{name}' cannot be a plugin name: {problem}.")
    if not description.strip():
        raise PluginError("Say in a sentence what the plugin is for: the description is empty.")
    if len(description.strip()) > MAX_DESCRIPTION or len(author) > MAX_AUTHOR:
        raise PluginError(f"The description may be {MAX_DESCRIPTION} characters and the author {MAX_AUTHOR}.")
    for label, value in (("description", description), ("author", author)):
        try:
            value.encode("utf-8")
        except UnicodeEncodeError:
            raise PluginError(f"The {label} is not valid text: it contains a character that cannot be written to a file.") from None
    if not components:
        raise PluginError("A plugin needs at least one skill or agent.")
    seen: set[tuple[str, str]] = set()
    read: list[tuple[ComponentRef, dict[str, bytes]]] = []
    plan: list[dict] = []
    files: dict[str, bytes] = {}
    for ref in components:
        if ref.kind not in COMPONENT_KINDS:
            raise PluginError(f"A plugin can hold a skill or an agent, not '{ref.kind}'.")
        if (ref.kind, ref.name) in seen:
            raise PluginError(f"The {ref.kind} '{ref.name}' is listed twice.")
        seen.add((ref.kind, ref.name))
        found, component_files = library.for_kind(ref.kind).read(ref.name, ref.version)  # hash-verified, then gated
        plan.append({"kind": ref.kind, "name": ref.name, "version": found.tag})
        read.append((ref, component_files))
        if ref.kind == "skill":
            for rel, data in component_files.items():
                if rel not in LEFT_OUT:
                    files[f"skills/{ref.name}/{_inside(rel)}"] = data
        else:
            files[f"agents/{ref.name}.md"] = component_files["AGENT.md"]
    caps = _capabilities(read)
    owner = author.strip() or DEFAULT_AUTHOR
    manifest: dict = {"name": name, "version": version, "description": description.strip(), "author": {"name": owner}}
    market = {
        "name": f"{name}-local", "description": description.strip(), "owner": {"name": owner},
        "plugins": [{"name": name, "source": "./", "description": description.strip()}],
    }
    files[MANIFEST] = _json(manifest)
    files[MARKETPLACE] = _json(market)
    files["README.md"] = _readme(name, description, version, plan, caps).encode("utf-8")
    if len(files) > MAX_ENTRIES:
        raise PluginError(f"This plugin would hold {len(files)} files, and a plugin of more than {MAX_ENTRIES} files cannot be imported back.")
    ordered = dict(sorted(files.items()))
    return PluginPlan(name, version, ordered, caps, plan, validate_files(ordered, folder=name, kind="plugin"))


def compose_for_keeping(
    library: Library, components: list[ComponentRef], *, name: str, description: str, author: str = "",
) -> PluginPlan:
    """The plugin as it would be kept. Its version (0.1.<n>) is pinned by Claude Code, so it moves only when the content does:
    the latest kept version's number when nothing changed, the next one when something did."""
    problem = name_problem(name)
    if problem:
        raise PluginError(f"'{name}' cannot be a plugin name: {problem}.")
    plugins = library.for_kind("plugin")
    versions = plugins.versions(name)
    kwargs = dict(name=name, description=description, author=author)
    if not versions:
        return compose_plugin(library, components, version="0.1.0", **kwargs)
    latest, files = plugins.read(name)
    current = _manifest_version(files)
    same = compose_plugin(library, components, version=current, **kwargs)
    if content_hash(same.files) == latest.content_hash:
        return same
    highest = (0, 1, 0)
    for stored in versions:  # a rollback makes the latest version carry an OLD number: the next one must beat them all
        try:
            seen = _SEMVER.match(_manifest_version(plugins.read(name, stored.version)[1]))
        except LibraryError:
            continue  # a damaged old version cannot tell its number; the others still count
        if seen:
            highest = max(highest, tuple(int(part) for part in seen.groups()))
    return compose_plugin(library, components, version=f"{highest[0]}.{highest[1]}.{highest[2] + 1}", **kwargs)


def _manifest_version(files: dict[str, bytes]) -> str:
    try:
        current = str(json.loads(files[MANIFEST].decode("utf-8")).get("version", ""))
    except (KeyError, ValueError, AttributeError):
        current = ""
    return current if _SEMVER.match(current) else "0.1.0"
