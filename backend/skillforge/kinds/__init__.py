"""The kinds this app builds. Insertion order is the order a screen lists them in.

`kinds` imports `build` and `validate` only; `library` (and later the builder and the API) import `kinds`, never
the reverse.
"""

from __future__ import annotations

from .base import Kind, Slot, UnknownKind
from .skill import SkillKind

KINDS: dict[str, Kind] = {"skill": SkillKind()}


def get_kind(key: str) -> Kind:
    try:
        return KINDS[key]
    except KeyError:
        raise UnknownKind(f"'{key}' is not a kind this app builds. It builds: {', '.join(KINDS)}.") from None


def all_kinds() -> list[Kind]:
    return list(KINDS.values())


__all__ = ["KINDS", "Kind", "Slot", "SkillKind", "UnknownKind", "all_kinds", "get_kind"]
