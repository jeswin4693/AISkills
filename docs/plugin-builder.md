# Plugin Builder

The third kind the app keeps (Phase 2 of the [Component Factory](component-factory.md)). A Claude Code **plugin** bundles skills,
agents, MCP servers (Phase 4a) and hooks (Phase 4b) so they can be added in one step. You do not describe a plugin in words and no model is
involved: you **pick** skills, agents and MCP servers that are already in your library and hooks from a fixed catalogue, name the plugin, look at what it can do on your
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
  hooks/hooks.json                  only with hooks: one group per hook, in exec form
  hooks/<hook>.py                   the catalogue's script for each hook, unchanged
```

## Hooks in a plugin (Phase 4b)

A hook is a program that Claude Code runs on your machine, with your permissions and outside any sandbox, every time its event happens. So a plugin made here can carry **only hooks from a
fixed catalogue** ([hook-catalogue.md](hook-catalogue.md)): nobody types a hook command and no model writes one. Each entry is a short Python script from SkillForge (standard library only),
a fixed event, matcher and timeout, and typed **options** that are checked against a strict pattern and given to the script as separate arguments (exec form: `command` is `python`, `args` start
with `-I` and the script and then the options, no shell), so an option can never become code. `-I` (isolated mode) matters: Python otherwise puts the script's own folder first on its search path, so a `json.py`
planted beside a script would be imported instead of the standard module and could blind a guard (found by an independent review; **checked in real Claude Code with a hostile `json.py` in the hooks folder: both guards still blocked**).

```json
{"hooks": {"PreToolUse": [{"matcher": "Read|Write|Edit|NotebookEdit",
   "hooks": [{"type": "command", "command": "python", "args": ["-I", "${CLAUDE_PLUGIN_ROOT}/hooks/block-secret-files.py", "--also", "secrets.json"], "timeout": 10, "onFailure": "block"}]}]}}
```

- **The catalogue (3 hooks):** *block-secret-files* (before Read, Write, Edit or NotebookEdit: stops files that usually hold secrets, judged by the file's name the way Windows and macOS would open it; the person may add file names),
  *block-force-push* (before Bash or PowerShell: stops `git push` with `--force`, `-f`, `--force-with-lease`, `--mirror` or a `+branch`, also inside `bash -c`, a subshell, `powershell -Command` or `cmd /c`),
  *log-tool-calls* (after every tool: one line, the time and the tool's name, never its input, in the plugin's data folder, rotated at 1 MB).
- **A hook is always described plainly:** when it runs, what Claude Code hands it, whether it can stop what Claude is about to do, and what its script can do (proven by a test for each entry: none reaches
  the network, starts a program or builds code from text; only `log-tool-calls` writes, and a test shows it leaves only its one log). It is never called read-only. The preview, the README and the risk diff all say it runs on your machine.
- **A hook is a policy aid, not a security boundary.** It matches names and text. `block-secret-files` does not see `Grep`, `Glob` or shell commands (`cat .env`), and judges a file's name only. `block-force-push` reads the command as text with a small lexer
  (quotes, `; & | ( )`, `$(...)`, backticks, line continuations, Windows paths, nested shells): an alias, a script, a variable or an encoded command that pushes is not seen, and **the Monitor tool and background shells are not covered**.
- **A guard fails closed:** if a blocking script cannot understand what Claude Code sends it, or the command is too long to read, it blocks and says so (exit 2), and every blocking hook is written with `"onFailure": "block"`, so even when it cannot be started (`python` missing
  from the PATH) Claude Code stops the action instead of letting it through. This was checked in real Claude Code: without `onFailure`, a `Read` of `.env` went through with no Python and nothing told the person; with it, the read was blocked and the reason shown.
  Older Claude Code (before 2.1.295) ignores the key. Without Python, or after a format change, the guarded tools stay blocked until it is fixed; the message says why. A hook that only looks (the log) does not fail closed.
- **The plugin's check recognises a hook only when it is exactly a catalogue hook:** its event, matcher, timeout (the integer the catalogue writes: `10.0` and `true` are not it), command, arguments (including `-I`) and `onFailure` are the ones the catalogue writes, the options are valid, and the
  script beside it is the catalogue's own. "The catalogue's own" means the SHA-256 held as a **constant in the catalogue entry** (line endings ignored), never "whatever file is on disk": a script changed on disk after installation is neither shipped nor accepted.
  A hash is listed as an earlier revision only when that script was safe to keep describing: the two guards' first revision failed open and is not. **Any other file in `hooks/`** (a `json.py`, a `json.pyw`, a `sitecustomize.py`) makes the row a warning. In a plugin from outside, anything else
  (a shell command, another script, extra keys, another hook type, a changed script) is **warned about with the command shown in full** (long arguments are cut with a visible marker, a run of blanks is named, control characters are written out, keys and tokens are masked). A plugin that holds nothing it can describe
  has no content and is refused; one with a catalogue hook beside another command is kept with the warning. The row covers only `hooks/hooks.json`; hooks declared anywhere else are on the extras row (below).
- **The risk diff:** a new hook is riskier (with when it runs and whether it can block), a removed one safer. A hook is identified by its id (a catalogue hook) or by its **whole object** (any other), so a change anywhere in a command, its arguments or its timeout is a different hook, and the same hook on
  other events is reported. For a catalogue hook a different program or timeout is riskier, dropping `onFailure: block` is riskier, a script that is no longer the catalogue's is riskier, a newer catalogue revision or changed options are something to look at, and code a plugin ships outside its components is compared like any script
  (a catalogue-named file that no catalogue hook runs is just code).
- **The page:** a Hooks card lists the catalogue with a "runs on your machine" badge on each, and a text box for each option (bad values are marked at once from the server's pattern, and the server still decides; unticking a hook forgets what was typed for it).
  API: `GET /api/hooks`, and `{"kind": "hook", "name": "<id>", "options": {...}}` on the plugin routes.

## MCP servers in a plugin (Phase 4a)

A server from the MCP library ([mcp-builder.md](mcp-builder.md)) is shipped under `servers/<name>/` and started by a root `.mcp.json` in the one form the composer writes:

```json
{"mcpServers": {"word-tools": {"command": "python", "args": ["${CLAUDE_PLUGIN_ROOT}/servers/word-tools/server.py"],
                               "env": {"WEATHER_API_KEY": "${user_config.word_tools_weather_api_key}"}}}}
