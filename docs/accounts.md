# Accounts: "Sign in with Google", and one library per person

A hosted SkillForge used to have **one shared access token** and a session cookie that said "someone signed in". That is fine for you alone, and wrong the moment a second
person uses the same server: they would see your builds and your library. This slice lets **other people sign in with their Google account**, and gives each person
**their own** builds, library, test runs and quality reports. Design: [superpowers/specs/2026-11-26-accounts-google-signin-design.md](superpowers/specs/2026-11-26-accounts-google-signin-design.md).

```
 the page loads Google's script         our server
        |                                  |
  1. GET /api/auth/nonce  ------------->   makes a one-time nonce, keeps it in a cookie the page cannot read
  2. Google's button (client id + nonce)
        |  the person picks their Google account
  3. Google hands the PAGE a signed ticket (an ID token)
  4. POST /api/auth/google {credential} -->  checks the ticket:  signed by Google's public key (RS256 only), made for THIS app (aud),
                                             issued by Google (iss), not expired, a verified email, and carrying the nonce from THIS browser's cookie
                                             then: is the email on the allow-list?  yes -> a user row, a session cookie that names the person
```

**No Google client secret is used or stored anywhere.** The ticket is checked against Google's *public* keys, and the Client ID is public by design (every visitor's browser gets it).

## Settings (on the host, as secrets or environment)

| Setting | Meaning |
|---|---|
| `SKILLFORGE_GOOGLE_CLIENT_ID` | The **Client ID** from Google Cloud Console (ends in `.apps.googleusercontent.com`). A client **secret** pasted here by mistake (`GOCSPX-…`) is refused with a message saying so. |
| `SKILLFORGE_ALLOWED_EMAILS` | **Who may sign in**, comma separated: addresses (`ada@example.com`), whole domains (`@team.example.org`: **only for a Google Workspace account of that domain**, not its subdomains, see "Domain entries" below), or `*` for any Google account. **Required** with the Client ID: an empty list refuses to start, because signing in proves who someone is, not that they are welcome. A typo such as `ada` (no `@`) is refused too. |
| `SKILLFORGE_ACCESS_TOKEN` | Unchanged and still **required**: it is the owner's way in, a script's Bearer token, and the key that signs every session, so changing it signs everyone out. |

Taking someone off `SKILLFORGE_ALLOWED_EMAILS` ends their access **on their very next request** (the session carries the email, and the list is checked every time).

## What is per person

| Per person | Shared |
|---|---|
| Builder sessions and their jobs | Public GitHub repository copies (public code; **who** read which repository is per person) |
| Suggestion runs, Testing Lab runs, quality reports | The server's own model, only when the host shares it with a daily cap; otherwise each person uses their own key ([per-person-keys.md](per-person-keys.md)) |
| The library of every kind: skills, agents, plugins, MCP servers (`<data>/users/<id>/library…`) | The server's disk and CPU |
| Model-call usage rows (each row says whose quota it used) | |

Another person's item is a **404, never a 403**, and the answer is word for word the answer for something that never existed: a request must not be able to find out that something is there.
A person's folder is named only by a random 32-character id this server made; nothing an email, a name or Google chose ever becomes part of a path, and anything that is not such an id is refused before a path is built.

## The owner

Local use, the access token and a Bearer header are all **the owner** (`local`), who owns everything that existed before accounts, exactly where it was. Nothing about local use changes, and the command line is untouched.

## Setting it up (free)

1. **Google Cloud Console** → a project → **OAuth consent screen / Google Auth Platform**: External, an app name, a support email, **no extra scopes** (only the basic sign-in ones).
   As far as Google's pages say, an app that asks only for basic identity can be used by anyone without review; a project left in *Testing* is limited to 100 listed test users.
2. **Credentials → Create credentials → OAuth client ID → Web application**. Under **Authorized JavaScript origins** add every address people open: `http://localhost:3000` for trying it on your computer, and your public `https://…` address once you have one.
   (No redirect address is needed: the button gives the page a ticket, there is no redirect.)
3. Copy the **Client ID** into `SKILLFORGE_GOOGLE_CLIENT_ID` on the host, and list the people in `SKILLFORGE_ALLOWED_EMAILS`.
4. Open the site: the sign-in page shows **Sign in with Google**, with "Owner of this server? Use the access token" underneath.

