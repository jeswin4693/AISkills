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

1. Copy `.env.example` to `.env` and fill in your provider key. Never commit `.env`.
2. Create the Python environment in `backend/` (see Step 0 notes in the project plan).
