# Limits per person, an owner's People page, and the small fixes (slice AJ)

The hosted version is meant to be open to **any Google account** (`SKILLFORGE_ALLOWED_EMAILS=*`). A free server is small, so three things make an open sign-up safe: **limits per person**, a **People page** for the owner with a reversible **turn off**, and a handful of small fixes found by the real tests of the earlier slices.
Design and plan: [superpowers/specs/2026-11-26-person-limits-and-admin-design.md](superpowers/specs/2026-11-26-person-limits-and-admin-design.md). Related: [accounts.md](accounts.md) (who a person is), [per-person-keys.md](per-person-keys.md) (their own model key).

## Limits per person

Only **signed-in people** on a **hosted** server are limited. **The owner (the access token, a Bearer header) and local use are never limited.** A limit of `0` means "none".

| Setting | Default | What it limits |
|---|---|---|
| `SKILLFORGE_PERSON_DISK_MB` | **500** | the size of a person's folder (their library of every kind) plus the folders of their own builds |
| `SKILLFORGE_PERSON_MAX_BUILDS` | **50** | builds a person may keep (discarding one makes room) |
| `SKILLFORGE_PERSON_MAX_ACTIVE` | **2** | background runs working at the same moment, builds, Testing Lab runs and behaviour scans together (the job pool has two workers and is shared by everybody) |

Each is a whole number from 0 to 10,000,000, or the server refuses to start and names the setting.

**Where they bite** (the others are not touched):

| Action | Disk | Builds kept | Runs working |
|---|---|---|---|
| Start a build | yes | yes | yes |
| Answer, approve or retry a build | yes | | yes |
| Save a build to the library, import a zip, keep a plugin, save test cases, restore a version | yes | | |
| Start or retry a Testing Lab run | | | yes |

"At or over" refuses. The refusal is HTTP **429** with `{"detail": "...", "limit": "disk" | "builds" | "active"}`; the words name the person's **own** numbers and say what to do ("Discard builds you no longer need, then try again"). A Testing Lab run is allowed at the disk limit: it writes next to nothing, and a person who is full can still test what they have.