To try it on your own computer, the page and the API must share **one address** (the session is a cookie, and a browser does not keep one between two addresses), so do **not** use `npm run dev`.
Run the API in hosted mode (`SKILLFORGE_MODE=hosted`, a 20+ character random `SKILLFORGE_ACCESS_TOKEN`, `SKILLFORGE_GOOGLE_CLIENT_ID`, `SKILLFORGE_ALLOWED_EMAILS`, `SKILLFORGE_ALLOWED_HOSTS=localhost,127.0.0.1`) with `python -m skillforge serve --port 8000`,
then build and start the web app so it forwards `/api` to it: `NEXT_PUBLIC_API_URL=same-origin SKILLFORGE_PROXY_API=http://127.0.0.1:8000 npm run build`, then `npm run start`, and open exactly `http://localhost:3000` (the origin you authorised; `127.0.0.1` would not match).
Settings in angle brackets in any example are placeholders to replace, never to paste: a placeholder as `SKILLFORGE_ALLOWED_EMAILS` is refused, and one as the access token would be accepted as a (guessable) token.
A single address in `SKILLFORGE_ALLOWED_EMAILS` lets only that address in; **`*` lets any Google account in, and each person's first sign-in creates their own account**. A Google project left in *Testing* status also admits only the test users listed in its console. Do not stop servers you already have running on those ports.

## What the judge of a ticket refuses (each has its own code, for tests and logs)

A ticket for **another app** (wrong `aud`, also when it lists several apps and ours is one), from **another issuer**, **expired** or issued **in the future**, **signed by another key**, with its **signature cut off** or its claims
**changed** after signing, using the **`none`** algorithm or **HS256 with the public key as the secret** (refused by looking at the algorithm *before* any key is used; PyJWT itself even refuses to create such a token), about an **unverified email**,
with **no email** or **no subject**, with **no nonce** or **another browser's nonce**, garbage of any kind, or a request that arrives with no nonce cookie at all. A refusal's message never repeats the ticket. Google being unreachable is a **503**.
**Wrong tickets touch no lock** (a ticket is a signature from Google, so there is nothing to guess); the five-wrong-tries lock (one minute) belongs to the **access token alone**, and a good Google sign-in does not reset it.
Instead, **every attempt uses up its nonce on the server**, good or bad, so a copy of a nonce cookie and a ticket cannot be sent again; the page asks for a fresh nonce after every refusal.

## Domain entries (`@company.com`) mean that company's Google Workspace

A whole-domain entry used to trust any verified email at that domain. Google's own guidance is to check the ticket's **`hd` claim** (the Workspace domain), because a *personal* Google account can be made with a company address and stays "verified" after its owner leaves.
Now an `@company.com` entry admits a person only if their address is at that domain **and** Google says (`hd`) the account belongs to that Workspace. The session remembers that domain, so the list is re-checked with it on every request: taking someone's exact address off the list does not let a domain entry stand in for it unless they came in through that Workspace.
An **exact address** or `*` needs no Workspace. A refused person at a listed domain is told why ("only with a Google Workspace account of that organisation"); someone at an unlisted domain is told nothing about which domains are listed.

## Limits (read these)

- **Whose model a person's calls use is now their own choice** ([per-person-keys.md](per-person-keys.md)): by default a person with no key of their own cannot use the host's model at all; the host may share it with a daily cap. The allow-list is still mandatory (signing in proves who someone is, not that they are welcome), and `*` should only be used knowingly.
- **A hosted copy still has no sandbox**: skills with scripts and MCP servers are built as drafts there, for everyone.
- **One server process, one SQLite file**: fine for a few people, not for a crowd. PostgreSQL has never been tried with this app.
- The list of people is a setting, and the owner has a **People page** to see who uses the server and turn an account off (slice AJ, [person-limits.md](person-limits.md)); each person has limits on disk, kept builds and runs at once. There is no account deletion, no teams and no sharing between people.
- **A person's files are not limited in size** except by the library's own per-skill limits.
- **Not verified:** the real round trip with Google in a browser (it needs your Google account and an authorised origin; the tests sign their own tickets), a real phone, several people signing in at the same moment, and any host. See [hosting.md](hosting.md).

## What was checked (2026-11-26)

- **Tests, all offline** (a mock model, tickets signed by a key the test makes): the whole backend suite is 3,600 tests (3,596 passed, 4 skipped: they need a Linux Docker, 0 failed), **192 of them new** (`test_google_auth.py` 42, `test_accounts_auth.py` 67, `test_accounts_isolation.py` 48, `test_users_db.py` 10, `test_accounts_review.py` 25). Web: 366 unit tests and a clean typecheck (16 files; `lib/google.ts` and the sign-in logic in `lib/auth.ts` have their own).
  The real-browser suite on free side ports: **100 of 100**, run again after the review's fixes (it runs the local version, so it shows nothing changed for local use; the hosted sign-in screen is driven by `npm run e2e:phone`, below).
  One Dashboard step failed once while the backend suite ran at the same moment (it counted elements before the card had filled in); it now waits for either answer first.
