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
from collections.abc import Set as AbstractSet
from pathlib import PurePosixPath
from urllib.parse import urlsplit

import yaml

from ..hookcatalog.catalogue import HOOKS_FILE, accepts, entry_for_args, parse_args
from ..results import FAILED, PASSED, WARNING, CheckResult
from .mcp import analyze_server
from .static import JS_LANGS, MAX_NAME, PY_SUFFIXES, SLUG, script_capabilities, validate_files

MANIFEST = ".claude-plugin/plugin.json"
MARKETPLACE = ".claude-plugin/marketplace.json"
RESERVED_PREFIXES = ("claude-", "anthropic-")  # Claude Code refuses plugin names that start like this
MANIFEST_CHECK = "plugin.json exists and is a valid plugin manifest"
MARKETPLACE_CHECK = "the marketplace entry matches the manifest"
CONTENTS_CHECK = "the plugin contains a skill, an agent, an MCP server or a hook"
HOOKS_CHECK = "hooks/hooks.json runs only catalogue hooks, unchanged"
SCRIPTS_CHECK = "scripts shipped inside the plugin"
EXTRAS_CHECK = "no hooks, undescribed MCP servers, settings or executables"
MCP_CONFIG_CHECK = ".mcp.json starts only the MCP servers shipped inside the plugin"
ALIAS_CHECK = "no file name that Windows or macOS would read as another file"
CODE_SUFFIXES = {
    ".py", ".pyw", ".pyz", ".js", ".mjs", ".cjs", ".ts", ".sh", ".bash", ".zsh", ".ps1", ".bat", ".cmd", ".rb", ".php", ".pl", ".lua", ".java",
    ".go", ".rs", ".c", ".cc", ".cpp", ".cs", ".kt",
}
EXTRA_FILES = {"hooks.json", ".mcp.json", ".lsp.json", "settings.json", "settings.local.json", "monitors.json"}  # what a plugin should not carry undescribed
EXTRA_DIRS = ("bin", "commands", "monitors", "workflows")  # Claude Code runs or loads what is here: put on the Bash PATH, markdown that can run shell lines, background shell commands, scripts
SPECIAL_FILES = (".claude-plugin/plugin.json", ".claude-plugin/marketplace.json", ".mcp.json", HOOKS_FILE, "monitors/monitors.json")
SPECIAL_DIRS = (".claude-plugin", "skills", "agents", "servers", "hooks", "bin", "commands", "monitors", "workflows", "output-styles", "themes")
LOADER_PREFIXES = ("PYTHON", "LD_", "DYLD_", "NODE_")  # variables that change how a program is loaded or searched
LOADER_NAMES = frozenset({
    "PATH", "PATHEXT", "IFS", "ENV", "SHELL", "COMSPEC", "PSMODULEPATH", "CLASSPATH", "BASH_ENV", "PERL5LIB", "PERL5OPT", "RUBYOPT", "RUBYLIB",
    "JAVA_TOOL_OPTIONS", "_JAVA_OPTIONS",
})
MCP_CONFIG = ".mcp.json"
SERVERS_DIR = "servers"  # not "mcp/": no folder is ever called like the SDK package
PLUGIN_ROOT = "${CLAUDE_PLUGIN_ROOT}"  # Claude Code replaces it with the folder the plugin is installed in
START_COMMAND = "python"
_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*\Z")  # a userConfig key (a dashed one is refused by `claude plugin validate`) and an environment variable name
_OPTION_REF = re.compile(r"^\$\{user_config\.([A-Za-z_][A-Za-z0-9_]*)\}\Z")
_SHOWN_ARGS = 8  # how many arguments of a command are shown
_SHOWN_CHARS = 40  # how much of a name is shown
_ARG_CHARS = 160  # how much of one argument is shown
EXTRA_MANIFEST_KEYS = ("hooks", "mcpServers", "lspServers", "channels", "commands", "workflows", "experimental")  # keys that point at, or hold, something that runs
_SECRET_FLAG = re.compile(r"(--?[A-Za-z0-9_-]*(?:token|key|secret|passw|pwd|auth|credential)[A-Za-z0-9_-]*=)\S+", re.I)
_SECRET_QUERY = re.compile(r"([?&][^=&\s]*(?:token|key|secret|passw|pwd|auth)[^=&\s]*=)[^&\s]+", re.I)
_SECRET_TOKEN = re.compile(r"\b((?:gh[pousr]_|github_pat_|sk-|xox[abprs]-|AKIA|AIza|glpat-|npm_)[A-Za-z0-9_\-]{8,})")
_LONG_OPAQUE = re.compile(r"[A-Za-z0-9+/_\-=]{40,}")
_BANG_LINE = re.compile(r"(?m)(?:^|\s)!`([^`\n]+)`|^```!")  # a skill or command line that runs a shell command when it loads


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


