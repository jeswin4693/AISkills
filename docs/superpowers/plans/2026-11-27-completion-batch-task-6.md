# Completion batch, task 6: verification, the browser, and the review of the rest of the batch — record

Task 6 had no step-by-step plan: the [design](../specs/2026-11-26-completion-batch-design.md) lists it as "verification, deliberate breaks, one independent review of the whole batch, docs, push". This is what was done and found. Tasks 1 to 5 have their own plans and outcomes ([task 2](2026-11-27-completion-batch-task-2.md), [task 3](2026-11-27-completion-batch-task-3.md), [task 4](2026-11-27-completion-batch-task-4.md), [task 5](2026-11-27-completion-batch-task-5.md)).

## The browser

Until now the two delete dialogs (task 4) and the Behaviour Scan page (task 5) had only unit tests and a type check. Both browser scripts now drive them in Edge:

- **The main suite** (`frontend/e2e/run.mjs`) gained 10 steps, **110 of 110** now. *The Behaviour Scan* (7): the page and its menu entry; choosing a skill shows the tasks and the most model calls before anything is asked; the options change them still without asking a model; a run shows progress, then a result that says evidence-not-proof, shows the limits and never says "safe"; an earlier scan is listed and a reload shows the latest again; a skill that makes the model read a secret and send it away is **flagged**, with the finding, the control and the steps; every step is shown as plain text (a reply holding `<img onerror>` stays text and nothing runs). *Deleting a library entry* (3): the Danger zone says what goes and that it cannot be undone, a part of the name is not enough, the exact name deletes it from the library and from the server, and the **server itself** refuses a delete without the right typed name.
- **The fake model** of that suite (`e2e/mock_server.py`) learned the scan's step format (honest for an ordinary skill; for a skill marked `[scan-bad]` it reads `.env` and sends what it found to a stranger, knowing the secret only from the tool result like a real model) and the task drafter. No key, no network.
- **The phone-size check** (`e2e/hosted-phone.mjs`, `e2e/hosted_server.py`) gained 17 checks, **62 of 62** (it ran before the review's fixes, which touched only scan files and not the flow it drives): the owner's **Erase** dialog at phone size (44 px targets, 16 px text, fits the width, the button stays off until the address is typed, a different address does not enable it, the right one in any case does) and, through the real page, API and disk, that the person's skill is **really gone from the server** afterwards and the account stays turned off.
- **A deliberate break in the browser:** the scan page was made to render a model's reply as HTML (`dangerouslySetInnerHTML`); the suite gave **109 passed, 1 failed**, exactly the plain-text step. The file was restored from git.

## The independent review (tasks 3, 5 and 6)

A fresh reviewer on the most capable model, with probes, read what no review had read: the kept checklist item (task 3), the whole behaviour-scan feature (task 5), the browser scripts, and how scans touch task 4's delete and erase. **No Critical, 3 Important, 11 Minor.** Task 3 held its rule, scan isolation, model choice, limits, locking and removal paths were right, and the page rendered all model text as plain text. The Important findings were all about the page telling the person something untrue:

- **I1, fixed test-first:** a skill's scan page could show an agent's verdict (libraries are per kind, so a skill and an agent can share a name and a version number, and the scan list had no `kind`). The list is asked for the kind, and the page also ignores a scan that is not about its own kind, entry and version.
- **I2, fixed test-first:** "what would run" and "at most N model calls" were not true with the default options: with a drafted task the engine plans up to **three** drafted tasks that **replace** fixed ones (the page said "one more task"), and the ceiling was too low at six tasks (61 shown, 73 spent). The preview now gives the real ceiling (`max_tasks`, `max_calls`), a test proves a worst-case run reaches it exactly and never passes it (retries aside), and the words say so.
- **I3, fixed test-first:** the "Flagged" headline always said the skill is the likely cause, even when no control run was made and the engine's own sentence said the opposite. It now blames the skill only when a control was run.
- **Regraded by effect and fixed in the same pass** (the reviewer said they close the last places where an unfinished or unsanitised thing reads as clean): **M1** a control that did not finish is never read as "nothing observed", and all control runs of a task are summarised; **M2** "nothing observed" is shown only for a task run that finished; **M3** a stored result writes control characters, terminal escapes and direction overrides out visibly (a NUL breaks some databases; a right-to-left override can make a web address read differently).
- **M11 (stale statements), fixed in the docs:** `CLAUDE.md` still said the scan was command line only and listed its page under "Next"; `docs/canary-scan.md` said the page had not been run in a browser.

**Minor, deferred (not fixed):**
1. The stored result is bounded per field, not in total; scan rows are never capped or counted against anything; the list loads up to 50 full results to build its summaries (the Testing Lab has the same pattern).
2. The cost line can be stale for a moment after an option changes (the Run button is not disabled while the new preview loads).
3. A second click with different options silently returns the scan already working, without saying the new options were not used.
4. A narrow race between a delete and a scan start can leave a failed row with the old content hash, which would be listed under a new entry of that name (compare the hash in `_execute`, or drop under the start lock).
5. The two checkboxes and the "Show the steps" summary are under 44 px tall; the flagged headline says "this skill" for an agent.
6. A browser step that asserts nothing (`getByRole("heading", { name: "What did not run" }).waitFor().catch(() => {})`).
7. The phone-width check of `/scan` may measure before the result has arrived, and "never says safe" is asserted on the clean result only, not on the flagged page.

## Final numbers (after the fixes)

Backend **3,967 passed / 4 skipped / 0 failed** (the 4 are symbolic-link tests this account cannot run), web **470 passed** with a clean type check, the main browser suite **110 of 110**, the phone check **62 of 62** (before the fixes, unchanged flow). Deliberate breaks across the batch: 9 (task 1) + 12 (task 2) + 8 (task 3) + 15 (task 4) + 14 (task 5) + 1 in the browser, all caught. Independent reviews: task 2 (1 Important), task 4 (2 Important), tasks 3, 5 and 6 (3 Important, and three Minor of the same family), each fixed test-first.

## Rulings made

1. **The review's scope was tasks 3, 5 and 6** (and how they touch task 4), because tasks 2 and 4 had their own independent reviews. Cost if wrong: a defect in the part of task 4 that task 5 did not touch was already covered by task 4's review.
2. **Three Minor findings were regraded to Important by their effect and fixed with the Important ones** (M1, M2, M3: an unfinished control or unsanitised text reading as clean); the other seven stay deferred, listed above. Cost if wrong: a fix pass slightly larger than the labels asked for.
3. **The phone check was not re-run after the fixes**: they changed only scan files, and the check drives the People page and the Erase dialog, which did not change. Cost if wrong: none for what it checks.
4. **The browser suites ran on side ports** (3100 and 8100, not 3000 and 8000), and the UI's default build was restored afterwards, so the user's own `.next` does not hold a test build. Nothing of the user's was touched.
5. **Nothing was pushed by this task.** The README, the roadmap and `CLAUDE.md` were updated; the push is the user's call.

## Not tried

A real model on the scan page (a scripted one was used), a real phone, a real Google sign-in, a real host, the command-line delete (there is none).
