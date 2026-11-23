"""What a skill cites in a repository, with the facts the graph had at that time. Data only.

`evidence.json` is read strictly (unknown keys, wrong types, over-long text, control or invisible characters and too many
references are refused) and what it holds is only ever used as a key to look something up in a graph and as text to show: it is
never opened as a path, never run and never evaluated. Text that came from the file or from a repository is shown escaped (`safe`),
so no character of it can move a terminal's cursor or reorder a line. The graph's facts are what code computed; a model wrote none.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

EVIDENCE_FILE = "evidence.json"
VERSION = 1
MAX_REFS = 60  # what one skill cites: a skill that needs more is too wide to check
MAX_LIST = 40  # names kept in a list; the true count and a digest of the whole list are stored beside it
MAX_TEXT = 400
MAX_FILE_BYTES = 800_000  # under the static checks' limit for one file (1 MB); read at the moment of use so a test can lower it
DIGEST_LISTS = ("callers", "callees", "symbols", "importers", "imports", "members")

# Control characters, and the invisible or direction-changing ones (the static checks refuse most of them in a skill's text): a name
# that holds one could reorder or hide what a terminal or a page shows.
_UNSAFE = re.compile(
    r"[\x00-\x1f\x7f-\x9f\u00ad\u061c\u180e\u2028\u2029\u200b-\u200f\u202a-\u202e\u2060-\u2064\u2066-\u206f"
    r"\ufe00-\ufe0f\ufeff\U000e0000-\U000e007f]"
)
_HEX = re.compile(r"[0-9a-f]{1,64}")


class EvidenceError(ValueError):
    """The evidence file cannot be used; the message says why."""


def safe(text: str) -> str:
    """`text` with every control, invisible or direction-changing character written out (\\x1b, \\u202e), for showing."""
    def escape(m: re.Match[str]) -> str:
        cp = ord(m.group())
        return f"\\x{cp:02x}" if cp <= 0xFF else f"\\u{cp:04x}" if cp <= 0xFFFF else f"\\U{cp:08x}"

    return _UNSAFE.sub(escape, text)


def _clean(value: str) -> str:
    if _UNSAFE.search(value):
        raise ValueError("control, hidden or direction-changing characters are not allowed")
    return value


class Ref(BaseModel):
    """One cited place and what the graph knew about it. Facts that do not apply to the kind of place stay empty."""

    model_config = ConfigDict(extra="forbid", strict=True)

    id: str = Field(max_length=MAX_TEXT)  # "src/a.py" or "src/a.py::Class.method": a key into the graph
    kind: Literal["file", "symbol"]
    file: str = Field(max_length=MAX_TEXT)
    lang: str = Field("", max_length=40)
    taken_at: str | None = Field(None, max_length=40)  # when this place was recorded (places cited later are recorded later)
    commit: str | None = Field(None, max_length=64)  # the repository's commit then, when it was in git
    dirty: bool = False  # the working tree had uncommitted changes then, so the commit alone does not describe what was read
    measured: bool = True  # False when the language has no resolved calls or imports here: nothing is claimed about them
    # a function, method or class
    symbol_kind: str = Field("", max_length=20)
    line: int = Field(0, ge=0)
    end_line: int = Field(0, ge=0)
    exported: bool = False
    decorated: bool = False
    shape: str | None = Field(None, max_length=80)  # the graph's hash of the body structure (names and values left out); none for a class
    size: int = Field(0, ge=0)
    text_hash: str | None = Field(None, max_length=80)  # a hash of the source text (a decorator included): catches an edit that keeps the structure
    bases: list[str] = Field(default_factory=list, max_length=MAX_LIST)  # a class: its base classes as written
    callers: list[str] = Field(default_factory=list, max_length=MAX_LIST)  # resolved only: a name-only guess is never recorded
    callers_total: int = Field(0, ge=0)
    callees: list[str] = Field(default_factory=list, max_length=MAX_LIST)
    callees_total: int = Field(0, ge=0)
    members: list[str] = Field(default_factory=list, max_length=MAX_LIST)  # a class: the names of its methods
    members_total: int = Field(0, ge=0)
    # a file
    lines: int = Field(0, ge=0)
    symbols: list[str] = Field(default_factory=list, max_length=MAX_LIST)
    symbols_total: int = Field(0, ge=0)
    importers: list[str] = Field(default_factory=list, max_length=MAX_LIST)
    importers_total: int = Field(0, ge=0)
    imports: list[str] = Field(default_factory=list, max_length=MAX_LIST)
    imports_total: int = Field(0, ge=0)
    digests: dict[str, str] = Field(default_factory=dict)  # name of a list -> a digest of the WHOLE sorted list: a cut list is still compared

    @field_validator("id", "file", "lang", "symbol_kind", "shape", "text_hash", "taken_at", "commit")
    @classmethod
    def _text(cls, value: str | None) -> str | None:
        return None if value is None else _clean(value)

    @field_validator("callers", "callees", "symbols", "importers", "imports", "bases", "members")
    @classmethod
    def _items(cls, values: list[str]) -> list[str]:
        for v in values:
            if len(v) > MAX_TEXT:
                raise ValueError("an entry is too long")
            _clean(v)
        return values

    @field_validator("digests")
    @classmethod
    def _digests(cls, values: dict[str, str]) -> dict[str, str]:
        for key, digest in values.items():
            if key not in DIGEST_LISTS or not _HEX.fullmatch(digest):
                raise ValueError("a digest is not one of the known lists, or is not a hex string")
        return values

    def truncated(self, name: str) -> bool:
        """Whether the recorded names of list `name` are fewer than there are (the count and digest still cover all of them)."""
        return getattr(self, f"{name}_total") > len(getattr(self, name))


class Evidence(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    version: Literal[1] = VERSION
    repo: str = Field(max_length=200)  # the folder's name only: a person's paths never travel with a skill
    commit: str | None = Field(None, max_length=64)  # the latest recording's commit
    dirty: bool = False  # ... and whether the working tree had uncommitted changes then
    focus: str | None = Field(None, max_length=MAX_TEXT)  # the folder the graph was limited to, when it was
    taken_at: str = Field(max_length=40)  # the latest recording; each place also carries its own time
    refs: list[Ref] = Field(default_factory=list, max_length=MAX_REFS)

    @field_validator("repo", "commit", "focus", "taken_at")
    @classmethod
    def _text(cls, value: str | None) -> str | None:
        return None if value is None else _clean(value)

    @model_validator(mode="after")
    def _no_repeats(self) -> "Evidence":
        ids = [r.id for r in self.refs]
        if len(set(ids)) != len(ids):
            raise ValueError("a reference is listed twice")
        return self


def evidence_bytes(ev: Evidence) -> bytes:
    """The file's bytes: the same evidence always gives the same bytes, so a version is only made when something differs."""
    return (json.dumps(ev.model_dump(mode="json"), indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def fit(ev: Evidence) -> tuple[Evidence, int]:
    """`ev` with places dropped from the end until its file fits the reader's limit, and how many were dropped. A file that is too
    large would be refused by the next import, so nothing larger than the limit is ever written."""
    dropped = 0
    while ev.refs and len(evidence_bytes(ev)) > MAX_FILE_BYTES:
        ev = ev.model_copy(update={"refs": ev.refs[:-1]})
        dropped += 1
    return ev, dropped


def read_evidence(files: Mapping[str, bytes]) -> Evidence | None:
    """The evidence in a folder's files, None when there is none, EvidenceError when there is a file that cannot be used."""
    data = files.get(EVIDENCE_FILE)
    if data is None:
        return None
    if len(data) > MAX_FILE_BYTES:
        raise EvidenceError(f"{EVIDENCE_FILE} is larger than {MAX_FILE_BYTES // 1000} KB")
    try:
        doc = json.loads(data.decode("utf-8-sig"))  # a byte-order mark is not a reason to refuse
    except RecursionError as exc:
        raise EvidenceError(f"{EVIDENCE_FILE} is nested too deeply to read") from exc
    except (UnicodeDecodeError, ValueError) as exc:
        raise EvidenceError(f"{EVIDENCE_FILE} is not valid JSON ({type(exc).__name__})") from exc
    if not isinstance(doc, dict):
        raise EvidenceError(f"{EVIDENCE_FILE} must be one JSON object")
    try:
        return Evidence.model_validate(doc)
    except ValidationError as exc:
        first = exc.errors()[0]
        where = ".".join(str(p) for p in first["loc"]) or "the file"
        # the location can be a key the file's author chose: it is shown escaped, like everything else that came from the file
        raise EvidenceError(f"{EVIDENCE_FILE} is not valid evidence ({safe(where)[:120]}: {safe(first['msg'])[:160]})") from exc
