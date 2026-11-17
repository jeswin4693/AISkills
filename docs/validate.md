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
| folder name matches the skill name | warning |
| no symbolic links, no paths that leave the folder | failed |
| file sizes within limits (1 MB per file, 5 MB total, `SKILL.md` 100 KB) | failed |
| no invisible or direction-changing characters (zero-width, bidi overrides, tag characters) in text files | failed, with file and line |
| no HTML comments or script tags in Markdown | warning |
| no wording that matches known attack patterns ("ignore all previous instructions", `curl ... \| sh`, sending secrets elsewhere, disabling approval, ...) | warning |
| JSON files parse; files in `schemas/` are valid JSON Schema; `tests/cases.json` is a list | failed |
| scripts parse (Python via `ast`, TypeScript/JavaScript via tree-sitter), without running them | failed; unsupported types warn |
| every script `SKILL.md` mentions exists | failed |
| scripts use only the capabilities the skill declares (`read_files`, `write_files`, `run_commands`, `network`) | failed if a script exceeds its declaration |
| no binary files; shell scripts are noted because they are not analysed | failed / warning |

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

Nothing calls the sandbox yet: `build` generates instructions only, with no scripts. Generating scripts and
testing them in the sandbox is the next step.
