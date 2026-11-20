# Component Factory, Phase 1: the Agent Builder (short plan)

> Executed inline with TDD, one commit per task. Spec: [docs/component-factory.md](../../component-factory.md) (Phase 1, "Rules this adds", subagent format facts).

**Goal:** a second kind, `agent`: describe a Claude Code subagent in words, answer what is missing, approve, and get an `AGENT.md` (front matter written by code, explicit `tools`, the person's rules carried word for word) that is checked, kept in its own library, exported, and installed as `~/.claude/agents/<name>.md`.

**Decisions (made while planning; each can be undone):**
- The library folder holds `AGENT.md` (like `SKILL.md`), plus `README.md`, `agent.sdm.json`, `spec.json`, `tests/cases.json`, `report.md`. **Install writes only `<name>.md`** into the agents folder (one file, not a folder).
- The same six checklist slots, in agent wording (goal, inputs, outputs, constraints, acceptance criteria, failure behaviour). The extraction's guess of `kind` never blocks an agent request.
- `tools` is always written, explicitly, by code from the model's `permissions` through `tools_for`; with no permission at all it is still `Read, Grep, Glob` (an empty or missing `tools` would give the agent every tool). `permissionMode`, `model`, `hooks` and `mcpServers` are never written.
- No `eval` for agents: their test cases are data, and the report says they were not run (a check is "passed" only if it ran).
- Imported agents: a missing `tools` fails; `bypassPermissions`, `hooks` and `mcpServers` warn. No unknown-key list (the subagent key list is incomplete in the spec and not verified).
- A zip's single top folder is unwrapped when it holds any registered kind's definition file (fixes ruling R10 for agents).
- Folded in from Phase 0's deferred minors: a test that every registered kind has a definition check; "Build an agent" (article); `definition_file` in `GET /api/kinds`.

**Out of scope:** running the agent builder against a live model, an agent flow in the real browser, `--kind` on the command line, `eval` from the web, plugin and MCP builders, an `AgentKind` choice of `model`.

**Global constraints:** run Python from `backend/` (`C:/dev/venvs/aiskills/Scripts/python.exe -m pytest`); tests offline (`MockProvider`); no new library; every model call names its task (`Task.EXTRACT`, `Task.DESIGN`); a kind is a registry key, never a path; skill behaviour and every skill request unchanged; existing tests change only where a task says so. Commits end with `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`.

## Review Focus
- A request that is plainly a skill still gets the skill's "this is not a skill" refusal in the skill builder (task 1).
- Model text is data: `{{ 7*7 }}`, `---` and newlines in any field cannot break the front matter or run as a template (task 2).
- No path to an agent file without an explicit `tools` line, however empty the model's permissions (tasks 2, 3).
- A repaired design is never worse than the first; a design with an uncovered acceptance criterion is a failed check, not a pass (task 3).
- Installing an agent never replaces an existing file without `force`, never writes outside the chosen folder, and backs up first (task 5).
- Exported agent zip imports back to identical content (task 5).

### Task 1: understanding for any kind
**Files:** `backend/skillforge/build/requirements.py`, `build/pipeline.py`; test `tests/test_agent_build.py`.
**Interface:** `understand_round(provider, words, round_no, max_rounds, *, questions=QUESTIONS, extract_system=EXTRACT_SYSTEM, skill_only=True) -> Round`; `check_completeness(spec, *, skill_only=True)`; `questions_for(missing, questions=QUESTIONS)`; `extract_spec(provider, words, rounds=1, system=EXTRACT_SYSTEM)`. Defaults keep every skill path identical.
**Tests:** an agent-wording extraction with `kind="agent"` completes with `skill_only=False` and is `blocked` with the defaults; the questions asked use the agent wording passed in.

### Task 2: the agent definition, design, assembly and files
**Files:** create `build/agent.py` (models `AgentTest`, `AgentDraft`, `AgentDefinition`; `AGENT_QUESTIONS`, `AGENT_EXTRACT_SYSTEM`, `AGENT_DESIGN_SYSTEM`; `design_agent`, `assemble_agent`; `render_agent_files(defn, spec) -> dict[str, str]`).
**Interface:** `assemble_agent(draft, spec, provider, now) -> AgentDefinition` (slug name, cleaned triggers, `compose_description`, `tools` from `tools_for` with the `Read Grep Glob` floor, criteria ids); `render_agent_files` returns `AGENT.md`, `README.md`, `agent.sdm.json`, `spec.json`, `tests/cases.json`. `AGENT.md` front matter is `name`, `description`, `tools` only, written with the YAML library; body: role, "When you are called" steps, "What to report", "Rules" (the person's constraints word for word, then the model's), "Done when" (criteria word for word), "If something goes wrong".
**Tests:** tools by permission (`[]` and `["read_files"]` both `Read, Grep, Glob`; `run_commands` adds `Bash`); front matter keys exactly `name, description, tools`; hostile text (`{{ 7*7 }}`, `---`, newlines) stays data; the person's lines appear verbatim; same definition gives the same bytes.

### Task 3: checks and the build pipeline
**Files:** `build/agent_pipeline.py` (`check_agent(defn, files) -> list[CheckResult]`, `AgentBuildResult`, `build_agent_from_spec(spec, provider, *, out_root, force, now=None, calls=0, notes=None, progress=None)`); `kinds` uses it in task 5.
**Checks (FAILED):** valid name, description present and at most 1024, role and output format present, at least one step, every acceptance criterion covered by a test, a positive and a negative test, the person's rules and criteria present word for word in `AGENT.md`. **Warnings:** vague wording, a step over 60 words, more than 7 steps. Plus the shared static checks with `kind="agent"`, plus one `not run` row ("test cases were not run against a model"). One repair attempt, kept only if not worse (`_score` as for skills). `status` is `draft` if any check failed, else `ok`.
**Tests:** a clean build writes every file and is `ok`; an uncovered criterion is `failed` and triggers one repair; a worse repair is discarded; the `not run` row is present; the files are written under `out_root/<name>`.

### Task 4: the definition check for imported agents
**Files:** create `validate/agent.py` (`check_agent_md(files, folder)`), register in `validate/__init__.py` as `DEFINITION_CHECKS["agent"]`; tests in `tests/test_validate.py`, `tests/test_kinds.py`.
**Checks:** `AGENT.md` exists with valid front matter; `name` a slug of at most 64; `description` present; body not empty; `tools` present and non-empty (FAILED if not); a warning each for `permissionMode: bypassPermissions`, `hooks`, `mcpServers`; a folder-name warning like the skill's.
**Tests:** each case above; `set(KINDS) <= set(DEFINITION_CHECKS)` (the Phase 0 minor).

### Task 5: `AgentKind`, the library, install and the API
**Files:** `kinds/base.py` (`definition_file: str`, `install_file: str | None = None`), `kinds/skill.py`, create `kinds/agent.py` (`AgentKind`, `summarize_agent`), `kinds/__init__.py` (register after `skill`), `library/package.py` (`_strip_top_folder` uses every kind's `definition_file`), `library/service.py` (`install_skill` writes `<name><suffix>` when the kind has `install_file`), `api/app.py` (`definition_file` in `/api/kinds`); update tests that list the kinds; `tests/test_agent_kind.py`.
**`AgentKind`:** key `agent`, label `Agent`, `library_dir` `library-agent`, `definition_file` and `install_file` `AGENT.md`, `personal_dir` `~/.claude/agents`, `name_of` from `AGENT.md`'s front matter, `understand` and `build` through tasks 1 to 3.
**Tests:** a whole conversation through the API with `MockProvider` (start `agent`, answers, approve, save) lands in `library-agent`; export then import gives identical content; install writes only `<name>.md`, refuses an existing file without `force` and backs it up with `force`; rescan is `same`; `/api/kinds` lists both kinds with `definition_file`.

### Task 6: the web UI
**Files:** `lib/types.ts` (`definition_file`), `lib/builder.ts` (`withArticle`), `lib/kind.ts` (`kindQuery`), `app/library/page.tsx` (tabs when more than one kind, `?kind=`), `app/library/[name]/page.tsx`, `app/library/[name]/diff/page.tsx`, `components/ImportPanel.tsx`, `InstallDialog.tsx`, `RescanPanel.tsx`, `FileViewer.tsx`, `builder/ResultCard.tsx`, `app/builder/page.tsx` (title uses the article); test `lib/builder.test.ts`.
**Behaviour:** every library call and link carries `?kind=` only for a kind other than skill; the definition file sorts first; the import text names the kind's file.
**Tests:** `withArticle("agent") === "an agent"`, `withArticle("skill") === "a skill"`; `kindQuery("skill") === ""`, `kindQuery("agent") === "?kind=agent"`. Then typecheck, unit tests, `npm run build`, the real-browser suite (39 existing behaviours must pass; set `SKILLFORGE_PYTHON`).

### Task 7: documents, full run, finish
`docs/agent-builder.md` (new), `docs/component-factory.md`, `docs/roadmap.md` (row P), `docs/api.md`, `docs/library.md`, `README.md`, `CLAUDE.md` next step; memory notes. Full backend suite, UI tests, browser suite; merge and push (project rule: push after each slice).
