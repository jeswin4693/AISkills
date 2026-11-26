# Development log: the Testing Lab, your own test cases, an independent review, and the Quality Report (2026-11-25)

What was developed in one working session, in order, with what was checked and what was learned. The per-slice details are in each slice's own document; the roadmap ([roadmap.md](roadmap.md)) has the one-row summaries.
The session began at commit `4e31e6f` (the Dashboard, slice AC) and ended with all nine pages of the original vision built.

## At a glance

| Step | What | Commit | Backend tests (collected) | UI unit tests | Browser steps | Deliberate breaks caught |
|---|---|---|---|---|---|---|
| start | the Dashboard (slice AC) | `4e31e6f` | 2,842 | 259 | 76 | |
| **AD** | **The Testing Lab**: run a skill's own test cases with and without the skill | `ffb8947` | 2,886 | 294 | 86 | 36 |
| **AE** | **Your own test cases**: write cases in the page, keep them as a new version | `1356b78` | 2,930 | 322 | 92 | 35 |
| **Review** | an independent review of AD and AE: 0 Critical, 5 Important, 9 Minor; 12 fixed, 2 documented | `d5fe0b9` | 2,984 | 332 | 92 | 19 |
| **AF** | **The Quality Report**: one page that says what the checks found, what did not run, what to do next | see `git log` | 3,013 | 350 | 100 | 28 |

## AD: the Testing Lab ([testing-lab.md](testing-lab.md))

The Dashboard said a skill had passed *static* checks and that "whether it works is what the Testing Lab is for", so the Lab was built next. A person chooses a skill and a version, sees **what would run and how many model calls it costs before anything is asked**, runs the skill's own test cases against a model **with the skill and without it**, and code (never a model) grades every reply.
The result says whether the skill **helped, adds nothing, made things worse**, or had **too few cases**, shows each failed check in numbers ("the first line is 101 characters, the limit is 50") and keeps the replies. It is a polled run kept in the database (`eval_runs`, migration 0005); a result is about the version it tested and says when a newer one exists; a skill that cannot be run (no cases, or it needs tools) says why and offers no button.
**Found on the author's machine:** none of the three saved skills could be run (one needs tools, one had a case with no message, one had no cases), which shaped the next slice. **A real run** with the configured model through the real API: 3 of 3 with the skill, 1 of 3 without.

## AE: your own test cases ([testing-lab.md](testing-lab.md))

A person can write test cases on the Lab page (a name, the exact message, one to three of the seven checks) and keep them as the **next version** of the skill through the library's checked import. `tests/cases.json` **and the definition file's own copy of the tests** are written together, only the latest version can be edited, a message pasted with a hidden character is refused by the library's own checks, and the page says what would stop a save before the button is pressed.
**Three things found while building it:** the first design's `PUT` could not have worked from a browser (the API's CORS policy allows only GET, POST and DELETE), a built skill keeps two copies of its tests, and a save could have created a second skill under another name. **A real run on a copy of the author's library:** `meeting-notes-summarizer` became runnable with three cases written from its own rules; the result (2 of 3 with the skill, 2 of 3 without) showed both **a real fault** (it wrote "due date: unassigned") and **a limit of the seven checks** (a "must not say X" check is passed by an answer that does nothing).

## The independent review ([testing-lab.md](testing-lab.md), "The independent review")

A fresh reader, with no part in writing the code, found **no Critical issue, 5 Important and 9 Minor**. Every finding was reproduced by a test that failed on the old code before it was fixed. The Important ones: **a regex check could freeze the whole server** (the guard missed `(a|aa)+$`; every pattern now runs in a child process killed after 1.5 seconds), "Run it again" could run a second copy of a version, a request the server could not read was shown as "Nothing changed", a skill that declares its tools only in its `SKILL.md` was run as text-only, and **a stale save could overwrite a newer version** (the store now checks the expected latest inside its lock). Twelve of 14 were fixed and two documented.

## AF: the Quality Report ([quality-report.md](quality-report.md))

One page for one version of one skill, assembled by code from stored files and stored runs (**a GET: no model, nothing run, nothing changed**), that **never says a skill is safe**. It shows a headline in counts and one sentence of attention; **what to do next** (worked out by code, each with a link); today's checks in three groups, each library check with what it was at import (worse, better, new); the requirement against its tests (criteria with no test, tests citing a criterion that does not exist); the cost in tokens; the Testing Lab's result **for that version** (never another's); what changed since the previous version; the code it cites; **what did not run, with reasons**; and what the report cannot tell you.
The key discovery: the builder's richer checks (instruction clarity, requirement coverage, token weight) were shown once at build time and **never kept with the version**, but for a skill built here the definition and spec are kept, so those checks can be **run again today, by code**. **On the author's real library** the report found that both built skills fail "the approved requirement reached SKILL.md word for word" because they were built before the builder learned to carry it (true, not a false alarm); and a test found that the first version would have reported a skill saved with Windows line endings as having "no front matter". The skill and version picker was extracted from the Lab and is shared by both pages.

## How we worked (and what that taught)

* **Every change was test-first, and every rule was broken once on purpose** to see a test fail (118 breaks across the session, each caught; the ones that survived were weak tests of ours, strengthened).
* **A review finding is a claim until a test fails on the old code.** Reproducing the report's findings proved them, and the same tests now guard the fixes.
* **Real runs found what mocks could not:** a result that counted 7 model calls where 6 were promised (a retried call counts); the CORS rule; the two copies of a skill's tests; the Windows line endings; the older skills that predate a builder rule.
* **Screenshots were read by eye** and found wording defects no assertion could (a sentence shown twice, a lowercase "it" after a full stop, a cut-off dropdown).
* **Honesty rules held:** a check that did not run is "not run", never a pass; a result is about the version it tested; the Quality Report never says safe; a limit that was not fixed is written down.

## State at the end

All nine pages of the original vision exist: Dashboard, Builder (chat), Repository (with the drawn map and the how-it-works guide), Library (versions, compare), Plugins, Testing Lab, Quality Report, Settings, and the Library's skill pages. Pushed to `jeswin4693/AISkills` on `main`.

## What is next

(The behavioural canary scan was built afterwards, as slice AG: [canary-scan.md](canary-scan.md).) Node servers inside plugins; the Streamable HTTP transport for MCP servers; the `/usage` clean-up; a function-level graph. Documented open risks: Lab runs share the builder's two-worker pool, keys the harness does not know are dropped when cases are saved, a snapshot being pruned while another request reads it, and a data folder inside a git work tree.
