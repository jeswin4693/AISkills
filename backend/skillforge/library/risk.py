"""What got riskier between two versions of a skill. Code only: no model, nothing is run.

A skill is checked once when it is imported, and then it is edited. Research on skill marketplaces found that a clean
skill can be edited into a bad one after it passed a scan, so the library compares every new version with the one
before it and says what changed *in the things code can see*:

    scripts        a new script; a script that now uses the network, runs commands or writes files (by syntax analysis)
    permissions    what the skill declares (skill.sdm.json) or asks for (`allowed-tools` in SKILL.md)
    wording        text that now matches a known attack pattern, or hidden markup (HTML comments, script tags)
    addresses      a web address a version now mentions that the one before did not
    description    the text an agent reads to decide when to use the skill
    instructions   SKILL.md and other Markdown files an agent reads: how many lines changed
    checks         any other static check that got worse

Both versions are checked with *today's* checks, so a new rule is not mistaken for a change in the skill.

This is not a safety verdict. It cannot read meaning: a few reworded sentences can change what an agent does, and no
pattern sees that. "No new risk found" means these checks found none, nothing more. Read the diff.
"""

from __future__ import annotations

import difflib
import json
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import PurePosixPath

import yaml

from ..hookcatalog import catalogue as hook_catalogue
from ..kinds import get_kind
from ..validate import validate_files
from ..validate.static import JS_LANGS, PY_SUFFIXES, TEXT_SUFFIXES, markup_findings, script_capabilities, split_tools, wording_findings

RISKIER = "riskier"  # something that can do more, or look worse, than before
LOOK = "look"  # a change that deserves reading, and that code cannot judge
SAFER = "safer"  # something that can do less than before

_ORDER = {RISKIER: 0, LOOK: 1, SAFER: 2}
_RANK = {"passed": 0, "not run": 0, "warning": 1, "failed": 2}
_COVERED_ELSEWHERE = {  # reported in detail below, so the generic "a check got worse" line would say it twice
    "no hidden markup (HTML comments, script tags) in Markdown", "no wording that matches known attack patterns",
}
_PLUGIN_ROWS = {  # the plugin's own rows, whose detail names what runs
    ".mcp.json starts only the MCP servers shipped inside the plugin", "hooks/hooks.json runs only catalogue hooks, unchanged",
    "no hooks, undescribed MCP servers, settings or executables", "scripts shipped inside the plugin",
}
_ADDRESS = re.compile(r"https?://([A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?)", re.I)
_MAX_LISTED = 6
NOTE = (
    "This compares only what code can see: script capabilities by syntax, permissions, known attack wording, web addresses "
    "and changed text. It cannot read meaning, so reworded instructions can still change what an agent does. "
    "Nothing here is a safety verdict: read the changes."
)


@dataclass
class RiskChange:
    direction: str  # riskier, look, safer
    kind: str  # script_added, script_removed, capability, dynamic_code, permission, tool, wording, markup, address, description, instructions, reference, check
    detail: str  # a plain sentence
    path: str = ""  # the file it is about, when there is one


@dataclass
class RiskDiff:
    older: str
    newer: str
    changes: list[RiskChange] = field(default_factory=list)
    note: str = NOTE

    def count(self, direction: str) -> int:
        return sum(c.direction == direction for c in self.changes)

    @property
    def level(self) -> str:
        """more_risk, look, less_risk or no_new_risk. Never "safe": see NOTE."""
        if self.count(RISKIER):
            return "more_risk"
        if self.count(LOOK):
            return "look"
        return "less_risk" if self.count(SAFER) else "no_new_risk"


# ---- reading the parts -------------------------------------------------------------------------------


def _text(data: bytes | None) -> str:
    return (data or b"").decode("utf-8", errors="replace").replace("\r\n", "\n")


def _front_matter(files: Mapping[str, bytes], definition: str = "SKILL.md") -> tuple[dict, str]:
    """(the front matter of the definition file, SKILL.md or AGENT.md, as a dict, the text after it). Empty when there is none or it is not valid."""
    text = _text(files.get(definition))
    match = re.match(r"---\n(.*?)\n---\n", text, re.DOTALL)
    if not match:
        return {}, text
    try:
        meta = yaml.safe_load(match.group(1))
    except yaml.YAMLError:
        return {}, text
    return (meta if isinstance(meta, dict) else {}), text[match.end():]


def _words(value: object) -> set[str]:
    """`allowed-tools` is written as a comma or space separated string, or as a list. An entry keeps its scope: `Bash(git *)`
    and `Bash(*)` are different entries, so widening a scope shows up in the risk diff."""
    return set(split_tools(value))


def _declared_permissions(files: Mapping[str, bytes]) -> set[str]:
    try:
        value = json.loads(_text(files.get("skill.sdm.json"))).get("permissions", [])
    except (ValueError, AttributeError):
        return set()
    return {str(p) for p in value} if isinstance(value, list) else set()


def _scripts(files: Mapping[str, bytes]) -> dict[str, bytes]:
    return {rel: data for rel, data in files.items() if rel.startswith("scripts/")}


def _analysed(rel: str) -> bool:
    suffix = PurePosixPath(rel).suffix.lower()
    return suffix in PY_SUFFIXES or suffix in JS_LANGS


def _line_changes(old: str, new: str) -> tuple[int, int]:
    added = removed = 0
    for line in difflib.unified_diff(old.splitlines(), new.splitlines(), lineterm="", n=0):
        if line.startswith("+") and not line.startswith("+++"):
            added += 1
        elif line.startswith("-") and not line.startswith("---"):
            removed += 1
    return added, removed


