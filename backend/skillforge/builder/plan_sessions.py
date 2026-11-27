"""Kept Task Plans (slice AN, docs/plan-approval.md): a plan is kept as it was made, a person answers its questions and decides on its assumptions, and approves it.

The bookkeeping is the same shape as the other kept runs (`scans.py`): a row, one place that finds a row for a person, and a revision that every save and every approval
has to name, so a person can only approve what was on their screen and a second window cannot silently overwrite the first. What is DECIDED is all in
`conductor/approval.py`: what counts as an answer, what stops an approval, the fingerprint and the text. No model is asked anything here.

A kept plan is the request and the plan, never a file's contents and never the repository's folder (only its name). An approved plan is locked until it is reopened, and
reopening is recorded. Another person's plan is "no such plan", the very answer for one that never existed.
"""

from __future__ import annotations

import re
import threading
import uuid
from typing import Any

from pydantic import ValidationError
from sqlalchemy import func, select, update

from ..conductor import TaskPlan, process
from ..conductor.approval import Answers, ApprovalError, blocked_message, fingerprint, missing, read_answers, render_approved, unanswered
from ..db import LOCAL_USER_ID, Database, PlanSession, now_text
from .errors import ApprovalBlocked, BadRequest, SessionNotFound, WrongState
from .limits import LimitReached

MAX_KEPT = 200  # plans a person may keep; deleting one makes room
MAX_EVENTS = 200  # the log keeps the newest of these
TASK_SHOWN = 200  # characters of a request the list shows
_ID = re.compile(r"^[0-9a-f]{32}\Z")
_KEEP = threading.Lock()  # one check-then-add at a time, so two plans made together cannot both take the last place

CHANGED = "This plan was changed in another window. Reload it to see where it stands."
UNREADABLE = "This plan was made by an older version of the app and cannot be shown. Delete it and make the plan again."


def _cut(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit].rstrip() + "…"


def _plan_of(row: PlanSession) -> TaskPlan:
    try:
        return TaskPlan.model_validate(row.plan)
    except ValidationError as exc:
        raise BadRequest(UNREADABLE) from exc


def _events(old: list, what: str, at: str) -> list[dict[str, str]]:
    return [*old, {"at": at, "what": what}][-MAX_EVENTS:]


def _approval_view(row: PlanSession, answers: Answers) -> dict[str, Any] | None:
    """The approval as shown: when, the tier, the fingerprint, and whether the kept plan and answers still make that fingerprint (a check that ran: it fails if the
    stored record was changed by hand, or by a bug, after the approval)."""
    if not row.approval:
        return None
    a = row.approval
    return {
        "approved_at": a["approved_at"], "fingerprint": a["fingerprint"], "tier": a["tier"],
        "intact": fingerprint(row.plan, answers) == a["fingerprint"],
    }


def _view(row: PlanSession) -> dict[str, Any]:
    """The whole plan session as a page reads it. `plan` has the same fields as the answer of `POST /api/plan`, and its `markdown` holds the answers and the approval."""
    plan = _plan_of(row)
    answers = Answers.from_json(row.answers)
    approval = _approval_view(row, answers)
    stops = missing(plan, answers)
    return {
        "id": row.id, "status": row.status, "created_at": row.created_at, "updated_at": row.updated_at, "rev": row.rev,
        "plan": {**row.plan, "markdown": render_approved(plan, answers, approval)},
        "questions": [
            {"index": i, "question": g.question, "why": g.why, "blocking": g.blocking, "source": g.source, "answer": answers.questions.get(i)}
            for i, g in enumerate(plan.reading.gaps)
        ],
        "assumptions": [
            {"index": i, "text": x.text, "why": x.why, "decision": answers.assumptions.get(i)} for i, x in enumerate(plan.reading.assumptions)
        ],
        "missing": stops, "unanswered": unanswered(plan, answers), "can_approve": row.status == "open" and not stops,
        "approval": approval, "events": row.events,
    }


def _summary(row: PlanSession) -> dict[str, Any]:
    """What the list shows: enough to tell the plans apart and see where each stands, without the plan."""
    head = {
        "id": row.id, "status": row.status, "created_at": row.created_at, "updated_at": row.updated_at, "approved_at": row.approved_at,
        "task": _cut(row.task, TASK_SHOWN), "repo": row.repo_name, "mode": row.mode,
    }
    try:
        plan = _plan_of(row)
    except BadRequest:
        return {**head, "readable": False}
    answers = Answers.from_json(row.answers)
    gaps, held = plan.reading.gaps, plan.reading.assumptions
    return {
        **head, "readable": True, "tier": plan.tier.tier, "tier_name": process.TIER_NAMES[plan.tier.tier],
        "questions": {
            "total": len(gaps), "blocking": sum(1 for g in gaps if g.blocking), "answered": sum(1 for i in answers.questions if i < len(gaps)),
            "blocking_answered": sum(1 for i, g in enumerate(gaps) if g.blocking and i in answers.questions),
        },
        "assumptions": {"total": len(held), "decided": sum(1 for i in answers.assumptions if i < len(held))},
    }


