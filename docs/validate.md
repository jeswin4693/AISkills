# Validate and sandbox: the safety layer

Skills are text and sometimes code written by a model, or downloaded from somewhere else. Treat all of it as
untrusted until it has been checked. Two tools do that, and both are honest about what they cannot do.

## `skillforge validate <skill-folder>`: static checks, runs nothing

Works on any skill folder, generated here or downloaded. It also runs automatically on every `build`.

```powershell
cd backend
python -m skillforge validate C:\path\to\skill-folder        # exit code 1 if any check failed
python -m skillforge validate C:\path\to\skill-folder --json
```

| Check | Result when it finds something |
|---|---|
| `SKILL.md` exists, front matter is valid YAML, name is a safe slug, description is present and within 1024 characters | failed |
| front matter uses only keys Claude Code knows (the list is data in `validate/formats.py`, with the day it was read) | warning |
| folder name matches the skill name | warning |
| no symbolic links, no repeated file names (zips), no paths that leave the folder | failed |
| file sizes within limits (1 MB per file, 5 MB total, `SKILL.md` 100 KB) | failed |
| no invisible or direction-changing characters (zero-width, bidi overrides, tag characters) in text files | failed, with file and line |
| no HTML comments or script tags in Markdown | warning |
| no wording that matches known attack patterns ("ignore all previous instructions", `curl ... \| sh`, sending secrets elsewhere, disabling approval, ...) | warning |
| JSON files parse; files in `schemas/` are valid JSON Schema; `tests/cases.json` is a list | failed |
| scripts parse (Python via `ast`, TypeScript/JavaScript via tree-sitter), without running them | failed; unsupported types warn |
| every script `SKILL.md` mentions exists | failed |
| scripts use only the capabilities the skill declares (`read_files`, `write_files`, `run_commands`, `network`) | failed if a script exceeds its declaration |
| no binary files; shell scripts are noted because they are not analysed | failed / warning |

**Kinds:** `validate_files(files, kind=...)` runs every check above for every kind of thing the app keeps. Only the first
row (the definition file) is the kind's own: a skill's is the `SKILL.md` check; another kind registers its own in
`DEFINITION_CHECKS`. An unregistered kind is refused, not guessed.

**The key list is a snapshot.** Claude Code ignores a front-matter key it does not know and says nothing, so a typo such
as `allowed_tools` would quietly do nothing; that is why an unknown key warns. The list was read on 2026-11-20 from the
Claude Code skills page through a summarising fetch, so the wording is paraphrased. A new Claude Code may know more keys:
add them to `validate/formats.py` and change the date. An older stored skill with a key that is missing from the list
shows up as "worse" in `library rescan`.

**Why some are warnings:** a pattern is not understanding. The wording check cannot tell an attack from a
security guide quoting one, so it asks a person to read the line instead of rejecting the skill.

**What passing means:** that these checks found nothing. It is not proof the skill is safe. Capability
detection is by syntax only: it cannot see calls made through other modules, dynamic code (`eval`, `exec`),
or anything that happens at run time.

## The sandbox: run untrusted scripts in a locked-down container, or not at all

`skillforge.sandbox` builds a hardened `docker run` command and runs it. **It fails closed**: every run starts
by asking Docker which operating system its engine runs, and unless the answer is Linux it raises
`SandboxUnavailable`. There is no fallback that runs a script on the host and no switch to turn the check off.

Every container gets: no network (`--network none`), a read-only root file system, all Linux capabilities
dropped, `no-new-privileges`, a process limit (no fork bombs), memory and CPU limits, no IPC, the unprivileged
user `nobody`, a `/tmp` that is writable but not executable, the skill mounted read-only, no image pulls at run
time, a time limit that kills the container, and a cap on captured output. Arguments are a list, never a shell
string, and the image name is validated so it cannot smuggle in options.

```powershell
python -m skillforge sandbox-status
```

### Status on the development machine

**Available, through Docker inside WSL** (the native Docker here only runs Windows containers). Real-container
tests prove the locks (7 of 7 pass), including a control showing that the network lock is what blocks the
connection. How it was set up, the steps for another machine, and what the sandbox does not prove are in
[sandbox-wsl.md](sandbox-wsl.md). Where no Linux engine exists, the sandbox raises `SandboxUnavailable` and no
script is run anywhere, and the build report says so.

`build --scripts` calls the sandbox: every generated script case runs in it, one container per case, and a case
counts as passed only if it really ran. Input text can be piped to a script (`-i` is added to the container
only when a case gives some). See [scripts.md](scripts.md).
