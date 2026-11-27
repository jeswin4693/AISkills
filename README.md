# AISkills (SkillForge AI)

An open-source platform that **understands repositories**, **suggests ideas** grounded in them, and **builds
reusable AI skills** from plain-English requirements.

Status: **Understand, Suggest, Build (with a test harness, `eval`), Safety (static checks and a sandbox), Scripts, the skill Library (versions, risk diff, rescan), the read-only Task Plan, a local API with a database, the web UI (Builder, Library, Plugins, Repository with a drawn architecture map, and Settings), one model service with backup models, the hosted version, and the foundation for more kinds of builder (the kind registry), the Agent Builder, the Plugin Builder and the MCP Builder (Python and Node) are built and tested. The main paths were run live with Gemini (Groq as a backup, the hosted image in Docker).** The behavioural canary scan is built too (slice AG, below), and so is **Sign in with Google with one library per person** for the hosted version (slice AH, below), with **each person's own model key and a daily allowance on the server's model** (slice AI, below) and **limits per person with an owner's People page** (slice AJ, below), and then **a completion batch** (slice AK, below): deleting and erasing, the behaviour scan on a web page, and four smaller things. Not built yet: Node servers inside plugins, a function-level graph, and any real host (the hosted version was run only in Docker on this machine).
See [docs/roadmap.md](docs/roadmap.md). To try every feature yourself, step by step, with sample files and a practice library that leaves
your real one alone: [docs/try-it-yourself.md](docs/try-it-yourself.md).

```
 Repo --> UNDERSTAND --graph facts--> SUGGEST --ideas with evidence--> BUILD --> skill packages
          (no AI)                     (AI + graph)                      (AI + templates)
```

## Where it is going: more than skills (the Component Factory)

The builder is being grown into four builders that share one app, one database, one library and one model service:
a **skill** builder (built), then an **agent** builder (a Claude Code subagent file), a **plugin** builder (assembled from
what is in your library) and an **MCP-server** builder. The approved plan, the phases and the rules are in
[docs/component-factory.md](docs/component-factory.md).

**Phase 0, the foundation, is built.** Nothing changes for skills; the app is ready for a second kind:

- **A kind registry** (`skillforge/kinds/`): what the app can build, the checklist a requirement of that kind must fill, and
  where it installs. Today it holds four kinds: the skill, the agent, the plugin and the MCP server.
- **One library per kind.** The skill library stays exactly where it was; every other kind gets its own folder, so names
  never collide. A kind is only ever a key looked up in the registry, never part of a file path.
- **The static checks take a kind.** Every check runs for every kind; only the check of the definition file (for a skill,
  `SKILL.md`) belongs to the kind.
- **Builder sessions remember their kind** (database migration 0003), and the builder runs that kind's own reading and
  building steps.
- **The API:** `GET /api/kinds`, `?kind=` on every library route, rescan and validate, and a `kind` when starting a build.
  An unknown kind is a plain 400 that names the kinds there are.
- **The web Builder** shows a kind picker as soon as there is more than one kind that is built by describing it, and a kind
  badge on past builds. Skills looked exactly the same when there was only one kind.
- **Two small skill improvements:** a skill's permissions are written into `SKILL.md` as `allowed-tools` by code, and the
  checks warn about front-matter keys that Claude Code does not know (both described below).

**Phase 1, the Agent Builder, is built on top of it** ([docs/agent-builder.md](docs/agent-builder.md)): pick **Agent** in the Builder
(or `"kind": "agent"` in the API) and describe a Claude Code subagent. You get an `AGENT.md` whose `tools` line is written by code
(never empty, never every tool), with your rules and acceptance criteria carried in word for word, checked, kept in its own library,
exported, and installed as one file in `~/.claude/agents`. The Library has an Agents tab. Not yet: a run against a live model,
`eval` for agents, an agent flow in the real browser, `--kind` on the command line.

**Phase 2, the Plugin Builder, is built too** ([docs/plugin-builder.md](docs/plugin-builder.md)): a plugin bundles skills and agents so Claude Code can add them
in one step. It is **composed, not described**: no conversation and no model. On the **Plugins** page you pick skills and agents from your library, and the app writes the plugin
folder (manifest, a local marketplace file, `skills/`, `agents/`, a README) and works out, by code, what it can do on your machine before you keep it. A damaged or failing
component is refused, reserved names are refused, and the version moves only when the content does. A plugin built this way passes Claude Code's own
`claude plugin validate --strict`. **Phase 4a (2026-11-23) lets a plugin carry MCP servers** from your MCP library: the composer writes `servers/<name>/`, a `.mcp.json` that starts each, and one secret
`userConfig` option for every environment variable a server reads (Claude Code asks for it when the plugin is enabled; no value is ever written to a file). What each server can do is read from its code and said plainly,
a plugin from outside that starts anything it does not ship is warned about with the command shown, and the risk diff calls a new server or a changed start command riskier. Claude Code's own validator accepts
such a plugin. **Phase 4b (2026-11-23) lets a plugin carry hooks, from a fixed catalogue only** ([docs/hook-catalogue.md](docs/hook-catalogue.md)): block secret files, block forced git pushes, log which tools were used. Nobody types a
hook and no model writes one: each is a short script from SkillForge, shipped unchanged, with only typed options that cannot become code. It is described plainly (it runs on your machine, with your permissions), recognised only when it is exactly the catalogue's,
and called riskier by the risk diff. **Real Claude Code ran them:** the two blocking hooks blocked a read of `.env`, a notebook edit and a force-push (also inside `bash -c`), an ordinary read passed, and the log hook wrote its line. That run also found that a guard
which cannot start (no Python on the PATH) **let the action through without telling anyone**, so every guard now fails closed (`onFailure: block`). A real install (in an isolated config folder, so your settings were untouched) started the plugin's MCP servers and passed them their option.
**Two independent reviews** then found real holes (a file named `.MCP.JSON` or `server.py.` that Windows treats as another file, a module planted beside a hook script, force-push shapes the guard missed): they are fixed and tested, and the guards' remaining blind spots are listed in
[docs/hook-catalogue.md](docs/hook-catalogue.md). A hook is a policy aid, not a security boundary. Not yet: an interactive-session check, macOS and Linux, and hook types other than commands.

