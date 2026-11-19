"""What kind of work a model call is. Builders name the task; configuration says which model does it.

Tiers are named by the kind of work and never by a model: the models live in the environment (docs/ai-engine.md).
"""

from __future__ import annotations

from enum import StrEnum


class Tier(StrEnum):
    FAST = "fast"  # reading a person's words, picking from a list
    DESIGN = "design"  # writing a draft of a skill, an agent, a suggestion
    CODE = "code"  # writing code
    ACTOR = "actor"  # standing in for an agent, to run a test case


class Task(StrEnum):
    EXTRACT = "extract"  # requirement extraction, task intake
    SELECT = "select"  # rule selection
    DESIGN = "design"  # skill and agent drafts
    SUGGEST = "suggest"  # suggest: review and ideas
    CODE = "code"  # helper scripts (later: MCP tool bodies, hook scripts)
    ACT = "act"  # eval replies


TIER_OF: dict[Task, Tier] = {
    Task.EXTRACT: Tier.FAST,
    Task.SELECT: Tier.FAST,
    Task.DESIGN: Tier.DESIGN,
    Task.SUGGEST: Tier.DESIGN,
    Task.CODE: Tier.CODE,
    Task.ACT: Tier.ACTOR,
}
