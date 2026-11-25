# The architecture map (slice Z)

The **Repository** page now draws a repository: its folders as boxes, and the imports between them as arrows. It is computed from the
code graph by code (no model, nothing is run) and drawn as plain SVG by the page (no library). It works for a folder and for a public GitHub
link, because it is part of the same `analyze` answer. Plan: [superpowers/plans/2026-11-25-architecture-map-slice-z.md](superpowers/plans/2026-11-25-architecture-map-slice-z.md),
design: [superpowers/specs/2026-11-25-architecture-map-design.md](superpowers/specs/2026-11-25-architecture-map-design.md).

## What you see

```
 web  ━━━━▶  api  ━━━━▶  pricing        a solid arrow: files in the left folder import files in the right one
              ▲   ╰┄┄┄┄┄┄┄╯             a dashed arrow: points back against the main direction (it closes a loop)
```

- A **box** is a folder: its name, its files and lines, and a line saying `tests` or `imports not measured` when that applies. A box that touches
  a loop shows `⇄` (a text mark, so colour is never the only signal).
- An **arrow** is drawn from the folder that imports to the folder that is imported. Its **thickness and number** are the count of distinct file
  pairs. Dashed arrows are the ones that point back (right to left, or inside one column): the weaker direction of two folders that import each other.
- **Click a box** (or tab to it and press Enter) to see its biggest files and functions and the languages in it, and to light up its arrows while
  the others fade. This is how a crowded map is read: one box at a time.
- **The arrows as a list** says the same in words (`api imports pricing (3 file pairs)`), for every arrow, drawn or not.
- Under the picture, **notes** say what was left out and what is not known (below).

## The rules (all in code, all tested)

| Rule | Why |
|---|---|
| Only **proven** imports are drawn. A `guess` (a name match only) is never drawn or counted as an arrow; the page says how many were left out. | The graph's rule: guesses never count. |
| Imports **written by test files** are not drawn; the page says how many. | A tests folder would point at every other box. |
| Boxes are folders. If that gives **fewer than six boxes** the map goes one level deeper (up to three levels, `skillforge/api`). A folder every file sits inside (`src/`, or a `focus` folder) is stripped and named. | The first real run: this repository's `backend` folder was three boxes and no arrows. |
| More than **14 boxes**: the smallest fold into one `(other: N more)` box that lists its folders. | Readability. |
| A box's id is its **position**, not its name. | A real folder called `(root)` or `(other)` cannot be mistaken for a box the code made. |
| **Columns:** one left-to-right order. Folders that import each other (a cycle group) come in topological order; inside a group the folder that mostly imports comes first. A column is the longest chain of forward arrows. An arrow against the order is a **back arrow**. A repository with no loop has none. | The first real run: 11 of 14 boxes were one cycle group, and "a group shares a column" made one column and a hairball. |
| Boxes inside a column are **ordered by the boxes they connect to** (a few sweeps), to cut crossings. | Readability; deterministic. |
| At most **36 arrows** are drawn, the strongest; the page says how many weaker ones are only in the list. | Real run: 57 arrows were unreadable. |
| A **language whose imports are not read** is said to be "not measured", never shown as depending on nothing. That is the `basic` level **and C#**: C# is a `standard` language, but `using Acme.B;` names a namespace, not a file, so the graph makes no import link for it (found by the independent review: a C# solution had been drawn as folders that depend on nothing). The answer lists such languages (`imports_not_read`). | Never claim more than a language's level gives. |
| If one folder holds **more than 40% of the files** (and at least 20), the page names it and the exact text to type in "Only this folder inside it" to zoom in. | Real run on the whole repository: `backend/skillforge` was one big box. |
| The same repository always gives the same answer, whatever order the graph was built in. | Tested by building it in reverse order. |

## The answer (`architecture` in `POST /api/repos/analyze`)

