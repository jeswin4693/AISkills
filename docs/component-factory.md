# Component Factory: skills, agents, plugins and MCP servers from one app

**Status: planned and approved by the project owner (2026-11-19). Built so far: the shared model service
([ai-engine.md](ai-engine.md)), Phase 0 (the foundation), Phase 1 (the Agent Builder) and Phase 2 (the Plugin Builder), all 2026-11-20 (plans: [phase 0](superpowers/plans/2026-11-20-component-factory-phase-0.md), [phase 1](superpowers/plans/2026-11-20-agent-builder-phase-1.md), [phase 2](superpowers/plans/2026-11-20-plugin-builder-phase-2.md); what each did and did not do is under "Phase 0/1/2: what was built" below, in [agent-builder.md](agent-builder.md) and in [plugin-builder.md](plugin-builder.md)). Nothing else here is built.** Next slice: Phase 3, the MCP Builder.

## What

Grow SkillForge from a skill builder into four builders that share one app, one database, one library and one model service:

| Builder | Output | Model calls (typical) |
|---|---|---|
| Skill (exists) | `SKILL.md` and supporting files | 3 to 5 |
| Agent | a Claude Code subagent file (`<name>.md`: front matter + system prompt) and its definition, spec, tests | 3 to 5 |
| Plugin | an installable plugin: manifest, skills, agents, later hooks and MCP, plus a local marketplace entry | 0 (assembled from the library) |
| MCP server | a Python (later TypeScript) server project, tested over the MCP protocol in the sandbox | 4 to 7 |

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
| 3 | MCP Builder: Python first, then TypeScript | XL, then M |
| 4 | Plugin v2: MCP, a hook catalogue, `userConfig`; risk diff for every kind | L |

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
- **Hooks:** 33 events are listed, five hook types (`command`, `http`, `mcp_tool`, `prompt`, `agent`); exit code 2 blocks on some events
  and not others.
- **MCP:** `.mcp.json` has `mcpServers`; server names are letters, digits, hyphens and underscores. **The sources disagree about the SDKs:**
  the connector-building skill names `@modelcontextprotocol/sdk` and FastMCP 3.x, while the current MCP tutorial pages, as read by the
  research agent, show `MCPServer` (Python) and `@modelcontextprotocol/server` (TypeScript, labelled beta). Settle this with a real install
  before the MCP builder is written. MCP tool annotation names and defaults, the MCPB manifest version ("0.3" or "0.4") and the Streamable
  HTTP parameters were not confirmed.

## Risks

Format drift (keep formats as data with a "checked on" date; warn on unknown values and fail on structure only), generated code and hooks
running on the person's machine (sandbox first, allow-listed dependencies, catalogue hooks, explicit install), model quality that code
cannot prove (same honesty as today), and the one existing path being refactored (the strangler approach and the existing tests).
