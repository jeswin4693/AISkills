# Completion batch, task 3: keep an answered checklist item between rounds — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A checklist item that was verified in an earlier round is not lost when a later round's model answer fails to repeat it, as long as its quote is still in the person's words.

**Architecture:** One pure function, `keep_verified` in `build/requirements.py`, runs inside `understand_round` between the extraction and the completeness check. The previous round's partial spec is kept on the session in a new column `build_sessions.partial_spec` (migration `0009`) and handed to `Kind.understand(..., previous=...)`. The CLI's `gather_spec` carries it in memory.

**Tech Stack:** Python, SQLAlchemy + Alembic, pytest, `MockProvider`. No new library.

**Spec:** [docs/superpowers/specs/2026-11-26-completion-batch-design.md](../specs/2026-11-26-completion-batch-design.md), item 3 (task 3 of its task list).

## Global Constraints

- Run from `backend/`; interpreter `C:\dev\venvs\aiskills\Scripts\python.exe -m pytest -q -p no:cacheprovider`. Tests offline, `MockProvider` only.
- **Completeness is a checklist in code, not the model's opinion.** An item counts only with a quote that code verified is in the person's own words (`quote_is_theirs`, one unbroken piece or a run of their whole sentences). Kept items obey the same rule, checked again against the CURRENT words.
- Models never decide what is kept; nothing is kept on the model's say-so.
- A plain `ADD COLUMN`, never a table rebuild (see migrations 0006 and 0008); the downgrade is a plain `DROP COLUMN`.
- The approved requirement (`row.spec`) is unchanged: it is still set only when the checklist is complete. The partial spec is never shown as the requirement and never built from.
- Commit messages end with `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`.

## Review Focus

