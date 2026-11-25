# The Quality Report (slice AF), the last of the nine pages in the original vision

Status: design written 2026-11-25 by Claude after the person said "Yes, start the Quality Report page". The details are **my calls**, with my reasons.

## Why

The original vision (docs/START_PROMPT.md, part D and the page list) asks for a Quality Report: "passed, failed, warnings, missing, suggestions" for a skill. Today the answer is scattered: the Library's skill page shows the checks as they were at import, a rescan says whether they got worse, the Builder's result page showed
the quality checks and the token cost **once, when the skill was built**, the Lab shows test results, and nothing says which acceptance criteria have a test. The Dashboard says "nothing needs you" about static checks only.
**What was found on 2026-11-25 while reading the code:** a saved skill keeps only 12 structure-and-safety checks from import. The builder's richer checks (instruction clarity, requirement coverage, the worked example, token weight) were shown at build time and **not kept with the version**; but for a skill built here, `skill.sdm.json` and `spec.json` are kept,
so those checks can be **run again today, by code, no model**.

## What the page is

One page for **one version of one skill**: `/quality?name=&version=`, a menu entry, a "Quality report" button on the skill's page. It assembles, from what exists and without asking a model:

1. **A headline** in counts (failed, warnings, not run, passed) and one sentence of attention (a problem, worth a look, or "nothing was found by the checks that ran"). **Never "safe", never a score.**
2. **What to do next**: an ordered list worked out by code from the gaps below (fix a failed check, write a test for an untested criterion, run the Lab, read the failed cases, shorten a heavy description...), each with a link where there is one.
3. **The checks, run again today**, in three groups, each check with what changed since import (worse, better, new):
   * *Library checks* (structure and safety): the same static checks as an import.
   * *Design checks* (instruction clarity, requirement coverage, tests are runnable, steps are short): only for a skill built here (needs `skill.sdm.json`).
   * *The written files against the requirement* (the requirement reached SKILL.md word for word, a worked example, the token cost): needs `skill.sdm.json` and `spec.json`.
4. **Requirements and tests**: each acceptance criterion and the tests that cite it, the criteria with no test, tests that cite a criterion that does not exist, how many tests can be run in the Lab and why the rest cannot.
5. **Cost**: tokens always loaded, loaded when used, on demand (works for any skill: it only needs SKILL.md and the other files).
6. **The Testing Lab result** for this version (or "never run", or "only an older version was run").
7. **Changes since the previous version** (the risk diff, as the library already works it out) and **evidence** it cites (with a pointer to the recheck on the skill's page, which needs the repository).
8. **What did not run**, listed: checks that did not run, the design checks for a skill with no definition file, the Lab if never run, scripts in a sandbox, a real agent, a semantic review.
9. **Limits**, as plain sentences.

## Goals

* Everything is computed by code from stored files and stored runs: **no model call, nothing is run, nothing is changed** (it is a GET).
* A check that did not run is said as "not run" with its reason, never counted as passed; a part that cannot be assembled says so and never shows zero.
* The same page works for an imported skill: the groups that need a definition file say "not run: this skill has no definition file (it was not built here)".

## Non-goals

* No score, grade or "safe". The library says plainly that passing static checks is not proof (README, docs/library.md).
* No auto-fix ("auto-fix then re-test" in the vision): a repair needs a model, and the builder already does one repair at build time.
* No new check. Every check on the page is one that already exists; this slice only runs them again on stored files and puts them in one place.
* Skills only (agents and the other kinds have their own definition files and no test harness yet).
* No history over time (a chart of quality per version).

## Anti-goals (a failure even if it technically works)

* A report that says "all good" when most of it did not run. The attention sentence is worded from what ran and lists what did not.
* A check re-run today shown as if it was the build's: each says it was run **now**, and what it was at import.
* A damaged version reported as fine: reading goes through `Library.read` (every file against the manifest), so a changed version is a 400 with the library's own words.
* A path or secret in the response (evidence names a repository: only its name is shown, as the skill page already does).

## Approaches considered

| | What | Trade-off |
|---|---|---|
| **A** | Regroup what the skill page already shows (stored checks, rescan) in the browser. | No server work, but it cannot add what was lost: the quality checks, the criteria coverage and the token cost are not in the stored checks. It would be the Dashboard's rescan again. |
| **B** | **One server route that assembles the report, with the pure assembly in testable functions**, and a page that only shows it. | New code, but the logic (coverage, grouping, suggestions, attention) is in Python with offline tests, and the page stays thin. |
| **C** | Also keep the quality checks in every new version at import. | Would change what every import stores and every version's hash-visible checks: too wide for this slice. |

**My pick: B.** (A cannot show what the person most wants, C changes the library.)

## Design

* `GET /api/library/{name}/quality?version=` (skills only, `?kind=` other than skill is a 400), in `api/quality.py`; the assembly in `builder/quality_report.py` as small pure functions (`token_summary`, `requirement_coverage`, `check_rows`, `suggestions`, `attention`) and one `build_report` that reads the version through `Library.read` and takes the Lab's runs as data.
* Today's static checks come from `validate_files`; each is compared with the stored check of the same name (`worse`, `better`, `same`, `new` when it did not exist at import). The design and written-file checks come from `build/checks.py` and `build/quality.py` (`run_checks`, `quality_checks`, `check_rendered`, `rendered_quality`), run on the stored `skill.sdm.json`, `spec.json` and text files. A definition or spec that cannot be read is a "not run" row with the reason, not a crash.
* Criteria come from the definition's `acceptance_criteria` (ids `AC1`...), else from `spec.json` (numbered in order), else none; tests from `tests_of` (their `covers`).
* The page: `components/quality/*`, `lib/quality.ts` (pure: tones, wording, ordering) with unit tests; the skill picker is shared with the Lab (extracted from it).

## What is left to the builder

The exact wording; the order inside a group; the layout. Not left: the rules above, and that every fact on the page comes from the response (the page invents nothing).

## Done means

Tests pass offline and in the browser suite, every rule broken once on purpose and caught, a run on the real library (a COPY: the three skills saved on this machine, one of them with its definition and spec), README, `docs/roadmap.md`, `docs/quality-report.md` updated, committed and pushed.
