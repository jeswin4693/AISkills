"""The skill kind: a folder with a SKILL.md whose front matter names it."""

from __future__ import annotations

import re
from collections.abc import Mapping
from pathlib import Path

import yaml

from ..build.models import SLOTS
from ..build.requirements import QUESTIONS
from ..validate.static import MAX_NAME, SLUG
from .base import Kind, Slot

# The labels the web UI shows for each slot (frontend/src/lib/builder.ts, SLOT_LABEL).
SLOT_LABELS = {
    "goal": "Goal",
    "inputs": "What it receives",
    "outputs": "What it produces",
    "constraints": "Rules it must respect",
    "acceptance_criteria": "How we will know it works",
    "failure_behavior": "When something goes wrong",
}


def skill_name_of(files: Mapping[str, bytes]) -> str | None:
    """The name in SKILL.md's front matter, or None when it is missing or not a safe name."""
    try:
        text = files["SKILL.md"].decode("utf-8").replace("\r\n", "\n")
        match = re.match(r"---\n(.*?)\n---\n", text, re.DOTALL)
        meta = yaml.safe_load(match.group(1)) if match else None
    except (KeyError, UnicodeDecodeError, yaml.YAMLError):
        return None
    name = meta.get("name") if isinstance(meta, dict) else None
    return name if isinstance(name, str) and SLUG.match(name) and len(name) <= MAX_NAME else None


class SkillKind(Kind):
    key = "skill"
    label = "Skill"
    library_dir = "library"
    slots = tuple(Slot(key, SLOT_LABELS[key], QUESTIONS[key]) for key in SLOTS)

    def name_of(self, files: Mapping[str, bytes]) -> str | None:
        return skill_name_of(files)

    def personal_dir(self) -> Path:
        return Path.home() / ".claude" / "skills"  # worked out per call, so a test (or a changed HOME) is honoured
