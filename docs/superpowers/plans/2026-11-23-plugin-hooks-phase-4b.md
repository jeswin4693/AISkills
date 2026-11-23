# Component Factory, Phase 4b: hooks in plugins, from a catalogue only (short plan)

> Executed inline with TDD, one commit per task, no model calls. Spec: [docs/component-factory.md](../../component-factory.md) ("Decisions (approved)": hooks come from a catalogue only, in exec form, always flagged as riskier). Follows [4a](2026-11-23-plugin-mcp-phase-4a.md).

**Goal:** a plugin can carry **hooks**, chosen from a small **catalogue** of vetted hooks that ship with SkillForge. Nobody types a hook command, and no model writes one. Each catalogue entry is fixed code (a short Python script, standard library only) plus a fixed event, matcher and timeout; the person may only fill **typed, validated options** (for example extra file patterns). The composer writes `hooks/hooks.json` and `hooks/<id>.py`, says plainly that a hook runs on this machine on every matching event, and the plugin's check recognises a hook **only when its script is byte-for-byte a catalogue script**. The risk diff calls every new or changed hook riskier.

**Format facts (checked 2026-11-23 with `claude plugin validate --strict`, CLI 2.1.325; the rest from the docs, see the Facts section of the result below):**
- `hooks/hooks.json` must have a top-level `"hooks"` object (without it the validator fails: `HOOKS_MISSING_WRAPPER`): `{"hooks": {"<Event>": [{"matcher": "...", "hooks": [{"type": "command", "command": "python", "args": ["${CLAUDE_PLUGIN_ROOT}/hooks/<id>.py"], "timeout": 10}]}]}}`.
- Exec form: `command` is the program and `args` its arguments, no shell. `args` without `command` is an error. An unknown event name warns (so fails under `--strict`).

**Decisions (the builder's calls):**
- The catalogue is code in the repo (`skillforge/hookcatalog/`): a table of entries and one real, testable `.py` file per entry, shipped into the plugin unchanged. Starter entries are few and plainly useful: block reading or writing secret files, block a forced `git push`, and log which tools were used (the tool's name and the time only, never its input).
- A script uses only the standard library, never the network, never starts a program. A test proves each entry's capabilities against the analyser, so the catalogue cannot quietly gain a power.
- Options are data with a strict pattern per option and a length cap; they reach the script as exec-form `args`, never through a shell.
- A script that cannot understand what Claude Code sends it **does not block** and says so (exit 1, a non-blocking error), so a format change never locks a person out; the docs say this plainly. A hook is a policy aid, not a security boundary: it matches names and text.
- The plugin's `hooks.json` is **recognised** only when every hook is a catalogue entry with exactly its event, matcher, timeout, command, a valid option list, and a shipped script whose SHA-256 is one the catalogue accepts (current or listed earlier revisions). Anything else (a shell command, another script, extra keys, a hook type other than `command`) is warned about with the command shown; the plugin from outside is never refused for it, as in 4a.

**Out of scope:** hooks of any type but `command`, free-text hooks, hooks inside a skill's or agent's own front matter (still only listed), `userConfig`-driven hook options, a model choosing hooks, `SessionStart` context injection (it feeds text to the model: a prompt, not a policy), and a real `claude plugin install`.

**Global constraints:** Python from `backend/` (`C:/dev/venvs/aiskills/Scripts/python.exe -m pytest`); tests offline; no new library; skill, agent, MCP and 4a behaviour unchanged; existing tests change only where a task says so. Use the Write/Edit tools for files (long shell heredocs with quotes fail in this shell). Commits end with `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`.

## Review Focus
- No catalogue script can reach the network, start a program, or write outside what its entry declares; the declared powers are proven by test (task 1).
- An option can never become code: strict patterns, a cap on how many, passed as separate `args` (task 1).
- `hooks.json` is described only when it matches the catalogue byte for byte; every other shape is shown, not trusted (task 3).
- A hook is always called riskier, in the preview, the README and the risk diff (tasks 2, 4).

### Task 1: the catalogue and its scripts
`skillforge/hookcatalog/` (`catalogue.py`, `scripts/*.py`): `HookEntry`, `Option`, `CATALOGUE`, `get_entry`, `render_args(entry, options)` (validates), `parse_args(entry, args)`, `script_bytes(entry)`, `accepted_hashes`. Tests: each script run with real stdin cases (blocks, allows, malformed input, odd paths), capabilities per entry proven, options accepted and refused, hashes pinned.

### Task 2: compose a plugin with hooks
`library/plugin.py`: `ComponentRef("hook", id, options=...)`, `hooks/hooks.json` and `hooks/<id>.py`, capability notes and `Capabilities.hook_entries`, README lines. Tests: exact files and JSON, several hooks on one event, notes, version moves only when content does, refusal of an unknown id or bad option.

### Task 3: read hooks in a plugin
`validate/plugin.py`: a hooks row (`HOOKS_CHECK`); `hooks/hooks.json` and described scripts are not unexplained extras or plain scripts; a plugin from outside is checked entry by entry. Tests for each shape.

### Task 4: the risk diff
`library/risk.py`: a new hook is riskier (with its event and matcher), a removed one safer, changed options or script riskier, an entry that is not from the catalogue riskier with its command shown.

### Task 5: API, page, docs, real check
`GET /api/hooks`, `kind: "hook"` with `options` on the plugin routes; the composer lists hooks with their options and a plain warning; docs; the real validator on a composed plugin; full suites; push.
