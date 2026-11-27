# The function-level call graph (slice AL): design

Status: written 2026-11-27 for the owner, who asked to "start the next phase of development" and did not answer the one question about why they want it.
Everything below that is not a rule of the project is **my call**, said as such, and can be changed.

## Intent (my reading)

The Repository page draws folders and the imports between them (slice Z). The graph underneath already knows every function and method and every
call between them (`graph/model.py`: `Symbol`, `Edge`), and the command line already answers `graph callers`, `callees` and `impact`. What is missing is
**seeing it**: pick a function, see who calls it and what it calls, so a person can judge what a change to it could reach before making it.

## Goals

- Search the repository's functions by name; pick one.
- Draw that function with the functions that call it (left) and the functions it calls (right), **one level or two**, as plain SVG like the folder map.
- Click a drawn function to move the view to it (and a Back button), so a person walks the call graph one function at a time.
- Start from the most depended-on functions the page already lists.
- Say plainly what was left out and what is not known.

## Non-goals

- No picture of the whole call graph (thousands of functions are unreadable; the folder map already needed caps).
- No model: everything is computed by code from the graph. Nothing is run. Nothing is saved or exported.
- No new library, no new table, no new setting.
- No change to the graph itself (`resolve.py` and the extractors are untouched).

## Anti-goals (would make it a failure even if it "works")

- A guess (a name-only match) drawn as a call. **Only proven (`resolved`) calls are drawn;** guesses are counted and said, never drawn.
- A language whose calls are not measured (the `basic` level) shown as "no callers". It says "not measured".
- Test functions that call a function drawn as if they were part of how the program works. They are **counted, not drawn**, unless the function chosen is itself a test.
- A person's own folder path in any answer.

## Constraints (project rules)

- The graph is deterministic: the same repository gives the same answer, in the same order, whatever order the graph was built in.
- Off in the hosted version like every route that reads a folder; works for a folder and for a public GitHub link (same `path` box).
- The page must never claim more than a language's level gives (`full`, `standard`, `basic`, `docs/languages.md`).
- Tests are offline; graphs are built by hand in the backend tests.

## Approaches considered

| | What | Trade-off |
|---|---|---|
| **A. Zoom explorer (chosen)** | Search, pick one function, draw callers and callees to depth 1 or 2, click to move. | Small, readable, answers "what does a change here reach?". Needs one server round trip per move (the graph is cached on disk, so a move is cheap). |
| B. Whole-project graph | Draw every function and every call. | The folder map needed caps at 14 boxes and 36 arrows; a real repository has thousands of functions, so it would be a hairball. |
| C. A text list only | Callers and callees as lists in a page. | The command line already does this; it does not add what the page is for. A text list is kept as the accessible twin of the picture. |

## Decisions (my calls)

- **Server:** two routes next to `POST /api/repos/analyze`, both taking the same `path` and `focus`: `POST /api/repos/functions` (search by name) and
  `POST /api/repos/calls` (one function's neighbourhood, `symbol` = a graph id from the search, `depth` 1 or 2). Both read the graph through the same
  cached `build_graph`; nothing is stored on the server.
- **Module:** `graph/callgraph.py` (pure functions on a `RepoGraph`), used by `builder/repository.py`.
- **The answer** (`calls`): `subject`, `nodes` (each with `role` subject / caller / callee / both, a `column` from -2 to 2, its own totals of proven callers and callees,
  so the page can say "3 more not drawn"), `edges` (`from`, `to`, `count` = call sites), `depth`, `measured`, `language`, `level`, `calls` (`written` = call sites
  written in the function, `tied` = those tied to a function in the repository), `left_out` (`guess`, `from_tests`, `over_limit`).
- **Caps** (readability, all said on the page when they bite): 20 functions each side, 10 neighbours of the chosen function, 5 of each function two steps away, 25 search results.
  The strongest first (most call sites, then name), so the cut is stable.
- **Ranking in the search:** exact name, then a name that starts with the text, then a name that contains it, then a file path that contains it; non-test code before tests; then the most callers.
- **A function that calls itself** is not drawn: the graph does not record a call to itself (`build.py` skips `target.id == sym.id`). Said in Limits.
- **A node that is both** a caller and a callee of the chosen function is drawn once, on the callee side, and the edges show both directions.
- **Page:** a section "Who calls what" under the folder map, inside the Repository page. Dashed arrows for a call that goes against the left-to-right order. The picture has a text twin
  ("Called by" and "Calls" lists).

## Left to the builder

Exact box sizes and spacing, the wording of notes, the unit-test list, and how the layout handles a column with many boxes.
