"""An opt-in cache of model answers (SKILLFORGE_LLM_CACHE=1). Off by default, because a hit returns the same answer: a retry
with the same prompt would not get a fresh sample.

Only answers that already passed schema validation are stored, eval replies are never cached, an entry expires after 7 days,
and at most 500 are kept. Entries are files under the per-user data folder (next to the graph cache, outside OneDrive): the
command line never opens the database. An entry holds the model's answer, which is derived from what the person typed, so the
folder is as private as the person's account.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import tempfile
import time
from collections.abc import Callable
from pathlib import Path
from typing import Protocol

from pydantic import BaseModel

log = logging.getLogger(__name__)

_KEY = re.compile(r"^[0-9a-f]{64}\Z")


class ResponseCache(Protocol):
    def get(self, key: str) -> str | None: ...

    def put(self, key: str, text: str) -> None: ...


def cache_key(provider: str, model: str, schema: type[BaseModel], system: str | None, prompt: str) -> str:
    """64 hex characters: the same provider, model, schema, system text and prompt always give the same key."""
    digest = hashlib.sha256()
    for part in (provider, model, json.dumps(schema.model_json_schema(), sort_keys=True), system or "", prompt):
        digest.update(part.encode("utf-8"))
        digest.update(b"\0")
    return digest.hexdigest()


class FileCache:
    def __init__(
        self, root: Path, ttl_s: int = 7 * 24 * 3600, max_entries: int = 500, clock: Callable[[], float] = time.time
    ) -> None:
        self.root = Path(root)
        self.ttl_s = ttl_s
        self.max_entries = max_entries
        self.clock = clock

    def _entry(self, path: Path) -> tuple[float, str] | None:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            stored, text = float(data["stored_at"]), data["text"]
        except (OSError, ValueError, KeyError, TypeError):
            return None
        return (stored, text) if isinstance(text, str) else None

    def get(self, key: str) -> str | None:
        if not _KEY.match(key):  # a key is 64 hex characters and never a path
            return None
        path = self.root / f"{key}.json"
        entry = self._entry(path)
        if entry is None:
            return None
        stored, text = entry
        if self.clock() - stored > self.ttl_s:
            path.unlink(missing_ok=True)
            return None
        return text

    def put(self, key: str, text: str) -> None:
        if not _KEY.match(key):
            return
        try:
            self.root.mkdir(parents=True, exist_ok=True)
            fd, temp = tempfile.mkstemp(dir=self.root, suffix=".tmp")  # written aside, then moved: never half-written
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump({"stored_at": self.clock(), "text": text}, handle)
            os.replace(temp, self.root / f"{key}.json")
            self._prune()
        except OSError:
            log.warning("could not write to the model answer cache", exc_info=True)

    def _prune(self) -> None:
        entries = []
        for path in self.root.glob("*.json"):
            entry = self._entry(path)
            entries.append((entry[0] if entry else 0.0, path))
        for _, path in sorted(entries)[: max(0, len(entries) - self.max_entries)]:
            path.unlink(missing_ok=True)
