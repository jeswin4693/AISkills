# Slice W: the repository in the web UI (plan)

Written 2026-11-23. Until now the main pipeline (understand a repository, get ideas grounded in it, build a skill from an idea, keep
evidence of the code it cites) only worked from the command line. The web UI had Builder, Library and Plugins. This slice brings the
pipeline into the pages: **Repository -> ideas -> a Builder session that records evidence -> evidence shown (and rechecked) on the skill's page.**
It is the part of the old "H5" (suggest and graph pages) that the product needs most; Settings stays out.

## Calls I made (to be corrected if wrong)

| Question | Call | Why |
|---|---|---|
| Where does a repository come from? | The person types its folder path; the page remembers it in the browser | there is no repository registry and nothing to sync; a path is what the CLI takes too |
| Hosted version | **Every route that reads a folder is off (403)**: analyze, suggestions, a build that carries a repository, recheck | it would read the server's disks, not the person's. Same rule as install |
| Analyze | One synchronous route, `POST /api/repos/analyze`: stats, languages with their honest levels, hotspots, parse notes. No model | the graph is cached and quick; no job needed |
| Suggest | A persisted **run** (`suggest_runs`, migration 0004) that runs in the background and is polled, like a build | two model calls, up to a minute; the result must survive a page reload and must not spend quota twice |
| Seeding a build | `POST /api/builds` takes an optional `repo` (absolute folder), `focus` and `evidence_nodes` (what the idea cited). Stored as `build_sessions.seed` (migration 0004) | the session already is the unit of work; one JSON column |
| When is evidence recorded? | At the **end of the build**, from the graph as it is then, for the kinds `skill` and `agent` only; if the repository cannot be read then, the build still finishes and says so in its notes | same behaviour as `build --repo`; evidence is text about code, an MCP server or a plugin makes no such claims |
| What the UI shows | a **Repository** page (analyze, ideas, "Build this"), the seed and "cites N places" on the build, and an **Evidence** panel with a recheck on the skill's page | the three places a person would look |
| Not in this slice | Settings, a drawn graph (numbers and tables only), citing or refreshing from a page, evidence for plugins and MCP servers | said plainly at the end |

## Steps (tests first)

1. Backend: migration 0004, `Builder.start(seed=)`, evidence at the end of `_build`, `seed` in the session view.
2. Backend: `POST /api/repos/analyze`; `POST/GET /api/suggestions`; `repo`, `focus`, `evidence_nodes` on `POST /api/builds`; hosted 403.
3. Frontend: types and client, `lib/repository.ts` (pure helpers, unit tests), the Repository page, the Builder session and Library skill page changes, the menu.
4. Real browser: the whole flow against the API with a scripted fake model (the existing e2e harness).
5. Real run: the flow against this repository with the configured model.
6. Docs, README, roadmap, memory; one independent review; commit and push.
