# Start prompt for a new Claude Code chat

Open the AISkills folder in VS Code, start a new Claude Code chat, and paste everything below the line.

---

# Project: SkillForge AI (folder: AISkills) - continue from Step 0

You are a Senior AI Architect, Full-Stack Engineer, AI Agent Engineer and Product Designer. I am continuing a project planned in an earlier chat that I can no longer access. Everything you need is below. Read it, inspect this folder, and then follow the "What I want from you now" section.

## 1. Product vision

SkillForge AI is a standalone web app where users describe, in plain English, the AI skill or agent they want. The platform must:
1. Understand the requirements and ask clarifying questions when they are incomplete.
2. Produce a structured requirement spec, and not generate files until requirements are clear.
3. Design the skill as a structured Skill Definition Model (SDM), the single source of truth for all generated files.
4. Generate the full skill package (SKILL.md or equivalent, scripts, schemas, config, examples, tests, README).
5. Validate it, run controlled tests in a sandbox, fix issues, and re-test.
6. Produce a reusable, versioned package that can be exported to Claude Code or other agent frameworks.

This must be a real engineering platform, not an LLM wrapper that writes Markdown. Never fabricate test or validation success. Treat all generated skills as untrusted until validated and tested.

## 2. Modules

- A. Requirement Intelligence: chat, extract objectives/constraints/acceptance criteria, detect gaps, ask questions.
- B. Skill Architect: turn the approved spec into the SDM (name, responsibilities, inputs/outputs, workflow, tools, scripts, config, error handling, security, limitations, tests).
- C. Skill Development Engine: template-based generators (not one giant prompt) for SKILL.md, scripts (Python/TypeScript), schemas, docs, tests.
- D. Skill Quality Intelligence: automated checks for requirement coverage, instruction clarity, structure, conflicts, code correctness, input validation, error handling, security, reusability, test coverage. Output a report (passed, failed, warnings, missing, suggestions) and auto-fix then re-test where possible.
- E. Testing Lab: isolated sandbox, positive/negative/edge/regression/instruction-following tests, logs, expected-vs-actual. No generated code runs on the host without sandboxing, resource limits and permission controls.
- F. Skill Management: dashboard, versions, compare, duplicate, export, import, history, format adapters.
- G. Agent Builder: future-ready only. Do not build it now, but do not block it architecturally.

## 3. UI (later phase)

Next.js + React + TypeScript + Tailwind. Pages: Dashboard, Skill Builder Chat (primary), Requirement Spec, Skill Architecture, Generated Files Explorer, Testing Lab, Quality Report, Version Management, Settings / AI Provider Config.

## 4. Stack (to evaluate, not to assume)

Backend Python + FastAPI + Pydantic. PostgreSQL + SQLAlchemy (SQLite or JSON files are acceptable for the first slice). Provider-independent LLM abstraction with adapters for Anthropic, OpenAI, Gemini, later Ollama. Isolated script execution. Do not add libraries without clear value. Do not assume a skill format or provider throughout the codebase; keep it extensible.

## 5. Mandatory engineering principles

Modular architecture with separation of frontend, backend, AI orchestration and execution. Strong typing and validation. Centralized error handling. No hardcoded credentials, API keys only from environment. Logging. Database migrations. Unit and integration tests. Clear docs. No uncontrolled execution of AI-generated code.

## 6. Roadmap phases

1 Discovery and architecture. 2 Foundation and DB. 3 Requirement Intelligence. 4 SDM and Architect. 5 Generation engine. 6 Quality evaluation. 7 Sandbox testing lab. 8 Management and versioning. 9 Agent Builder. 10 Integration, security testing, deployment. Each phase needs objectives, technical design, tasks, deliverables, test scenarios, acceptance criteria. Prioritize a working, testable MVP before advanced features.

## 7. Build order I agreed to (simple version)

Core idea: Chat -> Requirement Spec -> SDM -> Generated files -> Validator -> Sandbox test -> Report.

