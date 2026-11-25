# Design: the drawn architecture map (slice Z)

Date: 2026-11-25. Status: **approved by the user in conversation** ("Start to work", after the proposal below). Size: a small slice
(one backend function, one answer field, one page component), so this is the short design; the steps are in the plan.

## Intent and why

The Repository page reads a folder or a public GitHub link into the code graph, but shows only numbers and lists. The user asked twice
(in the Settings slice and the GitHub-link slice) for "paste a link and SEE the repo". This slice draws the repository's structure: its
top-level folders as boxes and the proven imports between them as arrows.

## Goals

- One picture of a repository: folders as boxes, arrows for proven imports, thickness for how many.
- Everything on it computed by code from the graph: no model, nothing run, same answer for the same repository.
- Honest labels: what is measured, what is not (languages without imports), how many guessed links were left out.
- Click a box to see its files and biggest functions.
- Works for a folder and for a GitHub link, because it rides on the existing `analyze` answer.

## Non-goals

- A function-level call graph (possible later: "click a box, see calls").
- Editing, dragging or saving the picture; exporting an image.
- Any new library. The picture is hand-written SVG.
- Runtime behaviour. Imports only say what a file *can* use, not what it does.

## Anti-goals (a failure even if it technically works)

- Drawing a `guess` link as if it were proven. Guesses never count (repository rule), so they are never drawn.
- A box or arrow that says more than the graph knows: a `basic`-level language has no imports, and must show as "imports not measured",
  never as "depends on nothing".
- Repeating the person's folder path anywhere in the answer (existing rule of the Repository page).
- An unreadable hairball on a large repository.

## Constraints (from the repository's rules)

- `backend/skillforge/graph` stays deterministic: no AI, links are `resolved` or `guess`, an ambiguous call makes no edge.
- No new library without clear value. The frontend has only Next and React, and every `npm install` needs the junction script.
- Tests are offline. The browser suite runs on ports 3100/8100, never on the user's 3000/8000.
- Every route that reads a folder is off in the hosted version; the map adds no new route, so nothing new to switch off.
- After the slice: tests pass; README, `docs/roadmap.md` and the slice's doc are updated; then commit and push.

## Approaches considered

| Approach | Trade-off | Verdict |
|---|---|---|
| **A. Folder boxes with import arrows, drawn as SVG by our own code** | Readable at any repo size, testable, no library; shows structure but not individual calls | **Chosen** |
| B. Every file as a dot, force-directed layout | Looks impressive; about 257 files already makes a hairball, needs a library, layout is not deterministic | Rejected |
| C. Function call graph around one picked function | Very useful, but zoomed in; does not answer "what does this repository look like" | Later, as part 2 inside a clicked box |

The user approved A, and the "no library, hand-written SVG" call, in the conversation.

## The design

**Backend.** A pure function `architecture(g)` in a new file `backend/skillforge/graph/architecture.py` (kept out of `query.py`, which is
already long) and a field `architecture` in the `analyze` answer (`builder/repository.py`, `analyze_repo`).

- A *module* is a file's folder, cut to the first level (`api`); files at the repository root form one module shown as `(root)`. If every
  file sits inside one folder (a `src/` or a `focus` folder), that common folder is stripped and reported as `base`, so the picture is not
  one box. **If that gives fewer than six boxes, the map goes one level deeper (`skillforge/api`), up to three levels**: found by the first
  real run, where this repository's `backend` folder was three boxes (`scripts`, `skillforge`, `tests`) and no arrows.
  Each box has an **id that is its position after sorting, not its name**, so a real folder called `(root)` or `(other)` cannot collide
  with the synthetic boxes.
- Per module: file count, lines, test-file share, languages with their level (full, standard, basic), symbol count, and whether any of
  its files has measured imports; the three biggest functions by size (name and place only).
- Arrows: for each `resolved` import edge between files of two different modules, one count per (from, to) of distinct file pairs.
  `guess` edges are not drawn; **imports written by a test file are not drawn either** (a tests folder would otherwise point at every
  box); the answer says how many of each were left out. A box whose files are all tests is marked `tests_only`.
- Cycles: a *cycle group* is folders that import each other, directly or through others (a strongly connected group, found by code). The
  answer names each group (the page shows a warning).
- Columns and back arrows: one left-to-right order. Cycle groups come in topological order, and inside a group the box that mostly imports
  comes before the one that is mostly imported (imports out minus imports in, within the group). An arrow against that order is a **back
  arrow** (drawn dashed): the weaker direction of a pair, the import that closes a loop; with no cycle there are none. A box's column is
  the longest chain of forward arrows that reaches it. Ties are broken by name, so the answer is the same every time. (The first design
  put a whole cycle group in one column; the first real run showed 11 of 14 boxes in one group, which made one column and a hairball.)
- A cap (about 14 boxes): the smallest modules beyond it fold into one `(other)` box that says what it holds.
- A repository where no language has measured imports returns the boxes without arrows and says "imports not measured".

**Frontend.** `components/repository/ArchitectureMap.tsx`, with layout helpers in `lib/architecture.ts` (pure, unit-tested), placed on the
Repository page under the numbers.

- Columns by level, boxes sized by file count within limits; arrows as curved paths whose width follows the count.
- Click or keyboard-select a box: a panel lists its files (first N) and biggest functions, with the box's language levels.
- A legend and the limits in plain words. Works at phone width (the picture scrolls inside its own frame, the page does not).
- Colours come from the existing theme; meaning is never colour-only (cycle = text and an icon as well as a colour).

## What is left to the builder

Exact box sizes, spacing, curve shape, the cap value and the colour tokens, as long as the rules above hold and the picture is readable at
390 px and at desktop width.

## How it is checked

- Backend unit tests on small synthetic repositories: grouping, root files, single-folder repositories, arrow counts, guess edges never
  drawn, cycle flag, basic-only language shown as "not measured", the cap and `(other)`, determinism (same answer twice), and no path
  anywhere in the answer.
- UI unit tests for the layout helpers; a typecheck.
- Browser steps in the real-Edge suite: the map appears for a folder, a click opens a box's panel, a cycle shows its warning, and the page
  does not scroll sideways at phone width.
- A real run on this repository and on a real GitHub link, with a screenshot read by eye.
- Deliberate breaks of each rule (the project's usual mutation check), then one independent review of this slice and slice Y together,
  after the user agrees to its cost.

## Honest limits to put on the page and in the docs

Imports only; a folder is a rough stand-in for a module; a language at `basic` level has no imports; a `guess` link is not drawn; the
picture is a view of the code as downloaded or read, not of a running system.
