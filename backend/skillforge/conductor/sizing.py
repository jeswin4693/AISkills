"""How big is this task, and so how much process does it need? Decided by code from measured facts, never by a model.

The tier is the HIGHEST of every signal below. A person may raise it; lowering it needs an explicit confirmation and is
recorded. If nothing could be measured (no repository, or no target named), the tier is only the baseline for that kind
of task, and the plan says so.
"""

from __future__ import annotations

import fnmatch
import re
from collections.abc import Sequence

from .models import Reach, Signal, StatedItem, TierDecision

BASELINE = {"docs": 0, "bugfix": 1, "investigation": 1, "feature": 2, "refactor": 2, "migration": 3, "other": 2}
CODE_TASKS = {"feature", "bugfix", "refactor", "migration"}

# Whole words in a path segment that mark code people are careful with. "token" is left out on purpose: it names too
# many harmless files (a tokenizer, tokens.py).
SENSITIVE_WORDS = {
    "auth", "authn", "authz", "oauth", "jwt", "security", "secret", "secrets", "credential", "credentials", "password",
    "passwords", "crypto", "encrypt", "encryption", "permission", "permissions", "payment", "payments", "billing",
    "migration", "migrations", "terraform", "dockerfile",
}
REACH_FILES = ((20, 3), (6, 2))  # (files reached at least, tier floor)
# Only a HIGH rating raises the tier. The graph's "medium" includes a penalty for having no test tied, which would send
# every small fix of untested code to a full design phase; the size of the change is measured by the file count instead.
RISK_FLOOR = {"high": 3}


def sensitive_reason(path: str, extra: Sequence[str] = ()) -> str | None:
    """Why a path counts as sensitive, or None."""
    p = path.replace("\\", "/").lower()
    for pattern in extra:
        if fnmatch.fnmatch(p, pattern.lower()):
            return f"matches your pattern '{pattern}'"
    if ".github/workflows/" in p:
        return "is a CI workflow"
    for part in p.split("/"):
        if part.startswith(".env"):
            return "is an environment file"
        for word in re.split(r"[^a-z0-9]+", part):
            if word in SENSITIVE_WORDS:
                return f"has '{word}' in its path"
    return None


def decide_tier(
    task_type: str, reach: Sequence[Reach], mentioned_files: Sequence[str], declared_risks: Sequence[StatedItem], *,
    sensitive: Sequence[str] = (), override: int | None = None, allow_lower: bool = False,
) -> TierDecision:
    baseline = BASELINE.get(task_type, 2)
    signals = [Signal(name="kind of task", floor=baseline, evidence=f"a '{task_type}' task starts at tier {baseline}")]
    measured = bool(reach)
    files = {f for r in reach for f in r.files_reached} | set(mentioned_files)

    for need, floor in REACH_FILES:
        if len(files) >= need:
            signals.append(Signal(name="size of the change", floor=floor, evidence=f"the named code reaches {len(files)} files by proven links"))
            break
    for r in reach:
        floor = RISK_FLOOR.get(r.risk)
        if floor:
            signals.append(Signal(name="risk of the named code", floor=floor, evidence=f"{r.target}: the graph rates a change to it {r.risk}"))
    seen: set[str] = set()
    for path in sorted(files):
        why = sensitive_reason(path, sensitive)
        if why and path not in seen:
            seen.add(path)
            signals.append(Signal(name="sensitive code", floor=3, evidence=f"{path} {why}"))
    for item in declared_risks:
        signals.append(Signal(name="risk you named", floor=3, evidence=f'you said: "{item.quote}"'))

    tier = max(s.floor for s in signals)
    note = ""
    if task_type in CODE_TASKS and not measured:
        note = "Nothing could be measured, so this is only the starting tier for this kind of task. Name the files or functions to measure it."
    if override is not None:
        if override > tier:
            signals.append(Signal(name="raised by you", floor=override, evidence=f"you asked for tier {override}"))
            tier = override
        elif override < tier:
            if allow_lower:
                note = (note + " " if note else "") + f"You lowered the tier from {tier} to {override}. The signals above still apply."
                tier = override
            else:
                note = (note + " " if note else "") + f"You asked for tier {override}, but the evidence says {tier}. Lowering needs an explicit confirmation, so {tier} stays."
    return TierDecision(tier=max(0, min(3, tier)), baseline=baseline, signals=signals, measured=measured, note=note)
