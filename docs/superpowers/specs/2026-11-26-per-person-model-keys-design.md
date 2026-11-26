# Per-person model keys and limits (slice AI): design

Status: **built (slice AI), see [../../per-person-keys.md](../../per-person-keys.md) for what was built and checked.** The owner's "card ok, go" covered the order of the four sub-projects (deploy kit, accounts, keys and limits, phone checks), **not** the choices below: they are mine, each marked *my call*, and can be changed.
Depends on: accounts (slice AH, [accounts.md](../../accounts.md)).

## Intent

After slice AH, several people can sign in to one hosted SkillForge and each has their own builds and library. But **every model call still spends the one key set on the server**, so the owner pays for everyone and one busy person can use up the quota.
The settled decision is *bring your own key* (no money handled by this project). This slice lets a signed-in person use **their own model and key**, and lets the owner decide whether people without a key may use the server's key, and how much.

## Goals

1. A signed-in person can save **one model choice and one key** (provider, model name, key). Their builds, suggestion runs, Testing Lab runs and guide runs then use that, not the server's.
2. **A key is never sent back** to any browser, never put in a log, an error or a usage row, and is stored **encrypted**.
3. By default a person **without** a key gets a clear "add your key" answer; the server's key is used only for the owner, unless the owner switches sharing on (*my call*: safe by default).
4. The owner can share the server's key **with a daily cap per person** (a number of model calls). The count comes from the `model_calls` rows that already carry `user_id`.
5. Nothing changes for local use or for the owner: the owner's calls use the server's settings exactly as today.

## Non-goals

- Several keys or backup models per person (one provider, one model: *my call*; backups stay a server feature).
- Money: no prices, no billing, no payment.
- A cap in tokens or in money (calls are what the usage rows count reliably; tokens are provider estimates).
- An admin page, teams, or sharing a key between two people.

## Anti-goals (a failure even if it technically works)

- A key readable by another signed-in person, in any response, or in an error message.
- A person falling back to the **owner's** key by accident (a missing key must stop with a message, not borrow).
- A person's call recorded under the wrong person, so the cap is wrong.
- A cap that can be dodged by starting several runs at once.

## Constraints

