# Plugin Builder

The third kind the app keeps (Phase 2 of the [Component Factory](component-factory.md)). A Claude Code **plugin** bundles skills,
agents and (since Phase 4a) MCP servers so they can be added in one step. You do not describe a plugin in words and no model is
involved: you **pick** skills, agents and MCP servers that are already in your library, name the plugin, look at what it can do on your
machine, and keep it. Everything is decided by code.

## Use it

Web: **Plugins** in the sidebar (`/composer`). Choose a name, a one-line description, optionally your name, tick the skills, agents and MCP servers,
press **Preview the plugin**, read it, then **Keep this plugin**. It appears in the Library under the **Plugins** tab, where you can
export it as a zip or install it from a folder. API: `POST /api/plugins/preview` and `POST /api/plugins` ([api.md](api.md)).
There is no `--kind` on the command line yet.

## What you get

```
my-plugin/
  .claude-plugin/plugin.json        name, version, description, author, and (only with servers that read variables) userConfig
  .claude-plugin/marketplace.json   a local marketplace, "my-plugin-local", that lists the plugin and points at this folder
  README.md                         what is inside, what it can do, the two commands that add it to Claude Code, and the server set-up
  skills/<skill>/...                every file of the skill's latest version, except spec.json (the requester's own words)
  agents/<agent>.md                 the agent's AGENT.md
  servers/<server>/...              every file of an MCP server's latest version (server.py, requirements.txt, README.md), except spec.json
  .mcp.json                         only with servers: one entry per server that starts it
```

## MCP servers in a plugin (Phase 4a)

A server from the MCP library ([mcp-builder.md](mcp-builder.md)) is shipped under `servers/<name>/` and started by a root `.mcp.json` in the one form the composer writes:

```json
{"mcpServers": {"word-tools": {"command": "python", "args": ["${CLAUDE_PLUGIN_ROOT}/servers/word-tools/server.py"],
                               "env": {"WEATHER_API_KEY": "${user_config.word_tools_weather_api_key}"}}}}
```

- **Every environment variable the server's code reads** becomes one `userConfig` option in `plugin.json` (`type: string`, `sensitive`, `required`), named `<server>_<variable lowercased>`
  (a hyphen becomes an underscore: Claude Code refuses a key with a dash, which was checked with its validator). Claude Code asks for the value when the plugin is enabled and keeps
  it as a secret; `claude plugin install ... --config <key>=<value>` sets it without the dialog. **No value is ever written to a file**, only the `${user_config.KEY}` reference.
  Two servers that read the same variable get two options, so they never share one value. A variable that is not a plain name, or two that would share an option, refuse the plugin.
- **The composer never relies on a server inheriting Claude Code's environment**: the docs do not say it does, so every variable is passed explicitly.
- **What a server can do is computed by code** from its `server.py` with the MCP reader (its tools, network, file writes, started programs, the variables it reads) and said in plain
  sentences in the preview and the README. It is called "a program that starts on this machine, with your permissions and outside any sandbox", never "read only", and the
  sentence says the reading is by syntax and not proof. A server needs `python` and the package in its `requirements.txt` (`pip install -r servers/<name>/requirements.txt`);
  no Python environment is managed for you.
- **The plugin's check reads the servers too:** each server runs through the MCP kind's own checks (a failing server fails the plugin), and a row says whether `.mcp.json` starts
  **only servers shipped in this plugin, in the composed form**. In a plugin from outside, an entry that starts anything else (another command, a URL, a different path, extra keys,
  a value written in `env`) is **warned about with the command shown** (an `env` value is never shown, only its name), and it is still named as an unexplained extra. An option
  that `.mcp.json` uses but `plugin.json` does not declare **fails**, as it does in Claude Code's own validator. A `userConfig` key Claude Code would refuse fails the manifest.
- **The risk diff** says a server that came into the plugin is **riskier** (a program that starts on your machine), one that left is safer, a changed server is compared with the MCP
  rules (a new network use, a new variable, new code beside it), and a changed start command, a new entry or a variable newly given to an entry in `.mcp.json` is **riskier** (both
  commands shown).

