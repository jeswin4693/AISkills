"""What each model call cost, kept per builder session. Counts and timings only: never a prompt or a reply."""

from __future__ import annotations

from sqlalchemy import select

from ..ai import UsageRecord
from ..db import Database, ModelCall, now_text


class DbUsageRecorder:
    """Writes one row per attempt for one job of one session. Plugged into the AI service by the builder."""

    def __init__(self, db: Database, session_id: str, job_id: int | None = None) -> None:
        self.db = db
        self.session_id = session_id
        self.job_id = job_id

    def record(self, rec: UsageRecord) -> None:
        with self.db.session() as s:
            s.add(ModelCall(
                session_id=self.session_id, job_id=self.job_id, created_at=now_text(), task=rec.task, tier=rec.tier,
                provider=rec.provider, model=rec.model, attempt=rec.attempt, status=rec.status, error_kind=rec.error_kind,
                input_tokens=rec.input_tokens, output_tokens=rec.output_tokens, latency_ms=rec.latency_ms,
            ))


def usage_summary(db: Database, session_id: str) -> dict:
    """Attempts made for a session, how many failed, tokens the providers reported (None when none did), and models used."""
    with db.session() as s:
        rows = s.execute(select(ModelCall).where(ModelCall.session_id == session_id)).scalars().all()
    known_in = [r.input_tokens for r in rows if r.input_tokens is not None]
    known_out = [r.output_tokens for r in rows if r.output_tokens is not None]
    return {
        "calls": len(rows),
        "errors": sum(r.status == "error" for r in rows),
        "input_tokens": sum(known_in) if known_in else None,
        "output_tokens": sum(known_out) if known_out else None,
        "models": sorted({r.model for r in rows}),
    }