def is_loader_variable(name: str) -> bool:
    """A variable that changes how a program is found or loaded (PATH, PYTHONPATH, LD_PRELOAD, NODE_OPTIONS ...). A server must never be
    handed one through an option: setting it makes the server, or what it starts, run something else."""
    upper = name.upper()
    return upper in LOADER_NAMES or upper.startswith(LOADER_PREFIXES)


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
    except RecursionError:
        return None, f"{path} is nested too deeply to read"  # a hostile file must be a failed row, not a crash
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


def _front_meta(data: bytes) -> dict:
    """The front matter of a skill or agent file as a dict (empty when there is none or it cannot be read)."""
    text = data.decode("utf-8", "replace").replace("\r\n", "\n")
    match = re.match(r"---\n(.*?)\n---\n", text, re.DOTALL)
    if not match:
        return {}
    try:
        meta = yaml.safe_load(match.group(1))
    except (yaml.YAMLError, RecursionError):
        return {}
    return meta if isinstance(meta, dict) else {}


def declared_commands(value: object, depth: int = 0) -> list[str]:
    """Every command a hooks, mcpServers, lspServers or monitors structure would start, as shown to a person (nested lists and maps are walked)."""
    found: list[str] = []
    if depth > 8:
        return found
    if isinstance(value, dict):
        if "command" in value or "url" in value:
            found.append(shown_command(value))
        else:
            for item in value.values():
                found += declared_commands(item, depth + 1)
    elif isinstance(value, list):
        for item in value:
            found += declared_commands(item, depth + 1)
    return found


def _extras_row(files: Mapping[str, bytes], manifest: dict, described: frozenset[str] = frozenset()) -> CheckResult:
    """What a plugin carries that runs or loads something and that no other row describes. `described` holds the root files other rows describe
    in full (`.mcp.json`, `hooks/hooks.json`). Commands declared in the manifest or in a skill's or agent's front matter are SHOWN, not just
    counted, and a skill or command file with a line that runs a shell command when it loads is named."""
    special_names = {n.casefold() for n in EXTRA_FILES}
    found = sorted(
        rel for rel in files
        if rel not in described and (PurePosixPath(rel).name.casefold() in special_names or PurePosixPath(rel).parts[0].casefold() in EXTRA_DIRS)
    )
    parts: list[str] = []
    if found:
        parts.append("files: " + ", ".join(found[:8]) + (f" and {len(found) - 8} more" if len(found) > 8 else ""))
    for key in EXTRA_MANIFEST_KEYS:
        if key not in manifest:
            continue
        value = manifest[key]
        if key == "experimental":
            value = value.get("monitors") if isinstance(value, dict) else None
            key = "experimental.monitors"
            if value is None:
                continue
        commands = declared_commands(value)
        if commands:
            parts.append(f"the manifest's {key} would start " + "; ".join(commands[:6]))
        else:
            parts.append(f"the manifest declares {key}" + (f" ({', '.join(str(v)[:60] for v in value[:3])})" if isinstance(value, list) and all(isinstance(v, str) for v in value) else ""))
    for kind, name, sub in components(files):
        if kind in ("skill", "agent"):
            definition = "SKILL.md" if kind == "skill" else "AGENT.md"
            meta = _front_meta(sub.get(definition, b""))
            for field_name in ("hooks", "mcpServers", "mcp_servers"):
                if meta.get(field_name):
                    commands = declared_commands(meta[field_name]) or ["something SkillForge cannot read"]
                    parts.append(f"the {kind} '{name}' declares {field_name}: " + "; ".join(commands[:4]))
        if kind == "skill":
            bang = [m.group(1) or "a ```! block" for m in _BANG_LINE.finditer(sub.get("SKILL.md", b"").decode("utf-8", "replace"))]
            if bang:
                parts.append(f"the skill '{name}' runs shell commands when it loads (the ! syntax): " + "; ".join(safe_text(c, 80) for c in bang[:3]))
    if not parts:
        return CheckResult(EXTRAS_CHECK, PASSED, "none")
    return CheckResult(EXTRAS_CHECK, WARNING, "; ".join(parts) + ". These run or load on your machine when the plugin is used: read them before installing.")