class PlanSessions:
    def __init__(self, db: Database) -> None:
        self.db = db

    def _row(self, s, pid: str, user: str) -> PlanSession:
        """A plan, if it is `user`'s. Someone else's is "no such plan", the very answer for one that never existed. `user` has no default here so a caller cannot forget it."""
        row = s.get(PlanSession, pid) if _ID.match(pid or "") else None
        if row is None or row.user_id != user:
            raise SessionNotFound("There is no such plan.")
        return row

    def _room(self, s, user: str) -> None:
        kept = s.execute(select(func.count()).select_from(PlanSession).where(PlanSession.user_id == user)).scalar_one()
        if kept >= MAX_KEPT:
            raise LimitReached("plans", f"You have {kept} kept plans, the most that are kept. Delete some you no longer need, then make the plan again.")

    def check_room(self, user: str = LOCAL_USER_ID) -> None:
        """Refuse before a plan is made (which can ask a model) when it could not be kept."""
        with self.db.session() as s:
            self._room(s, user)

    def keep(self, plan: dict[str, Any], user: str = LOCAL_USER_ID) -> dict[str, Any]:
        """Keep a plan as `plan_task` made it (its Markdown is left out: it is written again whenever the plan is read, with the answers)."""
        stored = {k: v for k, v in plan.items() if k != "markdown"}
        TaskPlan.model_validate(stored)  # what is kept can be read again
        pid, stamp = uuid.uuid4().hex, now_text()
        with _KEEP, self.db.session() as s:
            self._room(s, user)
            row = PlanSession(
                id=pid, created_at=stamp, updated_at=stamp, status="open", task=stored["prompt"], repo_name=stored.get("repo") or "", mode=stored["mode"],
                plan=stored, answers=Answers({}, {}).as_json(), rev=0, approved_at=None, approval=None, events=[{"at": stamp, "what": "made"}], user_id=user,
            )
            s.add(row)
            return _view(row)

    def get(self, pid: str, user: str = LOCAL_USER_ID) -> dict[str, Any]:
        with self.db.session() as s:
            return _view(self._row(s, pid, user))

    def list(self, user: str = LOCAL_USER_ID, limit: int = 50) -> list[dict[str, Any]]:
        query = select(PlanSession).where(PlanSession.user_id == user).order_by(PlanSession.created_at.desc(), PlanSession.id.desc()).limit(limit)
        with self.db.session() as s:
            return [_summary(r) for r in s.execute(query).scalars().all()]

    def save_answers(self, pid: str, rev: int, questions: dict[str, Any], assumptions: dict[str, Any], user: str = LOCAL_USER_ID) -> dict[str, Any]:
        """Replace the answers and decisions with these (a blank one is none). `rev` is the state the person was looking at; the same answers again change nothing."""
        with self.db.session() as s:
            row = self._row(s, pid, user)
            plan = _plan_of(row)
            if row.status == "approved":
                raise WrongState("This plan is approved, so its answers are locked. Reopen it to change them.")
            if rev != row.rev:
                raise WrongState(CHANGED)
            try:
                new = read_answers(plan, questions, assumptions)
            except ApprovalError as exc:
                raise BadRequest(str(exc)) from exc
            if new.as_json() == row.answers:
                return _view(row)
            stamp = now_text()
            claimed = s.execute(
                update(PlanSession).where(PlanSession.id == pid, PlanSession.rev == rev, PlanSession.status == "open")
                .values(answers=new.as_json(), rev=rev + 1, updated_at=stamp, events=_events(row.events, "answers saved", stamp))
            ).rowcount == 1
            if not claimed:
                raise WrongState(CHANGED)
            s.refresh(row)
            return _view(row)

    def approve(self, pid: str, rev: int, user: str = LOCAL_USER_ID) -> dict[str, Any]:
        """Approve exactly the state `rev` names, if code's checklist is met: every blocking question answered and every assumption decided."""
        with self.db.session() as s:
            row = self._row(s, pid, user)
            plan = _plan_of(row)
            if row.status == "approved":
                raise WrongState("This plan is already approved.")
            if rev != row.rev:
                raise WrongState(CHANGED)
            answers = Answers.from_json(row.answers)
            stops = missing(plan, answers)
            if stops:
                raise ApprovalBlocked(blocked_message(stops), stops)
            stamp = now_text()
            approval = {"approved_at": stamp, "fingerprint": fingerprint(row.plan, answers), "tier": plan.tier.tier, "rev": row.rev}
            claimed = s.execute(
                update(PlanSession).where(PlanSession.id == pid, PlanSession.rev == rev, PlanSession.status == "open")
                .values(status="approved", approved_at=stamp, approval=approval, updated_at=stamp, events=_events(row.events, "approved", stamp))
            ).rowcount == 1
            if not claimed:  # another request approved or changed it between the read and the write
                raise WrongState(CHANGED)
            s.refresh(row)
            return _view(row)

    def reopen(self, pid: str, user: str = LOCAL_USER_ID) -> dict[str, Any]:
        """Withdraw an approval. The answers stay and the log says it happened; nothing is lost, and the plan can be changed and approved again."""
        with self.db.session() as s:
            row = self._row(s, pid, user)
            if row.status != "approved":
                raise WrongState("This plan is not approved, so there is nothing to reopen.")
            stamp = now_text()
            claimed = s.execute(
                update(PlanSession).where(PlanSession.id == pid, PlanSession.status == "approved")
                .values(status="open", approved_at=None, approval=None, updated_at=stamp, events=_events(row.events, "reopened", stamp))
            ).rowcount == 1
            if not claimed:
                raise WrongState(CHANGED)
            s.refresh(row)
            return _view(row)

    def delete(self, pid: str, user: str = LOCAL_USER_ID) -> None:
        with self.db.session() as s:
            s.delete(self._row(s, pid, user))
