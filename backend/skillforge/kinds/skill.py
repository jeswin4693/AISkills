"""The skill kind: a folder with a SKILL.md whose front matter names it."""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from dataclasses import asdict
from pathlib import Path

import yaml

from ..build.models import SLOTS, RequirementSpec
from ..build.pipeline import BuildResult, Round, build_from_spec, understand_round
from ..build.requirements import QUESTIONS
from ..build.scripts import ScriptRunner
from ..providers.base import LLMProvider
from ..validate.static import MAX_NAME, SLUG
from .base import BuildOutcome, Kind, Slot

MAX_REPORT = 200_000

# The labels the web UI shows for each slot (frontend/src/lib/builder.ts, SLOT_LABEL).
SLOT_LABELS = {
    "goal": "Goal",
    "inputs": "What it receives",
    "outputs": "What it produces",
    "constraints": "Rules it must respect",
    "acceptance_criteria": "How we will know it works",
    "failure_behavior": "When something goes wrong",
}


def name_in_front_matter(files: Mapping[str, bytes], filename: str) -> str | None:
    """The name in `filename`'s front matter, or None when it is missing or not a safe name."""
    try:
        text = files[filename].decode("utf-8").replace("\r\n", "\n")
        match = re.match(r"---\n(.*?)\n---\n", text, re.DOTALL)
        meta = yaml.safe_load(match.group(1)) if match else None
    except (KeyError, UnicodeDecodeError, yaml.YAMLError):
        return None
    name = meta.get("name") if isinstance(meta, dict) else None
    return name if isinstance(name, str) and SLUG.match(name) and len(name) <= MAX_NAME else None


def skill_name_of(files: Mapping[str, bytes]) -> str | None:
    """The name in SKILL.md's front matter, or None when it is missing or not a safe name."""
    return name_in_front_matter(files, "SKILL.md")


def summarize(result: BuildResult) -> dict:
    """The build result as the plain dict a session stores and the pages read."""
    ran = [c for c in result.checks if c.status != "not run"]
    failed = sum(c.status == "failed" for c in ran)
    warned = sum(c.status == "warning" for c in ran)
    report = (result.out_dir / "report.md").read_text(encoding="utf-8")[:MAX_REPORT]
    return {
        "status": result.status, "draft_reason": result.draft_reason, "name": result.sdm.name,
        "description": result.sdm.description, "folder": result.out_dir.name, "files": result.files,
        "scripts": len(result.sdm.scripts), "report_md": report,
        "counts": {"passed": len(ran) - failed - warned, "warning": warned, "failed": failed, "not_run": len(result.checks) - len(ran)},
        "checks": [asdict(c) for c in result.checks],
        "tokens": asdict(result.tokens) if result.tokens else None,  # an estimate: build/quality.py
    }


class SkillKind(Kind):
    key = "skill"
    label = "Skill"
    library_dir = "library"
    definition_file = "SKILL.md"
    personal_label = "~/.claude/skills"
    slots = tuple(Slot(key, SLOT_LABELS[key], QUESTIONS[key]) for key in SLOTS)

    def name_of(self, files: Mapping[str, bytes]) -> str | None:
        return skill_name_of(files)

    def personal_dir(self) -> Path:
        return Path.home() / ".claude" / "skills"  # worked out per call, so a test (or a changed HOME) is honoured

    def understand(
        self, provider: LLMProvider, words: str, round_no: int, max_rounds: int, previous: RequirementSpec | None = None,
    ) -> Round:
        return understand_round(provider, words, round_no, max_rounds, previous=previous)

    def build(
        self, spec: dict, provider: LLMProvider, *, out_root: Path, with_scripts: bool, script_runner: ScriptRunner | None,
        sandbox_note: str, calls: int, notes: list[str], progress: Callable[[str], None],
    ) -> BuildOutcome:
        result = build_from_spec(
            RequirementSpec.model_validate(spec), provider, out_root=out_root, force=True, sandbox_note=sandbox_note,
            with_scripts=with_scripts, script_runner=script_runner, calls=calls, notes=notes, progress=progress,
        )
        return BuildOutcome(summarize(result), result.model_calls, result.notes)
