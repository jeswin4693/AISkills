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
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import PurePosixPath

import yaml

from ..kinds import get_kind
from ..validate import validate_files
from ..validate.static import JS_LANGS, PY_SUFFIXES, TEXT_SUFFIXES, markup_findings, script_capabilities, wording_findings

RISKIER = "riskier"  # something that can do more, or look worse, than before
LOOK = "look"  # a change that deserves reading, and that code cannot judge
SAFER = "safer"  # something that can do less than before

_ORDER = {RISKIER: 0, LOOK: 1, SAFER: 2}
_RANK = {"passed": 0, "not run": 0, "warning": 1, "failed": 2}
_COVERED_ELSEWHERE = {  # reported in detail below, so the generic "a check got worse" line would say it twice
    "no hidden markup (HTML comments, script tags) in Markdown", "no wording that matches known attack patterns",
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
    """`allowed-tools` is written as a comma or space separated string, or as a list."""
    if isinstance(value, str):
        return {w for w in re.split(r"[,\s]+", value) if w}
    if isinstance(value, list):
        return {str(w) for w in value}
    return set()


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
    """The scripts, and the definition file too when it is itself code (an MCP server's server.py)."""
    found = dict(_scripts(files))
    if definition in files and _analysed(definition):
        found[definition] = files[definition]
    return found


def _script_changes(old: Mapping[str, bytes], new: Mapping[str, bytes], out: list[RiskChange], definition: str = "SKILL.md") -> None:
    old_scripts, new_scripts = _code_files(old, definition), _code_files(new, definition)
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
    """For an MCP server: the tools it offers Claude and the environment variables it reads, by syntax."""
    from ..validate.mcp import analyze_server  # imported here: `validate` must not need `library` and `library` need not load it for other kinds

    def facts(files: Mapping[str, bytes]):
        try:
            return analyze_server(_text(files[definition]))
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


def risk_diff(old: Mapping[str, bytes], new: Mapping[str, bytes], older: str = "", newer: str = "", kind: str = "skill") -> RiskDiff:
    """What got riskier (and what got safer) from `old` to `new`, two versions of one kind held in memory.

    `kind` says which definition file and which tools key to read (SKILL.md and allowed-tools, AGENT.md and tools)."""
    spec = get_kind(kind)
    changes: list[RiskChange] = []
    _script_changes(old, new, changes, spec.definition_file)
    if spec.definition_file.endswith(".py"):
        _server_changes(old, new, changes, spec.definition_file)
    _permission_changes(old, new, changes, spec.definition_file, spec.tools_field)
    _wording_changes(old, new, changes)
    _address_changes(old, new, changes)
    _text_changes(old, new, changes, spec.definition_file, spec.label.lower())
    _check_changes(old, new, changes, kind)
    changes.sort(key=lambda c: _ORDER[c.direction])  # stable: within a group the order above is kept
    return RiskDiff(older, newer, changes)