def _lines(added: int, removed: int) -> str:
    return f"{added} line{'' if added == 1 else 's'} added, {removed} removed"


def _listed(items: Sequence[str]) -> str:
    shown = ", ".join(items[:_MAX_LISTED])
    return shown + (f" and {len(items) - _MAX_LISTED} more" if len(items) > _MAX_LISTED else "")


def _cut(text: str, limit: int = 110) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _addresses(files: Mapping[str, bytes]) -> dict[str, set[str]]:
    """host -> the files that mention it, in text files."""
    found: dict[str, set[str]] = {}
    for rel, data in files.items():
        if PurePosixPath(rel).suffix.lower() not in TEXT_SUFFIXES:
            continue
        for m in _ADDRESS.finditer(_text(data)):
            found.setdefault(m.group(1).lower(), set()).add(rel)
    return found


# ---- the comparison ----------------------------------------------------------------------------------


def _code_files(files: Mapping[str, bytes], definition: str) -> dict[str, bytes]:
    """The scripts, and, for a kind whose definition file is itself code (an MCP server's server.py), every OTHER code file beside it:
    `python server.py` imports its neighbours, so a new `colorsys.py` is new code that runs. The definition file is read separately,
    by `_server_changes`, with the full analysis."""
    found = dict(_scripts(files))
    if _analysed(definition):
        for rel, data in files.items():
            if rel != definition and _analysed(rel):
                found[rel] = data
    return found


def _script_changes(
    old: Mapping[str, bytes], new: Mapping[str, bytes], out: list[RiskChange], definition: str = "SKILL.md",
    pick: Callable[[Mapping[str, bytes]], dict[str, bytes]] | None = None,
) -> None:
    """Scripts that came, went or changed. `pick` says which files count (a plugin's own code outside its components); by default a
    kind's scripts and, for an MCP server, the code beside `server.py`."""
    old_scripts, new_scripts = (pick(old), pick(new)) if pick else (_code_files(old, definition), _code_files(new, definition))
    for rel in sorted(new_scripts.keys() - old_scripts.keys()):
        caps, dynamic = script_capabilities(rel, new_scripts[rel])
        uses = sorted(caps | dynamic)
        what = f"it uses {', '.join(uses)}" if uses else (
            "no network, commands or file writes were found" if _analysed(rel) else "this kind of script is not analysed for what it does"
        )
        out.append(RiskChange(RISKIER, "script_added", f"A new script, {rel}: {what}.", rel))
    for rel in sorted(old_scripts.keys() - new_scripts.keys()):
        out.append(RiskChange(SAFER, "script_removed", f"The script {rel} was removed.", rel))
    for rel in sorted(old_scripts.keys() & new_scripts.keys()):
        if old_scripts[rel] == new_scripts[rel]:
            continue
        (old_caps, old_dyn), (new_caps, new_dyn) = script_capabilities(rel, old_scripts[rel]), script_capabilities(rel, new_scripts[rel])
        for cap in sorted(new_caps - old_caps):
            out.append(RiskChange(RISKIER, "capability", f"{rel} now uses {cap}, which it did not before.", rel))
        for cap in sorted(old_caps - new_caps):
            out.append(RiskChange(SAFER, "capability", f"{rel} no longer uses {cap}.", rel))
        for dyn in sorted(new_dyn - old_dyn):
            out.append(RiskChange(RISKIER, "dynamic_code", f"{rel} now uses {dyn}: code that is built while it runs cannot be analysed.", rel))
        for dyn in sorted(old_dyn - new_dyn):
            out.append(RiskChange(SAFER, "dynamic_code", f"{rel} no longer uses {dyn}.", rel))
        if new_caps == old_caps and new_dyn == old_dyn:
            added, removed = _line_changes(_text(old_scripts[rel]), _text(new_scripts[rel]))
            note = "" if _analysed(rel) else " This kind of script is not analysed for what it does."
            out.append(RiskChange(LOOK, "script_changed", f"{rel} changed ({_lines(added, removed)}); its capabilities are the same.{note}", rel))


def _server_changes(old: Mapping[str, bytes], new: Mapping[str, bytes], out: list[RiskChange], definition: str) -> None:
    """For an MCP server (Python or Node): the tools it offers Claude and the environment variables it reads, by syntax."""
    if definition.endswith(".ts"):
        from ..validate.mcp_node import analyze_node_server as analyze  # imported here: `validate` must not need `library` and `library` need not load it for other kinds
    else:
        from ..validate.mcp import analyze_server as analyze

    def facts(files: Mapping[str, bytes]):
        try:
            return analyze(_text(files[definition]))
        except (KeyError, SyntaxError, ValueError, RecursionError):
            return None

    before, after = facts(old), facts(new)
    if before is None or after is None:
        return
    old_tools, new_tools = {t.name for t in before.tools}, {t.name for t in after.tools}
    for name in sorted(new_tools - old_tools):
        out.append(RiskChange(LOOK, "tool", f"The server now offers a new tool, {name}: it is one more thing Claude can do through it.", definition))
    for name in sorted(old_tools - new_tools):
        out.append(RiskChange(SAFER, "tool", f"The server no longer offers the tool {name}.", definition))
    for name in sorted(after.env_names - before.env_names):
        out.append(RiskChange(RISKIER, "environment", f"The server now reads the environment variable {name}: whatever value you give it is reachable by the tools.", definition))
    for name in sorted(before.env_names - after.env_names):
        out.append(RiskChange(SAFER, "environment", f"The server no longer reads the environment variable {name}.", definition))
    if after.env_dynamic and not before.env_dynamic:
        out.append(RiskChange(RISKIER, "environment", "The server now reads an environment variable by a name that is not written in the code (or all of them).", definition))
    for cap in sorted(after.capabilities - before.capabilities):  # aliases are followed, so `import os as o` cannot hide a new power
        out.append(RiskChange(LOOK if cap == "read_files" else RISKIER, "capability", f"{definition} now uses {cap}, which it did not before.", definition))
    for cap in sorted(before.capabilities - after.capabilities):
        out.append(RiskChange(SAFER, "capability", f"{definition} no longer uses {cap}.", definition))
    for construct in sorted(after.dynamic - before.dynamic):
        out.append(RiskChange(RISKIER, "dynamic_code", f"{definition} now uses {construct}: the checks cannot follow it, so what it does is not known.", definition))
    for construct in sorted(before.dynamic - after.dynamic):
        out.append(RiskChange(SAFER, "dynamic_code", f"{definition} no longer uses {construct}.", definition))


