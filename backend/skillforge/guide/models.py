"""What the model is asked to return. Kept flat and simple so more providers can follow the schema (code builds the schema from these fields).

Nothing here is trusted: every part and step is only a claim until `verify` has found its quote in the documents and looked its folder up in
the graph. The five layers are fixed so the page needs no copy of them from the model.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

# (id, what the page calls the band). The order is the order the bands are drawn, from what people touch down to what is outside.
LAYERS: tuple[tuple[str, str], ...] = (
    ("use", "What people use"),
    ("door", "The doors in"),
    ("work", "The workers"),
    ("shared", "Shared services"),
    ("outside", "The outside world"),
)
Layer = Literal["use", "door", "work", "shared", "outside"]


class PartDraft(BaseModel):
    id: str = Field(description='A short lowercase id for this part: letters, digits and hyphens only, such as "api". Unique.')
    name: str = Field(description="What a new developer would call it: two or three words.")
    layer: Layer = Field(
        description=(
            "use = what people touch (screens, a command line); door = how a request gets in (API, routes, handlers); "
            "work = the main features and logic; shared = services many parts use (storage, settings, model access, safety checks); "
            "outside = something outside this repository (a cloud service, a provider, Docker)."
        )
    )
    summary: str = Field(description="One plain sentence: what this part is for.")
    folder: str = Field(
        description=(
            "The folder or file that holds this part, exactly as one of the listed folder names (or a path a document gives). "
            "An empty string when no listed folder holds it, for example an outside service."
        )
    )
    takes_in: str = Field(description="What goes into this part, in a few plain words.")
    gives_out: str = Field(description="What comes out of this part, in a few plain words.")
    plain: str = Field(description="One everyday picture of this part (an office desk, a post room, a shop counter), not code.")
    quote: str = Field(description="ONE sentence copied word for word from the documents that shows this part exists.")


class StepDraft(BaseModel):
    part: str = Field(description="The id of one of your parts.")
    does: str = Field(description="One plain sentence: what happens to the action in this part.")
    quote: str = Field(description="ONE sentence copied word for word from the documents that shows this step happens.")


class JourneyDraft(BaseModel):
    title: str = Field(description='One action a person takes that the documents describe, such as "Build a skill".')
    steps: list[StepDraft] = Field(description="3 to 8 steps in the order they happen.")


class GuideDraft(BaseModel):
    parts: list[PartDraft]
    journeys: list[JourneyDraft]
