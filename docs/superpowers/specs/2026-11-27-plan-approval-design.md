# Answer and approve the Task Plan (slice AN): design

Status: written 2026-11-27 for the owner, who said "Plan and start to work on next phase of development" and gave no further detail (the questions are opted out, as for slices AL and AM). Everything here that is not a rule of the project is **my call**, said as such. No separate builder check was run.

## Intent (my reading)

The Task Plan (step C1, [task-conductor.md](../../task-conductor.md); a page since slice AM) ends with **questions** the request left open (some blocking), **assumptions** the work would otherwise make silently, and a promise that "none is used until you approve it". Today nothing can be answered, approved or kept: the page is gone on a reload, and nothing records what the person decided.
This slice is the step the design calls "a session, like the builder": **keep the plan, take the person's answers and decisions, and record an approval of exactly what was shown and answered.** The approved plan is the file the next phases (C2 to C5) start from.

## Goals

- Every plan the page makes is **kept** (a row), listed, and can be opened again or deleted.
- Each question can be **answered in the person's own words**; each assumption **approved or not approved**.
- **Approve** is allowed only when code's checklist is met: every *blocking* question has an answer, every assumption has a decision. Otherwise it says what is missing. A non-blocking question may stay unanswered, and the record says so.
- An approval records the time, the tier and a **fingerprint** (SHA-256) of the plan with the answers and decisions. While approved, nothing can be changed; **Reopen** withdraws the approval (and the record keeps that it happened).
- The **approved plan as Markdown**: the plan's own text plus a section with the answers, decisions and the approval, copyable and downloadable.

## Non-goals

- No re-planning from the answers (a plan made again from "the request plus the answers" is the next step, not this one). The page says plainly that **the size, tier and token plan were measured before the answers and are not measured again**.
- No phase skills, hooks, traceability or runner (C2 to C5). No change to how a plan is made: `make_plan` is called as before.
- No sign-in work: the route is off in the hosted version like `POST /api/plan` (it reads a folder and uses the server's model).
- No new library.

## Anti-goals (a failure even if it "works")

- Treating an answer as **correct**. Code checks that an answer exists, not that it is right. The record says "your words, as typed".
- An approval that can drift: answers changed after approval, or an approval of a screen the person never saw (two tabs).
- A guess shown as a fact: a question the plan never asked appearing answered; an assumption counted as approved by default.
- A folder path or a file's contents in anything kept or sent back (the plan already holds none; the repository folder is **not stored**).
- The old promise "nothing is saved" left on the page.

## Constraints (project rules)

- Models propose, code decides. No model is asked anything in this slice: the checklist, the fingerprint and every state change are code.
- A person's data is reached only through the person the request names: services take `user` (default the owner); another person's plan is a 404 identical to a missing one.
- Tests are offline (`MockProvider`).
- The CORS policy allows GET, POST and DELETE only, so changes are POSTs.

## Approaches considered

| | What | Trade-off |
|---|---|---|
| **A. A kept plan with answers and approval, no re-plan (chosen)** | A `plan_sessions` row holds the plan as made (immutable), the answers, the decisions, the approval and a small event log. Four POSTs and a DELETE. | Smallest thing that makes "approved" real and gives C2 a file to start from. The answers are recorded, not measured. |
| B. Answers feed a new plan at once | Each save re-runs `make_plan` on the request plus the answers. | An answer such as "I mean `cli.py::build`" would be measured, but every save costs a model call, the questions change under the person's hands, and "what was approved" becomes a moving target. Better as an explicit step after A. |
| C. Keep nothing, put answers in the Markdown only | The page edits the Markdown text. | No approval record, nothing for C2 to check, lost on reload. |

## Decisions (my calls)

- **Table** `plan_sessions` (migration 0011): `id` (32 hex), `user_id`, `created_at`, `updated_at`, `status` (`open` or `approved`), `task`, `repo_name`, `mode`, `plan` (the plan as made, with `tier_name` and `source`, without `markdown`), `answers` (`{questions: {"0": text}, assumptions: {"0": "approve"|"reject"}}`), `rev` (counts saves), `approved_at`, `approval` (`{fingerprint, tier, rev}`), `events` (`[{at, what}]`).
- **Routes:** `POST /api/plans` (the body of `POST /api/plan`: makes the plan and keeps it, 201), `GET /api/plans` (newest first, short summaries), `GET /api/plans/{id}`, `POST /api/plans/{id}/answers`, `POST /api/plans/{id}/approve`, `POST /api/plans/{id}/reopen`, `DELETE /api/plans/{id}`. `POST /api/plan` stays as "a plan that is not kept".
- **Saving answers replaces the whole set** (idempotent); a blank answer removes it. Keys are positions in the plan's own question and assumption lists, checked to be in range; an answer is at most 2,000 characters, control characters are removed (newlines kept), and it must hold a letter or digit to count as an answer.
- **Approve takes the `rev` the person saw.** A different `rev` is a 409 ("changed in another window"), so an approval is always of what was on screen.
- **A refusal to approve lists each missing item** (the question text or the assumption), so the page can point at them.
- **At most 200 kept plans per person**; past that the person is asked to delete some (a plan holds the request and the plan, never the code).
- **The fingerprint** is SHA-256 of the canonical JSON of `{plan, answers}`; it names a record in this app. It is not a signature, and the page says so.
- **The Markdown** is `render_markdown(plan)` plus a section "6. Your answers and approval" (answers verbatim, decisions, what was left unanswered, the approval and fingerprint, and the sentence that size and tier were not measured again).
- **Page:** the Task Plan page keeps every plan it makes, shows a **Kept plans** list, and under each plan's questions and assumptions shows the boxes, a save state, the missing items, **Approve** and **Reopen**.

## Left to the builder

Layout of the boxes, the exact wording of the page's own sentences, the unit-test list, how a long list of kept plans is shown.
