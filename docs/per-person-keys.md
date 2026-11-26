# Per-person model keys, and a daily allowance on the server's model

After accounts ([accounts.md](accounts.md)) several people can sign in to one hosted SkillForge, but **every model call still spent the one key set on the server**: the owner paid for everyone.
Now each signed-in person can use **their own model and key**, and the owner decides whether people without a key may use the server's model, and how much.
Design: [superpowers/specs/2026-11-26-per-person-model-keys-design.md](superpowers/specs/2026-11-26-per-person-model-keys-design.md). Plan: [superpowers/plans/2026-11-26-per-person-model-keys-slice-ai.md](superpowers/plans/2026-11-26-per-person-model-keys-slice-ai.md).

## What a person gets

| You are | Your calls use | Limit |
|---|---|---|
| **The owner** (local use, the access token, a Bearer header) | the server's own model, set in `.env` or the host's environment | none |
| **A person with a key of their own** (Settings, "My model") | **your** provider, model and key | none from this server (the provider's own limits apply) |
| **A person with no key, when the host shares** (`SKILLFORGE_SHARED_KEY_CALLS_PER_DAY=N`) | the server's model | **N calls a day**, counted from midnight UTC |
| **A person with no key, when the host does not share** (the default) | nothing: you are told to add your own key | n/a |

"Everything" means everything that asks a model: **builds, suggestion runs, Testing Lab runs** (and the status and "test my key" buttons). The server's model is **never borrowed** by someone it is not shared with.

## Settings

| Setting | Meaning |
|---|---|
| `SKILLFORGE_SHARED_KEY_CALLS_PER_DAY` | Hosted only, optional. A whole number from 0 to 1,000,000: how many model calls a day a signed-in person **without** a key of their own may make on the server's model. `0` or unset: not shared. It needs Google sign-in (otherwise only the owner can sign in and the owner is never limited): the server refuses to start with it and no Google settings. |

A person's key is sealed under `SKILLFORGE_ACCESS_TOKEN`, so that setting must stay set to the same value. **Changing the token signs everyone out and makes every saved key unreadable**: people are told to enter their key again (their builds fail with that message, retryable, never a 500).

## How it works

- **The key is sealed.** AES-256-GCM, the encryption key derived (HKDF-SHA256) from the access token **with a label of its own** (a leaked session-cookie key opens nothing here), the person's id as associated data (a sealed key copied into another person's row does not open), a fresh random nonce per seal. The database holds only ciphertext (`user_models`); a test searches the database file's bytes for the key.
- **One place decides which model a call uses:** `ModelAccess.provider_for(person)` (`builder/model_access.py`). A person's provider is built from **exactly three entries** (provider, model, their key): nothing of the server's environment, keys or backups comes along. Every returned provider has the usage recorder attached, so a suggestion run or a Testing Lab run (which have no builder session) leaves usage rows under the right person.
- **Which key paid is recorded** (`model_calls.key_source`: `server` or `own`). Only `server` calls count toward an allowance, so deleting a key never makes yesterday's own-key calls eat today's allowance.
- **The usage rows are the allowance's ledger, so nothing may delete them.** Discarding a build used to delete its rows (the independent review found that "start a build, discard it, start another" then made the shared model free); now Discard keeps them (counts and timings only, never a prompt or a reply) and lets go of the session, the same as a suggestion run's or a Testing Lab run's rows have no session.
- **The allowance is a gate inside the model engine, before every attempt** (a retry is an attempt). It counts the person's `server` rows since 00:00 UTC **plus attempts still in flight**: counting finished rows alone let six runs started at the same instant all see "none used" and all go (found while writing this slice; the threaded test failed 6 of 6 first). It raises a new error kind, `allowance`, which never hands the attempt to a backup model (a backup uses the same server key) and stays retryable.
- **A key goes in once and never comes out.** No route, error or log holds it, not even its end: the tests search every response and every log line of every call for it, including the 400 for a refused value and the 422 for a malformed body.
- **`custom` is not offered to people.** That provider takes an *address* from whoever sets it, which would let a person send the server to any address they type.

## What a person sees

