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
| `SKILLFORGE_ALLOWED_EMAILS` | **Who may sign in**, comma separated: addresses (`ada@example.com`), whole domains (`@team.example.org`, not its subdomains), or `*` for any Google account. **Required** with the Client ID: an empty list refuses to start, because signing in proves who someone is, not that they are welcome. A typo such as `ada` (no `@`) is refused too. |
| `SKILLFORGE_ACCESS_TOKEN` | Unchanged and still **required**: it is the owner's way in, a script's Bearer token, and the key that signs every session, so changing it signs everyone out. |

Taking someone off `SKILLFORGE_ALLOWED_EMAILS` ends their access **on their very next request** (the session carries the email, and the list is checked every time).

## What is per person

| Per person | Shared |
|---|---|
| Builder sessions and their jobs | Public GitHub repository copies (public code; **who** read which repository is per person) |
| Suggestion runs, Testing Lab runs, quality reports | The server's model key (until per-person keys, the next slice) |
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

To try it on your own computer: run the API in hosted mode with those settings (`SKILLFORGE_MODE=hosted`, a 20+ character `SKILLFORGE_ACCESS_TOKEN`, the Client ID, the allow-list, `SKILLFORGE_ALLOWED_HOSTS=localhost`)
and the web app on port 3000 (`http://localhost:3000` is the origin you authorised). Do not stop servers you already have running on those ports.

## What the judge of a ticket refuses (each has its own code, for tests and logs)

A ticket for **another app** (wrong `aud`, also when it lists several apps and ours is one), from **another issuer**, **expired** or issued **in the future**, **signed by another key**, with its **signature cut off** or its claims
**changed** after signing, using the **`none`** algorithm or **HS256 with the public key as the secret** (refused by looking at the algorithm *before* any key is used; PyJWT itself even refuses to create such a token), about an **unverified email**,
with **no email** or **no subject**, with **no nonce** or **another browser's nonce**, garbage of any kind, or a request that arrives with no nonce cookie at all. A refusal's message never repeats the ticket. Google being unreachable is a **503** and is
**not** counted as a wrong guess; every other refusal counts toward the five-wrong-tries lock (one minute), the same lock the access token uses.

## Limits (read these)

- **Everyone who signs in spends the host's model key** (per-person keys and limits are the next slice). That is why an allow-list is mandatory, and `*` should only be used knowingly.
- **A hosted copy still has no sandbox**: skills with scripts and MCP servers are built as drafts there, for everyone.
- **One server process, one SQLite file**: fine for a few people, not for a crowd. PostgreSQL has never been tried with this app.
- **No admin page**: the list of people is a setting. There is no account deletion, no teams and no sharing between people.
- **A person's files are not limited in size** except by the library's own per-skill limits.
- **Not verified:** the real round trip with Google in a browser (it needs your Google account and an authorised origin; the tests sign their own tickets), a real phone, several people signing in at the same moment, and any host. See [hosting.md](hosting.md).

## What was checked (2026-11-26)

- **Tests, all offline** (a mock model, tickets signed by a key the test makes): the whole backend suite is 3,576 tests (3,572 passed, 4 skipped: they need a Linux Docker), **168 of them new** (`test_google_auth.py` 42, `test_accounts_auth.py` 68, `test_accounts_isolation.py` 48, `test_users_db.py` 10). Web: 366 unit tests and a clean typecheck (16 files; `lib/google.ts` and the sign-in logic in `lib/auth.ts` have their own).
  The real-browser suite on free side ports: **100 of 100** (it runs the local version, so it shows nothing changed for local use; it does **not** drive the hosted sign-in screen).
  One Dashboard step failed once while the backend suite ran at the same moment (it counted elements before the card had filled in); it now waits for either answer first.
- **55 deliberate breaks** (change one rule, run the tests, restore): 47 on the backend (the ticket judge, the cookie, the allow-list, the configuration refusals, the nonce, the routes, every place a person is looked up, the library root, usage rows) and 8 on the page's logic.
  **The first run caught 44 of 47 and 7 of 8. Every survivor was a weak test of mine, not a hole in the code**, and each was fixed and re-broken until it failed:
  - *A name with an escape sequence in it:* the test put the escape after 500 letters, so cutting the name to 200 characters removed it before the cleaning mattered. The assertion could never fail. Now the escape and hidden direction marks sit in the middle of a short name.
  - *A person's session on a server with Google sign-in off:* the test's server had an empty allow-list, which refuses for its own reason. Now the list admits anyone, so only "Google is off" can refuse.
  - *A request with no nonce cookie:* the guard also stops the server from **fetching Google's keys** for it. Nothing pinned that; now a test checks the key fetcher is never asked.
  - *The script loader asked twice while still loading* (React mounts a component twice in development): nothing tested it. Now it must add one script and share one answer.
  (My break script crashed once on a Windows decoding error in the test runner's output. That was the script, not the code; it was fixed and the missing breaks were run.)
- **A failing test that was the right signal:** a test pinning the exact columns of the usage table ("no prompt or reply text is stored") failed when `user_id` was added. It was updated on purpose (an id is not text a person typed), and its other assertion still checks that none of the person's words are stored.

**Not verified:** a real sign-in with Google (the tests sign their own tickets), a real phone, several people at the same moment, any real host, and an **independent review** of this code: it handles who is allowed in, so it should have one before anyone relies on it.

## Where the code is

`api/google_auth.py` (checking a ticket), `api/hosted.py` (the cookie, the nonce, the allow-list, the routes), `db/users.py` and migration `0006` (users and the owner column), `library/registry.py` (whose library),
`api/scope.py` (whose request), and the owner/user arguments of `builder/service.py`, `builder/suggestions.py`, `builder/evals.py`. Web: `lib/google.ts`, `lib/auth.ts`, `lib/useAuth.tsx`, `components/LoginPanel.tsx`.
Tests: `tests/test_google_auth.py`, `test_accounts_auth.py`, `test_users_db.py`, `test_accounts_isolation.py`, `frontend/src/lib/google.test.ts`, `auth.test.ts`.
