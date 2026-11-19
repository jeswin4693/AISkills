# Roadmap

SkillForge AI does three things, built in this order:

```
 Repo --> UNDERSTAND --graph facts--> SUGGEST --ideas with evidence--> BUILD --> skill packages
          (no AI)                     (AI + graph)                      (AI + templates)
```

| Slice | What | Status |
|---|---|---|
| A. Understand | Repository graph: functions, calls, imports, impact, duplicates, hotspots, dead-code candidates. Python + TypeScript/JavaScript. Incremental cache. CLI. Tests. See [graph.md](graph.md). | **Built** |
| B. Providers + Suggest | One `LLMProvider` interface (Gemini and OpenAI through one adapter, plus a mock for tests). A review pass and an ideas pass over a fact sheet from the graph. Every suggestion must cite real graph nodes; uncited ones are dropped. See [suggest.md](suggest.md). | **Built; 83 offline tests; verified live with Gemini** |
| C. Build | Requirement text, clarifying questions (completeness decided by a checklist, answers backed by verified quotes), approval, skill definition, generated files, `report.md`. A suggestion can seed it. See [build.md](build.md) (original plan: [step1-proposal.md](step1-proposal.md)). | **Built; 127 offline tests; verified live with Gemini** |
| D1. Safety | Static validators for any skill folder (hidden text, attack wording, scripts versus declared permissions, structure) run on every build; a Docker sandbox runner that fails closed. See [validate.md](validate.md). | **Built and proven: 14 real-container tests (Docker in WSL) prove the locks and the per-language runs; 232 tests in total** |
| E. Any language | The graph, validators and sandbox work beyond Python and TypeScript: 45 languages at three honest levels (full, standard, basic), Java/Go/Rust/C/C++/C#/Ruby/PHP/Kotlin with resolved imports and calls, grammars loaded on demand with an offline mode, interpreter languages runnable in the sandbox. See [languages.md](languages.md). | **Built and tested** |
| F. Scripts | `build --scripts`: the model writes helper scripts and test cases, code checks them, every case runs in the sandbox, one repair attempt shown the real output. A case passes only if it ran; untested scripts make the skill a DRAFT. See [scripts.md](scripts.md). | **Built; 273 tests in total (36 offline script tests, 5 more real-container tests); verified live: real containers and Gemini** |
| G. Library | `library import` (static checks first, refused if one fails; folders and untrusted zips), numbered versions with a SHA-256 manifest (tamper-evident), `diff`, `rollback` (adds a version), deterministic `export` zip, `install` to `.claude/skills` (explicit target, backup before `--force`), opt-in `--test-scripts` re-run in the sandbox. See [library.md](library.md). | **Built and tested; checked on the real CLI on Windows; not yet used on skills from other people** |
| H1. API | Local HTTP API (FastAPI, `serve`, 127.0.0.1 only): library, validate, sandbox status and languages endpoints; Host and Origin checks against DNS rebinding and cross-site requests; capped in-memory uploads. See [api.md](api.md). | **Built and tested; checked against a real running server (curl)** |
| H2. Database + builder sessions | SQLAlchemy + Alembic (SQLite first, one URL setting for another database); the skill builder as a session across requests: questions, answers, approval, then background jobs with progress, retry, save to the library. Same rules as the CLI (checklist in code, verified quotes, approval before building). See [database.md](database.md), [api.md](api.md). | **Built and tested (offline, incl. real threads); verified live with Gemini: a full conversation produced a skill with 21 checks passed. Not tried: PostgreSQL, building with scripts over HTTP with a real sandbox** |
| D2. Product | Rest of the plan in [ui-and-database-plan.md](ui-and-database-plan.md): H3 UI shell + Library page, H4 builder chat page, H5 other pages and Settings. Agent Builder last. | **Next: H3 (web UI shell + Library page)** |

Why this order: slice A needs no model, no key and no network, so it is fully testable offline and every
later slice stands on it. Generated code is never executed until the sandbox in slice D exists.

Decisions behind this are in [decisions.md](decisions.md).
