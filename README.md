# AISkills (SkillForge AI)

An open-source platform that **understands repositories**, **suggests ideas** grounded in them, and **builds
reusable AI skills** from plain-English requirements.

Status: **Understand, Suggest, Build (with a test harness, `eval`), Safety (static checks and a sandbox), Scripts, the skill Library (versions, risk diff, rescan), the read-only Task Plan, a local API with a database, the web UI (Builder and Library), one model service with backup models, the hosted version, and the foundation for more kinds of builder (the kind registry), the Agent Builder, the Plugin Builder and the MCP Builder (Python) are built and tested. The main paths were run live with Gemini (Groq as a backup, the hosted image in Docker).** Not built yet: the TypeScript half of the MCP builder, plugins that carry hooks and MCP servers, and the web pages for the graph, suggestions and settings.
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
`claude plugin validate --strict`. Not yet: hooks and MCP servers inside a plugin (Phase 4).

**Phase 3, the MCP Builder (Python), is built too** ([docs/mcp-builder.md](docs/mcp-builder.md)): pick **MCP server** in the Builder and describe a few tools in plain words. The model drafts the tools; **code**
writes `server.py` around them (the imports, the signatures, the tool annotations, `mcp.run()`), pins the official `mcp` SDK, writes a README with the exact `claude mcp add` command, and checks it by reading it:
anything that starts programs, builds code from text, loads native code or carries a key **fails**, and a key is only ever the *name* of an environment variable. Then the server is **started in the sandbox and
called over the real MCP protocol**, and the build says "ok" only if it really ran and every test case matched; a server that never ran, or whose tool needs the network, is an honest DRAFT. Two real builds with the
configured model found and fixed two defects (missing imports, and a tool that returned simulated data). **An independent review then found real gaps** (an encoding trick that hid code from the checks,
code beside `server.py` that Python would import, alternate spellings of running a command, a forged sandbox verdict, and a tool name that could be written into the file as code); they are fixed and tested, and a server the
builder writes may now import only an allow-list of safe standard-library modules. The checks are still a reading by syntax and **cannot prove a file safe**: read a server you did not build before you add it
([docs/mcp-builder.md](docs/mcp-builder.md)). Not yet: TypeScript, HTTP, a run against a live Claude Code, and the MCP flow in a real browser.

**What is next, in this order:**

1. **Phase 3b, the MCP builder in TypeScript** (and the Streamable HTTP transport): the names of the TypeScript SDK still have to be settled with a real install, as the Python ones were.
2. **Phase 4, plugins that carry more:** hooks, MCP servers and settings inside a plugin, and a risk diff that sees every kind.
3. **More differentiators** ([docs/differentiators.md](docs/differentiators.md)): code-level evidence with drift detection,
   and a behavioural canary scan (the risk diff and rescan are already built).
4. **The remaining web pages:** the repository graph, suggestions and Settings.

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
│   ├── skillforge/kinds/     # the kind registry: what the app builds (skill, agent and plugin) and each one's checklist
│   ├── skillforge/library/   # versions per kind: import (checked), diff + risk diff, rescan, rollback, export, install (no AI)
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

Open **Plugins** in the web pages, give the plugin a name and a one-line purpose, tick the skills and agents to include and press **Preview the plugin**. You see its files,
**what it can do on your machine** (every tool its parts grant and every script it ships, worked out by code) and every check. **Keep this plugin** stores it in the
library's Plugins tab, where you can export it as a zip or install it from a folder. Its README has the two commands that add it to Claude Code:
`claude plugin marketplace add "<folder>"` and `claude plugin install <name>@<name>-local`. The app never writes Claude's settings: adding it is your command
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
python -m skillforge library export my-skill --out my-skill.zip
python -m skillforge library install my-skill --project          # or --personal, or --to <skills folder>
```

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

The **Builder** is the front door: describe a skill, an agent or an MCP server in a sentence (a picker at the top chooses which), answer only
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