def _in_server(rel: str, servers: set[str]) -> bool:
    parts = PurePosixPath(rel).parts
    return len(parts) >= 3 and parts[0] == SERVERS_DIR and parts[1] in servers


def _script_row(files: Mapping[str, bytes], catalogue_scripts: AbstractSet[str] = frozenset()) -> CheckResult:
    servers = set(server_names(files))
    scripts = {  # a server is read as a server, and a catalogue hook's script as the catalogue's own, on their rows
        rel: data for rel, data in shipped_code(files).items() if not _in_server(rel, servers) and rel not in catalogue_scripts
    }
    if not scripts:
        if servers or catalogue_scripts:
            return CheckResult(SCRIPTS_CHECK, PASSED, "no scripts besides its MCP servers and catalogue hooks, which are read on their own rows")
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


def _mask(text: str) -> str:
    """Keys, tokens and long opaque strings in a command are not repeated back: a report must never be where a secret leaks."""
    text = _SECRET_FLAG.sub(r"\1…", text)
    text = _SECRET_QUERY.sub(r"\1…", text)
    text = _SECRET_TOKEN.sub(lambda m: m.group(1)[: m.group(1).index("_") + 1 if "_" in m.group(1)[:8] else 3] + "…", text)
    return _LONG_OPAQUE.sub("…", text)


def safe_text(text: str, limit: int = _ARG_CHARS) -> str:
    """Text for a person to read: control characters written out (\\x1b), a long run of blanks named (so it cannot hide a tail behind it),
    keys masked, and a marker when it was cut."""
    out = []
    for ch in text:
        if ch == "\n":
            out.append("\\n")
        elif ch == "\r":
            out.append("\\r")
        elif ch == "\t":
            out.append("\\t")
        elif ord(ch) < 32 or ord(ch) == 127:
            out.append(f"\\x{ord(ch):02x}")
        else:
            out.append(ch)
    shown = re.sub(r" {4,}", lambda m: f" [{len(m.group())} spaces] ", "".join(out))
    shown = _mask(shown)
    return shown if len(shown) <= limit else shown[:limit] + "…"


def shown_command(entry: object) -> str:
    """What an entry would start, for a person to read: the command and its arguments (up to eight, each cut with a visible marker). A value in
    `env` is never shown, only the names; a remote server shows its host only; keys and tokens are masked; control characters and runs of blanks
    are made visible."""
    if not isinstance(entry, dict):
        return safe_text(json.dumps(entry), _SHOWN_CHARS)
    if "command" not in entry:
        if isinstance(entry.get("url"), str):
            try:
                host = urlsplit(entry["url"]).hostname or "an address that cannot be read"
            except ValueError:
                host = "an address that cannot be read"
            return f"a remote server at {safe_text(host, 80)}"
        return "an entry with " + (", ".join(safe_text(str(k), _SHOWN_CHARS) for k in sorted(entry, key=str)[:4]) or "no keys")
    raw_args = entry.get("args")
    args = raw_args if isinstance(raw_args, list) else []
    words = [safe_text(str(entry["command"]), 80), *(safe_text(str(a)) for a in args[:_SHOWN_ARGS])]
    return " ".join(words) + (f" …({len(args) - _SHOWN_ARGS} more)" if len(args) > _SHOWN_ARGS else "")


def _server_reads(files: Mapping[str, bytes]) -> dict[str, set[str]]:
    """Each shipped server and the environment variables its code reads by a name written in it (none when it cannot be read)."""
    reads: dict[str, set[str]] = {}
    for kind, name, sub in components(files):
        if kind == "mcp" and "server.py" in sub:
            try:
                reads[name] = set(analyze_server(sub["server.py"].decode("utf-8")).env_names)
            except (UnicodeDecodeError, SyntaxError, ValueError, RecursionError):
                reads[name] = set()
    return reads


