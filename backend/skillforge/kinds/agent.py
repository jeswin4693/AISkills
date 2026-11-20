"""The agent kind: a folder with an `AGENT.md` (a Claude Code subagent definition) that installs as one file, `<name>.md`."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import asdict
from pathlib import Path

from ..build.agent import AGENT_EXTRACT_SYSTEM, AGENT_QUESTIONS
from ..build.agent_pipeline import AgentBuildResult, build_agent_from_spec
from ..build.models import SLOTS, RequirementSpec
from ..build.pipeline import Round, understand_round
from ..build.scripts import ScriptRunner
from ..providers.base import LLMProvider
from .base import BuildOutcome, Kind, Slot
from .skill import MAX_REPORT, name_in_front_matter

AGENT_SLOT_LABELS = {
    "goal": "What it is for",
    "inputs": "What it is given",
    "outputs": "What it reports back",
    "constraints": "Rules it must follow",
    "acceptance_criteria": "How we will know it works",
    "failure_behavior": "When it cannot finish",
}


def summarize_agent(result: AgentBuildResult) -> dict:
    """The build result as the plain dict a session stores and the pages read (the same shape as a skill's)."""
    ran = [c for c in result.checks if c.status != "not run"]
    failed = sum(c.status == "failed" for c in ran)
    warned = sum(c.status == "warning" for c in ran)
    report = (result.out_dir / "report.md").read_text(encoding="utf-8")[:MAX_REPORT]
    return {
        "status": result.status, "draft_reason": result.draft_reason, "name": result.definition.name,
        "description": result.definition.description, "folder": result.out_dir.name, "files": result.files,
        "scripts": 0, "report_md": report,
        "counts": {"passed": len(ran) - failed - warned, "warning": warned, "failed": failed, "not_run": len(result.checks) - len(ran)},
        "checks": [asdict(c) for c in result.checks],
        "tokens": None,  # the token cost estimate is skill-only so far
    }


class AgentKind(Kind):
    key = "agent"
    label = "Agent"
    library_dir = "library-agent"
    definition_file = "AGENT.md"
    install_file = "AGENT.md"
    slots = tuple(Slot(key, AGENT_SLOT_LABELS[key], AGENT_QUESTIONS[key]) for key in SLOTS)

    def name_of(self, files: Mapping[str, bytes]) -> str | None:
        return name_in_front_matter(files, self.definition_file)

    def personal_dir(self) -> Path:
        return Path.home() / ".claude" / "agents"  # worked out per call, so a test (or a changed HOME) is honoured

    def understand(self, provider: LLMProvider, words: str, round_no: int, max_rounds: int) -> Round:
        # the person chose to build an agent, so what the extraction calls the request never blocks it
        return understand_round(
            provider, words, round_no, max_rounds, questions=AGENT_QUESTIONS, extract_system=AGENT_EXTRACT_SYSTEM, skill_only=False,
        )

    def build(
        self, spec: dict, provider: LLMProvider, *, out_root: Path, with_scripts: bool, script_runner: ScriptRunner | None,
        sandbox_note: str, calls: int, notes: list[str], progress: Callable[[str], None],
    ) -> BuildOutcome:
        # an agent has no scripts, so with_scripts, script_runner and sandbox_note do not apply
        result = build_agent_from_spec(
            RequirementSpec.model_validate(spec), provider, out_root=out_root, force=True, calls=calls, notes=notes, progress=progress,
        )
        return BuildOutcome(summarize_agent(result), result.model_calls, result.notes)
