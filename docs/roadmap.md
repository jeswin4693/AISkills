# Roadmap

SkillForge AI does three things, built in this order:

```
 Repo --> UNDERSTAND --graph facts--> SUGGEST --ideas with evidence--> BUILD --> skill packages
          (no AI)                     (AI + graph)                      (AI + templates)
```

| Slice | What | Status |
|---|---|---|
| A. Understand | Repository graph: functions, calls, imports, impact, duplicates, hotspots, dead-code candidates. Python + TypeScript/JavaScript. Incremental cache. CLI. Tests. See [graph.md](graph.md). | **Built, 51 offline tests** |
| B. Providers + Suggest | One `LLMProvider` interface (Gemini first, through its OpenAI-compatible endpoint), a mock provider for tests. Suggestions from graph facts. Every suggestion must cite real graph nodes, and uncited ones are dropped. | Next |
| C. Build | Requirement text, clarifying questions, requirement spec, skill definition, generated files, `report.md`. See [step1-proposal.md](step1-proposal.md). A suggestion can seed a requirement spec. | After B |
| D. Safety and product | Validators, Docker sandbox for generated scripts (fail closed), UI, database, versioning, export. Agent Builder last. | Later |

Why this order: slice A needs no model, no key and no network, so it is fully testable offline and every
later slice stands on it. Generated code is never executed until the sandbox in slice D exists.

Decisions behind this are in [decisions.md](decisions.md).
