# The Dashboard (slice AC), the first of three pages the original vision still lacked

Status: design written 2026-11-25 by Claude after the person said "yes" to starting on the Testing Lab, Quality Report and Dashboard pages. The other two
are separate slices (they need more than this one). My calls are marked as such.

## Why this one first

The original vision (docs/START_PROMPT.md) lists nine pages. Five exist; Dashboard, Testing Lab and Quality Report do not (the home page only redirects to the
Builder). The Dashboard is the cheapest and has the clearest value: **everything it shows already has an endpoint**, so it needs no server work, and it answers
the question a person has on opening the app: "does anything need me, what do I have, is the system ready?"

## What it shows (all computed by code from existing endpoints; no model, nothing is run)

1. **Needs attention**, worst first. From today's rescan of every kind (`GET /api/rescan?kind=`): a version whose files are damaged or that fails checks now
   (bad), or whose checks got worse since import (warning). From the builds: waiting for your answers or approval, failed, a draft that was never saved,
   finished but not saved. From the system: no model set up, no sandbox. At most ten are listed, and the rest are counted. When nothing needs the person, the page says what it
   looked at, so "nothing" is a checked statement and not an empty box.
2. **Your library**: per kind (skills, agents, plugins, MCP servers) how many and how many versions, and the five most recently saved versions.
3. **Recent builds**: the last five, with the same status words the Builder uses.
4. **Start something**: Build, Read a repository, Import (the Library), Combine into a plugin.

## Goals, non-goals, anti-goals

* Goals: one screen that says what needs the person, with a link to each thing; every part loads on its own.
* Non-goals: charts, history over time, a score. Nothing is saved or computed on the server for this page.
* **Anti-goal: a dashboard that hides a failure.** If the library of one kind cannot be read, or the rescan fails, the page says so in that section; it never shows
  "0" or "nothing needs you" for something it could not read.

## My calls

* **Home page.** `/` becomes the Dashboard (it redirected to `/builder`). The brand link goes to it, and the menu gets a "Dashboard" entry first.
* **No new endpoint.** The page calls the existing ones from the browser (the library and rescan once per kind, builds, provider, sandbox). A big library means a rescan
  of it on every visit; it only reads, and a person with hundreds of skills is not the case this slice is for. Said in the doc.
* **Pure logic in `lib/dashboard.ts`**, tested without a browser: what needs attention, in what order, and the library overview.
* **Severity order** is bad, then warning, then info, and inside a tone the order the data came in (the API gives builds newest first).
* **The browser suite** gets its first step changed (it expected `/` to redirect) and new steps for the empty state, a populated library and phone width.

## Left to the builder

The CSS, the exact words of each item, the doc `docs/dashboard.md`.
