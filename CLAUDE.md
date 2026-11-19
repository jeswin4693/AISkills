# CLAUDE.md: SkillForge AI (AISkills)

An open-source platform that understands repositories (a graph it remembers), suggests ideas grounded in them,
and builds reusable AI skills from plain-English requirements, with a safety layer. Python backend in
`backend/skillforge`.

**Status and plan: [docs/roadmap.md](docs/roadmap.md) is the source of truth. Read it (and the docs it links)
before asking what exists or what is next.** Built and tested: Understand (repository graph), Suggest, Build,
Safety (static validators + a fail-closed Docker sandbox), Scripts (`build --scripts`, every case run in the
sandbox), Library (`library import|list|versions|diff|rollback|export|install`, see [docs/library.md](docs/library.md)),
local API (`serve`, see [docs/api.md](docs/api.md)), database + builder sessions ([docs/database.md](docs/database.md)),
web UI (Builder + Library pages) in `frontend/` ([docs/ui.md](docs/ui.md)).
Next: pick a differentiator ([docs/differentiators.md](docs/differentiators.md): the generic skill-tool features are crowded; the gaps are code-level
evidence + drift, a behavioural canary scan, and a risk diff per version), then the other UI pages and Settings (H5)
([docs/ui-and-database-plan.md](docs/ui-and-database-plan.md)); Agent Builder last.

## Commands (run from `backend/`)

```powershell
python -m pytest -q                                   # all tests, offline (a few need a Linux Docker and skip without one)
python -m skillforge graph <stats|callers|impact|duplicates|...> <repo>
python -m skillforge suggest <repo> [--facts-only]    # AI parts need a provider key in .env
python -m skillforge build "<what the skill should do>"
python -m skillforge validate <skill-folder>
python -m skillforge sandbox-status
python -m skillforge library <import|list|versions|diff|rollback|export|install> ...
python -m skillforge serve [--port 8000]              # local API, 127.0.0.1 only
python -m skillforge plan "<task>" --repo <path> [--no-ai]   # read-only task plan (docs/task-conductor.md)
```

The web UI is in `frontend/` (run from there; `node_modules` and `.next` are junctions to `C:\dev\frontend`, see
[frontend/README.md](frontend/README.md)): `npm run dev` (UI at http://127.0.0.1:3000), `npm run typecheck`,
`npm test` (unit), `npm run build` then `npm run e2e` (real Edge browser against the real API; needs ports 3000 and 8000).
Run `scripts\frontend-node-modules.ps1` after every `npm install`.

Setup, the layout and what each part does are in [README.md](README.md). The development machine notes are in
[docs/environment-notes.md](docs/environment-notes.md) and [docs/sandbox-wsl.md](docs/sandbox-wsl.md).

## Rules for working here

- **The graph is deterministic.** No AI in `backend/skillforge/graph`. A link is `resolved` (proven) or `guess`
  (name only); guesses never count toward risk or test coverage; built-in method names (`get`, `push`, ...) are
  never matched by name; an ambiguous call makes no edge.
- **Models see only facts that code computed.** A suggestion must cite graph nodes that exist, and numbers it
  mentions are checked against the facts. Existence is checked, correctness of the reasoning is not: say so.
- **Completeness is a checklist in code, not the model's opinion.** A requirement slot counts as answered only
  with a quote that code verified appears in the person's own words. Never ask a model for JSON Schema or front
  matter: code builds schemas from field lists and writes YAML with a library. Model text is data and is never
  evaluated as a template.
- **Be honest about language depth.** Every language has a level (full / standard / basic, in
  `graph/languages.py` and [docs/languages.md](docs/languages.md)); never claim more than the level gives. A new
  language needs a grammar name that exists in `tree-sitter-language-pack`, a level, and, above `basic`, a spec in
  `graph/extract_generic.py` with tests. A missing grammar must degrade that one language, never the run.
- **A check is "passed" only if it ran.** Every report lists what did not run. Heuristics (wording, markup)
  warn; structural problems fail.
- **Generated code is untrusted.** Validate it statically, and run it ONLY through `skillforge.sandbox`, which
  fails closed: no Linux container engine means it does not run, never on the host. Windows containers are
  refused on purpose.
- **Tests are offline.** Use `MockProvider`. No test may read the real `.env` or call a hosted model (a conftest
  fixture enforces it). Tests that need a Linux Docker (`test_sandbox_live.py`) skip when none exists.
- **Keys** come only from the environment or the git-ignored `.env`. Never commit, print or document one. Do not
  hardcode model names: models get retired for new keys while still listed, so test a model with a real call.
- **No new library without clear value.** Do not add or reintroduce Ollama.
- **After each slice:** tests pass, README, `docs/roadmap.md` and the slice's doc are updated, then commit and push.
