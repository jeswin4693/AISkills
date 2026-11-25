# How it works: a guided diagram for new developers (slice AB)

The **Repository** page can now explain a project to someone new to it. A model reads the README and the docs and proposes the project's **parts**, the **layers** they sit in, and the **routes** an
action takes through them ("build a skill": the page, the API, the builder, the AI engine, the sandbox, the library). Then **code decides what is kept**: a part or step stays only if the sentence
it quotes is found, word for word, in the documents. What the graph knows is added: how big each part is, which files and functions to read first, and whether each step of a route is something
the code really imports. It works for a folder and for a public GitHub link, and from the command line.

Design (and the mockups it grew from): [superpowers/specs/2026-11-25-how-it-works-design.md](superpowers/specs/2026-11-25-how-it-works-design.md).

## What a person sees

```
 [Build a skill]  [Read a repository]  [Install from the library]        buttons: one per action the docs describe

 The route: Build a skill
  (1) Web page     You describe the skill.
        ┆  From the docs only          a web request is not an import, so the code cannot confirm it
  (2) Local API    Receives the request.
        │  Confirmed by the code       the files of one really import the files of the other
  (3) Builder      Asks questions, checks every answer.

 THE DOORS IN     [ (2) Local API ]
 THE WORKERS      [ (3) Builder ]  [ Library ]  [ HTTP transport: in the docs, not found in the code ]
 SHARED SERVICES  [ AI engine ]    [ Sandbox ]
 THE OUTSIDE      [ Model providers: outside this repository ]

 ┌ AI engine ── Quote found: README.md, line 41 ── In the code ── 12 files · 1,840 lines ┐
 │ What it does · Goes in, comes out │ Read these first (files, functions) │ Where the docs say so │ In plain words (not checked) │
 └────────────────────────────────────────────────────────────────────────────────────────────────┘
```

* **Layers (the bands)** are fixed: *What people use*, *The doors in*, *The workers*, *Shared services*, *The outside world*. A band with no part is not drawn.
* **The buttons on top** are the journeys. Each one numbers its own route through the same layers; parts that are not on the route fade.
* **A hop** (the link between two steps) is one of seven things. Only the first is proof, and it comes with the numbers: how many file pairs, and one of them (`web/app.py imports api/routes.py`), so a reader can judge it:

| Hop | Meaning |
|---|---|
| **Confirmed by the code** (solid) | Files in the first part really import files in the second (a proven import, never a guess). Files in a folder of tests, fixtures or a test server (`e2e`, `tests`, `spec`, ...) are not counted. |
| Imports both ways | Each way has imports. The two counts say which is stronger (for example 1 one way and 6 the other). |
| The code imports the other way | The docs say this order, the code imports from the second into the first (a callback, an event). |
| One folder | Both parts are the same folder, so imports cannot tell them apart. |
| Not measured | A language here has no import links the graph reads (the `basic` level, and C#). It is never called "not imported". |
| A step between was dropped | A step the model put between these two failed the quote check, so the two are not shown as joined by anything the docs said. |
| From the docs only | The docs say so and the code does not import it directly (a web request, a message). |

* **A part's status:** *Folder found in the code* (the folder the model named is in the graph: that is all that was checked, not that the part lives there), *In the docs, not found in the code* (the docs name
  it, or the folder it was given is not there), *Outside this repository* (a service, by nature).
