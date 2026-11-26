# Limits per person, an owner's People page, and the small fixes (slice AJ)

The hosted version is meant to be open to **any Google account** (`SKILLFORGE_ALLOWED_EMAILS=*`). A free server is small, so three things make an open sign-up safe: **limits per person**, a **People page** for the owner with a reversible **turn off**, and a handful of small fixes found by the real tests of the earlier slices.
Design and plan: [superpowers/specs/2026-11-26-person-limits-and-admin-design.md](superpowers/specs/2026-11-26-person-limits-and-admin-design.md). Related: [accounts.md](accounts.md) (who a person is), [per-person-keys.md](per-person-keys.md) (their own model key).

## Limits per person

Only **signed-in people** on a **hosted** server are limited. **The owner (the access token, a Bearer header) and local use are never limited.** A limit of `0` means "none".

| Setting | Default | What it limits |
|---|---|---|
| `SKILLFORGE_PERSON_DISK_MB` | **500** | the size of a person's folder (their library of every kind) plus the folders of their own builds |
| `SKILLFORGE_PERSON_MAX_BUILDS` | **50** | builds a person may keep (discarding one makes room) |
| `SKILLFORGE_PERSON_MAX_ACTIVE` | **2** | background runs working at the same moment, builds and Testing Lab runs together (the job pool has two workers and is shared by everybody) |

Each is a whole number from 0 to 10,000,000, or the server refuses to start and names the setting.

**Where they bite** (the others are not touched):

| Action | Disk | Builds kept | Runs working |
|---|---|---|---|
| Start a build | yes | yes | yes |
| Answer, approve or retry a build | yes | | yes |
| Save a build to the library, import a zip, keep a plugin, save test cases, restore a version | yes | | |
| Start or retry a Testing Lab run | | | yes |

"At or over" refuses. The refusal is HTTP **429** with `{"detail": "...", "limit": "disk" | "builds" | "active"}`; the words name the person's **own** numbers and say what to do ("Discard builds you no longer need, then try again"). A Testing Lab run is allowed at the disk limit: it writes next to nothing, and a person who is full can still test what they have.

**How it is measured.** The size is measured **on demand** (a walk of the person's folder and of the folders of their own builds), not kept as a counter that could drift; a link inside a folder (a symbolic link or a Windows junction) is counted as the small thing it is and **never followed**, so it can neither make another folder count as theirs nor make the walk leave their space. The two counts come from the database.

**At the same moment.** The check and the write that takes the place happen under one lock, so eight starts at the same instant with two places left give exactly two (a test starts eight threads together). The lock is in this process: the hosted image runs one process.

**What a person sees.** `GET /api/me/space` and a **Your space on this server** card on Settings: disk used of the limit, builds kept of the limit, runs working of the limit, each with a bar, and what to do when one is full. Only their own numbers; the owner sees nothing there.

## Turning an account off (the owner's People page)

The owner of a hosted server sees **People** in the menu (nobody else does). It lists everybody who has signed in with: name, address, builds kept, disk used, model calls today (on the server's model / on their own key), last seen, whether they have a key of their own (never the key, never which model), and any runs working. Each card has **Turn off this account** (it asks first, and says what happens) and, once off, **Turn back on**.

- **A turned-off person is signed out on their very next request**, even with a good session: the block is checked on every request, like the allow-list. Every call is refused with 403 "This account has been turned off on this server. Ask the person who runs it.", the sign-in screen says so, and a new Google sign-in is refused with the same words and **no session**.
- **Nothing is deleted.** Their builds, library and key stay; turning the account back on gives the same session back. (Deleting a person's data is a separate, irreversible step that is **not** built.) A build that was already running when the account was turned off finishes (at most the "runs working" limit).
- **Only the owner** can list or turn off: a person gets 403, local mode says there are no accounts. The owner cannot be turned off; an id that is not one this server made is refused before any lookup, and an unknown one is a 404.
- Routes: `GET /api/admin/people`, `POST /api/admin/people/{id}/block`, `POST /api/admin/people/{id}/unblock` (POST, not PATCH: the API's CORS policy allows GET, POST and DELETE only). The column is `users.blocked` (migration 0008, a plain `ADD COLUMN`; the downgrade keeps every person).

## The small fixes

| Fix | What changed |
|---|---|
| Changing only the **model name** no longer means pasting the key again | an empty key box keeps the saved key when it can still be opened and the provider is the same; with another provider the page and the server say "paste your key for the new provider" |
| The model box says **names can contain a slash** | a hint under the box (`openai/gpt-oss-120b` on Groq) |
| `Bearer:KEY` | refused like `Bearer KEY` (a key that merely begins with those letters is still a key) |
| No ".env" advice for a person | the unsafe-characters refusal, and a provider's "key rejected" or "model not found" for a person's own key, now point to Settings, My model |
| An attempt that fails with an **unexpected error** is counted | the engine records an `error` row of kind `other` and re-raises, so it counts against a person's daily allowance |

## Limits (read these)

- **No deleting a person's data from the admin page, no per-person custom limits** (one number for everybody), no limits on the owner, none in local mode.
- **The library cannot be shrunk by a person**: there is no "delete a skill". A person whose library alone passes the disk limit is stuck until the owner raises the setting; discarding builds frees only the build folders.
- The disk walk costs a pass over a person's files on each start, save or import: cheap at these sizes (a few hundred files), and the People page does one per person, so it is meant for a small server.
- **The lock and the in-flight places live in one process.** The hosted image runs one instance; several would each count the same rows but hold their own lock.
- A checklist item answered in an earlier builder round can still be lost in a later one (the spec is recomputed each round); the quote fix removed the cause seen so far, not the design.

## What was checked

(filled in after the verification)

## Where the code is

`builder/limits.py` (`PersonLimits`, `PersonSpace`, `LimitReached`, `folder_bytes`), the use of it in `builder/service.py` (`start`, `answer`, `approve`, `retry`, `save`) and `builder/evals.py`, `api/hosted.py` (the three settings), `api/builds.py` (`builder_options`, the `room` dependency), `api/me.py` (`/me/space`), `api/admin.py` (People), `db/users.py` + migration `0008` (the block), `api/hosted.py` (`AuthMiddleware` and the sign-in refuse a turned-off person), `settings/rules.py`, `builder/model_access.py`, `ai/service.py` (the small fixes).
Web: `lib/space.ts`, `components/settings/MySpace.tsx`, `app/admin/page.tsx`, `lib/admin.ts`, the menu in `components/AppShell.tsx`, the sign-in message in `components/LoginPanel.tsx`. Tests: `test_person_fixes.py`, `test_person_limits.py`, `test_admin_block.py`, `frontend/src/lib/space.test.ts`, `admin.test.ts`, `myModel.test.ts`, and the phone-size browser check `frontend/e2e/hosted-phone.mjs`.
