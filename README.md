# AISkills (SkillForge AI)

An open-source platform that **understands repositories**, **suggests ideas** grounded in them, and **builds
reusable AI skills** from plain-English requirements.

Status: **Understand, Suggest, Build, Safety, Scripts, the skill Library, a local API with a database, and the web UI's Library pages are built and tested; Suggest, Build, the builder API and Scripts are verified live with Gemini.**
See [docs/roadmap.md](docs/roadmap.md).

```
 Repo --> UNDERSTAND --graph facts--> SUGGEST --ideas with evidence--> BUILD --> skill packages
          (no AI)                     (AI + graph)                      (AI + templates)
```

## Layout

```
AISkills/
├── backend/
│   ├── skillforge/graph/   # repository graph: parse, resolve, query (no AI)
│   ├── skillforge/library/ # skill versions: import (checked), diff, rollback, export, install (no AI)
│   ├── skillforge/api/     # local HTTP API (FastAPI), localhost only
│   ├── skillforge/builder/ # the skill builder as a database-backed conversation with background jobs
│   ├── skillforge/db/      # SQLAlchemy models + Alembic migrations (SQLite first)
├── frontend/               # web UI: Next.js + React + TypeScript + Tailwind (talks to the local API)
│   ├── skillforge/cli.py   # `python -m skillforge ...`
│   ├── tests/              # offline tests, no key or network needed
│   └── scripts/            # Step 0 smoke test for the LLM provider
├── docs/                   # roadmap, graph design, decisions, environment notes
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

With `--scripts` the skill can ship helper scripts. Every script case runs in the Linux sandbox, and a skill whose
scripts never ran is marked DRAFT ([docs/scripts.md](docs/scripts.md)).

## Check any skill folder

Static safety and structure checks that run nothing, for skills made here or downloaded
([docs/validate.md](docs/validate.md)). Scripts are never run unless a Linux sandbox is available, and never on
your machine directly.

```powershell
cd backend
python -m skillforge validate C:\path\to\skill-folder   # exit code 1 if a check failed
python -m skillforge sandbox-status                     # is a safe place to run scripts available?
```

## Keep skills as versions

Import a skill folder or `.zip` (made here or downloaded): it is checked first and **refused if a check fails**.
Accepted skills are kept as v1, v2, ... that you can diff, roll back, export as a `.zip` or install where an agent
reads them ([docs/library.md](docs/library.md)). Needs no AI and no key; importing never runs a script.

```powershell
cd backend
python -m skillforge library import generated-skills\my-skill    # or a .zip
python -m skillforge library list
python -m skillforge library diff my-skill                       # what changed since the version before
python -m skillforge library rollback my-skill --to 1            # a new version with the content of v1
python -m skillforge library export my-skill --out my-skill.zip
python -m skillforge library install my-skill --project          # or --personal, or --to <skills folder>
```

## Run the local API (for the web UI that is coming)

```powershell
cd backend
python -m skillforge serve        # http://127.0.0.1:8000/api/docs, this machine only
```

The same library, validate, sandbox and language features over HTTP, locked to localhost, plus the skill builder as a
conversation you can poll: questions, answers, approval, then a background build ([docs/api.md](docs/api.md)).
Sessions are kept in a SQLite file ([docs/database.md](docs/database.md)); the plan for the web UI on top is in
[docs/ui-and-database-plan.md](docs/ui-and-database-plan.md).

## Open the web UI

```powershell
cd backend;  python -m skillforge serve     # terminal 1: the API
cd frontend; npm run dev                    # terminal 2: the UI, at http://127.0.0.1:3000
```

The **Builder** is the front door: describe a skill in a sentence, answer only what is missing, approve the requirement
(each line shown beside the words of yours that back it), watch it build, see which tests cover each way you said you
would know it works, and save it. The **Library** manages what you keep: versions, files, compare, export, install,
restore, all with the safety checks shown in plain words. The Builder needs a model set up in `.env`. First-time setup and
what was checked: [frontend/README.md](frontend/README.md) and [docs/ui.md](docs/ui.md). Where this project can be
genuinely different from other skill tools: [docs/differentiators.md](docs/differentiators.md).

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
#    (GOOGLE_API_KEY for Gemini, OPENAI_API_KEY, or ANTHROPIC_API_KEY). Never commit .env.
Copy-Item ..\.env.example ..\.env

# 4. Smoke test: one structured-output call to the configured provider
cd ..
C:\dev\venvs\aiskills\Scripts\python.exe backend\scripts\hello_structured.py
```

### Cost

The graph needs no key and costs nothing. For the AI parts you bring your own API key. Gemini offers a free
key with rate limits (check Google's terms for how free-tier data is handled); OpenAI usage is billed by the
provider to your own account. If you cannot get a Gemini key (Google sometimes refuses to create one for an
account), `LLM_PROVIDER` can also be `groq`, `openrouter`, `mistral`, or `custom` for any OpenAI-compatible API;
those four share the same adapter but have not been verified live yet. This repo includes no key, no bundled
model and no hosted service.

See [docs/environment-notes.md](docs/environment-notes.md) for machine findings, including the Docker limitation.
