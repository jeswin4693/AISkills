# How it works: a guided diagram for new developers (slice AB)

Status: design written 2026-11-25 by Claude after the person chose a shape in the browser mockups and said "build as your own". The mockups are
`.superpowers/brainstorm/*/content/diagram-shape.html` and `diagram-combined.html` (not committed).

## Intent

A new developer points SkillForge at a repository (a folder or a public GitHub link) and gets **one diagram that explains how the whole
project works**, read from its README and docs. The existing Repository-page map answers "which folder imports which"; it never reads a README and
does not say what the parts are *for*. This answers "what are the parts, in what order does an action travel through them, and where do I start
reading".

## What the person asked for (their words, shape chosen in the mockups)

* For **new developers**, so they understand the project quickly.
* **Layers (B) and one numbered action (A) together, with more detail inside each part.**
* Everything else ("build as of your own") is my call, recorded below.

## Goals

1. Layers: the parts sit in fixed bands (what people use, the doors in, the workers, shared services, the outside world).
2. Journeys: tabs, one per action the docs describe ("build a skill"). A journey is an ordered route through the parts, numbered.
3. Detail panel per part: what it does, what goes in and out, the files and functions to read first (from the graph), the quote from the docs
   it came from, and a plain-words picture.
4. Every hop of a journey says what is known: **confirmed** (the code really imports it), **docs only** (the docs say so, code cannot confirm: a
   web request is not an import), **imports the other way**, or **not measured** (a language whose imports are not read).
5. Parts the docs name but the code does not have are shown as **in docs, not in code**.

## Non-goals and anti-goals

* Not a call graph, not a picture of a running system, not saved or exported as an image.
* **Anti-goal: an invented part.** A diagram that looks complete but names a component that does not exist is worse than none. Every part and
  every step must carry a quote that code found word for word in the docs, or it is dropped.
* The model's own words (summaries, "does", in/out, plain words) are **not checked**; only the quote and the folder are. The page says so.
* No second diagram engine, no new library: HTML and CSS only, like the rest of the page.

## Constraints (from CLAUDE.md, kept)

* Models see only text code gathered; code judges (quotes found, folders looked up in the graph, part ids checked, caps). Model text is data,
  rendered as plain text, never evaluated.
* The model call names its task (`Task.GUIDE`, tier DESIGN) and goes through the AI service. No provider call elsewhere.
* The docs are untrusted data: fenced in the prompt, and nothing the model returns can change what code does (it can only be kept or dropped).
* A folder's absolute path never appears in an answer. Off in the hosted version (it reads a folder). Tests are offline (`MockProvider`).
* No new library.

## Approaches considered

1. **Model reads docs, code verifies (chosen).** One model call returns parts, layers and journeys, each with a quote. Code keeps only what it can
   check, then adds what the graph knows. Trade-off: needs a model key, and the summaries around the quotes are unchecked (said on the page).
2. **Headings and bullets turned into boxes by code, no model.** Fully deterministic, but READMEs have no fixed shape: it would draw the table of
   contents, not the working. Rejected: it fails the goal.
3. **Only the import map, labelled with model-written one-liners.** Cheap, but it is still "folders", with no journey, which is what the person
   asked to go beyond. Rejected.

## My calls (the person said "build as your own")

* **One request, not a polled run.** A guide is one model call. A polled run needs a database table and a migration; one request with a spinner is
  enough locally (the hosted version is off). Nothing is saved: asking again asks the model again. Said on the page and in the doc.
* **Docs read:** root `README*`, `ARCHITECTURE*`, `CLAUDE.md`, `AGENTS.md`, and `docs/**` text files (three levels), also from the focus folder.
  At most 12 files, 60,000 characters in all, 24,000 for one. Symbolic links, binaries and anything outside the folder are skipped.
* **GitHub snapshots now keep doc files** (they were dropped as `not_source`): the same name rules and limits as source files, plus their own caps
  (60 files, 200 KB each, 3 MB in all). The graph ignores them. A snapshot made before this change has no record of docs, so it is downloaded again
  for a guide.
* **Quotes:** 12 to 400 characters, compared after collapsing white space and removing backticks and asterisks. The place found (file and line)
  is worked out by code; the model's `source` is only a hint.
* **Limits of a guide:** at most 16 parts, 4 journeys, 8 steps in a journey. Fewer than two checked parts: the answer says so and draws nothing.
* **Hop status** reuses the architecture map's import links (proven, not from a test file): for hop A to B, A's folder imports B's folder.
* **CLI:** `python -m skillforge guide <folder-or-link> [--json]` prints the outline (the same function the page uses).

## Left to the builder

Exact prompt wording, the CSS, the unit-test cases beyond the ones named in the plan, the doc `docs/how-it-works.md`.
