"""Small helpers the adapters share when they turn a vendor's error into a `ProviderError`."""

from __future__ import annotations

import re
from collections.abc import Mapping

MAX_DETAIL = 600
_RETRY_IN = re.compile(r"retry in ([0-9]+(?:\.[0-9]+)?)\s*s", re.IGNORECASE)


def short(text: object, limit: int = MAX_DETAIL) -> str:
    """One line, at most `limit` characters: what is shown back to a model or in a message."""
    return " ".join(str(text).split())[:limit]


def retry_after(headers: Mapping[str, str] | None, message: str) -> float | None:
    """Seconds the provider asked us to wait: the `Retry-After` header when it is a number, else "retry in 12.5s" in the
    message (a heuristic: some providers say it only there). A date, or nothing, gives None."""
    value = headers.get("retry-after") if headers is not None else None
    if value:
        try:
            seconds = float(value)
            if seconds >= 0:
                return seconds
        except ValueError:
            pass
    found = _RETRY_IN.search(message or "")
    return float(found.group(1)) if found else None
