# The Architecture Map (slice Z) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Draw a repository's top-level folders as boxes and the proven imports between them as arrows on the Repository page.

**Architecture:** A pure, deterministic function over the existing code graph (`graph/architecture.py`) adds an `architecture` field to the
`analyze` answer. The page lays the boxes out in columns with pure TypeScript helpers (`lib/architecture.ts`) and draws them as
hand-written SVG (`components/repository/ArchitectureMap.tsx`). No model, no new route, no new library.

**Tech Stack:** Python 3.13 + pytest (backend); Next 16, React 19, TypeScript, Tailwind 4, vitest, real-Edge e2e (frontend).

**Spec:** [docs/superpowers/specs/2026-11-25-architecture-map-design.md](../specs/2026-11-25-architecture-map-design.md)

## Global Constraints

- `backend/skillforge/graph` is deterministic: no AI; a link is `resolved` or `guess`; a `guess` is **never** drawn or counted.
- No new library in `backend/requirements*.txt` or `frontend/package.json`. Run `scripts\frontend-node-modules.ps1` only if an `npm install` ever happens (none is planned).
- Tests are offline (no real `.env`, no hosted model). Backend tests from `backend/`: `C:\dev\venvs\aiskills\Scripts\python.exe -m pytest <file>` **without `-q`** (the project hides the summary line otherwise).
- The answer and the page never contain the person's own folder path; module names and file paths are repository-relative.
- Browser suite only on **free ports**: `E2E_UI_PORT=3100`, `E2E_API_PORT=8100`, `SKILLFORGE_PYTHON=C:\dev\venvs\aiskills\Scripts\python.exe`. Check `netstat -ano | findstr ":3000 :8000"` first; never stop the user's servers.
- The Write and Edit tools turn a typed backslash-u escape into a raw character: never type one in source or tests (use `chr(...)`). Keep each existing file's line endings.
- Work on branch `slice-z-architecture-map`, one commit per task, each message ending `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`. After the last task: tests pass, docs updated, fast-forward `main`, `timeout 75 git push origin main` (exit 124: check `git status -sb` again later before asking the user).

## Review Focus

Inputs the spec implies but a happy-path test would miss, most likely first (each has its test in the task named):

1. A flat repository with only root-level files: one `(root)` box, no arrows, a plain note, no crash (Task 1 `test_a_flat_repository_is_one_root_box`; Task 4 GitHub step).
2. A language whose imports are not read (`basic` level) must say "imports not measured", never look like "depends on nothing" (Task 1 `test_unmeasured_languages_are_said_not_drawn_as_independent`; Task 2 `mapNotes`).
3. Hundreds of top-level folders: the cap and one `(other)` box, arrows re-pointed, layout still inside its frame (Task 1 `test_many_folders_fold_into_other`; Task 2 `layout stays inside its frame`).
4. A real folder named `(root)` or `(other)`, or a name like `<script>` or 90 characters long: ids never collide, text is escaped, long labels are shortened with the full name kept (Task 1 `test_a_real_folder_named_like_a_synthetic_box_does_not_collide`; Task 2 `shortLabel`).
5. Folders that import each other through a third (A to B to C to A) and imports inside one folder: one cycle group, no self-arrow (Task 1 `test_a_cycle_through_three_folders_is_one_group`, `test_imports_inside_a_folder_are_not_arrows`).

---

### Task 0: Baseline, the browser re-run slice Y still owes

**Files:** none changed.

- [ ] **Step 1:** Create the branch: `git switch -c slice-z-architecture-map`.
- [ ] **Step 2:** Confirm ports 3100 and 8100 are free; in `frontend/` run `$env:NEXT_TELEMETRY_DISABLED='1'; $env:NEXT_PUBLIC_API_URL='http://127.0.0.1:8100'; npm run build`.
- [ ] **Step 3:** Run `$env:E2E_UI_PORT='3100'; $env:E2E_API_PORT='8100'; $env:SKILLFORGE_PYTHON='C:\dev\venvs\aiskills\Scripts\python.exe'; node e2e/run.mjs | Tee-Object e2e-baseline.log` (output only appears at the end). Expected: **60 of 60** behaviours pass (slice Y recorded 60 before its last backend tweaks). Delete `e2e-baseline.log` afterwards.
- [ ] **Step 4:** Run the backend suite once from `backend/` (`python -m pytest`, no `-q`). Expected: 2,489 passed, 3 skipped (symlinks) or better. If a step fails, stop and report it: it is slice Y's bug and changes the order.

---

### Task 1: The architecture answer (backend)

