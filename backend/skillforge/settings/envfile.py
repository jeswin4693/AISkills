"""Read and write the git-ignored `.env`, carefully: other lines, comments and the file's own line endings are kept, and the file is
replaced in one step, so a failed write leaves the old file whole (a half-written `.env` would lose every key)."""

from __future__ import annotations

import io
import os
import re
import tempfile
import time
from collections.abc import Mapping
from pathlib import Path

from dotenv.main import DotEnv

from .rules import SettingsError

ASSIGN = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=")
NOTE = "# Added by the SkillForge Settings page"
RETRIES = 4
RETRY_DELAY = 0.15  # seconds; a cloud-synced folder can hold a file for a moment
UNSAFE_LAYOUT = (
    "This page cannot edit safely: the .env file has a layout it does not understand (for example a value that spans several lines, "
    "or a lone carriage return). It was left as it is; edit it by hand."
)


def _ending(line: str) -> str:
    return "\r\n" if line.endswith("\r\n") else "\n" if line.endswith("\n") else ""


def parse_env_text(text: str, *, resolve: bool) -> dict[str, str]:
    """The names and values the server itself would read from this text (python-dotenv's own parser, so what is checked is what is
    used). `resolve` works out ${OTHER} the way `load_dotenv` did: the real environment first, then the file."""
    found = DotEnv(dotenv_path=None, stream=io.StringIO(text), interpolate=resolve, override=False).dict()
    return {name: value for name, value in found.items() if value is not None}


def edit_env_text(text: str, changes: Mapping[str, str | None], *, fold: bool = False) -> str:
    """`text` with each name in `changes` set to its value, or removed when the value is None. Every active copy of a name is
    changed; a commented-out line is left alone; a name that is not there yet is added at the end. With `fold`, a name written in
    another case counts as the same name (Windows treats them so)."""
    text = text.removeprefix("\ufeff")
    newline = "\r\n" if "\r\n" in text else "\n"
    lines = [line for line in re.split(r"(?<=\n)", text) if line]
    seen: set[str] = set()
    out: list[str] = []
    for line in lines:
        match = ASSIGN.match(line.rstrip("\r\n"))
        name = match.group(1) if match else None
        if name is not None and fold and name not in changes and name.upper() in changes:
            name = name.upper()
        if name is None or name not in changes:
            out.append(line)
            continue
        seen.add(name)
        value = changes[name]
        if value is not None:
            out.append(f"{name}={value}{_ending(line) or newline}")
    added = [(name, value) for name, value in changes.items() if value is not None and name not in seen]
    if added:
        if out and not _ending(out[-1]):
            out[-1] += newline
        if NOTE not in text:
            out.append((newline if out else "") + NOTE + newline)
        out.extend(f"{name}={value}{newline}" for name, value in added)
    return "".join(out)


def read_env_values(path: Path) -> dict[str, str] | None:
    """The names and values written in the file, or None when it cannot be read right now (so a caller keeps what it has)."""
    try:
        if not path.is_file():
            return {}
        return parse_env_text(path.read_text(encoding="utf-8-sig"), resolve=True)  # as text, like load_dotenv: a CRLF inside a quoted value reads as a newline
    except (OSError, UnicodeError, ValueError):
        return None


def _expected(old: dict[str, str], changes: Mapping[str, str | None], fold: bool) -> dict[str, str]:
    """What the file should mean after the change: everything it meant before, with exactly the named settings set or removed."""
    out = dict(old)
    for name, value in changes.items():
        for key in [k for k in out if k == name or (fold and k.upper() == name)]:
            del out[key]
        if value is not None:
            out[name] = value
    return out


def write_env_file(path: Path, changes: Mapping[str, str | None], *, fold: bool = False) -> None:
    """Apply `changes` to the file. Raises SettingsError (never with a value in it) when the file cannot be read as text, has a layout
    the line editor would get wrong, or cannot be written. A symbolic link is followed, so the link stays a link."""
    path = Path(os.path.realpath(path))
    try:
        raw = path.read_bytes() if path.exists() else b""
    except OSError as exc:
        raise SettingsError([{"name": "", "message": f"Could not read the .env file ({type(exc).__name__})."}]) from exc
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise SettingsError([{"name": "", "message": "The .env file is not valid UTF-8, so it was left as it is. Fix it by hand."}]) from exc
    updated = edit_env_text(text, changes, fold=fold)
    # The editor works line by line; the server reads the file with python-dotenv, which also knows quoted values over several lines
    # and other line breaks. Whatever the editor did (or failed to do: a name it could not see is not removed), the file must mean
    # exactly what was asked, or nothing is written and the person is told.
    if parse_env_text(updated, resolve=False) != _expected(parse_env_text(text, resolve=False), changes, fold):
        raise SettingsError([{"name": "", "message": UNSAFE_LAYOUT}])
    if updated == text:  # nothing to change (and no empty file is made just to remove a name that was never there)
        return
    tmp = ""
    try:
        fd, tmp = tempfile.mkstemp(prefix=".env.", suffix=".tmp", dir=path.parent)
        with os.fdopen(fd, "wb") as handle:
            handle.write(updated.encode("utf-8"))
            handle.flush()
            os.fsync(handle.fileno())
        for attempt in range(RETRIES):
            try:
                os.replace(tmp, path)
                break
            except PermissionError:
                if attempt == RETRIES - 1:
                    raise
                time.sleep(RETRY_DELAY)
    except OSError as exc:
        raise SettingsError([{"name": "", "message": f"Could not write the .env file ({type(exc).__name__}). Is it read-only, or open in another program?"}]) from exc
    finally:
        if tmp:
            try:
                os.unlink(tmp)
            except OSError:
                pass  # already replaced, or never made
