# The Quality Report (slice AF)

The last of the nine pages in the original vision. One page for **one version of one skill** that answers: *what did the checks find, what did not run, and what should I do next?*
It is assembled by code from what is stored (no model is asked, nothing is run, nothing is changed: it is a GET), and it **never says a skill is safe or good**: it lists what ran, what it found, and what did not run.
Design: [superpowers/specs/2026-11-25-quality-report-design.md](superpowers/specs/2026-11-25-quality-report-design.md).

## What a person sees

```
 Quality Report
   Skill [ git-commit-writer v ]   Version [ v1 (latest) v ]

   git-commit-writer v1   [latest]   3 days ago · zip git-commit-writer · 1 version in all
   [1 failed] [3 warnings] [0 not run] [27 passed]
   ! A problem: 1 check failed today. Fix it first.

   What to do next
     [Fix]   Fix: the approved requirement reached SKILL.md word for word. missing from SKILL.md: ... If this skill was built before the builder
             carried the requirement into SKILL.md, build it again, or add those lines to SKILL.md yourself.
     [Write] Write test cases so the Testing Lab can run this skill ...   Open
     [Read]  Read: the description says when to use the skill ...

   The checks, run again today
     Library checks: structure and safety          (the same checks as an import; each says what it was at import: worse / better / new)
     Design checks: instruction clarity and requirement coverage        (built skills only; run again from skill.sdm.json)
     The written files against the requirement                          (built skills only; skill.sdm.json and spec.json)
   The requirement and its tests      2 acceptance criteria: 1 with a test, 1 without.   (each criterion with the tests that cite it)
   What it costs to use               About 43 tokens always loaded, 536 when used, 2151 more on demand. These are estimates.
   The Testing Lab                    Only v1 was run in the Testing Lab (the skill helped). This version has not been.
   Changes since v1                   Worth a look. 0 riskier, 1 worth a look, 0 less risky.   Compare v1 and v2
   Code it cites                      3 places in shop-api, recorded 2 days ago ...
   What did not run                   Scripts run in a sandbox. A real agent using the skill. A review of the instructions ...
   What this report cannot tell you   Passing these checks is not proof ...
```

## What is in it, and where each part comes from

| Part | Source | Notes |
|---|---|---|
| **Headline** | counts of the check rows below (failed, warnings, not run, passed) | the number at the top is exactly the number of rows listed (the browser test compares them) |
| **Attention** | worked out from the headline and the findings | `bad` when a check failed; `warn` when nothing failed but something is worth a look (a warning, an untested criterion, a Lab result of "worse" or "adds nothing", riskier changes, a heavy description); otherwise `info` and **"Nothing was found by the checks that ran. N things did not run."**. Never green, never "safe" |
| **Library checks** | `validate_files`: the import's own static checks, run today | each is compared with the stored check of the same name: *worse*, *better*, *same*, or *new* (it did not exist at import) |
| **Design checks** | `build/checks.py` `run_checks` + `build/quality.py` `quality_checks`, run on the stored `skill.sdm.json` | only for a skill built here. These were shown **once, when the skill was built, and not kept with the version**: this is the first time they can be run again |
| **Written files vs the requirement** | `check_rendered` + `rendered_quality` on the stored `SKILL.md` and `spec.json` | the requirement reached SKILL.md word for word, a worked example, the token cost. Windows line endings are read as the same thing as Unix ones |
| **Requirement and tests** | the definition's `acceptance_criteria` (ids `AC1`...), else `spec.json` (numbered in order), else none; tests from `tests/cases.json` and their `covers` | criteria with no test, tests that cite a criterion that does not exist, how many tests the Lab can run and why not |
| **Cost** | `SKILL.md` and the other files | works for any skill (it needs no definition): always loaded, loaded when used, on demand; a heavy description or SKILL.md is said with what to do |
| **Testing Lab** | the Lab's stored runs | the result of **this version**; a run of another version is said to be of an older version and is never shown as this one's |
| **Changes since the previous version** | the library's own risk diff | the first version has none; never "safe": "No new risk found" |
| **Code it cites** | `evidence.json` | the repository's name and how many places; whether it still holds needs the repository (the recheck on the skill's page) |
| **What to do next** | the gaps above, ordered by code: a failed check, a criterion with no test, a test citing an unknown criterion, test cases to write, the Lab to run, a Lab result to read, warnings to read, a heavy skill to shorten, riskier changes to read | at most 12, the rest counted; each links to where to act |
| **What did not run** | check rows that did not run, the Lab if never run, scripts in a sandbox, a real agent, a review for conflicting rules, a security review | every item has its reason |

## The rules (in code, each one tested)

| Rule | Why |
|---|---|
| A **GET** that asks no model, runs nothing and changes nothing (the test calls it twice and compares). | Looking must cost nothing. |
| The version is read through `Library.read`, which checks every file against its manifest: a changed version is a **400** with the library's words, not a report. | A damaged version must not be reported as fine. |
| A part that cannot be assembled is a **row that did not run, with its reason**, never a crash and never a zero. A definition or spec that cannot be read, or a builder check that raises, is said in a row. | "A check is passed only if it ran." |
| A skill with no definition file is told its design checks cannot run **because it was not built here**; a skill that records no requirement says so and none is invented. | An imported skill is not "failing" the checks it cannot have. |
| The Lab result is for **this version**. | A result for v1 must not make v2 look tested. |
| `limits` and `not_run` are part of every response. | The report is honest about what it cannot say. |
| Skills only: another kind is a 400 that says so. | The other kinds have their own definition files and no test harness. |