- Settings stay off in the hosted version (a save there writes the server's `.env`); this slice adds a **separate, per-person** path that writes only the database.
- No new library: `cryptography` is already installed (PyJWT's `[crypto]` extra).
- Every model call still goes through `skillforge.ai` and names its task; the engine, its retries and its redaction are not bypassed.
- Tests are offline (a mock provider); no test reads the real `.env`.

## Approaches

| | A. Store the key encrypted on the server | B. Keep the key only in the browser, send it with every request | C. Only the owner's key, with caps (no personal keys) |
|---|---|---|---|
| Works for background jobs and on every device | yes | jobs need the key held in memory for their life; a new device must re-enter it | yes |
| The server never keeps a person's key | no (encrypted at rest) | yes | n/a |
| Matches "bring your own key" | yes | yes | no: the owner pays |
| Size | medium: a table, encryption, per-person provider lookup, 4 routes, a page | large: the key travels in a header on every job-starting route and into the job | small |

**Recommended and chosen (*my call*): A, plus the owner's optional shared key with a cap (the useful part of C).** B is the stronger privacy story, but a poll-based builder with background jobs makes it fragile and awkward on a phone, which is the point of the hosted version.
The honest cost of A is written in the limits below: whoever runs the server can read the keys.

## Design

**Storage.** A table `user_models` (migration 0007): `user_id` (primary key), `provider`, `model`, `key_ciphertext`, `key_nonce`, `updated_at`. One row per person. The key is encrypted with **AES-256-GCM**; the encryption key is derived with HKDF-SHA256 from `SKILLFORGE_ACCESS_TOKEN` using a label of its own (separate from the cookie-signing key). The person's id is bound in as associated data, so a ciphertext copied into another person's row does not decrypt.
Changing the access token makes stored keys unreadable: people are asked to enter them again (it already signs everyone out). Nothing about a key is stored in clear, not even its last characters.

**Using it.** One function, `provider_for(user_id)`, replaces the single `provider_factory()` in the builder, the suggestion runs, the Testing Lab and the guide route:
the owner gets today's `env_provider()`; another person gets `service_from_env({LLM_PROVIDER, LLM_MODEL, <that provider's key variable>: key})`, using the key variable names in `providers/factory.py`. No row means: the shared key if sharing is on and today's calls are under the cap, otherwise a typed error `no_model_key` (409) with a sentence the page shows. The jobs already know their person (`row.user_id`), so a background job resolves the provider for the row's person, never for whoever asks next.

**The cap.** `SKILLFORGE_SHARED_KEY_CALLS_PER_DAY=N` (unset or 0: the server's key is the owner's alone). Calls counted = rows in `model_calls` for that person since 00:00 UTC. The check happens when a run **starts** and again before each model call inside the engine's budget (the engine already has `max_calls`), so several simultaneous runs cannot each take the whole allowance (*my call*: reuse the engine's own per-run limit for "inside a run", and count rows at start for "across runs").

**Routes** (POST and DELETE only, never PUT: the CORS policy allows GET, POST and DELETE): `GET /api/me/model` (what is set: provider, model, "a key is saved on <date>", "uses the server's key", calls today and the cap; **never the key**), `POST /api/me/model` (provider, model, key: checked by the same rules as Settings: a fixed provider list, a safe model name, a key made of printable characters and of a sensible length), `DELETE /api/me/model`, `POST /api/me/model/test` (one tiny call, like "Test my models").
The owner gets the answer "the server's own settings are used". All four need a signed-in person.

**Page.** A **My model** section on a page for signed-in people: provider, model, a password-type key box that is cleared after saving, the saved/not saved state, a Test button, and the daily allowance when the server's key is shared.

## Changes found while planning against the code (2026-11-26; these override the text above where they differ)

1. **Only builder jobs recorded usage.** Suggestion runs and Testing Lab runs built their model with no recorder, so they left no `model_calls` row and a cap counted from rows would never see them. All three now go through one place (`ModelAccess.provider_for`) that attaches the recorder; `model_calls.session_id` is already nullable, so a run that has no builder session records `NULL`.
2. **Which key paid.** A person who has their own key must not use up the shared allowance, and one who deletes it must not find today's own-key calls counted. `model_calls` gets `key_source` (`server` or `own`, existing rows `server`); the allowance counts `server` rows of that person since 00:00 UTC.
3. **The cap is a gate before every attempt, not a per-run limit.** `AIService` gets an optional `gate` that runs inside `_guard` before every attempt and raises a `ProviderError(kind="allowance")` (a new error kind: "quota" is a FALLBACK kind, so the engine would hand the attempt to a backup model that uses the same server key, and "budget" is not retryable in the Testing Lab) when today's allowance is gone. A per-run `max_calls` would let several runs started together each take the whole remainder; the gate counts the person's rows on every attempt, so the overshoot is at most the attempts already in flight. The unit is **attempts** (a retry is a row), as the usage table counts.
4. **`custom` is not offered to people.** It takes an address from the person, which would make the server call any address they type. People choose from the fixed list without it.
5. **The form lives on the Settings page.** In the hosted version that page was switched off; it now shows **My model** for a signed-in person (the owner is told the server's own settings are used). No new menu entry.
6. **Settings for the server:** `SKILLFORGE_SHARED_KEY_CALLS_PER_DAY` (hosted only; unset or 0 means the server's model is the owner's alone). The three routes the web pages already use for "is a model set up" (`GET /api/provider`, `POST /api/provider/check`) become per person; the guide route and `/api/settings` are local-only and stay as they are.

## Threats considered

| Threat | Answer |
|---|---|
| Another person reads a key | never returned by any route; stored encrypted; a person's row is found only by the id from the session, never from the request |
| A key in a log, an error or a usage row | the engine already redacts keys it holds; a test sends a key through a failing provider and greps every response, log line and table |
| A copied ciphertext used for someone else | the person's id is the associated data of the encryption |
| Someone saves another provider's key as the wrong provider, or a huge or odd string | validated like Settings; the first failed call says "key refused", never repeats it |
| A person without a key borrows the owner's | `no_model_key` is raised before any provider is built; a test per entry point (build, suggest, lab, guide) |
| The cap dodged by parallel runs | counted at start, plus the per-run limit inside the engine |
| The owner is locked out by their own cap | the owner is never counted against it |

## Limits to state in the docs

- **Whoever runs the server can read the keys** (the encryption key comes from the access token the operator holds). "Bring your key" protects the operator's quota, not you from the operator. Use a key with its own spending limit at the provider.
- One provider and one model per person; no backups.
- The cap counts calls, not tokens or money; a long call counts once.
- An unreachable provider is a retry cost on the person's own key.

## What is left to the builder

Names of columns and routes beyond those above, the exact wording of messages, how the page shows the allowance, and whether the test button counts against the cap (default: it does not).

## How it will be checked

Test first, offline, with a mock provider: encryption round trip and the person-id binding; a wrong token cannot decrypt; every route refused without a sign-in; one person never sees or uses another's key (build, suggestion run, Testing Lab, guide); no key anywhere in responses, logs or rows; no-key stops with the typed error; the cap at the edge (N calls ok, N+1 refused, another person unaffected, the owner never refused, yesterday's calls not counted); parallel starts. Then deliberate breaks on every rule above, a real-browser run on side ports, and an independent review (it handles secrets).
