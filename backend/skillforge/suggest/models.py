"""What the model is asked to return. Kept flat and simple so more providers can follow the schema."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Category = Literal["refactor", "test", "cleanup", "risk", "skill", "automation"]
Confidence = Literal["high", "medium", "low"]


class Suggestion(BaseModel):
    title: str = Field(description="A short, specific title.")
    category: Category = Field(description="The kind of suggestion.")
    rationale: str = Field(description="Why this matters here, in two or three sentences, using only the facts.")
    evidence: list[str] = Field(
        description='Fact ids such as "F3" and/or exact node names copied from the facts. At least one is required.'
    )
    next_step: str = Field(description="The first concrete action to take.")
    confidence: Confidence = Field(description="Low when relying on candidates or name-only guesses.")
    skill_requirement: str = Field(
        description=(
            "For category skill or automation: a self-contained plain-English description of the job "
            "(input, output, rules). For every other category: an empty string."
        )
    )


class SuggestionSet(BaseModel):
    suggestions: list[Suggestion]
