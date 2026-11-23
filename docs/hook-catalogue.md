# The hook catalogue

The hooks a plugin made by SkillForge can carry (Phase 4b of the [Component Factory](component-factory.md), used by the [plugin composer](plugin-builder.md)). It lives in
`backend/skillforge/hookcatalog/`: a table (`catalogue.py`) and one script per entry (`scripts/`).

## Why a catalogue and not free text

A hook runs a program on the person's machine, with their permissions, outside any sandbox, every time its event happens. A model-written hook would be the most dangerous thing the app could make, and a typed
one is no better. So the rule is the one the project applies to generated code, made stricter: **the only hooks are the ones listed here**, each a short script that was written and tested by hand, whose powers
are proven by a test, and whose bytes are pinned by a hash that is a constant in the entry.

## The entries

| Id | Runs | Can block | Its script can | Options |
|---|---|---|---|---|
| `block-secret-files` | before Read, Write, Edit, NotebookEdit | yes (exit 2) | nothing beyond reading its input | `also`: up to 10 more file names or patterns (`*` and `?`) |
| `block-force-push` | before Bash, PowerShell | yes (exit 2) | nothing beyond reading its input | none |
| `log-tool-calls` | after every tool | no | write `tool-calls.log` in the plugin's data folder (`CLAUDE_PLUGIN_DATA`), rotated at 1 MB | none |

An entry fixes the event, the matcher, the timeout (10 s), the script **and its SHA-256**, what the script may do (`powers`), whether it fails closed (`onFailure: block`, for every hook that can block) and the options. `revision` is 2 for the two guards because
revision 1 failed open (and missed an abbreviated `--forc`) and is deliberately **not** accepted as the catalogue's script any more. An option has a strict pattern (letters, digits and `. _ - * ?`, not starting with a dash, at least one
letter or digit), a maximum number of values and a maximum length. Options reach the script as separate `args` after a flag, never joined into a string and never through a shell.

**Every hook is started as `python -I <script> ...`.** Isolated mode puts neither the script's folder nor any `PYTHON*` variable on Python's search path. Without it a `json.py` (or `json.pyw`, `re.py`, `sitecustomize.py`) planted beside a script is
imported instead of the standard module, and a guard that imports a blinded `json` waves everything through (found by an independent review, shown against the first version, and checked in real Claude Code: with a hostile `json.py` in the hooks
folder both guards still blocked). The plugin's check also warns about any other file in `hooks/`.

## The hash is a constant, not a file

