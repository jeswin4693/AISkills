# Per-person model keys and daily limits (slice AI) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
> **Execution chosen for this plan: native** (one session implements every task, then one fresh reviewer on the whole branch): the owner said "Start to work on next phase" and prefers no re-asking; the review gate in Task 9 is where an independent reader looks at the secret handling.

**Goal:** A signed-in person can save their own model and key (encrypted), their builds, suggestion runs and Testing Lab runs then use it, and the owner can share the server's model with a daily cap per person.

**Architecture:** One class, `ModelAccess`, decides which model a person's call uses and attaches the usage recorder; every model call site asks it (`provider_for(user_id)`). A key is sealed with AES-256-GCM under a key derived from the access token, bound to the person's id. The daily allowance is a gate inside `AIService` that counts the person's `model_calls` rows (`key_source = 'server'`) before every attempt.

**Tech Stack:** Python 3.13, FastAPI, SQLAlchemy + Alembic (SQLite), `cryptography` (already installed through `pyjwt[crypto]`: no new library), Next.js/React + vitest, Playwright (Edge).

**Spec:** [docs/superpowers/specs/2026-11-26-per-person-model-keys-design.md](../specs/2026-11-26-per-person-model-keys-design.md), including its section "Changes found while planning against the code", which overrides the earlier text.

## Global Constraints

