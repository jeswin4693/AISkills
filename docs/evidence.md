# Evidence: skills that cite code, and a recheck that says what changed

A skill often names code: "see `build_graph` in `graph/build.py`", "only `main` calls this". Code moves on and the skill does
not. This slice (V) lets a skill **carry the places it cites, with the facts the graph had when it was written**, and lets you
ask later, with one command, **what changed in those places**. Plan: [superpowers/plans/2026-11-23-evidence-drift-slice-v.md](superpowers/plans/2026-11-23-evidence-drift-slice-v.md).
Where it comes from: [differentiators.md](differentiators.md), item 1.

It is the same rule the Suggest step already follows ("a suggestion must cite graph nodes that exist"), extended from the day a
skill is made to every later day. It is **deterministic**: no model, nothing is run, only the graph is read and compared.

> It checks that **cited facts still hold**, not that the skill's advice is right. Every report says so.

## Use it

```powershell
cd backend
# 1. cite places in a repository (a new version of the skill; nothing is changed in the repository)
python -m skillforge library cite my-skill --repo C:\code\myrepo --ref src\config.py::parse_config --ref src\config.py
python -m skillforge library cite my-skill --repo C:\code\myrepo --from-text     # the files and functions the skill's own text names

# 2. later: what changed? (reads the repository, changes nothing; exit 1 if anything is gone, moved or changed)
python -m skillforge library recheck my-skill --repo C:\code\myrepo [--json] [--version N]

# 3. after you have read the skill against the changed code: record today's facts as the new baseline (a new version)
python -m skillforge library refresh my-skill --repo C:\code\myrepo [--drop-missing]

# a skill built from a suggestion carries the idea's cited places from the start
python -m skillforge build --from-suggestions report.json --pick 1 --repo C:\code\myrepo ...

# evidence names a private repository's files and functions: leave it out when you share
python -m skillforge library export my-skill --without-evidence
```

A place is a file (`src/config.py`), a function or class by name (`parse_config`), or `file::name` (`src/config.py::Parser.run`).
A name given with `--ref` that matches several places (a test file's function of the same name counts) or several files is
**listed, never picked**; one that is not in the graph is reported and never recorded. With `--from-text` the Task Plan's
mention finder reads the skill's text: it takes a name that matches one place, lists an ambiguous one, and, as in the Task
Plan, takes the only non-test match when a name also exists in tests (every place cited is shown, so you can see it).
A skill may cite at most 60 places, and the file must stay under 800 KB (the CLI says so rather than writing a file the next
import would refuse). Places recorded together are read with the **same `--focus`**: `cite`, `recheck` and `refresh` default to the
one the evidence was recorded with, a different one is refused when citing and noted when rechecking.

## What the recheck says

One verdict per place, worst first:

| Verdict | Means | Exit code |
|---|---|---|
| **MISSING** | the cited thing is gone (the report says whether its file still exists) | 1 |
| **MOVED** | it is gone, and **exactly one** place now looks like it (same body structure, or same name in another file): a **candidate, never applied for you** | 1 |
| **CHANGED** | it is there, and a recorded fact differs: its structure, kind, export or **decorators**, a class's **bases and methods**, its **resolved** callers or callees (the new and the gone ones are named), a file's symbols or importers | 1 |
| **EDITED** | the facts are the same but the text differs (a name, a value, a comment, or, for a cited **file**, the body of a function in it) | 0 |
| holds | every recorded fact is the same, and so is the text | 0 |

What is **not** a change: a function that only moved to another line, a blank line or comment above it, a changed line count.
Two or more look-alikes are listed ("places that look like it") but none is chosen, and a body shorter than 30 syntax nodes is
never matched by structure (many functions look like it).

### What is recorded

For a **function, method or class**: its kind, line range, whether it is exported or decorated, the graph's hash of its body
*structure* (names and values left out; a class has none), its size, a hash of its source **text, decorators included**, and its
**resolved** callers and callees; for a class also its **base classes and methods**. For a **file**: its language, line count, symbol
names, the files that import it or that it imports, and a hash of the whole file's text. Each place also carries when it was
recorded and the repository's commit, and **whether the working tree had uncommitted changes then** (see below).

* A name-only **guess** is never recorded as a caller or callee (guesses count toward nothing in this project).
* In a language whose calls and imports the graph does not resolve (the `basic` level, [languages.md](languages.md)), the
  lists stay empty and the place says **"not measured"**: the recheck never says "no callers" where the graph could not have seen them.
* A list is kept by name up to 40 entries, with the true count **and a digest of the whole list** beside it, so a caller swapped
  inside a long list is still a difference (the report then says which list was cut and that the names that changed are not known).
* Decorators: for Python the window of text starts at the first decorator (read with `ast`); for other languages the lines that
  start with `@` above a definition are included by a text heuristic, which can include a neighbour's decorator when no blank line separates them.
* Only the repository's **folder name** is stored, never a path on your computer.

### Where it is stored

`evidence.json` in the skill's folder, next to `SKILL.md`. So it is versioned, covered by the manifest hash (a changed file is
refused), exported with the skill and kept by a rollback. Writing it makes a new version (source "evidence") through the same
checks as an import. A skill without the file is exactly as before: no new row in its checks. A skill **with** one gets a check
row, "evidence.json is well-formed evidence", and a malformed file **fails** the import.

