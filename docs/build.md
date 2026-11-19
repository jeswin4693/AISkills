# Build: from a requirement to a skill folder

`skillforge build "<what you want>"` turns a plain-English requirement into a reusable skill folder, and
writes a report that says what was checked and what was not.

```
 your words --> extract (AI) --> CHECKLIST (code) --> questions --> you approve --> design (AI) --> CHECKS (code) --> files + report
                     ^                                   |                                  \--> one repair attempt if checks fail
                     +------- your answers --------------+
```

## Run it

```powershell
cd backend
python -m skillforge build "A skill that finds duplicate functions in a TypeScript repository and suggests safe refactors."
# let the skill ship helper scripts and test them in the sandbox (see scripts.md):
python -m skillforge build "..." --scripts
# or start from an idea found by `suggest`:
python -m skillforge suggest C:\path\to\repo --save report.json
python -m skillforge build --from-suggestions report.json --pick 1
# no terminal? answer the questions from a file and approve up front:
python -m skillforge build "..." --answers answers.json --yes
# rebuild the files from a saved definition, with no AI:
python -m skillforge render generated-skills\<name>\skill.sdm.json
```

Skill folders go to `generated-skills/` (git-ignored) unless you pass `--out`. An existing folder is never
replaced unless you pass `--force`. Needs a provider key in `.env`, except `render`.

## How "are the requirements complete?" is decided

Not by the model. A fixed checklist decides: **goal, inputs, outputs, constraints, acceptance criteria,
failure behavior**. The model only reads your words and fills in the checklist. To stop it filling gaps with
plausible inventions, every item must carry a **quote copied from your own words**, and code verifies that the
quote really appears in what you typed. An item with no verifiable quote counts as not answered, and you are
asked about it. "None" counts as an answer for inputs and constraints, but only if you said so. A request that
is a prompt, tool or agent rather than a skill is refused with an explanation.

Up to three rounds of questions, then it stops and names what is still missing. Nothing is built until you
approve the requirement. `spec.json` keeps your own words next to each item as evidence.

## What gets written

```
generated-skills/<name>/
  SKILL.md                      the instructions the agent follows, kept short (front matter written with a YAML library)
  README.md                     for people: what it does and does not do, how to install, permissions, limits
  schemas/input.schema.json     built by code from simple field lists, so always valid
  schemas/output.schema.json
  tests/cases.json              positive / negative / edge cases as data, each tied to your acceptance criteria
  skill.sdm.json                the skill definition: single source of truth for every file above
  spec.json                     your approved requirement, with your words as evidence
  report.md                     what ran, what passed, what failed, what did NOT run
```

The same `skill.sdm.json` always renders the same bytes (`render` proves it). Text written by the model is
data: it is never evaluated as a template, and the skill name is forced to a safe folder name by code.

## What makes the skill work well and cost little (step J)

An agent reads a skill in three tiers, and each costs tokens: the **name and description** are in its context on every
task, **SKILL.md** is loaded when the description matches the task, and everything else (scripts, schemas, tests,
README) is opened only if SKILL.md sends it there. So the description has to say *when* to use the skill or it never
triggers, and SKILL.md should hold what changes the agent's behaviour and nothing it already knows.

What the builder does about it (`build/quality.py`, no model involved):

- **The description is built by code**: the model writes one sentence saying what the skill does and 2 to 5
  `triggers` (phrases a person would really say); code writes `... Use when the request involves "a", "b", or "c".`
  (never past 1,024 characters, never twice).
- **Your approved requirement reaches SKILL.md by code, word for word**: your constraints become **Rules**, your
  acceptance criteria become a **Done when** checklist the agent is told to check before answering, your failure
  behaviour becomes **If something goes wrong**. A check fails the build if any of those lines is missing.
- **A worked example** comes from the first positive test case, and its text is chosen by the model.
- **What is for people stays out of SKILL.md**: the "this skill does" list, limitations and permissions are in
  `README.md`. A step that cannot fail says `none` and no failure line is written.
- **Repeats are dropped**: a "do not" you already stated as a rule, and a failure line that only restates an earlier
  one, are not said twice (a heuristic: lines that share about 40% of their content words).

Quality checks (they **warn**; the one repair attempt is told about them, and the better of the two designs is kept):
the description says when and has at least two trigger phrases; every input and output is named in the workflow
(an input no step uses may be ignored, an output no step produces is never made); no vague wording ("as needed",
"if necessary", "properly", "etc."); every step is at most 60 words; the example does not repeat itself; and the
**token cost** (an estimate, 4 characters per token): about N tokens always loaded, M when the skill is used, K in
other files. The builder shows that line on the result page and in the command-line summary.

