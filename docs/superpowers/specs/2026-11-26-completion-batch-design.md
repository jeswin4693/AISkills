# The completion batch (slice AK): six items, design and plan

Status: **approved by the owner's "Yes, start with items 1 to 6"** (after the owner chose to finish the planned list before deploying). The shapes and numbers are my calls, each marked *my call*.

## Why
The owner wants the planned product finished before it is put online. These six are the small and medium items on that list; the large ones (a function-level graph, Node servers inside plugins, Streamable HTTP) come after.

## The six items, as built
1. **The six small deferred fixes** of slice AJ's review. (a) A turned-off person's refused sign-in must not rewrite their record (look the person up by Google id and check the block BEFORE `upsert_google`). (b) The People page says "Last sign-in", not "Last seen", because that is what the field is. (c) The People list shows turned-off people FIRST, then the latest sign-in, and says "showing N of M" when it is capped at 1,000. (d) The sign-in middleware asks the database (is this person turned off?) in a thread pool, not on the event loop. (e) The browser-check launcher makes its Builder through `builder_options` (overriding only the model options), so no place that makes a hosted builder can forget the limits. (f) An error from the engine's own guards (`LLM_MAX_CALLS`, `LLM_MAX_INPUT_TOKENS`) no longer names owner settings when it reaches a person who is on their own key.
2. **A web page and API route for the behaviour scan** (the third differentiator, command line only until now). A polled run like the Testing Lab: pick a skill or agent and a version, see the tasks that would run and the most model calls BEFORE anything is asked, run it, read the verdict (a code from `CanaryReport.outcome()`, never "safe"), each finding with its transcript, what did not run, and the limits sentence. Per person, a table `scan_runs` (migration 0009), `builder/scans.py`, `api/scans.py`, a page `/scan`. *My call:* a scan counts toward the "runs working at once" limit and the model allowance like any run; skills and agents only (what `load_instructions` accepts); the person's own model is used.
3. **The builder keeps an answered checklist item between rounds.** The requirement is recomputed from all the person's words each round, so a model quirk could lose an item that was verified earlier (a real build lost "constraints"). The partial requirement is now kept on the session; in the next round an item the new extraction fails to back is kept from the previous round when its quote is still in the person's words (words only ever grow). The note says so.
4. **Deleting.** (a) A person (or the owner) can **delete a skill, agent, plugin or MCP server from their own library**: every version, with its backups; the person types its name to confirm; it cannot be undone and the page says so; plugins already built keep their own copies. (b) The owner can **erase a person's data** from the People page: their folder, their builds and their rows (builds and jobs, suggestion runs, Testing Lab runs, scan runs, their saved model key). *My calls:* it is allowed only for a person who is turned off and has nothing running; the owner types the person's address to confirm; the account row and the usage rows are KEPT (the rows are the allowance's ledger, and erasing them would let a person erase and re-register to reset their allowance), so the person is still turned off afterwards and, if turned back on, starts empty.
5. **The two open risks of the GitHub-link slice.** (a) Pruning can delete a snapshot another request is reading: opening a snapshot now marks it used, and pruning skips any snapshot used in the last 15 minutes (a long read is not cut off; a few extra copies may live a little longer). (b) A data folder inside a git work tree lets `git ls-files` and `git log` see the parent repository: for any folder inside the data folder, git is told not to look above it (`GIT_CEILING_DIRECTORIES`); a folder the person points at themselves is untouched, so a subfolder of a repository still works.
6. **The usage clean-up.** There is no usage page or route (the words only ever appeared in my "next" lists), so I read this as: the usage table (`model_calls`) grew forever, and since a discarded build now keeps its rows it grows faster. Rows older than `SKILLFORGE_USAGE_KEEP_DAYS` (default **90**, `0` = keep forever) are deleted once at start and then at most once a day; the daily allowance needs only today's rows, so nothing it counts is touched. *My call, stated plainly to the owner.*

## Non-goals
No change to how the allowance is counted, no per-person custom limits, no deleting an account row, no cleaning of the owner's data by the owner's own click beyond a skill.

## Anti-goals (a failure even if it "works")
- A delete that reaches another person's files or the owner's, a path built from anything but a name the library checked or an id this server made, a delete that follows a link out of the folder, or one that runs while a build of that person is working.
- A confirmation that can be skipped by a script (the server checks the typed name or address, not the page).
- A scan that shows another person's run or spends someone else's model.
- A "usage clean-up" that deletes today's rows (it would hand allowance back).

## Review focus
1. Every delete: the exact set of files and rows it touches, for a name or id that is odd (case, separators, `..`, a link inside the folder), and for another person's.
2. Erasing a person who is not turned off, or has a build working: refused; erasing keeps the account row and every usage row.
3. A scan run read, retried or listed by another person: 404; a scan's model calls counted against the person's allowance and "runs working".
4. The kept checklist item: an item whose quote is NOT in the words must never be kept; an item the model did not back must be kept only from the previous verified spec.
5. Pruning a snapshot in use: skipped; the usage retention never touches today's rows.

## Tasks (each test-first, each committed)
1. The six fixes (item 1). 2. Item 5 and item 6. 3. Item 3. 4. Item 4. 5. Item 2. 6. Verification, deliberate breaks, one independent review of the whole batch, docs, push.