`base` (the stripped common folder, or `""`), `modules` (per box: `id`, `label`, `kind` folder / root / other, `files`, `lines`, `test_files`,
`tests_only`, `symbols`, `languages`, `measured`, `column`, `top_functions` (3), `file_list` (12), `members`), `arrows` (`from`, `to`, `count`,
`back`), `cycles` (groups of box ids that import each other), `columns`, `measured`, `language_levels`, `imports_not_read` (the languages here whose imports are not
turned into file links), `left_out` (`guess`, `from_tests`) and `notes`. (`left_out.guess` is 0 today: every import link the graph makes is a proven one. The count is there so a
guess could never be drawn without being said; it will only show a number if a language's imports ever become guesses.) Names and paths are relative to the repository: **the person's own folder path is never in it** (tested). Code: `backend/skillforge/graph/architecture.py`;
page: `frontend/src/components/repository/ArchitectureMap.tsx` with the layout in `frontend/src/lib/architecture.ts` (pure, unit-tested).

## Limits (said plainly)

- **Imports only.** An arrow says files in one folder *can* use files in another, not what the program does when it runs. A folder is a rough
  stand-in for a module; a repository may be organised another way.
- **A language at the `basic` level, and C#, have no imports read**, so their boxes have no arrows. This is said on the page, never hidden.
- **A very connected codebase is still busy.** Arrows can pass behind boxes (they are straight between columns, not routed around boxes) and
  a wide map scrolls inside its frame. The 36-arrow cap, the ordering and click-to-highlight help; they do not make a dense project simple.
- A box is one **folder level** (up to three); there is no zoom on the picture itself. To zoom, type a folder in "Only this folder inside it".
- No function-level call graph, no history of how the structure changed, nothing is saved or exported as an image.
- It reads the code as it was downloaded or read; it says nothing about a running system.

## Checked

**Tests (2026-11-25).** Backend: 2,529 pass in all after the review's fixes and the Minor fixes (2,513 before them; 3 skipped: this account cannot create symbolic links), 27 of them new for this slice: 26 in `tests/test_architecture.py`
(graphs built by hand, so a guess link, a test file that imports, a language whose imports are not read, a hundred folders and a folder called `(root)` are exact) and one in
`tests/test_repository_api.py` (a real repository through the real `analyze` route, with no path in the answer). UI: 216 unit tests, 29 of them new
(`lib/architecture.test.ts`), and a clean typecheck. Browser: the real-Edge suite is **64 of 64** on free ports (60 before this slice, which was also the re-run slice Y still owed, plus
four map steps: the map with its cycle warning and no path on the page, a click and the keyboard with the faded arrows counted, the arrows as a list, and phone width with no sideways
scroll; the GitHub step now also checks that a flat repository says it is one box). The screenshots were read by eye.

**Deliberate breaks: 33, all caught (and 12 more on the review's fixes and 7 on the Minor fixes after it, also all caught).** Eighteen on the page's code (shortening a label, the width clamp, the dashed arrows, the frame margin, opposite arrows on one curve, an arrow
ending at the wrong edge, overlapping boxes, the cycle-name cut, the `tests` tag, the base folder note, the imports-only note, no reordering, no arrow cap, the weakest arrows drawn
instead of the strongest, and four on the zoom-in hint and the hidden-arrow count) and fifteen on the backend (a guess drawn as proven, test imports drawn, every box "measured",
no back arrows, a box id equal to its name, no cap on boxes, arrows inside a folder, the order inside a loop ignoring the weights, loops taken sinks first, unsorted arrows, a level
search that never stops early, no limit of three levels, the shared folder never stripped, test functions listed as biggest, and a box listing every file). **Two survived the
first run and got tests:** no arrow in the last column ever exercised the frame's margin, and opposite arrows had been kept apart only inside one column, not across columns.

**Real runs found three things nothing else did.**

1. This repository's own `backend` folder (read through `analyze_repo`): three boxes (`scripts`, `skillforge`, `tests`) and **no arrows** (368 imports from tests left out).
   Fewer than six boxes now means one level deeper.
2. The same run after that: **11 of the 14 boxes were one cycle group.** The first design put a whole group in one column, which made one column and a hairball. It was prototyped
   on the real answer before it was built: one order (groups topologically, inside a group more imports out than in first) gave six columns, with 16 back arrows carrying
   42 of the 256 file pairs. Ordering by import counts alone was rejected on paper (it would call an arrow "back" when nothing loops) and a test pins that.
3. In real Edge, a solid arrow and its dashed opposite lay **exactly on top of each other** (they looked like one line with two arrowheads). No assertion had said so; reading the
   screenshot did. The same look at the 14-box map (57 arrows) added the neighbour ordering inside a column, the 36-arrow cap, click-to-highlight and the zoom-in hint.

Also run: the same answer for the public link `jeswin4693/AISkills` (265 files, 365 test imports left out): eight boxes, `backend/skillforge` one big box holding 128 files, which is
what the zoom-in hint is for; and the page with `skillforge` as the focus folder, where the boxes become `api`, `library`, `build` and so on and 24 weaker arrows are left to the list.

**One independent review (2026-11-25, together with slice Y; about 142,000 tokens).** A fresh reader on the strongest model read the whole of `graph/architecture.py` and the layout and page code, and wrote
its own probes. **No Critical finding.** What it confirmed: the iterative Tarjan, the topological order and the columns are correct (300 random graphs gave the same answer whatever order the arrows came in, every loop-free
graph had zero back arrows and every arrow pointed right), arrow direction is right on real Java, Go and Python repositories, imports from tests are counted and not drawn, and no path appears in the answer (checked on four real graphs).
**One Important finding, reproduced and fixed test-first:** C# is a `standard` language but its imports are never turned into file links, so a C# solution was drawn as folders that depend on nothing and the page said "No imports
between folders were found". Boxes now say "imports not measured" for it, the answer lists `imports_not_read`, and a test pins that every language whose imports *are* mapped stays measured (so nothing is over-excluded). The fix was broken on purpose
(C# counted as measured again; the note not written) and both breaks are caught.
**Two Minor findings, fixed afterwards:** in a loop of three or more folders the box in the middle got no `⇄` mark although the warning named it (the mark was drawn from the back arrows only). Now **every folder of a loop gets the `⇄` mark**, and only the
folders at the ends of a back arrow (the arrows that close the loop) keep the warning outline, so a repository where most folders are tangled together does not turn into a wall of warnings (`loopMarks` in `lib/architecture.ts`, unit-tested and broken on purpose);
and `left_out.guess` is always 0 today, which was only said in prose: a test now builds real graphs (Python, TypeScript and Java, with an `import util` that could mean either of two files) and asserts that **every import link the graph makes is proven**, so if a
language ever makes a guessed link that test fails and this document needs a second look. **Not reached by the reviewer:** the page at phone width and real keyboard focus (both were checked by me in the browser suite), and the Linux and macOS case rules.

**Not verified:** macOS and Linux; a very large repository (the work is linear in files and edges and nothing was timed on a huge one); a screen reader (boxes are buttons with
names and keyboard use, and the arrows have a text list, but it was not tried); any browser but Edge.