These are heuristics: they find the common, mechanical weaknesses. A skill can pass all of them and still be a poor
skill, and a good one can trip a warning. Nothing here checks that the instructions are *right*.

## Checks that run (by code)

The static validators from [validate.md](validate.md) (hidden characters, attack-like wording, JSON, scripts,
capabilities, binaries) run on every build, next to these structural checks. Wording and markup findings are
**warnings**: they are shown in the report and do not make the skill a draft. The structural checks:

Name is a valid slug; description present and within 1024 characters; input and output schemas are valid JSON
Schema; field names unique and snake_case; every workflow step has an instruction and a failure response;
every acceptance criterion is covered by at least one test; tests cite only real criteria; there is a
positive and a negative test; `SKILL.md` front matter parses back to the same name and description.

If a check fails (or a quality warning is raised), the model gets one repair attempt with the exact problems, and
the design with fewer failures and then fewer warnings is kept: a repair never makes the skill worse. If a check still
fails, the folder is written as a **DRAFT**, the report says so, and the command exits with code 1.

## Checks that do NOT run (and are listed as such in every report)

Scripts running in a sandbox (without `--scripts` a skill has no scripts, and the report states whether a Linux
sandbox is available on the machine that built it; with `--scripts` the per-case results appear instead, see
[scripts.md](scripts.md), and "scripts tested on real project data" is listed as not run); test
cases run against a real agent (no harness yet; the cases are data); conflict analysis of the instructions;
a security review of the text. A report that says "every check that ran passed" also says that this is not a
guarantee the skill works.

## Real result (2026-11-17, `gemini-3.5-flash-lite`, free key)

From the one sentence "A skill that finds duplicate functions in a TypeScript repository and suggests safe
refactors" the model filled in only the goal and, as instructed, left everything else empty. The checklist
therefore asked five questions across two rounds. After the five answers it designed the skill
`ts-duplicate-detector` in about 24 seconds: 9 checks passed, 0 failed, 4 listed as not run. Reading the result:
the instructions matched the requirement, the "never edit any file" rule appears under "does not", every
workflow step has a failure response, the only permission asked for is `read_files`, and there are positive,
negative and edge tests tied to the acceptance criterion. Cosmetic flaw: the title is the slug in title case
("Ts Duplicate Detector").

## Real result for step J (2026-11-19, Gemini, the same one-sentence job as the installed `git-commit-writer`)

One live build each, so indicative only, and the requirement text was a rewrite of mine, not the original.

| | `git-commit-writer` (built before step J) | built after step J |
|---|---|---|
| SKILL.md | 2,142 characters, about 536 tokens | about 392 to 404 tokens (two runs) |
| Name and description (always loaded) | about 43 tokens, "Use this when you need to generate a commit message based on provided text" | about 54 to 55 tokens, with three trigger phrases |
| Names the inputs and outputs in the steps | by chance | every time (checked) |
| The person's rules and criteria in SKILL.md | by chance | every time (checked) |
| Worked example | none | yes |

The same design rendered with the old and the new template (a test design, so identical content): SKILL.md went from
about 316 to 298 tokens while gaining rules, a done-when list and an example. **The always-loaded text grows by
about 11 to 20 tokens**, the price of real trigger phrases; the saving is in SKILL.md.

The first live run still showed three weaknesses that the checks then did not catch, and each was fixed and then tested
with the model's own strings: a rule stated twice ("Do not: It does not look at..."), a garbled example (a repeated
phrase, and longer than the person's own 50-character limit), and three lines all saying "ask for a description".
The second live run had none of those. It still has one redundant "On failure" on a step that restates the step.

## Limits

- Skills only. Instructions only unless you pass `--scripts`; scripts are untrusted code, run only in the
  sandbox, and tested only on small samples ([scripts.md](scripts.md)).
- The quality of the questions and the design depends on the model; a small free model gives plain results.
- The checks are structural plus the heuristics above. They cannot tell you that the instructions are good, only that they are consistent and not
  obviously weak. **Test cases are still never run against an agent**, so nobody has measured whether an agent that
  loads the skill does the job better. The example is model-written and is not checked against your criteria (for
  instance a number limit); read it.
- The token numbers are estimates (4 characters per token); real tokenizers differ by model and language. Skills saved
  before step J have no `triggers`, still load and render, and get a warning.