def _entry_problem(name: str, entry: object, servers: Mapping[str, set[str]], options: Mapping[str, object], undeclared: list[str]) -> str:
    """Why this `.mcp.json` entry is not the one the composer writes for a server shipped here ("" when it is). Fills `undeclared` with
    the options it uses that the manifest does not declare. `servers` maps each shipped server to the variables its code reads: an entry
    may pass only those, and never a loader variable (`PYTHONPATH`, `LD_PRELOAD`). Each variable must take its value from the option the
    composer makes for that server and variable (so a secret typed for one server never reaches another), and that option must ask for a
    required secret with no default. `options` is the manifest's `userConfig`."""
    if not isinstance(entry, dict):
        return "is not an object"
    if name not in servers:
        return f"starts {shown_command(entry)}, which is not a server shipped in this plugin"
    extra = sorted(set(entry) - {"command", "args", "env"})
    if extra:
        return f"has {', '.join(map(str, extra))}, which SkillForge does not read, so what it does is not known (it starts {shown_command(entry)})"
    start = server_entry(name)
    if entry.get("command") != start["command"] or entry.get("args") != start["args"]:
        return f"starts {shown_command(entry)} instead of the shipped servers/{name}/server.py"
    env = entry.get("env", {})
    if not isinstance(env, dict):
        return "has an env that is not an object"
    literal: list[str] = []
    foreign: list[str] = []
    weak: list[str] = []
    for variable, value in env.items():
        ref = _OPTION_REF.match(value) if isinstance(value, str) else None
        if ref is None:
            literal.append(str(variable)[:_SHOWN_CHARS])
            continue
        key = ref.group(1)
        if key not in options:
            undeclared.append(key)
        elif key != user_config_key(name, str(variable)):
            foreign.append(f"{str(variable)[:_SHOWN_CHARS]} (it takes its value from the option {key}, which is another server's or another variable's)")
        else:
            body = options[key]
            body = body if isinstance(body, dict) else {}
            lacking = [what for what, ok in (("sensitive", body.get("sensitive") is True), ("required", body.get("required") is True), ("without a default", "default" not in body)) if not ok]
            if lacking:
                weak.append(f"the option {key} is not a required secret without a default (it is missing: {', '.join(lacking)})")
    if literal:
        return "gives " + ", ".join(literal) + " a value written in the file (only ${user_config.X} references are expected, so no key is kept here)"
    unread = sorted(str(v)[:_SHOWN_CHARS] for v in env if v not in servers[name])
    if unread:
        return "passes " + ", ".join(unread) + ", which the server's code does not read"
    loader = sorted(str(v)[:_SHOWN_CHARS] for v in env if is_loader_variable(str(v)))
    if loader:
        return "passes " + ", ".join(loader) + ", a variable that changes how a program is found or loaded: an option must never set it"
    if foreign:
        return "gives " + ", ".join(foreign)
    if weak:
        return "; ".join(weak)
    return ""


def _group_problems(event: str, group: object, files: Mapping[str, bytes], found: list[str], script_ok: set[str]) -> list[str]:
    """Why this matcher group of `hooks.json` is not exactly what the composer writes for one catalogue hook (an empty list when it is).
    Adds the hook's id to `found` when it is, and its script's path to `script_ok` whenever that script is the catalogue's."""
    where = event[:40]
    if not isinstance(group, dict):
        return [f"{where} holds an entry that is not an object"]
    if set(group) - {"matcher", "hooks"}:
        return [f"{where} has {', '.join(sorted(map(str, set(group) - {'matcher', 'hooks'})))[:60]}, which SkillForge does not read"]
    hooks = group.get("hooks")
    if not isinstance(hooks, list) or len(hooks) != 1 or not isinstance(hooks[0], dict):
        return [f"{where} has a group that does not hold exactly one hook"]
    hook = hooks[0]
    entry = entry_for_args(hook.get("args"))
    if entry is None:
        return [f"{where} runs {shown_command(hook)} (type {str(hook.get('type'))[:20]!r}), which is not a catalogue hook"]
    problems: list[str] = []
    data = files.get(entry.shipped_path)
    if data is None:
        problems.append(f"'{entry.id}' is missing its script {entry.shipped_path}")
    elif not accepts(entry, data):
        problems.append(f"{entry.shipped_path} is not the catalogue's script for '{entry.id}': what it does is not what the catalogue vouches for")
    else:
        script_ok.add(entry.shipped_path)
    written = {"type", "command", "args", "timeout"} | ({"onFailure"} if entry.on_failure else set())
    odd_keys = sorted(map(str, set(hook) ^ written))
    if odd_keys:
        problems.append(f"'{entry.id}' does not have exactly the keys the catalogue writes ({', '.join(sorted(written))}): {', '.join(odd_keys)[:60]}")
    if "onFailure" in hook and hook.get("onFailure") != entry.on_failure:
        problems.append(
            f"'{entry.id}' has onFailure {str(hook.get('onFailure'))[:20]!r}, the catalogue's is {entry.on_failure!r}: "
            + ("a guard that cannot run would let the action through" if entry.on_failure else "a hook that only looks must not stop the session when it cannot run")
        )
    if hook.get("type") != "command" or hook.get("command") != "python":
        problems.append(f"'{entry.id}' runs {shown_command(hook)} (type {str(hook.get('type'))[:20]!r}) instead of python")
    if event != entry.event:
        problems.append(f"'{entry.id}' is under {where}, the catalogue runs it on {entry.event}")
    if group.get("matcher", "") != entry.matcher:
        problems.append(f"'{entry.id}' has the matcher {str(group.get('matcher', ''))[:40]!r}, the catalogue's is {entry.matcher!r}")
    if "timeout" in hook and (type(hook["timeout"]) is not int or hook["timeout"] != entry.timeout):  # 10.0 and true are not the integer 10
        problems.append(f"'{entry.id}' has the timeout {str(hook.get('timeout'))[:10]}, the catalogue's is {entry.timeout}")
    if parse_args(entry, hook.get("args")) is None:
        problems.append(f"'{entry.id}' has arguments the catalogue does not write: {shown_command(hook)}")
    if not problems:
        found.append(entry.id)
    return problems


