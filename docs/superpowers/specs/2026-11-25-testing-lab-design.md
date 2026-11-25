# The Testing Lab (slice AD, then AE for the person's own test cases)

Status: design written 2026-11-25 by Claude. The person said "do whatever you prefer that which is best" when asked what the Lab should do for skills
that cannot be run today, so the approach below is **my call**, with my reasons. Slice AF (the Quality Report) is separate and comes after this one.

## Why

The original vision (docs/START_PROMPT.md, part E and the page list) asks for a Testing Lab: tests with logs and expected-versus-actual. The test harness
(`skillforge eval`, slice K) already does the hard part, but only on the command line. The Dashboard (slice AC) says outright that its "checked" means
static checks, "not that a skill works: that is what the Testing Lab is for".

**What the library looked like on 2026-11-25** (read from disk, three saved skills): none of them could be run by `eval`.
`count-todo-fixme` asks for `read_files` (a model with no tools cannot stand in for it); `git-commit-writer` has one test case with no message and no
check (saved before the harness existed); `meeting-notes-summarizer` has no test cases at all. A Lab that only wraps the command would say "not run" three
times. So the Lab has two jobs: **run what can be run, and let a person make more of it runnable by writing their own cases.**

## Goals

1. A **Testing Lab** page: choose a skill and a version, see exactly what would be run and what it would cost in model calls, run it, watch it, read the result.
2. The result is **kept** (a polled run, like the ideas on the Repository page), so it survives a reload and a second click cannot spend the quota twice.
3. The result shows the **comparison**, not a lone score: with the skill, without it, per case, with each failed check in words and the reply that failed it
   (expected versus actual). It says plainly whether the skill helped, added nothing, made things worse, or had too few cases.
4. A skill that **cannot** be run says why in the page's own words before anything is asked of a model, and says what a person can do about it.
5. (Slice AE) A person can **write their own test cases** in the page (a message and checks chosen from the seven kinds) and keep them as a **new version**
   through the library's checked import. Tests written by a person are the stronger answer to the documented limit that the model that wrote a skill also wrote its tests.

## Non-goals

* No new kind of check and no model judge: code grades with the seven checks in `evaluate/grade.py`.
* No running of skills that need tools (`read_files`, `run_commands`, `network`) or have scripts: a model with no tools is not an agent. They stay "not run" with the reason.
* No tests for agents, plugins or MCP servers (`eval` for agents is not built); the Lab says so for them.
* No automatic writing of test cases by a model for old skills (option B in the approaches): see below.
* No history chart, no comparison of two runs side by side. A list of earlier runs per skill is enough.

## Anti-goals (what would make this a failure even if it technically works)

* A Lab that shows a green badge when **nothing ran** or when too few cases ran. "Not run" and "too few cases" must be said, never rounded up.
* A result shown for a different version than the one tested, or presented as current when a newer version exists.
* Spending the model quota without the person having seen the number of calls first, or twice by a double click.
* Showing a model's reply as markup. Replies are text; the page renders them as text only.
* Hiding a failure to read the library or the runs behind an empty list.

## Constraints (from CLAUDE.md and the existing code)

* Models answer, code judges. Every model call names its task (`Task.ACT` is what `run_eval` already uses) and goes through the AI service.
* Tests are offline: `MockProvider`, inline jobs. No test reads the real `.env`.
* The library stays files with SHA-256 manifests. A new version is made only through `import_source` (static checks first, refused if one fails).
* A run is a row in the database (a migration, not `create_all`); a restart marks unfinished runs failed and retryable (`recover_interrupted`).
* The Lab works in the hosted version too: it reads the server's library and asks the server's model, like a build does. (Nothing reads a folder.)

## Approaches considered (what the Lab does for skills that cannot be run today)

| | What | Trade-off |
|---|---|---|
| **A** | Run what can be run; for the rest give the reason in plain words. | Smallest and honest, but on the three skills above it says "not run" three times. |
| **B** | A plus a button that has the model write test cases for old skills and saves them as a new version. | Makes old skills runnable fast, but the model then tests its own work: the weakness `evaluate.md` already names. For a hand-imported skill with no `spec.json` it would write tests from `SKILL.md` alone. |
| **C** | A plus an editor where the person writes the cases. | Most work in the page, but the tests are the person's own. Works for every text-only skill, with or without a spec. |

**My pick: A, then C** (A is slice AD, C is slice AE). B is left out on purpose: it would make the headline number look better without making it more trustworthy.

## Slice AD: running and reading

### Data