Add it to Claude Code with your own two commands (the app never writes Claude's settings):

```
claude plugin marketplace add "<path to the plugin folder>"
claude plugin install my-plugin@my-plugin-local
```

## What code decides

- **Components are read through the library**, which proves each file against its SHA-256 manifest. The plugin's own check then runs
  every nested skill and agent through **that kind's own checks** (a row per component: `skill 'x' passes its own checks`), so a failing
  component fails the plugin and is refused when it is kept, and the same happens to a plugin zip from outside. (The first version only
  verified the hashes here and said the checks were re-run; an independent review caught that.)
- **What it can do on your machine is computed**, not chosen: the tools every skill (`allowed-tools`) and agent (`tools`) grants, and
  every script it ships with what the script can do by syntax (network, running commands, writing files). The preview and the README
  list them in plain sentences; tools beyond reading are marked. A tool is named by what comes before a bracket (`Bash(git *)` is Bash),
  a tool SkillForge cannot describe is **named, never called read-only**, and "it can only read and search files" is said only when every
  tool is Read, Grep or Glob and nothing else is shipped. Code in any folder of a skill counts as shipped code, not only `scripts/`.
  Hooks, MCP servers and a bypassed approval declared in a component's front matter are listed and noted. A plugin zip from outside that
  carries `hooks/hooks.json`, `.mcp.json`, `bin/`, `settings.json` or manifest keys for hooks and MCP servers gets a warning, and a
  marketplace entry whose source is not this folder (`"./"`) is refused.
- **Names:** lowercase letters, digits and hyphens, at most 64, and **not** starting with `claude-` or `anthropic-` (Claude Code
  reserves those). The check runs on compose, on import and on a zip from outside.
- **The version is `0.1.<n>` and moves only when the content changes.** Claude Code pins a plugin's version and only updates it when
  the text changes, so keeping the same plugin twice makes no second version, and a changed skill makes the next one.
- **Checks (the plugin's own):** a valid manifest, a usable name, a marketplace entry named like the manifest, at least one skill or
  agent, and a list of what the scripts inside it can do (the shared script checks look only at a top-level `scripts/`, and a plugin
  keeps its scripts under `skills/<name>/scripts/`). The shared checks (hidden characters, attack-like wording, size, binaries) run
  on the whole plugin.
- **Install** copies the folder to a folder you choose. A plugin has no personal install folder.

## How it was checked

Offline tests for the composer, the checks, the API, export and import, and install. In addition, a plugin built by this code was given
to Claude Code's own validator on 2026-11-20 (`claude plugin validate <folder> --strict`, Claude Code 2.1.325): the manifest, the
skills folder and the agents folder pass, and the whole folder exits 0. The only findings are a LICENSE and an icon, which Anthropic's
public directory asks for and a local plugin does not need.

On 2026-11-23 (Phase 4a) the same validator was given a plugin composed from two real library servers, one of them reading `WEATHER_API_KEY`: the `.mcp.json`, the
`userConfig` and the `${user_config.*}` reference all pass and it exits 0 (same two notes). The validator was also used to settle the format before the code was written: it
reads `.mcp.json` (a `command` that is not text is an error), it refuses a `userConfig` key with a dash, a dot, a space or a leading digit (and accepts underscores and capitals),
and it fails a `${user_config.X}` that `plugin.json` does not declare. The checks in `validate/plugin.py` copy exactly those key rules.

## Limits

- **No real install was run.** The validator accepts the plugin; adding it with `claude plugin marketplace add` and `install` would
  change your Claude Code settings, so it was left to you. Tell me if either command complains.
- The marketplace entry points at the plugin's own folder (`source: "./"`), which the validator accepts; that Claude Code installs
  from it exactly this way was not tried.
- The risk diff between plugin versions compares each skill, agent and MCP server with the rules of its own kind (tools, scripts, wording, a server's code), says
  which components came or went, and reads `.mcp.json`; it reads hooks only as a key in a component's front matter (Phase 4b).
- The version `0.1.<n>` is one above the highest version number ever stored, so a rollback can never make a number repeat; a manifest
  always names an author (the default is `me`), because `claude plugin validate --strict` wants one.
- No hooks (Phase 4b). MCP servers and `userConfig` are in since Phase 4a, with these limits: **no real `claude plugin install` was run**, so what Claude Code does when it
  starts the server, asks for the options and passes them was not seen (the validator accepts the files and cross-checks `${user_config.*}` against `userConfig`); whether an
  unset optional option is an error is not in the docs, which is why every option is `required`; and the command is plain `python`, so on a machine where Python is called
  `python3` or does not have the package, the server will not start (the preview says it needs the package). Only Python servers from the MCP library, no TypeScript, no remote
  (`url`) servers. No LICENSE or icon is written: that is your choice, not the app's.
- The plugin page was not driven in a real browser (the new picker and the "Programs this plugin starts" section are covered by the typecheck and unit tests of its logic only);
  the 39 existing browser behaviours (skills) were not re-run for this slice.
