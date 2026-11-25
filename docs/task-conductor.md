# Task Conductor: any task in, a planned, rule-checked, human-guided SDLC flow out

**Status: step C1 (the read-only Task Plan) is built, see "Step C1: what is built" at the end. Everything after it is still
design.** Written 2026-11-19 from your request:

1. Read the prompt and plan what it **contains and what it does not**.
2. Plan the **token use**: which existing files to read, which new files to create.
3. Run the **whole SDLC flow, scaled from a simple task to a complex one**, then build and answer.
4. **Stop anywhere and ask the human** when in doubt.
5. **Never violate the rules.**

## The decision that shapes everything: where does it run?

| | A. Generated skills and hooks, run by Claude Code | B. A native conductor inside SkillForge |
|---|---|---|
| What we ship | A suite of skills, small scripts, and optional hooks | Our own agent loop, with our own tools |
| Who does the work | Claude Code | SkillForge, using a model through our provider layer |
| Can we **enforce** a rule? | Only through what Claude Code enforces itself: **hooks** and permissions. A skill's text is guidance | Yes: every action passes our code first |
| Effort | Medium | Large (it is the planned "Agent Builder") |

**Recommendation: build one shared planning core, ship it as A first, and grow it into B later.** The planning core
is read-only and safe, which makes it the right first thing to build.

## Rules that do not change

From [CLAUDE.md](../CLAUDE.md): models see only facts that code computed, completeness is a checklist in code, a requirement
counts only with a quote verified in the person's own words, generated code runs only in the sandbox, and a check is
"passed" only if it ran. The conductor follows them: **models propose, code decides.** That means no step may depend on a
model's opinion about its own certainty.

## Your five points, and how each is met