- **55 deliberate breaks** (change one rule, run the tests, restore): 47 on the backend (the ticket judge, the cookie, the allow-list, the configuration refusals, the nonce, the routes, every place a person is looked up, the library root, usage rows) and 8 on the page's logic.
  **The first run caught 44 of 47 and 7 of 8. Every survivor was a weak test of mine, not a hole in the code**, and each was fixed and re-broken until it failed:
  - *A name with an escape sequence in it:* the test put the escape after 500 letters, so cutting the name to 200 characters removed it before the cleaning mattered. The assertion could never fail. Now the escape and hidden direction marks sit in the middle of a short name.
  - *A person's session on a server with Google sign-in off:* the test's server had an empty allow-list, which refuses for its own reason. Now the list admits anyone, so only "Google is off" can refuse.
  - *A request with no nonce cookie:* the guard also stops the server from **fetching Google's keys** for it. Nothing pinned that; now a test checks the key fetcher is never asked.
  - *The script loader asked twice while still loading* (React mounts a component twice in development): nothing tested it. Now it must add one script and share one answer.
  (My break script crashed once on a Windows decoding error in the test runner's output. That was the script, not the code; it was fixed and the missing breaks were run.)
- **20 more deliberate breaks on the review's fixes, all caught the first time:** a used nonce usable again (forgotten at once, never "seen", never expired, no size bound); a Google sign-in clearing the token lock; a wrong ticket counting against it; a domain entry without the Workspace claim, or with any claim; the session forgetting the domain, or the re-check ignoring it; the old cookie parser; an unidentified request becoming the owner; the middleware ignoring a path prefix; the refusal hint missing or shown to everyone; the ticket's `hd` not read or not checked for shape; the migration downgrade rebuilding the table; and the CORS layer back inside the sign-in check. **75 breaks in all.**
- **A failing test that was the right signal:** a test pinning the exact columns of the usage table ("no prompt or reply text is stored") failed when `user_id` was added. It was updated on purpose (an id is not text a person typed), and its other assertion still checks that none of the person's words are stored.

**Not verified:** a real sign-in with Google (the tests sign their own tickets), several people at the same moment, any real host. (A real phone: see below for what was done at phone size.)

## The hosted sign-in screen at phone size (2026-11-26)

Until now the hosted sign-in screen had never been driven in a real browser. `npm run e2e:phone` (`frontend/e2e/hosted-phone.mjs` with `hosted_server.py`) starts a **throwaway hosted server** (a random token that is never printed, a made-up Client ID, an empty settings file and **no model**, so it can never read your real `.env` or spend a key)
and the web app built the way the Docker image builds it (page and API on one address), opens it in Edge as a 390 x 844 **touch device with an iPhone user agent**, and checks 13 things:
Google's button draws (its script comes from the internet) or the page says why not; no sideways scroll, on the sign-in screen and after signing in; the "Owner? Use the access token" line and the Sign in button are **44 px** tall; the token box text is 16 px (iPhone does not zoom in on focus);
a wrong token is refused visibly; the right token signs the owner in; the server has no model (the proof that it is not reading your `.env`); Sign out is reachable and returns to the sign-in screen; no console errors of our own. **13 of 13 pass.** Screenshots are read by eye (Google's real button, the error card and the signed-in dashboard all fit a 390 px screen).

What driving it found, all fixed or documented:
- The "Owner? Use the access token" line was **20 px tall** and the Sign in button **32 px**: now 44 px (`py-3`, `min-h-11`). Nothing else about the card changed.
- **A session cannot live across two origins.** With the page on one port and the API on another, a correct token left the browser with **no session cookie** (the page never asks for credentials, and a browser neither stores nor sends a cookie between origins). The supported hosted setup serves pages and API from one address, as the image does; `hosting.md` says so now (it used to offer `SKILLFORGE_UI_ORIGINS` for a different address without this warning).
- **The sign-in middleware's own 401 was answered outside the CORS layer**, so a trusted page on another address saw "blocked by CORS policy" instead of "401, sign in". Fixed by reordering the layers (the local-only check stays outermost); test in `test_accounts_review.py`.
- **The first version of the throwaway server read the real `.env`** (the status card showed the configured models). It made no model call, but a test must not read it: it now runs through its own launcher with no model, and the check above fails if that ever changes.
- Google's script put its own `g_state` cookie in the browser's jar: the same kind of cookie that hid the session in review finding 3.

**Not done:** a real phone (this is Edge's emulation of a viewport, touch and a user agent), iOS Safari or Android Chrome, a real Google sign-in (the Client ID is made up, so Google's button draws but cannot finish), and a slow mobile network.

## The independent review (2026-11-26)

A fresh reviewer was given the code, the rules and the claims to test, and none of my conclusions (158k tokens, 41 tool calls, scripts in a scratch folder, no model call, no `.env`). **No Critical finding: nobody gets in without a valid ticket or token, and no one person could see another's data.**
It reported 5 Important and 2 Minor findings. Its report is model output, so **each was reproduced as a failing test before any change**, and each test failed for the reason given. All seven are fixed (`tests/test_accounts_review.py`, 25 tests):

| # | Finding | Fix |
|---|---|---|
| 1 | One lock for the whole server, and a good Google sign-in **cleared it**: with any allowed Google account (or `*`) a guesser could try 4 tokens, replay a ticket, and never be locked | The lock belongs to the access token alone: Google sign-in neither counts toward it nor clears it |
| 2 | Five anonymous garbage tickets locked **every** sign-in, the owner's token included, for a minute (repeatable) | Wrong tickets touch no lock. The access-token lock can still be triggered by anyone who knows the address, as `hosting.md` already said |
| 3 | `SimpleCookie` stops at the first cookie it cannot parse, and Google's own `g_state={"i_l":0}` is one: a session cookie that came after it was invisible (every request 401, "not signed in") | The cookie header is read with Starlette's parser, which skips what it cannot read |
| 4 | An `@company.com` entry trusted any *verified* address at that domain, including a personal Google account made with a company address (the `hd` claim was never read) | See "Domain entries" above |
| 5 | The migration's **downgrade deleted every job and usage row** (a SQLite table rebuild cascades through foreign keys; the upgrade's own comment warned about exactly this) | A plain `DROP COLUMN`; a test proves the rows survive a downgrade and an upgrade again |
| 6 | "A nonce is used once" was only a request to the browser to delete a cookie: a copy of the cookie and the ticket worked again for ten minutes (what made finding 1 cheap). **My own test for this passed only because the test client's cookie jar obeyed that request** | The server remembers used nonces (bounded: 10,000, expired ones forgotten); every attempt, good or bad, uses its nonce up |
| 7 | If the app were ever served under a path prefix (a proxy mount, `--root-path`), the sign-in middleware did not see the request and the route made the caller **the owner** | A hosted request nobody identified is refused (`current_user` no longer defaults to the owner there); the middleware strips the prefix |

Checked by the reviewer and found sound: the algorithm is read before any key (so `none` and HS256-with-the-public-key fail), `jku`/`x5u`/`jwk` headers are ignored, `aud` must be one exact string, expiry, the verified email, a nonce-less request never fetches Google's keys and five unknown key ids cause one fetch, the session signature covers every field in constant time with no ambiguous splitting, the allow-list is re-checked on every request, changing the token invalidates every session, every library route and every kind goes through the person's own library, and `_row(user=None)` is reachable only from background jobs.
**Not checked by the reviewer:** a real Google round trip (and Google's real `g_state` behaviour in a browser), PostgreSQL, real races between two people, and the isolation tests beyond reading them.

## Where the code is

`api/google_auth.py` (checking a ticket), `api/hosted.py` (the cookie, the nonce, the allow-list, the routes), `db/users.py` and migration `0006` (users and the owner column), `library/registry.py` (whose library),
`api/scope.py` (whose request), and the owner/user arguments of `builder/service.py`, `builder/suggestions.py`, `builder/evals.py`. Web: `lib/google.ts`, `lib/auth.ts`, `lib/useAuth.tsx`, `components/LoginPanel.tsx`.
Tests: `tests/test_google_auth.py`, `test_accounts_auth.py`, `test_users_db.py`, `test_accounts_isolation.py`, `test_accounts_review.py` (the review's findings), `frontend/src/lib/google.test.ts`, `auth.test.ts`, and the phone-size browser check `frontend/e2e/hosted-phone.mjs` (+ `hosted_server.py`, `npm run e2e:phone`).