`HookEntry.sha256` holds the hash of the script (line endings ignored, because a Windows checkout may turn LF into CRLF). `script_bytes()` refuses to ship a script whose hash differs, and `accepts()` compares with the constant (and the entry's `earlier` hashes), never with
"whatever is on disk": otherwise a script edited after installation would redefine what "the catalogue's script" means, and the first version's pin lived only in a test.

## What a script does with what Claude Code sends it

It reads one JSON event on stdin (`tool_name`, `tool_input`) and exits `2` with the reason on stderr to block (for `PreToolUse`), or `0` to allow.

**A guard fails closed.** If a blocking script cannot understand the event, or the command is too long to read, it **blocks** (exit 2, "blocked this to be safe"), so a changed format is noticed at once instead of silently turning the guard off. If it cannot even be
started (for example `python` is not on the PATH) Claude Code would, by default, treat that as a non-blocking error and let the action through while telling nobody: **checked in real Claude Code 2.1.325 on 2026-11-23, a `Read` of `.env` went through
with no Python on the PATH.** So every blocking entry is written with `"onFailure": "block"` (a documented hook field, Claude Code 2.1.295 or newer; the same real run showed the read then blocked, with the reason "failed; blocking because onFailure is
block", for a missing Python and also for a script that exits 1). A hook that only looks (`log-tool-calls`) does not have it: a missing log must not stop anyone's work. The cost of failing closed is that without Python, or after a format change, the guarded
tools are blocked until it is fixed (the message says why); older Claude Code does not know `onFailure`, so there a guard that cannot start still lets the action through.

**A hook matches names and text: it is a policy aid, not a security boundary.** What each one does not see:

- `block-secret-files` judges the **file's name** the way Windows and macOS would open it (both slash styles, `.` and `..` folded away, `C:.env` read as `.env`, trailing dots and spaces and `:stream` dropped, capitals ignored, a short `ENV~1` refused). It does not see `Grep`, `Glob`
  or shell commands, so `cat .env` or a search that prints it is not stopped, and it knows a list of names (`.env*`, keys, certificates, `.npmrc`, `.pypirc`, `*.tfstate`, `*.tfvars`, credentials and secrets files), not what is inside a file.
- `block-force-push` reads the command with a small lexer: quotes, `; & | ( )` and new lines, `$(...)` and backticks anywhere, line continuations, `$'...'`, Windows paths, and the script given to `bash -c`, `powershell -Command`, `cmd /c` or `eval` (three levels deep). It blocks `--force`, `-f` (also in `-fu`),
  `--force-with-lease`, `--force-if-includes`, `--mirror` (or an unambiguous start of one, which git accepts) and a `+branch`. An alias, a script, a variable or an encoded command that pushes is not seen, and **the Monitor tool and background shells are not covered**. It blocks a few harmless
  commands too (`git push -o -f`).

## Adding a hook (the rules)

1. Write the script in `scripts/`: standard library only, no network, no started program, no code built from text, plain ASCII, a docstring that says what it does and does not. A guard must **block (exit 2) and say so** when it cannot read its input; a hook that only looks exits 1.
2. Add the entry to `CATALOGUE` with its event, matcher, timeout, `powers`, options and the script's `sha256` (the hash of the file with LF line endings). Options need a pattern that cannot become a flag or match everything.
3. Add tests in `tests/test_hook_catalogue.py`: run the script with real input (blocks, allows, malformed input, the evasions you can think of), prove `powers` with the analyser, check it leaves only the files it declares.
4. When an existing script changes on purpose: update the constant, raise `revision`, and put the old SHA-256 in the entry's `earlier` **only if that script is still safe to describe** (the two guards' first revision is not: it failed open).

## Facts and how far to trust them (read 2026-11-23)

From the official docs (read by research agents): a plugin's hooks are in `hooks/hooks.json` under a top-level `"hooks"` key (an optional `description` beside it; a `modules` key there makes a plugin a "mod" that runs JavaScript inside Claude Code, which is why any other top-level key is not described);
exec form is `command` (the program) plus `args` (no shell); exit 2 blocks a `PreToolUse` hook and its stderr is the reason, exit 1 is a non-blocking error (unless `onFailure` is `block`); the matcher `A|B` is a list of exact tool names; plugin hooks get `CLAUDE_PLUGIN_ROOT` and
`CLAUDE_PLUGIN_DATA` in their environment; hooks start when the plugin is enabled and the docs describe no per-hook approval. **Checked with Claude Code 2.1.325's `claude plugin validate`:** the exec form, the top-level `"hooks"` wrapper (without it the validator fails), an
unknown event name (a warning, so a failure under `--strict`), `args` without `command` (an error) and the `onFailure` key (accepted).

**Run by real Claude Code (2026-11-23, Windows, 2.1.325, `claude -p ... --plugin-dir <the plugin>`, one session each, no settings changed, a scratch folder with a dummy `.env`):**
- A `Read` of `.env` was blocked by `block-secret-files` and `git push --force origin main` by `block-force-push` (and `bash -c 'git push --force origin main'` by the hardened one), each with its script's own reason shown to the model (debug log: `Hook PreToolUse:Read error: status code 2`);
  a `Read` of `notes.txt` was allowed; after it `log-tool-calls` ran (PostToolUse does not run for a blocked call) and wrote `{"time": ..., "tool": "Read"}` to the plugin's data folder (removed afterwards).
- `${CLAUDE_PLUGIN_ROOT}` is replaced inside exec-form `args`; `python` resolves on this machine; **`tool_input.file_path` is the field a file tool's hook receives** (the hooks reference never lists it; the script blocks, exit 2, when it finds no path, in case a future version renames it);
  `NotebookEdit` hands its path as `notebook_path` (blocked with a matcher of only `NotebookEdit`); the `PowerShell` tool name is `PowerShell` (the force-push guard blocked it); in a non-interactive session a plugin's hooks run with no approval prompt.
- **With no Python on the PATH** the first version let a read of `.env` through (the debug log said `Hook command failed to spawn ... Executable not found in $PATH: "python"`, the session said nothing); with `onFailure: "block"` the same read was blocked and the reason shown, and so was a script that exits 1.
- **A planted `json.py`** beside the scripts did not change either guard once they were started with `-I`.

**Still not tried:** an interactive session, whether the `Monitor` tool or `Grep`/`Glob` inputs reach a hook, macOS and Linux, and any machine where Python is called `python3` (the docs do not say; on Windows exec form needs a real executable, which `python.exe` is).
`MultiEdit` is not a documented tool name, so it is not in the matcher.
