"""Models for the Task Plan: what the model returns (strict, no defaults), and what the plan holds.

The model only reads the person's words. Everything it claims is checked by code before it reaches the plan: a quote
must really be in the person's words, a named target must really be in their text and in the graph, a rule id must
really exist. Sizes, tiers and token numbers are computed by code from the repository graph, never by the model.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

TaskType = Literal["feature", "bugfix", "refactor", "migration", "docs", "investigation", "other"]
SizeClass = Literal["small", "medium", "large"]


# ---- what the model returns (sent as a strict schema: no defaults, no free-form dicts) ---------------------


class Quoted(BaseModel):
    text: str = Field(description="What the person asked for or said, in a few plain words.")
    quote: str = Field(description="Words copied exactly, word for word, from the person's text that support it.")


class GapAsked(BaseModel):
    question: str = Field(description="A question the person has to answer for the work to be done well.")
    why: str = Field(description="One sentence: what goes wrong if it stays unanswered.")
    blocking: bool = Field(description="True only if the work cannot start safely without the answer.")


class AssumptionMade(BaseModel):
    text: str = Field(description="Something you would have to assume because the person did not say it.")
    why: str = Field(description="One sentence: why an assumption is needed here.")


class NewFile(BaseModel):
    path: str = Field(description="Relative path of a file the work would create, such as docs/notes.md.")
    purpose: str = Field(description="One sentence: what the file is for.")
    size: SizeClass = Field(description="small (a few lines), medium (a page), large (several pages).")


class TaskReading(BaseModel):
    task_type: TaskType = Field(description="The closest kind of work.")
    summary: str = Field(description="One neutral sentence saying what is wanted. Add nothing the person did not say.")
    stated: list[Quoted] = Field(description="What the person asked for. Every item needs an exact quote.")
    constraints: list[Quoted] = Field(description="Rules or limits the person gave. Every item needs an exact quote.")
    out_of_scope: list[Quoted] = Field(description="Things the person said NOT to do. Every item needs an exact quote.")
    declared_risks: list[Quoted] = Field(description="Things the person said are sensitive or risky. Exact quotes only.")
    named_targets: list[str] = Field(description="Files, functions or modules the person named, exactly as they wrote them.")
    gaps: list[GapAsked] = Field(description="What the request does NOT say but the work needs. At most 8.")
    assumptions: list[AssumptionMade] = Field(description="Assumptions you would otherwise make silently. At most 6.")
    files_to_create: list[NewFile] = Field(description="New files the work would create. Empty if none are needed.")


class RuleRef(BaseModel):
    id: str = Field(description="The id of a rule from the list, exactly as given, such as R3.")
    why: str = Field(description="One sentence: why this rule applies to this task.")


class RuleSelection(BaseModel):
    applicable: list[RuleRef] = Field(description="Only the rules that apply to this task. Use only ids from the list.")


# ---- what the plan holds -----------------------------------------------------------------------------------


class StatedItem(BaseModel):
    text: str
    quote: str  # verified: really in the person's words


class Gap(BaseModel):
    question: str
    why: str
    blocking: bool
    source: Literal["model", "code"]  # "code": found by the graph, not by the model


class Assumption(BaseModel):
    text: str
    why: str


class Reading(BaseModel):
    task_type: str
    summary: str
    stated: list[StatedItem]
    constraints: list[StatedItem]
    out_of_scope: list[StatedItem]
    declared_risks: list[StatedItem]
    gaps: list[Gap]
    assumptions: list[Assumption]


class Mention(BaseModel):
    kind: Literal["file", "symbol"]
    text: str  # as the person wrote it
    target: str  # a graph file path or symbol id; "" when the mention is ambiguous
    file: str
    line: int | None
    candidates: int  # how many places the text matched
    ambiguous: bool
    source: Literal["prompt", "model"]
    options: list[str] = Field(default_factory=list)  # when ambiguous: up to MAX_OPTIONS of the places it matched


class Reach(BaseModel):
    """What a change to one mentioned target could reach, from the graph (proven links only)."""

    target: str
    files_reached: list[str]  # non-test files that depend on it by a proven link
    tests_tied: list[str]
    risk: str  # low | medium | high, from the graph's own scoring
    possible: int  # files linked by a name match only: listed, never counted


class Signal(BaseModel):
    name: str
    floor: int  # the lowest tier this signal allows
    evidence: str


class TierDecision(BaseModel):
    tier: int
    baseline: int
    signals: list[Signal]
    measured: bool  # False when no repository target could be measured
    note: str


class Phase(BaseModel):
    id: str
    title: str
    reads: str
    writes: str
    gate: str  # how we know it is done, in plain words
    approval: bool  # a person approves before the next phase


class Rule(BaseModel):
    """One rule found in a repository's rule file."""

    id: str  # R1, R2, ... in the order found
    source: str  # the file it came from
    line: int
    heading: str
    text: str


class AppliedRule(BaseModel):
    id: str
    source: str  # a file name, or "your prompt"
    line: int
    text: str
    why: str
    quote: str  # for a rule from the prompt: the person's words
    enforcement: str


class ReadItem(BaseModel):
    kind: Literal["slice", "file"]
    path: str
    symbol: str
    lines: str  # "12-40", or "" for a whole file
    tokens: int
    whole_file_tokens: int
    why: str
    priority: int


class CreateItem(BaseModel):
    path: str
    purpose: str
    size: str
    tokens: int


class TokenPlan(BaseModel):
    budget: int
    reads: list[ReadItem]
    dropped: list[ReadItem]
    read_total: int
    whole_files_total: int  # what the same files would cost if read whole instead of in slices
    create: list[CreateItem]
    create_total: int
    fits_budget: bool
    method: str


class TaskPlan(BaseModel):
    created_at: str
    prompt: str
    mode: str  # "model" or "facts only"
    model: str
    repo: str
    reading: Reading
    mentions: list[Mention]
    reach: list[Reach]
    tier: TierDecision
    phases: list[Phase]
    stop_triggers: list[str]
    rules: list[AppliedRule]
    rules_found: int
    token_plan: TokenPlan
    notes: list[str] = Field(default_factory=list)
    not_checked: list[str] = Field(default_factory=list)
    model_calls: int = 0
