# Design decisions

## D1 - Audience and deployment model (2026-11-17)

**Decision:** open source, for anyone to use. Self-hosted and bring-your-own-model first
(each user runs the app and uses their own provider API key).
Hosted with per-user encrypted keys can follow with the UI step. A hosted service where we
supply and pay for the model is not planned.

**Consequences**

- The LLM layer stays provider-neutral. Each adapter declares what it supports (JSON-schema output,
  context size) and the app warns when a model is too weak.
- Every generated skill records which model produced it.
- The sandbox must **fail closed**: if no safe sandbox is available, testing refuses to run.
  It must never fall back to running generated code on the host.
- Keys come only from the environment or settings. No key is ever stored in the repo.
- Install must be simple and work on Windows, macOS and Linux (CI on all three).
- Quality checks (validators, sandbox tests) matter more, because users will bring models of very
  different quality.

**Open items before the repo is made public**

- Choose a license (the repo has none yet, so by default nobody may reuse the code).
- Add a contributing guide and a security-reporting policy.
- Review docs for personal or employer information.
- Confirm that publishing is allowed under your employment / IP terms.

## D2 - Provider: bring your own API key, Gemini first (2026-11-17)

**Decision:** the first provider is Google Gemini, using the project owner's own key, through Gemini's
OpenAI-compatible endpoint. OpenAI and Anthropic are supported as additional adapters. OpenAI was tried
first, but the owner's account had no credits (HTTP 429).

**Consequences**

- This repo ships no key, no bundled model and no hosted service, so the project itself has no running cost.
- Gemini has a free key with rate limits, so there is a no-payment path for users. Free-tier terms and
  limits are Google's and can change.
- OpenAI and Anthropic usage is billed by the provider to whoever owns the key.
- `.env.example` defaults to `LLM_PROVIDER=gemini`. `LLM_MODEL` has no default, because models are retired
  for new users while still appearing in the provider's model list (`gemini-2.5-flash` was already
  unavailable to a new key), and the usable model depends on the account.
- Automated tests use a mock provider, never a hosted model.
- Docker Desktop is not assumed, because it needs a paid license at larger companies. Docker Engine or
  Podman are the free options for the sandbox.

## D3 - Scope: Understand, Suggest, Build; graph first (2026-11-17)

**Decision:** the platform covers three capabilities: **Understand** (a repository graph the tool remembers),
**Suggest** (AI ideas grounded in graph facts) and **Build** (requirements to skill packages). The graph is
built first, as a fresh Python implementation in this repository. It follows the design of the owner's
Repository Intelligence Assistant (RIA): evidence-only answers, confidence labels, an incremental cache. It
adds function-level call edges from real parsers, which RIA does not have. RIA stays a separate local tool
with no AI, and is not a runtime dependency.

**Consequences**

- The graph is built without AI, so it is deterministic, free, and fully testable offline.
- Every answer carries its confidence. Name-only guesses are labelled and never count toward risk scores or
  test coverage; calls that cannot be pinned down are counted, not invented.
- Suggestions must cite real graph nodes as evidence. A suggestion without evidence is dropped.
- The cache lives in a per-user data folder, never inside the analysed repository or this synced folder.
- Only Python and TypeScript / JavaScript are parsed at first. Agent Builder, hosting and more languages are
  deferred.