**Files:**
- Create: `backend/skillforge/graph/architecture.py`
- Modify: `backend/skillforge/builder/repository.py` (`analyze_repo`, add one key)
- Test: `backend/tests/test_architecture.py` (create), `backend/tests/test_repository_api.py` (one test)

**Interfaces:**
- Consumes: `RepoGraph`, `FileRecord`, `Edge`, `Symbol` from `skillforge.graph.model`; `languages.level_of(lang) -> "full"|"standard"|"basic"`.
- Produces: `architecture(g: RepoGraph, max_boxes: int = MAX_BOXES) -> dict[str, Any]` with constants `MAX_BOXES = 14`, `MAX_FILES_LISTED = 12`, `MAX_FUNCTIONS_LISTED = 3`. The dict is exactly:
  `base: str` (stripped common folder, `""` if none); `modules: list[Module]`; `arrows: list[{"from": id, "to": id, "count": int}]` sorted by `(-count, from, to)`; `cycles: list[list[id]]` (each group sorted, groups sorted); `columns: int`; `measured: bool` (any module measured); `language_levels: {lang: level}` for every language present; `left_out: {"guess": int, "from_tests": int}`; `notes: list[str]` (only the two sentences the page cannot derive: `Everything sits in one place, so the map is a single box.` and `Imports are not measured for any language here, so no arrows are drawn: ...not measured...`).
  `Module` = `{id: "m0".., label, kind: "folder"|"root"|"other", files, lines, test_files, tests_only, symbols, languages: {lang: files}, measured, column, top_functions: [{name, file, line, size}], file_list: [{path, lines}], members: [str]}`. Ids are `m<i>` assigned after sorting by label; `members` is non-empty only for `other`.
  `analyze_repo` answer gains `"architecture": architecture(g)`.

- [ ] **Step 1: Write the failing tests** in `test_architecture.py`. A helper `mini(files: dict[str, str | tuple[str, bool]], edges: list[tuple[str, str, str]])` builds a `RepoGraph` by hand (`FileRecord(path, lang, lines, size, mtime_ns=0, is_test)`; `Edge(src, dst, "imports", conf)`), so guess edges and test importers are exact. Helper `labels(result) -> dict[id, label]`. Tests, each asserting what its name says:
  - `test_folders_become_boxes_and_proven_imports_become_arrows`: `web/app.py -> api/routes.py -> pricing/core.py`; labels `{api, pricing, web}`; arrows by label `[(api,pricing,1),(web,api,1)]`; columns `web 0, api 1, pricing 2`; `columns == 3`.
  - `test_arrow_count_is_distinct_importing_file_pairs`: two files of `a` importing the same file of `b` give count 2; the same pair twice gives 1.
  - `test_imports_inside_a_folder_are_not_arrows`: only an `a/x.py -> a/y.py` edge: `arrows == []`.
  - `test_a_flat_repository_is_one_root_box`: files `a.py`, `b.py` at the top: one module, `kind == "root"`, label `(root)`, `arrows == []`, and `notes` contains `Everything sits in one place, so the map is a single box.`
  - `test_a_common_folder_is_stripped_and_reported`: all files under `src/` (`src/api/x.py`, `src/db/y.py`): `base == "src"`, labels `{api, db}`; with one file at the top as well, nothing is stripped and `base == ""`.
  - `test_guess_imports_are_never_drawn_and_are_counted`: one `guess` edge between folders: `arrows == []`, `left_out["guess"] == 1`.
  - `test_imports_from_tests_are_not_drawn_and_are_counted`: `tests/test_a.py` (is_test) importing `src/a.py`: no arrow, `left_out["from_tests"] == 1`, the `tests` module has `tests_only is True`.
  - `test_a_cycle_through_three_folders_is_one_group`: `a->b->c->a`: `cycles == [[ids of a,b,c]]` sorted, the three share one column; a plain chain has `cycles == []`.
  - `test_unmeasured_languages_are_said_not_drawn_as_independent`: assert `languages.level_of("swift") == "basic"` first; a module of swift files has `measured is False`; when every module is unmeasured, `measured is False`, `arrows == []` and a note contains `not measured`.
  - `test_many_folders_fold_into_other`: 20 folders of different sizes: exactly 14 modules, one `kind == "other"` with 7 `members` and the summed `files`; an arrow into a folded folder points at the `other` id; an arrow between two folded folders is dropped.
  - `test_a_real_folder_named_like_a_synthetic_box_does_not_collide`: folders literally named `(root)` and `(other)` plus top-level files: all ids unique, the real folders have `kind == "folder"`.
  - `test_top_functions_and_files_are_the_biggest_and_capped`: 15 files and 5 functions in one folder: `file_list` has 12 entries sorted by lines desc; `top_functions` has 3 sorted by size desc, never from test files; no `file`/`path` starts with `/` or contains `:`.
  - `test_the_answer_is_the_same_every_time_whatever_the_order`: build the same graph with files and edges in reverse insertion order; `==` on the two answers.
  - `test_an_empty_graph_gives_an_empty_map`: `modules == []`, `arrows == []`, `columns == 0`.
  In `test_repository_api.py`: `test_analyze_includes_the_architecture_map`: a real repo (`repo({...})`) with `pricing/__init__.py`, `pricing/core.py`, `api/__init__.py`, `api/routes.py` (`from pricing.core import tax`), `web/app.py` (`from api.routes import route`); `POST /api/repos/analyze`; `doc["architecture"]` has the three labels, the arrow `web->api`, and `not leaks(root, doc)`. (If the resolver needs other files for the imports to resolve, add them; the assertion on proven arrows must stay.)