**Settings → My model** (in the hosted version this page used to say settings are managed by whoever runs the server): the provider (a list), the model name, a password-type key box that is **cleared the moment it is saved**, the state ("a key is saved on <date>", never the key), **Test my key** (one tiny question to *their own* model; the server's model is never tried for them), **Remove my key**, and the allowance when the server's model is shared ("12 of 25 model calls used today (resets at midnight UTC)"). The page checks the same rules as the server before Save (quotes around a key, the word "Bearer", unsafe characters, lengths) with messages that never repeat the key. The owner is told that the server's own settings are used. The Builder's "no model" banner tells hosted people to add a key in Settings, not to edit a `.env` file.

| Route | Does |
|---|---|
| `GET /api/me/model` | what applies to this person (never a key) |
| `POST /api/me/model` `{provider, model, key}` | save (400 names each refused field; 403 for the owner) |
| `DELETE /api/me/model` | remove (safe to repeat) |
| `POST /api/me/model/test` | one tiny call to their own model |
| `GET /api/provider`, `POST /api/provider/check` | now per person (the pages already read them) |

Only GET, POST and DELETE exist: the API's CORS policy allows nothing else.

## Limits (read these)

- **Whoever runs the server can read the keys**: the encryption key comes from the access token the operator holds. "Bring your own key" protects the operator's quota, **not you from the operator**. Use a key with its own spending limit at the provider.
- **The unit is attempts, not calls or tokens or money.** A retry is a row. The allowance can be passed by the few attempts already in flight when it runs out, no more.
- **The in-flight slots live in one process's memory.** The hosted version already runs **one** instance (see [hosting.md](hosting.md)); several would each hold their own slots (the count of rows is shared through the database, the reservation is not).
- One provider and one model per person; no backup models for a person (backups stay a server feature). A key the provider refuses fails the job with the provider's own error, with the key removed.
- No admin page, no per-person limit set by the owner (one number for everybody), no rate limit on saving a key, and no way to see who spent what except the usage rows in the database.
- The allowance resets at **midnight UTC**, not the person's midnight.
- Four small things the independent review found and that are **not fixed yet** (none loses a key or lets anyone past the allowance on purpose):
  - An attempt that fails with an error that is not the engine's own (an unexpected one from a provider's library) writes no usage row, so it is not counted; its in-flight slot frees itself after 10 minutes. A small under-count, hard to trigger.
  - The refusal for unsafe characters in a key still ends "put it in the .env file by hand", and a provider's "key rejected (401)" still says "Check ..._KEY in .env": advice for the owner that a hosted person cannot follow. The key itself is never in either message.
  - Changing only the model name needs the key pasted again, though the card is titled "Change your model or key".
  - `Bearer:KEY` (with a colon) is accepted as a key; the provider then refuses it with a 401.

## What was checked (2026-11-26)

- **Backend: 3,704 tests passed, 4 skipped** (they need a Linux Docker), none failed; 104 of them are new for this slice (3 came from the review below and 3 from the first real sign-in). All offline, none reads the real `.env`.
- **Web: 393 unit tests passed, the typecheck is clean.** The main real-browser suite (the real Edge browser against the real API, on side ports) **passed 100 of 100**.
- **The hosted version at phone size** (`npm run e2e:phone`, a 390 px touch browser against a throwaway hosted server with a fake model, so no network and no real key): **29 of 29** checks, including a person saving a key, the key being nowhere on the page or in any of the 6 answers the server gave afterwards, a reload, testing it and removing it.
- **40 deliberate breaks, all caught, and 1 browser break caught** (a break is a small wrong change made to the code on purpose, to see that a test fails; one that survives means a test is too weak). They include: a key stored in plain text, a key in an error message, the shared model borrowed by someone it is not shared with, an own-key call counted against the allowance, the gate removed, the in-flight slots removed, and `custom` offered to people.
- **Three problems were found while building**: the plan's "quota" error kind would have handed a blocked call to a backup model on the same server key (found by reading the engine's fallback list, so the kind is now `allowance`); six runs started at the same moment all got through a daily allowance (found by reading my own gate against the design, then a threaded test failed 6 of 6 before the in-flight slots fixed it); and the phone check showed a cookie sign-in cannot work across two web addresses, so the hosted build must be **same-origin** (already how the Docker image is built).
- **One independent review** (a fresh reviewer on the most capable model, 165k tokens, given the code, the rules and the failure modes to test but none of my conclusions): **1 Critical, 0 Important, 4 Minor.** The Critical one, reproduced as a failing test first (6 calls reached the server's model against a limit of 2) and fixed: **Discard deleted a build's usage rows, so a person could start and discard builds to use the shared model without limit** (`tests/test_model_review.py`, 3 tests). The review found the key handling, the sealing, the isolation between people and the owner's unchanged path sound; the 4 Minor ones are listed under Limits.
- **The first real sign-in found a defect that 3,700 tests and the review had not** (`tests/test_model_review.py`, 3 tests, the first two RED before the fix): the real `serve` command, which the Docker image also runs, built its own Builder **without the model options**, so on a real hosted server **Settings -> My model answered "This server cannot keep personal model keys."** and `SKILLFORGE_SHARED_KEY_CALLS_PER_DAY` did nothing. Every test built its Builder by hand and the phone check used its own launcher, so nothing ran `serve`. Fixed in `cli.py` (`_run_serve` passes `model_options(hosted)`, the same function the lazy path uses); the tests now run the real `_run_serve` and try to save a person's key. A local `serve` still has no personal keys and no sharing.
- **Not tried:** a real key saved through the form after that fix (the owner reported that a real Google sign-in worked and reached the My model form; a second Google account was refused because the allow-list held one address, which is the setting working as written), a real phone, a real provider key saved by a real person, and more than one server instance. After the review's fix the backend suite was re-run; the two browser suites and the web unit tests were not (the fix changes one backend method and nothing the web pages read).

## Where the code is

`builder/keybox.py` (sealing), `db/user_models.py` + migration `0007` (storage, `key_source`), `settings/rules.py` (`check_person_model`), `ai/service.py` (the gate), `builder/model_access.py` (`ModelAccess`: whose model, the allowance, the views), `api/me.py` (the routes), `builder/service.py`, `suggestions.py`, `evals.py` and `api/builds.py` (every call site), `api/hosted.py` (the setting).
Web: `lib/myModel.ts`, `components/settings/MyModel.tsx`, `app/settings/page.tsx`, `app/builder/page.tsx` (the banner). Tests: `test_keybox.py`, `test_person_model_rules.py`, `test_user_models_db.py`, `test_ai_gate.py`, `test_model_access.py`, `test_model_wiring.py`, `test_me_model_api.py`, `frontend/src/lib/myModel.test.ts`, and the phone-size browser check `frontend/e2e/hosted-phone.mjs`.
