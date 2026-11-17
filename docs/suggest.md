# Suggest: AI ideas grounded in the graph

`skillforge suggest <repo>` asks a model for improvements and ideas for a repository. The model never reads
the code. It only sees a short **fact sheet** that code computed from the repository graph, so every
suggestion has to point at something real.

```
 graph --> FACTS (code) --> review pass (AI) --+
                       \--> ideas pass (AI) ---+--> GROUNDING (code) --> suggestions with evidence
```

## Run it

```powershell
cd backend
python -m skillforge suggest C:\path\to\repo --facts-only   # the fact sheet only: no AI, no key
python -m skillforge suggest C:\path\to\repo                # needs LLM_PROVIDER, LLM_MODEL and a key in .env
python -m skillforge suggest C:\path\to\repo --json --save report.json
```

Options: `--max` (review suggestions to keep), `--max-ideas`, `--no-ideas`, `--focus <dir>`, `--no-cache`,
`--no-history`. Providers: `gemini` and `openai` (verified live), plus `groq`, `openrouter`, `mistral` and
`custom` (any OpenAI-compatible API), which share the same adapter but are only checked with a mock.

## The fact sheet

Computed by code from the graph, each fact numbered (`F1`, `F2`, ...) and tied to real files or functions:
overview, most-called functions, risky files (imported by many and changed often), duplicate functions,
dead-code candidates, imported-by-many files that no test reaches, files that change together without
importing each other, the largest functions, and unresolved imports. Names and paths from the repository are
treated as hostile text: control characters and markup are stripped and the facts sit inside a fenced block
the model is told never to obey.

## Two passes

1. **Review**: `refactor`, `test`, `cleanup`, `risk`.
2. **Ideas**: `skill` and `automation` only. Each idea must carry a self-contained requirement text (input,
   output, rules) that the Build slice can later turn into a skill. A single combined prompt was tried first;
   the model ignored the "include a skill idea" instruction, so the work was split.

## Grounding: what is checked, and what is not

Checked by code, for every suggestion:

- It cites at least one **fact id or graph node that exists** (file path, function id, or a name that matches
  exactly one function). Citations that match nothing are ignored and listed; with none left the suggestion is
  **dropped** and the reason shown.
- Category matches the pass. Skill and automation ideas need a requirement text. Duplicate titles and
  anything over the limit are dropped.
- **Numbers** in the title, rationale and next step that appear in no fact are flagged `CHECK`.

**Not** checked: whether the reasoning is right. A suggestion can cite real code and still draw a weak
conclusion, for example call something "frequently changed" when the fact says 3 commits. Every report says
so. Read each suggestion against the cited code before acting.

## Real results (2026-11-17, `gemini-3.5-flash-lite`, free key)

- On the author's RIA repository (78 TypeScript files): 7 kept, 0 dropped in about 14 s. The duplicates it
  reported (`spread` in two files, `flagLine` in two files, the import helpers) and the large functions
  (`main` 270 lines, `createServer` 263 lines) were all real. One automation idea came back with a complete
  requirement text; the number check flagged an invented threshold.
- On this repository's own code it found a **bug in the graph**: it reported `extract.require_import` as
  unused, but a sibling closure called it. The resolver now follows enclosing function scopes, with tests.

## Limits

- Quality depends on the model. A small free model gives plain but safe suggestions.
- Only facts the graph can compute are available, so suggestions about naming, design intent or business
  logic are out of reach.
- Name-only call guesses and dead-code candidates are labelled in the facts and are never presented as proof.
