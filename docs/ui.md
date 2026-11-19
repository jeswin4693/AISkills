# Web UI

Step H3 of [ui-and-database-plan.md](ui-and-database-plan.md): a browser front end for the local API
([api.md](api.md)). **Built so far: the app shell and the Library.** The builder chat is the next step (H4).

How to run it: [../frontend/README.md](../frontend/README.md).

## What is there

| Page | What you can do |
|---|---|
| **Library** (`/library`) | Import a skill `.zip` by choosing or dropping it (optional note; optional re-run of the skill's own script tests in the sandbox). The result is shown in plain words: kept as vN with the files that changed, unchanged, or **refused** with the failed checks. Below it, every skill with its latest version, age, source and check counts. |
| **A skill** (`/library/<name>`) | Every version, newest first. Pick one to read its files (the API verifies the whole version against its hashes first) and the checks it passed at import. **Export** a `.zip` (optionally without `spec.json`, which holds the requester's own words), **Install** it (to `~/.claude/skills` or a folder you type, with a backup-and-replace step when it exists), **Restore** an older version (asks first; it adds a new version and deletes nothing), or open the changes since the version before. |
| **Compare** (`/library/<name>/diff`) | Two version pickers and, per file, added / removed / changed with the changed lines coloured and also announced as "added line" / "removed line" for screen readers. |
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

## What was checked

- `npm run typecheck`: clean. `npm test`: **20 unit tests** (the API client's error handling, the diff reader, formatters).
- `npm run build`: succeeds.
- `npm run e2e`: **19 behaviours in a real Edge browser** against the real API and the production build: the empty
  library; importing v1, an identical zip, a changed zip (v2), a skill with a hidden character (refused, nothing added)
  and a file that is not a zip; opening a skill; the diff including a removed Markdown `---` rule shown as removed; the
  version pickers; restoring v1 (asks first, adds v3, keeps the rest); a real zip download; install needing a folder,
  writing the files, and asking before replacing; an unknown skill; a phone-sized window with no sideways scrolling;
  dark mode; the keyboard; no script errors; and "the API is not running" when the server is stopped.
- The browser test itself found a real bug on its first run: the "Restored" message vanished the moment it appeared
  (the panel was re-created for the new version and took its message with it). It also showed that a select inside a
  label was announced as "From v1" instead of "From".
- Screenshots of each state were then read by eye. That found two things the tests passed over: a command-line flag
  ("Use --force") shown in the install dialog, and a label overlapping on a phone-sized window. Both are fixed.

## Limits

- **Only the Library so far.** The builder chat, suggestions, the graph, Settings, the Testing Lab and the Quality
  Report views are planned (H4 and H5). The sidebar's "Builder (soon)" is a placeholder, not a link.
- **Not tested in Chrome, Firefox or Safari**, only Edge (Chromium). Not tested with a screen reader: the semantics
  are there (landmarks, labels, live regions, a real `<dialog>`), but nobody has listened to it.
- **No automated accessibility audit** (such as axe) has been run.
- **The sandbox status takes a moment** (the API asks Docker inside WSL), so that row shows "checking…" on each full
  page load.
- Import accepts one `.zip` at a time, up to 6 MB. There is no way yet to import a skill from a URL or a folder.
- The dev server and the build were run on Windows only.
