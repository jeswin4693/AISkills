# Per-person limits, an owner's admin page, and the small fixes (slice AJ): design and plan

Status: **built (slice AJ), see [../../person-limits.md](../../person-limits.md) for what was built, checked and reviewed.** It was approved by the owner's "Yes, start step 2 now" for the three parts below; the numbers and shapes are my calls, each marked *my call*, and every one is a setting or a one-line change.

## Why

The hosted version is meant to be open to **any Google account** (`SKILLFORGE_ALLOWED_EMAILS=*`, which the owner asked for). Slice AH gave each person their own space and slice AI their own model key, but nothing stops one person from **filling the free VM's 30 GB disk**, queuing builds until nobody else gets a worker (the job pool has **2** workers), or staying on after misbehaving: the only way to remove someone was to edit the allow-list, which `*` has no entries in. Three things make an open sign-up safe, and the real tests of slices AH and AI found a handful of small flaws worth fixing in the same pass.

## Goals
1. **Limits per person** (not the owner): disk, kept builds, background runs at the same time; a person told plainly which limit they hit and what to do.
2. **An owner's admin page**: who has signed in, what each uses, and a reversible **block / unblock**.
3. **The small fixes** found by the independent review and the real tests (list below).

## Non-goals
- No deleting a person's data from the admin page (a block stops growth; deleting is irreversible and gets its own design). No per-person custom limits (one number for everybody, like the allowance). No quotas on the owner. No billing. No limits in local mode (there are no people there). A person's running jobs are not cancelled by a block (at most `max active` of them).

## Anti-goals (a failure even if it "works")
- A limit that can be dodged by acting at the same moment (the lesson of slice AI's allowance).
- A limit that one person's actions can use against another (a number or a name that tells one person about another's data).
- A **block that does not end a session that is already signed in** (the session is a signed cookie: the check must run on every request, like the allow-list).
- The owner locked out by their own limits.

## Approaches considered
| | Limits | Block |
|---|---|---|
| **A (chosen)** | Measure on demand (walk the person's folder + their build folders) at the few places that grow things, refuse when at or over; counts from the database | A `blocked` column on `users`, checked on every request by the sign-in middleware and at sign-in; reversible |
| B | Keep a running byte counter per person in the database, updated on every write | Remove the person from a stored allow-list |
| C | Operating-system quotas / a separate volume per person | A reverse-proxy rule |

A needs no new moving parts and cannot drift (B's counter drifts when a folder is changed by hand or a write fails halfway; C is not portable to a free VM and needs root). A costs a directory walk at start/save/import: cheap at these sizes (a few hundred files). Block B (an allow-list copy in the database) would duplicate the setting the owner already controls; C lives outside the app.

## My calls (change any of them)
- **Defaults:** disk **500 MB** per person (`SKILLFORGE_PERSON_DISK_MB`, `0` = no cap), **50** kept builds (`SKILLFORGE_PERSON_MAX_BUILDS`, `0` = none), **2** background runs at once, counting builds and Testing Lab runs that are working (`SKILLFORGE_PERSON_MAX_ACTIVE`, `0` = none). They apply **only to signed-in people in a hosted server** (the owner and local use are never limited).
- **Where they bite:** starting a build (count, disk, active), answering/approving/retrying one (active, disk), saving to the library (disk), importing a zip (disk), starting or retrying a Testing Lab run (active). "At or over" refuses; an import can overshoot by at most the size of one upload (already capped by the server).
- **How it fails:** HTTP **429** with `{"detail": "...", "limit": "disk" | "builds" | "active"}`; the message says what was reached and what to do (discard old builds, wait for a run to finish). Never another person's numbers.
- **Visible to the person:** `GET /api/me/space` and a **Your space** card on Settings (used of limit, builds kept of limit, runs working of limit), in plain words.
- **Block:** `users.blocked` (migration 0008, default 0). A blocked person's requests get **403** "This account has been turned off on this server. Ask the person who runs it." (so they are told, not left guessing); `/api/auth/status` reports them as not signed in; a new Google sign-in is refused with the same message and **no cookie**. Their data stays.
- **Admin:** owner-only `GET /api/admin/people` (id, name, email, joined, last sign-in, builds kept, disk used, model calls today on the server's model / on their own key, whether a key of their own is saved, blocked), `POST /api/admin/people/{id}/block` and `/unblock` (POST, not PATCH: the CORS policy allows GET, POST and DELETE only). A person who calls them gets 403; local mode answers `{"hosted": false, "people": []}`. The page `/admin` shows cards (phone-friendly) and appears in the menu **only for the owner of a hosted server**.
- **Small fixes:** (a) saving with the key box empty keeps the saved key when the provider is unchanged (else it says to paste the key for the new provider); (b) the Model box says some providers' names contain a slash; (c) `Bearer:KEY` is refused like `Bearer KEY`; (d) the unsafe-characters refusal for a person no longer says "put it in the .env file by hand"; (e) a provider's "check X_API_KEY in .env" is reworded for a person's own key ("Check your key under Settings, My model"); (f) an attempt that fails with an error that is not a provider error is recorded (so it counts against the allowance) and re-raised.
- **Not in this slice (said plainly):** an answered checklist item that is lost between builder rounds (needs the spec kept per round: its own change; the quote fix already removed the cause seen so far).

## Global constraints
- Another person's data is a 404 identical to a missing one; a person never sees another's numbers. A forgotten `user` argument means the owner, who has no limits (fail closed is for data; here the owner is exempt by design and a person must be passed to be limited).
- Settings are read in `Hosted.from_env` (invalid values refused at start, naming the setting; a value above 10,000,000 refused; never silently clamped).
- The usage rows stay the allowance's ledger: nothing in this slice deletes them.
- Tests are offline; no real key; the owner's real `.env` is never read.
- After the slice: tests, deliberate breaks, one independent review (it adds an enforcement point for who may do what), docs (`docs/person-limits.md`, README, roadmap, CLAUDE.md, `.env.example`, `hosting.md`), then commit and push.

## Review focus
1. A person at the build cap who discards one build can start exactly one more (no off-by-one either way).
2. Two requests at the same instant when one slot is left: not both pass (the *active* cap is checked and claimed together).
3. A **blocked person with a valid cookie**: every route is refused, including the ones the middleware does not guard (`/api/auth/*`), and sign-in is refused.
4. The owner's id or any odd id in `/api/admin/people/{id}/block`: the owner cannot be blocked; a non-hex id is refused before any lookup; an unknown id is 404.
5. A person's folder size must not follow a symbolic link out of their folder (a link inside it must not make another folder count, or be read).

## Tasks
1. **Small fixes** (a to f): tests first in `tests/test_person_fixes.py`, `frontend/src/lib/myModel.test.ts`.
2. **Limits**: `builder/limits.py` (`PersonLimits`, `space_of`, `LimitReached`), `Hosted` settings, wiring in `Builder` / `EvalRuns` / the import route, 429 handler, `GET /api/me/space`; `tests/test_person_limits.py`.
3. **Block and admin**: migration 0008, `UserStore.set_blocked/is_blocked/people`, middleware + sign-in checks, `api/admin.py`, `tests/test_admin_block.py`.
4. **Web**: `lib/space.ts` + `MySpace.tsx` on Settings, `app/admin/page.tsx` + menu entry, unit tests; the phone check gains the space card and the admin page.
5. **Verification and review**: full suites, breaks, independent review, docs, push.
