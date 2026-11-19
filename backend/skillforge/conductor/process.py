"""The process for each tier: phases, the file each one reads and writes, how we know it is done, and when to stop.

These are fixed tables, not model output. A later step turns each phase into a skill; this step only plans.
"""

from __future__ import annotations

from .models import Phase

TIER_NAMES = {0: "Trivial", 1: "Small fix", 2: "Feature or refactor", 3: "Complex or risky"}
ARTIFACT_DIR = ".skillforge/tasks/<task>/"


def _p(id_: str, title: str, reads: str, writes: str, gate: str, approval: bool = False) -> Phase:
    return Phase(id=id_, title=title, reads=reads, writes=writes, gate=gate, approval=approval)


_INTAKE = _p("intake", "Plan", "your request", "00-plan.md", "the scope, the allowed files, the rules and the budget are written down and you approved them", True)
_REPORT = _p("report", "Report", "the previous phase's file", "report.md", "what was done, what was not, and what to check is written")


def phases_for(tier: int) -> list[Phase]:
    if tier <= 0:
        return [
            _INTAKE,
            _p("change", "Change", "00-plan.md", "the change itself", "only files named in the plan were touched"),
            _p("verify", "Verify", "the change", "verify.md", "the check that proves it ran, and its result is written"),
            _REPORT,
        ]
    if tier == 1:
        return [
            _INTAKE,
            _p("reproduce", "Reproduce", "00-plan.md", "a failing test", "a test fails for the reason you described"),
            _p("fix", "Fix", "the failing test", "the fix", "the smallest change that makes that test pass"),
            _p("test", "Test", "the fix", "test results", "the whole related test set passes, and none was weakened"),
            _p("review", "Quick review", "the diff", "review.md", "the diff matches the plan and breaks no listed rule"),
            _REPORT,
        ]
    core = [
        _INTAKE,
        _p("requirements", "Requirements", "00-plan.md", "01-requirements.md", "every requirement has an id and at least one acceptance criterion"),
        _p("design", "Design", "01-requirements.md", "02-design.md", "every requirement is addressed by the design", tier >= 2),
        _p("tasks", "Task list", "02-design.md", "03-tasks.md", "every task points to a requirement, and every requirement to a task"),
        _p("implement", "Implement, tests first", "03-tasks.md", "the code and its tests", "each task has a test that failed before and passes now"),
        _p("test", "Test", "the code", "test results", "every acceptance criterion has a passing test"),
        _p("review", "Review", "the diff", "review.md", "the diff matches the plan, and each applicable rule is addressed with evidence", True),
        _REPORT,
    ]
    if tier == 2:
        return core
    extra = [
        _p("risk", "Risk and rollback", "02-design.md", "02a-risk.md", "each risk has a way to detect it and a way to undo the change", True),
        _p("decision", "Decision record", "02-design.md", "02b-decision.md", "the options considered and the reason for the choice are written", True),
        _p("security", "Security review", "the diff", "05a-security.md", "secrets, permissions, inputs and dependencies were each looked at", True),
    ]
    out = core[:3] + extra[:2] + core[3:7] + [extra[2]] + core[7:]
    return [Phase(**{**p.model_dump(), "approval": True}) for p in out]  # tier 3: a person approves every phase


# (condition in plain words, lowest tier it applies to)
STOP_TRIGGERS = [
    ("A question marked blocking is still unanswered.", 0),
    ("An action would touch a file the plan does not allow.", 0),
    ("A rule from the plan would be broken. This is a hard stop, not a question.", 0),
    ("A destructive action is about to happen (delete, overwrite, force).", 0),
    ("A new dependency, a secret, or network access appears.", 1),
    ("The change grows much larger than the plan said.", 1),
    ("The same test fails twice.", 1),
    ("The reading budget is 80% used or exceeded.", 1),
    ("Any phase of a tier 3 task ends.", 3),
]


def stop_triggers_for(tier: int) -> list[str]:
    return [text for text, lowest in STOP_TRIGGERS if tier >= lowest]
