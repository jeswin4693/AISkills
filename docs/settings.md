# The Settings page (slice X)

Until this slice a model, its key and its limits could only be set by editing the git-ignored `.env` by hand, and the server read that file
once (a later edit needed a restart). The web UI showed only a one-line "Model" status. The **Settings** page lets a person see what is
set (never a key), change it, and test it. Plan: [superpowers/plans/2026-11-23-settings-page-slice-x.md](superpowers/plans/2026-11-23-settings-page-slice-x.md).

```
Settings page --GET /api/settings--> what is set, and where each value comes from   (a key: only "set" or "not set")
      |
      +-- type a model / paste a key --POST /api/settings--> checked, then written into .env in one step
      |                                                       |  and applied to the running server at once
      |                                                       v
      |                                          the next build, suggestion or test uses it: no restart
      +-- "Test my models" --POST /api/provider/check--> one tiny call to each model (uses a little quota)
```

## What a person sees

| On the page | What it does |
|---|---|
| **The model in use** | "In use: provider / model", or why no model is usable yet, in the server's own words. **Test my models** asks each model one tiny question and says, in plain words, whether it works, how fast, or why not ("The key was refused", "Rate limited", "This key cannot use that model name"). It tests what is **saved**, so it is off while there are unsaved changes. |
| **Your model** | The provider (a list of the supported ones) and the model name. A warning says what is missing for the chosen provider ("No key for groq yet"). |
| **Keys** | One field per provider. A key field is a password box that **starts empty and is never filled in**: the page shows only "Saved" or "Not set". Paste a new key to replace one; **Remove it** takes one out. The custom provider also has its endpoint address. |
| **Backup models** | `provider:model, provider:model`, asked in order when the first model is rate limited, out of quota or unreachable. |
| **More options** (folded) | A different model for one kind of work (reading your words, writing a skill, writing scripts, running a skill's tests, and a second try); four limits (seconds to wait, most calls per run, most input tokens); the answer cache switch. |
| **Save changes** | Sends only what changed. Nothing is saved if any value is refused, and the refusal names the setting and says why without repeating the value. |
| A setting set **outside** `.env` | Shown, but read-only: "Set outside the .env file (in this computer's environment)". A real environment variable wins over the file, so a save would silently stop applying after a restart. Change it where it was set. |

## The rules it keeps

* **A key is never sent back.** Not the value, not its end, not its length (and an error a provider quotes back with a masked key, `sk-proj-****...abcd`, is redacted too, because "Test my models" returns the provider's error text): a secret row says only `set` or not, and where it comes from. No response and no error repeats a value: the body of a save is
  read and checked by hand (FastAPI's own 422 would repeat the input), a refusal says *which setting* and *why*, and the page drops a key from its state the moment it is saved. A key is never put in a URL or in the browser's storage.
* **Only a fixed list of settings can be changed** (`settings/catalogue.py`): the provider, the model, one key per provider, the custom address, backup models, a model for one kind of work, the second-try model, four limits and the cache switch. The hosted-mode options (`SKILLFORGE_MODE`, the access token, the data folder) are not on it. Any other name is refused, so the page can never write any line into the file.
* **A value is one line of safe characters**: letters, digits and `. _ ~ : / , @ + = % -`, with a length limit (400 for a key). That means `.env` never needs quoting and nothing can end the line early or hide inside it (a space, a quote, `#`, `$`, a newline or an invisible character is refused). A key with an unusual character can still be put in `.env` by hand. A provider must be a supported one, a number must be positive and within a limit, an address must be `http://` or `https://` with no login in it, and each backup must be `provider:model`.
* **The file is edited, not rewritten, and checked after the edit.** Other lines, comments and the file's own line endings are kept; every active copy of a name is updated; a commented-out line is left alone; a name that is not there is added at the end with a one-line note. The editor works line by line, but the server reads the file with python-dotenv, which also understands quoted values over several lines and a lone carriage return as a line break. So after every edit the **result is parsed the way the server parses it and compared with what was asked**: if the file would mean anything other than "everything it meant before, with exactly these settings set or removed" (a key written inside a multi-line value, say), **nothing is written** and the person is told to edit that file by hand. The file is replaced in **one step** (a temporary file in the same folder, then a replace, retried a few times because a cloud-synced folder can hold a file for a moment), so a failed write leaves the old file whole; a symbolic link is followed, so the link stays a link. A file that is not valid UTF-8 is not touched, and the page says it cannot read it. It is created (owner-only on Linux and macOS) the first time a person saves.
* **A change applies at once.** The model lookup now re-reads `.env` each time (a real environment variable still wins; `${OTHER}` in a value is worked out the way `load_dotenv` always did, the real environment first) and takes **one consistent copy** of the settings under the lock every save holds, and a save updates the running process. A hand edit that **changes** a value goes live without a restart. A name taken **out** of the file by hand is **not** dropped from a running server (a half-written file must never look like "every setting was removed"): only a save from the page removes one, and a hand removal needs a restart. Names the page does not manage (`LLM_CODE_TIMEOUT_S`, a proxy, ...) are applied once when not set yet, exactly as `load_dotenv` always did, and never changed or removed afterwards. A file that cannot be read right now changes nothing. On Windows a name written in another case (`google_api_key`) is the same setting.
* **Off in the hosted version** (403 on both routes; the page says so): a save would be written on the server, the same risk as installing into a server folder. A page on another website cannot call the save: the API's origin check already refuses a changing request from an origin it does not know.

## The API

| Route | |
|---|---|
| `GET /api/settings` | `{file, file_exists, groups, settings, status}`. Each setting: `name, group, label, help, kind (secret, choice, text, url, number, flag), provider, choices, set, source (file, environment, unset), editable`, and `value` for everything except a key. `status` is the same as `GET /api/provider`. |
| `POST /api/settings` | `{"changes": {"LLM_MODEL": "a-model", "GOOGLE_API_KEY": "...", "LLM_FALLBACKS": null}}`: a text sets, `null` or an empty text removes. All or nothing. 200 answers with the new state (as `GET`). 400 `{detail, problems: [{name, message}]}` when something is refused (an unknown name, a name set in the environment, an unsafe or wrong value, a body that is not the right shape); 413 over 20 KB; 403 in the hosted version. |
| `POST /api/provider/check` | existing: one tiny call to each model that is set up. The page uses it for "Test my models". |

## Checked

* Backend (102 tests; the whole suite: 2,316 passed, 3 skipped for symbolic links): `tests/test_settings.py` (the list, every rule above, the `.env` editor, applying and removing, a failed write, a file that is not text, two saves at once, the review's findings) and `tests/test_settings_api.py` (the routes, no key in any answer or error, hosted 403, another site refused, the model lookup seeing a change). Offline: a test never reads the real `.env` or environment.
* Frontend: 25 unit tests in `lib/settings.test.ts` (141 in all); the real-browser run has a "Settings" section (the menu, saving a model and a key, the key leaving the page and never coming back from the API, a refused value, removing a key - including one typed just before pressing Remove - and "Test my models") against a temporary `.env`.
* Mutation check: each rule above was broken on purpose, one at a time (24 breaks, then 13 more for the review's fixes), and a test caught every break except the symbolic-link one, whose test is skipped on this machine (this account cannot create links).
* **One independent review** (204k tokens) found no key leak and no way to write an unlisted line, and reproduced 4 Important and 6 Minor problems, all fixed test-first: the line editor could edit inside a multi-line quoted value or over a lone carriage return (now a check after every edit), a key typed before pressing Remove was saved instead of removed, "Test my models" could carry the end of a key back inside a provider's masked error text, a non-UTF-8 `.env` was ignored silently, a hand-written lowercase name on Windows showed as "set outside", `${...}` was resolved in a different order than before, a running server followed every name in the file (including a proxy or the data folder) and could drop settings while a file was half-written, a key a backup still needs could be removed with only a status line to say so (the page now warns before saving and says "Saved, but no model is usable yet" after), and small things (an address with a bad port or an IPv6 address, "Gemini" written by hand, the hint for a read-only file).

## What is not here

* Per-kind timeouts and output limits, the data folder and the other server options, the sandbox settings, and the hosted version's own options are still set in the environment or `.env` by hand.
* No list of models is fetched from a provider: models get retired while still listed, so "Test my models" (a real call) is the check.
* A key stored in `.env` is plain text on disk, like before: anyone who can read the file can read the key. The page does not encrypt it.
* The local API has no sign-in, so anything on this computer that can reach `127.0.0.1` could call it; that is true of the whole local API and unchanged. Writing is limited to the fixed list above.
* Only Windows was used for the real-browser run. The owner-only file mode on Linux and macOS is not tested.
