# Component Factory, Phase 4a: MCP servers inside plugins (short plan)

> Executed inline with TDD, one commit per task, no model calls. Spec: [docs/component-factory.md](../../component-factory.md) (Phase 4 and "Rules this adds"). Phase 4 is large, so it is cut in slices: **4a (this one) MCP servers in plugins**, 4b the hook catalogue, then whatever the risk diff still lacks.

**Goal:** a plugin can hold **MCP servers from the library** (the Python servers the MCP Builder makes), next to skills and agents. The composer writes `servers/<name>/` for each, a root `.mcp.json` that starts them, and a `userConfig` entry for every environment variable a server reads. What that makes the plugin do on the machine is computed by code, shown before it is kept, re-checked on import, and compared by the risk diff.

**Format facts (read from the docs by a research agent and checked 2026-11-23 with `claude plugin validate --strict`, CLI 2.1.325):**
- A root `.mcp.json` in the plugin is loaded with no manifest key: `{"mcpServers": {"<name>": {"command": "python", "args": ["${CLAUDE_PLUGIN_ROOT}/servers/<name>/server.py"], "env": {...}}}}`. The validator reads it (a non-string `command` is an error) but does not check the server name.
- `userConfig` in `plugin.json`: each key an identifier with underscores (a dashed key is refused: `Invalid key in record`), each value `{type, title, description, sensitive, required}`; `${user_config.KEY}` in the server's `env` is how a value reaches it. The validator fails a `${user_config.X}` that the manifest does not declare. `claude plugin install --config key=value` sets one without the dialog.
- NOT in the docs: that a stdio server inherits Claude Code's own environment, and what an unset optional `userConfig` value becomes. So the composer never relies on inheritance: every variable the server reads is mapped explicitly and is `required`.
- Docs say enabling a plugin starts its MCP servers with no per-server approval, and that they run outside the sandbox with the person's permissions.

**Decisions (the builder's calls):**
- Servers live under `servers/<name>/` (not `mcp/`, so no folder is ever called like the SDK package). Everything of the library entry is copied except `spec.json`, as for a skill.
- The start command is always `python` with the one shipped `server.py`. It needs the `mcp` package the server pins: the README and the capability notes say so (`pip install -r servers/<name>/requirements.txt`). Not done: a managed virtual environment.
- Key of a `userConfig` option: `<server with - as _>_<variable lowercased>`. Two that collide, or a variable that is not a plain identifier, refuse the plugin. All are `sensitive` and `required`.
- `.mcp.json` is **recognised** only when every entry is exactly that shape for a server shipped in this plugin (env values only `${user_config.X}` of a declared X). Anything else in a plugin from outside (another command, a URL, literal env values) is **warned about, with the command shown** and never trusted; an undeclared `${user_config.X}` **fails**, as in the real validator. Warn, not fail, matches how hooks were handled in v1.
- Server code is analysed with the MCP reader (`analyze_server`): its tools, what it can do by syntax, the variables it reads. The shipped `server.py` is not also listed as a plain script.

**Out of scope:** hooks (4b), a managed Python environment, TypeScript servers, running a server from the plugin on the host (the sandbox run is unchanged), `claude plugin install` for real (it changes the person's settings), the command line.

**Global constraints:** Python from `backend/` (`C:/dev/venvs/aiskills/Scripts/python.exe -m pytest`); tests offline; no new library; skill, agent and MCP behaviour unchanged; existing tests change only where a task says so. Commits end with `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`.

## Review Focus
- A server in a plugin is checked with the MCP kind's own checks, so a failing server fails the plugin (task 1).
- `.mcp.json` can never start anything that was not shipped and shown: unrecognised entries are named with their command (task 1).
- Nothing secret is ever written: env values are references, and a literal in a plugin from outside is reported by name only (tasks 1, 2).
- The capability notes say what a server can do by syntax and say it is not proof; they never call it read-only (task 2).
- A new server, or a changed start command, is **riskier** in the risk diff (task 3).

### Task 1: read servers inside a plugin
`validate/plugin.py`: `components()` also returns `("mcp", name, files)` for `servers/<name>/...`; `.mcp.json` row (`MCP_CONFIG_CHECK`); extras row skips a recognised root `.mcp.json`; the scripts row skips files of a recognised server; shared helpers `server_entry`, `user_config_key`. Tests: a server is checked by the MCP checks; each unrecognised shape warns with the command; an undeclared `${user_config.X}` fails; a literal env value is never repeated; the old extras tests still pass.

### Task 2: compose a plugin with servers
`library/plugin.py`: `COMPONENT_KINDS += "mcp"`, the files, `.mcp.json`, `userConfig`, `Capabilities.servers` and plain-sentence notes, the README setup lines. Tests: exact file list and JSON, the notes, refusal of a colliding or odd variable name, the version moves only when the server does, a plugin with a server passes `validate_files`.

### Task 3: the risk diff
`library/risk.py`: a server that came is riskier, one that went is safer, a changed server is compared with the MCP rules, a changed start command or a new option is riskier. Tests for each.

### Task 4: API, page, docs
`api/plugins.py` takes `"mcp"`; the composer page lists MCP servers and its text no longer says "Hooks and MCP servers are not part of this kind of plugin yet"; `lib/types.ts`, `lib/plugin.ts`. Docs: plugin-builder.md, component-factory.md, roadmap.md, README, CLAUDE.md status.

### Task 5: check it against the real tool
A plugin with a real library server is composed, written to a folder and given to `claude plugin validate --strict`; the whole backend suite, typecheck and UI unit tests run; the result is written into the docs as it was (what ran and what did not).
