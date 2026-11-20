# Component Factory, Phase 2: the Plugin Builder v1 (short plan)

> Executed inline with TDD, one commit per task, no model calls. Spec: [docs/component-factory.md](../../component-factory.md) (Phase 2, "Rules this adds", plugin format facts).

**Goal:** assemble a Claude Code **plugin** from skills and agents already in the library: pick components, name it, see what it can do on the machine (computed by code), and get a checked plugin folder with `.claude-plugin/plugin.json`, a local marketplace file, `skills/`, `agents/` and a README, kept in its own library, exported and installable from a folder.

**Format facts (checked 2026-11-20 with `claude plugin validate <path> --strict`, CLI 2.1.325, on a hand-made plugin):** a folder with `.claude-plugin/plugin.json` (`name`, `version`, `description`), `.claude-plugin/marketplace.json` (`name`, `owner.name`, `plugins[{name, source: "./", description}]`, entry name equals manifest name), `skills/<name>/SKILL.md` and `agents/<name>.md` is accepted. Warnings only for: no author, no marketplace description (both fixed by writing them), and README, LICENSE and icon for Anthropic's public directory (not needed locally). Install is `claude plugin marketplace add <folder>` then `claude plugin install <name>@<marketplace>`.

**Decisions:**
- A plugin is **composed, not described**: no conversation, no model. `Kind.conversational = False`; `Builder.start` refuses it with a plain message; the Builder picker lists only conversational kinds.
- A skill is copied whole except `spec.json` (the requester's own words); an agent contributes only `AGENT.md`, written as `agents/<name>.md`. Components are read through the library (hash-verified and re-gated), so a damaged or failing component is refused.
- Names: lowercase letters, digits, hyphens, at most 64; **not** starting `claude-` or `anthropic-`. The marketplace is `<name>-local`; the plugin version is `0.1.<n>` and bumps only when the content changes.
- What the plugin can do is computed by code from the components' `allowed-tools`, `tools` and scripts (`script_capabilities`), listed in the preview, the README and the checks. Hooks and MCP servers are not part of v1 (always empty).
- The plugin's own definition check (`validate/plugin.py`) fails on: no manifest, invalid JSON, a missing or invalid `name`, a reserved name, a marketplace entry whose name differs from the manifest. It warns on scripts inside the plugin (listing what they can do), because the shared script checks only look at a top-level `scripts/`.
- Install is a folder copy to a folder the person chooses (no personal target): the app never writes Claude's settings.

**Out of scope:** hooks, MCP servers, `userConfig`, a risk diff that sees scripts nested in `skills/` (Phase 4), running `claude plugin validate` inside the test suite (it is run by hand and reported), the CLI, a model-written README.

**Global constraints:** Python from `backend/` (`C:/dev/venvs/aiskills/Scripts/python.exe -m pytest`); tests offline; no new library; a kind is a registry key, never a path; skill and agent behaviour unchanged; existing tests change only where a task says so. Commits end with `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`.

## Review Focus
- A damaged, failing or missing component can never end up inside a saved plugin (task 2).
- No path in a component's files can leave its folder in the plugin, and no file name can collide across components (task 2).
- The capability list is complete: a skill's `allowed-tools`, an agent's `tools` and every script's capabilities all show; nothing is claimed that code did not compute (task 2).
- A reserved or invalid plugin name is refused everywhere: compose, import, and a zip imported from outside (tasks 2, 3).
- Exported plugin zip imports back identical, including the dot-folder (task 4).
- Composing unchanged components twice makes no second version (task 4).

### Task 1: kinds that are not described
`kinds/base.py` (`conversational: bool = True`), `builder/service.py` (`start` refuses a non-conversational kind), `api/app.py` (`/api/kinds` lists `conversational`; install refuses a target the kind does not offer). Tests: a fake non-conversational kind is refused by `start` with a plain message; `/api/kinds` lists the flag; installing with a target outside `install_targets` is a 400.

### Task 2: compose a plugin
`library/plugin.py`: `ComponentRef(kind, name, version=None)`, `Capabilities`, `PluginPlan(name, version, files, capabilities, components, checks)`, `compose_plugin(library, components, *, name, description, version, author="") -> PluginPlan`, `PluginError(LibraryError)`. Tests: exact file list and manifest/marketplace content; `spec.json` left out; reserved and invalid names; empty, duplicate and unknown components; capabilities (Bash from an agent, `allowed-tools` from a skill, a network script, hooks and MCP empty); a damaged component is refused.

### Task 3: the plugin kind and its definition check
`validate/plugin.py` (`check_plugin_json`, registered in `validate/__init__.py`), `kinds/plugin.py` (`PluginKind`: key `plugin`, `library_dir` `library-plugin`, `definition_file` `.claude-plugin/plugin.json`, `install_targets` `("folder",)`, `conversational` False), registry. Tests: each check; every kind still has a definition check; a hostile zip with a reserved name is refused on import.

### Task 4: API, save, export, install
`POST /api/plugins/preview` and `POST /api/plugins` (save through the checked import; 422 when refused; version bump only on change), plus the existing library routes with `?kind=plugin`. Tests: preview shows capabilities and files and saves nothing; save lands in `library-plugin`; unchanged recompose makes no new version and a changed one bumps `0.1.n`; export then import is identical; install copies the folder.

### Task 5: the composer page
`frontend/src/app/composer/page.tsx`, a nav link, `lib/plugin.ts` (request building, selection helpers), `api.previewPlugin` / `api.savePlugin`, `KindInfo.conversational`, the Builder picker lists only conversational kinds. Tests: pure helpers. Then typecheck, unit tests, build, the browser suite (39 existing must pass).

### Task 6: verify, document, finish
Run `claude plugin validate <built plugin> --strict` by hand on a plugin built through the API and report its output. Docs (`docs/plugin-builder.md`, component-factory, roadmap row Q, api, library, README, CLAUDE.md), full runs, one review (cost stated first), merge and push, memory notes.
