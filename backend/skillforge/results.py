"""The shared result type for every check. A check is "passed" only if it ran and succeeded."""

from __future__ import annotations

from dataclasses import dataclass

PASSED = "passed"
WARNING = "warning"  # a heuristic found something a person should read; it does not fail the skill
FAILED = "failed"
NOT_RUN = "not run"


@dataclass
class CheckResult:
    name: str
    status: str
    detail: str = ""
