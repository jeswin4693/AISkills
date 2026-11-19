# AI engine: one model service for every builder

**Status: built (2026-11-19), steps A0 to A3. Not built: the tier benchmark (A4).** Written from the assessment of the
existing Gemini integration and approved by the project owner. The plan is
[superpowers/plans/2026-11-19-ai-engine.md](superpowers/plans/2026-11-19-ai-engine.md). Results and limits are at the end.

## Why

Four builders (skill, agent, plugin, MCP server) will share one way of talking to a model. Today every feature calls
`generate_with_retry(provider, Schema, prompt, system)` and gets the one model in `.env`. That works and is verified
live with Gemini, but it has gaps the new builders would hit first:

| Gap in the source today | Effect |
|---|---|
| One model for the whole process | No cheaper model for extraction, no stronger one for code |
| `response.usage` is dropped; only calls are counted | Cost is invisible, and quota use is under-reported |
| SDK retries twice (hidden) and `generate_with_retry` twice more | Up to 6 HTTP calls for one failure, counted as 2 |
| SDK read timeout is 600 s | A hung call holds one of two job threads for 10 minutes |
| A 429 is final after the SDK's retries | No wait, no "try in N seconds" |
| A retry resends the identical prompt | An invalid answer is not told what was wrong |
| No capability declaration (decision D1 promised one) | Nothing warns that a model is a poor fit |
| No Anthropic adapter (only a mocked smoke script) | Adding Claude later would mean new code in every builder |

## Goals

- Gemini stays the default provider and model. With no new setting, every call goes to the same model with the same
  prompt as before.
- A builder says **what kind of task** it is doing; configuration says which model does it. Adding OpenAI or Anthropic
  later changes configuration, not builders.
- Fewer wasted calls, every real attempt counted, tokens recorded, bounded waits.
- Code stays the judge: nothing here asks a model whether its own answer is good.

## Non-goals (not in this slice)

Temperature or seed control, a Settings page, a "test the key" button, fixing `.env` edits needing a restart (the first
`load_dotenv` wins), session-level budgets across jobs, the tier benchmark (A4: it spends quota and needs the new
builders' sample requirements first), and any new Python library (`anthropic` is already pinned).

## Design

```
builders --task hint--> AIService
                        1 route:   task -> tier -> profile (provider, model, timeout, limits)
                        2 guard:   preflight size estimate, per-run call budget
                        3 call:    one HTTP attempt, no hidden retries (SDK max_retries = 0)
                        4 policy:  classify the error; backoff with jitter; honour Retry-After;
                                   tell the model what was invalid, once; escalate only when asked
                        5 record:  one usage row per attempt (tokens, latency, status), never prompt text
providers/ openai_compat (Gemini, OpenAI, Groq, ...) | anthropic (new) | MockProvider (tests)
```

`AIService` also presents itself as an `LLMProvider` (`name`, `model`, `generate_structured`), so builders keep their
`provider` parameter and tests keep using `MockProvider`. A bare provider is wrapped on the fly with no waiting, so
today's tests behave exactly as before.

### Tasks and tiers

Tiers are named by the kind of work, never by a model. The mapping lives in code; the models live in the environment.

| Task | Tier | Used by |
|---|---|---|
| `extract`, `select` | `fast` | requirement extraction, task intake, rule selection |
| `design`, `suggest` | `design` | skill drafts, suggest review and ideas |
| `code` | `code` | helper scripts (later: MCP tool bodies, hook scripts) |
| `act` | `actor` | `eval` replies (a model standing in for an agent) |

### Settings

Existing: `LLM_PROVIDER`, `LLM_MODEL`, the key variables. New, all optional (a tier that is not set uses the default):

```
LLM_<TIER>_PROVIDER, LLM_<TIER>_MODEL        TIER = FAST, DESIGN, CODE, ACTOR
LLM_ESCALATION_PROVIDER, LLM_ESCALATION_MODEL   used only after the checks failed twice (never otherwise)
LLM_TIMEOUT_S (default 90; the code tier defaults to 180 only when this is not set, and an explicit value applies to
              every tier), LLM_<TIER>_TIMEOUT_S
LLM_<TIER>_MAX_OUTPUT_TOKENS (default: none), LLM_MAX_INPUT_TOKENS (default: none)
LLM_MAX_CALLS         HTTP attempts allowed per run (default: none)
SKILLFORGE_LLM_CACHE  1 turns the response cache on (default: off)
```

A tier that names another provider needs that provider's key variable. A mistake (missing key, `LLM_CODE_MODEL` with a
different provider but no model, a number that is not a number) fails at start-up and names the variable. It never
falls back silently to the default model.

### Error policy (code, in `ai/policy.py`)

| Kind | Attempts | Wait |
|---|---|---|
| overloaded (5xx), timeout, connection | 3 | 1.5 s, then 3 s, plus up to 25 % jitter |
| rate_limit (429) | 3 | `Retry-After`, or "retry in N s" in the message, or backoff; stop if the wait is over 30 s |
| invalid_output | 2 | none; the second prompt ends with what was wrong (at most 600 characters) |
| other, marked retryable | 2 | backoff |
| auth, model_missing, bad_request, quota, refused, too_long, budget | 1 | stop |

