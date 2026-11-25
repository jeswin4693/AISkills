# The Testing Lab (slice AD)

The page that answers **"does this skill really help?"** The Dashboard and the Library only say that a skill passed *static* checks (it is well formed, nothing in it looks dangerous). The Lab runs the
skill's **own test cases** against a model, once with the skill and once without it, and **code (never a model) grades every reply**. Design: [superpowers/specs/2026-11-25-testing-lab-design.md](superpowers/specs/2026-11-25-testing-lab-design.md).
The engine is the one `skillforge eval` already had ([evaluate.md](evaluate.md)); this slice puts it in the web UI and keeps what it finds.

## What a person sees

```
 Testing Lab
   Skill [ git-commit-writer v ]   Version [ v1 (latest) v ]

   What would run
     short change  [positive]   Message sent:  fixed the login button alignment on mobile
                                The reply must pass:  has a first line of at most 50 characters
     no description [negative]  ...
   Run it
     Repeat each test [ once v ]   [x] Also run without the skill (this is what shows whether the skill adds anything)
     This will make 6 model calls to your model (3 tests x 1 repeat x with and without the skill), about 392 tokens of skill each time.
     [ Run the tests ]

   The skill helped
     With the skill: 3 of 3 runs passed every check.  Without it: 1 of 3.   (6 model calls, each test once, about 392 tokens for the skill)
   Case by case
     short change   With the skill  passed 1 of 1      Without it  passed 0 of 1
                                                         - the first line is 54 characters, the limit is 50
                    [Show the reply]                    [Show the reply]
   Earlier runs of this version
     v1  3 min ago  the skill helped · with the skill 3/3 · without it 1/3
```

* **Before anything is asked of a model** the page lists the cases that would run, each check in words, and the **number of model calls** (cases x repeats x conditions). The button says what it will do.
* **A skill that cannot be run says why and what to do**, in its own words, and offers no button: it has no test cases; its test cases have no message or no check (it was saved before test cases could be run);
  or it needs tools (`read_files`, `run_commands`, `network`) or has scripts, which a model with no tools cannot stand in for. The advice never points at a button that does not exist.
* **A run is kept.** It is a row in the database (`eval_runs`, migration 0005) that the page polls, so a reload shows it again, a second click while it works gets the same run (the quota is not spent twice), and a
  restart marks an unfinished run failed and offers "Run it again".
* **The result is the comparison**, never a lone score. The headline says one of: *the skill helped*, *adds nothing* (the model passes everything without it, so its tokens are paid for nothing these tests can see), *no difference*,
  *made it worse*, *too few cases to say* (fewer than three), or *run without the comparison* (no claim about the skill). Each case shows both sides, **each failed check in numbers** ("the first line is 54 characters, the limit is 50")
  and the replies themselves as plain text behind a disclosure.
* **A result is about one version.** The run stores the version and its content hash. When a newer version exists the result says "This run tested v1. The latest version is v2, and this run says nothing about it", and v2 shows no verdict until it has been run.
* A single repeat says that **models vary** and suggests three. The limits sentence of `evaluate.md` is on every result.
* The Library's skill page has a **Test this skill** button that opens the Lab on that version.

## The rules (in code, each one tested)

| Rule | Why |
|---|---|
| The outcome is a **code the server decides** (`EvalReport.outcome()`); the verdict sentence is written from it. The page never parses English. | A reworded sentence must not change what a page does. |
| `plan_cases` is the **one** place that decides which cases run. The run and the preview both use it. | What a person is shown before a run is, by construction, what the run does. |
| A skill that cannot be run is **refused before a run is stored or a model is asked** (400 with the reason). | No run exists that can only say "not run"; no quota is spent. |
| One run per skill version at a time; a second click gets the one that is working. | A double click cannot spend the quota twice. |
| `runs` is 1 to 5, at most 12 cases, 2 calls per case per repeat: bounded before a model is asked (422). | A typo cannot start 5,000 calls. |
| The version is read through `Library.read`, which checks every file against the manifest first. | A skill changed on disk is refused, not tested. |
| Replies are cut at 3,000 characters and messages at 2,000, and **marked as cut**; a reply is rendered as text, never markup. | A stored result stays small, a hostile reply cannot add elements to the page. |
| An error that is not a model or library error is named **by type only**; its text is never stored or shown. | It could hold a path. |
| Only **skills** can be run; any other kind is a 400 that says so. | `eval` for agents is not built. |