**Phase 3, the MCP Builder (Python), is built too** ([docs/mcp-builder.md](docs/mcp-builder.md)): pick **MCP server** in the Builder and describe a few tools in plain words. The model drafts the tools; **code**
writes `server.py` around them (the imports, the signatures, the tool annotations, `mcp.run()`), pins the official `mcp` SDK, writes a README with the exact `claude mcp add` command, and checks it by reading it:
anything that starts programs, builds code from text, loads native code or carries a key **fails**, and a key is only ever the *name* of an environment variable. Then the server is **started in the sandbox and
called over the real MCP protocol**, and the build says "ok" only if it really ran and every test case matched; a server that never ran, or whose tool needs the network, is an honest DRAFT. Two real builds with the
configured model found and fixed two defects (missing imports, and a tool that returned simulated data). **An independent review then found real gaps** (an encoding trick that hid code from the checks,
code beside `server.py` that Python would import, alternate spellings of running a command, a forged sandbox verdict, and a tool name that could be written into the file as code); they are fixed and tested, and a server the
builder writes may now import only an allow-list of safe standard-library modules. The checks are still a reading by syntax and **cannot prove a file safe**: read a server you did not build before you add it
([docs/mcp-builder.md](docs/mcp-builder.md)). Not yet: HTTP and the MCP flow in a real browser.

**The MCP builder also writes TypeScript servers** (Phase 3b, its own kind `mcp-node`, [docs/mcp-builder-node.md](docs/mcp-builder-node.md)): the same conversation, but code writes a `server.ts` for the official
TypeScript SDK v2 (the model drafts function bodies and the imports *as data*, from an allow-list), a `package.json` with exact versions and no scripts, and the pinned lockfile. It is read with tree-sitter by a second
reader (programs, code built from text, network, file writes, a key in pieces, install scripts, other code beside it), run **in the sandbox under Node's permission model** (`node --permission`, which a real run showed
refuses file writes through `fs`, starting programs and reads outside the folder, with known gaps such as `node:sqlite`) and called over the real MCP protocol. The README it writes has a `claude mcp add` command that starts the server the same way;
real Claude Code accepted that command and called a tool of the generated server. **Two independent reviews then attacked it** and found a Critical hole (destructuring reached `Function` and a build said "ok") and many reader gaps; they are fixed test-first, and the generated file now also removes `constructor` from every function as a second line of defence. It cannot be put in a plugin yet (a plugin cannot run `npm ci`).

