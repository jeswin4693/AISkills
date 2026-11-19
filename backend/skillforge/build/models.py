"""Models for the Build slice.

Three layers: what the model extracts (with quotes that code verifies), the approved RequirementSpec, and the
SkillDefinition (SDM) that every generated file is rendered from. Free-form JSON Schema is never asked of the
model: it gives simple field lists and code builds the schema, so the schema is valid by construction.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

Kind = Literal["prompt", "skill", "tool", "agent"]
FieldType = Literal["string", "integer", "number", "boolean", "list", "object"]
Permission = Literal["read_files", "write_files", "run_commands", "network"]
TestKind = Literal["positive", "negative", "edge"]

SLOTS = ("goal", "inputs", "outputs", "constraints", "acceptance_criteria", "failure_behavior")


# ---- extraction: what the model returns while reading the person's words -----------------------------


class Slot(BaseModel):
    values: list[str] = Field(description="What the person said for this item. Empty list if they did not say it.")
    quote: str = Field(
        description="Words copied exactly, word for word, from the person's text that support the values. "
        "Empty string if the person did not say it."
    )


class Extraction(BaseModel):
    kind: Kind = Field(description="The closest kind of thing the person wants.")
    goal: Slot
    inputs: Slot
    outputs: Slot
    constraints: Slot
    acceptance_criteria: Slot
    failure_behavior: Slot


# ---- the approved requirement spec -------------------------------------------------------------------


class RequirementSpec(BaseModel):
    kind: Kind = "skill"
    goal: str = ""
    inputs: list[str] = Field(default_factory=list)  # "none" is a valid, explicit answer
    outputs: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)  # "none" is a valid, explicit answer
    acceptance_criteria: list[str] = Field(default_factory=list)
    failure_behavior: str = ""
    quotes: dict[str, str] = Field(default_factory=dict)  # slot -> the person's own words that support it
    user_words: str = ""  # everything the person typed, kept for audit
    rounds: int = 1


# ---- the skill definition ----------------------------------------------------------------------------


class IOField(BaseModel):
    name: str = Field(description="snake_case name of the input or output field.")
    type: FieldType
    description: str
    required: bool


class Step(BaseModel):
    title: str
    instruction: str = Field(
        description="What the agent does in this step: short, imperative, at most 40 words. Name each input or output "
        "field it uses or produces exactly, in backticks."
    )
    on_failure: str = Field(
        description='What the agent does if this step cannot be done: one concrete action. Write "none" if the step cannot fail.'
    )


AssertionKind = Literal["contains", "not_contains", "starts_with", "regex", "max_chars", "max_lines", "first_line_max_chars"]


class Assertion(BaseModel):
    """One check that CODE runs on an agent's reply. Simple on purpose: the model answers, code judges."""

    kind: AssertionKind = Field(
        description="contains, not_contains, starts_with: some text, ignoring case. regex: a short pattern. "
        "max_chars, max_lines, first_line_max_chars: a whole number."
    )
    value: str = Field(description="The text, pattern or number to check. Keep it short.")
    why: str = Field(description="Which acceptance criterion or rule of the person this checks, in a few words.")


class SkillTest(BaseModel):
    name: str
    kind: TestKind
    input_description: str = Field(description="What the agent is given in this test. For a positive test: one concrete, literal example input.")
    expected_result: str = Field(description="What a correct run produces or does. For a positive test: the literal expected output.")
    covers: list[str] = Field(description='Ids of the acceptance criteria this test checks, such as "AC1".')
    run_input: str = Field(
        description="The exact message a person would send to an agent to start this test, including any text the skill "
        "works on. Never a description of the message. Empty only if the skill needs files, commands or the network."
    )
    assertions: list[Assertion] = Field(
        description="1 to 3 checks that code can run on the agent's reply to run_input. Empty only when run_input is empty."
    )

    @model_validator(mode="before")
    @classmethod
    def _skills_saved_before_tests_could_be_run(cls, data: Any) -> Any:
        """Older skill.sdm.json and tests/cases.json have neither field: they load as 'cannot be run here'."""
        if isinstance(data, dict):
            data = {**data}
            data.setdefault("run_input", "")
            data.setdefault("assertions", [])
        return data