def _package_changes(old: Mapping[str, bytes], new: Mapping[str, bytes], out: list[RiskChange]) -> None:
    """For a Node server: what `npm install` would run and fetch. `scripts` run by themselves when it installs, a dependency is code that runs when
    imported, and a lockfile that is not the pinned one decides where every package comes from."""
    from ..mcpnode import LOCK_FILE, PACKAGE_FILE, is_our_lock

    def read(files: Mapping[str, bytes]) -> dict:
        try:
            value = json.loads(_text(files[PACKAGE_FILE]))
            return value if isinstance(value, dict) else {}
        except (KeyError, ValueError, RecursionError):
            return {}

    before, after = read(old), read(new)
    old_scripts, new_scripts = before.get("scripts") or {}, after.get("scripts") or {}
    if (new_scripts and not isinstance(new_scripts, dict)) or (old_scripts and not isinstance(old_scripts, dict)):
        if bool(new_scripts) != bool(old_scripts) or new_scripts != old_scripts:  # whatever shape it has, `scripts` in package.json is what npm runs when it installs
            out.append(RiskChange(RISKIER if new_scripts else SAFER, "install_script", "package.json's scripts changed (it is not a list of named scripts, which npm may still read as scripts).", PACKAGE_FILE))
    elif isinstance(new_scripts, dict) and isinstance(old_scripts, dict):
        for name in sorted(new_scripts.keys() - old_scripts.keys()):
            out.append(RiskChange(RISKIER, "install_script", f"package.json now has a script, {name}: npm runs install scripts by itself when it installs.", PACKAGE_FILE))
        for name in sorted(old_scripts.keys() & new_scripts.keys()):
            if old_scripts[name] != new_scripts[name]:
                out.append(RiskChange(RISKIER, "install_script", f"The script {name} in package.json changed.", PACKAGE_FILE))
        for name in sorted(old_scripts.keys() - new_scripts.keys()):
            out.append(RiskChange(SAFER, "install_script", f"package.json no longer has the script {name}.", PACKAGE_FILE))
    old_deps, new_deps = before.get("dependencies") or {}, after.get("dependencies") or {}
    if isinstance(new_deps, dict) and isinstance(old_deps, dict):
        for name in sorted(new_deps.keys() - old_deps.keys()):
            out.append(RiskChange(RISKIER, "dependency", f"The server now depends on {name} {new_deps[name]}: more code that runs on your machine.", PACKAGE_FILE))
        for name in sorted(old_deps.keys() - new_deps.keys()):
            out.append(RiskChange(SAFER, "dependency", f"The server no longer depends on {name}.", PACKAGE_FILE))
        for name in sorted(old_deps.keys() & new_deps.keys()):
            if old_deps[name] != new_deps[name]:
                out.append(RiskChange(RISKIER, "dependency", f"{name} changed from {old_deps[name]} to {new_deps[name]}.", PACKAGE_FILE))
    for key in sorted((set(after) - set(before)) & {"overrides", "resolutions", "imports", "exports", "bin", "optionalDependencies", "peerDependencies", "devDependencies"}):
        out.append(RiskChange(RISKIER, "package", f"package.json now has {key}, which changes which packages are used or what Node loads.", PACKAGE_FILE))
    name = after.get("name") or before.get("name") or ""
    was_ours = LOCK_FILE in old and is_our_lock(_text(old[LOCK_FILE]), str(before.get("name") or name))
    is_ours = LOCK_FILE in new and is_our_lock(_text(new[LOCK_FILE]), str(name))
    if was_ours and not is_ours:
        out.append(RiskChange(RISKIER, "lockfile", "package-lock.json is no longer the pinned lockfile: it decides which packages are installed and where they come from.", LOCK_FILE))
    elif is_ours and not was_ours:
        out.append(RiskChange(SAFER, "lockfile", "package-lock.json is now the pinned lockfile.", LOCK_FILE))
    elif not is_ours and LOCK_FILE in old and LOCK_FILE in new and old[LOCK_FILE] != new[LOCK_FILE]:
        out.append(RiskChange(RISKIER, "lockfile", "package-lock.json changed: it decides which packages are installed and where they come from.", LOCK_FILE))