## API ([api.md](api.md))

| Route | |
|---|---|
| `GET /api/evals/preview?name=&version=&kind=` | What a run would do, or why not. No model. |
| `POST /api/evals` `{name, version?, runs, baseline, kind}` | Start a run (201). 400 with the reason for a skill that cannot be run, 404 for an unknown skill or version. |
| `GET /api/evals?name=&version=` | Runs, newest first, each with a short `summary`, without the heavy result. |
| `GET /api/evals/{id}` | One run: `status` (`working`, `done`, `failed`), `progress` `{done, total}`, and when done `result`. |
| `POST /api/evals/{id}/retry` | Runs a failed run again. 409 for any other state. |

It works in the hosted version too: it reads the server's library and asks the server's model, like a build does (nothing reads a folder).

## Your own test cases (slice AE)

The Lab's main limit was that the model that wrote a skill also wrote its tests. On the Lab page a person can now **write the cases themselves**, and keep them as a **new version** of the skill.

```
 Your test cases
   Case 1                                                         [Remove case]
     Name [ short change ]            Kind [ positive: the usual case, it should work v ]
     Message sent to the model (exactly what a person would type)
       [ fixed the login button alignment on mobile ]
     The reply must pass (1 to 3 checks)
       The reply [ has a first line of at most … characters v ]  Number [ 50 ]  Why [ the title is at most 50 characters ]   [Remove]
       [Add a check]
   [Add a case]
   Before this can be saved
     - Case 2 ('x'): it needs a message to send.
   Note [ ... ]                         [ Keep as a new version (v2) ]
```

* **Where it appears.** For a skill with no cases, or whose cases have no message or no check (the Lab's old advice is now this editor), on the **latest** version; for a runnable skill behind an **Edit the test cases…** button. A skill that **needs tools gets no editor**: more cases would not make it runnable.
  An older version offers none and says "Open the latest version": a save always makes the **next** version.
* **A case** is a name, a kind (positive, negative, edge), the exact message, and one to three of the seven checks with a value and an optional reason. An old case saved before cases could be run is shown with its name and an empty message, with a hint where to add a check.
* **The page says what would stop a save before it is pressed**, by the same rules the server applies (a name, a name not used twice, a message, at least one check, a whole number from 1 to 1,000,000 for a size, a pattern of at most 80 characters, the sizes); the server checks again, and also the rule that needs Python (a pattern that repeats a repeat could hang the checker).
  Every problem of every case is listed in one go, naming the case.
* **A save is a new version through the library's checked import**: `tests/cases.json` is written the way the builder writes it (indented, every character kept), **and the definition file `skill.sdm.json`'s own copy of the tests is updated with it** when it has one, so a later rebuild cannot bring the old tests back (and a definition that cannot be read stops the save rather than leave two copies that disagree).
  Everything else in the folder is carried over unchanged. The static checks run: **a message pasted with a hidden character is refused** and said in words (nothing stored), wording that only warns is kept with its warning.
* **A case whose words did not change keeps the descriptions it had** (`input_description`, `expected_result`); a changed or new one gets descriptions worked out from what the person wrote, never left stale.
* **A newer version made meanwhile is never dropped**: the edit names the version it was made on, and a save is refused (409, "A newer version exists") when that is no longer the latest.
* **Saving the same cases twice makes one version**, not two. The new version is marked `tests` / "edited in the Testing Lab" with the person's note, and shows in the library, the compare page and the risk diff like any change.

## Limits (said plainly)

* **A skill that needs tools cannot be run here**, and that is **most skills about code**. On 2026-11-25 none of the three skills saved on the author's machine could be run: one needs `read_files`, one was saved before test cases had messages, one was imported with no test cases.
  The Lab says so honestly; it does not pretend a model with no tools is an agent. For those skills the test that matters is still installing the skill and using it.
* **The tests of a built skill were written by the same model that wrote it**, so a skill can pass weak tests. Read the cases the page lists before believing a verdict. Cases a person writes themselves (above) are the stronger answer, but they still reach only what the seven checks can say, and a person can write weak ones too.
* **The README's count of test cases is not rewritten** when cases are edited (a built skill's README says how many it has); only `tests/cases.json` and the definition's copy are.
* **One model, a small sample, repeats of 1 to 5.** A single run is noisy: the first and second runs of the same build in `evaluate.md` said 0 of 3 and 2 of 6 without the skill.
* **Only what the seven checks can say** is checked (text, a pattern, length). Not facts, not tone, not "is this a good summary".
* **A run spends the model's quota**, and the page says how much before it starts. Nothing is counted in tokens per run (the AI engine's usage table is per builder session).
* The result of a run is kept forever (no clean-up yet); a run that was working when the server stopped is marked failed.

