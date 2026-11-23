# The hook catalogue

The hooks a plugin made by SkillForge can carry (Phase 4b of the [Component Factory](component-factory.md), used by the [plugin composer](plugin-builder.md)). It lives in
`backend/skillforge/hookcatalog/`: a table (`catalogue.py`) and one script per entry (`scripts/`).

## Why a catalogue and not free text

A hook runs a program on the person's machine, with their permissions, outside any sandbox, every time its event happens. A model-written hook would be the most dangerous thing the app could make, and a typed
one is no better. So the rule is the one the project applies to generated code, made stricter: **the only hooks are the ones listed here**, each a short script that was written and tested by hand, whose powers
are proven by a test, and whose bytes are pinned by hash.

## The entries

| Id | Runs | Can block | Its script can | Options |
|---|---|---|---|---|
| `block-secret-files` | before Read, Write, Edit, NotebookEdit | yes (exit 2) | nothing beyond reading its input | `also`: up to 10 more file names or patterns (`*` and `?`) |
| `block-force-push` | before Bash, PowerShell | yes (exit 2) | nothing beyond reading its input | none |
| `log-tool-calls` | after every tool | no | write `tool-calls.log` in the plugin's data folder (`CLAUDE_PLUGIN_DATA`), rotated at 1 MB | none |

An entry fixes the event, the matcher, the timeout (10 s), the script, what the script may do (`powers`), whether it fails closed (`onFailure: block`, for every hook that can block) and the options. `revision` is 2 for the two guards because
revision 1 failed open and is deliberately **not** accepted as the catalogue's script any more. An option has a strict pattern (letters, digits and `. _ - * ?`, not starting with a dash, at least one
letter or digit), a maximum number of values and a maximum length. Options reach the script as separate `args` after a flag, never joined into a string and never through a shell.

## What a script does with what Claude Code sends it

It reads one JSON event on stdin (`tool_name`, `tool_input`) and exits `2` with the reason on stderr to block (for `PreToolUse`), or `0` to allow.

**A guard fails closed.** If a blocking script cannot understand the event it **blocks** (exit 2, "blocked this to be safe"), so a changed format is noticed at once instead of silently turning the guard off. If it cannot even be
started (for example `python` is not on the PATH) Claude Code would, by default, treat that as a non-blocking error and let the action through while telling nobody: **checked in real Claude Code 2.1.325 on 2026-11-23, a `Read` of `.env` went through
with no Python on the PATH.** So every blocking entry is written with `"onFailure": "block"` (a documented hook field, Claude Code 2.1.295 or newer; the same real run showed the read then blocked, with the reason "failed; blocking because onFailure is
block", for a missing Python and also for a script that exits 1). A hook that only looks (`log-tool-calls`) does not have it: a missing log must not stop anyone's work. The cost of failing closed is that without Python, or after a format change, the guarded
tools are blocked until it is fixed (the message says why); older Claude Code does not know `onFailure`, so there a guard that cannot start still lets the action through. A hook matches names and text: it is a policy aid, not a security
boundary (the entries say what they do not see).

## Adding a hook (the rules)

1. Write the script in `scripts/`: standard library only, no network, no started program, no code built from text, plain ASCII, a docstring that says what it does and does not. It must exit 1 and say so when it cannot read its input.
2. Add the entry to `CATALOGUE` with its event, matcher, timeout, `powers` and options. Options need a pattern that cannot become a flag or match everything.
3. Add tests in `tests/test_hook_catalogue.py`: run the script with real input (blocks, allows, malformed input), prove `powers` with the analyser, add the script's hash to `tests/hook_catalogue_hashes.json`.
4. When an existing script changes on purpose: put its old SHA-256 in the entry's `earlier` and raise `revision`, so a plugin composed before still counts as described, and update the pinned hash.

## Facts and how far to trust them (read 2026-11-23)

From the official docs (read by a research agent): a plugin's hooks are in `hooks/hooks.json` under a top-level `"hooks"` key; exec form is `command` (the program) plus `args` (no shell);
exit 2 blocks a `PreToolUse` hook and its stderr is the reason, exit 1 is a non-blocking error; the matcher `A|B` is a list of exact tool names; plugin hooks get `CLAUDE_PLUGIN_ROOT` and `CLAUDE_PLUGIN_DATA` in their environment;
hooks start when the plugin is enabled and the docs describe no per-hook approval. **Checked with Claude Code 2.1.325's `claude plugin validate`:** the exec form, the top-level `"hooks"` wrapper (without it the validator fails), an
unknown event name (a warning, so a failure under `--strict`) and `args` without `command` (an error).

**Run by real Claude Code (2026-11-23, Windows, 2.1.325, `claude -p ... --plugin-dir <the plugin>`, one session, no settings changed, a scratch folder with a dummy `.env`):** a `Read` of `.env` was blocked by `block-secret-files` and
`git push --force origin main` by `block-force-push`, each with its script's own reason shown to the model (debug log: `Hook PreToolUse:Read error: status code 2`); a `Read` of `notes.txt` was allowed; after it `log-tool-calls` ran
(PostToolUse does not run for a blocked call) and wrote `{"time": ..., "tool": "Read"}` to `~/.claude/plugins/data/hook-plugin-inline/tool-calls.log` (the folder was removed afterwards). This settles what the docs left open:
`${CLAUDE_PLUGIN_ROOT}` is replaced inside exec-form `args`, `python` resolves on this machine, **`tool_input.file_path` is the field a file tool's hook receives** (the hooks reference never lists it: the script still fails loudly,
exit 1, when it finds no path, in case a future version renames it), and in a non-interactive session a plugin's hooks run with no approval prompt. **Still not tried:** an interactive session, `NotebookEdit`'s `notebook_path`,
the `PowerShell` tool name, and any machine where `python` is not on the PATH or is called `python3` (the docs do not say; on Windows exec form needs a real executable, which `python.exe` is).
`MultiEdit` is not a documented tool name, so it is not in the matcher.