def _permission_changes(
    old: Mapping[str, bytes], new: Mapping[str, bytes], out: list[RiskChange], definition: str = "SKILL.md", tools_field: str = "allowed-tools",
) -> None:
    gained, lost = _declared_permissions(new) - _declared_permissions(old), _declared_permissions(old) - _declared_permissions(new)
    if gained:
        out.append(RiskChange(RISKIER, "permission", f"The skill now asks for: {', '.join(sorted(gained))}.", "skill.sdm.json"))
    if lost:
        out.append(RiskChange(SAFER, "permission", f"The skill no longer asks for: {', '.join(sorted(lost))}.", "skill.sdm.json"))
    old_tools = _words(_front_matter(old, definition)[0].get(tools_field))
    new_tools = _words(_front_matter(new, definition)[0].get(tools_field))
    if new_tools - old_tools:
        out.append(RiskChange(RISKIER, "tool", f"{tools_field} now also lists: {', '.join(sorted(new_tools - old_tools))}.", definition))
    if old_tools - new_tools:
        out.append(RiskChange(SAFER, "tool", f"{tools_field} no longer lists: {', '.join(sorted(old_tools - new_tools))}.", definition))


def _wording_changes(old: Mapping[str, bytes], new: Mapping[str, bytes], out: list[RiskChange]) -> None:
    before_w = {(rel, label) for rel, label, _ in wording_findings(old)}
    after_w = {(rel, label): line for rel, label, line in wording_findings(new)}
    for rel, label in sorted(after_w.keys() - before_w):
        out.append(RiskChange(RISKIER, "wording", f"{rel}, line {after_w[(rel, label)]}, now has wording that {label}. This is a pattern match: read the line, it may be harmless.", rel))
    for rel, label in sorted(before_w - after_w.keys()):
        out.append(RiskChange(SAFER, "wording", f"{rel} no longer has wording that {label}.", rel))
    before_m = {(rel, what) for rel, what, _ in markup_findings(old)}
    after_m = {(rel, what): line for rel, what, line in markup_findings(new)}
    for rel, what in sorted(after_m.keys() - before_m):
        out.append(RiskChange(RISKIER, "markup", f"{rel}, line {after_m[(rel, what)]}, now has hidden markup ({what}): invisible on a rendered page, but an agent still reads it.", rel))
    for rel, what in sorted(before_m - after_m.keys()):
        out.append(RiskChange(SAFER, "markup", f"{rel} no longer has hidden markup ({what}).", rel))


def _address_changes(old: Mapping[str, bytes], new: Mapping[str, bytes], out: list[RiskChange]) -> None:
    before, after = _addresses(old), _addresses(new)
    for host in sorted(after.keys() - before.keys()):
        where = sorted(after[host])
        in_script = [rel for rel in where if rel.startswith("scripts/")]
        out.append(RiskChange(
            RISKIER if in_script else LOOK, "address",
            f"A web address that the version before did not mention: {host} (in {_listed(where)}).", where[0],
        ))
    gone = sorted(before.keys() - after.keys())
    if gone:
        out.append(RiskChange(SAFER, "address", f"No longer mentions: {_listed(gone)}."))


def _text_changes(
    old: Mapping[str, bytes], new: Mapping[str, bytes], out: list[RiskChange], definition: str = "SKILL.md", noun: str = "skill",
) -> None:
    old_meta, old_body = _front_matter(old, definition)
    new_meta, new_body = _front_matter(new, definition)
    old_desc, new_desc = " ".join(str(old_meta.get("description", "")).split()), " ".join(str(new_meta.get("description", "")).split())
    if old_desc != new_desc:
        out.append(RiskChange(
            LOOK, "description",
            f"The description changed. An agent reads it to decide when to use the {noun}. Was: \"{_cut(old_desc)}\" Now: \"{_cut(new_desc)}\"", definition,
        ))
    if definition in old or definition in new:
        added, removed = _line_changes(old_body, new_body)
        if added or removed:
            if _analysed(definition):  # code is not read by an agent: it runs on this machine
                out.append(RiskChange(LOOK, "instructions", f"The code in {definition} changed ({_lines(added, removed)}). It runs on your machine when the server starts.", definition))
            else:
                out.append(RiskChange(LOOK, "instructions", f"The instructions in {definition} changed ({_lines(added, removed)}). An agent follows them.", definition))
    for rel in sorted(old.keys() | new.keys()):  # other Markdown an agent may be sent to read
        if rel == definition or PurePosixPath(rel).suffix.lower() != ".md" or old.get(rel) == new.get(rel):
            continue
        if rel not in old:
            out.append(RiskChange(LOOK, "reference", f"A new Markdown file, {rel}. If {definition} points to it, an agent will read it.", rel))
        elif rel not in new:
            out.append(RiskChange(SAFER, "reference", f"The Markdown file {rel} was removed.", rel))
        else:
            added, removed = _line_changes(_text(old[rel]), _text(new[rel]))
            out.append(RiskChange(LOOK, "reference", f"{rel} changed ({_lines(added, removed)}). If {definition} points to it, an agent will read it.", rel))


def _check_changes(old: Mapping[str, bytes], new: Mapping[str, bytes], out: list[RiskChange], kind: str = "skill") -> None:
    before = {c.name: c for c in validate_files(old, kind=kind)}
    for c in validate_files(new, kind=kind):
        if c.name in _COVERED_ELSEWHERE:
            continue
        was = before.get(c.name)
        now_rank, was_rank = _RANK[c.status], _RANK[was.status] if was else 0
        if now_rank > was_rank:
            out.append(RiskChange(RISKIER, "check", f"A check got worse ({c.status}): {c.name}. {c.detail}".strip()))
        elif now_rank < was_rank:
            out.append(RiskChange(SAFER, "check", f"A check got better ({c.status}): {c.name}."))
        elif kind == "plugin" and now_rank > 0 and was is not None and c.detail != was.detail and c.name in _PLUGIN_ROWS:
            # the row was already a warning and still is, but what it names is different: without this a new command hides behind an old warning
            out.append(RiskChange(LOOK, "check", f"A warning that was already there changed: {c.name}. Now: {_cut(c.detail, 400)}"))