The file is read **strictly** and only ever as data: unknown keys, wrong types (`"5"` or `true` for a number), too many places,
over-long text, duplicate places, control, invisible or direction-changing characters and a file over 800 KB are refused (a leading
byte-order mark is accepted); a place is only used as a **key to look something up** in a graph and as text to show, never
opened as a path, never run, never evaluated (a test feeds `../../etc/passwd` and a `__import__(...)` string as places). **Whatever
came from the file or from a repository is shown escaped** (`\x1b`, `U+202E`): an error about a hostile key, a name taken from a
repository, a candidate and a file name never reach the terminal raw.

### Privacy

Evidence names the files and functions of a repository that may be private. `export --without-evidence` (and
`?without_evidence=true` on the API) leaves it out, the export command says when it is included, **`install` does not copy it**
into a skills folder (it says so), and **a plugin never ships it** from a component. It stays in your library unless you export it.

## The API (local only)

| Route | |
|---|---|
| `GET /api/library/{name}/evidence` | `?version=N`. The recorded evidence, or `evidence: null` for a skill without any. Reads what is stored. |
| `POST /api/library/{name}/recheck` | `{"repo": "<absolute path>", "version": N, "focus": "..."}` returns the same report as `recheck --json`. **Off in the hosted version** (403): it reads a folder on the server. 400 for a relative path, a missing folder, or a skill without evidence. |
| `GET /api/library/{name}/export` | `?without_evidence=true`. |

Citing and refreshing are command line only for now (they write the library from a folder on this machine).

## What a real run showed (2026-11-23)

On this repository, with a throwaway library: a skill that names `build_graph`, `find_mentions` and `ground` cited those places
(`--from-text`) and a recheck on the same code said "3 holds". Then in a **clone** of the repository three realistic changes were
made (a second caller of `ground`, an early return in `find_mentions`, `build_graph` renamed) and the recheck said:

```
Result: 1 moved, 2 changed
  MOVED    backend/skillforge/graph/build.py::build_graph
      - it may have moved or been renamed: ...::build_repository_graph has the same body structure (a candidate, not a fact: check it before relying on it)
  CHANGED  backend/skillforge/conductor/mentions.py::find_mentions
      - its code structure changed (was 437 syntax nodes, now 448)
  CHANGED  backend/skillforge/suggest/ground.py::ground
      - it now has 5 resolved callers, was 4 (new: backend/skillforge/suggest/extra_user.py::again)
```

**That run also found a real defect in the first version:** the evidence was recorded from a working tree with uncommitted files,
but only the commit id was kept, so the report blamed "gone" callers on code that was simply never in any commit. Evidence now records
whether the tree was dirty, and the recheck says so ("plus uncommitted changes", and a note). A real build with the configured model
from a suggestion with `--repo` also worked end to end: 31 checks passed, `evidence.json` was written, the folder imported (14 checks),
and the recheck said "holds".

## What one independent review found (2026-11-23), and what was done

A fresh reviewer, told to attack and to prove each claim by running code, read the first version. Every finding was reproduced
as a failing test first (34 of the 40 new tests failed on the old code), then fixed.

