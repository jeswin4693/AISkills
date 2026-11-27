# The Task Plan page (slice AM)

The command line's `python -m skillforge plan` ([task-conductor.md](task-conductor.md), step C1) now has a page: **Task Plan** in the menu. Type a task, optionally name a repository (a folder on this computer or a public GitHub link), and read
the plan before any work: what the request contains (with the person's own words as proof), what it leaves out, how big the task is from the code graph, the phases and when it stops to ask, the rules that apply, and what reading it would cost.
It is the same plan: the page calls `make_plan` unchanged and shows what the command prints, in the same order. Design: [superpowers/specs/2026-11-27-task-plan-page-design.md](superpowers/specs/2026-11-27-task-plan-page-design.md).

Nothing is saved, nothing is run, and nothing in the repository is changed or created. It is off in the hosted version (it reads a folder on the server and would use the server's model).

## What you see

```
 What should be done?   [ Make `route` in `api/routes.py` return the tax too. Do not change anything in pricing. ]
 Folder or GitHub link  [ C:\code\shop-api ]      [x] Don't use a model (plan from facts only)    > Options
 [ Plan it ]   Sent to the model: your task text, the names and places (not the contents) of the files and functions it mentions, ...

 Task plan   [Read by a model]      Read by gemini/... · 2 model calls · repository shop-api      [Copy as Markdown] [Download .md]
 1. What your request contains      You asked for: route returns the tax as well — "Make `route` in `api/routes.py` return the tax too."
 2. What it does NOT say            [Blocking] What should route return when the tax is zero?   ·   Assumptions (none used until approved)
 3. Size and process                Tier 2: Feature or refactor ... signals, phases (reads / writes / done when / approval), when it stops and asks
 4. Rules that apply                7 listed, from 16 found ... None is enforced yet
 5. Token plan (estimates)          Budget ... planned reading ... what to read in order, what was not planned, files it would create
 Notes · What was NOT checked
```

- **Facts only** (a checkbox): no model is asked. The plan then says plainly that the request was **not read** (never an empty "nothing stated"), and plans only what the code can measure: the code the request names, the size from proven links, the phases, the rules (listed, not filtered) and the token plan.
- **Options:** the kind of task (otherwise worked out from the request), a tier to raise it to (a tier can only be raised here; lowering one is a deliberate act of the command line and is recorded there), a reading budget in tokens, and path patterns that make a task tier 3.
- **Copy as Markdown** and **Download .md** give the same text the command prints (`render_markdown`), so a plan can be pasted into a ticket. The page keeps nothing: this is how a plan leaves it.
- A task written with **code names in backticks** (`` `parse_config` ``, `` `src/util.py` ``) is looked up in the graph; a plain word such as `build` is never taken for code.

## What is sent to a model

The page says it before anything is sent, with the same words the command prints. With a model: **the task text; the names and places (not the contents) of the files and functions the task mentions; file and language counts; and the lines of the repository's
`CLAUDE.md` / `AGENTS.md`**. A test pins that a distinctive string inside a function body, and the person's folder path, never reach the model. With **Don't use a model** nothing is sent. A GitHub copy has no `CLAUDE.md` or `AGENTS.md` (only source files
and README and doc files are downloaded), so no rule lines are sent and the plan's notes say its rules were not read.

## The route: `POST /api/plan`

| Body | |
|---|---|
| `task` | the request, 1 to 8,000 characters; at least three words and ten characters or a plain 400 |
| `repo` | optional: a folder on this computer or a public GitHub link (at most 4,096); blank means none |
| `no_ai` | send nothing to a model |
| `kind` | optional: feature, bugfix, refactor, migration, docs, investigation or other (replaces the model's guess) |
| `tier` | optional, 0 to 3, can only raise |
| `budget` | optional, tokens, 1 to 10,000,000 |
| `sensitive` | up to 10 path patterns of at most 200 characters |

The answer is the plan as `plan --json` gives it, plus `tier_name` (so the page and the Markdown cannot disagree), `markdown` and `source` (what a link was and what was left out; `{"kind": "none"}` with no repository). **No path of the person's folder is in it:**
the plan names a folder by its name and a GitHub link as `owner/repo` (the snapshot folder is a hash). A bad value is a 422; a task that is too short, a bad folder or link or an unreadable folder is a plain 400 in words (the operating system's own words, which repeat a path,
are never passed on); a model that is not set up or cannot answer is a 502 with its own words, never an empty plan. A too-short task is refused **before a link is downloaded or a model is asked** (`conductor.plan.check_task`, the one function that holds the rule).
Code: `backend/skillforge/builder/plans.py`, `api/plan.py`; page: `frontend/src/components/plan/PlanPage.tsx` and `PlanView.tsx`, with the form's checks and the plan's wording in `frontend/src/lib/plan.ts` (pure, unit-tested).

## What the page never does

- It never shows a plan as if it enforced anything: every rule says "not enforced yet", every token number is an estimate (about 4 characters a token), and the plan's own **What was NOT checked** list is always shown.
- It never says the whole task fits when it does not: the budget sentence follows the engine's `fits_budget`, which is false when anything was dropped for being over the budget.
- It never sends the form with a problem it can see (a task that is too short, a bad folder or link, a budget that is not a whole number, too many or too long path patterns); the server checks everything again.

## Limits (said plainly)

- **Answering the plan's questions and approving it is not built** (a builder-like session is the next step of the Task Conductor). The plan lists what is blocking; nothing records an answer.
- **Nothing is saved**: reload the page and the plan is gone (copy or download it first).
- A plan made with a model is **as good as the model's reading**; code checks that every quote is in the person's words and every named target is real, not that the reading is right or complete.
- **The size reflects only the code the request names.** If the work turns out to touch other code, that was not measured. Only proven links count.
- Token numbers are **estimates**, and they cover context to read and files to create, not the model's own reasoning or replies. Real use is not recorded anywhere yet.
- For a GitHub link the rule files are not read (not downloaded), and each plan downloads a copy only if the last one is older than 15 minutes.
- Needs the local app; off in the hosted version.

## Checked

**Tests (2026-11-27).** Backend: 4,074 pass in all (4 skipped: this account cannot create symbolic links), 30 of them new in `tests/test_plan_api.py` (the real route through the real app with a mock model: the model-made plan with its quotes, a blocking question and a chosen rule;
the plan as Markdown and as the plan, whole; that the model is sent the task and the names of what it mentions and **never a file's contents or a path**; a plan with no repository; a plan with no model that sends nothing and needs no key; that a plan **changes nothing in the repository**;
every rule "not enforced"; each option; every out-of-range value refused before anything is read; a too-short task refused before a link is downloaded or a model asked; a missing or failing model as a 502 with its own words; bad folders, an unreadable folder whose operating-system
words repeat a path, a blank box; a GitHub link named `owner/repo` with its rule-file note and no managed path; off when hosted). Web: 526 unit tests, 27 of them new (`lib/plan.test.ts`), and a clean typecheck. Browser: the real-Edge suite is **121 of 121** on side ports (6 new steps in
`e2e/run.mjs`: a plan with a model, with the quote behind each item, the blocking question, the tier, the rules and the token plan; a plan with no model that says the request was not read; saving the plan as Markdown (the file is the command's text, with no path) and copying it; a too-short
task refused in words with the button off; phone width with no sideways scroll; and a step back to the Repository page). The suite's fake model now answers the plan's two questions. **Its first run found a mistake in my own placement:** the new steps left the browser on `/plan`, so the 8 older
guide steps that expect the Repository page failed; a step that goes back and reads the map's repository again fixed it (the product was right).

**Deliberate breaks: 59, all caught in the end** (25 on the server side, in a scratch copy: the order of the checks, the options passed on, the status of each error, the limits, the hosted refusal; 34 on `lib/plan.ts`). The first round left 2: no test sat exactly on the 8,001-character edge, and a budget pattern that let `"1."` through
(`1.5` alone is caught by a later whole-number check, which made the change look harmless). Both now have tests; one more test was added before the round for a read error that repeats a path.

**A real run (2026-11-27, this repository's own code, through the real route, no model):** a plan for "add a `--json` option to the `library list` command in `cli.py`" matched `cli.py` and planned 5 reads (30,665 estimated tokens) in 8.5 seconds for the first read of the graph and under a second after; naming `` `_run_library` `` planned 13 reads for 16,976; a sensitive path
made it tier 3; **a budget of 8,000 gave a plan that reads 7,983 tokens and still says it does not fit** (the engine's `fits_budget` is false whenever anything was dropped for being over the budget), so the page words that case as "Not everything fits: some context is left out" and not as "over". No path was in any answer. A look at the screenshot found one wording to improve in both the page and the command (below).

**Not verified:** a real model on the page (the browser suite's fake model and the tests' mock answer; the command was run live with Gemini when it was built), a GitHub link in the browser (it is tested through the route with the page's fake download), a very large repository, a screen reader, any browser but Edge,
and an independent review. **A wording to improve, in the page and the command together:** with few rules the line "1 rule listed, from 0 found in the repository's rule files and your own words" is hard to read; the page keeps the command's sentence so the two can be compared.
