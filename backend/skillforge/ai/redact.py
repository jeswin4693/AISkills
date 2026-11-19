"""Remove keys from text before it is stored or shown. A safety net: errors come from outside and are kept in the database.

Two things are removed: the exact key values the providers hold, and anything shaped like a common API key or bearer token.
Values shorter than 8 characters are never treated as secrets (they would blank out ordinary words).
"""

from __future__ import annotations

import re
from collections.abc import Iterable

MIN_SECRET = 8
MARK = "[redacted]"
_SHAPES = (
    re.compile(r"AIza[0-9A-Za-z_\-]{20,}"),  # Google
    re.compile(r"sk-ant-[A-Za-z0-9_\-]{16,}"),  # Anthropic
    re.compile(r"sk-[A-Za-z0-9_\-]{20,}"),  # OpenAI and compatible
    re.compile(r"gsk_[A-Za-z0-9]{20,}"),  # Groq
    re.compile(r"\bbearer\s+[A-Za-z0-9._\-]{16,}", re.IGNORECASE),
)


def redact(text: str, secrets: Iterable[str] = ()) -> str:
    out = text
    for secret in sorted({s for s in secrets if s and len(s) >= MIN_SECRET}, key=len, reverse=True):
        out = out.replace(secret, MARK)
    for shape in _SHAPES:
        out = shape.sub(MARK, out)
    return out
