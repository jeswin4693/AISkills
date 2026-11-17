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
| D1. Safety | Static validators for any skill folder (hidden text, attack wording, scripts versus declared permissions, structure) run on every build; a Docker sandbox runner that fails closed. See [validate.md](validate.md). | **Built and proven: ~190 tests, including 7 that run real Linux containers (via Docker in WSL) and prove the locks** |
| D2. Product | UI, database, versioning, export, import. Agent Builder last. | Later |

Why this order: slice A needs no model, no key and no network, so it is fully testable offline and every
later slice stands on it. Generated code is never executed until the sandbox in slice D exists.

Decisions behind this are in [decisions.md](decisions.md).
