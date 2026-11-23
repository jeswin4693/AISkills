# Web UI

Steps H3 and H4 of [ui-and-database-plan.md](ui-and-database-plan.md): a browser front end for the local API
([api.md](api.md)). **Built so far: the app shell, the Library (H3), the Builder (H4), the Repository page (slice W, [repository-page.md](repository-page.md)) and the Settings page (slice X, [settings.md](settings.md)).**

How to run it: [../frontend/README.md](../frontend/README.md).

## What is there

| Page | What you can do |
|---|---|
| **Builder** (`/builder`, the front door) | Describe a skill in a sentence and press Start. If no model is set up it says what to put in `.env` (never asks for a key) and keeps Start disabled. Below the form, your earlier builds with their state (needs answers, needs approval, built, DRAFT, saved vN). When the server lists more than one kind, a picker above the box chooses what to build and past builds carry a kind badge; with one kind nothing on the page changes. |
| **A build** (`/builder/<id>`) | The whole conversation on one page, with a strip showing Describe, Answer, Approve, Build, Save. **Working:** what the server is doing now, with live messages, polled once a second. You can leave and come back. **Needs answers:** only the items your words did not cover, as questions, and "Why am I being asked?" shows which quotes were rejected. **Needs approval:** the requirement, every item next to **your own words** that back it; nothing is built until you press Approve. **Built:** the skill's checks, **each acceptance criterion next to the tests that cover it** (and a plain "No test case covers this" when none does), the files, the report, and **Save to the library**, which goes through the same checked import as any skill. A **DRAFT** cannot be saved until you tick that you understand it is one. **Failed:** the reason in words, and "Try again" when a second try can help (a missing key, an unreachable model). |
| **Library** (`/library`) | Import a skill `.zip` by choosing or dropping it (optional note; optional re-run of the skill's own script tests in the sandbox). The result is shown in plain words: kept as vN with the files that changed, unchanged, or **refused** with the failed checks. When it adds a version after another, a second box says **what got riskier** (more risk / worth a look / less risk, each line with its reason) and what that comparison cannot see. Below it, every skill with its latest version, age, source and check counts, and **Re-check everything**: today's checks on every stored version, saying which are now worse, failing or damaged (it changes nothing). With more than one kind there is a tab per kind (Skills, Agents), and every library page and link carries `?kind=` for a kind other than skill. |
| **MCP servers** | **Builder**: pick **MCP server**, describe the tools, answer only what is missing, approve, build, save ([mcp-builder.md](mcp-builder.md)). The result card says whether each test case ran in the sandbox, failed or did not run, and a server that never ran is a DRAFT. **Library**: an **MCP servers** tab like the skills and agents tabs (export, install into a folder, compare, re-check). The pages say "MCP server" where they said "skill". Not clicked through in a real browser. |
| **Plugins** (`/composer`) | Name a plugin, tick skills, agents and MCP servers from your library and hooks from the catalogue (each hook has a "runs on your machine" badge, says whether it can block, and has a box for each option, marked at once when a value would be refused), press **Preview the plugin** to see its files, what it can do on your machine (tools, scripts, and a "Programs this plugin starts" section for each MCP server: its tools, what its code can do, the secret options Claude Code will ask for) and every check, then **Keep this plugin**. No model is used. It then appears in the Library under Plugins. |
| **Repository** (`/repository`) | Type the full path of a folder on this computer (remembered in the browser only; the page shows the folder's name, never the path), **Read the repository** (languages and how deeply each is read, how much of the call graph is proven, the most depended-on functions, dead-code candidates; no model) and **Ask for ideas** (a model, in the background; each idea cites places that exist in the graph, and says that this does not make the advice right). A skill or automation idea has **Build this skill**, with its wording editable first; it starts a build session that ends with evidence for the cited places. Earlier runs are listed. Off in the hosted version. |
| **Settings** (`/settings`) | The model in use, **Test my models**, the provider and model, one key box per provider (never filled in: it says only "Saved" or "Not set", and a paste is dropped from the page once saved), backup models, and a folded "More options" (a model for one kind of work, four limits, the cache). Save writes `.env` and applies at once. A setting from the computer's environment is shown read-only. In the hosted version the page says it is managed by whoever runs the server ([settings.md](settings.md)). |
| **A skill** (`/library/<name>`) | Every version, newest first. Pick one to read its files (the API verifies the whole version against its hashes first) and the checks it passed at import. **Export** a `.zip` (optionally without `spec.json`, which holds the requester's own words), **Install** it (to `~/.claude/skills` or a folder you type, with a backup-and-replace step when it exists), **Restore** an older version (asks first; it adds a new version and deletes nothing), open the changes since the version before, or **Re-check this skill** (today's checks on each of its versions). A version that cites code also shows **Code it cites** (each place with the facts recorded) and **Recheck**, which compares them with a folder you name and lists what is missing, moved, changed or edited (off in the hosted version); the export can leave `evidence.json` out. |
| **Compare** (`/library/<name>/diff`) | Two version pickers; above the files, the **risk summary** for that pair; then, per file, added / removed / changed with the changed lines coloured and also announced as "added line" / "removed line" for screen readers. |
| **Status panel** (every page) | Whether the API is up, whether a Linux sandbox is available, and which model is set up (never a key). When the API is down it says so and gives the command to start it. |

## How it is built

| Part | Choice | Why |
|---|---|---|
| Framework | Next.js 16 (App Router), React 19, TypeScript 5.9 (strict) | In your original brief. TypeScript is held at 5.9 because 7.0 is brand new and Next's tooling targets 5.x. |
| Styling | Tailwind 4 with colour tokens in `globals.css`, light by default and dark when the system asks | No UI library: about a dozen small components in `components/ui.tsx`. Less to depend on. |
| Data | The browser calls the API directly (`fetch`), through one typed client (`lib/api.ts`) | One place decides what a 409 or an unreachable server means. The API's origin check and CORS are what let this work. |
| Dependencies | `next`, `react`, `react-dom`; dev: `tailwindcss`, `@tailwindcss/postcss`, `typescript`, `@types/*`, `vitest`, `playwright-core` | Each does one job. `playwright-core` drives your installed Edge, so nothing is downloaded. |

Choices worth knowing:

- **Nothing is shown as markup.** File text, diffs and messages are rendered as text, never as HTML. A skill that
  contains `<script>` is just text on screen.
- **The UI repeats no safety rule.** It does not decide what is allowed. The server checks every upload and every
  install; the UI shows what the server found. (Where the UI helps, as in refusing a `..` file path, it is a second
  lock, not the only one.)
- **Honest wording.** "Static checks only: nothing was run unless a line says so, and passing is not proof that a
  skill is safe" appears under every import result and on every version.
- **Colour is never the only signal.** Every status has a word (FAILED, warning, passed, not run, added, removed).
- **`node_modules` and `.next` live outside OneDrive** (junctions to `C:\dev\frontend`), like the Python venv.
- **The hosted version adds a sign-in and nothing else.** `AppShell` asks the API once whether a sign-in is needed. The local version never
  is, so nothing changes. When it is, the app shows a small sign-in form (one field for the access token) instead of the pages, a
  **Sign out** button in the sidebar, and no **Install** button on a skill page (it would write on the server; use **Export**). Any call
  answered 401 sends the person back to the form. The status panel's model line also says how many backup models wait behind the first.
  The page and the API share one address there (the build is made with `NEXT_PUBLIC_API_URL=same-origin`). See [hosting.md](hosting.md).
  The sign-in form has unit-tested logic and was not driven in a real browser.

## What was checked

- `npm run typecheck`: clean. `npm test`: **50 unit tests** (the API client's error handling for the library and the
  builder, the diff reader, formatters, the requirement-to-rows reading, the traceability of criteria to tests, the
  progress strip, the answer rules, the risk and re-check wording: no headline may say "safe").
- `npm run build`: succeeds.
- `npm run e2e`: **42 behaviours in a real Edge browser** (the last three are the plugin composer: the hook catalogue, a bad option stopping the preview, keeping a plugin with a skill and a hook,
  and a changed form clearing the old preview; the MCP picker has no server to pick in this run) against the real API (database, checklist, quote verification,
  checks and library all real; **the model is a scripted fake**, so the run is deterministic and needs no key) and the
  production build.
  - Library: the empty library; importing v1, an identical zip, a changed zip (v2), a skill with a hidden character
    (refused, nothing added) and a file that is not a zip; the diff including a removed Markdown `---` rule shown as
    removed; the version pickers; restoring v1; a real zip download; install and the replace prompt.
  - Risk and re-check: a first version shows no risk; a version that adds a script using the network shows **more risk**
    with its reasons, right after the import and again on the compare page; re-checking one skill and the whole library;
    and a stored file edited on disk behind the library's back shown as **damaged**, then fine once restored.
  - Builder: no model set up (explains what to put in `.env`, never asks for a key, Start disabled), then "Check again"
    and the sidebar updating without a reload; a sentence that starts a session shown as *working* and then asking
    **only the four missing items**; the answers; the requirement with **each item next to the person's own words**;
    Approve, live progress, and the result with **what the skill costs to use (an estimate), its SKILL.md carrying your rules, a done-when list and an example**, and **the acceptance criterion next to the three tests that cover it**;
    Save to the library as v1; a model failure shown plainly with "Try again" continuing from the same place; a
    **DRAFT** flagged at the top, with "No test case covers this", and not saveable until the person ticks that they
    understand; the list of past sessions; discarding one; an unknown session; leaving and coming back.
  - Everywhere: a phone-sized window with no sideways scrolling; dark mode; the keyboard; no script errors; and "the API
    is not running" when the server is stopped.
- **Python backend** (`python -m pytest`): unchanged except one check's wording, which no longer tells a web user to
  use a command-line flag.
- The browser test itself found a real bug on its first run: the "Restored" message vanished the moment it appeared
  (the panel was re-created for the new version and took its message with it). It also showed that a select inside a
  label was announced as "From v1" instead of "From".
- Screenshots of each state were then read by eye. That found two things the tests passed over: a command-line flag
  ("Use --force") shown in the install dialog, and a label overlapping on a phone-sized window. Both are fixed.

## Limits

- **A drawn graph, the Testing Lab and the Quality Report views are not built yet** (the rest of H5). The Repository page shows numbers and lists.
- **The Builder's automated browser test uses a fake model**, so it is repeatable and needs no key. The real thing was
  checked by hand with `node e2e/live.mjs` (real API, real model from your `.env`, real Edge): on 2026-11-19, with
  Gemini (`gemini-3.5-flash-lite`), one sentence, one round of five questions, approval, build and save took about
  21 seconds and 3 model calls, and produced `todo-fixme-counter` with its acceptance criterion covered by a positive, a
  negative and an edge test, saved as v1. That is one run of one skill with one provider, not a benchmark. (Earlier runs
  of the script failed twice, both times because of races in the script itself; a model that leaves an item unanswered
  is simply asked again, which is the checklist working.)
- **The Builder page does not show a risk diff.** It saves a new skill; if you save a skill under a name that is
  already in the library, open its Compare page to see what got riskier.
- **The browser test of the risk screens uses synthetic skills**, written for the test. Nobody has looked at how the
  risk box reads on a long list of changes (dozens of lines), or at how often it raises a false alarm.
- **The Builder cannot edit a requirement.** If the reading of your words is wrong you start over with a clearer
  description. Editing in place would need an API change.
- **A running build cannot be cancelled** (the API has no cancel). You can leave the page and come back.
- **Scripts in the builder** (the checkbox) have been tested over the API with a fake sandbox runner only, not through
  this page with a real sandbox.
- **Not tested in Chrome, Firefox or Safari**, only Edge (Chromium). Not tested with a screen reader: the semantics
  are there (landmarks, labels, live regions, a real `<dialog>`), but nobody has listened to it.
- **No automated accessibility audit** (such as axe) has been run.
- **The sandbox status takes a moment** (the API asks Docker inside WSL), so that row shows "checking…" on each full
  page load.
- Import accepts one `.zip` at a time, up to 6 MB. There is no way yet to import a skill from a URL or a folder.
- The dev server and the build were run on Windows only.