## Checked (2026-11-25)

**Tests.** Backend: **2,886 collected, 4 skipped (symbolic links), 0 failed** (2,842 passed before the slice, so 40 are new: `test_testing_lab.py` for the engine, `test_testing_lab_api.py` for the service and the routes; one existing test that
pins the list of tables was changed on purpose, and it also proves migration 0005 equals the model). Web: **294 unit tests** (35 new, `lib/testing.test.ts`) and a clean typecheck. Browser (real Edge, the real API, a scripted fake model, side ports 3100/8100):
**86 of 86** (76 before; 10 new steps: the menu and the empty page; a skill with no test cases says why and offers no run; a skill that needs tools says a model with no tools cannot stand in; the preview lists the cases and the cost, 6 then 18 then 9 calls as the choices change;
a run shows progress and then the verdict with both sides, each failed check in numbers and a reply behind a disclosure; the result is still there after a reload and listed under earlier runs; the skill page links in with its version; a model that cannot be reached fails the
run and "Run it again" finishes it; a newer version says so and has no verdict of its own; no sideways scrolling at phone width). Screenshots were read by eye, which found two things to fix: the same sentence shown twice on the "needs tools" page, and a skill name capitalised into "Todo-counter-e2e".

**The browser suite found a real fragility, not a test mistake.** The first run failed 9 of the 10 new steps because the picker could not be found by its label: the label wrapped the `<select>`, so its text included every option. Each label is now tied to its control by an `id`.