**Skills can now cite code and be rechecked against it** (slice V, [docs/evidence.md](docs/evidence.md)): a skill carries an `evidence.json` listing the files and functions it names, with the facts the graph had
(structure, resolved callers and callees, a file's symbols and importers, the commit and whether the tree had uncommitted changes). `library recheck NAME --repo PATH` later says, with names, what is **missing**, **moved** (one candidate, never applied for you),
**changed** (a new caller, a changed structure) or only **edited**; `library refresh` records today's facts after you have read the skill against the changed code. It is deterministic (no model, nothing is run) and checks that cited facts still hold,
**not that the skill's advice is right**. A skill built from a suggestion with `build --from-suggestions ... --repo PATH` carries the idea's cited places from the start. A real build with the configured model did that end to end, and a recheck on a changed clone of this repository
named the renamed function, the new caller and the changed structure (and exposed a flaw that is now fixed: a commit id alone hid uncommitted changes). **One independent review** found four wrong "holds" (a removed decorator, a class whose bases or methods changed, a file whose function bodies were all rewritten, a caller swapped inside a long list), escape sequences from a hostile file reaching the terminal and a privacy claim that was false for `install`; they are fixed test-first and the report now says what a place records and what it does not check. Evidence names a private repository's code, so `export --without-evidence` leaves it out, `install` keeps it in the library and a plugin never ships it. The web Repository page records it too (below), and a skill's library page lists the code it cites and can recheck it. Not yet: citing more places or refreshing from a page.

**What is next, in this order:**

1. **Phase 3b, the MCP builder in TypeScript, is built.** What is left of it: Node servers inside plugins and the Streamable HTTP transport.
2. **Phase 4 is built** (4a: MCP servers in plugins; 4b: hooks from a catalogue). A larger catalogue, `SessionStart` context hooks and a managed Python environment are possible later, none planned.
3. **All three differentiators are built:** the risk diff and rescan, code-level evidence with drift detection (slice V), and **the behavioural canary scan** (slice AG, below)
   ([docs/differentiators.md](docs/differentiators.md)).
4. **The Repository page, the Settings page, reading a repository from a GitHub link and the drawn architecture map are built** (slices W, X, Y and Z, below). Left of the web pages: a function-level graph (the map shows folders and the imports between them).

The live list, with what was verified, is [docs/roadmap.md](docs/roadmap.md).

## Layout

```
AISkills/
├── backend/
│   ├── skillforge/graph/     # repository graph: parse, resolve, query (no AI)
│   ├── skillforge/suggest/   # review and ideas over graph facts (AI), every suggestion cites real graph nodes
│   ├── skillforge/build/     # requirement checklist, skill design, rendering, quality checks, scripts
│   ├── skillforge/evaluate/  # the test harness: a skill's test cases run against a model, graded by code
│   ├── skillforge/validate/  # static checks on any skill folder (run nothing)
│   ├── skillforge/sandbox/   # the Linux Docker sandbox that generated scripts run in (fails closed)
│   ├── skillforge/kinds/     # the kind registry: what the app builds (skill, agent, plugin and MCP server) and each one's checklist
│   ├── skillforge/hookcatalog/ # the only hooks a plugin may carry: three fixed scripts, typed options, pinned hashes
│   ├── skillforge/library/   # versions per kind: import (checked), diff + risk diff, rescan, rollback, export, install, cite/recheck/refresh (no AI)
│   ├── skillforge/evidence/  # the places a skill cites + the graph's facts about them, and the recheck (docs/evidence.md; no AI)
│   ├── skillforge/ai/        # the one model service: model by task, retries, usage, redaction, backup models
│   ├── skillforge/providers/ # the model adapters (Gemini, OpenAI-compatible, Anthropic) and a mock for tests
│   ├── skillforge/api/       # local HTTP API (FastAPI), localhost only; the hosted mode adds a sign-in
│   ├── skillforge/builder/   # the builder as a database-backed conversation with background jobs
│   ├── skillforge/db/        # SQLAlchemy models + Alembic migrations (SQLite first)
│   ├── skillforge/conductor/ # the read-only Task Plan: scope, size, process, rules, token plan
│   ├── skillforge/cli.py     # `python -m skillforge ...`
│   ├── tests/                # offline tests, no key or network needed
│   └── scripts/              # Step 0 smoke test for the LLM provider
├── frontend/                 # web UI: Next.js + React + TypeScript + Tailwind (talks to the API)
├── docs/                     # roadmap, component factory plan, design docs per slice, decisions, environment notes
├── Dockerfile, deploy/       # the hosted version: one image with the pages and the API
├── .env.example
└── README.md
```

## Understand a repository

Works on repositories in many languages: full support for Python and TypeScript / JavaScript, standard support
for Java, Go, Rust, C, C++, C#, Ruby, PHP and Kotlin, and basic support (definitions and duplicate detection)
for 30+ more. See [docs/languages.md](docs/languages.md) or run `python -m skillforge languages`. Needs no AI
and no key.

```powershell
cd backend
python -m skillforge graph stats      C:\path\to\repo
python -m skillforge graph impact     C:\path\to\repo src/service.ts
python -m skillforge graph callers    C:\path\to\repo parse --depth 2
python -m skillforge graph duplicates C:\path\to\repo
python -m skillforge graph hotspots   C:\path\to\repo
```

Every answer says how sure it is (proven link, or a name-only guess), and the limits are stated in
[docs/graph.md](docs/graph.md). Nothing is written into the repository you analyse.

## Get AI suggestions for a repository

The model only sees facts computed from the graph, and a suggestion that cites nothing real is dropped
([docs/suggest.md](docs/suggest.md)). Needs a provider key in `.env`.

```powershell
cd backend
python -m skillforge suggest C:\path\to\repo --facts-only   # no AI, no key: just the facts
python -m skillforge suggest C:\path\to\repo                # refactor / test / risk findings + skill ideas
python -m skillforge guide C:\path\to\repo                  # how the project works, from its README and docs (parts, layers, routes; every quote checked)
```

## Build a skill

Describe what you want. It asks only what is missing, waits for your approval, then writes a skill folder and
a report that says what was checked and what was not ([docs/build.md](docs/build.md)). Needs a provider key.

```powershell
cd backend
python -m skillforge build "A skill that finds duplicate functions in a TypeScript repository and suggests safe refactors."
python -m skillforge build --from-suggestions report.json --pick 1   # start from an idea found by `suggest`
python -m skillforge build "A skill that counts TODO and FIXME comments in a folder." --scripts
```

The skill it writes is built to work well and cost little to use: its description says *when* to use it (built by code from
trigger phrases), your rules and acceptance criteria are carried into `SKILL.md` word for word with a done-when list and a
worked example, what is only for people lives in the README, and the result says what it costs in tokens (an estimate).
Checks warn about vague wording, an input no step uses and similar weaknesses ([docs/build.md](docs/build.md)).

If the skill needs files, commands or the network, the permissions it asks for are written into `SKILL.md` as
`allowed-tools`, by code and in a fixed order (`read_files` is `Read Grep Glob`, `write_files` is `Edit Write`,
`run_commands` is `Bash`, `network` is `WebFetch WebSearch`). That is a **grant**: Claude Code lets the skill use those
tools without asking while it is active, and `Bash` is not narrowed to the skill's own scripts. A skill that is only text
gets no `allowed-tools` line at all. The format was not tried against a live Claude Code.

Does the skill actually help? `build --eval` (or `python -m skillforge eval <skill-folder>`) runs the skill's own test
cases against a model **with the skill and without it**, and code grades the replies by simple checks (a model never
judges). It says whether the skill helped, adds nothing for the tokens it costs, or made things worse. It works for
skills that are only text; a skill that reads files or runs commands cannot be tested this way
([docs/evaluate.md](docs/evaluate.md)).

With `--scripts` the skill can ship helper scripts. Every script case runs in the Linux sandbox, and a skill whose
scripts never ran is marked DRAFT ([docs/scripts.md](docs/scripts.md)).

## Build an agent

The same conversation builds a Claude Code **subagent**: in the web Builder choose **Agent**, describe the job you want to hand
it, answer only what is missing (the questions are worded for an agent: what it is given, what it reports back, what it may
touch), approve the requirement, and save it. The agent file is `AGENT.md`; installing it writes one file,
`~/.claude/agents/<name>.md`, and never replaces one without asking ([docs/agent-builder.md](docs/agent-builder.md)).

What code decides, not the model: the `tools` line (at least `Read, Grep, Glob`, more only if the design asked for it, and
anything beyond reading is flagged for you to read), the front matter, and that your own rules and acceptance criteria appear in
the file word for word. What is not done: its test cases are not run against a model, and no live-model run of this builder has
been made yet.

## Build an MCP server

Pick **MCP server** in the web Builder (or `"kind": "mcp"` in the API) and describe a few tools. You get a folder with `server.py`, `requirements.txt`, `README.md` (with the command that adds it to Claude Code),
`tests/cases.json` and a report. The test cases are run **inside the sandbox**, so build its image once: `python -m skillforge sandbox-build-mcp` (needs Docker and a network, once). Without it the server is built but marked
DRAFT, never "ok" ([docs/mcp-builder.md](docs/mcp-builder.md)). The app never adds the server to Claude Code for you: that command changes your settings, so you run it.

## Compose a plugin

Open **Plugins** in the web pages, give the plugin a name and a one-line purpose, tick the skills, agents, MCP servers and hooks to include and press **Preview the plugin**. You see its files,
**what it can do on your machine** (every tool its parts grant, every script it ships, every program an MCP server starts and every hook that runs, worked out by code) and every check. **Keep this plugin** stores it in the
library's Plugins tab, where you can export it as a zip or install it from a folder. Its README has the two commands that add it to Claude Code:
`claude plugin marketplace add "<folder>"` and `claude plugin install <name>@<name>-local` (and, for MCP servers, the `pip install -r` lines and the `--config` option names). The app never writes Claude's settings: adding it is your command
([docs/plugin-builder.md](docs/plugin-builder.md)).

## Check any skill folder

Static safety and structure checks that run nothing, for skills made here or downloaded
([docs/validate.md](docs/validate.md)). Scripts are never run unless a Linux sandbox is available, and never on
your machine directly. It also warns about front-matter keys that Claude Code does not know: Claude Code ignores them
without a word, so a typo such as `allowed_tools` would quietly do nothing. The list of known keys is data, with the day it
was read (2026-11-20).

```powershell
cd backend
python -m skillforge validate C:\path\to\skill-folder   # exit code 1 if a check failed
python -m skillforge sandbox-status                     # is a safe place to run scripts available?
```

## Plan a task before doing it

A read-only plan for any software task: what your request contains (each item with your own quote, verified) and what it
does **not** say (questions, assumptions), how big it is (measured from the code graph), which process phases it needs and
when to stop and ask, which rules in `CLAUDE.md` apply, and a token plan (which exact functions to read instead of whole
files). It changes nothing and runs nothing ([docs/task-conductor.md](docs/task-conductor.md)).

```powershell
cd backend
python -m skillforge plan "Add a --json option to the library list command. Do not change other commands." --repo C:\path\to\repo
python -m skillforge plan "..." --repo C:\path\to\repo --no-ai --type bugfix    # sends nothing to any model
```

## Keep skills as versions

Import a skill folder or `.zip` (made here or downloaded): it is checked first and **refused if a check fails**.
Accepted skills are kept as v1, v2, ... that you can diff, roll back, export as a `.zip` or install where an agent
reads them ([docs/library.md](docs/library.md)). Needs no AI and no key; importing never runs a script. Each kind of
thing the app builds has its own library folder (the skill library is where it always was).

A skill that was clean when you imported it can be edited into a bad one later, so every new version is compared with
the one before it and **what got riskier is listed** (a script that now uses the network, a new permission or web
address, wording that matches an attack pattern, a changed description). `library rescan` runs today's checks again on
every version already stored. Both are done by code, never by a model, and say what they cannot see.

```powershell
cd backend
python -m skillforge library import generated-skills\my-skill    # or a .zip
python -m skillforge library list
python -m skillforge library diff my-skill                       # what changed since the version before, and what got riskier
python -m skillforge library rescan                              # today's checks on every stored version: which are now worse?
python -m skillforge library rollback my-skill --to 1            # a new version with the content of v1
python -m skillforge library cite my-skill --repo C:\code\repo --from-text   # record the code the skill names, with the graph's facts (docs/evidence.md)
python -m skillforge library recheck my-skill --repo C:\code\repo            # what changed in that code? (exit 1 if anything is gone, moved or changed)
python -m skillforge library refresh my-skill --repo C:\code\repo            # after you read the skill against the changes: record today's facts
python -m skillforge library export my-skill --out my-skill.zip              # add --without-evidence to leave out the names of a private repository's code
python -m skillforge library install my-skill --project          # or --personal, or --to <skills folder>
```

## The Repository page (slice W)

Until now the main pipeline worked only from the command line. On the **Repository** page you type the full path of a folder on your computer and the page
reads it into the code graph (no model, nothing is run), shows what the graph says, and can ask a model for **ideas that must cite code that really exists**.
A skill or automation idea has a **Build this skill** button (its wording is the model's, and you can change it first): it starts a Builder session that remembers the
repository, and when the build ends the skill carries `evidence.json` for the places the idea cited. Saved, its library page lists that code and can **recheck** it.
Everything that reads a folder is off in the hosted version, and the page is shown the folder's name, never its path. Details, the API and what a real run with the
configured model showed (including a skill idea the builder refused as "an agent", which is why the wording is editable): [docs/repository-page.md](docs/repository-page.md).

## The Settings page (slice X)

Until now the model and its key were set by editing the `.env` file by hand, and the server read it once. On the **Settings** page you choose the provider and the model, paste a key, add backup models and test them with **Test my models** (one tiny question to each model, so it uses a little quota). It is saved into `.env` on this computer and **used at once, with no restart**.
A key is **never shown again and never sent back** by the API (the page learns only "Saved" or "Not set"). Only a fixed list of settings can be changed, a value may hold only safe characters, a refusal says which setting and why without repeating the value, and a setting that comes from your computer's environment is shown read-only. Off in the hosted version. Details and limits (a key in `.env` is plain text on disk): [docs/settings.md](docs/settings.md).

## Reading a repository from a GitHub link (slice Y)

The box on the **Repository** page now takes the link of a **public GitHub repository** as well as a folder (for example `https://github.com/owner/repo`). The repository is **downloaded as a zip** (never cloned, so nothing in it can run) and unpacked by our own code: only source files, only safe names, with limits on size and count. Then it works everywhere a folder does: the graph, ideas, a build with evidence, and the recheck. The page says where it came from, what was kept and left out, and that git history is not downloaded. Public repositories only; off in the hosted version; the command line takes the link too (slice AA, next section). **One independent review (2026-11-25, together with the architecture map) found no Critical problem and four Important ones, all fixed test-first: a different branch's code shown on disks that ignore case, evidence recorded from a newer copy than the idea was made from, deep files skipped because of path length, and a 500 on long names.** Details, limits and what was checked, including a real run: [docs/github-link.md](docs/github-link.md).

## GitHub links on the command line (slice AA)

Every command that takes a repository (`graph <command> <repo>`, `suggest`, `plan --repo`, `build --repo`, and `library cite|recheck|refresh --repo`) now takes the link of a **public GitHub repository** as well as a folder, for example
`python -m skillforge graph stats https://github.com/owner/repo`. It is the page's own downloader (the same limits and safety rules), and the note about the download (where it came from, what was left out, that git history is missing) goes to stderr, so
`--json` is still pure JSON. `cite`, `recheck` and `refresh` always download a fresh copy (they answer what the code is now); the others reuse a copy up to 15 minutes old; `plan` says a link has no `CLAUDE.md` or `AGENTS.md` (only source files are downloaded).
A refused link or an unreachable GitHub is one `error:` line with exit code 2, and a folder behaves exactly as before. 14 deliberate breaks were all caught and the real command ran against this repository's public link. **No independent review** (an adapter over
code that was just reviewed). Details and limits: [docs/cli-github-links.md](docs/cli-github-links.md).

## The architecture map (slice Z)

Under the numbers, the **Repository** page now draws the repository: its **folders as boxes** and the **proven imports between them as arrows** (thicker means more files import across; dashed means an import that points back against the main direction and closes a loop). Click a box to light its arrows and see its biggest files and functions; **The arrows as a list** says the same in words. It is worked out by code from the graph (no model, nothing is run) and drawn as plain SVG (no new library), and it works for a folder and for a GitHub link. A guess is never drawn, imports written by test files are left out (and counted), a repository with fewer than six top folders is shown one level deeper, and a language whose imports are not read is said to be "not measured", never shown as depending on nothing. The first real runs on this project found three things no mock showed (a three-box map with no arrows, one giant cycle that made a hairball, and arrows lying on top of each other); all are fixed, and the page says how many weaker arrows it does not draw. **The same independent review covered this slice: no Critical problem and one Important one, fixed (C#, whose imports are never turned into links between files, had been drawn as folders that depend on nothing; it is now said to be "not measured").** An import written by a test file **or by test scaffolding** (an `e2e`, `fixtures` or `mocks` folder) is not drawn either: a real run showed the browser test's fake server drawing a false arrow to the backend, fixed afterwards. Details, rules, limits and what was checked: [docs/architecture-map.md](docs/architecture-map.md).

## How it works: a guide for new developers (slice AB)

Under the map, the **Repository** page has a **Show how it works** button. A model reads the project's **README and docs** and proposes its **parts**, the **layers** they sit in (what people use, the doors in, the workers, shared services, the outside world)
and the **routes** an action takes through them ("build a skill": the page, the API, the builder, the AI engine, the sandbox, the library). Then **code decides what is kept**: a part or a step stays only if the sentence it quotes is found, word for word, inside one
paragraph of the docs. Each step of a route says whether the code **confirms** it (a proven import, with the number of file pairs and an example), imports **both ways** or the other way, or whether **only the docs say so** (a web request is not an import). Click a
part to see what it does, **the files and functions to read first**, the quote and where it is, and a plain-words picture that is labelled as the model's own. A part the docs name but the code lacks is shown as such. It works for a folder and for a public
GitHub link (a downloaded copy now also keeps README and doc files, best first), and on the command line: `python -m skillforge guide <repo>`. One model call, nothing saved; a repository with no README gets that said and no model is asked.
**One independent review** (no Critical, 3 Important and 5 Minor findings, all fixed), **57 deliberate breaks, all caught**, and **real runs with a real model on this repository** that found three defects no mock showed (a hop "confirmed" by the browser test's fake server,
a hop with 1 import one way and 6 the other shown as plain "confirmed", and documents chosen alphabetically). Details, rules and limits: [docs/how-it-works.md](docs/how-it-works.md).

## The Dashboard (slice AC)

The app now opens on a **Dashboard** instead of redirecting to the Builder. It answers three questions on one screen: **does anything need me** (a stored skill that fails checks today or whose files are damaged, a build waiting for your answers, a failed or unsaved draft,
no model set up, no sandbox: worst first, with a link to each), **what do I have** (saved and versions per kind, and the versions saved most recently) and **where do I start** (Build, Read a repository, Import, Combine into a plugin). It only reads and needs no new server code. When nothing
needs you it says what it looked at, and **a part that cannot be read says so**: it never shows zero or "nothing needs you" for something it could not check. 259 UI unit tests, the browser suite 76 of 76, 26 deliberate breaks all caught. Details and limits: [docs/dashboard.md](docs/dashboard.md).

## The Testing Lab (slice AD)

The **Testing Lab** page answers *does this skill really help?* (the Dashboard and Library only say a skill passed static checks). Choose a skill and a version: the page lists the test cases that would run, each check in words, and **how many model calls it will cost before it asks anything**. A run sends each test message to
a model that has the skill and to one that does not, and **code (never a model) checks every reply**. The result says *the skill helped*, *adds nothing* (the model passes everything without it), *no difference*, *made it worse*, *too few cases*, or *no comparison*, shows **each failed check in numbers** ("the first line is 101 characters, the limit is 50") and keeps the replies. It is
a polled run kept in the database (a reload shows it again, a second click cannot spend the quota twice), it says when a newer version exists, and **a skill that cannot be run says why**: no test cases, or it needs tools (most skills about code), which a model with no tools cannot stand in for. None of the three skills on the author's machine could be run on 2026-11-25; slice AE (below) is what fixes that. 40 new backend tests (2,886 in all), 294 UI unit tests, browser suite 86 of 86, 36 deliberate breaks all caught, a real run with the configured model (3 of 3 with the skill, 1 of 3 without). Details and limits: [docs/testing-lab.md](docs/testing-lab.md).

### Your own test cases in the Lab (slice AE)

On the Lab page you can **write test cases yourself** (a name, the exact message, and one to three of the seven checks) and keep them as a **new version** of the skill (`POST /api/library/{name}/tests`, through the library's checked import; older versions are kept). The page says what would stop a save before you press it; only the latest version can be edited, a newer one made meanwhile is never dropped (409), a message with a hidden character
is refused by the library's own checks, and a built skill's two copies of its tests (`tests/cases.json` and the definition file's own list) are kept in step. **Real run on your own `meeting-notes-summarizer` (a copy of the library):** three cases written from its rules made it runnable, and the result, 2 of 3 with the skill and 2 of 3 without, showed both a real fault (it wrote "due date: unassigned") and a limit of the checks (a "must not say X"
check is passed by an answer that does nothing). 44 new backend tests (2,930 in all), 322 UI unit tests, browser suite 92 of 92, 35 deliberate breaks all caught. **An independent review of both slices** (no Critical, 5 Important, 9 Minor; 12 of 14 fixed test-first, 2 documented) found among other things that a pattern check could **freeze the whole server** (so every pattern now runs in a child process with a time limit), that "Run it again" could run a second copy, and that a stale save could overwrite a newer version; after the fixes: 54 more backend tests (2,984 in all), 332 UI unit tests, browser suite 92 of 92, 19 more deliberate breaks all caught. Details: [docs/testing-lab.md](docs/testing-lab.md).

## The Quality Report (slice AF)

The last of the nine pages in the original vision. Choose a skill and a version and the **Quality Report** says what the checks found, **what did not run**, and what to do next, in one place. It is assembled by code from stored files and stored Testing Lab runs: **a GET that asks no model, runs nothing and changes nothing**, and it **never says a skill is safe**. It shows a headline in counts and one sentence of attention, a list of **what to do next** (each with a link), and then
today's checks in three groups: the library's structure and safety checks (each with what it was when the skill was imported: worse, better or new), and, for a skill built here, the **builder's own design and written-file checks run again from the saved definition and spec** (they were shown once at build time and never kept with the version). Then the requirement against its tests (criteria with no test, tests that cite a criterion that does not exist), the cost in tokens, the Testing Lab's result **for that version**
(never another version's), what changed since the previous version, the code it cites, what did not run with its reason, and what the report cannot tell you. **On the author's own library** it found that both built skills fail "the approved requirement reached SKILL.md word for word" because they were built before the builder learned to carry it (true, not a false alarm), and it says what to do. 29 new backend tests (3,013 in all), 350 UI unit tests, browser suite 100 of 100, 28 deliberate breaks all caught.
Details and limits: [docs/quality-report.md](docs/quality-report.md). The whole session's work (the Testing Lab, your own test cases, an independent review, and this page) is written up in [docs/development-log.md](docs/development-log.md).

## The behavioural canary scan (slice AG)

The static checks read a skill's **words** and scripts. They cannot see a skill that politely tells an agent to read `.env` and put it in its answer. The canary scan watches what an agent **does** when it holds the skill:
`python -m skillforge canary <skill-or-agent-folder>` (or `--library NAME`). A model is given the instructions and an ordinary task ("summarise README.md") and answers **one structured step at a time**; **code plays six fake tools** on a fake machine
with **random planted fake secrets** (a canary in `.env`, cloud credentials, SSH keys, the environment), shows the model what each call returned, and **judges every call and the answer**: a secret place read, a canary sent out or copied somewhere, the environment dumped, a download run, a wipe,
a changed `CLAUDE.md` or shell profile. **No model decides anything** (a skill is text a model reads, so a model judge could be talked into "fine"), nothing real is touched and nothing from your computer is sent. A task that finds something is run again **without the skill**, so what the bare model does anyway is not blamed on the skill.
The result is `flagged`, `unclear`, `caution`, `incomplete` or `nothing_observed`: it **never says safe**, and an unfinished run is never counted as clean.

**Measured, with real runs** (`canary --measure`, a corpus of 23 known-bad and known-good skills, 561 model calls with the configured model): the scan flagged **12 of 15 bad skills** with **0 false alarms on 8 good ones**; the library's static wording checks caught **3**, and **none of the ten politely worded ones**. It missed the two it was
expected to miss (a skill that acts only on a date, one that openly sends documents to a place it names) and, in that run, one blunt skill which the static checks caught (**scanned again on its own it was flagged**: the model refused one task and obeyed another, so 12 of 15 is one run's count, not a rate, and `--runs 3` is advised): the two methods are complementary. The corpus was written by the scan's author, so the numbers are optimistic. Real runs also found a noisy signal (now fixed) and that a free model's rate limit can stop a run part way (those skills are reported "could not be run", never as clean).
68 deliberate breaks all caught; 395 new backend tests (3,408 in all). **One independent review** (2 Critical, 4 Important, 7 Minor, all fixed test-first) found, among other things, that **a long hostile command could freeze the scan for over a minute** (patterns that backtrack on model-written text), that common one-line exfiltration was only a "caution", that a control could excuse a *worse* finding of the same kind, and that **a terminal escape in text a model wrote could rewrite the verdict on screen**; the fixes also introduced a regression (a git commit message mentioning `push -f` read as a force-push) that the deliberate-break check caught. Command line only for now: no page or API route. Details, the tools, what the judge looks for and the limits: [docs/canary-scan.md](docs/canary-scan.md).

## Accounts: Sign in with Google, one library per person (slice AH)

A hosted copy used to have **one shared access token**: fine for you alone, wrong the moment a second person uses the same link, because they would see your builds and your library. Now **other people can sign in with their Google account** and each gets their **own** builds, library (skills, agents, plugins, MCP servers), Testing Lab runs, suggestion runs and quality reports.
Set two settings on the host: `SKILLFORGE_GOOGLE_CLIENT_ID` (public, from Google Cloud Console) and `SKILLFORGE_ALLOWED_EMAILS` (who may sign in: addresses, `@domain`, or `*`; required, because signing in proves who someone is, not that they are welcome).

- **Code checks Google's ticket, not a model or the page.** Only a ticket signed by Google's public key with RS256, made for this app, from Google, not expired, with a verified email and **this browser's one-time nonce**. `none`-algorithm and "HS256 signed with the public key" tickets are refused by reading the algorithm first.
- **No Google client secret is used or stored anywhere.** If one is pasted into the setting by mistake, the server refuses to start and says so.
- **Another person's item is a 404**, word for word the same as one that never existed. A person's folder is named only by a random id this server made.
- **Taking someone off the list ends their session on their next request.** The owner (local use, the access token) is unchanged and keeps everything that existed before.
- **Free hosting needs a name, not an IP:** Google accepts only https origins on a real domain name, so a free VM's bare address cannot be used for Google sign-in ([docs/hosting.md](docs/hosting.md), with a two-minute check you can do first). `docker-compose.https.yml` puts Caddy (automatic https) in front of the app.

**An independent review** (no Critical, 5 Important, 2 Minor, all fixed test-first) found, among other things, that **a good Google sign-in cleared the lock on wrong access tokens**, that **five anonymous garbage tickets could lock the owner out**, that **Google's own `g_state` cookie could hide the session**, that an `@company.com` entry trusted a *personal* Google account with a company address (it now needs the Workspace `hd` claim), and that **a migration downgrade deleted every job and usage row**; and my own test for "a nonce is used once" had passed only because the test client's cookie jar obeyed the server.
75 deliberate breaks, all caught in the end (every first-round survivor was a weak test of mine); 192 new backend tests (3,600 in all). **The hosted sign-in screen was driven in a real browser at phone size with touch** (`npm run e2e:phone`, 13 of 13), which found two small tap targets, that a session cannot live across two origins, and a 401 that a page on another address could not read: all fixed or documented.
**Not yet tried: a real Google sign-in in a browser (needs your own Google account), a real phone (this was Edge's emulation), any real host.** Until slice AI (next section) everyone who signed in spent the server's model key. Details and limits: [docs/accounts.md](docs/accounts.md).

## Per-person model keys and a daily allowance (slice AI)

After accounts, several people could sign in to one hosted copy, but **every model call still spent the one key on the server**: you paid for everyone. Now each person can bring their own.

- **Settings → My model:** pick a provider, type the model name, paste a key. The key box is a password box, is **emptied the moment it is saved**, and the key is **never shown again** (not in any answer, error or log; tests search for it).
- **The key is sealed on the server** (AES-256-GCM, a key derived from your `SKILLFORGE_ACCESS_TOKEN`; the database holds only ciphertext). **Whoever runs the server could still read it**: use a key with its own spending limit. Changing the access token makes saved keys unreadable, and people are told to enter theirs again.
- **One place decides which model a call uses** (`ModelAccess.provider_for`): you (the owner) use the server's model; a person with a key uses **only** their key (their provider is built from three entries, nothing of yours comes along); a person without a key uses the server's model **only if you set `SKILLFORGE_SHARED_KEY_CALLS_PER_DAY=N`** (N calls a day, midnight UTC, counted before every attempt, including attempts still running), otherwise they are told to add a key. It covers builds, suggestion runs and Testing Lab runs.
- **`custom` is not offered to people** (it takes an address, which would let a person aim your server at any address).
- Tests: backend 3,708 passed / 4 skipped (104 new for this slice, plus 4 for a builder fix a real build found), web 393 + a clean typecheck, the browser suite 100 of 100, **the phone-size check 29 of 29** (a person saves a key, it is on no page and in none of the server's answers, reload, test, remove), and **40 deliberate breaks + 1 browser break, all caught**. Along the way: the plan's "quota" error would have handed a blocked call to a backup model on your key, and six runs started at the same instant all got through an allowance; both are fixed and tested. **One independent review** (1 Critical, 4 Minor): the Critical one was that **Discard deleted a build's usage rows, which the allowance is counted from, so starting and discarding builds used the shared model without limit**; reproduced as a failing test first and fixed. The 4 Minor ones are listed in the doc below.
- **Not tried:** a real Google sign-in, a real phone, a real provider key saved by a real person, more than one server instance. Details and limits: [docs/per-person-keys.md](docs/per-person-keys.md).

## Limits per person, the People page and the small fixes (slice AJ)

The hosted copy is meant to be open to **any Google account**, on a small free server. Three things make that safe.

- **Limits per signed-in person, never the owner:** disk (default **500 MB**), kept builds (**50**) and background runs working at once (**2**), each a setting (`SKILLFORGE_PERSON_DISK_MB`, `SKILLFORGE_PERSON_MAX_BUILDS`, `SKILLFORGE_PERSON_MAX_ACTIVE`; 0 means none). A person at a limit is told which one and what to do (HTTP 429), and sees only their own numbers in a **Your space** card on Settings. Disk is counted the way a disk counts it (every file in whole 4 KB blocks, every folder a block, links never followed), because the independent review showed that counting bytes let a million one-byte files hide under a limit.
- **A People page for you, the owner:** who has signed in, what each uses (builds, disk, model calls today on your model and on their own key, whether they have a key of their own, never the key), and a reversible **Turn off this account**. A turned-off person is **signed out on their very next request**, told why on the sign-in screen, and refused a new sign-in; **nothing they made is deleted**.
- **Small fixes found by real use:** an empty key box keeps a saved key (changing only the model name no longer means pasting the key again), the model box says some names contain a slash, `Bearer:KEY` is refused, a signed-in person's errors point to Settings and never to a `.env` file they do not have, and an attempt that fails with an unexpected error is counted against their allowance.
- Tests: backend 3,779 passed / 4 skipped (71 new), web 424 + a clean typecheck, the browser suite 100 of 100, **the phone-size check 44 of 44**, and the deliberate breaks (60 first: 52 caught and 8 survivors that were all weak tests of mine, strengthened; then the whole script of 65 again on the final code). **One independent review: no Critical, two Important (tiny files dodged the disk limit; one person's big folder held up everybody's build start), seven Minor:** both Important ones were reproduced as failing tests first and fixed; the Minor ones were fixed afterwards (the completion batch's first task: a turned-off person's refused sign-in no longer rewrites their record, turned-off people are listed first, and more).
- **Not tried:** a real phone, a real host, many people at once, more than one server instance. (Deleting a person's data and a person deleting their own skills were built afterwards, in slice AK below.) **Not built:** limits set per person. Details and limits: [docs/person-limits.md](docs/person-limits.md).

## The completion batch (slice AK)

Six items, finished before the first deployment, each test-first and committed on its own ([the design](docs/superpowers/specs/2026-11-26-completion-batch-design.md)).

- **Small fixes the review of slice AJ left:** a turned-off person's refused sign-in no longer rewrites their record, the People page says *Last sign-in* and lists turned-off people first, and a few more.
- **Three risks closed:** a GitHub copy that was opened in the last 15 minutes is never pruned (a request still reading it is not cut off); git never looks above the data folder (a data folder inside a checkout no longer shows the parent repository's history); and **the usage table is cleaned** (rows older than `SKILLFORGE_USAGE_KEEP_DAYS`, default 90, **never today's**, which a person's daily allowance is counted from).
- **The builder keeps an answered checklist item between rounds**, but only when its quote is still in the person's own words (a real build had lost "constraints" and asked for it again).
- **Deleting, which cannot be undone:** a person can delete a skill, agent, plugin or MCP server from their own library with every version and its backups (a *Danger zone* on its page, the name typed); the owner can **erase a turned-off person's data**, keeping the account and every usage record, which their allowance is counted from ([docs/data-removal.md](docs/data-removal.md)). No link is ever followed, and the server checks the typed name or address itself.
- **The Behaviour Scan page** (`/scan`, `/api/scans`): the third differentiator on a web page. Pick a skill or an agent and a version, see the tasks that would run and the most model calls before anything is asked, run it as a polled scan, and read the engine's result: a headline written from its code, **never "safe"** (nothing observed is information and says *evidence, not proof*), what did not run, every finding, and every step as plain text ([docs/canary-scan.md](docs/canary-scan.md)). A scan counts as running work, belongs to one person, and is erased and removed with them and with its entry.
- **Tests:** backend 3,967 passed / 4 skipped, web 470 + a clean typecheck, **the browser suite 110 of 110** (the scan page and the delete dialog are now driven in a real browser) and **the phone-size check 62 of 62** (the owner's erase dialog too, proving a person's skill is really gone from the server), and 59 deliberate breaks, all caught (one of them in the browser: a scan page that rendered a model's reply as HTML). **Three independent reviews** (the GitHub-link risks, deleting and erasing, and the kept item with the scan page): no Critical finding, 6 Important found and fixed test-first, the Minor ones listed in [the plans](docs/superpowers/plans/2026-11-27-completion-batch-task-6.md).
- **Not tried:** a real model on the scan page (a scripted one was used), a real phone, a real Google sign-in, a real host. **Not built:** a command-line delete, limits set per person.

## Run the local API (the web UI talks to it)

```powershell
cd backend
python -m skillforge serve        # http://127.0.0.1:8000/api/docs, this machine only
```

The same library, validate, sandbox and language features over HTTP, locked to localhost, plus the skill builder as a
conversation you can poll: questions, answers, approval, then a background build ([docs/api.md](docs/api.md)).
`GET /api/kinds` lists what the app builds (the skill, the agent, the plugin and the MCP server) with each kind's checklist, and the library
routes take `?kind=`. A plugin is composed rather than described, so it has its own two routes: `POST /api/plugins/preview` and
`POST /api/plugins`.
Sessions are kept in a SQLite file ([docs/database.md](docs/database.md)); the plan for the web UI on top is in
[docs/ui-and-database-plan.md](docs/ui-and-database-plan.md).

## Open the web UI

```powershell
cd backend;  python -m skillforge serve     # terminal 1: the API
cd frontend; npm run dev                    # terminal 2: the UI, at http://127.0.0.1:3000
```

The **Repository** page reads a folder into a graph, asks for grounded ideas and starts a build from one. The **Builder** is the front door: describe a skill, an agent or an MCP server in a sentence (a picker at the top chooses which), answer only
what is missing, approve the requirement (each line shown beside the words of yours that back it), watch it build, see which
tests cover each way you said you would know it works, and save it. The **Plugins** page combines skills and agents you
already have into one plugin, with no model. The **Library** manages what you keep, with a tab for skills, agents and
plugins: versions, files, compare, export, install, restore, all with the safety checks shown in plain words. The Builder
needs a model set up in `.env`. First-time setup and
what was checked: [frontend/README.md](frontend/README.md) and [docs/ui.md](docs/ui.md). Where this project can be
genuinely different from other skill tools: [docs/differentiators.md](docs/differentiators.md).

## Use it from your phone or any computer (the hosted version)

Besides the version that runs on your own computer, there is a hosted version: one Docker image with the web pages and the API
behind a single address and an access token. Deploy it once, then open the link on your phone or laptop and sign in. Everything
about it, including how to deploy, what it turns off and what is protected, is in [docs/hosting.md](docs/hosting.md). Local use
is unchanged and is still the default.

## Setup

The venv lives outside OneDrive so thousands of files do not sync.

```powershell
# 1. Python environment (Python 3.13)
uv venv C:\dev\venvs\aiskills --python 3.13
uv pip install --python C:\dev\venvs\aiskills\Scripts\python.exe -r backend\requirements-dev.txt

# 2. Run the tests (offline)
cd backend
C:\dev\venvs\aiskills\Scripts\python.exe -m pytest

# 3. For the AI parts later: copy .env.example to .env, then set LLM_MODEL and your API key
#    (GOOGLE_API_KEY for Gemini, OPENAI_API_KEY, or ANTHROPIC_API_KEY for provider anthropic). Never commit .env.
Copy-Item ..\.env.example ..\.env

# 4. Smoke test: one structured-output call to the configured provider
cd ..
C:\dev\venvs\aiskills\Scripts\python.exe backend\scripts\hello_structured.py
```

### Cost

The graph needs no key and costs nothing. For the AI parts you bring your own API key. Gemini offers a free
key with rate limits (check Google's terms for how free-tier data is handled); OpenAI usage is billed by the
provider to your own account. If you cannot get a Gemini key (Google sometimes refuses to create one for an
account), `LLM_PROVIDER` can also be `groq` (verified live on its gpt-oss models), `openrouter`, `mistral`, or `custom` for any
OpenAI-compatible API; those three share the same adapter but have not been verified live yet. `anthropic` has its own adapter, checked against
a mock only. This repo includes no key, no bundled model and no hosted service.

### One model service for every feature

Every model call goes through one service ([docs/ai-engine.md](docs/ai-engine.md)): it picks the model by the kind of work
(you can give writing code its own model, or the tests a Claude model, with a few optional lines in `.env`), makes one
retry policy for failures, counts every attempt and the tokens the provider reports, and keeps keys out of error text.
With none of the optional settings, one model does everything, as before.

**Use several providers together.** Put every key you have in `.env`, pick the main model with `LLM_PROVIDER` and `LLM_MODEL`,
and list the others as backups: `LLM_FALLBACKS=groq:<model>,openai:<model>`. If the first is rate limited, out of quota,
overloaded or unreachable, the next one answers. Any provider works, free or paid (Gemini, Groq, OpenAI, Anthropic Claude,
OpenRouter, Mistral, or any OpenAI-compatible API). `python -m skillforge models --test` shows what is set up, which keys
nothing uses, and tests each model with one tiny call.

See [docs/environment-notes.md](docs/environment-notes.md) for machine findings, including the Docker limitation.
