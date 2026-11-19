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
| D2. Product | UI and database next (the library's folder store is what the database would replace). Agent Builder last. | **Next: Web UI and database** |

Why this order: slice A needs no model, no key and no network, so it is fully testable offline and every
later slice stands on it. Generated code is never executed until the sandbox in slice D exists.

Decisions behind this are in [decisions.md](decisions.md).
