# The Repository page (slice W)

Until this slice the main pipeline (understand a repository, get ideas grounded in it, build a skill from an idea, keep evidence of the
code it cites) worked only from the command line. The web UI had Builder, Library and Plugins. This slice brings the pipeline into the
pages. Plan: [superpowers/plans/2026-11-23-repository-page-slice-w.md](superpowers/plans/2026-11-23-repository-page-slice-w.md).

```
Repository page  --path-->  analyze (graph, no model)  --> numbers a person can read
      |
      +--> "Ask for ideas" --> a suggestion run (the model, in the background, polled; kept in the database)
                                   |  every idea cites graph nodes that exist (checked by code)
                                   v
                          "Build this skill"  (the requirement is the model's wording; the person can change it)
                                   |
                                   v   Builder session with a seed {repo, focus, cited places}
                          questions, approval, build   ...as always
                                   |   at the end of the build: evidence.json from the graph as it is then
                                   v
                          Save to the library --> the skill's page lists the code it cites and can recheck it
```

## What each part does

| On the page | What happens |
|---|---|
| **Read the repository** | `POST /api/repos/analyze`: the graph's facts for a folder (size, languages and their honest levels, how much of the call graph is proven, the most depended-on functions, busy files, dead-code candidates). No model, nothing is run. A full path is needed; a bare folder name is refused before anything is sent. The page remembers the folder in the browser only. |
| **Ask for ideas** | `POST /api/suggestions`: the same code as `skillforge suggest` (a review pass and an ideas pass, grounding that drops what cites nothing real). It runs in the background as a row in the new `suggest_runs` table and the page polls it, so a reload keeps the result and a second click cannot spend the quota twice. A failed run says why and can be tried again. |
| **An idea** | Its title, rationale, the places it cites (these exist in the graph: checked by code), its confidence, any number it quotes that is in none of the facts, and a first step. The card says plainly that the places being real does not make the advice right. |
| **Build this as a skill** | Only for skill and automation ideas that carry a requirement and cite a place. It starts a Builder session whose first words are the idea's requirement, **which the person can edit first** (the real model sometimes words a skill as an action, "Refactor these functions", and the builder then refuses it as an agent). The page sends only the run and the idea's position: **the server takes the run's own folder and the idea's own cited places**, so a build cannot be about another repository than its idea was made for, whatever the folder box says. |
| **The build ends** | For a skill or an agent, `evidence.json` is written into the built folder from the graph as it is **then**: a repository that is gone then, or none of whose places exist, only adds a note and the build is unchanged. The result says "It cites N places in <repo>". |
| **The skill's page** | "Code it cites" lists each place with the facts recorded and when; **Recheck** runs the evidence recheck against a folder and lists the verdicts (missing, moved, changed, edited, holds) worst first, with the report's own statement of what it does not check. An export can leave `evidence.json` out. |

## The API

| Route | |
|---|---|
| `POST /api/repos/analyze` | `{"path": "<absolute folder>", "focus": "src"}` returns `{name, focus, stats, notes, hotspots, dead_code}`. The path is never sent back, only the folder's name. 400 for a relative path, a missing folder or a file. |
| `POST /api/suggestions` | `{"path", "focus", "with_ideas"}` starts a run (201). The folder is checked before any model is asked. **A second request for the same folder and focus while that run is still working returns that run**, so a double click or a second tab asks the model once. |
| `GET /api/suggestions`, `GET /api/suggestions/{id}` | The runs (without their results), and one run: `status` (working, done, failed), `result` (the report: `suggestions` with `evidence_nodes`, `dropped`, `notes`), `error`, `retryable`. 404 for an unknown id. |
| `POST /api/suggestions/{id}/retry` | Runs a failed run again; 409 for any other. |
| `POST /api/builds` | now also takes **`from_run` and `idea`** (a finished run and the idea's position in it: the server uses that run's folder and the idea's cited places) or, for scripts, `repo`, `focus` and `evidence_nodes` (at most 60 places); not both. A half-given seed, an idea that is not a buildable skill or automation, a run that is not finished, a folder that is gone, or a kind other than skill or agent is a 400. The session shows `seed: {repo, focus, places}` (the folder's name, never the path) and the result `evidence: {repo, places, skipped}`. |

**Every route that reads a folder is off in the hosted version (403):** analyze, suggestions, a build with a repository, and recheck. A folder
would be one on the server, not on the person's computer.

## Where the path lives

