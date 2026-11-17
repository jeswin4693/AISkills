# Step 1 proposal: requirement text to skill files (thin slice)

Status: **original proposal, now built as slice C of the [roadmap](roadmap.md).** What exists is described in
[build.md](build.md); it differs in details (for example quotes verified by code decide completeness, and the
schemas are built from field lists). Kept for the reasoning.

## Goal

One command takes a plain-English description and produces a skill folder on disk:

```
description -> questions -> approved RequirementSpec -> SkillDefinition (SDM) -> files
```

No UI, no database, no Docker. Everything must be testable offline.

## What the user runs

```powershell
skillforge new "A skill that finds duplicate functions in a TypeScript repo and suggests safe refactors"
```

1. The model drafts a `RequirementSpec` from the text.
2. **Code, not the model,** checks completeness. A fixed checklist decides what is missing.
3. Missing items become questions. The user answers. Repeat (max 3 rounds).
4. When the checklist is complete, the spec is saved as `spec.json` and the user approves it.
5. The model turns the approved spec into a `SkillDefinition` (validated by Pydantic; one retry if invalid).
6. Code checks the SDM against the spec (see "Checks that really run").
7. Files are rendered from templates into `generated-skills/<name>/` (already git-ignored).

Also: `skillforge render sdm.json` re-renders files from a saved SDM with **no model call**.

## Folder layout

```
backend/
  skillforge/
    models/        requirement.py (RequirementSpec), sdm.py (SkillDefinition)
    providers/     base.py (LLMProvider), openai_compat.py (Gemini + OpenAI), mock.py
    pipeline/      requirements.py (completeness + questions), architect.py (spec -> SDM), checks.py
    render/        claude_skill.py + templates/ (SKILL.md, README.md, ...)
    prompts/       versioned prompt templates, kept out of code
    cli.py
  tests/
  scripts/hello_structured.py   (kept for now, removed once the provider interface replaces it)
```

## Provider interface

```python
class LLMProvider(Protocol):
    name: str
    model: str
    def generate_structured(self, schema: type[T], prompt: str, *, system: str | None = None) -> T: ...
```

- `OpenAICompatibleProvider`: one adapter for Gemini and OpenAI (base URL + key env var differ). Already proven live with Gemini.
- `MockProvider`: returns fixed objects. Used by every automated test. No test ever calls a hosted model.
- Anthropic stays in the hello script until someone has a key to verify it.
- Errors map to one `ProviderError` with a message the user can act on (already done in the hello script).
- Every generated skill records `provider` + `model` in `skill.sdm.json`.

## Completeness check (the "when are requirements done" problem)

A fixed checklist, scored by code:

| Slot | Counts as complete when |
|---|---|
| goal | non-empty, one clear sentence |
| kind | one of prompt / skill / tool / agent (Step 1 builds only `skill`) |
| inputs | at least one described input, or explicitly "none" |
| outputs | at least one described output |
| acceptance criteria | at least one testable criterion |
| constraints | filled, or explicitly "none" |
| failure behavior | what to do on bad input or tool failure |

The model may *extract* and *phrase questions*, but it never decides that requirements are complete.

## SkillDefinition (subset built in Step 1)

Fields follow `docs/sdm-draft.md`: name (lowercase-hyphen slug, length-limited), version, description
(says when to use the skill), kind (`skill` only), responsibilities (does / does not), inputs and outputs
(JSON Schema), workflow steps, permissions (default none), error handling, limitations, test cases
(positive / negative / edge, as data), acceptance criteria, target format, provenance (provider, model,
prompt versions).

## Files produced

```
generated-skills/<name>/
  SKILL.md                  frontmatter (name, description) + instructions
  README.md                 human overview, limitations, how to test
  schemas/input.schema.json
  schemas/output.schema.json
  tests/cases.json          test cases from the SDM (data only, not executed in Step 1)
  skill.sdm.json            the SDM itself = single source of truth
  report.md                 what ran and what did not (see below)
```

Frontmatter is written with a safe YAML writer, never by string concatenation.

## Checks that really run in Step 1

Ran by code, reported as **passed / failed**:
- spec and SDM validate against their Pydantic models
- input and output schemas are valid JSON Schema
- every acceptance criterion maps to at least one test case
- every workflow step references only declared scripts and tools
- rendered `SKILL.md` frontmatter parses back to the same name and description

Reported as **not run** (Step 2): script compilation, sandbox execution, instruction-conflict analysis,
security review. A check is marked passed only if it ran.

## Proposed decisions for you

1. **No executable script source in Step 1.** The SDM can *describe* scripts, but Step 1 generates
   instructions, schemas and test data only. Generated code would be untrusted, and the sandbox does not
   exist yet (your Docker cannot run Linux containers). Scripts arrive with Step 2.
   Your TypeScript repository analyzer demo is generated in instruction-only form first.
2. **New libraries:** `jinja2` (templates), `pyyaml` (safe frontmatter), and `pytest` (dev only).
   The CLI uses the standard library (`argparse`). No FastAPI until the UI step.
3. **CLI first.** An API endpoint adds nothing until there is a UI.

## Tests (all offline, mock provider)

- model validation: bad names rejected, non-`skill` kinds rejected with an explanation
- completeness: scoring is deterministic, each missing slot produces a question
- pipeline end to end with `MockProvider`: files exist, frontmatter parses, SDM round-trips
- renderer golden files: same SDM always renders the same bytes
- provider error mapping, using a mocked HTTP transport (the scratch checks done in Step 0)
- one live test marked `live`, skipped by default, run by hand against Gemini

## Acceptance criteria

- `pytest` passes offline with no key and no network.
- `skillforge new` with the demo text produces a complete folder with a Gemini key set.
- `skillforge render` reproduces the same files from a saved SDM with no model call.
- `report.md` lists every check as passed, failed or not run, with no claim that was not executed.
- No key or personal data in any file; generated output stays git-ignored.

## Out of scope for Step 1

Database, UI, FastAPI, Docker sandbox, script source generation, auto-fix loops, versioning, export,
Agent Builder.

## Risks

| Risk | Mitigation |
|---|---|
| Small or free models give weak output | validation + one retry; clear errors; the report shows what failed |
| Gemini's JSON-schema support is narrower than OpenAI's (nested models, optional fields) | test early with the real SDM schema; simplify the schema if needed |
| Models get retired or return 503 | no default model; error text says what to do |
| User text tries to steer the model ("ignore the rules") | spec and SDM are validated data; generated files are treated as untrusted and are never executed in Step 1 |

## Build order (small commits, each pushed)

1. Package scaffold, pytest, move the provider code behind `LLMProvider`.
2. Models and completeness check, with tests.
3. `MockProvider` and the pipeline, with tests.
4. Renderer and templates, with golden-file tests.
5. CLI and `report.md`.
6. First live run with Gemini on the demo requirement; record real results and problems.