- Step 0: environment and skeleton (mostly done, see below).
- Step 1 (thin slice, no UI, no DB): Pydantic RequirementSpec and SkillDefinition models; one LLM provider interface with a single `generate_structured(schema, prompt)` method and one adapter; one output format (Claude SKILL.md folder layout); a CLI or single FastAPI endpoint that goes requirement text -> clarifying questions -> SDM -> files on disk.
- Step 2: deterministic non-LLM validators (frontmatter valid, referenced scripts exist, schemas parse, Python compiles, no conflicting rules) plus a Docker sandbox runner (no network, CPU/memory/time limits, read-only mount) and an honest report where a check only counts as passed if it actually ran.
- Step 3: Next.js UI with chat as the main page, then PostgreSQL + Alembic, versioning, export, dashboard. Agent Builder last.

The hardest problems: deciding when requirements are complete (use a checklist-style completeness score, not the model's own judgment), keeping files consistent with the SDM (render from templates, then check files against the SDM), sandboxing untrusted code, and honest evaluation (separate checks that actually ran from checks the LLM merely claimed).

The platform must also distinguish a prompt (one-off text, no reuse contract), a skill (reusable instructions plus optional scripts and schemas with defined I/O and tests, runs inside a host agent), a tool (callable function, strict schema, no judgment), and an agent (owns a loop and goal: skills + tools + memory + permissions + model config).

## 8. Current state of this folder (done in the earlier chat)

- `git init` on branch `main`, nothing committed yet.
- `.gitignore` (ignores `.env`, `.venv`, `node_modules`, generated output), `.env.example` (provider-neutral variable names, no keys), `README.md`, `docs/sdm-draft.md` (draft SDM fields and prompt/skill/tool/agent table), empty `backend/` folder.
- The earlier workspace was a folder named AIBC. It could not be renamed because VS Code had it open, so this AISkills folder was created instead. The empty AIBC folder can be deleted.

## 9. Findings about my machine (Windows 11 Enterprise, PowerShell)

- Python 3.14.3 default, and Python 3.13.15 also installed. Node 24.13.1. Git 2.53.0. Docker 29.3.0 with the daemon running.
- Docker is in Windows-container mode (server=windows). The sandbox needs Linux containers. WSL is not installed, so switching may need the Hyper-V backend, and company policy might block it. This must be resolved before the sandbox work.
- This project is inside a OneDrive-synced folder. A `.venv` or `node_modules` here would sync thousands of files. Prefer a venv outside OneDrive (for example `C:\dev\venvs\aiskills`) or exclude those folders.

## 10. Decisions still open (ask me, do not assume)

1. Python version for the venv (suggested: 3.13, because 3.14 may lack package builds) and venv location.
2. First LLM provider (suggested: Anthropic Claude) and model.
3. First output format (suggested: Claude SKILL.md).
4. First demo skill to build the platform around (suggested: a TypeScript repository analyzer that finds duplicate functions and suggests safe refactoring).
5. Whether to switch Docker to Linux containers and test it.

## 11. What I want from you now

- Do not implement anything beyond finishing Step 0 until I approve.
- First inspect this folder and confirm the state in section 8 is accurate.
- Keep answers short and simple. I want "how and where to start", not long essays.
- Ask me the open decisions in section 10 in one short list, with your recommendation for each.
- After I answer, finish Step 0 (venv, hello-world structured-output call to the chosen provider with the key read from `.env`, Docker check), then propose the Step 1 slice and wait for my approval.
- If I ask for the full technical proposal, cover: product architecture, component architecture, database schema, SDM design, AI orchestration, requirement analysis workflow, skill generation workflow, validation/evaluation methodology, sandbox architecture, API endpoints, frontend page structure, security architecture, stack justification, folder structure, phase roadmap, risks and mitigations. Include the hardest engineering challenges and how to solve them.