An explicit `attempts=` from a caller (suggest passes 2) is a hard cap. A length cut-off (`too_long`) is no longer
retried with the same prompt: it would fail the same way.

### Usage

One row per HTTP attempt in a new table `model_calls` (migration 0002): session, job, task, tier, provider, model,
attempt, status, error kind, input and output tokens (null when the provider gives none), latency. Prompt and reply
text are never stored. The session payload gains a `usage` summary and the result page shows it ("Model use while
building: 4 attempts at the model · 1,734 tokens in and 1,515 out · gemini-3.5-flash-lite."). Tokens are the provider's
numbers, never an estimate. A builder session records rows only when its model is an `AIService`; a bare provider is used as it is.

### Escalation

If `LLM_ESCALATION_MODEL` is set and the skill design still fails structural checks after its one repair, the design
is asked once more on that model and kept only if it scores better. Nothing is escalated by default, and a model's own
confidence never triggers it.

### Secrets

Provider error text is stored and shown, so every error passes through a redaction step that removes the exact key
values the providers hold and common key shapes. The service never reads `.env`; it is given an environment mapping
(like `provider_from_env(env)`), so the test fixture that blocks the real `.env` keeps working.

### Response cache (opt-in)

Off unless `SKILLFORGE_LLM_CACHE=1`. Keyed by a hash of provider, model, schema, system and prompt; stores only answers
that already passed schema validation; never used for `act` (a test must be able to ask twice); entries expire after 7
days, at most 500 are kept. Files are written under the per-user data folder (`llm-cache/`, next to the graph cache,
outside OneDrive), not the database, because the command line never opens the database. **A cache hit returns the same
answer, so a "retry" with the same prompt does not get a fresh sample**; that is why it is off by default.

## Decisions

Approved by the owner: a thin layer in front of the providers (not a rewrite, not a gateway library); the tier names and
`LLM_<TIER>_…` variables above; SDK retries off in favour of one policy, and a 90 s timeout in place of 600 s; a usage
table that stores counts and timings only; the cache; the Anthropic adapter. Calls of mine, open to change: Anthropic is
asked with `messages.create` and a JSON schema in `output_config.format`, validated by our code, with none of the beta flags
from the smoke script (the SDK's `messages.parse` validates inside the call, so a refusal, which has no content, would have
looked like invalid output); the cache is a file cache, not a database table; the per-run call budget is per `AIService`
instance (one job), not per session; a cache hit is a usage row with status `cache` and attempt 0, and is not a call.

## Results (2026-11-19)

- **Backend:** 755 tests run, 753 passed, 2 skipped (the ones that need a Linux Docker or symlinks, as before), up from 626;
  about 130 are new. Every old test passes unchanged except two edits to old tests that were expected: the
  "Supported providers" message now lists `anthropic`, and the migration test's list of tables now includes `model_calls`.
- **Web UI:** typecheck clean, 53 unit tests (3 new). The real-browser suite (`npm run e2e`) was **not run** for this slice.
- **Live, Gemini (`gemini-3.5-flash-lite`), through the new service:**
  - one tiny call: 1 attempt, 10 tokens in and 25 out, 1.3 s, routed as `fast`;
  - two real builder conversations in a scratch data folder (your library and database untouched). The first stopped
    after 3 rounds with "requirements still incomplete (4/6)": the model gave a supporting quote for `outputs` that was not
    word for word in the person's text, so the checklist (correctly) did not count it. The second finished: `count-todos`,
    30 checks passed, 0 failed, 4 not run, 4 attempts, 0 errors, 1,734 tokens in and 1,515 out, 7.9 s. In both, the usage rows
    added up exactly to the session totals. Two runs say little about how often the model leaves a slot unanswered.

## Limits and what is not verified

- **Never run against the real service:** the Anthropic adapter (mock only: there is no key), a tier or escalation model of a
  second provider, the response cache against a real model, and a real 429 (the wait handling is tested with a mocked server).
- **Behaviour changes** (all approved, all tested): the SDK's hidden retries are off, so each failure is retried by our policy
  and every attempt is counted; the call timeout is 90 s instead of 600 s; a length cut-off is no longer retried with the same
  prompt; connection errors and timeouts are now retried by us (the SDK did it before, invisibly).
- **Escalation covers the skill design only.** Scripts, evaluation repairs and the other call sites do not escalate yet.
- **Provenance still records the default model only.** The usage table has the model of every attempt, but only for builder
  sessions; the command line does not write usage anywhere (it has no database).
- **The call budget is per run (one job), not per session.**
- **Not fixed here, found in the assessment:** an edit to `.env` is not noticed by a running server (the first `load_dotenv`
  wins), "configured" in the status panel does not prove the key works, and `.env` sits in a OneDrive-synced folder (a real
  user environment variable would avoid that; it wins over the file).
- **The tier benchmark (A4) is not built.** Which tasks need a stronger model than Flash-Lite is still a guess: it needs sample
  requirements for the agent and MCP builders, and it spends quota, so it waits for them.
- **The cache stores model answers on disk** (under the per-user data folder, outside OneDrive). They come from what the
  person typed, so the folder is as private as the account.

## Left for the builder

The exact wording of redaction patterns, the file layout of the cache, and the wording of the usage line in the UI.
