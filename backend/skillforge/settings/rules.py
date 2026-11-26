"""What a value may look like. A value is one line from a short list of safe characters, so `.env` never needs quoting and nothing
can end the line early or hide inside it. A refusal names the setting and says why; it never repeats the value (it may be a key)."""

from __future__ import annotations

import re
from urllib.parse import urlsplit

from ..providers.factory import supported_names
from .catalogue import Setting

SAFE = re.compile(r"[A-Za-z0-9._~:/,@+=%-]+")  # no space, quote, #, $, backslash, control or invisible character
SAFE_ADDRESS = re.compile(r"[A-Za-z0-9._~:/,@+=%\[\]-]+")  # the same, and square brackets for an IPv6 address such as http://[::1]:1234
INTEGER = re.compile(r"[0-9]{1,9}")
DECIMAL = re.compile(r"[0-9]{1,6}(\.[0-9]{1,6})?")

UNSAFE = (
    "Only letters, digits and . _ ~ : / , @ + = % - can be saved here. If you need anything else, put it in the .env file by hand."
)
LIMITS = {"secret": 400, "text": 200, "url": 300}
MAX_BACKUPS = 10
MAX_BACKUPS_TEXT = 600


class SettingsError(ValueError):
    """One or more settings were refused. `problems` is [{"name", "message"}]; neither ever holds a value the person typed."""

    def __init__(self, problems: list[dict[str, str]]) -> None:
        self.problems = problems
        super().__init__("; ".join(f"{p['name']}: {p['message']}" if p["name"] else p["message"] for p in problems))


def _providers() -> str:
    return ", ".join(supported_names())


def _safe(value: str, limit: int, pattern: re.Pattern[str] = SAFE, unsafe: str = UNSAFE) -> None:
    if len(value) > limit:
        raise ValueError(f"That is too long (the limit is {limit} characters).")
    if not pattern.fullmatch(value):
        raise ValueError(unsafe)


def _provider(value: str) -> str:
    name = value.lower()
    if name not in supported_names():
        raise ValueError(f"That is not a provider this app supports. Use one of: {_providers()}.")
    return name


def _number(setting: Setting, value: str) -> str:
    if not (INTEGER if setting.integer else DECIMAL).fullmatch(value):
        raise ValueError("Use a positive whole number." if setting.integer else "Use a positive number, for example 30 or 2.5.")
    if not 0 < float(value) <= setting.maximum:
        limit = int(setting.maximum) if setting.maximum == int(setting.maximum) else setting.maximum
        raise ValueError(f"Use a number above 0 and at most {limit}.")
    return value


def _address(value: str) -> str:
    _safe(value, LIMITS["url"], SAFE_ADDRESS)
    try:
        parts = urlsplit(value)
        _ = parts.port  # raises ValueError for a port that is not a number or is out of range
        usable = parts.scheme in ("http", "https") and bool(parts.hostname) and "@" not in value
    except ValueError:  # an unmatched bracket, a bad port
        usable = False
    if not usable:
        raise ValueError("Use an address that starts with http:// or https:// and has no login in it, for example http://localhost:1234/v1.")
    return value


def _backups(value: str) -> str:
    _safe(value, MAX_BACKUPS_TEXT)
    items = value.split(",")
    if len(items) > MAX_BACKUPS:
        raise ValueError(f"Use at most {MAX_BACKUPS} backup models.")
    clean = []
    for item in items:
        provider, colon, model = item.partition(":")
        if not colon or not provider or not model:
            raise ValueError("Each backup is provider:model, separated by commas, for example groq:openai/gpt-oss-20b.")
        clean.append(f"{_provider(provider)}:{model}")
    return ",".join(clean)


# ---- a person's own model (slice AI) ------------------------------------------------------------------------------
# The same safe characters as the Settings page. A key travels in an HTTP header, so a control or invisible character in it is never allowed.

# `custom` is left out: it takes an ADDRESS from whoever sets it, which would let a person send the server to any address they type.
PERSON_PROVIDERS: tuple[str, ...] = tuple(name for name in supported_names() if name != "custom")
PERSON_MODEL_LIMIT = 128  # as wide as model_calls.model, so a usage row can always hold it
_QUOTES = "\"'`"
# What a person is told about unsafe characters: the owner's text sends them to the .env file, which a person on a hosted server does not have.
UNSAFE_PERSON = "Only letters, digits and . _ ~ : / , @ + = % - can be used here."


def _person_provider(raw: str) -> str:
    name = raw.strip().lower()
    if name == "custom":
        raise ValueError("The 'custom' provider sends the server to an address you type, so it is not offered here. Choose one of: " + ", ".join(PERSON_PROVIDERS) + ".")
    if name not in PERSON_PROVIDERS:
        raise ValueError("That is not a provider this app supports. Use one of: " + ", ".join(PERSON_PROVIDERS) + ".")
    return name


def _person_model(raw: str) -> str:
    model = raw.strip()
    if not model:
        raise ValueError("Give the model name your key can use, for example the one in your provider's documentation.")
    _safe(model, PERSON_MODEL_LIMIT, unsafe=UNSAFE_PERSON)
    return model


def _person_key(raw: str) -> str:
    key = raw.strip()  # a pasted key often carries a space or a newline at either end
    if not key:
        raise ValueError("Paste your key.")
    if key[0] in _QUOTES or key[-1] in _QUOTES:
        raise ValueError("Remove the quotes around the key: paste only the key itself.")
    if re.match(r"bearer([\s:]|$)", key, re.IGNORECASE):
        raise ValueError("Paste only the key, without the word Bearer in front of it.")
    _safe(key, LIMITS["secret"], unsafe=UNSAFE_PERSON)
    return key


def check_person_model(provider: str, model: str, key: str, *, keep_key: bool = False) -> tuple[str, str, str]:
    """(provider, model, key), cleaned, or SettingsError naming every field that is wrong. A refusal never repeats the key.
    `keep_key`: the person left the key box empty and a saved key stays as it is; the key then comes back as "" (nothing to seal)."""
    cleaned: dict[str, str] = {}
    problems: list[dict[str, str]] = []
    for name, check, raw in (("provider", _person_provider, provider), ("model", _person_model, model), ("key", _person_key, key)):
        if name == "key" and keep_key and not raw.strip():
            cleaned[name] = ""
            continue
        try:
            cleaned[name] = check(raw)
        except ValueError as exc:
            problems.append({"name": name, "message": str(exc)})
    if problems:
        raise SettingsError(problems)
    return cleaned["provider"], cleaned["model"], cleaned["key"]


def check_value(setting: Setting, raw: str) -> str:
    """The value as it will be written, or ValueError saying what is wrong (never the value itself)."""
    value = raw.strip()
    if setting.kind == "secret":
        _safe(value, LIMITS["secret"])
        return value
    if setting.kind == "choice":
        _safe(value, 40)
        return _provider(value)
    if setting.kind == "url":
        return _address(value)
    if setting.kind == "number":
        return _number(setting, value)
    if setting.kind == "flag":
        if value != "1":
            raise ValueError("Use 1 to turn it on, or remove the setting to turn it off.")
        return value
    if setting.name == "LLM_FALLBACKS":
        return _backups(value)
    _safe(value, LIMITS["text"])
    return value
