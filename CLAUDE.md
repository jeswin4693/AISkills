# CLAUDE.md: SkillForge AI (AISkills)

An open-source platform that understands repositories (a graph it remembers), suggests ideas grounded in them,
and builds reusable AI skills from plain-English requirements, with a safety layer. Python backend in
`backend/skillforge`.

**Status and plan: [docs/roadmap.md](docs/roadmap.md) is the source of truth. Read it (and the docs it links)
before asking what exists or what is next.** Built and tested: Understand (repository graph), Suggest, Build (skills built to work well and cost little: description by code,
requirement carried into SKILL.md, quality checks, token cost; `build/quality.py`; a test harness that runs each skill's
test cases against a model with and without the skill, graded by code: `evaluate/`, [docs/evaluate.md](docs/evaluate.md)),
Safety (static validators + a fail-closed Docker sandbox), Scripts (`build --scripts`, every case run in the
sandbox), Library (`library import|list|versions|diff|rescan|rollback|export|install`, with a risk diff on every new
version, see [docs/library.md](docs/library.md)),
local API (`serve`, see [docs/api.md](docs/api.md)), database + builder sessions ([docs/database.md](docs/database.md)),
web UI (Builder + Library pages) in `frontend/` ([docs/ui.md](docs/ui.md)), and the AI engine (`ai/`: every model call
goes through one service that picks a model by task, owns the retry policy, counts attempts and tokens, and redacts keys, and
asks backup models (`LLM_FALLBACKS`, any provider) when the first cannot answer; [docs/ai-engine.md](docs/ai-engine.md)), and the
hosted version (one Docker image, a sign-in, one public address: [docs/hosting.md](docs/hosting.md)).
The Component Factory's Phase 0 is built: a kind registry, and a library, validator, builder session and API that work per kind
(`skill`, `agent`, `plugin` and `mcp` are registered; Phase 1 is the Agent Builder, [docs/agent-builder.md](docs/agent-builder.md), Phase 2 the Plugin Builder, [docs/plugin-builder.md](docs/plugin-builder.md), and Phase 3 the MCP Builder (Python), [docs/mcp-builder.md](docs/mcp-builder.md): the server is started in the sandbox and called over the real MCP protocol, image built once with `python -m skillforge sandbox-build-mcp`; plan: [docs/component-factory.md](docs/component-factory.md)).
Phase 4a is built too (a plugin can carry MCP servers from the library: `servers/<name>/`, a `.mcp.json`, one secret `userConfig` option per variable the server reads;
[docs/plugin-builder.md](docs/plugin-builder.md)).
Phase 4b is built too (a plugin can carry hooks, only from the catalogue in `skillforge/hookcatalog/`: fixed scripts, typed options, recognised only when byte-identical;
[docs/hook-catalogue.md](docs/hook-catalogue.md); real Claude Code ran them, which found that a guard that cannot start failed open, so guards now carry `onFailure: block`; two independent reviews of Phases 4a and 4b are fixed and tested).
Phase 3b is built too (the MCP builder for Node: its own kind `mcp-node`, a TypeScript `server.ts` run by `node --permission` in the sandbox and read by `validate/mcp_node.py`; image built once with `python -m skillforge sandbox-build-mcp-node`; [docs/mcp-builder-node.md](docs/mcp-builder-node.md); two independent reviews are fixed and tested; not in plugins yet).
Slice V is built too (a skill can cite code: `evidence.json` holds the files and functions it names with the graph's facts, `library cite|recheck|refresh` say what changed in them, deterministic, no model;
[docs/evidence.md](docs/evidence.md); a recheck checks that cited facts still hold, not that the skill's advice is right; evidence names a private repository's code, so export can leave it out and a plugin never ships it).
Slice W is built too (the web **Repository** page: read a folder into the graph, grounded ideas as a polled run, a Builder session seeded with the idea's cited places that ends with `evidence.json`, and a recheck on the skill's page;
every route that reads a folder is off in the hosted version; [docs/repository-page.md](docs/repository-page.md)).
Slice X is built too (the web **Settings** page: choose the model, paste a key, add backups, test them; a key is never sent back, only a fixed list of names can be changed, values are checked, `.env` is edited atomically and the change applies at once; the model lookup re-reads `.env` each time; off in the hosted version; [docs/settings.md](docs/settings.md)).
Slice Y is built too (the Repository page's box also takes the link of a **public GitHub repository**: GitHub's zip is downloaded, never cloned, and unpacked by our own code with strict name and size rules, kept as a snapshot; it works everywhere a folder does; off in the hosted version; **one independent review, four Important findings fixed**; [docs/github-link.md](docs/github-link.md)).
Slice Z is built too (the Repository page **draws the repository**: top-level folders as boxes and the proven imports between them as arrows, worked out by code in `graph/architecture.py` and drawn as plain SVG with no library; a guess and an import written by a test file or by test scaffolding (an `e2e`, `fixtures` or `mocks` folder) are never drawn, only counted; fewer than six folders means one level deeper; a loop is shown by dashed back arrows; click a box to light its arrows; works for a folder and for a link; **one independent review of Y and Z together, one Important finding for Z fixed (C# imports are not measured)**; [docs/architecture-map.md](docs/architecture-map.md)).
Slice AA is built too (every command that takes a repository, `graph`, `suggest`, `plan --repo`, `build --repo` and `library cite|recheck|refresh --repo`, also takes the link of a **public GitHub repository**: the page's own downloader through one helper, `_repo_arg` in `cli.py`; the note about the download goes to stderr so `--json` stays JSON; `cite`, `recheck` and `refresh` always download fresh; `plan` says a copy has no `CLAUDE.md` or `AGENTS.md`; a folder is untouched and does not import the builder; no independent review; [docs/cli-github-links.md](docs/cli-github-links.md)).
Slice AB is built too (the Repository page's **How it works** guide for new developers: a model reads the README and docs and proposes parts, layers and routes, and code keeps only what it can check: a quote found word for word inside one paragraph, a folder looked up in the graph, each hop of a route marked confirmed / both ways / reversed / docs-only from proven imports; `guide/` and `builder/guides.py`, `POST /api/repos/guide`, `skillforge guide`; a GitHub copy now also keeps README and doc files; one request, nothing saved; **one independent review, 3 Important and 5 Minor fixed, 57 deliberate breaks caught, and real model runs that found three defects no mock showed**; [docs/how-it-works.md](docs/how-it-works.md)).
Slice AC is built too (the **Dashboard**, the home page: what needs you (today's rescan of every kind, unfinished builds, no model, no sandbox, worst first), what the library holds, recent builds, where to start; no new server code, pure logic in `frontend/src/lib/dashboard.ts`; a part that cannot be read says so and is never shown as zero; the Quality Report view is still not built; [docs/dashboard.md](docs/dashboard.md)).
Slice AD is built too (the **Testing Lab** page: pick a skill and version, see what would run and its cost in model calls before anything is asked, run its own test cases against a model with and without the skill, read the verdict and each failed check; a polled run kept in `eval_runs`, `builder/evals.py`, `api/evals.py`, `GET /api/evals/preview` + `POST /api/evals`; the outcome is a code from `EvalReport.outcome()`, one `plan_cases` decides what runs; a skill that needs tools or has no usable cases is refused with its reason (none of the author's three saved skills could be run); real run with the configured model: 3 of 3 with the skill, 1 of 3 without; [docs/testing-lab.md](docs/testing-lab.md)).
Next: the person's own test cases in the Testing Lab (slice AE, [docs/testing-lab.md](docs/testing-lab.md)), the Quality Report page, the last differentiator ([docs/differentiators.md](docs/differentiators.md): a behavioural canary scan; the risk diff + rescan and code-level evidence + drift are built),
and Node servers in plugins ([docs/ui-and-database-plan.md](docs/ui-and-database-plan.md)).

## Commands (run from `backend/`)

```powershell
python -m pytest -q                                   # all tests, offline (a few need a Linux Docker and skip without one)
python -m skillforge graph <stats|callers|impact|duplicates|...> <repo>
python -m skillforge suggest <repo> [--facts-only]    # AI parts need a provider key in .env
python -m skillforge guide <repo> [--json]            # how the project works, from its README and docs; every quote checked (docs/how-it-works.md)
python -m skillforge build "<what the skill should do>"
python -m skillforge validate <skill-folder>
python -m skillforge eval <skill-folder> [--runs 3]   # run its test cases against a model, with and without the skill (docs/evaluate.md)
python -m skillforge sandbox-status
python -m skillforge sandbox-build-mcp-node           # once, needs a network: the image generated Node MCP servers are tested in
python -m skillforge library <import|list|versions|diff|rescan|rollback|export|install|cite|recheck|refresh> ...   # cite/recheck/refresh: docs/evidence.md
python -m skillforge serve [--port 8000]              # local API, 127.0.0.1 only (hosted version: docs/hosting.md)
python -m skillforge models [--test]                  # which models and keys are set up; --test asks each model one tiny question
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
- **Models answer, code judges.** A skill's test replies are graded by the seven checks in `evaluate/grade.py`, never
  by asking a model whether a reply is good (a judge model can be talked into anything by the text it judges). A
  model-written regex is length-limited and refused if it repeats a repeat, because Python's `re` has no time limit.
- **Generated code is untrusted.** Validate it statically, and run it ONLY through `skillforge.sandbox`, which
  fails closed: no Linux container engine means it does not run, never on the host. Windows containers are
  refused on purpose.
- **Tests are offline.** Use `MockProvider`. No test may read the real `.env` or call a hosted model (a conftest
  fixture enforces it). Tests that need a Linux Docker (`test_sandbox_live.py`) skip when none exists.
- **Keys** come only from the environment or the git-ignored `.env`. Never commit, print or document one. Do not
  hardcode model names: models get retired for new keys while still listed, so test a model with a real call.
- **Every model call names its task** (`generate_with_retry(..., task=Task.X)`, `skillforge.ai`) and never calls a
  provider directly, so the model, the retries, the budget, the usage rows and the redaction apply to it. Settings are read
  only in `service_from_env`, and `ai/` never calls `load_dotenv` (the test fixture blocks the two loaders that do).
- **The API has no sign-in locally, so it never listens beyond this machine without one.** `serve --host` anything but loopback
  is refused unless `SKILLFORGE_MODE=hosted` with a strong `SKILLFORGE_ACCESS_TOKEN`. Anything that writes on the server's own disk
  (install into a folder) is off in the hosted version. A backup model never hides a mistake: a bad key or a bad request is raised,
  not passed to a fallback.
- **No new library without clear value.** Do not add or reintroduce Ollama.
- **After each slice:** tests pass, README, `docs/roadmap.md` and the slice's doc are updated, then commit and push.