| You asked | Mechanism | Enforced by | What exists today | New |
|---|---|---|---|---|
| 1. What the prompt contains and what it does not | A **scope ledger**: *stated* (with the person's quote), *not stated* (becomes a question), *assumed* (needs approval, never treated as fact), *out of scope* (explicit) | Code verifies every quote | The six-item checklist and quote verification, for skills | The same idea for any task type (feature, bug, refactor, migration, docs) |
| 2. Token plan | A **context plan**: files to read in the cheapest-first order, **function-level slices** from the graph, files to create with an expected size, a budget per phase | Code computes it. In a native run, code also stops at the budget | The graph knows each function's `line` and `end_line`, so it can cut out one function instead of a whole file | Token estimates (about 4 characters a token, labelled as estimates); **recording real usage** from provider answers, which we do not do today (we only count model calls) |
| 3. Full SDLC, simple to complex | **Process tiers** (below), chosen from measured facts | Code picks the tier | The graph's impact analysis (how many files a change reaches), hotspots and test ties | Tier rules, phase templates, artifact contracts |
| 4. Stop and ask | **Structural stop triggers** (below), plus doubts the model raises with cited evidence | Code | The Builder's states `awaiting_answers` and `awaiting_approval`, stored in the database | A general "checkpoint" record: doubt, approval, rule hit, budget |
| 5. Never violate rules | A **rule ledger**: each rule is *mechanical* (code can check it) or *judgment* (a person must review). Mechanical rules block; judgment rules are listed as "not enforced, review me" | Code for mechanical rules. In A, hooks. In B, the tool layer | The static validators and the sandbox | Rule sources (CLAUDE.md, the prompt's own limits, a pluggable rules server), a rule compiler, hooks |

## Process tiers: the flow scales with the task

The tier is the **highest** of these signals: the graph's blast radius (files reached), touched paths on a "sensitive" list
(auth, money, migrations, public interfaces), a risk the person declares, and unanswered blocking gaps. A person can raise
a tier; lowering one needs an explicit confirmation.

| Tier | Example | Phases |
|---|---|---|
| **0 Trivial** | Fix a typo, change one config value | Intake, Change, Verify, Report |
| **1 Small fix** | One function misbehaves | Intake, Reproduce (a failing test first), Fix, Test, Quick review, Report |
| **2 Feature or refactor** | Several files, one area | Requirements, Design (short), Task list, Implement (tests first), Test, Review, Docs and report |
| **3 Complex or risky** | Many modules, data, security, public interface | Tier 2 plus risk assessment, a decision record, rollback plan, security review, and a human approval at **every** gate |

Each phase is a skill the existing Builder can generate, with a file it reads and a file it writes, so a phase starts
from the previous phase's **file**, not from the whole conversation (this is also the biggest token saving).

## When it stops and asks

Triggers computed by code, not by the model feeling unsure:

1. A gap marked blocking is unanswered.
2. An action would touch a file outside the plan's allowed paths.
3. The change is much larger than planned.
4. A new dependency, a secret, or network access appears.
5. Tests fail twice.
6. The budget is 80% used or exceeded.
7. A mechanical rule would be violated (this is a hard block, not a question).
8. Any tier 3 gate; any destructive action (delete, force, overwrite).

The model may also raise a doubt, but it must cite evidence (a quote from the prompt or a `file:line`). To avoid
over-asking, doubts are batched at the start of a phase, and the work stops mid-phase only for new information.

## Rules: honest about what can be guaranteed

Sources: the repository's `CLAUDE.md` / `AGENTS.md`, the limits in the prompt itself, safety rules of the tool, and
pluggable providers (your environment already has a rules server that returns cited rules for a task).

- **Mechanical rules** (a path allow-list, forbidden commands, "no new dependency without approval", "every requirement
  has a test", a naming pattern) are checked by code before and after every action and on every diff.
- **Judgment rules** ("keep functions small", "follow the existing style") cannot be checked by code. The plan lists them
  as **advisory** and a person reviews them at the gate.
- The plan says, up front: "7 rules apply: 4 enforced by code, 3 need your review."

**What "never violate" can honestly mean:** a guarantee for mechanical rules, inside the tools we control. Not for
judgment rules, and not for anything a model does outside those tools.

In mode A, the program-run locks are **hooks**: for example, refuse any file edit unless an approved plan exists and
the path is in its allowed list; run a linter after each edit; refuse to finish while a required artifact is missing.
Hooks can intercept tool calls, but the exact blocking behaviour must be checked against the Claude Code documentation
before anything is built on it.

## Pieces to build

A new `skillforge/conductor/` package, shaped like the existing Builder:

- `models`: the task plan, scope ledger, token plan, tier, phase, gate, checkpoint, rule ledger.
- `intake`: the checklist per task type, with verified quotes.
- `sizing`: tier from graph facts.
- `tokens`: estimates, graph slices, budget; later, real usage.
- `rules`: rule sources, the mechanical/judgment split, checks.
- `gates`: artifact checks (also as scripts that run in the sandbox).
- `session`: the state machine (working, awaiting answers, awaiting approval, blocked, over budget, done), stored in the database.
- `export`: the skill suite, scripts and hooks for Claude Code.

For a native run (B) the model layer needs one new thing. Rather than free tool-calling, use **structured actions**: the
model returns one validated action ("read this slice", "propose this patch"), code checks it against the rules and the
budget, then runs it. That fits our rule, works with every provider we support, and keeps all control in code.

## Build order

| Step | What | Check |
|---|---|---|
| **C1 Task Plan (read-only)** | Prompt (and optionally a repo) in; scope ledger, tier, rule ledger and token plan out; the UI shows it for approval. Writes nothing to the repository | Offline with a mock model; once live with a real model |
| C2 The suite | Phase skills, artifact contracts, the token-plan script and the rule ledger file, built by the existing Builder, saved as one suite | The existing checks; each phase tried alone |
| C3 Enforcement export | Hooks and permission suggestions, gate scripts proven in the sandbox. Installing them changes the person's settings, so it asks first | Hook behaviour checked against the docs and a real run |
| C4 Cross-phase traceability | Requirement to design to task to test, verified by code | Offline |
| C5 Native runner | The structured-action loop, checkpoints in the UI, budget from real usage counts | Offline plus live |

## Limits to say out loud

- **A skill is guidance.** In Claude Code only hooks and permissions are enforced.
- **Token numbers are estimates** until real usage is recorded, and each provider counts differently.
- **Running a project's tests in our sandbox is limited**: no network, so no installing dependencies, and compiled languages
  are not runnable. Real "implement and test" needs a project-specific build area, which is on the backlog.
- **Natural-language rules are hard to turn into checks.** Expect many to stay advisory.
- **Too many questions is a failure too.** The stop triggers need tuning on real tasks.
- **A big surface.** Start read-only (C1) and measure before adding anything that changes files.
- Do not test on confidential repositories with a hosted model.

## Step C1: what is built (read-only Task Plan)

```powershell
cd backend
python -m skillforge plan "Add a --json option to the 'library list' command in cli.py. Do not change any other command." --repo C:\path\to\repo
python -m skillforge plan "..." --repo C:\path\to\repo --no-ai --type bugfix   # sends nothing anywhere
```

It reads and changes **nothing** in the repository and runs nothing. It prints a plan with: what the request contains
(each item with the person's own quote, verified), what it does **not** say (questions, blocking ones first, and
assumptions that are never used until approved), the tier and **why**, the phases and when each is done, the rules that
apply (with file and line, all marked "not enforced yet"), the token plan, and a list of what was **not** checked.
Options: `--tier N` (can only raise; lowering needs `--allow-lower` and is recorded), `--budget`, `--sensitive GLOB`,
`--json`, `--save FILE`, `--file FILE`.

| Part | Decided by | Notes |
|---|---|---|
| What the request contains, gaps, assumptions, files to create | The model reads; **code verifies** every quote, every named target and every new path | A claim without a quote in the person's words is dropped, and the plan says so |
| Which files and functions the request names | **Code**, from the graph | A plain word such as `build` is never taken for code; a name matching several places (a function, or a file name such as `pipeline.py` that two folders have) is ambiguous: not measured, and asked about, with the matching places listed (up to five). A file name that matches one source file and a test file means the source file |
| The tier | **Code**, from the highest of: kind of task, files reached by proven links, a **high** risk rating, sensitive paths, risks the person named | Every signal is shown with its evidence. The tier reflects only the code the request names |
| The phases and stop triggers | Fixed tables | `skillforge/conductor/process.py` |
| Which rules apply | The model **chooses by id** among the rules parsed from `CLAUDE.md` / `AGENTS.md`; an id that does not exist is dropped | Rules in the prompt itself are added with the person's quote |
| The token plan | **Code** | Rule files, then exactly the named functions (graph line ranges), then proven neighbours, then at most 3 of the most relevant tied tests; a budget by tier; a hint when naming a function would be cheaper |

**What the model sees** (and the command says so before it sends anything): the task text, the names and places (not the
contents) of the files and functions it mentions, file and language counts, and the lines of the rule files. A test
checks that a distinctive string inside a function body never reaches the model.

**Checked:** 79 offline tests, including that a plan changes nothing in the repository and that no file content is sent.
Run live on this repository with Gemini (a feature request with a limit): it split the request into separate items, each
with the person's own quote; raised the one real gap (what JSON structure?) as blocking; and chose the one rule that
applies. It also exposed two weaknesses, now fixed and covered by tests: a path at the end of a sentence did not match, and
the first token plan was far too big.

**A worked example of the token plan** (the same task, "add a `--json` option to `library list` in `cli.py`", planned
reading in estimated tokens; this repository, one run each):

| Plan | Tokens to read |
|---|---|
| First version: the whole `cli.py` and all 11 test files tied to it | 53,260 |
| Only the 3 most relevant tied tests, with a hint that `_run_library` (890 tokens) matches the words | 24,511 |
| The function named in backticks instead of the file: its exact lines, its proven neighbours, 3 tests | 14,037 |

(The same files read whole would cost about 25,300 in the last row.) These are estimates at about 4 characters a token.
The hint is a guess from names, and the savings come from reading less, not from the plan itself costing nothing.

**Not built yet:** answering the questions and approving the plan (a session, like the builder), the web page, turning the
plan into skills (C2), enforcement by hooks (C3), the checked requirement-to-test chain (C4), and a runner (C5). The token
numbers are estimates, and real token use is not recorded anywhere yet.

## Reference: Polaris, compared and not adopted (2026-11-25)

Polaris (v2026.2.9, a spec-driven development toolkit based on GitHub Spec Kit) was compared with how this project already
works. **Decision: it is not installed in this repository.** It is the prompt-only "option A" from the top of this page: its
steps are instructions to a model, and no code checks the result. Its ideas are still worth reading before C2 to C5.

**Why not installed** (each point was checked on the author's machine, not assumed):

| Polaris step | Already covered here by |
|---|---|
| `constitution` (the project's permanent rules) | `CLAUDE.md`, "Rules for working here" |
| `specify` (interview, then a feature spec) | `docs/superpowers/specs/` |
| `tasks` (work packages) | `docs/superpowers/plans/` |
| `review`, `accept`, `merge` | one final independent review, then the "After each slice" checklist |
| `assess`, `standards` | the product itself: `graph`, `suggest`, `guide` |

- `polaris analyze .` reported this project as type "unknown" with no test framework: it looks at the repository root, and the
  code is in `backend/` and `frontend/`. It wrote nothing.
- `tasks` tells the person to run `/polaris.plan` first, but that command does not exist in the install. A flow that names a
  step that is missing is the kind of fault C4 (traceability) should catch **by code**.
- Each of the `specify` and `tasks` prompts is about 22 KB (roughly 5 to 6 thousand tokens, an estimate at 4 characters a
  token). Token cost is a stated concern here.

**What is worth borrowing, and how this design differs**

| Polaris idea | Could inform | How the Conductor differs |
|---|---|---|
| Two "missions" with their own phases. `software-dev`: research, design, implement, test, review. `research`: question, methodology, gather, analyze, synthesize, publish. (A third, `documentation`, exists; its phases were not read.) | C2 phase skills, and a "research" task type next to feature, bug, refactor, migration, docs | The tier comes from graph facts (blast radius, sensitive paths), not from a model's guess at which mission fits |
| An interview scaled to the size of the request: 1 to 2 questions for a trivial feature, 5 or more for a critical one | The stop triggers in "When it stops and asks"; it supports the limit "too many questions is a failure too" | The number of questions follows the tier and the scope ledger, and a slot counts as answered only with a verified quote |
| One isolated **worktree** (a second folder of the same git repository, on its own branch) per work package | Tier 3 tasks (C3 and C5): try each task-list item apart from the main branch | A change reaches the main branch only after the code-run gates pass |
| A written rules file that every step must follow | The rule ledger's sources (`CLAUDE.md` already counts) | Each rule is marked mechanical (code blocks it) or judgment (a person reviews it) |

## Decisions for the person who owns the project

1. Start with C1, the read-only plan? (recommended)
2. First runtime: export to Claude Code (A), or native (B)? (recommended: A first)
3. Which rule sources count: the repo's `CLAUDE.md`, and any rules server?
4. Which stack to tune the phase templates for first?
5. Batch the questions at the start of a phase, or interrupt as they come?
