# Component Factory: skills, agents, plugins and MCP servers from one app

**Status: planned and approved by the project owner (2026-11-19). Built so far: the shared model service
([ai-engine.md](ai-engine.md)), Phase 0 (the foundation), Phase 1 (the Agent Builder), Phase 2 (the Plugin Builder) and Phase 3 (the MCP Builder, Python), all 2026-11-20 (plans: [phase 0](superpowers/plans/2026-11-20-component-factory-phase-0.md), [phase 1](superpowers/plans/2026-11-20-agent-builder-phase-1.md), [phase 2](superpowers/plans/2026-11-20-plugin-builder-phase-2.md), [phase 3](superpowers/plans/2026-11-20-mcp-builder-phase-3.md); what each did and did not do is under "Phase 0/1/2/3: what was built" below, in [agent-builder.md](agent-builder.md), [plugin-builder.md](plugin-builder.md) and [mcp-builder.md](mcp-builder.md)). Phase 4a (MCP servers inside plugins, [plan](superpowers/plans/2026-11-23-plugin-mcp-phase-4a.md)) and Phase 4b (hooks from a catalogue, [plan](superpowers/plans/2026-11-23-plugin-hooks-phase-4b.md)) were built on 2026-11-23. Nothing else here is built.** Next: the TypeScript half of Phase 3, or whatever the roadmap names.

## What

Grow SkillForge from a skill builder into four builders that share one app, one database, one library and one model service:

| Builder | Output | Model calls (typical) |
|---|---|---|
| Skill (exists) | `SKILL.md` and supporting files | 3 to 5 |
| Agent | a Claude Code subagent file (`<name>.md`: front matter + system prompt) and its definition, spec, tests | 3 to 5 |
| Plugin | an installable plugin: manifest, skills, agents, later hooks and MCP, plus a local marketplace entry | 0 (assembled from the library) |
| MCP server | a Python or a Node (TypeScript) server project, tested over the MCP protocol in the sandbox | 4 to 7 |

Not rebuilt, not broken: every existing route, test and page keeps working (a new `kind` defaults to `skill`).

## Architecture

```
words -> extract -> CHECKLIST -> ask -> APPROVE -> design -> render -> CHECKS -> repair x1 -> (eval) -> files + report
         (model)    (code)              (you)      (model)   (code)    (code)
  each KIND supplies: slots + questions | draft model + prompt | templates | checks | eval adapter | install target
  Library: one root per kind (the skill one stays where it is), SHA-256 versions, risk diff, rescan, export, install
```

- **Strangler, not rewrite:** `SkillKind` is a thin adapter over today's functions; the command-line path is untouched and the
  existing tests are the safety net.
- **Library:** `Library(kind=...)`; separate roots (`library`, `library-agent`, `library-plugin`, `library-mcp`): no migration, no
  name collisions. `validate_files` gets a `kind`; only the `SKILL.md` check is skill-specific.
- **Database:** migration 0003 adds `build_sessions.kind` (default `skill`) and `parent_id` (a plugin's child builds).
- **API:** existing routes unchanged; `POST /api/builds` takes an optional `kind`; `GET /api/kinds` (slots, labels, install
  targets); `?kind=` on the library routes.
- **UI:** `/builder` gets a kind picker, sessions a kind badge, slot labels come from the server instead of `lib/builder.ts`; the
  Library gets tabs per kind; a plugin composer page picks components from the library and shows what the plugin can do on the machine.
- **Models:** every call names its task (`skillforge.ai`). MCP tool bodies use the `code` tier; escalation and the tier benchmark
  (A4) come before the MCP builder is trusted.

## Phases (highest value first)

| Phase | What | Size |
|---|---|---|
| 0 | Foundation: kind registry, `SkillKind` adapter, migration 0003, `Library(kind)`, validator `kind`, API and UI picker; small skill improvements (`permissions` to `allowed-tools`, warn on unknown front-matter keys, run `eval` from the web pages) | M |
| 1 | **Agent Builder** | M |
| 2 | Plugin Builder v1 (skills and agents) | M |
| 3 | MCP Builder: Python first (**built**), then TypeScript (**built**, 3b) | XL, then M |
| 4 | Plugin v2: MCP, a hook catalogue, `userConfig`; risk diff for every kind. **4a (MCP servers and `userConfig` in a plugin, and the risk diff for them) and 4b (hooks from a catalogue) are built** | L, in slices |

Sizes are guesses at this repo's pace (S 1 to 2 days, M 3 to 5, L 1 to 2 weeks, XL more), including tests, docs and a live check.

## Phase 0: what was built (2026-11-20)

- `skillforge/kinds/`: `Kind` (key, label, `library_dir`, checklist `slots`, `install_targets`, `name_of`, `personal_dir`, `understand`,
  `build`), the registry (`KINDS`, `get_kind`, `all_kinds`) and `SkillKind`, a thin adapter over the old functions.
- `Library(root, kind="skill")` and `Library.for_kind(kind)`: one root per kind next to the skill one (`library-<kind>`,
  `backups-<kind>`); the skill library did not move.
- `validate_files(..., kind=)` with `DEFINITION_CHECKS`: only the definition-file check varies by kind.
- Migration 0003: `build_sessions.kind` (default `skill`) and `parent_id` (no foreign key: SQLite cannot add one to an existing table).
- The builder runs `understand` and `build` through the session's kind. A session whose kind is no longer registered can be read,
  listed and discarded, and fails plainly when continued.
- API: `GET /api/kinds`; `?kind=` on every library route, `rescan` and `validate`; `kind` on `POST /api/builds`. An unknown kind is a 400.
- UI: a kind picker and badge, shown only when more than one kind exists; the requirement and question labels come from the server.
- `build/tools.py`: a skill's permissions become `allowed-tools` (a grant; `Bash` is not narrowed to the skill's scripts).
  `validate/formats.py`: the front-matter keys Claude Code knows, read on 2026-11-20 from the skills page through a summarising fetch;
  an unknown key warns.