| Found | Done |
|---|---|
| **Critical:** removing or swapping a decorator (`@login_required`) gave "holds", in Python and TypeScript: the graph's line starts at the `def`, and the `decorated` flag was never compared | The text hash starts at the first decorator (Python: read with `ast`; others: the `@` lines above, by text), and the `decorated` flag is compared |
| **Critical:** a cited class said "its structure is the same" when a base class or a method was added: classes have no structure hash | A class records its base classes and its methods and a change in them is "changed"; a place with no structure hash says only "its text differs" |
| **Critical:** a cited file said "holds" after every function body in it was rewritten | A file records a hash of its whole text; a differing text is "edited" (never "holds") |
| **Critical:** with a list cut at 40, swapping one caller for another gave "holds" without a word | A digest of the whole list is recorded and compared; the report says the list was cut |
| Escape sequences in a hostile key reached the terminal inside an error message; some invisible characters (U+FEFF, U+061C, U+00AD, U+FE0x) were accepted | Everything shown from the file or from a repository is escaped; the refused set is larger |
| Citing with another `--focus` than the one recorded made a false "changed" right away | The command defaults to the recorded focus, citing with another is refused, a recheck with another says so |
| `build --repo` could write an `evidence.json` over 400 KB that the next import refused; the check failure did not say why | The file is trimmed to fit (and says so), `cite` refuses with the way out, and a failed check shows its detail |
| The privacy sentence was false for `install` (it copied `evidence.json` into the skills folder) | `install` leaves it in the library and says so |
| `--ref NAME` picked the one non-test match silently; two files with one name said "matches nothing" | Several matches are listed, never picked, for an explicit reference |
| A form feed or U+2028 above a function shifted the text window by one line (the graph counts `\n` only) | Lines are split on `\n` only |
| A refresh made a new version although no code had changed (the dirty flag and line numbers counted) | They are no longer compared |
| A string, a bool or a float was accepted for a number; a byte-order mark was refused | The model is strict; the mark is accepted |

Not changed, said plainly: TypeScript overload signatures and a Python property getter and setter share one id (only the last
is tracked); the decorator window outside Python is a text heuristic.

## Tests

`tests/test_evidence.py` (model, snapshot, recheck on small repositories, hostile files), `test_evidence_library.py` (cite, recheck,
refresh, export, plugin, risk diff, rollback), `test_evidence_cli.py` (commands, exit codes, `build --repo`), `test_evidence_api.py`,
`test_evidence_review.py` (what the independent review found). All offline, 159 tests. 32 deliberate breaks of the code (guesses counted as callers, short bodies matched by structure, callers compared where
calls are not resolved, control characters accepted, a text edit invisible, one of two candidates picked, refresh dropping what is gone,
export or plugin ignoring the exclusion, citing again overwriting recorded facts, a duplicated file mention, hosted recheck allowed, a
foreign repository accepted, the check skipped on import, the build recording without a graph; and for the review's fixes: decorators
ignored, a class's bases and methods ignored, a file's text ignored, a cut list compared by count only, names or a hostile key shown raw, a
different focus accepted, install copying the evidence, a name picked among several, lines split like `splitlines`, a refresh counting the
dirty flag, a wrongly typed value accepted, an oversized file written, U+FEFF accepted) were each caught by a test.

## Limits (said plainly)

* **A claim in prose is not parsed.** "Only called from `main`" is not understood: the places are checked (and `main`'s callers are
  among the recorded facts), the sentence is not. A value written in the skill's text is noticed only as an edit.
* **The graph is as deep as the language.** Calls and imports are resolved for full and standard levels only; elsewhere "not measured".
  A call the graph cannot resolve (dynamic calls, reflection) is invisible here, as everywhere in this project.
* **A candidate is a guess.** "Moved" means one place has the same body structure or name; renamed *and* rewritten code is "missing".
* **Evidence is attached from the command line.** The web Builder has no repository input, so it records none; there is no web page
  for evidence yet.
* **Uncommitted changes make a commit id incomplete**; the report says so but cannot separate what is committed from what is not.
* A place is cited by what the graph knew; `refresh` accepts today's facts, so it is for after a person has read the skill against
  the changed code, not a way to silence the report.
* Not verified: macOS and Linux paths, a repository of hundreds of thousands of files (a recheck reads the whole graph each time).