* **A quote that does not even mention its part** (no word of the part's name, id or folder is in it) is kept but flagged, in the panel and on the route, because the check that it exists in the docs says nothing about
  whether it is about that part.
* **Click a part:** what it does, what goes in and out, **the files and functions to read first** (from the graph, never tests), the quote and where it is (`README.md, line 41`), and a **plain-words picture**
  that is labelled *model's words, not checked*.

## The pipeline

```
documents (README, ARCHITECTURE, CLAUDE.md, AGENTS.md, docs/**)   guide/docs.py        read safely, best first, capped
folders of the code (a parser's list, with file counts)           guide/prompt.py      the only names the model may use for "folder"
        │                                                                              the documents are fenced and untrusted
        ▼
ONE model call  (Task.GUIDE, tier DESIGN)  ->  GuideDraft         guide/models.py      parts, journeys; flat schema built from the fields
        ▼
checks by code                                                    guide/verify.py      quote looked up, folder looked up, ids safe, caps
        ▼
the answer: layers, parts (+ what the graph knows), journeys (+ a status per hop), what was dropped, notes
```

`guide_repo` (`builder/guides.py`) resolves the folder or link, reads the documents, builds the graph (no history), asks the model once and returns the answer; the API route and `skillforge guide` both
call it. **One request, nothing saved**: a guide is one model call, so it needs no run row or migration. The request waits for the model; asking again asks the model again.

## The rules (all in code, all tested)

| Rule | Why |
|---|---|
| A part or a step stays only if its **quote is found word for word** in a document. The document and the line are worked out by code; the model's own idea of the source is not used. | Models answer, code judges. An invented component is the worst failure: it looks complete. |
| A quote must lie **inside one paragraph** (a blank line, a heading, a list item, a table row or a code fence starts a new one, so a quote cannot join a heading to the text under it, or two paragraphs) and must **start and end on whole words**. It is compared **after** inline marks (backticks, `*`), invisible characters (a right-to-left override cannot reach the page), white space, curly quotes and long dashes are made plain, and after a list marker or heading mark the model copied is removed. Case and word order are exact. 20 to 400 characters, at least 4 words. | Fair to how a model copies from rendered text; not so loose that a fragment such as `eb page sends ev`, or two unrelated sentences glued together, passes. (The independent review found exactly that.) |
| A **folder** a part names is looked up in the graph (whole names, not a prefix of one). A leading `/` or `./` is dropped (the path is read from the repository's top); a path with a drive or any `:`, or with `..`, is never followed. No folder, or one that is not there: *in the docs, not found in the code*. A part in the outside layer with no folder is *outside*. | The model never invents code. A missing part is information for a new developer, so it is shown, not hidden. |
| A hop is **confirmed** only by a proven import between the two parts' own files: never a test, never a file in a folder of tests, fixtures or a test server, never a guess. When the code also imports the other way it says **both ways**, with the counts. When a step was dropped between two steps, the hop says so instead of joining them. | The graph's rule: guesses never count. A real run on this repository found a hop "confirmed" by one import from the browser test's fake server, and another with 1 import one way and 6 the other. |
| Ids are made by code (`p1`, `p2` ... in order); a repeated or unusable id is dropped; at most **16 parts, 4 journeys, 8 steps** each; a journey needs **two checked steps**; the same part twice in a row is one step. | Readability, and a hard bound on what a model can put on the page. |
| The model's own words are **cleaned** (control and invisible characters out, white space collapsed) and **cut** (name 60, a line 200, plain words 300 characters), and shown as text, never as markup. | The page renders model text as data only. |
| The documents are **untrusted**: fenced in the prompt, a closing tag inside one is broken, the system prompt says never to follow them. Whatever the model returns can only be **kept or dropped** by code. | A hidden instruction cannot add a part the documents do not support. (A model that obeys it could still quote the instruction itself: see the limits.) |
| Documents are read only if they are **regular files inside the repository**: no symbolic link or junction that leads out, no binary, nothing over 400 KB, at most **12 files, 24,000 characters each, 60,000 in all**. The order is README, ARCHITECTURE, CLAUDE.md and AGENTS.md, pages in a `docs` folder that explain the structure (`architecture`, `overview`, `design`, `how-it-works`, ...), other READMEs, then the rest by name (case does not decide). A focus puts the documents inside it first and nothing else: it is compared as text and never looked up on the disk. At most 3,000 folders are searched. Every path in an answer is relative. | Safety and cost. The first real run chose among 52 pages alphabetically and read a prompt file before the architecture pages. |
| No README or docs: the answer says so and **no model is asked**, so no key is needed. | Cheap and honest. |
| Fewer than **two checked parts**: `thin`, nothing is drawn, and the page says so. | A near-empty diagram would mislead. |
| The call names its task (`Task.GUIDE`) and goes through the AI service. | One model service: retries, budget, usage, redaction. |
| A model that says the request is too big (`input_too_large`) is asked again with **half, then a quarter** of the documents' text; any other failure is shown at once. Decided by the error's kind, never by its words. | A backup with a small limit can still answer a smaller request. |

## GitHub copies now keep documents

Until now a downloaded copy kept only source files, so `README.md` was thrown away (`not_source`). It now keeps **README and doc files too**, chosen by the same rule and the same order the folder reader uses
(`guide.docs.is_doc_path` and `sort_key`, both counted from the top of the repository): a `README*` in the first three folders, `ARCHITECTURE`, `CLAUDE.md` and `AGENTS.md` at the top, and text files (`.md .markdown .rst .txt .adoc`)
inside a `docs` folder that is one of the first three. They have **limits of their own** (60 files, 200 KB each, 3 MB in all), so they can never use up the source limit, **documents alone are still "no source"**, and every safety
rule for names still applies. When a cap would cut some, **the best are kept first**, however the archive happens to order them (the independent review showed a lowercase `readme.md` being pushed out by 70 pages under `docs/`).
The graph ignores them. A snapshot records how many it kept (`docs`); one made before this change has no record, so a guide **downloads it again**. The Repository page's source summary carries the count.

## The API and the command line

`POST /api/repos/guide` takes `{"path": "<folder or GitHub link>", "focus": "src"}` and returns the answer: `status` (`ok`, `thin`, `no_docs`), `name`, `source`, `docs` (what was read), `layers`, `parts`
(`id, name, layer, summary, takes_in, gives_out, plain, folder, status, files, lines, read_first, quote`), `journeys` (`title, steps, hops`), `dropped` (what and why), `notes`, and the model used. 400 for a bad path or link,
**502 when the model could not be used** (no key, no quota, unreachable) or GitHub could not be reached, **403 in the hosted version** (it reads a folder). No path of the person's is in it (tested).

```powershell
python -m skillforge guide <folder-or-link> [--focus src] [--json]    # needs a provider key, unless there is nothing to read
```

The outline lists the layers, each part with the quote behind it, and each route with what is known about every hop. A link's download note goes to stderr, so `--json` stays JSON.

## Limits (said plainly)

* **A kept quote is in the documents. That is all it proves.** It does not prove the quote is *about* that part, that the documents are up to date, or that the model's summary, in/out words and plain-words
  picture are right: those are shown as the model's own. Read a part's panel against the files it points at.
* **A model that obeys an instruction hidden in a document can still quote that instruction.** The quote would be real, so it would be kept. The checks stop invented parts, not a model that has been talked into
  following the documents too literally.
* **The routes are only as good as the documents.** A project whose README says nothing about how an action flows gets layers and no route. A hop the code cannot confirm is shown as *from the docs only*, which is
  often right (a web request, a queue); it is a statement about the checker, not about the project.
* **"Folder found" is all that is checked about where a part lives.** The folder is one the model chose from a list the parser made; that it exists does not prove the part lives there. A quote is also only flagged, not
  judged, when it does not mention its part.
* **Imports are the only proof.** A route through a language whose imports are not read (basic, C#) is *not measured*. Two parts in one folder are *one folder*. A hop shows a few file pairs so a reader can see
  whether they are the real link, and files in a folder named for tests or a test server (`e2e`, `tests`, `spec`, `fixtures`, `mocks`, `testing`) are not counted; a test server in a folder with another name still would be.
  (The architecture map of slice Z applies the same rule, from one shared function: it first drew a `frontend/e2e` to backend arrow that came only from the browser test's fake server, which this guide's first real run showed. See [architecture-map.md](architecture-map.md).)
* **The page guides the repository that was last read**, not what the box says now, and ignores an answer that comes back after another read.
* **One call, nothing saved.** It waits for the model (seconds to about a minute), uses a little quota each time and is not remembered after a reload. Documents beyond the caps are not read, and a long one is cut (the page says so).
* **Strict quoting costs some real parts.** When a model paraphrases instead of copying, a part that really exists is dropped (the real GitHub run lost "Docker Sandbox" and "Web User Interface" this way). Every drop is
  listed on the page with its reason, and asking again often brings them back.
* **The prompt is large**: up to about 15,000 tokens (60,000 characters of documents). A backup model with a small per-minute limit cannot take that (the first real GitHub run's Groq backup refused 16,700 tokens against 8,000 per minute
  while Gemini was overloaded). So when a model says the request is too big for it (the typed error kind `input_too_large`, see [ai-engine.md](ai-engine.md)), the guide **asks again with about half, then a quarter, of the documents' text**
  (`shrink` in `guide/docs.py`: the best documents stay whole, the one that does not fit is cut and says so, the rest are counted as left out). The page says "only about 50%" (or 25%), shows the documents that were really given, and the quotes
  are checked against what the model was given, so a part that leans on the cut-away text is dropped, not kept. After the quarter the error is shown. Parts that need the text that was cut may be missing: ask again when the first model is back.
* Off in the hosted version, like every route that reads a folder. No function-level call graph, no image export.

## Checked

**Tests (2026-11-25).** Backend: **2,772 pass** (4 skipped: three symbolic-link tests and one more of mine, because this account cannot create symbolic links; 2,569 passed before this slice), 204 of them new:
108 in `tests/test_guide.py` (the quote rules, parts, journeys, every kind of hop, the prompt, the whole run), 77 in `tests/test_guide_docs.py` (which files are documents, reading them safely, what a GitHub copy keeps, a real
junction) and 19 in `tests/test_guide_api.py` (the API for a folder and for a link, and the command line). Documents and graphs are built by hand and the model is a `MockProvider`, so nothing depends on what a real model says.
UI: **237 unit tests** (216 before; 21 new in `lib/guide.test.ts`) and a clean typecheck. Browser: the real-Edge suite is **72 of 72** on free side ports (64 before, plus eight steps: no README says so and asks no model; the layers,
the numbered route and its hops; a part the code lacks and one outside the repository; a click shows where to start reading and that the plain words are not checked; another action and a hop only the docs describe; phone width with no
sideways scroll; the guide is drawn for the repository that was read, not for what the box says now; reading again clears it). The screenshots were read by eye.

**Deliberate breaks: 57, all caught.** The first round (37 breaks, before the review) caught 34; two survived and one could not be applied. After the review's fixes the list has a break for every rule, the new ones included:
55 were caught on the first run, and the 2 that survived were tests that could not tell a rule from its absence (a three-word quote that is long enough, and a list marker that stays in the text and so blocks a match either way).
Both tests were strengthened and every break is now caught. Two earlier survivors taught something too: a guard that could never be reached (a test file's import can never match, because a part's files exclude tests) was removed, and a
test of a focus that leaves the repository used a folder that did not exist (the rule was later replaced: a focus never touches the disk).

**One independent review (2026-11-25)**: a fresh reader (no Critical, 3 Important, 5 Minor; about 130,000 tokens, 14 tool calls, six proof scripts of its own). Two of the Important findings were reproduced again before fixing. All eight are fixed, test first:
**I1** a quote only had to be a substring, so `eb page sends ev` or a heading glued to the next paragraph passed and a made-up part survived (now: inside one paragraph, whole words, 20 characters and 4 words, and a quote that does not mention its part is flagged);
**I2** a GitHub copy could drop the root README, because 70 pages under `docs/` came first in the archive and the cap kept the first 60 (now: best first, one rule and one order for the unpacker and the folder reader); **I3** the page could show a guide for a different
repository than the map (now: the last read repository, and a late answer is ignored); **M1** a dropped middle step silently joined its neighbours (now: "a step between was dropped"); **M2** a reversed-text character could reach a quote (now dropped on both sides);
**M3** a link and a folder disagreed under a focus (now one rule counted from the top; a focus only changes the order); **M4** a junction test (it refuses a junction that leads outside); **M5** the document name in the prompt tag is escaped, the action buttons are plain
toggle buttons instead of half-built tabs, and "In the code" became "Folder found in the code".

**Real runs (2026-11-25, this repository's own docs, which are public; Gemini `gemini-3.5-flash-lite`).** They found three defects no mock showed:
1. The first run (a folder) drew **10 parts and 2 routes, nothing dropped**, and showed **Web UI to Local API as "confirmed"**: the only import was `frontend/e2e/mock_server.py`, the browser test's fake server. Files in folders named for tests or a test server no longer count.
2. **Model Service to Build Engine was "confirmed" with 1 import one way and 6 the other.** It now says "imports both ways" with the counts and an example. The two hops were replayed on the real graph with the fixed code: now "from the docs only" and "both ways, 1 and 6".
3. With 52 doc pages and room for a few, the pages were taken **alphabetically**, so a prompt file came before the architecture pages. Pages named for structure now come first.

After the fixes, a second run (a folder) drew 5 parts and 1 route (the model varies between runs), read `README.md`, `CLAUDE.md` and the two architecture pages first, and flagged two quotes as not mentioning their part. A third run used **this repository's public GitHub link**:
the first attempt failed cleanly (Gemini answered 503, and the Groq backup refused the 16,700-token request, one `error:` line and exit code 2); the second read **278 source files and 56 README and doc files from GitHub's real zip** and drew 8 parts and 2 routes, with 6 items
dropped (two parts whose quotes were not in the docs word for word, and the steps that needed them; the hop across a dropped step said so).

**Follow-up: a request too big for a model (2026-11-25).** The failed first GitHub attempt (Gemini overloaded, the Groq backup refusing 16,700 tokens) was fixed test first: the adapters now report a typed `input_too_large` (HTTP 413, OpenAI's `context_length_exceeded`,
Anthropic's 413), the guide asks again with half, then a quarter, of the documents, and Groq's `json_validate_failed` is now `invalid_output` (asked again once with what the model wrote). Tests added in the adapters, the policy, the engine's chain of models, `shrink`, the
pipeline, and **two end-to-end tests through real adapters over a fake connection** that reproduce the real failure (an overloaded first model, a backup that refuses the size); 24 deliberate breaks, all caught (one was dead code in `shrink`, removed).
The whole backend suite: **2,842 pass** (2,820 before this follow-up), 4 skipped (symbolic links), none failed. The web code did not change.
**A real Groq-only run** (Groq's free tier, 8,000 tokens a minute; every request listed from the engine's usage records) showed the staircase against the real API: the full size was refused as `input_too_large`, so was half, a quarter was accepted by size, the model then wrote
JSON that did not match the schema (now `invalid_output`, asked again once), and that retry was rate limited (429), twice, even after waiting a minute. **So Groq's free tier alone never produced a guide.** What this fix gives a person is a clear, typed failure and a smaller second try;
it does not make a small free-tier backup able to draw the diagram.

**Not verified:** a real GitHub download of a repository other than this one; macOS and Linux (the junction test is Windows-only, the symbolic-link tests skip here); a very large docs set; a README in another language; a model other than Gemini producing a valid guide
after a size refusal (the Groq run above never got that far); the hosted refusal over a real network (it is tested with the test client).