**Not done, on purpose:** running `eval` from the web pages (it takes minutes and many model calls, the hosted version forwards
`/api/*` through a rewrite that I believe cuts a request at about 30 seconds, and the `jobs` table only exists per builder session, so
it needs a job that is not a builder session); library tabs and per-kind skill and compare pages (Phase 1, when a second kind exists
to look at); a `--kind` flag on the command line.

**Skill-shaped parts a second kind must decide for itself:** a zip's single top folder is unwrapped only when it holds a `SKILL.md`
(`library/package.py`), so a zip of another kind keeps its files at the top of the zip until that kind chooses a layout;
`retest_scripts` and the risk diff read skill files (Phase 4 widens the risk diff); `Round`, which a kind's `understand` returns,
still carries a skill-shaped `RequirementSpec`.

## Phase 1: what was built (2026-11-20)

The Agent Builder, in [agent-builder.md](agent-builder.md): `AgentKind` (`AGENT.md`, `library-agent`, installs as one file `<name>.md`
into `~/.claude/agents`), the same six-item checklist in agent wording, a design the model drafts and code turns into `AGENT.md`
(front matter by YAML: `name`, `description`, `tools` only; the person's lines word for word), checks decided by code with one repair
kept only if not worse, a definition check for imported agents, a library tab and `?kind=` through every web page.

Changes that reach beyond the agent: `understand_round`, `extract_spec`, `check_completeness` and `questions_for` take the kind's own
wording and a `skill_only` switch (defaults keep the skill builder identical); `Kind` has `definition_file`, `install_file` and
`personal_label`; a zip's single top folder is unwrapped for any kind's definition file (this settles the Phase 0 zip limit);
`install_skill` writes one file for a kind that has an `install_file`; `GET /api/kinds` lists `definition_file`, `personal_label`
and `installs_as_file`; a test that every registered kind has a definition check (a Phase 0 deferred minor); "Build an agent".

**Not done, on purpose:** a run against a live model, an agent flow in the real browser, `eval` for agents (their test cases are data and
are reported as not run), unknown front-matter keys for agents (the list is not verified), risk-diff rules beyond `AGENT.md` and its `tools` line (Phase 4), a `model`
choice for the agent, `--kind` on the command line, and Phase 0's `eval` from the web pages.

## Phase 2: what was built (2026-11-20)

The Plugin Builder, in [plugin-builder.md](plugin-builder.md). A plugin is **composed, not described**: no conversation and no model. You pick
skills and agents already in the library; `library/plugin.py` reads each through the library (hash-verified and re-gated), writes `.claude-plugin/plugin.json`,
a local `.claude-plugin/marketplace.json` that points at the folder itself, `skills/`, `agents/` and a README, and computes what the plugin can do on the
machine (tools granted, scripts shipped and what they use). `PluginKind` (`library-plugin`, installs from a folder only, `conversational = False`),
`validate/plugin.py` (a valid manifest, a name that is not reserved (`claude-`, `anthropic-`), a matching marketplace entry, something inside, and what the
scripts inside can do), `POST /api/plugins/preview` and `POST /api/plugins`, a **Plugins** page (`/composer`), and a version `0.1.<n>` that moves only when the
content does. Changes beyond the plugin: `Kind.conversational` (the Builder refuses and does not list a kind that is composed), and install refuses a target the kind
does not offer.

**Checked against the real tool:** a plugin built by this code passes `claude plugin validate --strict` (Claude Code 2.1.325, 2026-11-20): the manifest, the
skills folder, the agents folder and the whole folder. **Not done, on purpose:** hooks, MCP servers and `userConfig` (Phase 4), a risk diff that sees scripts
nested under `skills/` (Phase 4), a real `claude plugin marketplace add` and `install` (they change the person's Claude settings, so the person runs them), a
LICENSE or icon, `--kind` on the command line.

## Phase 3: what was built (2026-11-20)

The MCP Builder (Python), in [mcp-builder.md](mcp-builder.md). `McpKind` (`library-mcp`, definition file `server.py`, installs into a folder only, conversational): the model drafts
the tools, code assembles `server.py` around them (imports, signatures, docstrings, per-tool annotations, `mcp.run()`), pins `mcp==2.3.0`, writes the README with the exact
`claude mcp add` command and carries the person's own words in; `validate/mcp.py` checks the file by reading it (what runs commands, builds code from text, loads native code or
carries a key fails; network, writes, other packages, a computed environment name and a name that is never defined warn), `build/mcp_pipeline.py` adds the builder's stricter rules and
one repair kept only if not worse, and `build/mcp_protocol.py` starts the server **in the sandbox** with a fixed harness and calls every test case over the real MCP protocol, graded by code.
`python -m skillforge sandbox-build-mcp` builds the one image (`skillforge-mcp:2.3.0`) once. The risk diff reads a server's code, its tools and its environment variables. Changes beyond the
kind: the save message names what was built ("This MCP server is a DRAFT"), and the web pages say "MCP server" where they said "skill".

**Checked against the real tools (2026-11-20):** the SDK names by a real install; a generated server started and called in a real container; two real builds with the configured model, which
found and fixed two defects a mock model could not (missing imports, and a tool that returned simulated data). **Not done, on purpose:** TypeScript, HTTP transport, resources and prompts, OAuth,
packages beyond the standard library, file writes and commands, `claude mcp add` run for you, a live Claude Code run, `eval` for servers, `--kind` on the command line, an MCP flow in the real browser.

## Phase 3b: what was built (2026-11-23)

The MCP Builder for Node (TypeScript), in [mcp-builder-node.md](mcp-builder-node.md), [plan](superpowers/plans/2026-11-23-mcp-node-phase-3b.md). `McpNodeKind` (`mcp-node`, "MCP server (Node)", `library-mcp-node`, definition file `server.ts`, installs into a folder only, conversational): a **separate kind**, so
the plugin composer (which lists the `mcp` kind) cannot include one. The model drafts function bodies and a list of imports **as data**; code writes `server.ts` for the official TypeScript SDK v2 (`@modelcontextprotocol/server` 2.4.0, zod 4.6.7) with the zod schema, the handler,
the per-tool annotations and the transport, plus a `package.json` (exact versions, no `scripts`, `"type": "module"`) and the pinned lockfile (`mcpnode/lock.template.json`, only the package name differs). `validate/mcp_node.py` reads any `server.ts` with tree-sitter (programs, code built from text, network, file writes,
a key in pieces, env vars, install scripts, other code beside it, case aliases of `package.json`, other lockfiles); `build/mcp_node_pipeline.py` holds a body to allow-lists (names, properties, imports, provably-numeric indexes); `build/mcp_node_protocol.py` runs a fixed `.mjs` harness in the locked container from the image
`skillforge-mcp-node:2.4.0` (`python -m skillforge sandbox-build-mcp-node`), with the server started as `node --permission`. The shared grader (`mcp_protocol.py`) now takes a `Flavour`; the Python behaviour is unchanged (136 protocol and security tests still pass). The risk diff reads a Node server's code and `package.json` (a new install script, dependency, `overrides` or a lockfile that is no longer the pinned one is riskier).

**Checked against the real tools (2026-11-23):** the SDK names by a real install and run; `node server.ts` needs `"type": "module"`; Node's permission model refused a write, a program and an outside read in the real container; real Claude Code 2.1.325 accepted the README's `claude mcp add ... node --permission` command (isolated config folder) and listed the server as Connected, and a real
session called its tool; two real builds with the configured model (a word-tools server: ok, 60 of 60 checks, 2 model calls; a weather tool with a key: an honest DRAFT, its network cases not run), the second of which showed a model defect no check could see (the tool hard-coded the test's city), now a warning. **Not done, on purpose:** Node servers inside plugins (a plugin cannot run `npm ci`), HTTP transport,
resources and prompts, a TypeScript type check, the Node flow in a real browser.

## Phase 4a: what was built (2026-11-23)

MCP servers inside plugins, in [plugin-builder.md](plugin-builder.md). A plugin can hold MCP servers from the MCP library (`ComponentRef("mcp", name)`, `"kind": "mcp"` in the API): the composer writes
`servers/<name>/`, a root `.mcp.json` that starts each (`python ${CLAUDE_PLUGIN_ROOT}/servers/<name>/server.py`), and one `sensitive`, `required` `userConfig` option per environment variable the server's code
reads, passed as `${user_config.KEY}` (never a value). `validate/plugin.py` reads a plugin's servers with the MCP kind's own checks and checks that `.mcp.json` starts only what is shipped, in the composed form
(anything else is warned about with the command shown; an undeclared option fails; a `userConfig` key Claude Code refuses fails the manifest). `library/plugin.py` computes what each server can do (`analyze_server`)
and says it in plain sentences. `library/risk.py` calls a new server, a changed start command, a new `.mcp.json` entry and a newly passed variable riskier. The composer page lists MCP servers and shows "Programs this plugin starts".

**Checked against the real tool (2026-11-23, Claude Code 2.1.325):** `claude plugin validate --strict` reads `.mcp.json`, refuses a `userConfig` key with a dash, dot, space or leading digit, and fails an undeclared
`${user_config.X}`; a plugin composed from two real library servers (one reading a key) passes with exit 0. **Read from the docs by a research agent, not tried:** a plugin's MCP servers start when it is enabled with no
per-server approval, outside the sandbox; `claude plugin install --config key=value` exists (checked in `--help`); the docs do not say a stdio server inherits Claude Code's environment, so every variable is passed explicitly.
**Not done, on purpose:** a managed Python environment (the command is plain `python`), TypeScript or remote servers. (Hooks were built after in 4b; a real install, the MCP picker in a browser and an independent review were done afterwards and are in "Phase 4 after the review" below.)

## Phase 4b: what was built (2026-11-23)

Hooks inside plugins, from a catalogue only ([hook-catalogue.md](hook-catalogue.md), [plugin-builder.md](plugin-builder.md), [plan](superpowers/plans/2026-11-23-plugin-hooks-phase-4b.md)). `skillforge/hookcatalog/`: a table of three
vetted hooks (block secret files, block forced git pushes, log tool names) and one short standard-library script each, with typed options handed to the script as separate exec-form arguments. `ComponentRef("hook", id, options=...)` and
`"kind": "hook"` in the API: the composer writes `hooks/hooks.json` and the catalogue's script unchanged, and describes every hook plainly (when it runs, whether it can block, what its script can do, what was chosen). `validate/plugin.py`
recognises a hook only when it is exactly a catalogue hook (event, matcher, timeout, command, arguments, and a script whose SHA-256 is the catalogue's, line endings ignored); anything else is warned about with the command shown, and a plugin
that holds nothing it can describe has no content. `library/risk.py` calls a new hook, a changed trigger and a script that is no longer the catalogue's riskier, and now compares any code a plugin ships outside its components. `GET /api/hooks`,
a Hooks card and a "Hooks this plugin runs" preview section on the composer page.

**Checked against the real tool (2026-11-23, Claude Code 2.1.325):** `claude plugin validate --strict` accepts a plugin of all three hooks. **And the hooks were run by real Claude Code**: with the plugin loaded for one session only (`--plugin-dir`, no settings
changed), in a scratch folder with a dummy `.env`, `block-secret-files` blocked a `Read` of `.env` and `block-force-push` blocked `git push --force`, each with its own reason shown to the model (the debug log: `Hook PreToolUse:Read error: status code 2`), an
ordinary `Read` of `notes.txt` went through, and `log-tool-calls` ran afterwards and wrote its line to the plugin data folder. That settles what the docs left open: the exec form with `python` and `${CLAUDE_PLUGIN_ROOT}` works on Windows, exit 2 blocks and its
stderr is the reason, `tool_input.file_path` is the field, and a plugin's hooks run without an approval prompt in a non-interactive session. The real-browser suite passes 42 of 42 (3 new composer behaviours). **Not done, on purpose:** hook types other than
`command`, hooks inside a skill's or agent's front matter (they are now listed with their commands, not built), `SessionStart` context injection (it feeds text to the model), and a managed Python.

## Phase 4 after the review and the real runs (2026-11-23)

After 4a and 4b were built and pushed, I ran what had been left unverified, and two fresh agents reviewed the slices (told to attack, not to confirm). What that changed:

**Real Claude Code (2.1.325, Windows) found two things the tests could not.**
- **A guard that cannot start fails open.** With `python` missing from the PATH, a `Read` of `.env` went through and the session said nothing. Every blocking catalogue hook now carries `"onFailure": "block"` (checked: a missing Python and a script that exits 1 then block, with the reason shown), the two guards block themselves
  (exit 2) when they cannot read the event, the validator requires the key on guards and refuses it on the logger, and the risk diff calls dropping it riskier. The guards' scripts are revision 2.
- **An option value is stored in `.credentials.json`** in the Claude folder (private to you, not a vault). The notes, README, page and docs said "kept as a secret"; they now say where.
- Confirmed: the `PowerShell` and `NotebookEdit` tool names and `notebook_path`; a real `claude plugin marketplace add` + `install --config` (in an isolated `CLAUDE_CONFIG_DIR`, so your settings were untouched) of a plugin with two MCP servers, both **Connected** in `claude mcp list`;
  and the option's value reaching the server's environment (a server that refuses to start without it connected with the right value and failed with a wrong one). The MCP picker was driven in a real browser (43 behaviours in all).

**The independent reviews** found 13 problems in 4a (2 Critical) and 12 in 4b (3 Critical), each reproduced by running code. All that I could reproduce are fixed and tested (the new tests were run on the code from before the fixes: about 110 of 150 failed there):
- *Critical, both slices:* a file whose name differs from a special file only in capitals (`.MCP.JSON`, `hooks/Hooks.json`), or with a trailing dot, space or colon (`server.py.`), is the same file on Windows and macOS but was never inspected, so a plugin could be reported fully described while running something else (now refused);
  a module planted beside a hook script (`hooks/json.py`, `json.pyw`) was imported instead of the standard library and could blind a guard (now: `python -I`, plus a warning for any other file in `hooks/`); the force-push guard missed line continuations, subshells, quoted `;`, `bash -c`, `powershell -Command`,
  Windows paths and `git.cmd` (now a real lexer, and a command too long to read is blocked).
- *Important:* the risk diff said nothing about an entry that arrived together with its server, a changed `userConfig` option (`sensitive` to false, a default added), an inline manifest `mcpServers`, a re-pointed environment value or hooks and commands declared in the manifest or a skill's front matter, and could not tell two hooks apart (now compared by whole object);
  an option could be wired to another server's variable and still count as "the composed form"; `g = os.environ.get` hid a variable from the analyser; extra keys beside `mcpServers` and the unshown tail of a long command hid things; a deeply nested JSON file crashed validation and a few bytes of Python could make the analyser build 8 million characters;
  `block-secret-files` was reached by `.env/.`, `C:.env` and 8.3 names; the catalogue's hash lived only in a test (now a constant in each entry, checked when a script is shipped).
- *Minor:* a server name starting with a digit, loader variables (`PYTHONPATH`) as options, secrets and URLs in reports, the click order changing the plugin and its version, a pip instruction for a server that ships no requirements file, option text kept in the page after a hook is unticked, and other places a plugin can run code
  (`commands/`, `monitors/`, `workflows/`, the `!` syntax, front-matter hooks), which came from a docs lookup.

**Still open, said plainly:** an interactive Claude Code session; macOS and Linux; the guards' known blind spots (shell commands and `Grep`/`Glob` for secrets; aliases, scripts, encoded commands, the Monitor tool and background shells for pushes); what Claude Code does with a `userConfig` option that has a default or is not required (the checks refuse such options for servers);
whether a key beside `mcpServers` in `.mcp.json` is read; older Claude Code (before 2.1.295) ignores `onFailure`.

## Decisions (approved)

Order as above. "Agent Builder" here means **definition files**, not a runtime agent loop (the Task Conductor's native loop in
[task-conductor.md](task-conductor.md) stays separate). MCP servers use the official SDKs at pinned versions, in two pre-built sandbox
images (Python, Node) made once with network and never pulled at run time; this needs Docker or WSL. Hooks come from a catalogue only,
in exec form (`command` + `args`, no shell), and are always flagged as riskier. One library root per kind.

## Rules this adds

- **A kind is a registry key, never a path.** `Library`, the API and the builder look a kind up in the registry before they touch a
  folder, so `?kind=../x` cannot name one.

- **Least privilege by code.** An omitted `tools` field gives an agent every tool, so code always writes an explicit `tools` list,
  derived from the permission posture (Read/Grep/Glob = `read_files`, Edit/Write = `write_files`, Bash = `run_commands`,
  WebFetch/WebSearch = `network`). The model never chooses `permissionMode`; `bypassPermissions` only by an explicit choice, with a warning.
- **Secrets never enter a session.** Input and output are scanned in code; the MCP builder accepts environment variable *names* only.
- **Installing is explicit.** Nothing writes a person's Claude settings, `.mcp.json` or plugin config without a shown diff, a backup and a yes.
- **What a plugin can do is computed by code** (tools granted, hooks, MCP commands, scripts) and shown at approval and install.

## Format facts and how far to trust them

Read from the official docs by a research agent on 2026-11-19, **not tested against a live Claude Code**. Re-check before relying on them:

- **Subagent** (`.claude/agents/<name>.md`, `~/.claude/agents/`, or a plugin's `agents/`): required `name` and `description`; optional
  `tools` (omitted = all tools), `disallowedTools`, `model` (`sonnet`, `opus`, `haiku`, `fable`, a full id, or `inherit`), `permissionMode`,
  `maxTurns`, `skills`, `mcpServers`, `hooks`, `memory`, `color`, `effort`, `isolation`, others. Unknown keys are ignored. In a plugin, `hooks`,
  `mcpServers` and `permissionMode` are ignored.
- **Plugin:** `.claude-plugin/plugin.json` (only `name` is required; kebab-case; names starting `claude-` or `anthropic-` are refused;
  `homepage` must parse as a URL; paths start with `./`, stay inside the plugin, no symlinks), with `skills/`, `agents/`, `hooks/hooks.json`,
  `.mcp.json` beside it. A pinned `version` stops updates until the string changes. A marketplace is `.claude-plugin/marketplace.json`
  (`name`, `owner`, `plugins`); the entry name must equal the manifest name. `claude plugin validate <path> --strict` exists and checks
  the manifest.
- **Plugin MCP servers and `userConfig` (checked 2026-11-23 with the real validator and `--help`; the rest from the docs):** a root `.mcp.json` is loaded with no manifest key (an inline `mcpServers` in
  `plugin.json` is merged and wins on a name clash); `${CLAUDE_PLUGIN_ROOT}` is the plugin's installed folder and `${CLAUDE_PLUGIN_DATA}` a folder kept across updates; `userConfig` fields are
  `type` (string, number, boolean, directory, file), `title`, `description`, `required`, `default`, `sensitive` and more (unknown keys are an error), sensitive values go to the platform's credential
  store, and `${user_config.KEY}` is substituted in MCP config and exec-form hook `args` only (a value reaches an MCP server only if mapped in `env`).
- **Hooks:** 33 events are listed, five hook types (`command`, `http`, `mcp_tool`, `prompt`, `agent`); exit code 2 blocks on some events
  and not others. In a plugin they are in `hooks/hooks.json` under a top-level `"hooks"` key (same shape as `settings.json`; the exact entry fields were not read for 4b yet).
- **MCP:** `.mcp.json` has `mcpServers`; server names are letters, digits, hyphens and underscores. **The Python SDK is settled by a real install
  (2026-11-20):** the official `mcp` package is 2.3.0, `FastMCP` is gone in 2.x and the class is `MCPServer` (`from mcp.server.mcpserver import MCPServer`),
  tool annotations are `read_only_hint`, `destructive_hint`, `idempotent_hint`, `open_world_hint` and `title` (all default `None`), and a server started
  through `stdio_client` does not inherit the caller's environment (details in [mcp-builder.md](mcp-builder.md)). **Still unconfirmed:** the TypeScript SDK's names
  (`@modelcontextprotocol/sdk` or `@modelcontextprotocol/server`), the MCPB manifest version ("0.3" or "0.4") and the Streamable HTTP parameters.

## Risks

Format drift (keep formats as data with a "checked on" date; warn on unknown values and fail on structure only), generated code and hooks
running on the person's machine (sandbox first, allow-listed dependencies, catalogue hooks, explicit install), model quality that code
cannot prove (same honesty as today), and the one existing path being refactored (the strangler approach and the existing tests).