def _canonical(value: object) -> str:
    try:
        return json.dumps(value, sort_keys=True, ensure_ascii=True)
    except (TypeError, ValueError, RecursionError):
        return repr(type(value))


def _json_or_none(files: Mapping[str, bytes], path: str) -> object:
    try:
        return json.loads(files[path].decode("utf-8"))
    except (KeyError, UnicodeDecodeError, ValueError, RecursionError):
        return None  # a file that cannot be read is the validator's to report, not a reason to crash a comparison


def _hooks_in(files: Mapping[str, bytes]) -> dict[str, dict]:
    """The hooks `hooks/hooks.json` runs, by identity: a catalogue hook by its id, any other by the WHOLE hook object (command, arguments,
    timeout and every other key), so a change anywhere in it makes it a different hook, and two hooks never collapse into one. Where each
    runs (event and matcher) is kept as a set."""
    from ..validate.plugin import shown_command  # here: `validate.plugin` needs nothing from the library

    data = _json_or_none(files, hook_catalogue.HOOKS_FILE)
    events = data.get("hooks") if isinstance(data, dict) else None
    found: dict[str, dict] = {}
    for event, groups in (events.items() if isinstance(events, dict) else []):
        for group in (groups if isinstance(groups, list) else []):
            if not isinstance(group, dict) or not isinstance(group.get("hooks"), list):
                continue
            matcher = str(group.get("matcher", ""))
            for hook in group["hooks"]:
                if not isinstance(hook, dict):
                    continue
                args = hook.get("args")
                entry = hook_catalogue.entry_for_args(args)
                record = found.setdefault(entry.id if entry else "hook " + _canonical(hook), {
                    "places": set(), "shown": shown_command(hook), "entry": entry, "hook": hook, "on_failure": hook.get("onFailure"),
                    "options": (hook_catalogue.parse_args(entry, args) or {"arguments": [shown_command(hook)]}) if entry else {},
                })
                record["places"].add((str(event), matcher))
    return found


def _places_text(places: set[tuple[str, str]]) -> str:
    return ", ".join(f"{event} for {matcher or 'every tool'}" for event, matcher in sorted(places))


def _options_text(options: Mapping[str, Sequence[str]]) -> str:
    return "; ".join(f"{key}: {', '.join(values)}" for key, values in options.items()) or "none"


def _hook_changes(old: Mapping[str, bytes], new: Mapping[str, bytes], out: list[RiskChange]) -> None:
    """What the plugin's hooks now do on the machine: a hook that came is riskier (it runs on every matching event, with the person's
    permissions), one that went is safer, one that runs on other events, whose program or other keys changed, or whose script is no longer
    the catalogue's is riskier."""
    from ..validate.plugin import safe_text  # here: `validate.plugin` needs nothing from the library

    where = hook_catalogue.HOOKS_FILE
    before, after = _hooks_in(old), _hooks_in(new)
    for ident in sorted(after.keys() - before.keys()):
        hook = after[ident]
        entry = hook["entry"]
        if entry:
            detail = (
                f"The hook '{entry.id}' is now in the plugin: it runs on your machine, with your permissions, on {_places_text(hook['places'])}. {entry.summary}"
                + (" It can stop what Claude is about to do." if entry.effect == "blocks" else " It only looks.")
                + (" By its script it writes files." if entry.powers else "")
            )
        else:
            detail = (
                f"{where} now runs {hook['shown']} on {_places_text(hook['places'])}: not a catalogue hook, so what it does is not vouched for. "
                "It runs on your machine, with your permissions, when the plugin is enabled."
            )
        out.append(RiskChange(RISKIER, "hook_added", detail, where))
    for ident in sorted(before.keys() - after.keys()):
        hook = before[ident]
        out.append(RiskChange(
            SAFER, "hook_removed",
            f"The hook '{hook['entry'].id}' is no longer in the plugin." if hook["entry"] else f"{where} no longer runs {hook['shown']}.", where,
        ))
    for ident in sorted(before.keys() & after.keys()):
        was, now = before[ident], after[ident]
        name = now["entry"].id if now["entry"] else now["shown"]
        if was["places"] != now["places"]:
            out.append(RiskChange(
                RISKIER, "hook_trigger",
                f"The hook '{name}' now runs on {_places_text(now['places'])}, not on {_places_text(was['places'])}: it will run on different events.", where,
            ))
        if was["options"] != now["options"]:
            out.append(RiskChange(
                LOOK, "hook_options", f"The options of the hook '{name}' changed. Was: {_options_text(was['options'])}. Now: {_options_text(now['options'])}.", where,
            ))
        if was["on_failure"] != now["on_failure"]:
            if was["on_failure"] == "block":
                out.append(RiskChange(
                    RISKIER, "hook_failure",
                    f"The hook '{name}' no longer says onFailure \"block\": if it cannot run (python missing from the PATH) or fails, the action it guards now lets the action through, and nothing tells the person.",
                    where,
                ))
            elif now["on_failure"] == "block":
                out.append(RiskChange(SAFER, "hook_failure", f"The hook '{name}' now says onFailure \"block\": if it cannot run or fails, Claude Code stops the action instead of letting it through.", where))
            else:
                out.append(RiskChange(LOOK, "hook_failure", f"The hook '{name}' changed what Claude Code does when it cannot run (onFailure): was {was['on_failure']!r}, now {now['on_failure']!r}.", where))
        entry = now["entry"]
        if entry is None:
            continue
        for key in sorted((set(was["hook"]) | set(now["hook"])) - {"args", "onFailure"}):  # the program, the timeout and any other key of a catalogue hook
            if was["hook"].get(key) != now["hook"].get(key):
                out.append(RiskChange(
                    RISKIER, "hook_other",
                    f"The hook '{entry.id}' now has {key} {safe_text(_canonical(now['hook'].get(key)), 80)} instead of {safe_text(_canonical(was['hook'].get(key)), 80)}: what Claude Code starts is no longer what the catalogue writes.",
                    where,
                ))
        old_script, new_script = old.get(entry.shipped_path), new.get(entry.shipped_path)
        if old_script is None or new_script is None or hook_catalogue.script_hash(old_script) == hook_catalogue.script_hash(new_script):
            continue
        if not hook_catalogue.accepts(entry, new_script):
            out.append(RiskChange(
                RISKIER, "hook_script",
                f"The script of the hook '{entry.id}' ({entry.shipped_path}) is no longer the catalogue's: it is code that runs on your machine, and the catalogue does not vouch for it.",
                entry.shipped_path,
            ))
        elif hook_catalogue.accepts(entry, old_script):
            out.append(RiskChange(LOOK, "hook_script", f"The script of the hook '{entry.id}' is now a newer revision of the catalogue's script.", entry.shipped_path))
        else:
            out.append(RiskChange(SAFER, "hook_script", f"The script of the hook '{entry.id}' is the catalogue's script again.", entry.shipped_path))


