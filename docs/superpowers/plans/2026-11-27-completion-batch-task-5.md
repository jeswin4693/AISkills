# Completion batch, task 5: the behaviour scan on a web page — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The third differentiator, the behaviour scan (command line only until now), gets a page and an API: pick a skill or agent and a version, see the tasks that would run and the most model calls BEFORE anything is asked, run it as a polled background run, and read the verdict, every finding with its transcript, what did not run and the limits sentence. Never "safe".

**Architecture:** A new table `scan_runs` (migration `0010`) and `builder/scans.py::ScanRuns`, a near copy of the Testing Lab's `EvalRuns` (preview, start with the second-click rule and admission, get, list, retry, a background `_execute`), around the existing engine `canary/runner.py` (`load_instructions`, `preview`, `run_canary`, `CanaryReport`). `api/scans.py` exposes it; the web page `/scan` mirrors the Lab page. Scan runs join every place that already knows about "work running": the per-person active limit, `Builder.working_for`, restart recovery, the erase of a person's data and the clean-up when a library entry is deleted (the earlier review required the last three).

**Tech Stack:** Python, FastAPI, SQLAlchemy + Alembic, pytest, `MockProvider`; Next.js, TypeScript, vitest. No new library.

**Spec:** [docs/superpowers/specs/2026-11-26-completion-batch-design.md](../specs/2026-11-26-completion-batch-design.md), item 2, its Anti-goals ("A scan that shows another person's run or spends someone else's model") and Review focus 3.

## Global Constraints

- Run backend tests from `backend/` with `C:\dev\venvs\aiskills\Scripts\python.exe -m pytest -q -p no:cacheprovider`; web from `frontend/` (`npm test`, `npm run typecheck`). Offline: `MockProvider` only.
- **No code decides "safe".** The outcome is a code from `CanaryReport.outcome()` (`flagged|unclear|caution|incomplete|nothing_observed|not_run`); words are written from it, never the other way round; the page never uses the word "safe" as a claim and always shows the limits sentence (`canary.runner.LIMITS`). An unfinished run is never shown as clean.
- **Models answer, code judges.** The page shows what the engine's code found; it asks no model anything itself.
- **A person's run is theirs.** Another person's run is a 404 identical to a missing one; a run spends the model of the person it belongs to (`ModelAccess.provider_for`: their own key, or the shared model within their allowance) and counts toward their "runs working at once".
- **Skills and agents only** (what `load_instructions` accepts); a plugin or an MCP server is refused with the engine's own sentence. A scan reads the library only, never a folder, so it is available in the hosted version.
- Text a model produced (replies, tool calls, results) is shown as plain text only, never as markup; a stored result stays small (long text cut and marked).
- No absolute path or key in any answer. Commit messages end with `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`.

## Review Focus

1. Another person's scan run, read, retried or listed, is a 404 identical to one that never existed; a scan of another person's library entry is the same 404 as a missing one.
2. A scan's model calls are recorded for the person it belongs to and count toward their allowance; a scan counts toward "runs working at once" (a person at the cap is refused with a 429, and a build is refused while a scan works).
3. A scan run is counted by `Builder.working_for` (so a delete and an erase wait for it), removed by the erase of its person, removed when its library entry is deleted (a new entry of that name must not show the old verdict), and recovered after a restart (a run left "working" becomes failed and retryable).
4. The page never says "safe", shows the limits sentence with every result, shows an unfinished run as unfinished, and shows what did not run.
5. A hostile skill or model cannot make the page run its text: transcripts are plain text; a stored result is bounded in size.

---

### Task 1: Storage, and joining the places that know about running work

