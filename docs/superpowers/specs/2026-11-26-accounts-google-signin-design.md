# Design: accounts with Google sign-in (slice AH)

Written 2026-11-26. The user said "card ok, go" after I described the plan, so the choices below are mine, with reasons. The ask: a free link that works on any
device, and Google sign-in so other people can use it too (the project is open source). This slice is the **accounts** part; the free-host deployment kit and per-person
model keys are separate slices that follow ([plan in memory], order: deploy kit, accounts, per-person keys, phone checks; accounts come first in the code because the others build on them).

## Intent

Today the hosted version has one shared access token and a cookie that says "someone signed in". There is no person in it, none of the five tables has an owner, and
the library is one shared folder. To let other people use one server **without seeing each other's skills, builds or runs**, the app needs to know who is asking, and every read and write
needs to be about that person only.

## Goals

- **Sign in with Google.** The browser's Google button returns a signed ID token; the server verifies it (signature against Google's public keys, issuer, audience = our Client ID,
  expiry, verified email, nonce) and starts a session. **No Google client secret is used or stored.**
- **Who may sign in is decided by the host's owner**, by an allow-list of emails (`SKILLFORGE_ALLOWED_EMAILS`: addresses, `@domain` entries, or `*` for any Google account). An empty list refuses to start:
  signing in proves who someone is, not that they are welcome.
- **A user row** per Google account (`users`: id, google sub, email, name, times), kept in the database.
- **Everything is per person**: build sessions and their jobs, suggestion runs, Testing Lab runs, model-call usage rows, and the library of every kind (skills, agents, plugins, MCP servers) live under the person's id.
  Another person's item is a **404, never a 403** (the answer must not say it exists).
- **Local use and the owner's token are unchanged**: local mode, the access token and a Bearer header all act as the one existing user (`local`), who owns the data that exists today. All 3,408 existing tests keep passing.

## Non-goals (this slice)

Per-person **model keys** and quotas (the next slice; until then every signed-in person spends the host's key, which is why the allow-list matters), the free-host deployment kit,
an admin page, email/password sign-up, teams or sharing between people, deleting an account, and changing anyone's data layout on disk for the owner.

## Anti-goals (a failure even if it "works")

- Trusting anything the browser says about who it is: identity comes only from a verified token and our own signed cookie.
- A token accepted for another app (wrong audience), from another issuer, expired, with an unverified email, or replayed (the nonce).
- One person reading, changing or even detecting another person's data through any route, a job, a background thread, a path or a name.
- A path built from a user-chosen string (the person's folder is named by a random id we made, never by an email).
- Breaking local mode, the command line or the owner's existing library.

## Constraints (CLAUDE.md)

Offline tests only (a test signs its own tokens with a key it makes); no key or secret is printed, stored or committed; one **new library, `PyJWT[crypto]`**, because checking an RSA signature is security-critical and must not be hand-written
(it brings `cryptography`); nothing runs generated code except through the sandbox; the API never listens beyond the machine without a sign-in.

## Approaches considered

| Sign-in | Verdict |
|---|---|
| **Google Identity Services ID-token flow (chosen)** | The button gives the page a signed token; one POST to the server; no redirect, no secret, nothing to leak. Needs one small script from Google in the page. |
| OAuth authorization-code flow | Needs the client **secret** on the server and redirects; more to get wrong and to leak; gives access tokens we do not need. |
| Supabase Auth / Firebase Auth | A second service and its users table, for something one signed token already does; it would make this app depend on a vendor. A good choice later if real accounts and Postgres are wanted. |

| Per-person data | Verdict |
|---|---|
| **A `user_id` column on every table, plus one library folder per person (chosen)** | Smallest change: the library code is untouched (`Library(root)`), SQLite keeps working, and a test can prove isolation. |
| A database file per person | Many connections and migrations to run per user; the jobs share one runner. |
| PostgreSQL row-level security | Never tried here; a bigger move than this slice needs. |

## Design

**Who is asking.** `User(id, email)`. `LOCAL_USER` has id `local` and is used for local mode, the access token and Bearer. A Google user has a random hex id (`users.id`). `current_user(request)` returns it; the
auth middleware puts it on the request once the cookie is verified.

**The session cookie** is versioned. `v1` (token login) is unchanged and means the owner. `v2.<user id>.<expiry>.<signature>` is signed with the key already derived from the access token, so changing the token signs everyone out. Every request also
checks that the cookie's email is **still on the allow-list**, so removing someone from the list ends their access at once (no database read needed).

**Verification** (`api/google_auth.py`): RS256 only (the `none` and HS256 tricks are refused); the key is found by the token's `kid` in Google's published keys (fetched over https and cached; a test injects its own); `iss` is `accounts.google.com` or `https://accounts.google.com`;
`aud` equals our Client ID exactly; `exp`/`iat` with a small clock allowance; `email_verified` true; a `sub`; and the **nonce** the server issued for this attempt (a short signed cookie) equals the token's `nonce`, so a stolen token cannot be replayed into another browser.

**Endpoints.** `GET /api/auth/status` says whether a sign-in is needed, who is signed in, and the **public** Google Client ID (the page needs it). `GET /api/auth/nonce` issues a nonce. `POST /api/auth/google {credential}` verifies, checks the allow-list, upserts the user and sets the cookie.
The five-wrong-tries guard also covers Google attempts. The token login stays as the owner's way in.

**Data.** Migration 0006: table `users`; column `user_id` (default `local`) on `build_sessions`, `suggest_runs`, `eval_runs` and `model_calls`. Every read filters by it, every write sets it, a job carries its session's user. The library of person *u* is `<data>/users/<u>/library` (the other kinds sit next to it, as `Library.for_kind` already does);
`local` keeps `<data>/library` exactly as today. Public repository copies (a GitHub snapshot is public code) stay shared; **who read which repository** does not (runs are per person).

**Still off in the hosted version** (unchanged): installing into server folders, reading a server folder, the settings page, the sandbox.

## Threats considered

Token replay (nonce, short expiry), token for another app (audience), forged token (signature, RS256 only), an allow-list bypass (case-insensitive exact email or domain, checked on every request), session fixation (a new cookie on every sign-in), cross-person reads (404 and a test per route),
a path built from user input (random ids only), the shared model key being spent by strangers (the allow-list, and per-person keys next), terminal escapes in a name or email shown in a page (the page escapes; the server stores plain text and caps its length).

## Left to the builder

Exact column order, the cache time of Google's keys, the clock allowance, the wording of messages, how the page shows the signed-in person. All covered by tests written first.
