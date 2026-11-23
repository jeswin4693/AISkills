"""The settings as they are now: what `.env` says, what this running process has, and where each value comes from.

A real environment variable always wins over the file (that is how `.env` has always worked here), so a setting that comes from the
environment is shown but cannot be changed from the page: a save would silently stop applying at the next restart. A value this
class put into the process from the file is remembered, so the page can tell the two apart, pick up a hand edit of the file, and apply
a save at once, with no restart.

A key is never returned from here: a secret row says only "set" or "not set".
"""

from __future__ import annotations

import os
import threading
from collections.abc import MutableMapping
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlsplit

from ..providers.factory import supported_names
from .catalogue import GROUPS, Setting, catalogue, setting_named
from .envfile import read_env_values, write_env_file
from .rules import SettingsError, check_value

_LOCK = threading.RLock()  # one change at a time, in this process (the file is one shared thing)
FOLD_CASE = os.name == "nt"  # Windows treats environment names without regard to case, so `google_api_key` is `GOOGLE_API_KEY` there


def _fold(name: str) -> str:
    return name.upper() if FOLD_CASE else name


def default_env_file() -> Path:
    """The `.env` at the root of the repository, next to the backend folder (tests point this somewhere else)."""
    return Path(__file__).resolve().parents[3] / ".env"


INVALID_ADDRESS = "(not a valid address)"


def _plain_address(value: str) -> str:
    """An address as it is safe to show: no login and no query, which a hand-written one might carry."""
    try:
        parts = urlsplit(value)
        host = parts.hostname or ""
        if not parts.scheme or not host:
            return ""
        port = f":{parts.port}" if parts.port else ""
        host = f"[{host}]" if ":" in host else host  # an IPv6 literal keeps its brackets
        return f"{parts.scheme}://{host}{port}{parts.path}"
    except ValueError:
        return INVALID_ADDRESS if value.strip() else ""


class EnvSettings:
    def __init__(self, path: Path | None = None, environ: MutableMapping[str, str] | None = None) -> None:
        self.path = path if path is not None else default_env_file()
        self.environ: MutableMapping[str, str] = os.environ if environ is None else environ
        self._applied: dict[str, str] = {}  # name -> the value this class put into the process from the file

    # ---- keeping the process in step with the file -----------------------------------------------------------

    def sync(self) -> None:
        """Bring the process up to date with the file. A name the page manages that was set from the file follows the file when its
        value changes. A real environment variable (or anything else that set a value in this process) is never overwritten. A name
        taken out of the file by hand is NOT dropped from a running server (a half-written file must never look like "every setting
        was removed"): only a save from the page removes one. Any other name in the file is applied once when it is not set yet,
        exactly as `load_dotenv` always did. A file that cannot be read right now changes nothing."""
        with _LOCK:
            self._sync()

    def snapshot(self) -> dict[str, str]:
        """One consistent copy of the settings, taken after a sync and under the same lock as every change, so a model lookup
        never sees half of a save."""
        with _LOCK:
            self._sync()
            return dict(self.environ)

    def _sync(self) -> bool:
        """True when the file could be read (a missing file counts: there is nothing to read)."""
        values = read_env_values(self.path)
        if values is None:
            return False
        for name in list(self._applied):
            if self.environ.get(name) != self._applied[name]:  # something else changed it: it is no longer ours
                del self._applied[name]
        for raw_name, value in values.items():
            name = _fold(raw_name)
            if name in self._applied:
                if self._applied[name] != value:
                    self.environ[name] = self._applied[name] = value
            elif name not in self.environ:
                self.environ[name] = value
                if setting_named(name) is not None:  # only what the page manages is followed afterwards
                    self._applied[name] = value
            # else: the environment already has it, and wins
        return True

    def _source(self, name: str) -> str:
        value = self.environ.get(name)
        if value is None:
            return "unset"
        return "file" if self._applied.get(name) == value else "environment"

    # ---- what the page shows ------------------------------------------------------------------------------------

    def view(self) -> dict:
        with _LOCK:
            readable = self._sync()
            return {
                "file": ".env", "file_exists": self.path.is_file(), "file_readable": readable, "groups": [dict(g) for g in GROUPS],
                "settings": [self._row(s) for s in catalogue()],
            }

    def _row(self, s: Setting) -> dict:
        source = self._source(s.name)
        value = self.environ.get(s.name, "")
        row = {
            "name": s.name, "group": s.group, "label": s.label, "help": s.help, "kind": s.kind, "provider": s.provider,
            "choices": supported_names() if s.kind == "choice" else [], "set": bool(value.strip()), "source": source,
            "editable": source != "environment",
        }
        if s.kind != "secret":  # a key is never sent, not even its end or its length
            row["value"] = _plain_address(value) if s.kind == "url" else value
        return row

    # ---- changing ------------------------------------------------------------------------------------------------

    def apply(self, changes: object) -> None:
        """Set (a text) or remove (None or empty) each named setting, all or nothing. Raises SettingsError listing what is wrong,
        with the setting's name and a reason, never the value."""
        if not isinstance(changes, dict) or not changes:
            raise SettingsError([{"name": "", "message": "There is nothing to save."}])
        with _LOCK:
            self._sync()
            problems: list[dict[str, str]] = []
            clean: dict[str, str | None] = {}
            for name, raw in changes.items():
                setting = setting_named(name)
                if setting is None:
                    problems.append({"name": "", "message": "One of the names is not a setting this page can change."})
                elif self._source(name) == "environment":
                    problems.append({"name": name, "message": "It is set in this computer's environment, outside the .env file, so it cannot "
                                     "be changed here. Change or remove it there, then restart the server."})
                elif raw is None:
                    clean[name] = None
                elif not isinstance(raw, str):
                    problems.append({"name": name, "message": "It must be text."})
                elif not raw.strip():
                    clean[name] = None
                else:
                    try:
                        clean[name] = check_value(setting, raw)
                    except ValueError as exc:
                        problems.append({"name": name, "message": str(exc)})
            if problems:
                raise SettingsError(problems)
            write_env_file(self.path, clean, fold=FOLD_CASE)
            for name, value in clean.items():
                if value is None:  # a removal from the page is the one thing that does drop a value from the running server
                    self.environ.pop(name, None)
                    self._applied.pop(name, None)
            self._sync()


@lru_cache(maxsize=8)
def _shared(path: str) -> EnvSettings:
    return EnvSettings(Path(path))


def default_settings() -> EnvSettings:
    """The one `EnvSettings` for the real `.env` and the real environment, shared by the model lookup and the Settings page."""
    return _shared(str(default_env_file()))