def _hooks_row(files: Mapping[str, bytes]) -> tuple[CheckResult | None, bool, set[str], int]:
    """(the row, whether `hooks/hooks.json` is the described one, the paths of shipped scripts that are the catalogue's own, how many
    hooks are exactly catalogue hooks). It is described when every hook in it is a catalogue hook with exactly the event, matcher,
    timeout, command and arguments the catalogue writes, and its script is the catalogue's. Anything else is shown to the person and
    never trusted."""
    if HOOKS_FILE not in files:
        return None, False, set(), 0
    data, why = _json(files, HOOKS_FILE)
    if why:
        return CheckResult(HOOKS_CHECK, FAILED, why), False, set(), 0
    events = data.get("hooks") if isinstance(data, dict) else None
    if not isinstance(events, dict) or not any(isinstance(groups, list) and groups for groups in events.values()):
        detail = f'{HOOKS_FILE} has no hooks in the form SkillForge reads (a top-level "hooks" object of events), so what it runs is not described: read it'
        return CheckResult(HOOKS_CHECK, WARNING, detail), False, set(), 0
    problems: list[str] = []
    found: list[str] = []
    script_ok: set[str] = set()
    for event, groups in events.items():
        if not isinstance(groups, list):
            problems.append(f"{str(event)[:40]} is not a list of groups")
            continue
        for group in groups:
            problems += _group_problems(str(event), group, files, found, script_ok)
    stray = sorted(map(str, set(data) - {"hooks", "description"})) if isinstance(data, dict) else []
    if stray:
        problems.append(f"{HOOKS_FILE} has {', '.join(stray)[:60]}, which SkillForge does not read")
    loose = sorted(rel for rel in files if rel.startswith("hooks/") and rel != HOOKS_FILE and rel not in script_ok)
    if loose:  # a module planted beside a script can replace one it imports; the scripts run in isolated mode, but nothing else beside them is expected
        problems.append(f"{', '.join(loose[:5])} sits beside the hook scripts and is not one of them: a file there can be imported instead of a standard module, or run by another hook")
    if problems:
        detail = "; ".join(problems[:5]) + ". A hook runs on your machine with your permissions when the plugin is enabled: read it before installing."
        return CheckResult(HOOKS_CHECK, WARNING, detail), False, script_ok, len(found)
    detail = "runs " + ", ".join(found) + f" from the catalogue, unchanged (this row covers only {HOOKS_FILE}: hooks declared anywhere else are listed on the extras row)"
    return CheckResult(HOOKS_CHECK, PASSED, detail), True, script_ok, len(found)