- [ ] **Step 2:** Run `python -m pytest tests/test_architecture.py tests/test_repository_api.py`. Expected: the new tests FAIL (`No module named skillforge.graph.architecture`, missing `architecture` key); the rest pass.
- [ ] **Step 3: Implement** `architecture()` in `graph/architecture.py` and wire it into `analyze_repo`. Approach: strip the common folder (while every file has a `/` and all share the first segment); group files by first segment (`(root)` if none); keep the biggest `max_boxes - 1` by `(files desc, label asc)` and fold the rest into one `other` module when more than `max_boxes`; assign ids by sorted label; build file-pair sets from `resolved` `imports` edges whose importer is not a test and whose two modules differ; find strongly connected groups with an iterative Tarjan (no recursion, so a deep repository cannot hit the recursion limit); column = longest chain of arrows over the collapsed groups; sort everything explicitly so the answer never depends on dict order. Notes are plain sentences, one per condition (nothing measured, one place only, guesses left out, tests left out).
- [ ] **Step 4:** Run the same command. Expected: all PASS. Then run the full backend suite once; expected no new failure.
- [ ] **Step 5:** Commit: `git add backend && git commit -m "Slice Z: the architecture answer (folders, proven import arrows, cycles)"`.

---

### Task 2: Types and layout helpers (frontend, pure)

**Files:**
- Modify: `frontend/src/lib/types.ts` (add types, `RepoAnalysis.architecture`)
- Create: `frontend/src/lib/architecture.ts`, `frontend/src/lib/architecture.test.ts`

**Interfaces:**
- Consumes: the answer shape of Task 1, as TypeScript: `ArchFunction {name,file,line,size}`, `ArchFile {path,lines}`, `ArchModule` (fields exactly as the `Module` above, `kind: "folder"|"root"|"other"`), `ArchArrow {from,to,count}`, `Architecture {base,modules,arrows,cycles: string[][],columns,measured,language_levels: Record<string,string>,left_out:{guess,from_tests},notes}`; `RepoAnalysis.architecture?: Architecture` (optional, so an old answer cannot break the page).
- Produces (all pure, exported from `lib/architecture.ts`):
  `layoutMap(arch: Architecture): MapLayout` where `MapLayout = {width, height, boxes: Placed[], arrows: DrawnArrow[]}`, `Placed = {id, x, y, w, h}`, `DrawnArrow = {from, to, count, d: string, width: number, cycle: boolean, x: number, y: number}` (`d` an SVG path, `x,y` where its count is written);
  `shortLabel(label: string, max?: number): string` (default 18, ends with `…`);
  `boxSubtitle(m: ArchModule): string`; `arrowSentences(arch): string[]`; `cycleSentences(arch): string[]`; `mapNotes(arch): string[]`.

