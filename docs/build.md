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
  SKILL.md                      the instructions the agent follows (front matter written with a YAML library)
  README.md                     overview, how to install, limits
  schemas/input.schema.json     built by code from simple field lists, so always valid
  schemas/output.schema.json
  tests/cases.json              positive / negative / edge cases as data, each tied to your acceptance criteria
  skill.sdm.json                the skill definition: single source of truth for every file above
  spec.json                     your approved requirement, with your words as evidence
  report.md                     what ran, what passed, what failed, what did NOT run
```

The same `skill.sdm.json` always renders the same bytes (`render` proves it). Text written by the model is
data: it is never evaluated as a template, and the skill name is forced to a safe folder name by code.

## Checks that run (by code)

The static validators from [validate.md](validate.md) (hidden characters, attack-like wording, JSON, scripts,
capabilities, binaries) run on every build, next to these structural checks. Wording and markup findings are
**warnings**: they are shown in the report and do not make the skill a draft. The structural checks:

Name is a valid slug; description present and within 1024 characters; input and output schemas are valid JSON
Schema; field names unique and snake_case; every workflow step has an instruction and a failure response;
every acceptance criterion is covered by at least one test; tests cite only real criteria; there is a
positive and a negative test; `SKILL.md` front matter parses back to the same name and description.

If a check fails, the model gets one repair attempt with the exact failures. If it still fails, the folder is
written as a **DRAFT**, the report says so, and the command exits with code 1.

## Checks that do NOT run (and are listed as such in every report)

Scripts running in a sandbox (this tool generates no scripts yet, and the report states whether a Linux
sandbox is available on the machine that built the skill); test
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

## Limits

- Skills only, and instructions only: no scripts. Generated code would be untrusted and the sandbox does not exist.
- The quality of the questions and the design depends on the model; a small free model gives plain results.
- The checks are structural. They cannot tell you that the instructions are good, only that they are consistent.
