"""Suggest: facts from the graph -> model (a review pass, then an ideas pass) -> grounding."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from ..graph import query
from ..graph.model import RepoGraph
from ..providers.base import LLMProvider
from ..providers.retry import generate_with_retry
from .facts import Fact, collect_facts
from .ground import Dropped, GroundedSuggestion, ground
from .models import SuggestionSet
from .prompt import IDEAS, IDEAS_SYSTEM, REVIEW, REVIEW_SYSTEM, build_prompt

REVIEW_CATEGORIES = frozenset({"refactor", "test", "cleanup", "risk"})
IDEA_CATEGORIES = frozenset({"skill", "automation"})


@dataclass
class SuggestReport:
    repo: str
    provider: str
    model: str
    facts: list[Fact]
    suggestions: list[GroundedSuggestion]
    dropped: list[Dropped]
    attempts: int  # model calls made, retries included
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "repo": self.repo,
            "provider": self.provider,
            "model": self.model,
            "attempts": self.attempts,
            "facts": [asdict(f) for f in self.facts],
            "suggestions": [
                {
                    **g.suggestion.model_dump(),
                    "evidence_nodes": g.evidence_nodes,
                    "ignored_evidence": g.ignored_evidence,
                    "unverified_numbers": g.unverified_numbers,
                }
                for g in self.suggestions
            ],
            "dropped": [asdict(d) for d in self.dropped],
            "notes": self.notes,
        }


def _ask(provider: LLMProvider, prompt: str, system: str, attempts: int) -> tuple[SuggestionSet, int]:
    return generate_with_retry(provider, SuggestionSet, prompt, system, attempts)


def suggest(
    g: RepoGraph,
    provider: LLMProvider,
    *,
    max_suggestions: int = 8,
    max_ideas: int = 3,
    with_ideas: bool = True,
    attempts: int = 2,
) -> SuggestReport:
    facts = collect_facts(g)
    repo = Path(g.root).name
    calls = 0

    answer, used = _ask(provider, build_prompt(facts, repo, max_suggestions, REVIEW), REVIEW_SYSTEM, attempts)
    calls += used
    kept, dropped = ground(answer.suggestions, g, facts, max_suggestions, REVIEW_CATEGORIES)

    if with_ideas:
        answer, used = _ask(provider, build_prompt(facts, repo, max_ideas, IDEAS), IDEAS_SYSTEM, attempts)
        calls += used
        idea_kept, idea_dropped = ground(answer.suggestions, g, facts, max_ideas, IDEA_CATEGORIES)
        kept += idea_kept
        dropped += idea_dropped

    notes = [
        "Evidence is checked for existence in the graph, and numbers are checked against the facts. Neither proves "
        "the reasoning is right. Read each suggestion against the cited code before acting on it.",
    ]
    if g.call_stats.get("guess", 0) or g.call_stats.get("ambiguous", 0):
        notes.append(
            f"The graph has {g.call_stats.get('guess', 0)} name-only call guesses and "
            f"{g.call_stats.get('ambiguous', 0)} ambiguous calls; the facts do not rely on them."
        )
    if query.stats(g)["commits_read"] is None:
        notes.append("No git history: churn and co-change facts are missing.")
    return SuggestReport(repo, provider.name, provider.model, facts, kept, dropped, calls, notes)