- [ ] **Step 1: Write the failing tests** in `architecture.test.ts` (a small `arch()` factory like `idea()` in `repository.test.ts`):
  - `layout puts each module in its column, left to right, with no box overlapping another`.
  - `layout stays inside its frame`: 14 boxes over 6 columns: every box and every arrow end is within `width` x `height`.
  - `a forward arrow starts at the source box's right edge and ends at the target's left edge`; `an arrow that points back or sideways is still drawn and flagged cycle only when both ends are in one cycle group`.
  - `arrow width grows with the count but is clamped between 1.5 and 8`.
  - `the same input gives the same layout`.
  - `shortLabel keeps a short name, shortens a 90-character one with an ellipsis, and leaves markup-like text untouched as plain text` (`<script>` is returned as typed: escaping is React's job).
  - `arrowSentences read "web imports api (3 file pairs)"`, singular for 1; `cycleSentences name every member`; `boxSubtitle says "12 files · 3,400 lines"` and adds `tests` for a tests-only box and `imports not measured` for an unmeasured one.
  - `mapNotes starts with the answer's own notes, then says guesses and test imports were left out with their counts, names the languages whose level in language_levels is basic as not measured, names the base folder, and always ends with the imports-only limit` (assert on the substrings `name matches`, `not measured`, `inside src/`, `imports only`).
- [ ] **Step 2:** In `frontend/`: `npm test -- architecture`. Expected: FAIL (module not found).
- [ ] **Step 3: Implement** the types and `lib/architecture.ts`. Layout: column width and gap constants at the top of the file; boxes in a column ordered as the answer gives them; height = 52 + up to 28 by file count; forward arrows are cubic Béziers between facing edges; other arrows loop over the top of their boxes so they never pass behind one; `width = clamp(1.5 + 1.5 * log2(count), 1.5, 8)`.
- [ ] **Step 4:** `npm test` (all, expected 187 + new, all pass) and `npm run typecheck` (clean).
- [ ] **Step 5:** Commit: `git add frontend/src && git commit -m "Slice Z: map layout helpers and types"`.

---

### Task 3: The map on the Repository page

**Files:**
- Create: `frontend/src/components/repository/ArchitectureMap.tsx`
- Modify: `frontend/src/app/repository/page.tsx` (render it under `RepoSummary`)

**Interfaces:**
- Consumes: `layoutMap`, `shortLabel`, `boxSubtitle`, `arrowSentences`, `cycleSentences`, `mapNotes` (Task 2); `Card`, `Badge`, `Alert` from `components/ui`.
- Produces: `ArchitectureMap({ architecture }: { architecture: Architecture | undefined })`; renders nothing when `architecture` is missing or has no modules.

- [ ] **Step 1: Implement** the component (a React component has no unit test here; Task 4's browser steps are its test). Required behaviour and exact text hooks the browser steps use:
  - A `Card` with heading `How the code is laid out` and one line: `Folders as boxes; an arrow means files in one folder import files in the other (proven links only).`
  - The SVG sits in a frame with `overflow-x-auto` so the page itself never scrolls sideways; `role="img"` with a `<title>` such as `Map of N folders and M arrows`.
  - Each box is `<g role="button" tabIndex={0}>` with its `shortLabel` as text and the full label in `<title>`; click, Enter and Space select it; the selected box is outlined. Box text and arrow counts are plain SVG text (escaped by React).
  - A cycle shows an `Alert tone="warn"` titled `Folders that import each other` with the `cycleSentences`; cycle arrows are dashed and the box outline carries a text marker `⇄`, so colour is never the only signal.
  - A panel for the selected box: heading `Inside <label>`, its `boxSubtitle`, languages with levels, `file_list` as `path · N lines`, `top_functions` as `name · file:line`; for an `other` box, its `members`. Before any selection it says `Select a box to see what is inside it.`
  - `<details><summary>The arrows as a list</summary>` with every `arrowSentences` line (or `No imports between folders were found.`).
  - Under the picture, `mapNotes` as small muted lines.
  - Colours from existing tokens (`surface`, `border`, `accent`, `warn`, `muted`); no new CSS file.
- [ ] **Step 2:** Add `{analysis && <ArchitectureMap architecture={analysis.architecture} />}` after the `RepoSummary` line of `page.tsx`.
- [ ] **Step 3:** `npm run typecheck` (clean), `npm test` (all pass), `npm run build` with `NEXT_PUBLIC_API_URL=http://127.0.0.1:8100` (builds).
- [ ] **Step 4:** Commit: `git add frontend/src && git commit -m "Slice Z: the architecture map on the Repository page"`.

---

### Task 4: Browser steps and a look with your own eyes

**Files:**
- Modify: `frontend/e2e/run.mjs` (new steps at the **end** of the group headed `console.log("The repository")`, so earlier steps keep the page state they expect)

**Interfaces:**
- Consumes: the component's text hooks from Task 3; the existing `step`, `shot`, `folderBox()` helpers and `scratch`.

- [ ] **Step 1:** Write the new steps (they fail until Task 3 is built, so run them first against the build of Task 3 to see them pass; a step that passes on the first run proves nothing, so also break the page on purpose once and see it fail):
  - Create `shop-map/` in `scratch`: `pricing/core.py` (`def tax(): return 1`), `pricing/audit.py` (`from api.routes import route`), `api/routes.py` (`from pricing.core import tax` and a function), `web/app.py` (`from api.routes import route`), each package with an empty `__init__.py`.
  - `reading a repository with folders draws its map`: read `shop-map`; `How the code is laid out` heading appears; boxes `web`, `api`, `pricing` exist as `role=button`; the `Folders that import each other` warning names `api` and `pricing`; the path of `scratch` appears nowhere in the page text; `shot(page, "34-architecture-map")`.
  - `clicking a box shows what is inside it`: click `pricing`; `Inside pricing` and `pricing/core.py` appear; pressing Enter on the `web` box (focused with Tab/focus()) changes the panel to `Inside web`.
  - `the arrows can be read as a list`: open `The arrows as a list`; text `web imports api` is present.
  - `the map never makes the page scroll sideways at phone width`: `page.setViewportSize({width: 390, height: 800})`; `document.documentElement.scrollWidth <= 390`; `shot(page, "35-architecture-map-phone")`; restore the viewport.
  - Extend the existing GitHub-link step (flat 3-file repository) with `await page.getByText(/everything sits in one place/i).waitFor()`.
- [ ] **Step 2:** Run the whole suite as in Task 0 Step 3. Expected: **64 of 64** (60 + 4 new steps; the GitHub assertion is inside an old step).
- [ ] **Step 3:** Read `shot` images `34-architecture-map` and `35-architecture-map-phone` with the Read tool (set `E2E_SHOTS` to a scratch folder). Fix anything cramped, overlapping or clipped, and re-run.
- [ ] **Step 4:** Commit: `git add frontend/e2e && git commit -m "Slice Z: browser steps for the architecture map"`.

---

### Task 5: Real runs, deliberate breaks, docs, merge

**Files:**
- Create: `docs/architecture-map.md`
- Modify: `README.md`, `CLAUDE.md`, `docs/roadmap.md` (new row Z; update row D2 "Next"), `docs/repository-page.md`, `docs/ui.md`, `docs/try-it-yourself.md`, `docs/github-link.md` (one line: the map works for links)

- [ ] **Step 1: Real runs.** Start `python -m skillforge serve --port 8200` with `SKILLFORGE_DATA_DIR` set to a scratch folder, `POST /api/repos/analyze` on this repository (focus `backend`) and read the answer: the boxes should be the `skillforge` sub-folders and `tests`, with believable arrows. Then `analyze` the real link `https://github.com/jeswin4693/AISkills`. Write down box count, arrow count, cycles, and anything surprising (a surprise is a finding: fix it with a test first).
- [ ] **Step 2: Deliberate breaks** (change one thing, run the tests, expect a failure, restore): draw `guess` edges; count importers that are tests; call a basic-language box measured; replace the cycle grouping with a plain longest path; build ids from labels; remove the cap; draw same-folder imports; let `shortLabel` return the long name; remove the arrow-width clamp; drop the page's `overflow-x-auto`. Every break must be caught; a survivor gets a new test.
- [ ] **Step 3: Docs.** `docs/architecture-map.md`: what it shows, the rules (guesses and test imports left out, cycles as groups, cap and `(other)`), the answer's shape, the limits (imports only, a folder is a rough module, `basic` languages unmeasured, no history), what was checked (counts, real runs, breaks), and "no independent review yet". Add the roadmap row (same style as row Y), update the README status line and "What is next" item 4, the `CLAUDE.md` status paragraph ("Slice Z is built too") and its "Next" line (remove the drawn map), and the other docs listed above.
- [ ] **Step 4:** Full backend suite, `npm test`, `npm run typecheck`, then the e2e once more (expected 64 of 64). Check `git diff` has no `.env` and no key text.
- [ ] **Step 5:** Commit the docs; `git switch main`; `git merge --ff-only slice-z-architecture-map`; `timeout 75 git push origin main`.

---

### Task 6: One independent review of slice Y and slice Z together (only with your yes)

**Stop here and ask first: about 200k tokens and 15 minutes.** If yes: one fresh reviewer on the strongest model gets a source-only diff package (`git diff 0718db0..HEAD -- backend/skillforge frontend/src`), is briefed on slice Y (untrusted zip and path handling, link-parser bypasses, redirects and SSRF, size limits, cache races, Windows quirks, no link or path echoed) and slice Z (a wrong arrow, a guess drawn as proven, a path leaked, a hang or recursion on a deep or huge repository, markup in a folder name), and may not touch the real `.env` or use the network more than needed. Fix every reproduced finding test-first, then update the docs (`docs/github-link.md` and `docs/architecture-map.md` "Checked") and the memory file.
