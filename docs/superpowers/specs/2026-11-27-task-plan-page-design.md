# The Task Plan page (slice AM): design

Status: written 2026-11-27 for the owner, who asked to "start the next phase of development" and gave no further detail. Everything here that is not a rule of the project is **my call**, said as such.

## Intent (my reading)

`python -m skillforge plan "<task>" --repo <folder>` (step C1 of the Task Conductor, [task-conductor.md](../../task-conductor.md)) reads a request and plans it **before any work**: what it contains (with the person's own verified quotes),
what it does not say (questions, assumptions), the size of the task from the code graph, the process and when it stops to ask, the rules that apply, and a token plan. It is built, tested and was run live, but it exists **only on the command line**.
The page puts the same plan where the other tools are, so the plan can be read, not scrolled past in a terminal.

## Goals

- A **Task Plan** page: type a task, optionally name a repository (a folder on this computer or a public GitHub link), choose whether a model may read the request, and read the plan as five clear sections.
- The page shows **exactly what the command line shows**, nothing more claimed: the plan's own `not_checked` list is always shown, every rule is marked "not enforced yet", every token number is an estimate.
- Before anything is sent to a model the page says **what would be sent** (the same sentence the command prints).
- **Copy the plan as Markdown** (the command's own `render_markdown`), so a plan can be pasted into a ticket or a skill.

## Non-goals

- No change to how a plan is made: `make_plan` is called as the command calls it. The one edit in `conductor/` moves its too-short-task check into a function, `check_task`, so the route can refuse a task before a download or a model (the behaviour is the same).
- No saving, no history, no session: **answering the plan's questions and approving it** is a later step (the builder-like session in the design doc), not this one.
- No phase skills, hooks, traceability or runner (C2 to C5).
- No new library, table or setting.

## Anti-goals (a failure even if it "works")

- Showing a plan as if it enforced anything. Rules say "not enforced"; a plan made without a model says the request was **not read**, never an empty "nothing stated".
- Sending anything to a model that the command would not send. The model sees the task text, the **names and places** (not contents) of files and functions the task mentions, file and language counts, and the lines of `CLAUDE.md` / `AGENTS.md`.
- The person's own folder path in any answer or on the page. A GitHub link is shown as `owner/repo`, never the snapshot's folder.
- A model that cannot be reached shown as an empty plan: it is an error with the reason (as the guide's is).

## Constraints (project rules)

- Models propose, code decides: unchanged, it is all inside `make_plan`.
- Reads a folder, so it is **off in the hosted version** (403) like every route that reads a folder; the plan would also use the server's model.
- Tests are offline (`MockProvider`); no test reads the real `.env` or calls a model.
- Every model call names its task: already so inside `conductor/` (`Task.EXTRACT`, `Task.SELECT`).

## Approaches considered

| | What | Trade-off |
|---|---|---|
| **A. A synchronous route and a page (chosen)** | `POST /api/plan` returns the whole plan; the page shows a spinner while it waits (one or two model calls, seconds). Nothing saved. | Smallest; the same shape as the "How it works" guide, which is also one request and nothing saved. A refresh loses the plan (it can be copied first). |
| B. A polled run kept in the database | Like the suggestion runs: a table, a start route, polling, a list of earlier plans. | Survives a reload and keeps a history, but needs a migration and a pool slot, for a plan that takes seconds. Worth it later when the plan becomes a session with answers and approval. |
| C. A page that only shows `--json` pasted in | No server work. | Nobody would paste it; it does not remove the command line. |

## Decisions (my calls)

- **Route:** `POST /api/plan`. Body: `task` (at most 8,000 characters), `repo` (optional, a folder or a public GitHub link, at most 4,096), `no_ai`, `kind` (optional: feature, bugfix, refactor, migration, docs, investigation, other), `tier` (optional, 0 to 3, can only raise),
  `budget` (optional tokens), `sensitive` (up to 10 path globs, each at most 200 characters). `allow_lower` is left to the command line: lowering a tier is recorded as a deliberate act and is not a thing to offer on a form.
- **Answer:** the plan as the command's `--json` gives it (`TaskPlan`), plus `markdown` (`render_markdown`) and `source` (what a link was and what was left out, as the Repository page shows). `repo` is `owner/repo` for a link and the folder's name otherwise.
- **A GitHub copy has no `CLAUDE.md` or `AGENTS.md`** (only source files are downloaded), so the plan's notes say so, as the command does.
- **Errors:** a task that is too short, a bad tier, a bad folder or link → 400 in words; a model that cannot be used or answered → 502 with its own words; no path in any message.
- **Page:** `/plan`, a menu entry **Task Plan**. The repository box starts with the folder the Repository page last read (remembered in this browser), editable. **Facts only** (no model) is a checkbox, **off** by default, because the model reading is the point; the page says what would be sent next to the button.
- **Sections:** 1 What the request contains, 2 What it does not say, 3 Size and process, 4 Rules that apply, 5 Token plan, then Notes and What was NOT checked, in the order the command prints them, so the two can be compared.

## Left to the builder

Layout of the sections, the exact wording of the page's own sentences, the unit-test list, how long tables are shown on a phone.
