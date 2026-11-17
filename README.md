# AISkills (SkillForge AI)

An open-source platform that **understands repositories**, **suggests ideas** grounded in them, and **builds
reusable AI skills** from plain-English requirements.

Status: **Understand, Suggest and Build are built and tested offline.** The live check of Build with a real
model is still pending. See [docs/roadmap.md](docs/roadmap.md).

```
 Repo --> UNDERSTAND --graph facts--> SUGGEST --ideas with evidence--> BUILD --> skill packages
          (no AI)                     (AI + graph)                      (AI + templates)
```

## Layout

```
AISkills/
├── backend/
│   ├── skillforge/graph/   # repository graph: parse, resolve, query (no AI)
│   ├── skillforge/cli.py   # `python -m skillforge ...`
│   ├── tests/              # offline tests, no key or network needed
│   └── scripts/            # Step 0 smoke test for the LLM provider
├── docs/                   # roadmap, graph design, decisions, environment notes
├── .env.example
└── README.md
```

## Understand a repository

Works on Python and TypeScript / JavaScript repositories. Needs no AI and no key.

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
```

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
key with rate limits (check Google's terms for how free-tier data is handled); OpenAI and Anthropic usage is
billed by the provider to your own account. This repo includes no key, no bundled model and no hosted service.

See [docs/environment-notes.md](docs/environment-notes.md) for machine findings, including the Docker limitation.
