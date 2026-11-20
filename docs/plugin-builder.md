# Plugin Builder

The third kind the app keeps (Phase 2 of the [Component Factory](component-factory.md)). A Claude Code **plugin** bundles skills and
agents so they can be added in one step. You do not describe a plugin in words and no model is involved: you **pick** skills and agents
that are already in your library, name the plugin, look at what it can do on your machine, and keep it. Everything is decided by code.

## Use it

Web: **Plugins** in the sidebar (`/composer`). Choose a name, a one-line description, optionally your name, tick the skills and agents,
press **Preview the plugin**, read it, then **Keep this plugin**. It appears in the Library under the **Plugins** tab, where you can
export it as a zip or install it from a folder. API: `POST /api/plugins/preview` and `POST /api/plugins` ([api.md](api.md)).
There is no `--kind` on the command line yet.

## What you get

```
my-plugin/
  .claude-plugin/plugin.json        name, version, description, author
  .claude-plugin/marketplace.json   a local marketplace, "my-plugin-local", that lists the plugin and points at this folder
  README.md                         what is inside, what it can do, and the two commands that add it to Claude Code
  skills/<skill>/...                every file of the skill's latest version, except spec.json (the requester's own words)
  agents/<agent>.md                 the agent's AGENT.md
```

Add it to Claude Code with your own two commands (the app never writes Claude's settings):

```
claude plugin marketplace add "<path to the plugin folder>"
claude plugin install my-plugin@my-plugin-local
```

## What code decides

- **Components are read through the library**, which proves each file against its SHA-256 manifest and re-runs the static checks first.
  A damaged or failing skill or agent is refused and can never end up inside a plugin.
- **What it can do on your machine is computed**, not chosen: the tools every skill (`allowed-tools`) and agent (`tools`) grants, and
  every script it ships with what the script can do by syntax (network, running commands, writing files). The preview and the README
  list them in plain sentences; tools beyond reading are marked. Hooks and MCP servers are always empty in this version.
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

## Limits

- **No real install was run.** The validator accepts the plugin; adding it with `claude plugin marketplace add` and `install` would
  change your Claude Code settings, so it was left to you. Tell me if either command complains.
- The marketplace entry points at the plugin's own folder (`source: "./"`), which the validator accepts; that Claude Code installs
  from it exactly this way was not tried.
- The risk diff between plugin versions does not see scripts nested under `skills/` (Phase 4 widens it to every kind).
- No hooks, MCP servers or `userConfig` (Phase 4). No LICENSE or icon is written: that is your choice, not the app's.
- The plugin page was not driven in a real browser; the 39 existing browser behaviours (skills) still pass.
