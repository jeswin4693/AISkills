"""Compose a Claude Code plugin from skills, agents and MCP servers that are already in the library.

No model is involved: a plugin is an assembly, and everything about it is decided by code. Each component is read through the
library, which proves its files against their SHA-256 manifest; the plugin's own check then runs every component through that
kind's own checks, so a damaged or failing component fails the plugin and is refused when it is kept. What the plugin can do on the machine (the tools its skills and agents grant, the
scripts it ships and what those can do, the programs its MCP servers start and what they read) is computed from the files and shown before anything is kept or installed.

An MCP server is shipped as `servers/<name>/` and started by a root `.mcp.json`; every environment variable its code reads becomes a
`userConfig` option (sensitive, required) that the entry passes as a `${user_config.KEY}` reference. A value is never written.

A hook is never typed and never written by a model: it is chosen from the catalogue (`skillforge/hookcatalog`), shipped as the
catalogue's own script in `hooks/<id>.py` and listed in `hooks/hooks.json` in exec form. The only thing a person can add is a typed
option that the catalogue checks against a strict pattern.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import PurePosixPath

from ..hookcatalog.catalogue import HOOKS_FILE, CatalogueError, HookEntry, get_entry, hook_group, script_bytes
from ..results import FAILED, CheckResult
from ..validate import validate_files
from ..validate.mcp import analyze_server
from ..validate.plugin import (
    MANIFEST, MARKETPLACE, MCP_CONFIG, SERVERS_DIR, START_COMMAND, is_identifier, is_loader_variable, name_problem, server_entry, shipped_code,
    user_config_key,
)
from ..validate.static import JS_LANGS, PY_SUFFIXES, script_capabilities, split_tools
from .package import MAX_ENTRIES, LibraryError
from .risk import _front_matter
from .store import Library, content_hash

COMPONENT_KINDS = ("skill", "agent", "mcp", "hook")
KIND_ORDER = {kind: i for i, kind in enumerate(COMPONENT_KINDS)}
SERVER_POWERS = {
    "network": "reach the network", "write_files": "write or delete files", "read_files": "read files", "run_commands": "start other programs",
}
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
    kind: str  # "skill", "agent", "mcp" or "hook" (a hook is named by its id in the catalogue)
    name: str
    version: int | None = None  # None: the latest. A hook has none: the catalogue's script is the one used
    options: Mapping[str, Sequence[str]] | None = None  # a hook's typed options; no other kind has any


@dataclass
class Capabilities:
    tools: list[str]  # every tool any skill or agent in it grants
    by_component: list[dict]  # {"kind", "name", "tools", "scripts", "script_capabilities"} for each
    scripts: list[str]  # plugin-relative paths
    script_capabilities: list[str]  # network, run_commands, write_files: what the scripts use, by syntax only
    hooks: list[str] = field(default_factory=list)  # the components that declare hooks in their front matter
    mcp_servers: list[str] = field(default_factory=list)  # the components that declare MCP servers in their front matter
    notes: list[str] = field(default_factory=list)  # the same, in plain sentences
    servers: list[dict] = field(default_factory=list)  # each MCP server it starts: name, tools, capabilities, environment, environment_dynamic, dynamic, command
    hook_entries: list[dict] = field(default_factory=list)  # each catalogue hook it carries: id, title, summary, event, matcher, effect, sees, options, powers, command


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


def _server_summary(name: str, files: dict[str, bytes]) -> dict:
    """What an MCP server is and does, by reading its `server.py` the way the MCP checks do (by syntax; never run)."""
    try:
        facts = analyze_server(files["server.py"].decode("utf-8"))
    except (KeyError, UnicodeDecodeError, SyntaxError, ValueError, RecursionError) as exc:
        raise PluginError(f"The MCP server '{name}' cannot be read as a Python server ({type(exc).__name__}), so it was not used.") from None
    return {
        "name": name, "tools": [t.name for t in facts.tools], "capabilities": sorted(facts.capabilities),
        "environment": sorted(facts.env_names), "environment_dynamic": facts.env_dynamic, "dynamic": sorted(facts.dynamic),
        "command": f"{START_COMMAND} {SERVERS_DIR}/{name}/server.py", "requirements": "requirements.txt" in files,
    }


def _server_notes(server: dict) -> list[str]:
    """Plain sentences for one server. It is a program, so it is never called read-only, and what code can see is said to be a reading, not proof."""
    name, tools = server["name"], server["tools"]
    powers = ", ".join(SERVER_POWERS[c] if c in SERVER_POWERS else str(c) for c in server["capabilities"])
    first = (
        f"The MCP server '{name}' is a program that starts on this machine, with your permissions and outside any sandbox, whenever Claude Code loads the plugin. "
        f"It offers {len(tools)} tool{'s' if len(tools) != 1 else ''}" + (f" ({', '.join(tools)})" if tools else "") + ". "
        + (f"By reading its code (by syntax, not proof) it can: {powers}." if powers else "By reading its code (by syntax, not proof) it does not reach the network, start programs or write files.")
    )
    if server["dynamic"]:
        first += f" It also uses {', '.join(server['dynamic'])}, which the checks cannot follow, so what it does is not fully known."
    second = (
        f"The server '{name}' needs Python with the package in servers/{name}/requirements.txt: run pip install -r servers/{name}/requirements.txt."
        if server["requirements"] else f"The server '{name}' ships no requirements.txt, so what it needs installed is for you to find in its code."
    )
    names = server["environment"]
    if names:
        second += (
            f" It reads the environment variable{'s' if len(names) != 1 else ''} {', '.join(names)}: Claude Code asks you for "
            f"{'each' if len(names) != 1 else 'it'} when the plugin is enabled and stores {'them' if len(names) != 1 else 'it'} in its own credentials store "
            "(on Windows a file, .credentials.json, in your Claude folder: private to you, but not a vault)."
        )
    if server["environment_dynamic"]:
        second += " It also reads environment variables by a name that is not written in the code (or all of them), so it can read any variable Claude Code gives it."
    return [first, second]


def _hook_summary(entry: HookEntry, options: Mapping[str, Sequence[str]] | None) -> dict:
    """What one catalogue hook is, in the words the preview and the README use."""
    return {
        "id": entry.id, "title": entry.title, "summary": entry.summary, "event": entry.event, "matcher": entry.matcher, "effect": entry.effect,
        "sees": entry.sees, "options": {key: list(values) for key, values in (options or {}).items() if values}, "powers": sorted(entry.powers),
        "command": f"python -I {entry.shipped_path}", "revision": entry.revision,
    }


def _tools_in_words(matcher: str) -> str:
    tools = [t for t in matcher.split("|") if t]
    if not tools:
        return "any tool"
    return tools[0] if len(tools) == 1 else ", ".join(tools[:-1]) + " or " + tools[-1]


def _hook_notes(hooks: list[dict]) -> list[str]:
    """Plain sentences, one per hook, and one caution. A hook is a program that runs on the machine, so it is never called read-only."""
    notes: list[str] = []
    labels = {opt.key: opt.label for hook in hooks for opt in get_entry(hook["id"]).options}
    for hook in hooks:
        when = (
            f"is about to use {_tools_in_words(hook['matcher'])}" if hook["event"] == "PreToolUse"
            else f"has used {_tools_in_words(hook['matcher'])}" if hook["event"] == "PostToolUse" else f"reaches the event {hook['event']}"
        )
        text = (
            f"The hook '{hook['id']}' runs a program on this machine, with your permissions and outside any sandbox, every time Claude Code {when}. "
            f"{hook['summary']} It is handed {hook['sees']}. "
            + (
                "It can stop what Claude is about to do. If it cannot run, it stops the action instead of letting it through. " if hook["effect"] == "blocks"
                else "It only looks; it cannot stop anything. If it cannot run, nothing is logged and the action goes ahead. "
            )
            + ("By reading its script it can write files, and it does not reach the network or start programs." if hook["powers"]
               else "By reading its script it does not reach the network, start programs or write files.")
        )
        for key, values in hook["options"].items():
            text += f" {labels.get(key, key)} (your choice): {', '.join(values)}."
        notes.append(text)
    if hooks:
        notes.append(
            "A hook is a policy aid, not a security boundary: it matches names and text. A hook that guards something fails closed: if it cannot read what Claude Code sends it, "
            "or `python` is not on your PATH, it blocks the action it watches until that is fixed (the missing-python case needs Claude Code 2.1.295 or newer: older versions "
            "let the action through when the program cannot start, and tell nobody)."
        )
    return notes


def _hooks_file(selected: list[tuple[HookEntry, Mapping[str, Sequence[str]] | None]]) -> dict:
    hooks: dict[str, list[dict]] = {}
    for entry, options in selected:
        hooks.setdefault(entry.event, []).append(hook_group(entry, options))
    return {"hooks": hooks}


def _capabilities(kinds_files: list[tuple[ComponentRef, dict[str, bytes]]], hook_entries: list[dict] | None = None) -> Capabilities:
    """What the plugin can do, by reading the files. A tool is named by what comes before a bracket (`Bash(git *)` is Bash); a tool
    SkillForge cannot describe is named, never called read-only; hooks, MCP servers and a bypassed approval in a component's front
    matter are listed; code in ANY folder of a skill counts as shipped code, not only `scripts/`; and an MCP server the plugin ships is
    read as a server (its tools, what its code can do, the variables it reads)."""
    by: list[dict] = []
    all_tools: set[str] = set()
    all_scripts: list[str] = []
    all_caps: set[str] = set()
    unanalysed: list[str] = []
    granted_by: dict[str, list[str]] = {}
    hooks: list[str] = []
    servers: list[str] = []
    bypass: list[str] = []
    shipped_servers: list[dict] = []
    for ref, files in kinds_files:
        if ref.kind == "mcp":
            shipped_servers.append(_server_summary(ref.name, files))
            by.append({"kind": "mcp", "name": ref.name, "tools": [], "scripts": [], "script_capabilities": []})
            continue
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
    for server in shipped_servers:
        notes += _server_notes(server)
    notes += _hook_notes(hook_entries or [])
    if all_scripts:
        n = len(all_scripts)
        used = ", ".join(sorted(c.replace("_", " ") for c in all_caps)) or "nothing risky by syntax"
        notes.append(f"It ships {n} script{'s that run' if n != 1 else ' that runs'} on this machine and can use: {used}.")
    if unanalysed:
        notes.append("These could not be analysed, so read them: " + ", ".join(unanalysed) + ".")
    if not notes:
        notes.append("It can only read and search files.")
    return Capabilities(sorted(all_tools), by, all_scripts, sorted(all_caps), hooks, servers, notes, shipped_servers, hook_entries or [])


def _server_config(servers: list[dict]) -> tuple[dict, dict]:
    """(the `.mcp.json` entries, the `userConfig` options) for the servers a plugin ships. Each variable a server reads gets one option
    of its own, so two servers never share a value; only a reference to the option is written, never a value. A variable that is not
    a plain name, or two that would share an option, refuse the plugin."""
    entries: dict[str, dict] = {}
    options: dict[str, dict] = {}
    owner: dict[str, tuple[str, str]] = {}  # option key -> (server, variable) that already uses it
    for server in servers:
        name, wanted = server["name"], {}
        for variable in server["environment"]:
            key = user_config_key(name, variable)
            if not is_identifier(variable):
                raise PluginError(f"The MCP server '{name}' reads the environment variable '{variable}', which is not a plain name (letters, digits and underscores), so it cannot be given as a plugin option.")
            if is_loader_variable(variable):
                raise PluginError(
                    f"The MCP server '{name}' reads {variable}, a variable that changes how a program is found or loaded: a plugin option must never set it, "
                    "so this server cannot go into a plugin as it is."
                )
            if not is_identifier(key):
                raise PluginError(
                    f"The MCP server '{name}' cannot be given an option for {variable}: its name makes the option key '{key}', which Claude Code refuses "
                    "(a key starts with a letter or an underscore). Give the server a name that starts with a letter."
                )
            if key in owner:
                other_server, other_variable = owner[key]
                raise PluginError(
                    f"The MCP servers '{other_server}' (variable {other_variable}) and '{name}' (variable {variable}) would share the option '{key}': "
                    "rename one of the variables or one of the servers."
                )
            owner[key] = (name, variable)
            wanted[variable] = key
            options[key] = {
                "type": "string", "title": f"{variable} for {name}", "sensitive": True, "required": True,
                "description": f"Read by the MCP server {name}. Claude Code asks for it when the plugin is enabled and stores it in its own credentials store.",
            }
        entries[name] = server_entry(name, wanted)
    return entries, options


def _readme(name: str, description: str, version: str, plan: list[dict], caps: Capabilities) -> str:
    market = f"{name}-local"
    lines = [f"# {name.replace('-', ' ').title()}", "", description.strip(), "", f"Version {version}. Made with SkillForge from skills and agents in its library.", "",
             "## What is inside", ""]
    lines += [f"- {'MCP server' if c['kind'] == 'mcp' else c['kind']} `{c['name']}` ({c['version']})" for c in plan]
    lines += ["", "## What it can do on your machine", "", "Worked out by code from the files, never chosen by a model.", ""]
    lines += [f"- {note}" for note in caps.notes]
    lines += [
        "", "## Add it to Claude Code", "", "Run these two commands, with the path of this folder:", "",
        "```", f'claude plugin marketplace add "<path to this folder>"', f"claude plugin install {name}@{market}", "```", "",
        "SkillForge never writes Claude's settings: adding the plugin is your command.", "",
    ]
    if caps.hook_entries:
        lines += [
            "## Hooks", "", "A hook runs on your machine every time its event happens, with your permissions. Each one here is a fixed script from "
            "SkillForge's catalogue, shipped unchanged in `hooks/`; none was written by a model. They start with `python`, which must be on your PATH: a hook that guards "
            "something fails closed (`onFailure: block`), so without Python it blocks the action it watches until you install Python or remove the plugin.", "",
        ]
        for hook in caps.hook_entries:
            chosen = "".join(f" {key}: {', '.join(values)}." for key, values in hook["options"].items())
            lines.append(f"- hook `{hook['id']}`: runs on {hook['event']}" + (f", tools {hook['matcher']}" if hook["matcher"] else ", every tool") + f". {hook['summary']}{chosen}")
        lines.append("")
    if caps.servers:
        options = [(s["name"], v, user_config_key(s["name"], v)) for s in caps.servers for v in s["environment"]]
        lines += ["## Before the MCP servers can start", "", "Each server runs with `python`."]
        needing = [s["name"] for s in caps.servers if s["requirements"]]
        if needing:
            lines += ["It needs its package, once, from this folder:", "", "```"]
            lines += [f"pip install -r servers/{name}/requirements.txt" for name in needing]
            lines += ["```"]
        lines += [""]
        if options:
            lines += [
                "Claude Code asks for these options when the plugin is enabled and stores them in its own credentials store (marked sensitive). Without the dialog, give each one to the install command:", "",
                "```", f"claude plugin install {name}@{market} " + " ".join(f"--config {key}=<value>" for _, _, key in options), "```", "",
            ]
            lines += [f"- `{key}`: the environment variable `{variable}` of `{server}`" for server, variable, key in options]
            lines += ["", "No value is written in any file of this plugin.", ""]
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
        raise PluginError("A plugin needs at least one skill, agent or MCP server.")
    seen: set[tuple[str, str]] = set()
    read: list[tuple[ComponentRef, dict[str, bytes]]] = []
    plan: list[dict] = []
    files: dict[str, bytes] = {}
    chosen_hooks: list[tuple[HookEntry, Mapping[str, Sequence[str]] | None]] = []
    # By kind, then by name, whatever order the parts were clicked in: the same parts make the same plugin (and so no new version).
    for ref in sorted(components, key=lambda r: (KIND_ORDER.get(r.kind, len(KIND_ORDER)), r.name)):
        if ref.kind not in COMPONENT_KINDS:
            raise PluginError(f"A plugin can hold a skill, an agent or an MCP server, or a hook, not '{ref.kind}'.")
        if (ref.kind, ref.name) in seen:
            raise PluginError(f"The {ref.kind} '{ref.name}' is listed twice.")
        seen.add((ref.kind, ref.name))
        if ref.options and ref.kind != "hook":
            raise PluginError(f"The {ref.kind} '{ref.name}' has options, but only a hook can have them.")
        if ref.kind == "hook":
            if ref.version is not None:
                raise PluginError(f"The hook '{ref.name}' has no version to choose: it comes from the catalogue.")
            try:
                entry = get_entry(ref.name)
                hook_group(entry, ref.options)  # refuses a bad option
            except CatalogueError as exc:
                raise PluginError(str(exc)) from None
            chosen_hooks.append((entry, ref.options))
            files[entry.shipped_path] = script_bytes(entry)
            plan.append({"kind": "hook", "name": entry.id, "version": f"r{entry.revision}"})
            continue
        found, component_files = library.for_kind(ref.kind).read(ref.name, ref.version)  # hash-verified, then gated
        plan.append({"kind": ref.kind, "name": ref.name, "version": found.tag})
        read.append((ref, component_files))
        if ref.kind == "skill":
            for rel, data in component_files.items():
                if rel not in LEFT_OUT:
                    files[f"skills/{ref.name}/{_inside(rel)}"] = data
        elif ref.kind == "mcp":
            for rel, data in component_files.items():
                if rel not in LEFT_OUT:
                    files[f"{SERVERS_DIR}/{ref.name}/{_inside(rel)}"] = data
        else:
            files[f"agents/{ref.name}.md"] = component_files["AGENT.md"]
    caps = _capabilities(read, [_hook_summary(entry, options) for entry, options in chosen_hooks])
    if chosen_hooks:
        files[HOOKS_FILE] = _json(_hooks_file(chosen_hooks))
    entries, options = _server_config(caps.servers)
    owner = author.strip() or DEFAULT_AUTHOR
    manifest: dict = {"name": name, "version": version, "description": description.strip(), "author": {"name": owner}}
    if options:
        manifest["userConfig"] = options
    if entries:
        files[MCP_CONFIG] = _json({"mcpServers": entries})
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