def _plugin_level_code(files: Mapping[str, bytes], owned: set[str]) -> dict[str, bytes]:
    """Code a plugin ships outside its components: not in `skills/` or `servers/` (they are compared by their own kind's rules) and not the
    script of a catalogue hook that the plugin RUNS (`owned`, compared with the hooks). A catalogue-named file that no catalogue hook runs is
    just code, and is compared like any other."""
    from ..validate.plugin import SERVERS_DIR, shipped_code  # here: `validate.plugin` needs nothing from the library

    return {rel: data for rel, data in shipped_code(files).items() if PurePosixPath(rel).parts[0] not in ("skills", SERVERS_DIR) and rel not in owned}


def _manifest_changes(old: Mapping[str, bytes], new: Mapping[str, bytes], out: list[RiskChange]) -> None:
    """The plugin manifest is not instructions an agent follows, but two things in it matter: the options it asks a person for (a secret that
    stops being sensitive, a default that is used without asking) and the keys that start something (inline hooks, MCP and LSP servers,
    monitors), whose commands are compared."""
    from ..validate.plugin import EXTRA_MANIFEST_KEYS, MANIFEST, declared_commands  # here: `validate.plugin` needs nothing from the library

    raw_before, raw_after = _json_or_none(old, MANIFEST), _json_or_none(new, MANIFEST)
    before, after = (raw_before if isinstance(raw_before, dict) else {}), (raw_after if isinstance(raw_after, dict) else {})
    old_options = before.get("userConfig") if isinstance(before.get("userConfig"), dict) else {}
    new_options = after.get("userConfig") if isinstance(after.get("userConfig"), dict) else {}
    for key in sorted(new_options.keys() - old_options.keys()):
        out.append(RiskChange(LOOK, "option", f"The plugin now asks for the option {_cut(str(key), 60)}, and what is typed there reaches whatever uses it.", MANIFEST))
    for key in sorted(old_options.keys() - new_options.keys()):
        out.append(RiskChange(SAFER, "option", f"The plugin no longer asks for the option {_cut(str(key), 60)}.", MANIFEST))
    for key in sorted(old_options.keys() & new_options.keys()):
        was = old_options[key] if isinstance(old_options[key], dict) else {}
        now = new_options[key] if isinstance(new_options[key], dict) else {}
        label = _cut(str(key), 60)
        if was.get("sensitive") is True and now.get("sensitive") is not True:
            out.append(RiskChange(RISKIER, "option", f"The option {label} is no longer sensitive: its value is not kept as a secret any more.", MANIFEST))
        elif was.get("sensitive") is not True and now.get("sensitive") is True:
            out.append(RiskChange(SAFER, "option", f"The option {label} is now sensitive: its value is kept as a secret.", MANIFEST))
        if "default" in now and was.get("default") != now.get("default"):
            out.append(RiskChange(RISKIER, "option", f"The option {label} now has a default ({_cut(_canonical(now['default']), 60)}): Claude Code may use it without asking.", MANIFEST))
        elif "default" in was and "default" not in now:
            out.append(RiskChange(LOOK, "option", f"The option {label} no longer has a default.", MANIFEST))
        if was.get("required") != now.get("required"):
            out.append(RiskChange(LOOK, "option", f"The option {label} changed whether it is required: was {was.get('required')!r}, now {now.get('required')!r}.", MANIFEST))
        if was.get("type") != now.get("type"):
            out.append(RiskChange(LOOK, "option", f"The option {label} changed type: was {_cut(str(was.get('type')), 30)}, now {_cut(str(now.get('type')), 30)}.", MANIFEST))
    for key in EXTRA_MANIFEST_KEYS:
        was_value, now_value, shown = before.get(key), after.get(key), key
        if key == "experimental":
            was_value = was_value.get("monitors") if isinstance(was_value, dict) else None
            now_value = now_value.get("monitors") if isinstance(now_value, dict) else None
            shown = "experimental.monitors"
        was_commands, now_commands = declared_commands(was_value), declared_commands(now_value)
        for command in now_commands:
            if command not in was_commands:
                out.append(RiskChange(RISKIER, "manifest", f"The manifest now declares {shown} that starts {command}. It runs on your machine when the plugin is enabled.", MANIFEST))
        for command in was_commands:
            if command not in now_commands:
                out.append(RiskChange(SAFER, "manifest", f"The manifest no longer declares {shown} that starts {command}.", MANIFEST))
        if not was_commands and not now_commands and was_value != now_value:
            out.append(RiskChange(RISKIER if now_value is not None else SAFER, "manifest", f"The manifest {'now declares' if now_value is not None else 'no longer declares'} {shown}.", MANIFEST))


