# The function-level call graph (slice AL)

Under the folder map, the **Repository** page now has **Who calls what**: search the repository's functions, pick one, and see the functions that **call it** on the left and the functions **it calls** on the right,
one step or two. It is computed from the code graph by code (no model, nothing is run) and drawn as plain SVG, like the map above it. It works for a folder and for a public GitHub link, and is off in the hosted version
with every route that reads a folder. Design: [superpowers/specs/2026-11-27-function-graph-design.md](superpowers/specs/2026-11-27-function-graph-design.md).

## What you see

```
 called by                  the function               calls
 ┌──────────────┐         ┌───────────────┐         ┌──────────────┐
 │ handle       │ ━━━━━━▶ │ checkout      │ ━━━━━━▶ │ price        │
 │ web.py:3     │         │ shop.py:3     │         │ shop.py:3    │
 │ 0 callers... │         │ 1 caller...   │         └──────────────┘
 └──────────────┘         └───────────────┘         ┌──────────────┐
                                    └━━━━━━━━━━━━━▶ │ audit        │
                                                    └──────────────┘
```

- A **box** is a function, method or class: its name, where it is (`folder/file.py:line`), and its own proven callers and calls (`2 callers · calls 3`, and `· 3 tests` when test functions call it).
  A function in a test file has a dashed border; one that is both a caller and a callee of the chosen function is drawn once, on the callee side, with `⇄`.
- An **arrow** is a call, from the caller to the callee; its thickness and number are the **call sites** written. A call that goes against the left-to-right order (a callee that calls one of the callers) is dashed.
- **Click a function** in the picture (or tab to it and press Enter) to look at that one next; **Back** returns along the way you came. **One step / Two steps** chooses how far to follow.
- **Find a function** searches by part of a name; **start from a function many others depend on** lists the most depended-on functions the page already knows (the hotspots).
- **The calls as a list** says the same in sentences (`handle calls checkout`), for a screen reader and for a crowded picture. Under the picture, **notes** say what was left out.

## The rules (all in code, all tested)

| Rule | Why |
|---|---|
| Only **proven** calls (`resolved`) are drawn. A call matched by name only (`guess`) is **counted and said**, never drawn, and never counted in a function's totals. | The graph's rule: guesses never count. |
| A language whose calls the graph does not read (the `basic` level) is **"not measured"**: the picture is the function alone and says so. It is never "called by 0". | Never claim more than a language's level gives ([languages.md](languages.md)). |
| Functions in **test files** that call something are **counted, not drawn** (they show it is tested, not how the program works), unless the function chosen is itself a test. A function's own totals keep the two apart (`callers_total`, `tests_total`). | The same rule the folder map and the guide use. |
| **Caps**, strongest first: at most 20 functions a side over both steps, 10 neighbours of the chosen function, 5 of each function two steps away. Strongest = most call sites, then name, then id, so the cut is stable. What was cut is **counted** (`over_limit`) and the note says how to see it (click a function). | A real repository has thousands of functions; a picture of all of them is a hairball. |
| A function reached by two paths, or on both sides, is drawn **once**; the chosen function is never its own neighbour. | A node is one function. |
| Between the functions that are drawn, **every proven call is an edge** (not only the ones that led to them). | The picture shows the real shape, including a caller that also calls a callee. |
| The same graph gives the **same answer**, whatever order it was built in: nodes by column then name, edges by their ends. | Tested by building the graph in reverse. |
| A call a function makes to **itself** is not drawn: the graph does not record one (`build.py` skips it). | Said in Limits. |

## The answer (`POST /api/repos/functions` and `POST /api/repos/calls`)

Both take the same `path` and `focus` as `repos/analyze`, so a folder and a GitHub link both work. Neither sends the person's folder back (names and ids are relative to the repository), and a bad path, a blank search, an unknown
function or a depth other than 1 or 2 is a plain 400 or 422 in words.

* **Search** (`query`, at most 200 characters) answers `name`, `focus`, `query`, `total` and `matches` (at most 25): `id` (`file::name`), `name`, `kind`, `file`, `line`, `test`, `callers`, `callees` and `measured`.
  The order: an exact name, then a name that starts with the text, then one that contains it, then a file path that does; code before tests; then the most callers.
* **Calls** (`symbol` = an `id` from the search, `depth` 1 or 2) answers `subject`, `nodes` (each: `id`, `name`, `kind`, `file`, `line`, `lines`, `test`, `role` subject / caller / callee / both, `column` from -2 to 2,
  `callers_total`, `tests_total`, `callees_total`), `edges` (`from`, `to`, `count`), `depth`, `measured`, `language`, `level`, `calls` (`written` call sites in the function, `tied` of them tied to a function in the repository) and
  `left_out` (`guess`, `from_tests`, `over_limit`).