1. A kept item whose quote is NOT in the current words is never kept (a hand-edited or damaged record included).
2. An item the new extraction DID back is never replaced by the old one (the new round's answer wins).
3. A damaged or unreadable `partial_spec` (wrong shape, `null`) means nothing is kept and nothing crashes.
4. The kept item and the note say so: the person can see that "constraints" came from round N-1.
5. All four conversational kinds (skill, agent, mcp, mcp-node) and the command line keep items, not only the skill builder; the plugin kind (composed, not described) still refuses.

---

### Task 1: `keep_verified` and its use in `understand_round`

**Files:**
- Modify: `backend/skillforge/build/requirements.py` (new function after `verify_extraction`)
- Modify: `backend/skillforge/build/pipeline.py` (`understand_round` gains `previous`; `gather_spec` carries it)
- Create: `backend/tests/test_keep_answered.py`

**Interfaces:**
- Produces: `keep_verified(spec: RequirementSpec, previous: RequirementSpec | None, user_words: str) -> tuple[RequirementSpec, list[str]]` — returns the spec (the same object, filled in) and notes WITHOUT a round prefix, like `verify_extraction`. For each slot in `SLOTS`: if `slot in spec.quotes` leave it; else if `previous` has `slot in previous.quotes`, a non-empty value, and `quote_is_theirs(previous.quotes[slot], normalise(user_words))`, copy that slot's value and quote from `previous` and add the note `f"{slot}: kept from the previous round (your words still say it; the new reading did not repeat it)."`. `kind`, `rounds`, `user_words` stay the new spec's.
- Produces: `understand_round(..., previous: RequirementSpec | None = None)`; the kept notes join `extract_notes` (so they get the `round N:` prefix).

- [ ] **Step 1: Write the failing tests** in `tests/test_keep_answered.py`. Reuse `FIRST`, `ANSWERS`, `slot`, `round_one`, `round_two` from `test_skill_build`. Helper `spec_with(**slots_and_quotes)`. Tests (names and assertions):

```python
WORDS = FIRST + " It must never edit files. " + ANSWERS["acceptance_criteria"]

def previous_with_constraints() -> RequirementSpec:
    return RequirementSpec(constraints=["never edit files"], quotes={"constraints": "It must never edit files"})

def test_an_item_the_new_reading_dropped_is_kept_when_its_quote_is_still_in_the_words():
    new, notes = keep_verified(RequirementSpec(goal="g" * 12), previous_with_constraints(), WORDS)
    assert new.constraints == ["never edit files"] and new.quotes["constraints"] == "It must never edit files"
    assert len(notes) == 1 and notes[0].startswith("constraints: kept from the previous round")

def test_an_item_whose_quote_is_not_in_the_words_is_never_kept():
    previous = RequirementSpec(constraints=["x"], quotes={"constraints": "a rule nobody wrote"})
    new, notes = keep_verified(RequirementSpec(), previous, WORDS)
    assert new.constraints == [] and "constraints" not in new.quotes and notes == []

def test_an_item_the_new_reading_backed_is_not_replaced():
    new = RequirementSpec(constraints=["never run commands"], quotes={"constraints": "It must never edit files"})
    kept, notes = keep_verified(new, previous_with_constraints(), WORDS)
    assert kept.constraints == ["never run commands"] and notes == []

def test_with_nothing_before_nothing_changes():            # previous None -> same spec, no notes
def test_an_old_slot_with_no_value_or_no_quote_is_not_kept():   # empty values, or values but quotes missing
def test_a_run_of_whole_sentences_as_a_quote_is_kept():          # quote_is_theirs's second form
def test_goal_and_failure_behavior_keep_as_text_not_lists():     # str slots copied as str
def test_understand_round_completes_with_a_kept_item_and_asks_without():
    ext = round_two().model_copy(update=dict(constraints=slot()))
    r = understand_round(MockProvider([ext]), WORDS_ALL, 2, 3, previous=previous_with_constraints())
    assert r.state == "complete" and any(n.startswith("round 2: constraints: kept") for n in r.notes)
    r = understand_round(MockProvider([ext]), WORDS_ALL, 2, 3)
    assert r.state == "questions" and [q.slot for q in r.questions] == ["constraints"]
def test_the_command_line_conversation_keeps_an_item_across_rounds():   # gather_spec with ask(); round 1 backs constraints, round 2 drops it
```

- [ ] **Step 2: Run to see them fail** — `pytest -q -p no:cacheprovider tests/test_keep_answered.py`. Expected: FAIL (`ImportError: cannot import name 'keep_verified'`).
- [ ] **Step 3: Implement** `keep_verified` (and the `previous` argument, and `gather_spec` setting `previous = r.spec` after a "questions" round).
- [ ] **Step 4: Run** the new file, then `tests/test_skill_build.py tests/test_builder.py`. Expected: pass.
- [ ] **Step 5: Commit** `Slice AK task 3a: an answered item is kept between rounds when its quote is still the person's own words`.

---

### Task 2: The kinds, the session column and the service

**Files:**
- Create: `backend/skillforge/db/migrations/versions/0009_partial_spec.py`
- Modify: `backend/skillforge/db/models.py` (`BuildSession.partial_spec`), `backend/skillforge/kinds/base.py`, `skill.py`, `agent.py`, `mcp.py`, `mcp_node.py`, `plugin.py` (accept and pass `previous`), `backend/skillforge/builder/service.py` (`_understand`)
- Modify: `backend/tests/test_kinds.py` (the fake kind accepts `previous=None`), `backend/tests/test_keep_answered.py`
- Modify: `docs/build.md`, `docs/database.md`

**Interfaces:**
- Consumes: `understand_round(..., previous=)` and `keep_verified` from Task 1.
- Produces: `Kind.understand(self, provider, words, round_no, max_rounds, previous: RequirementSpec | None = None) -> Round`; `BuildSession.partial_spec: dict | None` (JSON, nullable, never in `Builder.view`); migration `0009` (`op.add_column("build_sessions", sa.Column("partial_spec", sa.JSON(), nullable=True))`, downgrade a plain `op.drop_column`).
- `Builder._understand`: reads `row.partial_spec`, `RequirementSpec.model_validate` it inside `try/except ValidationError` (anything wrong → `None`), passes `previous=`; after a round whose state is `"questions"` stores `row.partial_spec = r.spec.model_dump()`.

- [ ] **Step 1: Write the failing tests** (added to `tests/test_keep_answered.py`, using `test_builder.make`):

```python
def test_the_migration_adds_a_nullable_partial_spec_column(tmp_path):     # migrate("0008"): no column; migrate(): column present, nullable
def test_a_round_that_asks_questions_keeps_its_partial_spec_but_never_shows_it(make):
    env = make([R1_WITH_CONSTRAINTS, R2_WITHOUT_CONSTRAINTS, draft()])
    first = env.start(description=FIRST + " It must never edit files.")
    assert first["status"] == "awaiting_answers" and first["spec"] is None and "partial_spec" not in first
    # stored: read the row through env.db
def test_a_dropped_item_is_kept_through_the_whole_conversation(make):
    answered = env.post(sid, "answers", answers={k: ANSWERS[k] for k in ("acceptance_criteria", "failure_behavior")}).json()
    assert answered["status"] == "awaiting_approval" and answered["spec"]["constraints"] == ["never edit files"]
    assert any("constraints: kept from the previous round" in n for n in answered["notes"])
def test_a_damaged_partial_spec_means_nothing_is_kept_and_nothing_crashes(make):   # set partial_spec = {"goal": 5} and None-like junk through env.db, then answer: the round asks for constraints again
def test_a_partial_spec_whose_quote_is_not_in_the_words_is_not_trusted(make):      # set a record with a fake quote: the item is asked for again
@pytest.mark.parametrize("kind", ["skill", "agent", "mcp", "mcp-node"])
def test_every_conversational_kind_keeps_an_item(kind):
    r = get_kind(kind).understand(MockProvider([ext_without_constraints]), WORDS_ALL, 2, 3, previous=previous_with_constraints())
    assert r.spec.constraints == ["never edit files"]
def test_the_plugin_kind_still_refuses():                                  # get_kind("plugin").understand(..., previous=None) raises BuildError
```

- [ ] **Step 2: Run to see them fail** — expected: FAIL (no column, `TypeError: understand() got an unexpected keyword argument 'previous'`).
- [ ] **Step 3: Implement** the migration, the model column, the five kinds' signatures (the four conversational ones pass `previous=previous` to `understand_round`; `plugin` still raises), the fake kind's signature in `test_kinds.py`, and `_understand`.
- [ ] **Step 4: Run** `tests/test_keep_answered.py tests/test_kinds.py tests/test_builder.py tests/test_agent_build.py tests/test_mcp_build.py tests/test_mcp_node_build.py`, then the whole suite. Expected: all pass.
- [ ] **Step 5: Document and commit.** `docs/build.md` (after the paragraph on quotes): an item verified in an earlier round is kept when the new reading does not repeat it and its quote is still in your words (checked again against the current words); the round's note says so; the partial requirement is kept on the session (`partial_spec`), never shown as the requirement. `docs/database.md`: the column and migration `0009`. Commit `Slice AK task 3b: the builder keeps the partial requirement between rounds`.

---

### Deliberate breaks (after both tasks; restore each)

1. `keep_verified` skips the `quote_is_theirs` check → the not-in-the-words test fails.
2. `keep_verified` overwrites a slot the new reading backed → the "not replaced" test fails.
3. `_understand` stops storing `partial_spec` → the conversation test fails.
4. `_understand` lets a damaged record raise → the damaged-record test fails.
5. `Kind.understand` of `agent` drops `previous` → the kinds test fails for `agent`.
6. `gather_spec` never sets `previous` → the command-line test fails.
7. `Builder.view` includes `partial_spec` → the "never shows it" test fails.

---

## Outcome (2026-11-27)

Built in commits `1a59dc7` (task 1: `keep_verified`, `understand_round(previous=)`, the command-line loop) and `2598cde` (task 2: the kinds, the column and migration 0009, the service). Backend: **3,846 passed / 4 skipped / 0 failed** (the 4 skips are symbolic-link tests this account cannot run); 25 new tests in `tests/test_keep_answered.py`.

**Deliberate breaks:** 8 run, 8 caught: no quote check, overwriting an item the new reading backed, not storing the partial spec, a damaged record raising, the agent kind dropping `previous`, the command line not carrying `previous`, the session view showing `partial_spec`, and `understand_round` ignoring `previous`.

**Rulings made while building:**
1. The partial requirement lives in its own column `build_sessions.partial_spec` (migration 0009), not in `row.spec`. `row.spec` is the requirement awaiting approval and feeds the approval card, the result card and `_build`; reusing it would show a half-answered requirement as if it were the requirement. Cost if wrong: one extra nullable column. Consequence: the behaviour-scan table (batch item 2) becomes migration **0010**; the design doc now says so.
2. No separate independent review for this task: the approved design schedules one review of the whole batch (task 6) and names the kept item in its review focus (point 4). Cost if wrong: a defect in this task would be found at the end of the batch instead of now.
3. The tests for a damaged record and for a quote that is not in the words pass vacuously before the column exists (there is nothing stored to damage); the deliberate breaks 1 and 4 are what prove they can fail.

**Not covered:** the web pages were not re-run in a browser (no UI change; the session view is unchanged and `partial_spec` is not in it).