- A key is **never** returned by any route, never in a log, an error, a usage row or the browser after it is sent once; stored only as ciphertext. A refusal names the field and why, never the value.
- Encryption: AES-256-GCM; key = HKDF-SHA256 of `SKILLFORGE_ACCESS_TOKEN` with `info=b"skillforge-user-keys-v1"` (not the cookie-signing key); associated data = the person's id; a fresh 12-byte nonce per seal. Changing the token makes stored keys unreadable: say so, never a 500.
- Providers for people: `supported_names()` **without** `custom`. Model name and key use the Settings `SAFE` characters (`A-Za-z0-9._~:/,@+=%-`), key at most 400 characters, model at most 200.
- Routes: GET, POST and DELETE only (CORS allows nothing else); a body that fails validation must not echo its input (the app's 422 handler already guarantees this: keep using pydantic bodies, and test it).
- Every model call goes through `skillforge.ai` and names its task; settings are read only in `service_from_env`; no test reads the real `.env` or calls a hosted model (use `MockProvider` and the `ModelOptions.build` seam).
- The owner (`LOCAL_USER_ID`) always uses the server's model and is never capped; local use is unchanged.
- Another person's data is a 404 identical to a missing one; a forgotten `user` argument means the owner (fail closed), as in slice AH.
- After the slice: tests pass, `docs/per-person-keys.md` written, README, roadmap, CLAUDE.md and `.env.example` updated, deliberate breaks run, an independent review (it handles secrets), then commit and push.

## Review Focus

Failure modes the spec implies but does not spell out. Each line has its test in the task named in brackets.

1. **A pasted key with whitespace, a newline, quotes or "Bearer " in front.** Expected: surrounding whitespace is trimmed and the key is accepted; quotes or "Bearer" are refused with a message that says what to remove, never repeating the key. [Task 2]
2. **The access token was changed.** Stored keys cannot be opened: the person sees "enter your key again" and `key_readable: false`; builds fail with that message (retryable), no 500. [Task 4]
3. **A key for the wrong provider** (a Groq key saved as OpenAI). The provider answers 401: the job fails with the engine's `auth` error, which must not contain the key. [Task 5]
4. **Several runs started at the same moment on the shared allowance.** Expected: the allowance is enforced on every attempt, so the total never exceeds the limit by more than the attempts already in flight. [Task 3, Task 5]
5. **The day boundary and a removed key.** Calls from before 00:00 UTC are not counted; own-key calls never use the allowance; deleting a key while a job runs leaves that job on the model it started with. [Task 4]

---

### Task 1: `KeyBox`, sealing a key under the access token

**Files:**
- Create: `backend/skillforge/builder/keybox.py`
- Test: `backend/tests/test_keybox.py`

**Interfaces:**
- Produces: `class KeyBoxError(Exception)`; `class KeyBox` with `__init__(self, access_token: str)`, `seal(self, user_id: str, secret: str) -> tuple[bytes, bytes]` (ciphertext, nonce) and `open(self, user_id: str, ciphertext: bytes, nonce: bytes) -> str` (raises `KeyBoxError`, whose message never contains the secret or the token).

- [ ] **Step 1: Write the failing tests** in `test_keybox.py`: `test_a_sealed_key_opens_for_the_same_person_and_token`; `test_the_ciphertext_does_not_contain_the_key`; `test_another_persons_id_cannot_open_it` (the associated data); `test_another_access_token_cannot_open_it`; `test_a_flipped_byte_is_refused`; `test_two_seals_of_the_same_key_differ` (fresh nonce); `test_an_error_never_repeats_the_key_or_the_token`; `test_a_token_that_is_empty_is_refused_at_construction`.
- [ ] **Step 2: Run them; expect FAIL** (`ModuleNotFoundError`): `python -m pytest tests/test_keybox.py -q` from `backend/`.
- [ ] **Step 3: Implement `KeyBox`** with `cryptography`'s `HKDF(SHA256, length=32, salt=None, info=b"skillforge-user-keys-v1")` and `AESGCM`; the associated data is `b"user:" + user_id.encode()`.
- [ ] **Step 4: Run them; expect PASS.**
- [ ] **Step 5: Commit** `git add backend/skillforge/builder/keybox.py backend/tests/test_keybox.py && git commit -m "Slice AI: KeyBox, a key sealed under the access token"`.

### Task 2: Storage (`user_models`, `key_source`) and the person's validation rules

**Files:**
- Modify: `backend/skillforge/db/models.py` (add `UserModelRow`; add `ModelCall.key_source`), `backend/skillforge/db/__init__.py` (exports), `backend/skillforge/settings/rules.py` and `backend/skillforge/settings/__init__.py` (export)
- Create: `backend/skillforge/db/migrations/versions/0007_user_models.py`, `backend/skillforge/db/user_models.py`
- Test: `backend/tests/test_user_models_db.py`, `backend/tests/test_person_model_rules.py`

**Interfaces:**
- Produces: table `user_models(user_id PK -> users.id ON DELETE CASCADE, provider String(32), model String(128), key_ciphertext LargeBinary, key_nonce LargeBinary, updated_at String(32))`; column `model_calls.key_source String(8) NOT NULL default/server_default 'server'`; `@dataclass(frozen=True) class StoredModel(provider: str, model: str, key_ciphertext: bytes, key_nonce: bytes, updated_at: str)`; `class ModelStore(db: Database)` with `get(user_id) -> StoredModel | None`, `put(user_id, provider, model, ciphertext, nonce) -> StoredModel` (replaces any existing row), `delete(user_id) -> bool`; `PERSON_PROVIDERS: tuple[str, ...]`; `check_person_model(provider: str, model: str, key: str) -> tuple[str, str, str]` returning the cleaned triple or raising `SettingsError` with `problems` `[{"name": "provider" | "model" | "key", "message": str}]`.

- [ ] **Step 1: Write the failing tests.** `test_user_models_db.py`: the migration to head creates `user_models` and the column and matches the models exactly (use the existing migration-vs-models comparison pattern in `test_users_db.py`); existing `model_calls` rows read `key_source == 'server'`; `put` then `get` round-trips and a second `put` replaces; `delete` returns True then False; the database file's bytes never contain the key (put ciphertext of a known string, read the file); a downgrade to 0006 keeps `jobs` and `model_calls` rows (use plain `drop_column`, as 0006 now does). `test_person_model_rules.py`: provider list excludes `custom` and includes `anthropic`; `custom` is refused naming why; a model with a space, quote, backslash, control or invisible character is refused; a key with surrounding whitespace or a trailing newline is trimmed and accepted; a key in quotes is refused with "Remove the quotes"; a key starting with "Bearer " is refused with "without the word Bearer"; a 401-character key is refused; no error message contains the key (assert with a distinctive key).
- [ ] **Step 2: Run them; expect FAIL.**
- [ ] **Step 3: Implement** the model rows, migration `0007` (`op.create_table`, `op.add_column` plain: never `batch_alter_table`, see 0006's comment; downgrade with plain `op.drop_column`), `ModelStore`, and `check_person_model` in `rules.py` reusing `_safe`, `SAFE` and `LIMITS`.
- [ ] **Step 4: Run them plus `tests/test_builder.py` (it pins the table set: add `user_models`) and `tests/test_usage_db.py` (it pins `model_calls` columns: add `key_source`, keeping its "no text stored" assertion).**
- [ ] **Step 5: Commit** the files above with `-m "Slice AI: user_models, key_source and the rules for a person's model"`.

### Task 3: A gate inside `AIService`

**Files:**
- Modify: `backend/skillforge/ai/service.py` (`AIService.__init__`, `with_recorder`, `escalated`, `_guard`)
- Test: `backend/tests/test_ai_gate.py`

**Interfaces:**
- Produces: `AIService(..., gate: Callable[[], None] | None = None)`; `with_recorder(self, recorder, *, gate: Callable[[], None] | None = None) -> AIService` (keeps `self.gate` when the argument is None); `escalated()` passes `self.gate` on. `_guard` calls `self.gate()` first, before the `max_calls` check; whatever the gate raises (a `ProviderError`) propagates unchanged.

- [ ] **Step 1: Write the failing tests:** `test_the_gate_runs_before_every_attempt_not_once_per_call` (a provider that fails twice then succeeds: the gate is called 3 times); `test_a_gate_that_raises_stops_the_call_before_the_provider_is_asked` (the mock provider's call count stays 0); `test_with_recorder_and_escalated_keep_the_gate`; `test_no_gate_changes_nothing` (existing behaviour); `test_a_gate_error_is_not_retried` (kind `quota` from the gate is raised, not retried by the policy).
- [ ] **Step 2: Run; expect FAIL.**
- [ ] **Step 3: Implement** the optional parameter and the call at the top of `_guard`; read how `generate` loops (around line 207) to be sure `_guard` runs per attempt, and keep a gate error out of the retry policy if it would otherwise be retried.
- [ ] **Step 4: Run `tests/test_ai_gate.py` and the existing `tests/test_ai_*.py`; expect PASS.**
- [ ] **Step 5: Commit** `-m "Slice AI: an optional gate before every model attempt"`.

### Task 4: `ModelAccess`, the one place that says which model a person uses

**Files:**
- Create: `backend/skillforge/builder/model_access.py`
- Modify: `backend/skillforge/builder/usage.py` (`DbUsageRecorder(db, session_id: str | None, job_id=None, user_id=LOCAL_USER_ID, key_source: str = "server")`), `backend/skillforge/builder/__init__.py` (export `ModelAccess`, `ModelOptions`), `backend/skillforge/api/hosted.py` (`Hosted.shared_calls_per_day: int = 0`, read from `SKILLFORGE_SHARED_KEY_CALLS_PER_DAY` in `from_env`: whole number 0 to 1,000,000, anything else refuses to start naming the setting)
- Test: `backend/tests/test_model_access.py`

**Interfaces:**
- Consumes: `KeyBox` (Task 1), `ModelStore`, `check_person_model` (Task 2), `AIService.with_recorder(recorder, gate=...)` (Task 3), `service_from_env`, `provider_status`, `check_models`.
- Produces: `@dataclass(frozen=True) class ModelOptions(keybox: KeyBox | None = None, shared_calls_per_day: int = 0, build: Callable[[Mapping[str, str]], LLMProvider] = service_from_env, clock: Callable[[], datetime] = utc_now)`; `class ModelAccess(db: Database, server_provider: Callable[[], LLMProvider], options: ModelOptions = ModelOptions())` with
  - `provider_for(user_id: str, *, session_id: str | None = None, job_id: int | None = None) -> LLMProvider`: owner gets the server's model; a person with a saved model gets `options.build({"LLM_PROVIDER": p, "LLM_MODEL": m, KEYVAR: key})` (KEYVAR from `providers.factory.key_variables()`), recorded as `key_source="own"`; a person without one gets the server's model with the allowance gate if `shared_calls_per_day > 0`, else a `ProviderError(kind="auth", retryable=True)` saying to add a key in Settings; an unreadable key (token changed) is a `ProviderError(kind="auth", retryable=True)` saying to enter it again. Every returned `AIService` has the usage recorder attached.
  - `status_for(user_id) -> dict` (the `provider_status` shape plus `"source": "own" | "server" | "none"` and `"allowance": {"limit": int, "used": int} | None`), `my_model(user_id) -> dict`, `save(user_id, provider, model, key) -> dict`, `remove(user_id) -> dict`, `test(user_id) -> dict` (one tiny call on the person's OWN model only; `{"configured": False, ...}` without one), `used_today(user_id) -> int` (rows with `key_source='server'`, `created_at >= <today UTC>T00:00:00`).
  - `my_model` returns `{"mode": "owner" | "own" | "shared" | "none", "provider", "model", "key_saved": bool, "key_saved_at": str, "key_readable": bool, "allowance": {...} | None, "providers": [names], "message": str}`; never a key, not even its end.

- [ ] **Step 1: Write the failing tests** in `test_model_access.py` (a fake `build` records the env mapping it gets and returns `AIService.single(MockProvider(...))`; a fake clock): owner never touches the store or the gate; a person with a saved model gets the fake-built provider with exactly the key they saved (decrypted) and **no other key in the mapping**; own-key calls are recorded with `user_id` and `key_source="own"` and never count toward the allowance; no key + sharing off raises the "add your own key" error; no key + sharing on returns the server model and the gate raises `kind="quota"` at `used >= limit`, counting only that person's `server` rows from today UTC (yesterday's and another person's rows ignored, own-key rows ignored); the gate counts rows per attempt, so a second provider made for the same person while the first is in flight sees the first's rows [Review 4]; deleting the key while a built provider exists leaves that provider working and the next `provider_for` falls back [Review 5]; a different access token yields `key_readable: False` and a retryable `ProviderError` with no key text [Review 2]; `save` validates through `check_person_model` and refuses for the owner, for a missing keybox, and for `custom`; `my_model` and `status_for` never contain the key (assert on `json.dumps`); `Hosted.from_env` parses the new setting and refuses `-1`, `abc` and `10**7`.
- [ ] **Step 2: Run; expect FAIL.**
- [ ] **Step 3: Implement** `ModelOptions`, `ModelAccess` and the recorder's new parameters; the allowance gate is a closure that raises `ProviderError("You have used today's allowance of N model calls on this server's model (it resets at midnight UTC). Add your own model key in Settings to go on.", kind="quota", retryable=True)`.
- [ ] **Step 4: Run `tests/test_model_access.py tests/test_hosted.py tests/test_usage_db.py`; expect PASS.**
- [ ] **Step 5: Commit** `-m "Slice AI: ModelAccess decides which model a person uses, and the shared allowance"`.

### Task 5: Every model call asks `ModelAccess`

**Files:**
- Modify: `backend/skillforge/builder/service.py` (`Builder.__init__(..., model_options: ModelOptions = ModelOptions())`, `Builder.default(library, library_for=None, model_options=ModelOptions())`, `self.access`, `_provider`, the `suggestions` and `evals` properties), `backend/skillforge/builder/suggestions.py` (`SuggestRuns(db, runner, provider_for: Callable[[str], LLMProvider])`, `_execute` reads the row's `user_id`), `backend/skillforge/builder/evals.py` (`EvalRuns(db, runner, provider_for, library, library_for=None)`, `_execute` passes `owner`), `backend/skillforge/api/app.py` and `backend/skillforge/api/builds.py` (`get_builder` builds `ModelOptions(keybox=KeyBox(hosted.token), shared_calls_per_day=hosted.shared_calls_per_day)` when hosted; `/provider` and `/provider/check` use the caller's person)
- Modify (tests that built these directly): `backend/tests/test_accounts_isolation.py` (the `World` helper passes `ModelOptions(shared_calls_per_day=1_000_000)` so people can use the mock; the three direct constructions take `lambda user: mock`)
- Test: `backend/tests/test_model_wiring.py`

**Interfaces:**
- Consumes: `ModelAccess.provider_for/status_for/test` (Task 4).
- Unchanged on purpose: the repository guide route and `/api/settings` (local-only, so always the owner).

- [ ] **Step 1: Write the failing tests:** a person's **build** uses the person's own provider (the fake `build` sees their key; Bob's job never sees Ada's); a person's **suggestion run** and **Testing Lab run** do too and leave `model_calls` rows under their id with `session_id IS NULL`; a person with no key and sharing off gets a failed build/run whose error says to add a key and is `retryable`; the owner's calls are unchanged and now recorded for suggestion/lab runs too; `GET /api/provider` for a person without a key says `configured: false` with the add-a-key detail and `source: "none"`, with a key says `own` and the model (never the key), with sharing on says `server` and the allowance; `POST /api/provider/check` makes one call on the person's own model only; **a wrong key** (the fake provider raises `ProviderError(kind="auth")`) fails the job with an error that does not contain the key [Review 3]; run 6 simultaneous suggestion runs for one person on a shared allowance of 3 against a mock provider and assert the mock was asked at most 3 + in-flight times [Review 4].
- [ ] **Step 2: Run; expect FAIL.**
- [ ] **Step 3: Implement the wiring.** `Builder._provider` becomes `return self.access.provider_for(user_id, session_id=sid, job_id=job_id)`; remove its own recorder code (the recorder now lives in `ModelAccess`).
- [ ] **Step 4: Run the whole of `tests/test_accounts_isolation.py tests/test_builder.py tests/test_testing_lab*.py tests/test_suggest*.py tests/test_usage_db.py tests/test_model_wiring.py`; expect PASS.**
- [ ] **Step 5: Commit** `-m "Slice AI: builds, suggestion runs and Testing Lab runs use the person's model"`.

### Task 6: The routes `/api/me/model`

**Files:**
- Create: `backend/skillforge/api/me.py`
- Modify: `backend/skillforge/api/app.py` (include the router under `/api`)
- Test: `backend/tests/test_me_model_api.py`

**Interfaces:**
- Produces: `GET /api/me/model -> my_model`; `POST /api/me/model` with body `{"provider": str (max 40), "model": str (max 200), "key": str (max 400)}` `-> my_model` (400 with `{"detail", "problems"}` from `SettingsError`, never the key); `DELETE /api/me/model -> my_model`; `POST /api/me/model/test -> test()`. The owner on POST/DELETE gets 403 saying the owner's model is set in the server's environment (hosted) or Settings (local); signed out is 401 as for every route.

- [ ] **Step 1: Write the failing tests** (the `World` helper from `test_accounts_isolation.py`): Ada saves a model and Bob's `GET` shows nothing of it and no key anywhere in any of Bob's responses; Ada's own responses never contain her key (assert on the raw text of every response, and on `caplog`); a malformed body (422) and a refused value (400) do not echo the key [Global Constraints]; `custom` is refused; the owner gets 403 on POST and DELETE and `mode: "owner"` on GET; `DELETE` is idempotent; `POST .../test` uses only the person's own key and says so when there is none; local mode (no accounts) answers `mode: "owner"` and refuses writes; no route accepts PUT.
- [ ] **Step 2: Run; expect FAIL.**
- [ ] **Step 3: Implement the router** with the caller's person from `api/scope.user_id(request)`, thin over `ModelAccess` (`get_builder(app).access`).
- [ ] **Step 4: Run `tests/test_me_model_api.py` and `tests/test_accounts_*.py`; expect PASS.**
- [ ] **Step 5: Commit** `-m "Slice AI: GET/POST/DELETE /api/me/model and the test route"`.

### Task 7: The My model section on the Settings page

**Files:**
- Create: `frontend/src/lib/myModel.ts`, `frontend/src/lib/myModel.test.ts`, `frontend/src/components/settings/MyModel.tsx`
- Modify: `frontend/src/lib/types.ts` (`MyModelView`, extend `ProviderStatus` with optional `source` and `allowance`), `frontend/src/lib/api.ts` (`myModel`, `saveMyModel`, `removeMyModel`, `testMyModel`), `frontend/src/app/settings/page.tsx` (when `useAuth().hosted`, render `<MyModel />` instead of the `.env` editor), `frontend/src/app/builder/page.tsx`, `frontend/src/components/testing/TestingLab.tsx` and `frontend/src/app/repository/page.tsx` (the "No AI model is set up" wording: in hosted, "Add your own model key in Settings", not ".env")

**Interfaces:**
- Produces in `myModel.ts`: `PERSON_PROVIDERS: string[]` (same list as the server's, no `custom`); `cleanKey(raw: string): string` (trims); `problemsWith(provider: string, model: string, key: string): { provider?: string; model?: string; key?: string }` (the same rules as the server: safe characters, lengths, no quotes, no "Bearer"); `allowanceText(a: { limit: number; used: number } | null): string`.

- [ ] **Step 1: Write the failing unit tests** in `myModel.test.ts` mirroring the server rules (`custom` absent; quotes and "Bearer" named; trimmed key accepted; long values refused; messages never contain the key; `allowanceText` for 0 used, partly used, used up, none).
- [ ] **Step 2: Run `npm test`; expect FAIL.**
- [ ] **Step 3: Implement** `myModel.ts`, then the component: provider select, model input, a `type="password"` key input with `autoComplete="off"` that is **cleared after a save**, a Save button disabled while the rules say no (each problem shown next to its field), a Test button, a Remove button, the saved state ("a key is saved on <date>", never the key), and the allowance line; the owner sees the sentence that the server's own settings are used. 44 px tap targets (`min-h-11`) as on the sign-in screen.
- [ ] **Step 4: Run `npm test` and `npm run typecheck`; expect PASS and clean.**
- [ ] **Step 5: Commit** `-m "Slice AI: the My model section on the Settings page"`.

### Task 8: Drive it in a real browser at phone size

**Files:**
- Modify: `frontend/e2e/hosted_server.py` (it builds its own `Builder`, so pass it `model_options=ModelOptions(keybox=KeyBox(hosted.token), shared_calls_per_day=hosted.shared_calls_per_day)`; at startup write a signed session cookie for one made-up person to `<data>/person-cookie.txt` using the product's own `make_cookie` and `UserStore.upsert_google`; leave `SKILLFORGE_SHARED_KEY_CALLS_PER_DAY` unset so that person starts with no model), `frontend/e2e/hosted-phone.mjs` (a second context signed in as that person, using the cookie file)

- [ ] **Step 1: Add the failing checks** to `hosted-phone.mjs`: as the person, Settings shows My model; saving a model with a made-up key works and the page then says a key is saved and **the key is not anywhere in the page text, the DOM or the network responses**; the key box is empty after saving; Remove returns to "no model"; the form fits 390 px with no sideways scroll and 44 px tap targets; as the owner, Settings shows the owner sentence.
- [ ] **Step 2: Run `NEXT_PUBLIC_API_URL=same-origin SKILLFORGE_PROXY_API=http://127.0.0.1:8100 npm run build` then `npm run e2e:phone`; expect the new checks to FAIL until Task 7's page is built, then PASS.**
- [ ] **Step 3: Commit** `-m "Slice AI: the My model form driven at phone size"`.

### Task 9: Docs, breaks, full suites, independent review, push

**Files:**
- Create: `docs/per-person-keys.md`
- Modify: `.env.example` (commented `SKILLFORGE_SHARED_KEY_CALLS_PER_DAY`), `docs/hosting.md` (settings table), `docs/accounts.md` (the "Limits" line about the server's model key), `docs/roadmap.md`, `README.md`, `CLAUDE.md`, the design doc's status line

- [ ] **Step 1: Write `docs/per-person-keys.md`** (what it does, settings, who can see what, the limits already in the design plus: attempts not calls; a few in-flight attempts can overshoot; the operator can read keys; `custom` not offered; tokens change = re-enter keys).
- [ ] **Step 2: Deliberate breaks** (script in the scratchpad as for slice AH): the AAD removed; a key returned by any route; the owner capped; `custom` allowed; own-key rows counted toward the allowance; yesterday's rows counted; the gate skipped; the key left in the form after save; `key_source` not recorded; the person's provider built with the owner's key in the mapping; unreadable key not caught. Every break must fail a test; strengthen the test first when one survives.
- [ ] **Step 3: Full backend suite (background), `npm test`, `npm run typecheck`, `npm run build` + `npm run e2e` (side ports) and `npm run e2e:phone`; expect all green** (report the counts).
- [ ] **Step 4: Independent review** by a fresh reviewer given the code, the Global Constraints and the claims to test, none of my conclusions; state its cost first (about 130k to 230k tokens); reproduce every finding as a failing test before fixing.
- [ ] **Step 5: Commit and push** (`git status -sb` must show no "ahead"); update the memory notes.