Code: `backend/skillforge/graph/callgraph.py` (pure functions on the graph), `builder/repository.py` (`find_functions`, `explore_calls`), `api/repos.py`; page: `frontend/src/components/repository/FunctionExplorer.tsx`
with the layout and the wording in `frontend/src/lib/callgraph.ts` (pure, unit-tested; it reuses the folder map's curve and arrow thickness).

## Speed: the graph is kept in memory

Moving from one function to the next is a series of requests about one repository. A real run on this repository showed the cost: **about 3 seconds per click** (the graph was read again each time: about 1 second even with the on-disk cache,
and about 3 seconds with a focus folder, which the on-disk cache does not cover). `builder/graphcache.py` keeps the **last two graphs** in memory and uses one **only while every file is exactly as it was** (the same names, sizes and
modification times: the test the on-disk cache already applies). The fingerprint is taken **before** the graph is read, so a file that changes during a read leaves an older fingerprint behind and the next request reads again,
never the other way round. The graph is shared by requests that run at the same moment, so its lookup tables are built before it is kept and nothing in the explorer changes it. After the change a click took **0.2 to 0.3 seconds**.
History from git is not read (the explorer does not use it). `analyze` is unchanged and does not use this cache.

## Checked

**Tests (2026-11-27).** Backend: 4,044 pass in all (4 skipped: this account cannot create symbolic links), 77 of them new: `tests/test_callgraph.py` (51: graphs built by hand, so a guess call, a test that calls, a basic language, the caps, a mutual call
and the build order are exact), `tests/test_callgraph_api.py` (12: the real routes through the real app, no path in any answer, a plain 400 or 422 for bad input, the focus folder, off when hosted) and `tests/test_graphcache.py` (14: a hit skips the read, an
edit of any kind, a rename, an added or removed file and a change during the read each read it afresh, only two graphs are kept, twelve threads reading one kept graph all get the same answer). Web: 499 unit tests, 29 of them new
(`lib/callgraph.test.ts`), and a clean typecheck. Browser: the real-Edge suite is **115 of 115** on side ports (5 new steps in `e2e/run.mjs`; the first run had one failure, my own selector matched two sentences, fixed).

**Deliberate breaks: 69, all caught in the end.** 30 on `callgraph.py`, 13 on `graphcache.py` and 26 on `lib/callgraph.ts`. **The first rounds let 13 through, and every survivor was a weak test of mine:** my cap test used call counts that happened to fall in
name order, so "strongest first" and "by name" looked the same; the side-cap test compared against the very constant it was checking; nothing looked at the order of the answer or at a mutual call two steps out; the cache's tests only changed a file's
content, never its size alone, its name alone, or a failing listing; one of my breaks was not a break at all (it still took the fingerprint before the read); and nothing pinned the picture's width, its height or the shortening of a name.

**A real run (2026-11-27, this repository's own code, through the real routes):** the answer matched the source (`find_symbol` is called by `_calls_query`, `find_path` and `impact`, and it calls `find_symbols` and raises `QueryError`), no path was in it,
**and the run showed each click took about 3 seconds**, which is why the graph is now kept in memory (0.2 to 0.3 seconds after). A look at the screenshots found nothing to change.

**Not verified:** a repository of thousands of files (every click walks and stats every file to be sure nothing changed), macOS and Linux, a screen reader (the functions are `role=button` with names and keyboard use, and the picture has a text list), any browser but Edge,
a C#, Java or Go repository on the page (the rules are tested with hand-built graphs, not with a real repository in those languages), and an independent review.

## Limits (said plainly)

- **Calls the graph can prove, nothing more.** A call through a variable of unknown type, a callback, reflection or dynamic dispatch is not seen; a function that looks unused here may be used that way ([graph.md](graph.md)).
- A language at the `basic` level has **no calls at all**; a `standard` one has resolved and guessed calls and only the resolved ones are drawn.
- A function that calls **itself** (recursion) is not drawn.
- A picture shows **one function and two steps**, not the whole call graph, and the caps leave out the weakest neighbours (counted and said).
- Arrows are curves between columns and can pass behind a box in a dense picture; the list under it is the complete twin.
- The graph is the code **as it was read** (a folder as it is now, a GitHub link as it was downloaded); nothing says what happens when the program runs.
- For a **GitHub link**, each click uses the downloaded copy that is current when it is made (a copy is reused for 15 minutes, as everywhere else); after that the next click downloads the repository again, so a long session can
  show the code as it is later than the map above it. A folder is read as it is now.
- Only the **last two** repositories are kept in memory; the third makes the first read again (the answer is the same, only slower).
- Needs the local app (off in the hosted version, like every route that reads a folder).