## API ([api.md](api.md))

`GET /api/library/{name}/quality?version=` (`?kind=` anything but `skill` is a 400). Returns `{name, version, tag, latest, versions, created_at, source_kind, source_label, note, content_hash, headline, attention, groups, requirements, tests, tokens, lab, changes, evidence, suggestions, suggestions_more, not_run, limits}`.
Each row of `groups` is `{name, status, detail, was, change}` with `change` one of `same`, `worse`, `better`, `new` (library checks) or `run_now` (design and written checks, which were not kept at import). 404 for an unknown skill or version, 400 for a version changed on disk or another kind, 422 for a bad version. Works hosted too (behind the sign-in).

## What it found on the author's real library (2026-11-25, read-only)

The report was run on the three skills saved on the author's machine, **before the page was built** (by calling the function, nothing written):

* **`git-commit-writer` and `count-todo-fixme` both fail "the approved requirement reached SKILL.md word for word".** That is **true, not a false alarm**: both were built on 2026-11-19, before the builder learned (step J, "stronger skills") to carry the approved requirement into `SKILL.md`; their `SKILL.md` has no rules or criteria section, and a rebuild would have one. At build time they passed everything the builder checked *then*, which is exactly why this report is useful: the builder's own checks, run again today, show the drift between an old skill and the current standard. The suggestion now says so and what to do ("build it again, or add those lines to SKILL.md yourself").
* Both built skills also warn that the description gives fewer than two concrete trigger phrases, and that there is no worked example (their tests have no message to take one from); `git-commit-writer` also warns that its tests have no message to send.
* **`meeting-notes-summarizer`** (imported, no definition file) has 12 passing library checks and **two rows that did not run**, "the design checks cannot run: it was not built here", and the headline says `0 failed · 0 warnings · 2 not run · 12 passed` with "Nothing was found by the checks that ran. 7 things did not run." It is the honest answer for a skill the checks cannot reach.
* **The first version of the report would have been wrong in one real case**: a skill saved with Windows line endings (CRLF) was reported as having "no front matter", because the builder's check was written for files it generated itself (always `\n`). Found by a test that rewrote a `SKILL.md` on Windows; the report now reads both line endings as the same thing.
* The token numbers match the Lab's: 536 tokens for `git-commit-writer`'s `SKILL.md` and 43 for its name and description, as `evaluate.md` records from the build.

## Limits (said plainly)

* **The design and written-file checks need a skill built here** (its `skill.sdm.json` and `spec.json`). For an imported skill the page has only the library's 12 structure and safety checks, the cost and the tests, and says what it cannot run.
* **They hold a skill to the words it was built from**, not to what happens when it is used. A skill that says what the requirement says can still be wrong.
* **The checks that were run at build time were not kept with the version**, so the page cannot say what they said then, only what they say today. (Keeping them at import would change what every version stores: not done.)
* **Heuristics warn, they do not fail** (vague wording, a missing trigger phrase, a long step): read them, they can be wrong.
* **Token numbers are estimates** at about four characters a token.
* A skill with many versions reads two versions for the "changes since" part; a very large library was not timed.

## Checked (2026-11-25)

**Tests.** Backend: **3,013 collected, 4 skipped (symbolic links), 0 failed** (2,984 before; 29 new in `test_quality_report.py`: a built skill, a skill edited after it was built, a skill saved with Windows line endings, a plain imported skill, a definition or spec that cannot be read, criteria with and without tests, the Lab's result for this version and not another, the risk diff, evidence, the attention sentence, what did not run, the cap on suggestions,
that a second call changes nothing and asks no model, a changed version refused, and the hosted sign-in). Web: **350 unit tests** (18 new in `lib/quality.test.ts`) and a clean typecheck; the Lab was refactored onto the shared picker and its 92 browser steps still pass. Browser (real Edge, the real API, a scripted fake model, side ports): **100 of 100** (92 before; 8 new steps: the menu and the empty page; a built skill's three groups, **with the headline compared against the number of rows actually listed**;
the verdict never claims safety; an imported skill says its design checks could not run and why; the Lab result belongs to the version it ran on; a suggestion leads to where to act and the changes since the previous version link to the comparison; the skill's own page has a Quality report button; no sideways scrolling at phone width).

**Deliberate breaks: 28, all caught** (19 backend, 9 page). One survived the first run and was my test's fault: the "scripts did not run" item could be renamed to just "Scripts" because the test only looked for the word; it now demands the whole wording and the break is caught.

**What the browser run and a read of the screenshots found:** two of my own test steps were wrong (a pattern that matched the real check name "the approved requirement…" and the page's own disclaimer, and a link matched by a name that also fits the sidebar's "Quality Report" before the skill page had loaded its button), and one wording defect no assertion could see (a lowercase "it" after a full stop in "What did not run"), all fixed.

**Real run (2026-11-25, read-only, on the author's own library):** see "What it found on the author's real library" above: two built skills fail the requirement check because they predate the rule, one imported skill has two rows that did not run and says so, and the line-ending defect was found by a test before it could mislead.

**Not verified:** a library of hundreds of skills or a skill with hundreds of versions (each report reads the version's files and the previous version's); a screen reader beyond native elements, headings and `aria-label`s; the hosted sign-in with this page in a real browser (the route is covered by the hosted test); any browser but Edge.
