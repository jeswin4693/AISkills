# Evaluate: do a skill's test cases pass, and does the skill help?

Until this step the builder checked that a skill was *consistent*. Nobody had measured whether a model that has the skill
does the job better than a model that does not. `skillforge eval` does that for skills that are only text.

```
 each test case:  a message (run_input)  +  checks that code can run (assertions)
                        |
        +---------------+----------------+
        v                                v
 model WITH the skill            model WITHOUT the skill      <- same message, no tools
        |                                |
        v                                v
   code grades the reply by the checks (no model judges anything)
        |
        v
 "The skill helped: passed 6 of 6 with it, 2 of 6 without it"
```

## Run it

```powershell
cd backend
python -m skillforge eval generated-skills\my-skill                    # a skill folder
python -m skillforge eval --library my-skill [--version 2]             # a skill in the library
python -m skillforge eval generated-skills\my-skill --runs 3           # repeat each test: models vary
python -m skillforge eval generated-skills\my-skill --no-baseline      # only with the skill: half the model calls
python -m skillforge eval generated-skills\my-skill --json
python -m skillforge build "..." --eval [--eval-runs 3]                # build, then test it, in one go
```

It needs a model key in `.env` and makes **2 model calls per test case per run** (3 tests, 1 run: 6 calls). Exit code 0
when the skill passed every test, 1 when it failed one, 2 when nothing could be run.

## What is sent to the model

For each test, one request: the skill's own `SKILL.md` as instructions and the test's message (`<request>`), and the same
message with no skill. Nothing from your repository or your machine is sent: only the skill and the messages that were
written with it. The model has no tools. The text of a message or a skill cannot close its own tag to break out of it.

## The checks (code judges, not a model)

| Check | Passes when the reply... |
|---|---|
| `contains`, `not_contains`, `starts_with` | has, lacks or begins with some text (case ignored) |
| `regex` | matches a short pattern (see the limits below) |
| `max_chars`, `max_lines` | is at most that long (blank lines are not counted) |
| `first_line_max_chars` | has a first line (a title) of at most that many characters |

A test passes only when **all** its checks pass. No check asks a model whether a reply is good, because a model used as
a judge can be talked into anything by the text it is judging. The cost: only what those seven can say is checked. Tone,
correctness of facts and "is this a good summary" are not.

A pattern written by a person or a model and run on text written by a model could hang the program (`(a+)+$`, or `(a|aa)+$`, on a
long run of `a`). Python's `re` has no time limit and holds the interpreter while it runs, so a pattern is refused up front when it is
longer than 80 characters or when a repeat contains another repeat or a choice between alternatives (read from the parsed pattern), and
**every accepted pattern runs in a child process that is killed after 1.5 seconds**, because no rule about a pattern's text can see every
slow one. Only the first 20,000 characters of a reply are searched. A refused or stopped check counts as failed and says why; a check that
could not be judged never passes.

## How the builder uses it

The design step now writes, for every test, the **exact message** a person would send (`run_input`) and 1 to 3 checks
taken from the person's acceptance criteria and rules. Checks are validated: a malformed one is a structural failure and
is repaired. A text-only skill whose tests have no message or no check gets a quality warning.

With `build --eval`, after the design: the tests are run with and without the skill. If the skill fails some of its own
tests, the model is shown the real message, the real reply and the failed check, and gets **one** repair; the new design
is kept only if it passed more tests and failed no more structural checks. The report then has rows for both runs and the
verdict. A failing test is a **warning, never a failure**: the tests are written by a model too, so a failing case may be a
bad test as easily as a bad skill. Nothing here makes a skill a draft. If the model cannot be reached during testing, the
finished skill is kept and the row says "not run".

## What it tells you

- **The skill helped**: it passed more tests than the model did without it. The tests it fixed are where it earns its tokens.
- **The model passed every test without the skill too**: on these tests the skill adds nothing for the tokens it costs
  each time it is used. A useful thing to learn before you ship it.
- **No difference** / **made it worse**: said plainly.
- **Too few cases** (fewer than 3 runnable): it says so instead of claiming a result.
- Per case, so you can see *which* tests the skill is for and which the model already does.

## Real result (2026-11-19, Gemini, the commit-message job)

`build --eval` on "a skill that writes a clear git commit message from a short description of what changed", with the person's
rules "title at most 50 characters, starting with a verb", "only use what was described" and "ask if no description is given":

| Test | With the skill | Without it |
|---|---|---|
| a bug fix described in one sentence | passed 2 of 2 | failed 2 of 2: titles of 52 and 54 characters (`fix: prevent crash when ...`) |
| "write a commit message for me" (no description) | passed 2 of 2 | passed 2 of 2: it asks anyway |
| a long description of a big refactor | passed 2 of 2 | failed 2 of 2: titles of 71 and 74 characters |

Verdict: *the skill helped, 6 of 6 against 2 of 6*, and the reason is visible: without the skill the model writes
conventional-commit titles that break the person's own 50-character rule. The "ask for a description" case passes without
the skill, so the skill adds nothing there. The first run of the same build said 0 of 3 without the skill and this run
2 of 6, so **single runs are noisy**: use `--runs 3` before believing a small gap.

## Limits (read these)

- **Text-only skills only.** A skill that asks for `read_files`, `run_commands` or `network`, or that has scripts, is reported
  "not run": a model with no tools cannot stand in for an agent that has them. That is most skills about code.
- **The tests are written by the same model that wrote the skill**, from your acceptance criteria. A skill can pass weak tests.
  Read `tests/cases.json`.
- **One model, a small sample.** It uses the model in your `.env` (a small free one by default), 3 tests, 1 run unless you
  ask for more. A model that is stronger than the one that wrote the skill, or a real agent, may behave differently.
- **It measures what the seven checks can express.** Format, length and required or forbidden words. Not facts, not tone.
- **It is not a Claude Code run.** The test that matters most is still installing the skill and using it for real.
- Skills saved before this step have no messages or checks: they are reported "not run", and a rebuild gives them tests.
- The Builder page in the browser cannot ask for `--eval` yet (the command line can). **The Testing Lab page runs a saved skill's tests in the browser** (slice AD, [testing-lab.md](testing-lab.md)): it shows what would run and what it costs before asking, keeps the result, and says when a newer version exists.