**Files:**
- Modify: `backend/skillforge/db/models.py` (`ScanRun`), `backend/skillforge/db/__init__.py` (export), `backend/skillforge/db/database.py` (`recover_interrupted`), `backend/skillforge/builder/limits.py` (`PersonSpace.active`), `backend/skillforge/builder/service.py` (`working_for`; `drop_lab_runs` becomes `drop_runs_of`), `backend/skillforge/builder/erase.py` (`scan_runs` in the report), `backend/skillforge/api/app.py` (the delete route calls `drop_runs_of`), `backend/skillforge/api/admin.py` is unchanged (it returns the report as it is)
- Create: `backend/skillforge/db/migrations/versions/0010_scan_runs.py`, `backend/tests/test_scan_storage.py`
- Modify: `backend/tests/test_erase_person.py`, `backend/tests/test_library_delete_api.py`, `backend/tests/test_person_limits.py` (small additions)
- Modify: `frontend/src/lib/types.ts` (`EraseReport.scan_runs`), `frontend/src/lib/remove.ts` (`erasedNotice` counts them), `frontend/src/lib/remove.test.ts`

**Interfaces:**
- Produces: `ScanRun` (table `scan_runs`): `id` str32 pk, `created_at`, `updated_at`, `status` (working|done|failed, indexed), `kind` str16 (`skill` or `agent`), `name` str64 (indexed), `version` int, `content_hash` str64, `runs` int (each task is run this many times), `scenarios` int (the most tasks), `control` bool (also run without the skill), `draft` bool (a model drafts one task from the description), `tasks_total` int, `tasks_done` int, `result` JSON nullable, `error` text, `retryable` bool, `user_id` str32 (indexed, default `local`).
- Produces: `Builder.drop_runs_of(user_id: str, kind: str, name: str) -> int` (replaces `drop_lab_runs`: deletes that person's `EvalRun` and `ScanRun` rows of that entry and kind, returns how many); `EraseReport.scan_runs: int`; the erase answer gains `scan_runs`.
- Changes: `PersonSpace.active` and `Builder.working_for` also count `ScanRun` rows with status `working`; `Database.recover_interrupted` also marks working `ScanRun` rows failed and retryable (the message "The server stopped while this was running. Retry to run it again.") and its return value counts them; `erase_person` deletes the person's `ScanRun` rows.

- [ ] **Step 1: Write the failing tests.** `tests/test_scan_storage.py`: `test_the_migration_creates_scan_runs_with_its_indexes` (migrate("0009"): no table; migrate(): the columns above, the indexes on status, name and user_id); `test_a_scan_run_left_working_is_failed_and_retryable_after_a_restart` (also: a finished one is untouched, and `recover_interrupted()` counts it). In `test_person_limits.py`: `test_a_working_scan_run_counts_toward_the_active_cap` (like the Lab one: with `max_active=1`, a working scan run makes a build start a 429 `active`). In `test_library_delete_api.py`: `add_scan_run(w, uid, rid, status="working", name="foo", kind="skill")`; `test_working_for_counts_builds_lab_runs_and_suggestion_runs...` gains a working scan run (the totals change by one); the lab-runs deletion test gains scan runs: deleting skill `foo` removes that person's scan runs of skill `foo` and leaves other names', other kinds' and other people's. In `test_erase_person.py`: `seed_person` adds a scan run; `counts` gains `"scans"`; every exact report dict gains `"scan_runs"` (1 for a seeded person, 0 for the second erase); a working scan run refuses an erase (the `adder` parametrization gains `add_scan_run`). `remove.test.ts`: `erasedNotice` counts scan runs ("1 behaviour scan"); both fixtures gain `scan_runs`.
- [ ] **Step 2: Run to see them fail** (no table, no `scan_runs` key, `AttributeError: drop_runs_of`).
- [ ] **Step 3: Implement** the model, the migration (create table; indexes `ix_scan_runs_status`, `ix_scan_runs_name`, `ix_scan_runs_user_id`; downgrade drops them then the table), the export, the four hooks, the rename, `scan_runs` in the erase report and the web words.
- [ ] **Step 4: Run** the new and changed files, `tests/test_builder.py tests/test_admin_block.py tests/test_library_delete.py`, and `npx vitest run src/lib/remove.test.ts`. Expected: pass.
- [ ] **Step 5: Commit** `Slice AK task 5a: scan runs are stored, counted as running work, recovered after a restart, erased and removed with their entry`.

---

### Task 2: `ScanRuns`, the service

**Files:**
- Create: `backend/skillforge/builder/scans.py`, `backend/tests/test_scan_runs.py`
- Modify: `backend/skillforge/builder/service.py` (a `scans` property next to `evals`), `backend/skillforge/builder/__init__.py` if it exports `EvalRuns`

**Interfaces:**
- Consumes: `canary.instructions.load_instructions`, `canary.runner.preview / run_canary / LIMITS`, `ScanRun`, `PersonSpace.admit/lock`, `ModelAccess.provider_for`.
- Produces in `builder/scans.py`: `RUN_CAP = 3`, `SCENARIO_CAP = 6`, `DEFAULT_SCENARIOS = 5`, `report_view(report: CanaryReport) -> dict` (the report as plain data: `to_dict()` plus `limits`; every tool call's text cut to 500 characters, every tool result to 600, a reply and a message to 2,000, each cut marked `…`), `run_view(row: ScanRun, *, full: bool = True) -> dict` (`id, status, kind, name, version, tag, content_hash, runs, scenarios, control, draft, progress: {done, total}, error, retryable, created_at, updated_at`, plus `result` when full, else `summary: {outcome, calls, findings, finished, total} | None`, where `findings` counts observations of severity medium or worse in the with-skill runs and `finished` counts finished runs), and `class ScanRuns(db, runner, provider_for, library, library_for=None, space=None)` with `preview(name, version=None, kind="skill", user=LOCAL_USER_ID, runs=1, scenarios=DEFAULT_SCENARIOS, control=True, draft=True) -> dict`, `start(name, version=None, runs=1, scenarios=DEFAULT_SCENARIOS, control=True, draft=True, kind="skill", user=LOCAL_USER_ID) -> dict`, `get(rid, user=LOCAL_USER_ID) -> dict`, `list(name=None, version=None, limit=50, user=LOCAL_USER_ID) -> list[dict]`, `retry(rid, user=LOCAL_USER_ID) -> dict`.
- `preview` answer: `name, kind, version, tag, content_hash, tasks: [{id, message, source}]` (fixed tasks, the entry's own test messages; a task a model would draft is not in it and `draft` says one more call is made), `runs, control, draft`, `max_calls` (the engine's most, plus 1 when `draft`), `declared` (the tool kinds it declares or `null`), `scripts` (listed, never run), `limits: {max_runs, max_scenarios, default_scenarios}`, `limits_text` (the engine's `LIMITS`). A kind other than skill or agent, or an entry with no `SKILL.md`/`AGENT.md`, is a `BadRequest` with the engine's sentence.
- `start` follows `EvalRuns.start`: the person's own library, the second click on a running scan of the same entry and version (their own) returns that run, admission counts the person's running work, `tasks_total = scenarios planned × runs`, the work is submitted to the runner. `_execute` never raises: `ProviderError` → failed, retryable unless its kind is one of `NOT_RETRYABLE` (as the Lab); library/builder errors → failed; anything else → failed with "Unexpected error (<Type>). The server's log has the details." (no text that could hold a path). `retry` re-runs a failed one under the same admission.

- [ ] **Step 1: Write the failing tests** (`tests/test_scan_runs.py`, HTTP not needed yet: the `ScanRuns` object through `w.builder.scans` on the isolation `World` with the canary tests' scripted `Agent`): preview lists the fixed tasks and the entry's own test messages, `max_calls` arithmetic, asks no model (the agent saw no prompt), refuses a plugin, an unknown kind and an entry with no instructions; start → done with `outcome == "nothing_observed"` for an agent that finishes at least three tasks, progress done == total, the result holds runs with turns, the verdict never contains "safe" as a claim and the limits text is present; a flagged outcome for an agent that reads `.env` then sends what it read; an unfinished run (the agent never says done) is `incomplete`, never `nothing_observed`; failure: a `ProviderError` on the first step → failed and retryable, a refused kind → not retryable, then retry after the model is fixed ends done; the second click returns the running run (runner parked); another person's run: get/retry/list are a 404/empty identical to a missing one, preview of another person's entry is the same 404; admission: with `max_active=1` a second scan is a `LimitReached("active")`; the model calls are recorded as usage rows of the person the run belongs to; the stored result is bounded (a 5,000-character tool result is cut to 600 and marked).
- [ ] **Step 2: Run to see them fail** (`ModuleNotFoundError: skillforge.builder.scans`).
- [ ] **Step 3: Implement** `scans.py` and the `scans` property.
- [ ] **Step 4: Run** `tests/test_scan_runs.py tests/test_canary_runner.py tests/test_evals.py`. Expected: pass.
- [ ] **Step 5: Commit** `Slice AK task 5b: ScanRuns, the behaviour scan as a kept, polled run`.

---

### Task 3: `api/scans.py`

**Files:**
- Create: `backend/skillforge/api/scans.py`, `backend/tests/test_scan_api.py`
- Modify: `backend/skillforge/api/app.py` (include the router)

**Interfaces:**
- Produces: `GET /api/scans/preview?name=&version=&kind=&runs=&scenarios=&control=&draft=`, `POST /api/scans` (201) with `{name, version?, runs (1..3), scenarios (1..6), control, draft, kind}`, `GET /api/scans?name=&version=`, `GET /api/scans/{rid}`, `POST /api/scans/{rid}/retry`. The static `preview` path is registered before `/scans/{rid}`. The person is `user_id(request)`. Out-of-range numbers are a 422.

- [ ] **Step 1: Write the failing tests** (`tests/test_scan_api.py`, the isolation `World` over HTTP): preview/start/get/list/retry for a person and for the owner; a second person gets 404s identical to missing ones for get, retry, and for preview or start of an entry they do not have, and an empty list; 422 for `runs=0`, `runs=4`, `scenarios=0`, `scenarios=7`; the routes work in the hosted version (a person's own model, no folder is read); a signed-out request is refused as every route is.
- [ ] **Step 2: Run to see them fail.** Expected: 404 on the routes.
- [ ] **Step 3: Implement** the router and register it.
- [ ] **Step 4: Run** `tests/test_scan_api.py tests/test_scan_runs.py tests/test_api.py`, then the whole backend suite. Expected: pass.
- [ ] **Step 5: Commit** `Slice AK task 5c: /api/scans, the behaviour scan over HTTP`.

---

### Task 4: The web page

**Files:**
- Create: `frontend/src/lib/scan.ts`, `frontend/src/lib/scan.test.ts`, `frontend/src/lib/useScanRun.ts`, `frontend/src/components/scan/ScanPage.tsx` (picker, preview, run, history), `frontend/src/components/scan/ScanResult.tsx`, `frontend/src/app/scan/page.tsx`
- Modify: `frontend/src/lib/types.ts`, `frontend/src/lib/api.ts` (`scanPreview`, `startScan`, `scanRuns`, `scanRun`, `retryScan`), `frontend/src/components/AppShell.tsx` (a nav entry "Behaviour Scan")

**Interfaces:**
- Produces in `lib/scan.ts`: `outcomeInfo(code: string): { tone: Tone; title: string; summary: string }` for the six codes (flagged → bad "Flagged", unclear → warn "Unclear", caution → warn "Caution", incomplete → warn "Too little ran", nothing_observed → neutral "Nothing observed", not_run → neutral "Not run"; a code it does not know → neutral with the code itself; **no title or summary ever says "safe"**; `nothing_observed`'s summary says "evidence, not proof"); `maxCallsText(max: number, draft: boolean): string`; `runChoices(max: number): number[]`; `severityTone(severity: string): Tone`; `taskState(run: ScanRunTask): "finished" | "stopped" | "unfinished"` (an unfinished run is never shown as finished); `findingsOf(result: ScanResult): Finding[]` (every observation of the with-skill runs with its task, step and detail, most serious first); `controlSummary(result, scenarioId: string): string | null`; `shortTranscript(turn)` helpers as needed; `pollAfterAnswer` is reused from `lib/testing`.
- `useScanRun(id: string | null)` mirrors `useEvalRun` (poll every 1.5 s while working, `adopt`, `stalled`, `check`).
- UI: the page keeps `?kind=&name=&version=` in the address; a **kind** select (skill, agent), the entry and the version; a **preview card** (the tasks that would run with their sources, the most model calls, what it declares, scripts that are listed and never run, the limits sentence) and options (repeat 1–3, tasks 1–6, "also run without it", "let a model draft one task"); a **Run** button disabled with no model or while a run works; progress; the **result**: the verdict banner (`outcomeInfo`), the engine's verdict sentence, the limits sentence, a "What did not run" list, then every task with its transcript as plain text (`<pre>` blocks, never HTML), its findings with severity badges, its final answer and the control's finding; a list of earlier runs; a retry button for a retryable failure. Buttons at least `min-h-11`.

- [ ] **Step 1: Write the failing tests** (`scan.test.ts`): `outcomeInfo` for all six codes and an unknown one (and a loop asserting no title or summary matches `/\bsafe\b/i`), `nothing_observed` says "evidence, not proof"; `maxCallsText`; `runChoices`; `severityTone`; `taskState` for finished, stopped early (error) and out of steps; `findingsOf` orders most serious first and ignores the controls; `controlSummary`; the five API calls (methods, URL-encoded parameters, bodies, the server's message raised on a 409/429).
- [ ] **Step 2: Run to see them fail.**
- [ ] **Step 3: Implement** the logic first, then the hook, the components and the nav entry.
- [ ] **Step 4: Run** `npm test` and `npm run typecheck`. Expected: all pass.
- [ ] **Step 5: Commit** `Slice AK task 5d: the Behaviour Scan page`.

---

### Task 5: Docs and the batch's own checks

**Files:** Modify `docs/canary-scan.md` (the page and the API), `docs/api.md` (the five routes), `docs/ui.md`, `docs/person-limits.md` (scans count toward "runs at once"), `docs/data-removal.md` (scan runs are now covered by erase, `working_for` and the delete clean-up), `docs/database.md` (`scan_runs`, migration 0010).

- [ ] **Step 1:** write the doc changes; in `canary-scan.md` say what the page shows, that it never says "safe", the caps (3 repeats, 6 tasks) and that a scan counts as running work.
- [ ] **Step 2:** run the whole backend suite with `-rs`, the web tests and the type check; expected: all pass, the same 4 symbolic-link skips.
- [ ] **Step 3: Commit** `Slice AK task 5e: docs for the behaviour scan page`.

---

### Deliberate breaks (after task 3; restore each)

1. `ScanRuns.get` ignores the owner → another person's run is readable; the isolation test fails.
2. `ScanRuns.retry` ignores the owner → the isolation test fails.
3. `ScanRuns.list` ignores the owner → the isolation test fails.
4. `_execute` uses the server's model for a person (`provider_for` replaced) → the usage-rows-for-that-person test fails.
5. `start` skips `_admit` → the cap test fails.
6. `PersonSpace.active` stops counting scan runs → the cap test fails.
7. `Builder.working_for` stops counting scan runs → the work-running tests fail.
8. `erase_person` forgets scan runs → the erase test fails.
9. `drop_runs_of` forgets scan runs → the delete test fails.
10. `recover_interrupted` forgets scan runs → the restart test fails.
11. `report_view` stops cutting a long tool result → the bounded-result test fails.
12. `_execute` reports an unfinished run as done with outcome `nothing_observed` → the unfinished-run test fails (the engine decides: this proves the page's service stores what the engine says).
13. The second-click rule ignores the person → the second click can return somebody else's run; the isolation test fails.

### After the tasks

No separate independent review: the approved design schedules one review of the whole batch (task 6), and its focus names the scan (point 3). The browser run of the new page and of the two dialogs of task 4 also happens in task 6.