def _config_changes(old: Mapping[str, bytes], new: Mapping[str, bytes], out: list[RiskChange], came_with_server: set[str]) -> None:
    """What `.mcp.json` starts. An entry that arrives or leaves together with its server in the composed form is said by the server's own line;
    any other entry is shown with its command, and every difference in an entry that stayed (its command, any other key such as `cwd`, and what each
    variable takes its value from) is reported. A value in `env` is never shown, only where it comes from."""
    from ..validate.plugin import MCP_CONFIG, safe_text, server_entry, shown_command  # here: `validate.plugin` needs nothing from the library

    def entries(files: Mapping[str, bytes]) -> dict[str, dict]:
        data = _json_or_none(files, MCP_CONFIG)
        found = data.get("mcpServers") if isinstance(data, dict) else None
        return {str(k): v for k, v in found.items() if isinstance(v, dict)} if isinstance(found, dict) else {}

    def composed(name: str, entry: Mapping) -> bool:
        return {k: v for k, v in entry.items() if k != "env"} == server_entry(name)

    def env_of(entry: Mapping) -> dict:
        env = entry.get("env")
        return dict(env) if isinstance(env, dict) else {}

    def source(value: object) -> str:
        match = re.fullmatch(r"\$\{user_config\.([A-Za-z_][A-Za-z0-9_]*)\}", value) if isinstance(value, str) else None
        return f"the option {match.group(1)}" if match else "a value written in the file"

    started_before, started_after = entries(old), entries(new)
    for name in sorted(started_after.keys() - started_before.keys()):
        if name in came_with_server and composed(name, started_after[name]):
            continue
        out.append(RiskChange(RISKIER, "server_start", f"{MCP_CONFIG} now starts '{name}': {shown_command(started_after[name])}. It runs on your machine when the plugin is enabled.", MCP_CONFIG))
    for name in sorted(started_before.keys() - started_after.keys()):
        if name in came_with_server and composed(name, started_before[name]):
            continue
        out.append(RiskChange(SAFER, "server_start", f"{MCP_CONFIG} no longer starts '{name}'.", MCP_CONFIG))
    for name in sorted(started_before.keys() & started_after.keys()):
        was, now = started_before[name], started_after[name]
        if (was.get("command"), was.get("args")) != (now.get("command"), now.get("args")):
            out.append(RiskChange(
                RISKIER, "server_start", f"{MCP_CONFIG} now starts '{name}' as {shown_command(now)} instead of {shown_command(was)}.", MCP_CONFIG,
            ))
        for key in sorted((set(was) | set(now)) - {"command", "args", "env"}):
            if was.get(key) != now.get(key):
                out.append(RiskChange(
                    RISKIER, "server_start",
                    f"{MCP_CONFIG} now has {key} {safe_text(_canonical(now.get(key)), 80)} for '{name}' (it was {safe_text(_canonical(was.get(key)), 80)}): it changes how the server is started.", MCP_CONFIG,
                ))
        was_env, now_env = env_of(was), env_of(now)
        for variable in sorted(map(str, now_env.keys() - was_env.keys())):
            out.append(RiskChange(RISKIER, "environment", f"{MCP_CONFIG} now gives '{name}' the environment variable {variable}: whatever value is set is reachable by the server.", MCP_CONFIG))
        for variable in sorted(map(str, was_env.keys() - now_env.keys())):
            out.append(RiskChange(SAFER, "environment", f"{MCP_CONFIG} no longer gives '{name}' the environment variable {variable}.", MCP_CONFIG))
        for variable in sorted(map(str, now_env.keys() & was_env.keys())):
            if now_env[variable] != was_env[variable]:
                out.append(RiskChange(
                    RISKIER, "environment",
                    f"{MCP_CONFIG} now gives '{name}' {variable} from {source(now_env[variable])} instead of {source(was_env[variable])}.", MCP_CONFIG,
                ))