The folder a person types stays on their computer. A suggestion run and a build session keep it in the database row (a build needs it to
record evidence when it ends); **no response and no error message repeats it** (an error says "Not a directory on this computer" or names the kind of failure, never the
path; tests check results and errors, and a run that failed because the folder vanished), and pages are shown only the folder's name, resolved (`repo\..` is `repo`). A **network path**
(`\\server\share`, `//server/share`) is refused: opening one would reach out to another machine. The page remembers the last folder in the browser's own storage.

## Checked

* Backend tests: `tests/test_repository_api.py` and `tests/test_repository_review.py` (43 in all: analyze, runs, seeded builds, builds from a run, hosted 403, the migration, recovery after a stop, the review's findings), offline with a mock model. The whole suite: 2,215 passed, 2 skipped (symbolic links).
* Frontend: 27 new unit tests (`lib/repository.test.ts`); the real-browser run now has 9 more behaviours (52 in all): the menu, a bare folder name and a network path
  refused, a missing folder (and its error shows no path), reading a repository and remembering it, ideas, building from an idea with its wording edited, the skill's page listing the code it
  cites, and a recheck that says holds, then names a new caller, then says missing.
* **A real run (2026-11-23) with the configured model**, through the API on this repository (folder `backend`): analyze found 195 files, all
  Python at the full level, and sent no path; two model calls gave 8 ideas, every one citing nodes that exist (none dropped); the one skill idea was
  refused as "an agent" until its requirement was reworded (this is why the wording is now editable); built reworded, it passed 31 checks and carried
  `evidence.json` for 5 places, was saved as v1, and a recheck said "5 holds".

## What one independent review found (2026-11-23), and what was done

A fresh reviewer read the first version, with a hosted client, hostile folders and the migration among its inputs. 20 of the 22 new tests failed on the old code.

| Found | Done |
|---|---|
| The person's path was repeated in error texts (`Not a directory: <path>`, an OSError's text in a failed run, the recheck route), against the page's own statement | No message repeats a path; network paths are refused; the folder is named by what it resolves to (`X\..` was named `..`) |
| **"Build" used the folder box, not the run's folder**: edit the box, or read a different folder with the same name, and the evidence was recorded from the wrong repository | A build now names the run and the idea; the **server** takes the run's folder and the idea's own places (the page sends neither) |
| Two requests writing the graph cache at once collided on one temporary file (425 of 600 saves failed in a probe); a run then failed with no "Try again" | Each write has its own temporary file and gives up quietly if the replace cannot be done; nothing is left behind |
| "A second click cannot spend the quota twice" was false (two requests, four model calls) | One run per folder and focus while it is working, and the page picks up a working run after a reload |
| A fetch error while polling froze the spinner; opening an earlier run kept the old one on screen (and a retry would have retried it); the list of earlier runs went stale | The poll tries again; a new run starts clean; the list follows the open run |
| An edited requirement was kept by the idea's *title*, so a later run's same-titled idea inherited it | Edits are kept by run and position |
| A recheck started on one version could show its report under another | A late answer for another version is dropped, the report names its version, and the Repository page's remembered focus is no longer overwritten |
| Names that were not in the graph reached the result as raw text (control and bidi characters) | They are shown escaped |
| A `ValueError` anywhere in a run was reported as "the repository could not be read" | Only reading the folder says that; anything else says "Unexpected error (type)" and the log has the rest |
| "Low confidence means it leans on name-only guesses" overclaimed (it is the model's own statement), and "Build this automation" built a skill | Worded as the model's statement; the button says "Build this as a skill" |

Not changed, said plainly: no time or size cap on reading a huge folder or a drive root; a stale run row is never deleted.

## Limits (said plainly)

* The **ideas are only as good as the model**: the real run's only skill idea ("Refactor Duplicate Pipeline and Builder Functions") was a refactoring task
  dressed as a skill. Grounding proves the cited code exists, not that the idea is worth building.
* Evidence is recorded for **skills and agents only**; an MCP server or a plugin makes no claims about a repository.
* The page also draws the repository's folders and the imports between them (slice Z, [architecture-map.md](architecture-map.md)); there is still no function-level graph. (The Settings page was built later: [settings.md](settings.md).) A repository can be read from a folder on this computer or from a public GitHub link ([github-link.md](github-link.md)). Citing and refreshing evidence from a page, and a page for the evidence of every skill at once, are not built.
* Needs the local app (a folder on this computer): the hosted version refuses all of it.
* Not verified: a build from a run with a **real** model (the real run above used the equivalent `repo` + `evidence_nodes` request; the from-run path ran with the scripted fake model and in tests), macOS and Linux paths, a very large repository (reading is one request that waits), more than one person using one server.
