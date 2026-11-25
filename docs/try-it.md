# Try it yourself: steps and sample inputs

A hands-on guide to testing what SkillForge AI does today. Every command below was run on a small throwaway repository before it was
written down, and the outputs described are what those runs printed. Commands are for **Windows PowerShell**.

## What needs what

| Scenario | Needs a model? | Needs Docker (Linux sandbox)? | Costs quota? |
|---|---|---|---|
| A. Read a repository (graph) | no | no | no |
| B. Library, risk diff, safety checks | no | no | no |
| C. Evidence and drift (a skill that cites code) | no | no | no |
| D. Build a skill in the Builder | **yes** | no | a few calls |
| E. Build an agent, an MCP server (Python, Node) | **yes** | **yes** (MCP) | a few calls each |
| F. The Repository page (ideas for a repository) | **yes** | no | about 2 calls, then a build |
| G. Plugins page, install | no | no | no |
| H. The Settings page (model and key) | no (the test button uses one tiny call) | no | only if you press Test my models |

Start with A, B and C: they are free and show the safety and drift features, which are the unusual parts.

## 0. One-time setup (two PowerShell windows)

Use a **throwaway data folder**, so nothing you try touches your real library. Set it in **both** windows (and in any window where you run
`skillforge` commands):

```powershell
$env:SKILLFORGE_DATA_DIR = "C:\temp\skillforge-try"
$py = "C:\dev\venvs\aiskills\Scripts\python.exe"
```

**Window 1, the API:**

```powershell
cd "C:\Users\jj1\OneDrive - Aptean-online\Documents\GitHub\AISkills\backend"
& $py -m skillforge serve
```

**Window 2, the web pages:**

```powershell
cd "C:\Users\jj1\OneDrive - Aptean-online\Documents\GitHub\AISkills\frontend"
npm run dev
```