def _mcp_config_row(files: Mapping[str, bytes], manifest: dict) -> tuple[CheckResult | None, bool]:
    """(the row, whether `.mcp.json` is the described one). It is described when every entry starts a server shipped in this plugin,
    in the one form the composer writes."""
    servers = _server_reads(files)
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
    declared = options if isinstance(options, dict) else {}
    undeclared: list[str] = []
    problems = []
    stray = sorted(map(str, set(data) - {"mcpServers"})) if isinstance(data, dict) else []
    if stray:  # the plugin is only described by what it says under mcpServers; anything beside it may be read by Claude Code as more servers
        problems.append(f"{MCP_CONFIG} has {', '.join(s[:_SHOWN_CHARS] for s in stray[:4])} beside mcpServers, which SkillForge does not read")
    for name, entry in entries.items():
        problem = _entry_problem(str(name), entry, servers, declared, undeclared)
        if problem:
            problems.append(f"'{str(name)[:_SHOWN_CHARS]}' {problem}")
    if undeclared:
        names = ", ".join(sorted(set(undeclared)))
        detail = f'{MCP_CONFIG} uses ${{user_config.X}} for {names}, which plugin.json does not declare under "userConfig": it cannot resolve on install'
        return CheckResult(MCP_CONFIG_CHECK, FAILED, detail), False
    if problems:
        return CheckResult(MCP_CONFIG_CHECK, WARNING, "; ".join(problems[:5]) + ". It runs on your machine when the plugin is enabled: read it before installing."), False
    return CheckResult(MCP_CONFIG_CHECK, PASSED, "starts " + ", ".join(sorted(map(str, entries)))), True


def _alias_row(files: Mapping[str, bytes]) -> CheckResult:
    """A name that differs from a special file only in capitals names the SAME file on Windows and macOS (`.MCP.JSON` is `.mcp.json`), but
    every check here looks files up by their exact spelling and would see nothing. Such a file, and a special folder spelled with other
    capitals (`Hooks/`, `Servers/`), fail the plugin. (A trailing dot or space and a colon are refused by the shared path check.)"""
    special = {p.casefold(): p for p in SPECIAL_FILES}
    folders = {d.casefold(): d for d in SPECIAL_DIRS}
    extras = {n.casefold(): n for n in EXTRA_FILES}
    problems: list[str] = []
    for rel in sorted(files):
        parts = PurePosixPath(rel).parts
        if not parts:
            continue
        if rel.casefold() in special and rel != special[rel.casefold()]:
            problems.append(f"{rel} is {special[rel.casefold()]} on Windows and macOS")
        elif parts[0].casefold() in folders and parts[0] != folders[parts[0].casefold()]:
            problems.append(f"{rel} is in the folder {folders[parts[0].casefold()]}/ on Windows and macOS")
        elif parts[-1].casefold() in extras and parts[-1] != extras[parts[-1].casefold()]:
            problems.append(f"{rel} is a {extras[parts[-1].casefold()]} on Windows and macOS")
    if problems:
        return CheckResult(ALIAS_CHECK, FAILED, "; ".join(problems[:5]) + ": the checks would not see it, and Claude Code would load it")
    return CheckResult(ALIAS_CHECK, PASSED, "none")


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
    out.append(_alias_row(files))
    has_skill = any(PurePosixPath(rel).match("skills/*/SKILL.md") for rel in files)
    has_agent = any(PurePosixPath(rel).parent.as_posix() == "agents" and rel.endswith(".md") for rel in files)
    has_server = bool(server_names(files))
    hooks_row, hooks_described, catalogue_scripts, catalogue_hooks = _hooks_row(files)
    out.append(  # a hook counts as content when at least one is exactly a catalogue hook; a plugin of nothing but commands we cannot describe has none
        CheckResult(CONTENTS_CHECK, PASSED) if has_skill or has_agent or has_server or catalogue_hooks
        else CheckResult(CONTENTS_CHECK, FAILED, "there is no skills/<name>/SKILL.md, agents/<name>.md or servers/<name>/server.py in it, and no hook it can describe")
    )
    out += _component_rows(files)
    config_row, config_described = _mcp_config_row(files, manifest)
    if config_row is not None:
        out.append(config_row)
    if hooks_row is not None:
        out.append(hooks_row)
    described = frozenset(([MCP_CONFIG] if config_described else []) + ([HOOKS_FILE] if hooks_described else []))
    out.append(_extras_row(files, manifest, described))
    out.append(_script_row(files, catalogue_scripts))
    return out