**How it is measured.** The size is measured **on demand** (a walk of the person's folder and of the folders of their own builds), not kept as a counter that could drift. **Every file is charged in whole 4 KB blocks, at least one, and every folder and link one block**: what it really takes on a disk, so a million one-byte files cannot hide under a limit counted in bytes (the independent review reproduced 28 imports of 400 tiny files each passing a 1 MB limit). A link inside a folder (a symbolic link or a Windows junction) is **never followed**, so it can neither make another folder count as theirs nor make the walk leave their space. **The walk stops as soon as the limit is passed**, so a huge folder costs a bounded amount to look at (at the default 500 MB, about 128,000 entries at most). The two counts come from the database. The space card and the People page reuse a measurement up to 5 seconds old; **admission always measures fresh**.

**At the same moment.** For the counts kept in the database (builds kept, runs working), the check and the write that takes the place happen under one lock, so eight starts at the same instant with two places left give exactly two (a test starts eight threads together). **The disk is measured before that lock is taken**, never while holding it: walking one person's big folder used to hold the lock every other person's build start needs (the review reproduced Bob waiting for Ada's walk). The price: an action can overshoot the disk limit by what one action writes (a few MB), never a runaway. The lock is in this process: the hosted image runs one process.

**What a person sees.** `GET /api/me/space` and a **Your space on this server** card on Settings: disk used of the limit, builds kept of the limit, runs working of the limit, each with a bar, and what to do when one is full. Only their own numbers; the owner sees nothing there.

## Turning an account off (the owner's People page)

The owner of a hosted server sees **People** in the menu (nobody else does). It lists everybody who has signed in with: name, address, builds kept, disk used, model calls today (on the server's model / on their own key), last seen, whether they have a key of their own (never the key, never which model), and any runs working. Each card has **Turn off this account** (it asks first, and says what happens) and, once off, **Turn back on**.

- **A turned-off person is signed out on their very next request**, even with a good session: the block is checked on every request, like the allow-list. Every call is refused with 403 "This account has been turned off on this server. Ask the person who runs it.", the sign-in screen says so, and a new Google sign-in is refused with the same words and **no session**.
- **Nothing is deleted.** Their builds, library and key stay; turning the account back on gives the same session back. (Erasing a person's data is a separate, irreversible step, slice AK: [data-removal.md](data-removal.md).) A build that was already running when the account was turned off finishes (at most the "runs working" limit).
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

- **No per-person custom limits** (one number for everybody), no limits on the owner, none in local mode. (Erasing a turned-off person's data is now possible, slice AK: [data-removal.md](data-removal.md).)
- **A person can now shrink their own library** (slice AK): *Delete this skill…* on an entry's page removes it with every version and backup ([data-removal.md](data-removal.md)); before that a person whose library alone passed the disk limit was stuck until the owner raised the setting.
- The disk walk is bounded (it stops at the limit) but still a pass over up to about 128,000 entries for a person near the default limit, on each start, answer, approve, retry, save or import; the People page does one per person (reused for 5 seconds). It is meant for a small server.
- **One person with several Google accounts gets several sets of limits** (the open allow-list is the owner's choice). A person can also repeat a limit-checked call as often as they like; there is no rate limit on any route.
- `POST /api/library/import?test_scripts=true` (the sandbox runs inside the request) and the model checks (`/api/me/model/test`, `/api/provider/check`) are not counted as "runs working": they are requests, not background runs, and the hosted image has no container engine for the first.
- **The lock and the in-flight places live in one process.** The hosted image runs one instance; several would each count the same rows but hold their own lock.
- A checklist item answered in an earlier builder round can still be lost in a later one (the spec is recomputed each round); the quote fix removed the cause seen so far, not the design.

## The independent review (2026-11-26)

A fresh reviewer on the most capable model (186k tokens, 42 tool calls), given the code, the rules and the failure modes to test but none of my conclusions: **no Critical finding, two Important, seven Minor.** Both Important findings were reproduced as failing tests first and are fixed (`tests/test_person_limits.py`, 6 tests): **(1)** the disk limit counted only file bytes, so many tiny files dodged it (now charged in blocks, see above); **(2)** the disk walk ran while holding the lock every person's build start needs, so one person with a huge folder stalled everybody (now measured before the lock, stopping at the limit, and cached for display). The five focus points (off-by-one at the cap, two starts at the same instant, a blocked person with a valid session, odd ids on the admin routes, links out of a folder) held up, and migration 0008 is safe both ways.

**Minor findings (all fixed afterwards, in the completion batch's first task: see the end of this section):**

- A turned-off person's refused sign-in still rewrites their record (name, picture, last sign-in), so they can change what the People page shows and appear at the top as "last seen just now". The fix is to look the person up and check the block before updating the record.
- "Last seen" is the last **sign-in**, not the last activity (a session lasts days); the label should say so.
- The People list is capped at 1,000 people, latest sign-in first: on a very open server a turned-off person could fall past the cap and not be found to turn back on from the page (list turned-off people first, or page the list).
- The sign-in middleware asks the database (is this person turned off?) from async code on every request of a person: each lookup is a primary-key read, a failure answers 500 (it fails closed), but it blocks the event loop for that moment (a thread pool would not).
- The browser check's launcher passes `limits=hosted.person_limits` by hand instead of calling `builder_options`, so the helper's "so none can forget" is true for two of the three places a builder is made (a test covers the real `serve`; the launcher is the third).
- Errors raised by the engine's own guards (`LLM_MAX_CALLS`, `LLM_MAX_INPUT_TOKENS`) still name owner settings when a person's own key hits them.
- This file said "a few hundred files" for the walk's cost: corrected above.

**Fixed afterwards (slice AK, task 1; `tests/test_batch_fixes.py`, each also broken on purpose and caught):** a turned-off person's refused sign-in is now looked up and refused **before** anything about them is written, so it changes neither their name, their picture nor their last sign-in; the People page says **Last sign-in** (that is what the date is); the list shows **turned-off people first** (so one can always be found to turn back on) and says "Showing N of M people" when it is cut at 1,000; the sign-in check's database lookup runs in a thread pool and no longer blocks the event loop; the browser check's launcher builds its builder through `builder_options`, so none of the three places that make a hosted builder can forget the limits; and the engine's own guard errors (`LLM_MAX_CALLS`, `LLM_MAX_INPUT_TOKENS`), which a person on the **shared** model could see, now say "a limit set by the person who runs this server" instead of naming owner settings (the owner still sees the setting's name).

## What was checked

- **Backend: 3,779 tests passed, 4 skipped** (they need a Linux Docker), none failed; 71 of them are new for this slice (the small fixes, the limits, the People routes and the block, and the tests the breaks and the review added). All offline, none reads the real `.env`.
- **Web: 424 unit tests passed, the typecheck is clean.** The main real-browser suite passed **100 of 100**.
- **The hosted version at phone size** (`npm run e2e:phone`, 390 px, touch, a throwaway hosted server with no real model): **44 of 44** checks, 15 of them new: a person's own space card with its three bars, the owner's People page (the person listed, a 44 px Turn off button, asking first), turning the account off (the person told so on the sign-in screen, every call of theirs a 403), and turning it back on (the same session works again, everything kept).
- **Deliberate breaks** (a break is a small wrong change made to the code on purpose, to see that a test fails): the first run of 60 caught 52 and **8 survived, and every one was a weak test of mine** (no test at exactly the limit; the answer, retry and Lab-retry paths never walked; a documented rule, "a Lab run is allowed at the disk limit", with no test; a leak test that searched the wrong form of a secret; the own-key and server call counts never compared; one clamp that did nothing). All were strengthened and re-broken (7 caught, the redundant line deleted). After the review's fix the whole script, now **65 breaks**, was run again on the final code: **all 65 caught, none survived.**
- **Two real defects were found by the review, not by my tests** (see above), and the earlier real sign-in of slice AI had found that `serve` forgot the model options: that is why `builder_options` is now the one place a hosted builder's options are made, with a test through the real `serve` command.
- **Not tried:** a real Google sign-in of a person who is then turned off, a real phone, a real host, many people at once, more than one server instance, and the walk on a real folder of hundreds of thousands of files (the early stop is tested on a thousand).


## Where the code is

`builder/limits.py` (`PersonLimits`, `PersonSpace`, `LimitReached`, `folder_bytes`), the use of it in `builder/service.py` (`start`, `answer`, `approve`, `retry`, `save`) and `builder/evals.py`, `api/hosted.py` (the three settings), `api/builds.py` (`builder_options`, the `room` dependency), `api/me.py` (`/me/space`), `api/admin.py` (People), `db/users.py` + migration `0008` (the block), `api/hosted.py` (`AuthMiddleware` and the sign-in refuse a turned-off person), `settings/rules.py`, `builder/model_access.py`, `ai/service.py` (the small fixes).
Web: `lib/space.ts`, `components/settings/MySpace.tsx`, `app/admin/page.tsx`, `lib/admin.ts`, the menu in `components/AppShell.tsx`, the sign-in message in `components/LoginPanel.tsx`. Tests: `test_person_fixes.py`, `test_person_limits.py`, `test_admin_block.py`, `frontend/src/lib/space.test.ts`, `admin.test.ts`, `myModel.test.ts`, and the phone-size browser check `frontend/e2e/hosted-phone.mjs`.