Open http://127.0.0.1:3000. The **Status** box at the bottom left must show the API **online**, the sandbox **Linux, ready** (needed for
scenario E) and a **Model** name (needed for D, E and F). To check from the command line (in window 1's folder, in a third window):

```powershell
& $py -m skillforge sandbox-status        # AVAILABLE: Docker inside WSL is running Linux containers.
& $py -m skillforge models --test         # asks each configured model one tiny question
```

If the web page says "The API is not running", window 1 is not running `serve`.

### Make the sample inputs

A tiny repository (`shop-api`) and a tiny skill (`commit-message-helper`):

```powershell
New-Item -ItemType Directory -Force C:\temp\shop-api, C:\temp\samples\commit-message-helper | Out-Null
Set-Content C:\temp\shop-api\core.py "def shared():`n    return 1`n"
Set-Content C:\temp\shop-api\a.py "from core import shared`n`ndef use_a():`n    return shared()`n"
Set-Content C:\temp\shop-api\b.py "from core import shared`n`ndef use_b():`n    return shared()`n"
@'
def tidy(rows):
    out = []
    for row in rows:
        if row is None:
            continue
        value = str(row).strip().lower()
        if value and value not in out:
            out.append(value)
    return sorted(out)
'@ | Set-Content C:\temp\shop-api\util.py
@'
---
name: commit-message-helper
description: Writes a short commit message from a description of what changed.
---
# Commit message helper

Write one line of at most 50 characters in the imperative mood. Add a blank line and a short body only if needed.
'@ | Set-Content C:\temp\samples\commit-message-helper\SKILL.md
```

The skill's folder name must equal its `name` (a check enforces it).

## A. Read a repository (no model)

```powershell
& $py -m skillforge graph stats C:\temp\shop-api
& $py -m skillforge graph callers C:\temp\shop-api shared
& $py -m skillforge graph hotspots C:\temp\shop-api
& $py -m skillforge suggest C:\temp\shop-api --facts-only
& $py -m skillforge plan "rename the function shared in core.py to shared_value" --repo C:\temp\shop-api --no-ai
```

**Expect:** `Files: 4 ... Languages: python 4 (full)`; `Callers of shared (core.py:1)` listing `use_a a.py:3` and `use_b b.py:3`; the facts list
says `shared ... is called from 2 distinct places` and flags `tidy` as large; the plan says "A plan only. Nothing was run" and names `core.py`.
Try it on a bigger repository too, such as this project's own `backend` folder.

**A GitHub link works too** (Repository page, needs the network): paste `https://github.com/jeswin4693/AISkills` and press **Read the repository**. Expect the heading `jeswin4693/AISkills`, a **from GitHub** badge, "Nothing was run", what was left out, and "Git history is not downloaded". A link to another site, or to a private or missing repository, is refused with a plain message. **The command line takes the link too** (slice AA): `& $py -m skillforge graph stats https://github.com/jeswin4693/AISkills --no-history` prints the same facts as for a folder, with `Repository: jeswin4693/AISkills`, and a note about the download on stderr (where it came from, what was left out, that git history is missing); run it twice and the second says `a copy from a moment ago`. Add `--json` and stdout is still pure JSON. A link to another site, or to a repository that does not exist, is one `error:` line with exit code 2. `plan ... --repo <link>` also says that `CLAUDE.md` and `AGENTS.md` are not downloaded, and `library cite|recheck|refresh --repo <link>` always download fresh ([docs/cli-github-links.md](cli-github-links.md)).

**It proves:** the graph is computed from the code, every link is proven or labelled a guess, and nothing here used a model or ran anything.

## B. Library, risk diff and safety checks (no model)

```powershell
& $py -m skillforge library import C:\temp\samples\commit-message-helper
```

**Expect:** `Imported 'commit-message-helper' as v1`, `13 passed, 0 failed`, and the line that passing is not proof it is safe.

**Make a riskier version** (a script that uses the network) and import again:

```powershell
New-Item -ItemType Directory C:\temp\samples\commit-message-helper\scripts | Out-Null
Set-Content C:\temp\samples\commit-message-helper\scripts\net.py "import requests`n`nprint(requests.get('http://example.test').text)"
& $py -m skillforge library import C:\temp\samples\commit-message-helper
```

**Expect:** `Risk v1 -> v2: MORE RISK (3 riskier ...)`: a new script that uses the network, a web address the version before did not mention, a check that got worse. Never the word "safe".

**Take it back out** and import again:

```powershell
Remove-Item -Recurse C:\temp\samples\commit-message-helper\scripts
& $py -m skillforge library import C:\temp\samples\commit-message-helper
```

**Expect:** a new version and `less risk (0 riskier, 0 to look at, 3 safer)`.

**A hidden character is refused** (an invisible zero-width character appended to the skill's text):

```powershell
Add-Content -Encoding UTF8 C:\temp\samples\commit-message-helper\SKILL.md ([string][char]0x200B + "zero width")
& $py -m skillforge library import C:\temp\samples\commit-message-helper
```

**Expect:** `Refused: nothing was added to the library` and `FAILED: no hidden or direction-changing characters ... SKILL.md ... (U+200B)`.
Put the file back by running the `commit-message-helper` block of "Make the sample inputs" again.

Then:

```powershell
& $py -m skillforge library list
& $py -m skillforge library versions commit-message-helper
& $py -m skillforge library rescan          # today's checks on every stored version
& $py -m skillforge library diff commit-message-helper
```

**In the web page:** Library. Make a zip and drop it on the import box:
`Compress-Archive -Path C:\temp\samples\commit-message-helper -DestinationPath C:\temp\samples\commit-message-helper.zip`.
Open the skill: versions, files, the checks, **Changes since vN**, **Export .zip**, **Install...** (to a folder such as `C:\temp\skills-out`; a second
install asks before replacing), **Restore this version...** (asks first, adds a new version, deletes nothing), **Re-check this skill**.

## C. Evidence and drift: a skill that cites code (no model)

```powershell
& $py -m skillforge library cite commit-message-helper --repo C:\temp\shop-api --ref core.py::shared --ref util.py::tidy
& $py -m skillforge library recheck commit-message-helper --repo C:\temp\shop-api
```

**Expect:** `Recorded 2 place(s)`, then `Result: 2 holds`, and the line "It checks that cited facts still hold, not that the skill's advice is right".

Now change the code, **one change at a time**, running the recheck after each (the exit code is 1 for missing, moved or changed, 0 for holds or edited):

| Do this | Run the recheck, expect |
|---|---|
| `(Get-Content C:\temp\shop-api\core.py) -replace 'return 1','return 2' \| Set-Content C:\temp\shop-api\core.py` | **EDITED** `core.py::shared`: same structure, the text differs (exit 0) |
| `Set-Content C:\temp\shop-api\c.py "from core import shared`n`ndef use_c():`n    return shared()`n"` | **CHANGED** `core.py::shared`: `it now has 3 resolved callers, was 2 (new: c.py::use_c)` (exit 1) |
| `(Get-Content C:\temp\shop-api\util.py) -replace 'def tidy\(','def normalise(' \| Set-Content C:\temp\shop-api\util.py` | **MOVED** `util.py::tidy`: `util.py::normalise has the same body structure (a candidate, not a fact)` (exit 1) |
| `Remove-Item C:\temp\shop-api\util.py` | **MISSING** `util.py::tidy` (exit 1) |

Add `--json` to the recheck for the machine-readable report. When you have read the skill against the changes and want today's facts as the new baseline:

```powershell
& $py -m skillforge library refresh commit-message-helper --repo C:\temp\shop-api --drop-missing
```

**In the web page:** the skill's page shows **Code it cites** and a **Recheck** box (type `C:\temp\shop-api`): the same verdicts, worst first.

**It proves:** the recheck notices removed, moved, changed and edited code by what the graph computed, says "candidate" when it is only a guess, and never claims to judge the skill's advice.

## D. Build a skill with the model (Builder page)

Open **Builder**. If the page says no model is set up, the `.env` file in the repository root needs `LLM_PROVIDER`, `LLM_MODEL` and the key (the page never asks for a key).

**Type:** `A skill that counts TODO and FIXME comments in a folder and reports them for each file.` and press **Start**.

The builder reads your words and asks only what is missing. **Answer in plain sentences**, for example:

| If it asks about | You can answer |
|---|---|
| what it produces | `A report of counts per file.` |
| rules and limits | `It must never edit any file.` |
| how we will know it works | `It works when it lists every file with its counts.` |
| when something goes wrong | `If the folder cannot be read it stops and says so.` |

**Expect:** a **Check the requirement** screen where every item sits next to **your own words** that back it; nothing is built until you press **Approve and build**.
Then progress messages, and the result: checks, **each acceptance criterion next to the tests that cover it**, the files (open SKILL.md), the token cost, and **Save to the library**.

**Also try:**
- A request that is not a skill: `An agent that watches my inbox all day and answers emails for me.` The builder should refuse it as "an agent, not a skill" instead of building something wrong.
- Leave out the rules and the success test in your first sentence and see that it asks for exactly those, nothing else.

## E. Agents and MCP servers (the kind picker on the Builder page)

Pick the kind with the radio buttons above the text box.

| Pick | Type | Expect |
|---|---|---|
| **Agent** | `A subagent that reviews a pull request diff for security problems and reports findings with file names and line numbers. It may only read files.` | an `AGENT.md` with a `tools` line that lists only read tools |
| **MCP server** | `An MCP server with two tools: count_words, which counts the words in a text, and shout, which returns the text in capital letters. It needs no network and no keys.` | a `server.py`, and **"ok" only if the server really ran in the sandbox** and every test case matched (needs Docker) |
| **MCP server (Node)** | the same sentence | a `server.ts`, a `package.json` with exact versions, run under `node --permission` in the sandbox |
| **MCP server** (an honest DRAFT) | `An MCP server with one tool that returns the current weather for a city using a weather API key.` | a **DRAFT**: the tool needs the network, so its cases are "not run" and the build never says "ok" |

The result page says, for each test case, whether it **ran in the sandbox**, failed, or did not run. A case that did not run proves nothing, and the page says so.

## F. The Repository page (ideas for a repository)

Open **Repository** and type a folder. Use `C:\temp\shop-api` for a quick look (the graph part works with no model), or this project's own folder for richer ideas:

- Folder: `C:\Users\jj1\OneDrive - Aptean-online\Documents\GitHub\AISkills`
- Only this folder inside it: `backend`

1. **Read the repository.** Expect the languages (python, `full`), how many calls are proven, the most depended-on functions. The page never shows your path.
   **Look at the map under it, "How the code is laid out".** With the folder above (`backend`) expect about 14 boxes named like `skillforge/api`, `skillforge/build`, `skillforge/graph` and `tests`, arrows between them (thicker means more files import across), a yellow box saying which folders import each other, and dashed arrows for the imports that close a loop. **Click a box** (or press Tab, then Enter): its arrows light up and the rest fade, and you get its biggest files and functions. Open **The arrows as a list** to read every arrow in words. The notes under the map say what was left out (imports written by test files, weaker arrows, guesses). To zoom in, put `skillforge` in "Only this folder inside it", read again, and the boxes become `api`, `library`, `build` and so on. A flat repository such as `shop-api` is one box, and the page says so.
2. **Ask for ideas.** Each idea lists the places it cites; they exist in the graph (checked by code), and the card says that does not make the advice right.
3. On a skill idea open **What the skill will be asked to do (you can change it)**. If the model worded it as a task ("Refactor ..."), the builder may refuse it as an agent, so **reword it**, for example:
   `A skill that finds duplicated functions in the backend folder of a Python repository and lists them. It receives the path of the backend folder. It produces a short list of the duplicates, each with the file and the function name. It must never edit any file. It works when every duplicate it lists really exists in the folder. If the folder cannot be read it stops and says so.`
4. **Build this as a skill**, answer anything it asks, approve, and look for the line **It cites N places in AISkills (evidence.json)**. **Save to the library**, open it, and use **Recheck** with the same folder: expect `Holds`.

Things to try on this page: a bare folder name (`shop-api`) and a network path (`\\server\share\repo`) are refused before anything is sent; a folder that does not exist gives a plain message that does not repeat the path; reload the page and the folder is remembered.

## G. Plugins and install

- **Plugins page:** name `my-first-plugin`, description `Helpers for commit messages.`, tick `commit-message-helper`, press **Preview the plugin**. Expect the files, what the plugin can do on your machine, and every check; then **Keep this plugin**. No model is used.
- Library, the skill, **Install...**: to a folder such as `C:\temp\skills-out`. `evidence.json` stays in the library on purpose (it names a repository's code).
- **Export** has a tick box to leave `evidence.json` and `spec.json` out.

## H. The Settings page (model and key)

Open **Settings**. This writes the `.env` file in the project folder, so use a spare key, or only look and press nothing.

1. The top card says **In use: provider / model**, or why no model is usable yet.
2. Change the **Model** name and press **Save changes**. Expect "Saved. It is used from now on, with no restart."; start a build and it uses the new model.
3. In **Keys**, paste a key into a provider's box and save. The box empties and the badge says **Saved**. Reload: the key is never shown again (that is on purpose).
4. Type a key with a space in it and save. Expect **Nothing was saved**, the setting named, and no copy of what you typed. Press **Discard changes**.
5. **Remove it** next to a saved key, then save: the badge says **Not set** and the line is gone from `.env`.
6. **Test my models** sends one tiny question to each model (a little quota) and says whether each works, how fast, or why not ("The key was refused", "Rate limited").
7. If a setting says **Set outside .env**, it comes from your computer's environment and wins over the file: change or remove it there.

Open `.env` in an editor to see what was written: your own lines and comments are kept, and new names are added at the end under one comment line.

## Run the automated checks (what has been verified)

```powershell
cd "C:\Users\jj1\OneDrive - Aptean-online\Documents\GitHub\AISkills\backend"
& $py -m pytest          # about 3 minutes: 2,316 tests, 3 skipped because this account cannot create symbolic links
cd ..\frontend
npm run typecheck; npm test      # the page logic: 141 tests
```

The real-browser run (58 behaviours, drives Edge against the real API with a scripted fake model) needs ports 3100 and 8100 and a build for them:
`$env:NEXT_PUBLIC_API_URL = "http://127.0.0.1:8100"; npm run build; $env:E2E_UI_PORT = "3100"; $env:E2E_API_PORT = "8100"; $env:SKILLFORGE_PYTHON = $py; npm run e2e`.

## If something does not work

| You see | Do this |
|---|---|
| "The API is not running" | start window 1 (`serve`) and press **Try again** |
| "No AI model is set up yet" | put `LLM_PROVIDER`, `LLM_MODEL` and the key in the `.env` file in the repository root, then **Check again**; `models --test` shows what is configured |
| Sandbox row says unavailable / MCP builds are DRAFTs | start Docker in WSL; `& $py -m skillforge sandbox-status` should say AVAILABLE; the MCP images are built once with `sandbox-build-mcp` and `sandbox-build-mcp-node` |
| A page shows something old after you changed files | the `$env:SKILLFORGE_DATA_DIR` folder is what both windows read: use the same value in both |
| Start over cleanly | stop both windows, delete `C:\temp\skillforge-try`, start again |

## What does not exist yet (so you do not look for it)

a drawn graph (the Repository page shows numbers and lists); reading a GitHub link on the command line (the web page does it; clone first for the command line); the behavioural canary scan; Node MCP servers inside plugins; evidence for plugins and MCP servers; the hosted version on a real host (the image was built and run in Docker, not deployed); macOS and Linux (only Windows was used); an interactive Claude Code session using what you build (real Claude Code accepted the generated plugin and server commands in isolated runs).
