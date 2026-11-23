# Plan: API, database and web UI

Goal: everything the command line does today, usable from a browser, on your own machine. Nothing here changes the
rules in [CLAUDE.md](../CLAUDE.md): the graph stays deterministic, generated code runs only in the sandbox, keys stay
in the environment or `.env`.

## Choices (and why)

| Part | Choice | Why |
|---|---|---|
| API | Python + FastAPI, run by uvicorn on `127.0.0.1` | In your original brief; typed with the same Pydantic models the code already uses. |
| Database | SQLAlchemy + Alembic, **SQLite first** (a file in the per-user data folder) | The brief allows SQLite for the first slice. PostgreSQL is not installed here and needs no admin-only step this way. Moving to PostgreSQL later means changing one connection setting. |
| UI | Next.js + React + TypeScript + Tailwind (Node 24 is installed) | In your original brief. Chat builder is the main page. |
| The skill library | Stays as **files** (see [library.md](library.md)) | Its SHA-256 manifests make tampering visible. The database will *index* it later, not replace it. |

## Steps, each one tested and committed on its own

| # | Step | Needs a model? |
|---|---|---|
| H1 | **API foundation**: app, local-only protections, and endpoints for the library (list, versions, diff, import, rollback, export, install), validate, sandbox status, languages. See [api.md](api.md). | no · **Built** |
| H2 | **Database + build sessions**: tables for build sessions and jobs; the chat builder as an API (a round of questions, your answers, approval, then a background job with progress). See [database.md](database.md) and the builder part of [api.md](api.md). | yes (mock in tests; checked live with Gemini) · **Built** |
| H3 | **UI shell + Library page**: the first screen on top of H1, so something real can be clicked early. See [ui.md](ui.md). | no · **Built** |
| H4 | **Builder page**: describe, answer, approve, live progress, the result with traceability, save. See [ui.md](ui.md). | yes (fake model in the browser test) · **Built** |
| H5 | Suggest and graph pages, Settings (shows only *whether* a key is set, never its value), Testing Lab and Quality Report views. | partly: the Repository page (suggestions, slice W) and **Settings (slice X, [settings.md](settings.md))** are built; a drawn graph, the Testing Lab and the Quality Report are not |

Agent Builder stays last and is not blocked by any of this.

## Rules for the local API (a web page on another site must not be able to drive it)

- Binds to `127.0.0.1` only. A request whose `Host` is not `localhost`, `127.0.0.1` or `[::1]` is refused
  (stops DNS-rebinding).
- A request that changes something and carries an `Origin` must come from an allowed origin (the UI's own address).
  CORS allows only those origins. A request with no `Origin` is a command-line client, which is fine.
- Uploads are read with a hard size cap, into memory, never unpacked to disk; the library's own checks still decide.
- No endpoint ever returns an API key. Nothing runs a script except through the sandbox.
- Long work (reading your words, writing a skill) is a job you poll (built in H2). `test_scripts` on a library import
  still blocks until its cases finish.

## Open questions (will be asked when reached, not before)

- H5: should the Settings page be allowed to *write* a key into the git-ignored `.env`, or only show how to? **Answered in slice X: it writes (the page is no easier than editing the file if it only shows how), with a fixed list of names, safe characters only, a key never sent back, an atomic write, and off in the hosted version ([settings.md](settings.md)). Say so if you want it to only show how.**
- Later: one command that starts API and UI together, and what "installable" should mean for other people.
