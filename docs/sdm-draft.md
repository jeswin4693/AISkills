# Skill Definition Model (SDM) - Draft v0

Status: draft for review. Not final. This will become a Pydantic model in `backend/`.

The SDM is the single source of truth. All generated files (SKILL.md, scripts, schemas, tests, README) are rendered from it, and validators check the files against it.

## Fields

| Field | Purpose |
|---|---|
| `name`, `version`, `description` | Identity. Description says when the skill should be used. |
| `kind` | `prompt` \| `skill` \| `tool` \| `agent` - see classification below |
| `responsibilities` | What the skill does and, explicitly, what it does not do |
| `inputs` / `outputs` | JSON Schema for each |
| `workflow` | Ordered steps, each with a goal, tool used and failure handling |
| `scripts` | Supporting scripts: language, purpose, entry point, declared dependencies |
| `tools` | External tools / integrations the skill needs |
| `permissions` | Declared file, network and command access (default: none) |
| `error_handling` | Known failure modes and the expected response |
| `limitations` | Stated honestly, shown in the generated docs |
| `tests` | Positive, negative, edge and regression cases with expected results |
| `acceptance_criteria` | Copied from the approved requirement spec |
| `target_formats` | Output adapters to render (start with `claude-skill`) |

## prompt vs skill vs tool vs agent

| Kind | Rule of thumb |
|---|---|
| Prompt | One-off instruction text. No files, no reuse contract. |
| Skill | Reusable instructions plus optional scripts and schemas, with defined inputs/outputs and tests. Runs inside a host agent. |
| Tool | A callable function with a strict schema and no judgment of its own. |
| Agent | Owns a loop and a goal: skills + tools + memory + permissions + model config. Future phase. |

## Open questions

- Final field names and nesting
- How `workflow` steps reference `scripts` and `tools`
- How `permissions` are enforced by the sandbox
