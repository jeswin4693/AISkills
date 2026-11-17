"""Grounding: keep a suggestion only if what it cites exists in the graph. Existence is checked by code."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..graph import query
from ..graph.model import RepoGraph
from .facts import Fact
from .models import Suggestion

MIN_REQUIREMENT_CHARS = 20


_NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")
_ORDINARY = {"0", "1", "2"}  # counting words, not claims about the repository


def _numbers(text: str) -> set[str]:
    return {m.group().rstrip(",").replace(",", "") for m in _NUMBER.finditer(text)}


@dataclass
class GroundedSuggestion:
    suggestion: Suggestion
    evidence_nodes: list[str]  # the graph nodes (files or symbols) the evidence resolved to
    ignored_evidence: list[str] = field(default_factory=list)  # cited items that matched nothing
    # numbers in the title, rationale or next step that appear nowhere in the fact sheet
    unverified_numbers: list[str] = field(default_factory=list)


@dataclass
class Dropped:
    title: str
    reason: str


def resolve_evidence(item: str, g: RepoGraph, facts_by_id: dict[str, Fact]) -> list[str]:
    ref = item.strip()
    m = re.fullmatch(r"[Ff](\d+)", ref)
    if m:
        fact = facts_by_id.get(f"F{int(m.group(1))}")
        return list(fact.nodes) if fact else []
    if ref in g.files or ref in g.symbols:
        return [ref]
    found = query.find_symbols(g, ref)
    return [found[0].id] if len(found) == 1 else []


def ground(
    suggestions: list[Suggestion],
    g: RepoGraph,
    facts: list[Fact],
    max_keep: int,
    allowed: frozenset[str] | None = None,
) -> tuple[list[GroundedSuggestion], list[Dropped]]:
    facts_by_id = {f.id: f for f in facts}
    sheet_numbers: set[str] = set()
    for f in facts:
        sheet_numbers |= _numbers(f.summary) | _numbers(" ".join(f.nodes))
    kept: list[GroundedSuggestion] = []
    dropped: list[Dropped] = []
    seen_titles: set[str] = set()
    for s in suggestions:
        title = " ".join(s.title.split()) or "(untitled)"
        nodes: list[str] = []
        ignored: list[str] = []
        for item in s.evidence:
            found = resolve_evidence(item, g, facts_by_id)
            if not found:
                ignored.append(item)
            nodes.extend(n for n in found if n not in nodes)
        if allowed is not None and s.category not in allowed:
            dropped.append(Dropped(title, f"category '{s.category}' was not asked for in this pass"))
        elif not s.rationale.strip() or not s.next_step.strip() or title == "(untitled)":
            dropped.append(Dropped(title, "missing title, rationale or next step"))
        elif not nodes:
            dropped.append(Dropped(title, "no cited evidence exists in the graph"))
        elif s.category in ("skill", "automation") and len(s.skill_requirement.strip()) < MIN_REQUIREMENT_CHARS:
            dropped.append(Dropped(title, "a skill or automation idea needs a requirement text"))
        elif title.lower() in seen_titles:
            dropped.append(Dropped(title, "duplicate title"))
        elif len(kept) >= max_keep:
            dropped.append(Dropped(title, "over the requested limit"))
        else:
            seen_titles.add(title.lower())
            claimed = _numbers(" ".join([s.title, s.rationale, s.next_step]))
            unverified = sorted(claimed - sheet_numbers - _ORDINARY, key=lambda n: (len(n), n))
            kept.append(GroundedSuggestion(s, nodes, ignored, unverified))
    return kept, dropped
