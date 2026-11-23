"""The definition check of a plugin: `.claude-plugin/plugin.json` and what sits beside it.

It plays the part for a plugin that the `SKILL.md` check plays for a skill; every other static check still runs on the whole
folder. Nothing here runs anything. A plugin is only as safe as what it contains, so the check:
- runs every nested skill and agent through that kind's OWN checks (a plugin from outside, or a component stored before a check
  existed, must not carry a failing one in);
- lists what the code it ships can do (the shared script checks look at a top-level `scripts/` folder only, and a plugin keeps its
  code under `skills/<name>/`, in any folder);
- reads the MCP servers a plugin ships (`servers/<name>/`) with the MCP kind's own checks, and checks that `.mcp.json` starts only
  those, in the one form the composer writes; anything else it starts is shown and warned about, never trusted;
- warns about what a plugin should not carry without describing it (hooks, other MCP servers, settings, executables), because they
  run on the machine;
- refuses a marketplace entry that points anywhere but this folder.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from pathlib import PurePosixPath

from ..results import FAILED, PASSED, WARNING, CheckResult
from .static import JS_LANGS, MAX_NAME, PY_SUFFIXES, SLUG, script_capabilities, validate_files

MANIFEST = ".claude-plugin/plugin.json"
MARKETPLACE = ".claude-plugin/marketplace.json"
RESERVED_PREFIXES = ("claude-", "anthropic-")  # Claude Code refuses plugin names that start like this
MANIFEST_CHECK = "plugin.json exists and is a valid plugin manifest"
MARKETPLACE_CHECK = "the marketplace entry matches the manifest"
CONTENTS_CHECK = "the plugin contains a skill, an agent or an MCP server"
SCRIPTS_CHECK = "scripts shipped inside the plugin"
EXTRAS_CHECK = "no hooks, undescribed MCP servers, settings or executables"
MCP_CONFIG_CHECK = ".mcp.json starts only the MCP servers shipped inside the plugin"
CODE_SUFFIXES = {
    ".py", ".js", ".mjs", ".cjs", ".ts", ".sh", ".bash", ".zsh", ".ps1", ".bat", ".cmd", ".rb", ".php", ".pl", ".lua", ".java",
    ".go", ".rs", ".c", ".cc", ".cpp", ".cs", ".kt",
}
EXTRA_FILES = {"hooks.json", ".mcp.json", ".lsp.json", "settings.json", "settings.local.json"}  # what a plugin should not carry undescribed
MCP_CONFIG = ".mcp.json"
SERVERS_DIR = "servers"  # not "mcp/": no folder is ever called like the SDK package
PLUGIN_ROOT = "${CLAUDE_PLUGIN_ROOT}"  # Claude Code replaces it with the folder the plugin is installed in
START_COMMAND = "python"
_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*\Z")  # a userConfig key (a dashed one is refused by `claude plugin validate`) and an environment variable name
_OPTION_REF = re.compile(r"^\$\{user_config\.([A-Za-z_][A-Za-z0-9_]*)\}\Z")
_SHOWN_ARGS = 3
_SHOWN_CHARS = 40
EXTRA_MANIFEST_KEYS = ("hooks", "mcpServers", "lspServers")


def name_problem(name: object) -> str:
    """Why this cannot be a plugin name ("" when it can)."""
    if not isinstance(name, str) or not SLUG.match(name) or len(name) > MAX_NAME:
        return f"name must be lowercase letters, digits and hyphens, at most {MAX_NAME} characters"
    for prefix in RESERVED_PREFIXES:
        if name.startswith(prefix):
            return f"names that start with '{prefix}' are reserved, so Claude Code refuses them"
    return ""


def is_identifier(text: object) -> bool:
    """A name Claude Code accepts as a `userConfig` key, and a plain environment variable name."""
    return isinstance(text, str) and bool(_IDENTIFIER.match(text))


def user_config_key(server: str, variable: str) -> str:
    """The `userConfig` option that carries one environment variable to one server. The server's name comes first, so two servers
    that read the same variable ask for it separately and never share one value; a hyphen becomes an underscore because a key
    with a hyphen in it is refused."""
    return f"{server.replace('-', '_')}_{variable.lower()}"


def server_entry(name: str, variables: Mapping[str, str] | None = None) -> dict:
    """The `.mcp.json` entry that starts the server shipped as `servers/<name>/server.py`: `variables` maps each environment variable
    to the option that carries it. Values are never written, only references like `${user_config.KEY}`."""
    entry: dict = {"command": START_COMMAND, "args": [f"{PLUGIN_ROOT}/{SERVERS_DIR}/{name}/server.py"]}
    if variables:
        entry["env"] = {variable: f"${{user_config.{key}}}" for variable, key in variables.items()}
    return entry


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
    """(kind, name, that component's own files) for each skill, agent and MCP server inside a plugin folder."""
    skills: dict[str, dict[str, bytes]] = {}
    servers: dict[str, dict[str, bytes]] = {}
    agents: list[tuple[str, str, dict[str, bytes]]] = []
    for rel, data in files.items():
        parts = PurePosixPath(rel).parts
        if len(parts) >= 3 and parts[0] == "skills":
            skills.setdefault(parts[1], {})["/".join(parts[2:])] = data
        elif len(parts) >= 3 and parts[0] == SERVERS_DIR:
            servers.setdefault(parts[1], {})["/".join(parts[2:])] = data
        elif len(parts) == 2 and parts[0] == "agents" and rel.endswith(".md"):
            agents.append(("agent", PurePosixPath(rel).stem, {"AGENT.md": data}))
    return (
        [("skill", name, sub) for name, sub in sorted(skills.items())] + sorted(agents, key=lambda a: a[1])
        + [("mcp", name, sub) for name, sub in sorted(servers.items())]
    )


def server_names(files: Mapping[str, bytes]) -> list[str]:
    """The MCP servers the plugin ships: a folder under `servers/` that holds a `server.py`."""
    return [name for kind, name, sub in components(files) if kind == "mcp" and "server.py" in sub]


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


def _extras_row(files: Mapping[str, bytes], manifest: dict, described_config: bool = False) -> CheckResult:
    found = sorted(
        rel for rel in files
        if (PurePosixPath(rel).name in EXTRA_FILES or PurePosixPath(rel).parts[0] == "bin") and not (described_config and rel == MCP_CONFIG)
    )
    keys = [k for k in EXTRA_MANIFEST_KEYS if k in manifest]
    if not found and not keys:
        return CheckResult(EXTRAS_CHECK, PASSED, "none")
    parts = []
    if found:
        parts.append("files: " + ", ".join(found[:8]) + (f" and {len(found) - 8} more" if len(found) > 8 else ""))
    if keys:
        parts.append("the manifest declares " + ", ".join(keys))
    return CheckResult(EXTRAS_CHECK, WARNING, "; ".join(parts) + ". These run or load on your machine when the plugin is used: read them before installing.")


def _in_server(rel: str, servers: set[str]) -> bool:
    parts = PurePosixPath(rel).parts
    return len(parts) >= 3 and parts[0] == SERVERS_DIR and parts[1] in servers


def _script_row(files: Mapping[str, bytes]) -> CheckResult:
    servers = set(server_names(files))
    scripts = {rel: data for rel, data in shipped_code(files).items() if not _in_server(rel, servers)}  # a server is read as a server, above
    if not scripts:
        if servers:
            return CheckResult(SCRIPTS_CHECK, PASSED, "no scripts besides its MCP servers, which are read as servers (see their rows)")
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


def _shown(entry: object) -> str:
    """What an entry would start, for a person to read: the command and its first arguments, each cut short. A value in `env` is
    never shown, only the names."""
    if not isinstance(entry, dict):
        return json.dumps(entry)[:_SHOWN_CHARS]
    if "command" not in entry:
        return "an entry with " + (", ".join(sorted(str(k) for k in entry)[:4]) or "no keys")
    raw_args = entry.get("args")
    args = raw_args if isinstance(raw_args, list) else []
    words = [entry["command"], *args[:_SHOWN_ARGS]]
    shown = " ".join(str(w)[:_SHOWN_CHARS] for w in words)
    return shown + (" ..." if len(args) > _SHOWN_ARGS else "")


def _entry_problem(name: str, entry: object, servers: set[str], declared: set[str], undeclared: list[str]) -> str:
    """Why this `.mcp.json` entry is not the one the composer writes for a server shipped here ("" when it is). Fills `undeclared` with
    the options it uses that the manifest does not declare."""
    if not isinstance(entry, dict):
        return "is not an object"
    if name not in servers:
        return f"starts {_shown(entry)}, which is not a server shipped in this plugin"
    extra = sorted(set(entry) - {"command", "args", "env"})
    if extra:
        return f"has {', '.join(map(str, extra))}, which SkillForge does not read, so what it does is not known (it starts {_shown(entry)})"
    start = server_entry(name)
    if entry.get("command") != start["command"] or entry.get("args") != start["args"]:
        return f"starts {_shown(entry)} instead of the shipped servers/{name}/server.py"
    env = entry.get("env", {})
    if not isinstance(env, dict):
        return "has an env that is not an object"
    literal = []
    for variable, value in env.items():
        ref = _OPTION_REF.match(value) if isinstance(value, str) else None
        if ref is None:
            literal.append(str(variable)[:_SHOWN_CHARS])
        elif ref.group(1) not in declared:
            undeclared.append(ref.group(1))
    if literal:
        return "gives " + ", ".join(literal) + " a value written in the file (only ${user_config.X} references are expected, so no key is kept here)"
    return ""


def _mcp_config_row(files: Mapping[str, bytes], manifest: dict) -> tuple[CheckResult | None, bool]:
    """(the row, whether `.mcp.json` is the described one). It is described when every entry starts a server shipped in this plugin,
    in the one form the composer writes."""
    servers = server_names(files)
    if MCP_CONFIG not in files:
        if servers:
            return CheckResult(MCP_CONFIG_CHECK, WARNING, f"the plugin ships {', '.join(servers)} but has no {MCP_CONFIG}, so Claude Code will not start it"), False
        return None, False
    data, why = _json(files, MCP_CONFIG)
    if why:
        return CheckResult(MCP_CONFIG_CHECK, FAILED, why), False
    entries = data.get("mcpServers") if isinstance(data, dict) else None
    if not isinstance(entries, dict) or not entries:
        return CheckResult(MCP_CONFIG_CHECK, WARNING, f'{MCP_CONFIG} has no "mcpServers" entries in the form SkillForge reads, so what it starts is not described: read it'), False
    options = manifest.get("userConfig")
    declared = set(options) if isinstance(options, dict) else set()
    undeclared: list[str] = []
    problems = []
    for name, entry in entries.items():
        problem = _entry_problem(str(name), entry, set(servers), declared, undeclared)
        if problem:
            problems.append(f"'{str(name)[:_SHOWN_CHARS]}' {problem}")
    if undeclared:
        names = ", ".join(sorted(set(undeclared)))
        detail = f'{MCP_CONFIG} uses ${{user_config.X}} for {names}, which plugin.json does not declare under "userConfig": it cannot resolve on install'
        return CheckResult(MCP_CONFIG_CHECK, FAILED, detail), False
    if problems:
        return CheckResult(MCP_CONFIG_CHECK, WARNING, "; ".join(problems[:5]) + ". It runs on your machine when the plugin is enabled: read it before installing."), False
    return CheckResult(MCP_CONFIG_CHECK, PASSED, "starts " + ", ".join(sorted(map(str, entries)))), True


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
    options = manifest.get("userConfig")
    if options is not None and not isinstance(options, dict):
        problems.append("userConfig must be an object of options")
    elif isinstance(options, dict):
        bad = [str(k)[:_SHOWN_CHARS] for k in options if not is_identifier(k)]
        if bad:
            problems.append("userConfig keys may hold only letters, digits and underscores, and cannot start with a digit (Claude Code refuses others): " + ", ".join(bad[:3]))
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
    has_server = bool(server_names(files))
    out.append(
        CheckResult(CONTENTS_CHECK, PASSED) if has_skill or has_agent or has_server
        else CheckResult(CONTENTS_CHECK, FAILED, "there is no skills/<name>/SKILL.md, agents/<name>.md or servers/<name>/server.py in it")
    )
    out += _component_rows(files)
    config_row, described = _mcp_config_row(files, manifest)
    if config_row is not None:
        out.append(config_row)
    out.append(_extras_row(files, manifest, described))
    out.append(_script_row(files))
    return out
