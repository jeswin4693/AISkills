"""Cleaning the usage table: records older than a set number of days go, today's never do (slice AK).

`model_calls` keeps one row per attempt at a model: counts and timings, never a prompt or a reply. A discarded build keeps its rows (they are the
ledger a person's daily allowance on the server's model is counted from, `builder/model_access.py`), so the table only ever grew.

* `SKILLFORGE_USAGE_KEEP_DAYS` (default 90, `0` keeps everything for ever) says how many days of rows to keep.
* The clean-up runs once when the server starts and then at most once a day, from the moment a build, a suggestion run or a Testing Lab run asks for its model.
* **Nothing it counts for the allowance is ever touched.** The allowance reads only today's rows (UTC), and the line the clean-up draws is never later
  than today's midnight, whatever the number of days says.
* A value that is not understood deletes nothing (it is not guessed) and is logged. A clean-up that fails is logged and never fails a person's build.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable, Mapping
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete

from ..db import Database, ModelCall
from .model_access import utc_now

log = logging.getLogger(__name__)

SETTING = "SKILLFORGE_USAGE_KEEP_DAYS"
DEFAULT_KEEP_DAYS = 90
MAX_KEEP_DAYS = 36500  # a hundred years: more than any server will run
DUE_AFTER = timedelta(hours=24)


def keep_days_from_env(environ: Mapping[str, str]) -> int:
    """How many days of usage rows to keep. Unset or blank is the default (90). A whole number from 0 to 36500 is that number (0 keeps everything).
    Anything else (a negative number, a decimal, text, too large) is 0, which deletes nothing, with one warning: a setting that deletes data is never guessed."""
    text = (environ.get(SETTING) or "").strip()
    if not text:
        return DEFAULT_KEEP_DAYS
    if text.isascii() and text.isdigit() and int(text) <= MAX_KEEP_DAYS:
        return int(text)
    log.warning("%s must be a whole number of days from 0 to %d (0 keeps everything); it was not understood, so no usage records are deleted.", SETTING, MAX_KEEP_DAYS)
    return 0


def prune_usage(db: Database, keep_days: int, now: datetime) -> int:
    """Delete the usage rows older than `keep_days` days and return how many went. 0 (or less) deletes nothing.

    The line is `min(now - keep_days, today's midnight UTC)`, written as the same ISO text the allowance compares with, so a row of today is never
    older than it, even for one day kept just after midnight."""
    if keep_days <= 0:
        return 0
    now = now.astimezone(timezone.utc)
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    cutoff = min(now - timedelta(days=keep_days), midnight).strftime("%Y-%m-%dT%H:%M:%S")
    with db.session() as s:
        return s.execute(delete(ModelCall).where(ModelCall.created_at < cutoff)).rowcount


class UsageRetention:
    """Runs `prune_usage` the first time it is asked, and then at most once in 24 hours."""

    def __init__(self, db: Database, keep_days: int, clock: Callable[[], datetime] = utc_now) -> None:
        self.db = db
        self.keep_days = keep_days
        self.clock = clock
        self._last: datetime | None = None
        self._lock = threading.Lock()

    def run_if_due(self) -> int:
        """The number of rows deleted (0 when it was not due, when nothing is kept off, or when it failed). Never raises. A failed attempt counts as
        an attempt: a broken database is not hit again by every build, only by the next day's."""
        if self.keep_days <= 0:
            return 0
        now = self.clock()
        with self._lock:
            if self._last is not None and now - self._last < DUE_AFTER:
                return 0
            self._last = now
        try:
            return prune_usage(self.db, self.keep_days, now)
        except Exception as exc:  # noqa: BLE001 - nothing about keeping a table tidy may stop a person's work
            log.warning("the usage records could not be cleaned (%s); trying again tomorrow", type(exc).__name__)
            return 0
