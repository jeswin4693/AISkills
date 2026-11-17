# AISkills (SkillForge AI)

A platform that turns natural-language requirements into tested, versioned, reusable AI skill packages.

Status: **Step 0 - environment and project skeleton.** No application code yet.

## Layout

```
AISkills/
├── backend/   # FastAPI + Pydantic (Step 1+)
├── docs/      # architecture notes, SDM draft
├── .env.example
└── README.md
```

A `frontend/` (Next.js) folder will be added later, after the backend slice works.

## Core idea

The Skill Definition Model (SDM) is the single source of truth. Every generated file is derived from it.

```
Chat -> Requirement Spec -> SDM -> Generated files -> Validator -> Sandbox tests -> Quality report
```

See [docs/sdm-draft.md](docs/sdm-draft.md).

## Setup

The venv lives outside OneDrive so thousands of files do not sync.

```powershell
# 1. Python environment (Python 3.13)
uv venv C:\dev\venvs\aiskills --python 3.13
uv pip install --python C:\dev\venvs\aiskills\Scripts\python.exe -r backend\requirements.txt

# 2. Free local AI: install Ollama from https://ollama.com, then download a model
ollama pull qwen2.5:7b

# 3. Config: the defaults in .env.example already point at local Ollama. No key needed.
#    Never commit .env.
Copy-Item .env.example .env

# 4. Smoke test: one structured-output call to the configured provider
C:\dev\venvs\aiskills\Scripts\python.exe backend\scripts\hello_structured.py
```

### Cost

The default setup costs nothing: local Ollama needs no account and no key, and your prompts never leave
your machine. The only "price" is your own hardware (about 5 GB of RAM for the 7B model, CPU is fine but
slow). Hosted providers (Ollama Cloud, Anthropic, others) are optional extras that you can enable in `.env`.

See [docs/environment-notes.md](docs/environment-notes.md) for machine findings, including the Docker limitation.
