# Scripts: skills that include code, tested in the sandbox

`skillforge build "<what you want>" --scripts` lets a skill ship small helper scripts, and proves they run.
Without `--scripts` nothing changes: you get an instructions-only skill, as before.

```
 approved requirement --> write scripts + test cases (AI) --> CHECKS (code) --> run every case in the SANDBOX
                                      ^                                              |
                                      +---- one repair attempt, shown the real output ---+
                       --> design the workflow around the scripts that really exist (AI) --> files + report
```

```powershell
cd backend
python -m skillforge build "A skill that counts TODO and FIXME comments in a folder." --scripts
python -m skillforge render generated-skills\<name>\skill.sdm.json --out C:\somewhere   # no AI; runs the cases again
```

## What the model decides, and what code decides

| The model writes | Code decides |
|---|---|
| a script's source, purpose and usage text | the file name and path (`scripts/<name>.<ext>`), the extension from the language |
| a language from a fixed list: python, javascript, typescript, bash, ruby, php, java | the run command, taken from the same table the sandbox uses |
| test cases: arguments, input text, small sample files, what the output must contain | where sample files go (`tests/fixtures/<case>/`), and that none can leave that folder |
| nothing else | the permissions: `run_commands` is added, because the agent has to run the scripts |

Script names are forced to a safe form, the language is a closed list, and model text is data: it is written
as is and never evaluated as a template. Compiled languages (Go, Rust, C, C++, C#, Kotlin) are not offered,
because the strict sandbox is read-only and cannot build; see [languages.md](languages.md).

## The rules a script must follow

A script reads the files named in its arguments (or standard input), prints its result, writes problems to
standard error and exits non-zero when it cannot do its job. It uses only the language's standard library
(nothing is installed in the sandbox). It never writes files, never uses the network, never starts programs.
The model is told this, and code checks it for Python, JavaScript and TypeScript (see below).

## Checks that run (by code), in this order

1. **Structure** (nothing is run): names valid and unique, at most 4 scripts, sensible sizes; every script has
   a case; every case names a real script; fixture paths are plain relative paths; an exit-0 case must check
   some output (a case that only means "did not crash" proves almost nothing); no empty expected fragment
   (it would match anything); every script has a success case that checks what it prints. A script with no
   failure case is a warning.
2. **No network, programs or file writes** in the script's code, by syntax analysis of Python and
   JavaScript/TypeScript. Other languages are not analysed, and the existing validator says so in a warning.
3. **The cases run in the sandbox**, one container per case: no network, read-only disk, no capabilities,
   limits on time, memory and processes. A case passes only if the script really ran, ended with the expected
   exit code and printed every expected fragment.
4. **The workflow** may name only scripts that exist, and every script should be named by a step (a script no
   step uses is a warning).

If a case fails, the model gets **one** repair attempt with its previous scripts and the exact failures,
including what the script really printed. That output is shown to the model as data, not instructions. If it
still fails, the skill is a **DRAFT** and the report names the failing case.

## When nothing could run

A case is never counted as passed unless it ran. The skill is written, but it is a **DRAFT** and the CLI exits 1
when:

- there is no Linux sandbox on the machine (the scripts are kept, clearly marked untested; no repair attempt is
  wasted on something that could not run), or
- an image is not on the machine yet. Images are never fetched while running. The report gives the exact
  command, for example `wsl.exe --exec docker pull python:3.13-slim`. Other scripts whose image exists still run.

## What a pass does and does not mean

- It means: the script ran in a locked box and printed the expected text on **sample files the model wrote**.
- It does not mean the script is right on your real files. The expected text is also chosen by the model, so a
  passing case can still be a weak test. Read `tests/script_cases.json`.
- It does not mean the script behaves the same on your machine. **When an agent uses the skill, the scripts run
  on your own machine, outside the sandbox**, perhaps on another operating system (a Linux-tested script that
  prints `/` in paths prints `\` on Windows).
- Every report lists "scripts tested on real project data" as a check that did not run.

## What gets written

```
generated-skills/<name>/
  scripts/<script>.<ext>                 the code
  tests/script_cases.json                each case: the exact command, the sample files, what must happen
  tests/fixtures/<case>/...              the sample files
  SKILL.md                               gains a "Scripts" section with the code-built run command
  skill.sdm.json                         holds the scripts and cases; `render` rebuilds every file and re-runs the cases
```

## Verified live (2026-11-18)

- Real containers (Docker in WSL): input text reaches a script; success and failure cases pass and fail for
  the right reasons (a wrong expectation is reported with the script's real output); a script that tries the
  network or a write is stopped by the box itself; a Java file whose name differs from its class runs; a
  TypeScript script runs with arguments and sample files.
- Real model (`gemini-3.5-flash-lite`): from one sentence and five answers it wrote a Python script and two
  cases, all 29 checks that ran passed, both cases passed in the sandbox. Reading the result: the script counts
  the text `TODO` anywhere, not only in comments, and the success case checks only that the file name and the
  words TODO and FIXME appear, not the counts. That is exactly what the report warns about.

## Limits

- Interpreter languages only (see above). One run per case, 60 seconds and 256 MB each.
- Standard library only: a script that needs a package fails its case, and the repair attempt has to remove
  the dependency.
- No test of the skill with a real agent yet (an agent harness is later work).
- Script capabilities are analysed only for Python, JavaScript and TypeScript.