```

- **Every environment variable the server's code reads** becomes one `userConfig` option in `plugin.json` (`type: string`, `sensitive`, `required`, no default), named `<server>_<variable lowercased>`
  (a hyphen becomes an underscore: Claude Code refuses a key with a dash, which was checked with its validator). Claude Code asks for the value when the plugin is enabled and stores
  it in its own credentials store (**checked on Windows: a file, `.credentials.json`, in the Claude folder, private to you but not a vault**); `claude plugin install ... --config <key>=<value>` sets it without the dialog. **No value is ever written to a file of the plugin**, only the `${user_config.KEY}` reference.
  Two servers that read the same variable get two options, so they never share one value. A variable that is not a plain name, a server name that makes an invalid key (a leading digit), a variable that changes how a program is found or loaded
  (`PATH`, `PYTHON*`, `LD_*`, `DYLD_*`, `NODE_*`, `BASH_ENV`, `CLASSPATH` ...), or two that would share an option, refuse the plugin with a message that names the servers.
- **The composer never relies on a server inheriting Claude Code's environment**: the docs do not say it does, so every variable is passed explicitly. **Checked in real Claude Code** (below): the value reaches the server.
- **What a server can do is computed by code** from its `server.py` with the MCP reader (its tools, network, file writes, started programs, the variables it reads, including `g = os.environ.get` and `map(os.environ.get, ...)`, which an independent review showed the reader had missed)
  and said in plain sentences in the preview and the README. It is called "a program that starts on this machine, with your permissions and outside any sandbox", never "read only", and the
  sentence says the reading is by syntax and not proof. A server needs `python` and, when it ships a `requirements.txt`, `pip install -r servers/<name>/requirements.txt` (said only then); no Python environment is managed for you.
- **The plugin's check reads the servers too:** each server runs through the MCP kind's own checks (a failing server fails the plugin), and a row says whether `.mcp.json` starts
  **only servers shipped in this plugin, in the composed form**. In a plugin from outside, an entry that starts anything else (another command, a URL, a different path, extra keys, a value written in `env`, an option that belongs to another server or variable,
  an option that is not a required secret without a default, a variable the server never reads, a loader variable) and any key beside `mcpServers` is **warned about with the command shown** (an `env` value is never shown, only its name; a remote server shows its host only),
  and it is still named as an unexplained extra. An option that `.mcp.json` uses but `plugin.json` does not declare **fails**, as it does in Claude Code's own validator. A `userConfig` key Claude Code would refuse fails the manifest.
- **The risk diff** says a server that came into the plugin is **riskier** (a program that starts on your machine), one that left is safer, a changed server is compared with the MCP
  rules (a new network use, a new variable, new code beside it). `.mcp.json` is compared entry by entry: a new entry that is not the composed one for its server (even when its server arrives in the same version), a changed command, any other changed key (`cwd`),
  a variable newly given or taken from another option are **riskier** (the commands shown, values never). The manifest is compared too: an option that stops being sensitive or gains a default is riskier, and a command in an inline `hooks`, `mcpServers`, `lspServers`
  or monitors key is shown.

Add it to Claude Code with your own two commands (the app never writes Claude's settings):

```
claude plugin marketplace add "<path to the plugin folder>"
claude plugin install my-plugin@my-plugin-local
```

## What code decides

- **Components are read through the library**, which proves each file against its SHA-256 manifest. The plugin's own check then runs
  every nested skill, agent and MCP server through **that kind's own checks** (a row per component: `skill 'x' passes its own checks`), so a failing
  component fails the plugin and is refused when it is kept, and the same happens to a plugin zip from outside. (The first version only
  verified the hashes here and said the checks were re-run; an independent review caught that.)
- **What it can do on your machine is computed**, not chosen: the tools every skill (`allowed-tools`) and agent (`tools`) grants, and
  every script it ships with what the script can do by syntax (network, running commands, writing files; `.pyw` counts as Python). The preview and the README
  list them in plain sentences; tools beyond reading are marked. A tool is named by what comes before a bracket (`Bash(git *)` is Bash),
  a tool SkillForge cannot describe is **named, never called read-only**, and "it can only read and search files" is said only when every
  tool is Read, Grep or Glob and nothing else is shipped. Code in any folder of a skill counts as shipped code, not only `scripts/`.
- **What else runs is listed with its commands, not just counted.** The extras row names `bin/`, `commands/`, `monitors/`, `workflows/`, `.lsp.json`, `settings.json` and any case variant of them, and **shows the commands** that the manifest's `hooks`, `mcpServers`,
  `lspServers`, `channels`, `commands`, `workflows` and `experimental.monitors` keys would start, that a skill's or agent's front matter declares under `hooks` or `mcpServers`, and the lines in a skill that run a shell command when it loads (the `!` syntax; read from the
  Claude Code docs). A marketplace entry whose source is not this folder (`"./"`) is refused.
- **Names Windows or macOS would read as another file are refused.** On those systems `.MCP.JSON` IS `.mcp.json`, `server.py.` (a trailing dot or space) IS `server.py`, and `server.py:x` is a hidden stream of it, but every check looks files up by their exact
  spelling, so such a file was invisible. A file whose name differs from a special file (`.mcp.json`, `hooks/hooks.json`, `plugin.json`, `settings.json`, ...) only in capitals, a special folder spelled with other capitals (`Hooks/`, `Servers/`), and any name with a
  trailing dot or space or a colon **fail** (the last in every kind's shared path check). The docs do not say whether Claude Code matches names case-insensitively; the reason is that the file system does.
- **Hostile input cannot crash or exhaust the checks:** a JSON file nested 100,000 deep is a failed row (not an error 500), and the analyser no longer builds a string out of a few bytes of source (`"A" * 200 * 200 * 200` was 8,000,000 characters; five levels would have been 320 GB).
- **Names:** lowercase letters, digits and hyphens, at most 64, and **not** starting with `claude-` or `anthropic-` (Claude Code
  reserves those). The check runs on compose, on import and on a zip from outside.
- **The version is `0.1.<n>` and moves only when the content changes.** Claude Code pins a plugin's version and only updates it when
  the text changes, so keeping the same plugin twice makes no second version, and a changed skill makes the next one. **The parts are put in order (by kind, then by name) before the plugin is written**, so the same parts
  picked in another order make the same plugin (the first version let the click order change `.mcp.json`, the options and the README, and so the version).
- **Checks (the plugin's own):** a valid manifest, a usable name, a marketplace entry named like the manifest, no aliased names, at least one skill, agent, MCP server or recognised hook, the rows for `.mcp.json` and `hooks/hooks.json`, the extras and a list of what the scripts inside it
  can do (the shared script checks look only at a top-level `scripts/`, and a plugin keeps its scripts under `skills/<name>/scripts/`). The shared checks (hidden characters, attack-like wording, size, binaries) run on the whole plugin.
- **Install** copies the folder to a folder you choose. A plugin has no personal install folder.

## How it was checked

- **Offline tests** for the composer, the checks, the API, export and import, install, the hook scripts (run with real input), and the review findings (each written first and seen to fail on the code before the fix).
- **Claude Code's own validator** (`claude plugin validate <folder> --strict`, 2.1.325): plugins with skills, agents, MCP servers with an option, and all three hooks pass (exit 0; the only findings are a LICENSE and an icon, which Anthropic's public directory asks for and a local plugin does not need).
  The validator also settled formats before the code was written: it reads `.mcp.json`, refuses a `userConfig` key with a dash, a dot, a space or a leading digit, and fails a `${user_config.X}` that `plugin.json` does not declare.
- **Real Claude Code ran the hooks** (2026-11-23, `claude -p ... --plugin-dir`, one session each, no settings changed, a scratch folder with a dummy `.env`): `Read`, `NotebookEdit` (`notebook_path`), `Bash` and `PowerShell` tool names are the ones the matcher uses; the guards blocked a read of `.env`, a notebook edit and `git push --force`
  (also inside `bash -c`), an ordinary read passed, the log hook wrote its line, a missing `python` blocked the guarded tools (and let them through before `onFailure` was added), and a planted `json.py` did not blind a guard.
- **A real install, in an isolated config folder** (`CLAUDE_CONFIG_DIR` pointing at a scratch folder, so your Claude settings were not touched): `claude plugin marketplace add` and `claude plugin install ... --config ...` succeeded for a plugin with two MCP servers; `claude mcp list` showed both
  `plugin:...` servers **Connected** (with a Python that has the `mcp` package on the PATH); and a server that refuses to start unless its option reached its environment was Connected with the right value and `Failed to connect` with a wrong one, so **the `${user_config.KEY}` value really reaches the server**.
  The option's value was found in `.credentials.json` of that config folder.
- **A real browser** (Edge, the real API, a scripted fake model): 43 behaviours, including the plugin composer with a skill, a hook (a bad option stops the preview), and an MCP server.
- **Two independent reviews** (2026-11-23, fresh agents told to attack, one per slice, who could not run `claude`): 13 findings on 4a (2 Critical) and 12 on 4b (3 Critical): a hostile file named in other capitals, or with a trailing dot, or a module planted beside a hook script, was reported as fully described, and the force-push guard missed ordinary
  shapes. Every finding I could reproduce is fixed and tested; some are documented limits instead of fixes (the guards' blind spots, a harmless false positive on `git push -o -f`), and are under Limits. I re-ran the new tests on the code from before the fixes: about 110 of the 150 failed there (the five-level memory case was not run on the old code: it would have needed 320 GB),
  and the ones that passed were controls (things that must stay allowed) and checks of behaviour that was already right. Writing them also caught two tests of mine that did not reproduce the claim, which I fixed.

## Limits

- **An interactive Claude Code session was not tried**; every real run was non-interactive (`claude -p`). In particular the docs describe no approval prompt for a plugin's hooks or MCP servers, and none appeared; an interactive session may differ.
- **Windows only.** The real runs and the credentials-store location were seen on Windows. That `.MCP.JSON` and `server.py.` name the same file as `.mcp.json` and `server.py` was shown by the reviewers on this NTFS machine (Node and Python's `zipfile` opened or wrote the other file), not by me in Claude Code. macOS and Linux were not tried; that APFS ignores capitals by default is reasoning, not a test.
- **The command is plain `python`.** On a machine where Python is called `python3`, or lacks the package a server needs, the server does not start; a guard blocks instead of waving things through (Claude Code 2.1.295 or newer).
- **Hooks are a policy aid.** What the guards do not see is listed above (shell commands and `Grep`/`Glob` for secrets; aliases, scripts, encoded commands, the Monitor tool and background shells for pushes). The `Monitor` tool and `Grep`/`Glob` tool inputs were not tried against a hook.
- **Not verified in Claude Code:** whether a `userConfig` option with a `default` or `required: false` is used without asking (the checks refuse such options for servers, because it is unknown); whether a `.mcp.json` key beside `mcpServers` is read; the workflows, `commands/` and `monitors/` behaviour (they are listed, not run);
  the `!` syntax (read from the docs).
- The marketplace entry points at the plugin's own folder (`source: "./"`); a real install from it worked (above).
- The risk diff compares what code can see; a reworded instruction can still change what an agent does, and a plugin is never called safe.
- The version `0.1.<n>` is one above the highest version number ever stored, so a rollback can never make a number repeat; a manifest
  always names an author (the default is `me`), because `claude plugin validate --strict` wants one. No LICENSE or icon is written: that is your choice, not the app's.
- Only Python servers from the MCP library, no TypeScript, no remote (`url`) servers, and hook types other than `command` are not offered.