**Deliberate breaks: 36, all caught** (20 on the backend, 16 on the page's logic). The first run of the page's breaks caught 15 of 16: replacing the advice for a skill that needs tools with "Add more test cases" went unnoticed because my test accepted any of three phrases, one of which was elsewhere in the text. The test now demands the right advice and rejects the wrong kind, and the break is caught.

**Real run (2026-11-25, the configured model, `gemini-3.5-flash-lite`, through the real HTTP API and a throwaway data folder, so the real library was not touched):** a text-only commit-message skill with three cases was imported, previewed (3 cases, 6 calls), run, and polled
(progress 0, 1, 2, 3 of 3) in **12 seconds**: *The skill helped*, with the skill 3 of 3, without it 1 of 3. Without the skill the model answered "write me a commit message" with an invented `feat: add initial project structure and configuration` (it never asked what changed) and wrote a 53-character title for the refactor;
with the skill it asked, and kept the title short. **That run showed that the result said 7 model calls where the page had promised 6**: a call that is tried again counts as an attempt. The page now says so before the run. One run, one model, three cases: it shows the path works with a real model, not how good the skill is.

**Not verified:** the hosted version's sign-in with this page (it adds nothing of its own); a skill with many cases and repeats (a run of 12 cases x 5 repeats x 2 is 120 calls: bounded, but not timed); a model that is slow for minutes (the page polls and tolerates five failed polls, which was not forced in the browser);
macOS and Linux; a screen reader beyond the native controls (labels are tied to controls by id; the progress bar has `role=progressbar`); any browser but Edge.

## Checked, slice AE: your own test cases (2026-11-25)

**Tests.** Backend: **2,930 collected, 4 skipped (symbolic links)**, 44 new in `test_case_editor.py` (2,886 before); web: **322 unit tests** (28 new: `lib/cases.test.ts`, and two for the changed advice) and a clean typecheck; browser (real Edge, the real API, a scripted fake model, side ports): **92 of 92** (86 before; 6 new steps: a
runnable skill offers its cases and nothing can be saved until something changes; the first case of a skill that had none is written, the page names what is missing before the button is pressed, and the Lab then runs it and says "Too few test cases to say" for one case; an old case with no message or check is shown by name, with a hint where to add a check, and the fixed one runs and its descriptions are worked out
again; an edit of a version that is no longer the latest is refused with "A newer version exists" and stores nothing; a message pasted with a hidden character is refused by the library's own checks, said in words with the line, and stores nothing; no sideways scrolling at phone width).

**Deliberate breaks: 35, all caught** (18 backend, 17 page logic). Two were not caught at first and both were my tests' fault, not the code's: nothing checked that a changed *check* (not only a changed message) refreshes a case's `expected_result`, so it could have described checks that no longer exist (a test now does); and one "break" of the page's order-comparison was not a break at all (calling `.sort()` on objects sorts nothing), so
it was rewritten to really ignore order and caught.

**Found while building it, and fixed:**
* The design said `PUT`. **This API's CORS policy allows only GET, POST and DELETE**, so a browser could not have sent it, though every offline test would have passed. It is a `POST`, like the API's other writes.
* A built skill keeps **two copies of its tests** (`tests/cases.json` and the `tests` list inside `skill.sdm.json`, which a rebuild renders from). Editing one would have let a later rebuild bring the old tests back; a save now updates both, and stops if the definition cannot be read.
* A save files a version under the name the skill gives itself, so a skill filed under a different library name would have created a **second skill** instead of a new version. A guard refuses it.
* A case with no checks showed an empty list and no hint (the browser run failed on it): the page now says "No checks yet" and where to add one. The selected check was cut off in a narrow dropdown: widened.
* An existing test (`test_the_same_conversation_works_on_real_threads_with_the_browser_poll`) failed once, with a browser suite running beside it: it asserted at once that the session is done *and* its job succeeded, but those are two updates a moment apart. It now waits for the second. (A race in the test, not in the product.)

**Real run on your own skill (2026-11-25, `gemini-3.5-flash-lite`, the real HTTP API on a COPY of your library, so the real one was not touched):** `meeting-notes-summarizer` had no test cases, so the Lab said "no test cases". Three cases were written from the skill's own rules (ask when no notes are pasted; write "unassigned" for a task with no owner; do not invent) and saved through the API as `v2`
("tests", with the note); the Lab then ran them in 14 s: **2 of 3 with the skill, 2 of 3 without it, "no difference"**. The reading of the replies is the useful part, and it is a lesson about the limits of the seven checks:
* **With the skill it failed my third case** with `Sam: Write the test plan (due date: unassigned)`: it used the word "unassigned" for a missing *due date*, which the skill never asked for (it says to write it when there is no *owner*). So the check caught a real, mild misbehaviour, and the skill's wording is a little loose.
* **Without the skill it "passed" that case by doing nothing the skill is for**: one line, "Notes received and recorded: ...", no summary, no decisions, no action items. A "must not say X" check is passed by an answer that does not do the job at all. And the two sides both scored 2 of 3 for opposite reasons (the skill failed one the model passed; the model failed one the skill passed).
  So **"no difference" here does not mean the skill is useless**: the seven checks cannot express "did the job". Tests that name what a good answer must contain (as the second case does: "unassigned" and "Priya") are worth more than tests that only name what it must not.

**Not verified:** the editor against a very large library or 30 cases of 4,000 characters (bounded, not timed); two people saving at once (the second is refused as stale, which is the rule, but a simultaneous race at the file level was not provoked); a screen reader beyond native controls and labels tied by id; any browser but Edge.

## Next

* **AF: the Quality Report page**: it gathers a version's checks, token cost, which criteria have tests (now including a person's own cases, which carry no criteria unless they were kept) and the latest Lab result, and had little to show before the Lab kept results.
* An **independent review** of slices AD and AE together is still owed (earlier slices W, X, Y, Z and AB each had one and each found real bugs).