def _plugin_changes(old: Mapping[str, bytes], new: Mapping[str, bytes], out: list[RiskChange]) -> None:
    """Inside a plugin: each skill, agent and MCP server that is in both versions is compared with the rules of its own kind, a component
    that came or went is said, and so are the manifest's options and start-keys, what `.mcp.json` starts, the hooks, and any code outside
    the components."""
    from ..validate.plugin import components, declared_commands, shipped_code  # here: `validate.plugin` needs nothing from the library

    def keyed(files: Mapping[str, bytes]) -> dict[tuple[str, str], dict[str, bytes]]:
        return {(kind, name): sub for kind, name, sub in components(files)}

    def label(kind: str) -> str:
        return "MCP server" if kind == "mcp" else kind

    def where(kind: str, name: str, path: str = "") -> str:
        if kind == "mcp":
            return f"servers/{name}/{path or 'server.py'}"
        return f"skills/{name}/{path or 'SKILL.md'}" if kind == "skill" else f"agents/{name}.md"

    def power(kind: str, sub: Mapping[str, bytes]) -> list[str]:
        if kind == "mcp":
            return ["a program that starts on your machine"]
        definition, field_name = ("SKILL.md", "allowed-tools") if kind == "skill" else ("AGENT.md", "tools")
        meta = _front_matter(sub, definition)[0]
        reasons: list[str] = []
        tools = sorted({entry.split("(")[0] for entry in split_tools(meta.get(field_name))} - {"Read", "Grep", "Glob"})
        if tools:
            reasons.append("the tools " + ", ".join(tools))
        code = shipped_code(sub)
        if code:
            reasons.append(f"{len(code)} code file{'s' if len(code) != 1 else ''}")
        if meta.get("hooks"):
            reasons.append("hooks")
        if meta.get("mcpServers") or meta.get("mcp_servers"):
            reasons.append("MCP servers")
        return reasons

    def commands(kind: str, sub: Mapping[str, bytes]) -> list[str]:
        """The commands a skill's or agent's front matter says to start (its hooks and MCP servers), as shown to a person."""
        if kind == "mcp":
            return []
        meta = _front_matter(sub, "SKILL.md" if kind == "skill" else "AGENT.md")[0]
        return declared_commands(meta.get("hooks")) + declared_commands(meta.get("mcpServers") or meta.get("mcp_servers"))

    before, after = keyed(old), keyed(new)
    for kind, name in sorted(after.keys() - before.keys()):
        reasons = power(kind, after[(kind, name)])
        if kind == "mcp":
            detail = f"The MCP server '{name}' is now in the plugin: a program that starts on your machine, with your permissions and outside any sandbox, whenever Claude Code loads the plugin."
        else:
            detail = f"The {kind} '{name}' is now in the plugin" + (f" and asks for {', '.join(reasons)}." if reasons else "; it asks for nothing beyond reading.")
            started = commands(kind, after[(kind, name)])
            if started:
                detail += " It would start: " + "; ".join(started[:3]) + "."
        out.append(RiskChange(RISKIER if reasons else LOOK, "component_added", detail, where(kind, name)))
    for kind, name in sorted(before.keys() - after.keys()):
        out.append(RiskChange(SAFER, "component_removed", f"The {label(kind)} '{name}' is no longer in the plugin.", where(kind, name)))
    for kind, name in sorted(before.keys() & after.keys()):
        old_c, new_c = before[(kind, name)], after[(kind, name)]
        if old_c == new_c:
            continue
        for change in risk_diff(old_c, new_c, kind=kind).changes:
            out.append(RiskChange(change.direction, change.kind, f"{label(kind)} '{name}': {change.detail}", where(kind, name, change.path)))
        gained = [word for word in power(kind, new_c) if word in ("hooks", "MCP servers") and word not in power(kind, old_c)]
        if gained:
            out.append(RiskChange(RISKIER, "capability", f"The {kind} '{name}' now declares {' and '.join(gained)}: they run on your machine.", where(kind, name)))
        was_started = commands(kind, old_c)
        for command in commands(kind, new_c):
            if command not in was_started:
                out.append(RiskChange(RISKIER, "capability", f"The {kind} '{name}' now declares a command that starts {command}.", where(kind, name)))

    came_with_server = {name for kind, name in after.keys() ^ before.keys() if kind == "mcp"}
    _manifest_changes(old, new, out)
    _config_changes(old, new, out, came_with_server)
    _hook_changes(old, new, out)
    owned = {entry.shipped_path for hook in (*_hooks_in(old).values(), *_hooks_in(new).values()) if (entry := hook["entry"]) is not None}
    _script_changes(old, new, out, pick=lambda files: _plugin_level_code(files, owned))  # a script a hooks file runs that is not a catalogue hook's, or any other code outside the components


def risk_diff(old: Mapping[str, bytes], new: Mapping[str, bytes], older: str = "", newer: str = "", kind: str = "skill") -> RiskDiff:
    """What got riskier (and what got safer) from `old` to `new`, two versions of one kind held in memory.

    `kind` says which definition file and which tools key to read (SKILL.md and allowed-tools, AGENT.md and tools)."""
    spec = get_kind(kind)
    changes: list[RiskChange] = []
    if kind == "plugin":  # everything inside it is a skill or an agent: compare those, each by its own kind's rules
        _plugin_changes(old, new, changes)
    else:
        _script_changes(old, new, changes, spec.definition_file)
        if spec.definition_file.endswith((".py", ".ts")):
            _server_changes(old, new, changes, spec.definition_file)
        if spec.definition_file.endswith(".ts"):
            _package_changes(old, new, changes)
        _permission_changes(old, new, changes, spec.definition_file, spec.tools_field)
        _wording_changes(old, new, changes)
        _address_changes(old, new, changes)
        _text_changes(old, new, changes, spec.definition_file, spec.label.lower())
    _check_changes(old, new, changes, kind)
    changes.sort(key=lambda c: _ORDER[c.direction])  # stable: within a group the order above is kept
    return RiskDiff(older, newer, changes)