A table `eval_runs` (migration `0005`): `id` (32 hex), `created_at`, `updated_at`, `status` (`working`, `done`, `failed`), `kind`, `name`, `version`,
`content_hash` (of the version tested), `runs` (repeats per case, 1 to 5), `baseline` (also run without the skill), `cases_total`, `cases_done`, `result` (JSON),
`error`, `retryable`. Indexed on `status` and `name`. `recover_interrupted` marks a `working` run failed and retryable.

### The engine (small changes to `evaluate/runner.py`)

* `plan_cases(skill, max_cases)` returns the runnable cases and the skipped ones with their reasons. `run_eval` uses it (same behaviour as before); so does the preview,
  so what the page lists is, by construction, what will be run.
* `run_eval(..., on_case=callback)` calls back after each case with (done, total), for the progress strip. Default `None`: nothing changes for the command line.
* `EvalReport.outcome()` returns a code (`helped`, `adds_nothing`, `no_difference`, `worse`, `too_few`, `with_only`, `not_run`), and `verdict()` is written from it,
  so a page never parses English to learn the result. The wording of `verdict()` does not change.

### The service (`builder/evals.py`) and the API (`api/evals.py`)

* `GET /api/evals/preview?name=&version=&kind=`: no model. Returns whether it is runnable and **why not** if it is not, the cases that would run (message and checks),
  what is skipped, the skill's token cost, and the number of model calls for 1 repeat with and without the baseline.
* `POST /api/evals` `{name, version?, runs, baseline, kind}`: refuses (400) what the preview calls not runnable, so a run is never started that can only say "not run".
  One run per skill version at a time: a second click gets the one that is working. 201 with the run.
* `GET /api/evals?name=&version=` the runs, newest first, without their results but with a summary (outcome, the two counts, the calls); `GET /api/evals/{id}` the whole run;
  `POST /api/evals/{id}/retry` for a failed one. A missing model is the same failed-and-retryable run the ideas use.
* The stored result is a **plain view**, not a pickled report: the outcome code, the verdict text, the counts, the limits sentence, the cases, and per run the reply
  (cut at 3,000 characters, and marked when cut) with each check's kind, value, reason, pass and detail.

### The page (`/testing`, a Testing Lab entry in the menu, a "Test this skill" link on a skill's page)

A skill picker and a version picker; **What would run** (the cases and their checks, or the reason it cannot run); the cost in model calls with a repeat choice (1, 3, 5)
and the "also without the skill" box ticked by default; **Run the tests**; a progress strip (Test 2 of 3); the **result**; and **Earlier runs** for that skill.
The result card says the outcome in words with a tone (helped = good; adds nothing = warning, with its token cost; no difference = neutral; worse = bad; too few = neutral),
shows "with the skill n of m / without it n of m", and one row per case with both sides, each failed check in words, and the replies behind a disclosure.
A single repeat says that single runs vary. A run for an older version than the latest says so. The logic that decides tone, wording, estimates and staleness is pure (`lib/testing.ts`).

### What is left to the builder

The exact words; layout details; whether the pickers remember the last skill (not needed); the shape of the per-reply view as long as it carries what is listed above.

## Slice AE: the person's own test cases

* A **Test cases** section on the Lab page for the chosen version: the current cases, add / edit / remove, and **Keep as a new version**.
  A case is a name, a kind (positive, negative, edge), the message to send, and 1 to 3 checks, each one of the seven kinds with a value and the reason it is there.
* `POST /api/library/{name}/tests` `{base_version, cases, note?}` (**a POST, not the PUT first written here**: this API's CORS policy allows only GET, POST and DELETE, so a browser could not send a PUT, and the API's other writes are POSTs). The server validates every case with the same rules the harness uses (`assertion_problem`), writes
  `tests/cases.json` into a copy of **the latest version's files** and keeps it only through `import_source`, so the static checks run and a refusal leaves the library untouched.
  `base_version` must be the latest (409 otherwise): a person never silently drops a newer change. Identical content makes no new version.
  Found while building it: the definition file `skill.sdm.json` holds a second copy of the tests (a rebuild renders from it), so a save updates **both**, and stops if the definition cannot be read rather than leave two copies that disagree. `GET /api/library/{name}/tests` lists every case of a version, the ones that cannot be run too, so they can be fixed.
* Limits to say in the page: tests a person writes still only reach what the seven checks can say; an edit makes a new version (older ones are kept, as everywhere).

## Done means

Tests pass offline (and the browser suite for the new pages), every rule broken once on purpose and caught by a test, a real run with the configured model on a skill
saved on this machine, README, `docs/roadmap.md`, `docs/testing-lab.md` updated, then committed and pushed.