class SkillDraft(BaseModel):
    """What the model designs. Code adds version, provenance and the criteria text."""

    name: str = Field(description="Lowercase letters, digits and hyphens only, at most 40 characters.")
    description: str = Field(
        description="ONE sentence, third person, saying what the skill does. Do not say when to use it: that is `triggers`."
    )
    triggers: list[str] = Field(
        description="2 to 5 short phrases or situations in which a person would want this skill, in the words they would "
        'really use (for example "write a commit message", "summarise my changes"). Code adds them to the description.'
    )
    does: list[str] = Field(description="What the skill is responsible for.")
    does_not: list[str] = Field(description="What it explicitly does not do.")
    inputs: list[IOField]
    outputs: list[IOField]
    workflow: list[Step]
    permissions: list[Permission] = Field(description="Only what the steps really need; empty if nothing.")
    error_handling: list[str]
    limitations: list[str]
    tests: list[SkillTest]


class Provenance(BaseModel):
    provider: str
    model: str
    created_at: str
    rounds: int
    name_adjusted: bool = False


# ---- scripts: written by the model, run only in the sandbox ------------------------------------------
# No defaults and no free-form dicts below: these are sent to the model as a strict schema.
# Keep ScriptLanguage equal to the keys of sandbox.images.RUNNERS (a test enforces it).

ScriptLanguage = Literal["python", "javascript", "typescript", "bash", "ruby", "php", "java"]


class Script(BaseModel):
    name: str = Field(description="Lowercase letters, digits and underscores, like find_duplicates. No extension: code makes the file name.")
    language: ScriptLanguage
    purpose: str = Field(description="One sentence: the mechanical job this script does for the skill.")
    usage: str = Field(description="What arguments it takes and what it prints, in a few plain sentences.")
    code: str = Field(description="The complete source code. Standard library only. No placeholders or TODOs.")


class Fixture(BaseModel):
    path: str = Field(description="File name inside this case's fixture folder, such as input.txt or src/a.ts. Relative, no '..'.")
    text: str = Field(description="The file's content. Keep it small.")


class ScriptCase(BaseModel):
    name: str = Field(description="Short name of the case, lowercase words with hyphens, unique across all cases.")
    script: str = Field(description="The name of the script this case runs, exactly as written in its 'name'.")
    args: list[str] = Field(description='Command-line arguments. Write {fixtures} for this case\'s fixture folder, such as "{fixtures}/input.txt".')
    stdin: str = Field(description="Text sent to the script's standard input. Empty string for none.")
    fixtures: list[Fixture] = Field(description="Small input files created for this case. Empty list for none.")
    expect_exit_code: int = Field(description="The exit code a correct run ends with: 0 for success, non-zero for a failure case.")
    stdout_contains: list[str] = Field(description="Short exact fragments the script's standard output must contain.")
    stderr_contains: list[str] = Field(description="Short exact fragments the script's standard error must contain. For failure cases give one short word of your own error message.")


class ScriptBundle(BaseModel):
    """What the script step returns: the scripts and the cases that prove them."""

    scripts: list[Script] = Field(description="At most 4 scripts. An empty list when the job needs no code.")
    cases: list[ScriptCase] = Field(description="Test cases. Every script needs a success case and a failure case.")


class SkillDefinition(SkillDraft):
    # Skills saved before `triggers` existed have none: they still load, and the quality check says so.
    triggers: list[str] = Field(default_factory=list)
    version: str = "0.1.0"
    kind: Literal["skill"] = "skill"
    acceptance_criteria: dict[str, str]  # "AC1" -> text, copied from the approved spec
    provenance: Provenance
    scripts: list[Script] = Field(default_factory=list)  # empty for an instructions-only skill
    script_cases: list[ScriptCase] = Field(default_factory=list)
