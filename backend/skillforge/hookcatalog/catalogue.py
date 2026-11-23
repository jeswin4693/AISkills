"""The hook catalogue: the only hooks a plugin made by SkillForge can carry.

A hook runs a program on the person's machine every time its event happens, with the person's permissions and outside any sandbox.
So nobody types one and no model writes one: each entry here is a fixed Python script (standard library only, `scripts/`), a fixed
event, matcher and timeout, and a small set of typed **options** that are checked against a strict pattern and handed to the script as
separate command-line arguments (exec form, no shell), so an option can never become code.

A plugin's `hooks/hooks.json` counts as *described* only when every hook in it is one of these entries with exactly the event,
matcher, timeout, command and arguments written here, and the script shipped beside it is the catalogue's script (compared by
SHA-256, line endings ignored). Anything else is shown to the person and warned about, never trusted.

This module imports nothing from the rest of SkillForge so the validator, the composer and the risk diff can all use it.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

SCRIPTS = Path(__file__).parent / "scripts"
PLUGIN_ROOT = "${CLAUDE_PLUGIN_ROOT}"  # Claude Code replaces it with the folder the plugin is installed in
HOOKS_FILE = "hooks/hooks.json"
HOOKS_DIR = "hooks"
START_COMMAND = "python"


class CatalogueError(ValueError):
    """A hook or an option that the catalogue does not offer."""


@dataclass(frozen=True)
class Option:
    """One thing the person may choose for a hook. Each value must match `pattern` completely and is passed after `flag`."""

    key: str
    label: str
    help: str
    flag: str
    pattern: re.Pattern[str]
    max_items: int
    max_length: int


@dataclass(frozen=True)
class HookEntry:
    id: str
    title: str
    summary: str  # one plain sentence: what it does
    event: str
    matcher: str  # "" means every tool
    effect: str  # "blocks": it can stop what Claude is about to do; "observes": it only looks
    sees: str  # what Claude Code hands it, in plain words
    timeout: int  # seconds
    script: str  # the file in `scripts/`
    powers: frozenset[str] = frozenset()  # what the script is allowed to do on the machine: a subset of {"write_files"}, proven by a test
    options: tuple[Option, ...] = ()
    fixed_args: tuple[str, ...] = ()  # arguments every use gets, after the script's path
    revision: int = 1
    earlier: frozenset[str] = field(default_factory=frozenset)  # SHA-256 of earlier revisions of the script that a plugin may still carry

    @property
    def shipped_path(self) -> str:
        """Where the script sits inside a plugin."""
        return f"{HOOKS_DIR}/{self.id}.py"

    @property
    def command_path(self) -> str:
        """How `hooks.json` names the script (`${CLAUDE_PLUGIN_ROOT}` is the plugin's folder)."""
        return f"{PLUGIN_ROOT}/{self.shipped_path}"


# A file name or a pattern with * and ?: it cannot start with a dash (it could be read as a flag) and must hold a letter or a digit
# (a pattern of only wildcards would block every file).
_SECRET_PATTERN = re.compile(r"(?=.*[A-Za-z0-9])[A-Za-z0-9._*?][A-Za-z0-9._*?-]{0,59}")

CATALOGUE: dict[str, HookEntry] = {
    entry.id: entry
    for entry in (
        HookEntry(
            id="block-secret-files",
            title="Keep secret files out of reach",
            summary=(
                "Stops Claude's file tools (Read, Write, Edit, NotebookEdit) from using files that usually hold secrets: .env files, private keys, "
                "certificates and credential files. It does not see shell commands, so `cat .env` is not stopped."
            ),
            event="PreToolUse",
            matcher="Read|Write|Edit|NotebookEdit",
            effect="blocks",
            sees="the name of the tool and the path of the file it is about to use",
            timeout=10,
            script="block_secret_files.py",
            options=(
                Option(
                    key="also", label="More file names to protect", flag="--also", pattern=_SECRET_PATTERN, max_items=10, max_length=60,
                    help="File names or patterns using * and ? (for example secrets.json or *.token): letters, digits and . _ - * ? only, not starting with a dash, with at least one letter or digit.",
                ),
            ),
        ),
        HookEntry(
            id="block-force-push",
            title="No forced git pushes",
            summary=(
                "Stops Claude from running a git push that forces (--force, -f, --force-with-lease, or a +branch). It reads the command as text, so "
                "an alias or a script that pushes is not seen."
            ),
            event="PreToolUse",
            matcher="Bash|PowerShell",
            effect="blocks",
            sees="the name of the tool and the shell command Claude is about to run",
            timeout=10,
            script="block_force_push.py",
        ),
        HookEntry(
            id="log-tool-calls",
            title="Keep a log of the tools Claude used",
            summary=(
                "Adds one line (the time and the name of the tool, never what it was given) to tool-calls.log in the plugin's data folder after every "
                "tool call. The log is rotated at 1 MB."
            ),
            event="PostToolUse",
            matcher="",
            effect="observes",
            sees="the name of the tool that was just used",
            timeout=10,
            script="log_tool_calls.py",
            powers=frozenset({"write_files"}),
        ),
    )
}


def get_entry(entry_id: str) -> HookEntry:
    try:
        return CATALOGUE[entry_id]
    except KeyError:
        raise CatalogueError(f"'{entry_id}' is not a hook in the catalogue. It offers: {', '.join(CATALOGUE)}.") from None


def _clean(options: Mapping[str, Sequence[str]] | None, entry: HookEntry) -> dict[str, list[str]]:
    """The options for `entry`, validated, or a CatalogueError that says what is wrong."""
    given = dict(options or {})
    known = {o.key: o for o in entry.options}
    unknown = sorted(set(given) - set(known))
    if unknown:
        raise CatalogueError(f"The hook '{entry.id}' has no option {', '.join(repr(k) for k in unknown)}. It has: {', '.join(known) or 'none'}.")
    out: dict[str, list[str]] = {}
    for key, option in known.items():
        values = given.get(key, [])
        if isinstance(values, str) or not isinstance(values, Sequence):
            raise CatalogueError(f"The option '{key}' of '{entry.id}' must be a list of text values.")
        if len(values) > option.max_items:
            raise CatalogueError(f"The option '{key}' of '{entry.id}' may hold at most {option.max_items} values.")
        for value in values:
            if not isinstance(value, str) or len(value) > option.max_length or not option.pattern.fullmatch(value):
                shown = value[:30] if isinstance(value, str) else type(value).__name__
                raise CatalogueError(f"'{shown}' is not allowed in '{key}' of '{entry.id}'. {option.help}")
        if values:
            out[key] = list(dict.fromkeys(values))  # in the order given, each once
    return out


def render_args(entry: HookEntry, options: Mapping[str, Sequence[str]] | None = None) -> list[str]:
    """The `args` of the hook: the script's path, the fixed arguments, then each option as `flag value`. Never joined into one string."""
    clean = _clean(options, entry)
    args = [entry.command_path, *entry.fixed_args]
    for option in entry.options:
        for value in clean.get(option.key, []):
            args += [option.flag, value]
    return args


def parse_args(entry: HookEntry, args: object) -> dict[str, list[str]] | None:
    """The options in `args` when they are exactly what `render_args` writes for this entry, otherwise None."""
    if not isinstance(args, list) or not all(isinstance(a, str) for a in args):
        return None
    head = [entry.command_path, *entry.fixed_args]
    if args[: len(head)] != head:
        return None
    rest = args[len(head):]
    flags = {o.flag: o for o in entry.options}
    options: dict[str, list[str]] = {}
    if len(rest) % 2:
        return None
    for flag, value in zip(rest[::2], rest[1::2]):
        if flag not in flags:
            return None
        options.setdefault(flags[flag].key, []).append(value)
    try:
        clean = _clean(options, entry)
    except CatalogueError:
        return None
    return clean if render_args(entry, clean) == args else None  # same order, no repeats: exactly what would be written


def hook_group(entry: HookEntry, options: Mapping[str, Sequence[str]] | None = None) -> dict:
    """The entry as one matcher group of `hooks.json`."""
    group: dict = {}
    if entry.matcher:
        group["matcher"] = entry.matcher
    group["hooks"] = [{"type": "command", "command": START_COMMAND, "args": render_args(entry, options), "timeout": entry.timeout}]
    return group


def _normal(data: bytes) -> bytes:
    """Line endings do not change what a script does: a Windows checkout may turn LF into CRLF, so compare with LF."""
    return data.replace(b"\r\n", b"\n")


def script_bytes(entry: HookEntry) -> bytes:
    """The catalogue's script for this entry, as it is shipped in a plugin (LF line endings)."""
    return _normal((SCRIPTS / entry.script).read_bytes())


def script_hash(data: bytes) -> str:
    return hashlib.sha256(_normal(data)).hexdigest()


def accepts(entry: HookEntry, data: bytes) -> bool:
    """Whether `data` is this entry's script, current or an earlier revision that is still accepted."""
    digest = script_hash(data)
    return digest == script_hash(script_bytes(entry)) or digest in entry.earlier


def entry_for_script_path(path: object) -> HookEntry | None:
    """The catalogue entry whose script a `hooks.json` command path names, if any."""
    if not isinstance(path, str):
        return None
    return next((e for e in CATALOGUE.values() if e.command_path == path), None)
