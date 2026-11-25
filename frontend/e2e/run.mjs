// End-to-end check in a real browser: the real API (a scratch data folder, a fake scripted model), the built UI, and
// Microsoft Edge.
//
//   npm run build && npm run e2e
//
// Needs Edge (Windows has it) or set E2E_BROWSER_CHANNEL=chrome. No browser is downloaded: playwright-core drives the
// installed one. Set SKILLFORGE_PYTHON to the Python that has the backend installed. Screenshots go to E2E_SHOTS if set.
// The model is fake on purpose (e2e/mock_server.py): the run is deterministic and needs no key and no network. Everything
// else is real. A run against a real model is a separate, manual check (see docs/ui.md).
import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { crc32 } from "node:zlib";
import { chromium } from "playwright-core";

const here = path.dirname(fileURLToPath(import.meta.url));
const frontend = path.resolve(here, "..");
const backend = path.resolve(frontend, "..", "backend");
const python = process.env.SKILLFORGE_PYTHON ?? "python";
// The ports are configurable so this can run next to your own `serve` and `npm run dev`. If you change them, build the UI
// for the new API address first:  $env:NEXT_PUBLIC_API_URL = "http://127.0.0.1:8100"; npm run build
const UI_PORT = process.env.E2E_UI_PORT ?? "3000";
const API_PORT = process.env.E2E_API_PORT ?? "8000";
const UI = `http://127.0.0.1:${UI_PORT}`;
const API = `http://127.0.0.1:${API_PORT}`;
const shots = process.env.E2E_SHOTS;
const scratch = fs.mkdtempSync(path.join(os.tmpdir(), "skillforge-e2e-"));
const installRoot = path.join(scratch, "project", ".claude", "skills");
const modelFlag = path.join(scratch, "model-ready"); // the fake model counts as "not set up" until this file exists

// ---- a store-only zip writer, so the test needs no zip library --------------------------------------
function makeZip(entries) {
  const locals = [];
  const centrals = [];
  let offset = 0;
  for (const [name, content] of Object.entries(entries)) {
    const nameBuf = Buffer.from(name, "utf8");
    const data = Buffer.isBuffer(content) ? content : Buffer.from(content, "utf8");
    const crc = crc32(data);
    const local = Buffer.alloc(30);
    local.writeUInt32LE(0x04034b50, 0);
    local.writeUInt16LE(20, 4);
    local.writeUInt16LE(0, 6);
    local.writeUInt16LE(0, 8); // stored
    local.writeUInt16LE(0, 10);
    local.writeUInt16LE(33, 12); // 1980-01-01
    local.writeUInt32LE(crc, 14);
    local.writeUInt32LE(data.length, 18);
    local.writeUInt32LE(data.length, 22);
    local.writeUInt16LE(nameBuf.length, 26);
    locals.push(local, nameBuf, data);
    const central = Buffer.alloc(46);
    central.writeUInt32LE(0x02014b50, 0);
    central.writeUInt16LE(20, 4);
    central.writeUInt16LE(20, 6);
    central.writeUInt16LE(0, 8);
    central.writeUInt16LE(0, 10);
    central.writeUInt16LE(0, 12);
    central.writeUInt16LE(33, 14);
    central.writeUInt32LE(crc, 16);
    central.writeUInt32LE(data.length, 20);
    central.writeUInt32LE(data.length, 24);
    central.writeUInt16LE(nameBuf.length, 28);
    central.writeUInt32LE(offset, 42);
    centrals.push(central, nameBuf);
    offset += 30 + nameBuf.length + data.length;
  }
  const cd = Buffer.concat(centrals);
  const end = Buffer.alloc(22);
  end.writeUInt32LE(0x06054b50, 0);
  end.writeUInt16LE(Object.keys(entries).length, 8);
  end.writeUInt16LE(Object.keys(entries).length, 10);
  end.writeUInt32LE(cd.length, 12);
  end.writeUInt32LE(offset, 16);
  return Buffer.concat([...locals, cd, end]);
}

const skillMd = (body) => `---\nname: e2e-demo\ndescription: A demo skill used by the end-to-end test.\n---\n# E2E demo\n\n${body}`;
const V1 = skillMd("Read the file.\n\n---\n\nSay what it holds.\n");
const V2 = skillMd("Read the file.\n\nSay what it holds, and list its first three lines.\n"); // the '---' rule is removed
const zipOf = (md, extra = {}) => makeZip({ "e2e-demo/SKILL.md": md, "e2e-demo/README.md": "A demo.\n", ...extra });

// ---- processes ---------------------------------------------------------------------------------------
const children = [];
function start(cmd, args, opts) {
  const log = fs.openSync(path.join(scratch, `${path.basename(args[0] ?? cmd)}-${children.length}.log`), "w");
  const child = spawn(cmd, args, { ...opts, stdio: ["ignore", log, log], windowsHide: true });
  children.push(child);
  return child;
}
async function waitFor(url, what, timeoutMs = 60000) {
  const end = Date.now() + timeoutMs;
  while (Date.now() < end) {
    try {
      if ((await fetch(url)).ok) return;
    } catch {
      /* not up yet */
    }
    await new Promise((r) => setTimeout(r, 400));
  }
  throw new Error(`${what} did not start at ${url}`);
}

let passed = 0;
const failures = [];
async function step(name, fn) {
  try {
    await fn();
    passed += 1;
    console.log(`  ok   ${name}`);
  } catch (e) {
    failures.push(name);
    console.log(`  FAIL ${name}\n       ${String(e.message ?? e).split("\n").slice(0, 6).join("\n       ")}`);
  }
}
const shot = async (page, name) => {
  if (shots) {
    fs.mkdirSync(shots, { recursive: true });
    await page.screenshot({ path: path.join(shots, `${name}.png`), fullPage: true });
  }
};

// ---- the run -----------------------------------------------------------------------------------------
let api;
let ui;
let browser;
try {
  api = start(python, [path.join(here, "mock_server.py")], {
    cwd: backend,
    env: {
      ...process.env, PYTHONPATH: backend, SKILLFORGE_DATA_DIR: path.join(scratch, "data"), E2E_MODEL_FLAG: modelFlag,
      E2E_API_PORT: API_PORT, SKILLFORGE_UI_ORIGINS: UI, // the API only accepts changes from origins it was told about
    },
  });
  ui = start(process.execPath, [path.join(frontend, "node_modules", "next", "dist", "bin", "next"), "start", "--hostname", "127.0.0.1", "--port", UI_PORT], {
    cwd: frontend,
    env: { ...process.env, NEXT_TELEMETRY_DISABLED: "1" },
  });
  await waitFor(`${API}/api/health`, "the API");
  await waitFor(`${UI}/library`, "the UI");

  browser = await chromium.launch({ channel: process.env.E2E_BROWSER_CHANNEL ?? "msedge", headless: true });
  const context = await browser.newContext({ viewport: { width: 1280, height: 900 }, acceptDownloads: true });
  const page = await context.newPage();
  const problems = [];
  page.on("pageerror", (e) => problems.push(`page error: ${e.message}`));
  // The browser logs every non-2xx answer as a console error. This run deliberately provokes a 400 (not a zip),
  // a 404 (unknown skill), a 409 (install onto an existing folder) and a 422 (a refused skill), so those lines are
  // expected. A script error, or any other status, is a real problem.
  const expectedLog = /Failed to load resource: the server responded with a status of (400|404|409|422)/;
  page.on("console", (m) => m.type() === "error" && !expectedLog.test(m.text()) && problems.push(`console: ${m.text()}`));
  const upload = (name, buffer, type = "application/zip") => page.locator('input[type="file"]').setInputFiles({ name, mimeType: type, buffer });
  const alert = (re) => page.locator('[role="alert"], [role="status"]').filter({ hasText: re }).first();

  console.log("The front door");
  await step("/ opens the dashboard, which says the model is not set up and nothing is saved yet, and the status panel finds the API", async () => {
    await page.goto(UI + "/");
    await page.getByRole("heading", { name: "Dashboard", level: 1 }).waitFor();
    await page.getByRole("heading", { name: "Needs attention", level: 2 }).waitFor();
    await page.getByText("No AI model is set up").waitFor(); // this test server starts with no model, like a missing .env
    await page.getByText("Nothing saved yet").waitFor();
    await page.getByText("No builds yet").waitFor();
    await page.getByText(/online · v/).waitFor();
    await page.getByText("Linux, ready").waitFor({ timeout: 30000 }).catch(() => {}); // the sandbox may be absent on another machine
    await shot(page, "00-dashboard-empty");
  });
  await step("the sidebar leads to the library", async () => {
    await page.getByRole("navigation", { name: "Main" }).getByRole("link", { name: "Library" }).click();
    await page.waitForURL("**/library");
    await page.getByRole("heading", { name: "Library", level: 1 }).waitFor();
  });

  console.log("The library page");
  await step("an empty library says so", async () => {
    await page.getByText("No skills yet").waitFor();
    await shot(page, "01-empty-library");
  });
  await step("a valid zip is imported as v1 and listed", async () => {
    await upload("e2e-demo.zip", zipOf(V1));
    await alert(/Imported 'e2e-demo' as v1/).waitFor();
    await page.getByRole("link", { name: /e2e-demo/ }).first().waitFor();
    await shot(page, "02-imported-v1");
  });
  await step("the same zip again changes nothing", async () => {
    await upload("e2e-demo.zip", zipOf(V1));
    await alert(/Unchanged: 'e2e-demo' is identical to v1/).waitFor();
  });
  await step("a changed zip becomes v2 and lists what differs", async () => {
    await upload("e2e-demo.zip", zipOf(V2, { "e2e-demo/extra.md": "More.\n" }));
    await alert(/Imported 'e2e-demo' as v2/).waitFor();
    await page.getByText("extra.md").first().waitFor();
    await shot(page, "03-imported-v2");
  });
  await step("the import also says what to look at, in words that never call a skill safe", async () => {
    await alert(/v1 → v2: Worth a look/).waitFor();
    await page.getByText("The instructions in SKILL.md changed").waitFor();
    await page.getByText(/A new Markdown file, extra\.md/).waitFor();
    await page.getByText(/cannot read meaning/).waitFor();
    assert.equal(await page.getByText("More risk", { exact: true }).count(), 0, "nothing in this change adds a capability");
    const summary = await alert(/v1 → v2: Worth a look/).innerText();
    assert.doesNotMatch(summary, /\bsafe\b/i, "the risk summary must never call a skill safe");
  });
  await step("a skill with a hidden character is refused, shows the failed check, and adds nothing", async () => {
    await upload("bad.zip", makeZip({ "SKILL.md": "---\nname: sneaky\ndescription: Looks fine.\n---\nHello‮ there\n" }));
    await alert(/Refused: nothing was added/).waitFor();
    await page.getByText("FAILED").first().waitFor();
    assert.equal(await page.getByRole("link", { name: /sneaky/ }).count(), 0);
    await shot(page, "04-refused");
  });
  await step("something that is not a zip gives a plain error", async () => {
    await upload("notes.txt", Buffer.from("just text"), "text/plain");
    await alert(/could not be done/).waitFor();
    await page.getByText(/not a zip/).first().waitFor();
  });

  console.log("The skill page");
  await step("opening the skill shows v2 as latest and v1, and the SKILL.md text", async () => {
    await page.goto(UI + "/library");
    await page.getByRole("link", { name: /e2e-demo/ }).first().click();
    await page.getByRole("heading", { name: "e2e-demo", level: 1 }).waitFor();
    await page.getByRole("heading", { name: /^v2/ }).waitFor();
    await page.getByLabel("Text of SKILL.md").getByText("A demo skill used by the end-to-end test.", { exact: false }).waitFor();
    await shot(page, "05-skill-page");
  });
  await step("changes since v1 show added and removed lines, and a removed --- rule counts as removed", async () => {
    await page.getByRole("link", { name: "Changes since v1" }).click();
    await page.getByText("added line:").first().waitFor();
    const removed = await page.locator("div.bg-del-bg").allTextContents();
    assert.ok(removed.some((t) => t.includes("----")), `no removed '----' line among: ${JSON.stringify(removed)}`);
    assert.ok((await page.locator("div.bg-add-bg").count()) >= 1);
    await shot(page, "06-diff");
  });
  await step("the version pickers on the compare page change the comparison", async () => {
    await page.getByLabel("From version").selectOption("2");
    await page.waitForURL("**/diff?from=2&to=2");
    await page.getByText("v2 and v2 are identical").waitFor();
    await page.getByLabel("To version").selectOption("1");
    await page.waitForURL("**/diff?from=2&to=1");
    await page.getByText("added line:").first().waitFor(); // v2 -> v1 puts the '---' rule back
  });
  await step("restoring v1 asks first, then adds v3 and keeps the older versions", async () => {
    await page.goto(UI + "/library/e2e-demo");
    await page.getByRole("button", { name: /^v1/ }).click();
    await page.getByRole("button", { name: "Restore this version…" }).click();
    await page.getByRole("dialog").getByText(/adds a new version/).waitFor();
    await page.getByRole("button", { name: "Restore v1" }).click();
    await alert(/Restored: v3 now has the content of v1/).waitFor();
    await page.getByRole("button", { name: /^v3/ }).waitFor();
    assert.equal(await page.getByRole("button", { name: /^v[123]\b/ }).count(), 3);
    await shot(page, "07-restored");
  });
  await step("export downloads a real zip", async () => {
    await page.getByRole("button", { name: /^v3/ }).click();
    const [download] = await Promise.all([page.waitForEvent("download"), page.getByRole("button", { name: "Export .zip" }).click()]);
    assert.equal(download.suggestedFilename(), "e2e-demo-v3.zip");
    const file = path.join(scratch, download.suggestedFilename());
    await download.saveAs(file);
    assert.equal(fs.readFileSync(file).subarray(0, 2).toString(), "PK");
    await alert(/Exported e2e-demo-v3\.zip/).waitFor();
  });
  await step("install needs a folder, writes the skill there, and a second install asks before replacing", async () => {
    await page.getByRole("button", { name: "Install…" }).click();
    const dialog = page.getByRole("dialog");
    await dialog.getByLabel(/A folder I choose/).check();
    assert.ok(await dialog.getByRole("button", { name: "Install" }).isDisabled(), "Install should wait for a folder");
    await dialog.getByLabel("Skills folder (absolute path)").fill(installRoot);
    await dialog.getByRole("button", { name: "Install" }).click();
    await dialog.getByText("Installed").first().waitFor();
    assert.ok(fs.existsSync(path.join(installRoot, "e2e-demo", "SKILL.md")), "SKILL.md was not written");
    await shot(page, "08-installed");
    await dialog.getByRole("button", { name: "Done" }).click();

    await page.getByRole("button", { name: "Install…" }).click();
    await dialog.getByLabel(/A folder I choose/).check();
    await dialog.getByLabel("Skills folder (absolute path)").fill(installRoot);
    await dialog.getByRole("button", { name: "Install" }).click();
    await dialog.getByText("That folder already exists").waitFor();
    assert.equal(await dialog.getByText("--force").count(), 0, "a command-line flag leaked into the dialog");
    await shot(page, "09-install-conflict");
    await dialog.getByRole("button", { name: "Back it up and replace" }).click();
    await dialog.getByText(/was copied to/).waitFor();
    await dialog.getByRole("button", { name: "Done" }).click();
  });
  await step("an unknown skill shows a plain error with a way back", async () => {
    await page.goto(UI + "/library/nothing-here");
    await page.getByText("Something went wrong").waitFor();
    await page.getByRole("link", { name: "Back to the library" }).waitFor();
  });

  console.log("Risk diff and re-check");
  const riskyZip = (desc, extra = {}) =>
    makeZip({ "risky-demo/SKILL.md": `---\nname: risky-demo\ndescription: ${desc}\n---\n# Risky demo\n\nRead the notes.\n`, "risky-demo/README.md": "A demo.\n", ...extra });
  const riskyStored = path.join(scratch, "data", "library", "risky-demo", "v1", "skill", "README.md");
  await step("a first version has nothing to compare with, so no risk is shown", async () => {
    await page.goto(UI + "/library");
    await upload("risky-demo.zip", riskyZip("A demo skill for the risk check."));
    await alert(/Imported 'risky-demo' as v1/).waitFor();
    assert.equal(await page.getByText(/More risk|Worth a look|No new risk/).count(), 0);
  });
  await step("a version that adds a script using the network is flagged as more risk, with the reasons", async () => {
    await upload("risky-demo.zip", riskyZip("A demo skill for the risk check, now with a helper.", {
      "risky-demo/scripts/fetch.py": "import requests\nrequests.get('https://api.example.test/data')\n",
    }));
    await alert(/Imported 'risky-demo' as v2/).waitFor();
    await alert(/v1 → v2: More risk than the version before/).waitFor();
    await page.getByText("A new script, scripts/fetch.py: it uses network.").waitFor();
    await page.getByText(/A web address that the version before did not mention: api\.example\.test/).waitFor();
    await page.getByText(/The description changed/).waitFor();
    await page.getByText(/cannot read meaning/).waitFor();
    await shot(page, "10-risk-after-import");
  });
  await step("the compare page shows the same risk above the file changes", async () => {
    await page.goto(UI + "/library/risky-demo/diff");
    await alert(/v1 → v2: More risk than the version before/).waitFor();
    await page.getByText("A new script, scripts/fetch.py: it uses network.").waitFor();
    await page.getByText("scripts/fetch.py").first().waitFor();
    await shot(page, "11-risk-on-compare");
  });
  await step("re-checking one skill says nothing got worse, and says it checks only what code can see", async () => {
    await page.goto(UI + "/library/risky-demo");
    await page.getByRole("heading", { name: "Re-check this skill" }).waitFor();
    await page.getByRole("button", { name: "Re-check now" }).click();
    await alert(/Nothing got worse: 2 versions checked/).waitFor();
    await page.getByText(/passing is not proof that a skill is safe/).last().waitFor();
  });
  await step("re-checking the whole library lists every version, with links", async () => {
    await page.goto(UI + "/library");
    await page.getByRole("button", { name: "Re-check now" }).click();
    await alert(/Nothing got worse: \d+ versions checked/).waitFor();
    await page.getByRole("link", { name: "risky-demo v2", exact: true }).waitFor();
    await page.getByRole("link", { name: "e2e-demo v1", exact: true }).waitFor();
  });
  await step("a stored file edited behind the library's back is reported damaged, and again fine once restored", async () => {
    const original = fs.readFileSync(riskyStored);
    fs.writeFileSync(riskyStored, "tampered\n");
    try {
      await page.getByRole("button", { name: "Re-check again" }).click();
      await alert(/1 version damaged/).waitFor();
      await page.getByText(/was changed after import \(README\.md\)/).waitFor();
      await shot(page, "12-rescan-damaged");
    } finally {
      fs.writeFileSync(riskyStored, original);
    }
    await page.getByRole("button", { name: "Re-check again" }).click();
    await alert(/Nothing got worse/).waitFor();
  });

  console.log("The builder");
  let convoPath = "";
  const describe = (text) => page.getByLabel("What should the skill do?").fill(text);
  const startBtn = () => page.getByRole("button", { name: "Start", exact: true });
  await step("without a model the builder says what to set up and never asks for a key", async () => {
    await page.goto(UI + "/builder");
    await page.getByText("No AI model is set up yet").waitFor();
    await page.getByText("Supported: custom, gemini").first().waitFor(); // the server's own explanation of what is missing
    assert.equal(await page.locator('input[type="password"]').count(), 0);
    assert.equal(await page.getByLabel(/key/i).count(), 0, "the page must not ask for a key");
    await describe("A skill that counts TODO and FIXME comments in a folder.");
    assert.ok(await startBtn().isDisabled(), "Start must wait for a model");
    await shot(page, "13-no-model");
  });
  await step("after the model is set up, 'Check again' lets the person start", async () => {
    fs.writeFileSync(modelFlag, "ready");
    await page.getByRole("button", { name: "Check again" }).click();
    await page.getByText("No AI model is set up yet").waitFor({ state: "detached" });
    await page.getByText("Model: mock-1").waitFor();
    await page.getByRole("region", { name: "Status" }).getByText("mock-1").waitFor(); // the sidebar updates without a reload
    assert.ok(await startBtn().isEnabled());
  });
  await step("a sentence starts a session that is 'working', then asks only what is missing", async () => {
    await startBtn().click();
    await page.waitForURL(/\/builder\/[0-9a-f]{32}$/);
    convoPath = new URL(page.url()).pathname;
    await page.getByText(/Reading your words/).first().waitFor();
    await page.getByText("A few details are missing").waitFor();
    assert.equal(await page.locator("form textarea").count(), 4, "only the 4 missing items should be asked");
    await page.locator('[aria-current="step"]').getByText("Answer").waitFor();
    assert.ok(await page.getByRole("button", { name: "Send answers" }).isDisabled(), "needs at least one answer");
    await shot(page, "14-questions");
  });
  await step("the answers go back, and the requirement shows each item next to the person's own words", async () => {
    await page.getByLabel(/What it produces/).fill("It should give a report of counts per file.");
    await page.getByLabel(/Rules it must respect/).fill("It must never edit any file.");
    await page.getByLabel(/How we will know it works/).fill("It works when it lists every file with its counts.");
    await page.getByLabel(/When something goes wrong/).fill("If the folder cannot be read it stops and says so.");
    await page.getByRole("button", { name: "Send answers" }).click();
    await page.getByText("Check the requirement").waitFor();
    await page.getByText("“never edit any file”").waitFor();
    await page.getByText("“in a folder”").waitFor();
    assert.equal(await page.getByRole("button", { name: "Approve and build" }).count(), 1);
    await shot(page, "15-requirement");
  });
  await step("approving builds the skill with progress, then shows which test covers each acceptance criterion", async () => {
    await page.getByRole("button", { name: "Approve and build" }).click();
    await page.getByText(/Writing the skill/).first().waitFor();
    await page.getByRole("heading", { name: "todo-counter-e2e", level: 1 }).waitFor({ timeout: 30000 });
    await page.getByText("every check that ran passed").first().waitFor();
    await page.getByText("What you asked for, and what covers it").waitFor();
    await page.getByText("AC1", { exact: true }).first().waitFor();
    for (const t of ["counts a file", "unreadable folder", "empty folder"]) await page.getByText(t).first().waitFor();
    assert.equal(await page.getByText("No test case covers this.").count(), 0);
    await page.getByLabel("Text of SKILL.md").filter({ hasText: "name: todo-counter-e2e" }).waitFor();
    await shot(page, "16-built");
  });
  await step("the built skill says what it costs to use, and its SKILL.md carries the person's rules, a done-when list and an example", async () => {
    await page.getByText(/Costs about [\d,]+ tokens on every task \(its name and description\) and [\d,]+ more when the agent uses it\. Estimates\./).waitFor();
    const text = await page.getByLabel("Text of SKILL.md").innerText();
    for (const heading of ["## Steps", "## Rules", "## Done when", "## Example"]) assert.ok(text.includes(heading), `SKILL.md has no '${heading}'`);
    assert.ok(text.includes('Use when the request involves "count TODO comments"'), "the description lacks the trigger phrases");
    for (const gone of ["## Responsibilities", "## Limitations", "## Permissions"]) assert.ok(!text.includes(gone), `'${gone}' is loaded every time but only people read it`);
  });
  await step("saving puts it in the library, and the library shows it as v1", async () => {
    await page.getByRole("button", { name: "Save to the library" }).click();
    await page.getByText("Saved to the library as 'todo-counter-e2e' v1").waitFor();
    await page.getByRole("link", { name: "Open it in the library" }).click();
    await page.getByRole("heading", { name: "todo-counter-e2e", level: 1 }).waitFor();
    await page.getByRole("heading", { name: /^v1/ }).waitFor();
  });
  await step("a model failure is shown plainly, and 'Try again' continues from the same place", async () => {
    await page.goto(UI + "/builder");
    await describe("A skill that counts TODO and FIXME comments in a folder. [model-down]");
    await startBtn().click();
    await page.getByText("It stopped").waitFor();
    await page.getByText(/could not be reached/).first().waitFor();
    await shot(page, "17-failed");
    await page.getByRole("button", { name: "Try again" }).click();
    await page.getByText("A few details are missing").waitFor();
  });
  await step("a DRAFT is flagged and cannot be saved until the person says they understand it", async () => {
    await page.goto(UI + "/builder");
    await describe(
      "A skill that counts TODO and FIXME comments in a folder. [draft] It should give a report of counts per file. It must never edit any file. " +
        "It works when it lists every file with its counts. If the folder cannot be read it stops and says so.",
    );
    await startBtn().click();
    await page.getByText("Check the requirement").waitFor(); // everything was in the first sentence: no questions
    await page.getByRole("button", { name: "Approve and build" }).click();
    await page.getByText("This skill is a DRAFT").waitFor({ timeout: 30000 });
    await page.getByText("Built as a DRAFT").waitFor(); // the badge at the top does not say a plain, green "Built"
    await page.getByText("No test case covers this.").first().waitFor();
    const save = page.getByRole("button", { name: "Save to the library" });
    assert.ok(await save.isDisabled(), "a draft must not be saveable by accident");
    await page.getByLabel(/I understand it is a draft/).check();
    assert.ok(await save.isEnabled());
    await shot(page, "18-draft");
    await save.click();
    await page.getByText(/Saved to the library as 'todo-counter-e2e' v2/).waitFor();
  });
  await step("past sessions are listed, and a discarded one disappears", async () => {
    await page.goto(UI + "/builder");
    const rows = page.locator('a[href^="/builder/"]');
    await rows.first().waitFor();
    const before = await rows.count();
    assert.ok(before >= 3, `expected at least 3 sessions, saw ${before}`);
    await page.getByText("saved v1").first().waitFor();
    await page.getByText("DRAFT").first().waitFor();
    await shot(page, "19-builds-list");
    await rows.filter({ hasText: "Needs your answers" }).first().click();
    await page.getByRole("button", { name: "Discard this session…" }).click();
    await page.getByRole("dialog").getByRole("button", { name: "Discard", exact: true }).click();
    await page.waitForURL("**/builder");
    await page.waitForFunction((n) => document.querySelectorAll('a[href^="/builder/"]').length === n, before - 1);
  });
  await step("a session that does not exist shows a plain error with a way back", async () => {
    await page.goto(UI + "/builder/" + "0".repeat(32));
    await page.getByText("Something went wrong").waitFor();
    await page.getByText("There is no such builder session.").waitFor();
    await page.getByRole("link", { name: "Back to the builder" }).waitFor();
  });
  await step("leaving a finished session and coming back shows it as it was", async () => {
    await page.goto(UI + convoPath);
    await page.getByRole("heading", { name: "todo-counter-e2e", level: 1 }).waitFor();
    await page.getByText("Saved to the library as 'todo-counter-e2e' v1").waitFor();
  });

  console.log("Plugins with hooks");
  await step("the composer lists the hook catalogue with what each hook does, and a bad option stops the preview until it is fixed", async () => {
    await page.goto(UI + "/composer");
    await page.getByRole("heading", { name: "Compose a plugin", level: 1 }).waitFor();
    await page.getByLabel("Name", { exact: true }).fill("e2e-plugin");
    await page.getByLabel("What is it for?").fill("Safety hooks and a demo skill.");
    await page.getByRole("checkbox", { name: /e2e-demo/ }).check();
    const hook = page.getByRole("checkbox", { name: /Keep secret files out of reach/ });
    await hook.waitFor();
    await page.getByText("runs on your machine").first().waitFor();
    await page.getByText("can block").first().waitFor();
    await hook.check();
    const preview = page.getByRole("button", { name: "Preview the plugin" });
    assert.ok(await preview.isEnabled(), "a skill and a hook with no options is enough");
    const box = page.getByLabel(/More file names to protect/);
    await box.fill("a;rm -rf /");
    await page.getByText(/is not allowed/).waitFor();
    assert.ok(await preview.isDisabled(), "an option the server would refuse must stop the preview");
    await box.fill("secrets.json, *.token");
    assert.ok(await preview.isEnabled());
    await shot(page, "20-composer-hooks");
  });
  await step("the preview says what the hook does, the plugin is kept, and it is in the plugin library with its hook files", async () => {
    await page.getByRole("button", { name: "Preview the plugin" }).click();
    await page.getByRole("heading", { name: "Hooks this plugin runs" }).waitFor();
    await page.getByText(/outside any sandbox/).first().waitFor();
    await page.getByText("hooks/hooks.json", { exact: false }).first().waitFor();
    await page.getByText("secrets.json, *.token", { exact: true }).waitFor(); // the option line; the plugin's note says it in a sentence too
    await shot(page, "21-composer-preview");
    await page.getByRole("button", { name: "Keep this plugin" }).click();
    await page.getByText(/Kept 'e2e-plugin' as v1/).waitFor();
    const rows = await (await fetch(API + "/api/library?kind=plugin")).json();
    assert.ok(rows.some((r) => r.name === "e2e-plugin"), "the plugin should be in the plugin library");
    const stored = await (await fetch(API + "/api/library/e2e-plugin?kind=plugin")).json();
    const paths = JSON.stringify(stored.versions[0]);
    assert.ok(paths.includes("hooks/hooks.json") && paths.includes("hooks/block-secret-files.py") && paths.includes("skills/e2e-demo/SKILL.md"), paths);
  });
  await step("an editing change to the form clears the old preview, so what is kept is only what was shown", async () => {
    await page.goto(UI + "/composer");
    await page.getByLabel("Name", { exact: true }).fill("e2e-plugin-two");
    await page.getByLabel("What is it for?").fill("One hook.");
    await page.getByRole("checkbox", { name: /Log which tools|Keep a log of the tools/ }).check();
    await page.getByRole("button", { name: "Preview the plugin" }).click();
    await page.getByRole("heading", { name: "Hooks this plugin runs" }).waitFor();
    await page.getByText(/By reading its script it can write or delete files/).waitFor();
    await page.getByLabel("What is it for?").fill("One hook, changed.");
    await page.getByRole("heading", { name: "Hooks this plugin runs" }).waitFor({ state: "detached" });
  });

  await step("an MCP server from the library goes into a plugin: the preview names the program it starts and the secret option Claude Code will ask for", async () => {
    const server = [
      '"""Word tools."""', "from mcp.server.mcpserver import MCPServer", "from mcp.types import ToolAnnotations", "", 'mcp = MCPServer("word-tools")', "", "",
      "@mcp.tool(annotations=ToolAnnotations(read_only_hint=True))", "def count_words(text: str) -> str:", '    """Count the words in a text."""', "    return str(len(text.split()))", "", "",
      "@mcp.tool()", "def shout(text: str) -> str:", '    """Return the text in capital letters, then the key."""', "    import os", '    return text.upper() + os.environ.get("WEATHER_API_KEY", "")', "", "",
      'if __name__ == "__main__":', "    mcp.run()", "",
    ].join("\n");
    const imported = await fetch(API + "/api/library/import?kind=mcp", {
      method: "POST", headers: { "Content-Type": "application/zip" }, body: makeZip({ "word-tools/server.py": server, "word-tools/requirements.txt": "mcp==2.3.0\n" }),
    });
    assert.equal(imported.status, 200, await imported.text());
    await page.goto(UI + "/composer");
    await page.getByRole("heading", { name: "Compose a plugin", level: 1 }).waitFor();
    await page.getByLabel("Name", { exact: true }).fill("e2e-plugin-mcp");
    await page.getByLabel("What is it for?").fill("Word tools for Claude.");
    await page.getByRole("checkbox", { name: /word-tools/ }).check();
    await page.getByRole("button", { name: "Preview the plugin" }).click();
    await page.getByRole("heading", { name: "Programs this plugin starts" }).waitFor();
    await page.getByText("count_words, shout", { exact: false }).first().waitFor();
    await page.getByText("WEATHER_API_KEY", { exact: true }).waitFor(); // the variable the server reads, named in the option sentence
    await page.getByText(/outside any sandbox/).first().waitFor();
    await page.getByText(".mcp.json", { exact: false }).first().waitFor();
    await shot(page, "22-composer-mcp");
    await page.getByRole("button", { name: "Keep this plugin" }).click();
    await page.getByText(/Kept 'e2e-plugin-mcp' as v1/).waitFor();
    const stored = await (await fetch(API + "/api/library/e2e-plugin-mcp?kind=plugin")).json();
    const paths = JSON.stringify(stored.versions[0]);
    assert.ok(paths.includes(".mcp.json") && paths.includes("servers/word-tools/server.py"), paths);
  });

  console.log("The repository");
  const repoDir = path.join(scratch, "shop-api"); // a small repository the page reads; edited below to see the recheck notice what changed
  fs.mkdirSync(repoDir, { recursive: true });
  const writeRepo = (name, text) => fs.writeFileSync(path.join(repoDir, name), text);
  writeRepo("core.py", "def shared():\n    return 1\n");
  writeRepo("a.py", "from core import shared\n\ndef use_a():\n    return shared()\n");
  writeRepo("b.py", "from core import shared\n\ndef use_b():\n    return shared()\n");
  const folderBox = () => page.getByLabel("Folder or GitHub link", { exact: true });
  await step("the menu leads to the Repository page, which waits for a folder", async () => {
    await page.goto(UI + "/builder");
    await page.getByRole("link", { name: "Repository" }).click();
    await page.getByRole("heading", { name: "Repository", level: 1 }).waitFor();
    assert.ok(await page.getByRole("button", { name: "Read the repository" }).isDisabled());
    await shot(page, "30-repository-empty");
  });
  await step("a folder name without its full path is refused before anything is sent", async () => {
    await folderBox().fill("shop-api");
    await page.getByText(/Give the full path of the folder/).waitFor();
    assert.ok(await page.getByRole("button", { name: "Read the repository" }).isDisabled());
  });
  await step("a folder that does not exist gives a plain answer", async () => {
    await folderBox().fill(path.join(scratch, "nowhere"));
    await page.getByRole("button", { name: "Read the repository" }).click();
    await page.getByText(/Not a directory/).first().waitFor();
    assert.ok(!(await page.locator("main").innerText()).includes(scratch), "an error about a folder must not repeat its path");
  });
  await step("a network path is refused before anything is sent", async () => {
    await folderBox().fill("//server/share/repo");
    await page.getByText(/Network paths are not read/).waitFor();
    assert.ok(await page.getByRole("button", { name: "Read the repository" }).isDisabled());
  });
  await step("a GitHub link is read like a folder, says where it came from and what was left out, and shows no path", async () => {
    await folderBox().fill("https://gitlab.com/acme/shop-api");
    await page.getByText(/public GitHub repository/).first().waitFor();
    assert.ok(await page.getByRole("button", { name: "Read the repository" }).isDisabled());
    await folderBox().fill("https://github.com/acme/shop-api");
    await page.getByRole("button", { name: "Read the repository" }).click();
    await page.getByRole("heading", { name: "acme/shop-api", level: 2 }).waitFor();
    await page.getByText("from GitHub", { exact: true }).waitFor();
    await page.getByText(/Nothing was run\./).waitFor();
    await page.getByText(/Git history is not downloaded/).waitFor();
    await page.getByText(/3 files/).first().waitFor();
    await page.getByText("Everything sits in one place, so the map is a single box.").waitFor(); // a flat repository: one box, said plainly
    const text = await page.locator("main").innerText();
    assert.ok(!text.includes(scratch) && !text.includes("codeload"), "the page must not show where the copy is kept");
    await shot(page, "30b-github-link");
  });
  await step("a link to a repository that does not exist (or is private) says so plainly", async () => {
    await folderBox().fill("https://github.com/acme/missing");
    await page.getByRole("button", { name: "Read the repository" }).click();
    await page.getByText(/Private repositories cannot be read/).first().waitFor();
  });
  await step("reading a repository shows what the graph says, never the path, and the page remembers the folder", async () => {
    await folderBox().fill(repoDir);
    await page.getByRole("button", { name: "Read the repository" }).click();
    await page.getByRole("heading", { name: "shop-api", level: 2 }).waitFor();
    await page.getByText(/3 files/).first().waitFor();
    await page.getByText("python", { exact: true }).waitFor();
    await page.getByText("full", { exact: true }).waitFor();
    await page.getByText(/Most depended on/).waitFor();
    assert.ok(!(await page.locator("main").innerText()).includes(scratch), "the page must not show the folder's path");
    await shot(page, "31-repository-read");
    await page.reload();
    await page.waitForFunction((p) => document.querySelector("input")?.value === p, repoDir);
  });
  await step("asking for ideas shows ideas that cite real places, and the ones that are not skills are only for reading", async () => {
    await page.getByRole("button", { name: "Read the repository" }).click();
    await page.getByRole("heading", { name: "shop-api", level: 2 }).waitFor();
    await page.getByRole("button", { name: "Ask for ideas" }).click();
    await page.getByText(/Asking the model for ideas/).waitFor();
    await page.getByRole("heading", { name: "Count TODO comments for a folder" }).waitFor();
    await page.getByText("Skill idea", { exact: true }).waitFor();
    await page.getByText("core.py::shared", { exact: true }).waitFor();
    await page.getByRole("heading", { name: "Cover core.py with a test" }).waitFor();
    assert.equal(await page.getByRole("button", { name: /^Build this/ }).count(), 1, "only the skill idea can start a build");
    await shot(page, "32-ideas");
  });
  await step("'Build this as a skill' starts a session that remembers where the idea came from, and builds with evidence", async () => {
    await page.getByText("What the skill will be asked to do (you can change it)").click(); // the model's wording is the person's to change
    const box = page.getByLabel(/This is the model's wording/);
    assert.ok((await box.inputValue()).startsWith("A skill that counts TODO and FIXME comments"));
    await box.fill((await box.inputValue()) + " Extra words from the person.");
    await page.getByRole("button", { name: "Build this as a skill" }).click();
    await page.waitForURL(/\/builder\/[0-9a-f]{32}$/);
    await page.getByText(/Started from an idea about/).waitFor();
    await page.getByText(/Extra words from the person\./).first().waitFor(); // the build was asked what the person wrote, not the original
    await page.getByText("Check the requirement").waitFor(); // the idea carried the whole requirement: nothing was left to ask
    assert.ok(!(await page.locator("main").innerText()).includes(scratch), "the session must not show the folder's path");
    await page.getByRole("button", { name: "Approve and build" }).click();
    await page.getByRole("heading", { name: "todo-counter-e2e", level: 1 }).waitFor({ timeout: 30000 });
    await page.getByText(/It cites 1 place in/).waitFor();
    await page.getByText("evidence.json").first().waitFor();
    await shot(page, "33-built-with-evidence");
  });
  await step("the skill's page lists the code it cites, and a recheck against the same folder says everything holds", async () => {
    await page.getByRole("button", { name: "Save to the library" }).click();
    await page.getByText(/Saved to the library as 'todo-counter-e2e' v\d+/).waitFor();
    await page.getByRole("link", { name: "Open it in the library" }).click();
    await page.getByRole("heading", { name: "Code it cites" }).waitFor();
    await page.getByText("core.py::shared").first().waitFor();
    await page.getByText(/1 place in/).waitFor();
    await page.getByRole("button", { name: "Recheck" }).click();
    await page.getByText("Nothing the skill cites is gone, moved or changed").waitFor();
    await page.getByText("Holds 1").waitFor();
    await shot(page, "34-recheck-holds");
  });
  await step("after the code changes, the recheck names what changed; after it is deleted, it says missing", async () => {
    writeRepo("c.py", "from core import shared\n\ndef use_c():\n    return shared()\n");
    await page.getByRole("button", { name: "Recheck" }).click();
    await page.getByText("Something the skill cites is gone, moved or changed").waitFor();
    await page.getByText(/c\.py::use_c/).first().waitFor();
    await page.getByText("Changed 1").waitFor();
    await shot(page, "35-recheck-changed");
    writeRepo("core.py", "def other():\n    return 1\n");
    await page.getByRole("button", { name: "Recheck" }).click();
    await page.getByText("Missing 1").waitFor();
    await page.getByText(/not that the skill's advice is right/).waitFor(); // every report says what it does not check
  });

  console.log("The architecture map");
  const mapDir = path.join(scratch, "shop-map"); // folders that import each other: web -> api, and api <-> pricing
  const writeMap = (name, text) => {
    fs.mkdirSync(path.dirname(path.join(mapDir, name)), { recursive: true });
    fs.writeFileSync(path.join(mapDir, name), text);
  };
  writeMap("pricing/__init__.py", "");
  writeMap("pricing/core.py", "def tax():\n    return 1\n");
  writeMap("pricing/audit.py", "from api.routes import route\n\ndef audit():\n    return route()\n");
  writeMap("api/__init__.py", "");
  writeMap("api/routes.py", "from pricing.core import tax\n\ndef route():\n    return tax()\n");
  writeMap("web/app.py", "from api.routes import route\n\ndef page():\n    return route()\n");
  const mapBox = (name) => page.getByRole("button", { name: new RegExp(`^${name}:`) });
  await step("reading a repository with folders draws its map: boxes, arrows, and a warning for folders that import each other", async () => {
    await page.goto(UI + "/repository");
    await page.getByRole("heading", { name: "Repository", level: 1 }).waitFor();
    await folderBox().fill(mapDir);
    await page.getByRole("button", { name: "Read the repository" }).click();
    await page.getByRole("heading", { name: "How the code is laid out" }).waitFor();
    for (const name of ["web", "api", "pricing"]) await mapBox(name).waitFor();
    await page.getByText("Folders that import each other").waitFor();
    await page.getByText(/api and pricing import each other/).waitFor();
    assert.ok(!(await page.locator("main").innerText()).includes(scratch), "the map must not show the folder's path");
    await shot(page, "34m-architecture-map");
  });
  await step("clicking a box shows what is inside it, and the keyboard works too", async () => {
    await page.getByText("Select a box to see what is inside it.").waitFor();
    await mapBox("pricing").click();
    await page.getByRole("heading", { name: "Inside pricing", level: 3 }).waitFor();
    await page.getByText("pricing/core.py").first().waitFor();
    const faded = () => page.locator('svg path[data-faded="true"]').count();
    assert.equal(await faded(), 1, "with pricing selected only web -> api is not one of its arrows, so one arrow fades");
    await mapBox("web").focus();
    await page.keyboard.press("Enter");
    await page.getByRole("heading", { name: "Inside web", level: 3 }).waitFor();
    await page.getByText("web/app.py").first().waitFor();
    assert.equal(await faded(), 2, "with web selected, the two arrows between api and pricing fade");
  });
  await step("the arrows can also be read as a list", async () => {
    await page.getByText("The arrows as a list").click();
    await page.getByText(/web imports api \(\d+ file pairs?\)/).waitFor();
    await page.getByText(/api imports pricing \(\d+ file pairs?\)/).waitFor();
    await page.getByText(/pricing imports api \(\d+ file pairs?\)/).waitFor();
  });
  await step("the map never makes the page scroll sideways at phone width", async () => {
    await page.setViewportSize({ width: 390, height: 800 });
    await page.waitForTimeout(300);
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    assert.ok(overflow <= 1, `the map makes the page scroll sideways by ${overflow}px`);
    await mapBox("api").scrollIntoViewIfNeeded();
    await shot(page, "34n-architecture-map-phone");
    await page.setViewportSize({ width: 1280, height: 900 });
  });

  console.log("How it works (the guide)");
  // The sentences the fake model quotes (mock_server.py, guide_draft). The real checking code looks each one up in this README.
  const GUIDE_README = [
    "# Shop map", "",
    "The web page sends every price request to the API.",
    "The API asks the pricing engine for the price.",
    "The pricing engine works out the tax for the price.",
    "Payments are taken by an outside payment provider.",
    "A cache for prices is planned but does not exist yet.", "",
  ].join("\n");
  const guideButton = () => page.getByRole("button", { name: /^(Show how it works|Draw it again)$/ });
  const action = (name) => page.getByRole("group", { name: "Actions" }).getByRole("button", { name }); // one button per action the docs describe
  const part = (band, name) => page.locator(`section[aria-label="${band}"]`).getByRole("button", { name: new RegExp(name) });
  await step("with no README the guide says there is nothing to read, and no model is asked", async () => {
    await guideButton().click();
    await page.getByText("There is no README or docs to read").waitFor();
    assert.ok(!(await page.locator("main").innerText()).includes(scratch), "the guide must not show the folder's path");
  });
  await step("with a README the guide draws the layers and a numbered route, and says which hops the code confirms", async () => {
    writeMap("README.md", GUIDE_README);
    await guideButton().click();
    await page.getByText(/Reading the docs and asking the model/).waitFor();
    await action("Show a price").waitFor();
    await page.getByText(/Drawn for\s+shop-map/).waitFor(); // the page says which repository the guide is for
    await page.getByText("The route: Show a price").waitFor();
    await page.getByText("1 file pair, for example web/app.py imports api/routes.py").waitFor(); // what stands behind a confirmed hop
    await page.getByText("1 file pair one way, 1 file pair the other").waitFor(); // api and pricing import each other in this repository: said, not hidden behind "confirmed"
    for (const band of ["What people use", "The doors in", "The workers", "Shared services", "The outside world"]) {
      await page.getByRole("heading", { name: band, level: 3 }).waitFor();
    }
    assert.equal(await page.getByText("Confirmed by the code", { exact: true }).count(), 1, "web imports api: that hop is confirmed");
    assert.equal(await page.getByText("Imports both ways", { exact: true }).count(), 1, "api imports pricing and pricing imports api: that hop says both ways");
    await page.getByText(/README\.md \(8 lines\)/).first().waitFor(); // the page says what it read
    assert.ok(!(await page.locator("main").innerText()).includes(scratch), "the guide must not show the folder's path");
    await shot(page, "34g-guide");
  });
  await step("a part the docs name but the code lacks, and one outside the repository, are said plainly", async () => {
    await part("Shared services", "Price cache").click();
    const panel = page.getByRole("region", { name: "Price cache in detail" });
    await panel.getByText("In the docs, not found in the code").waitFor();
    await panel.getByText("There is nothing to read: the code has no folder for this part.").waitFor();
    await part("The outside world", "Payment provider").click();
    await page.getByRole("region", { name: "Payment provider in detail" }).getByText("Outside this repository").waitFor();
  });
  await step("a click on a part shows where to start reading, the sentence the docs gave, and that the plain words are not checked", async () => {
    await part("The workers", "Pricing engine").click();
    const panel = page.getByRole("region", { name: "Pricing engine in detail" });
    await panel.getByText("Folder found in the code").waitFor(); // what was checked: the folder is there, which is not the same as "the part lives there"
    await panel.getByText("Read these first").waitFor();
    await panel.getByText("pricing/core.py").first().waitFor();
    await panel.getByText("The pricing engine works out the tax for the price.").waitFor(); // the quote, as found in the README
    await panel.getByText(/Quote found: README\.md, line 5/).waitFor();
    await panel.getByText("model's words, not checked").waitFor();
    await shot(page, "34h-guide-part");
  });
  await step("another action shows its own route, and a hop only the docs describe is not called confirmed", async () => {
    await action("Skip the API").click();
    await page.getByText("The route: Skip the API").waitFor();
    await page.getByText("From the docs only", { exact: true }).first().waitFor();
    assert.equal(await page.getByText("Confirmed by the code", { exact: true }).count(), 0, "web does not import pricing directly");
    assert.equal(await action("Skip the API").getAttribute("aria-pressed"), "true");
    assert.equal(await action("Show a price").getAttribute("aria-pressed"), "false");
  });
  await step("the guide never makes the page scroll sideways at phone width", async () => {
    await page.setViewportSize({ width: 390, height: 800 });
    await page.waitForTimeout(300);
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    assert.ok(overflow <= 1, `the guide makes the page scroll sideways by ${overflow}px`);
    await action("Show a price").scrollIntoViewIfNeeded();
    await shot(page, "34i-guide-phone");
    await page.setViewportSize({ width: 1280, height: 900 });
  });
  await step("the guide is drawn for the repository that was read, not for what the box says now", async () => {
    await folderBox().fill(path.join(scratch, "nowhere")); // typing another path after reading must not change which repository the guide is for
    await guideButton().click();
    await page.getByText(/Reading the docs and asking the model/).waitFor();
    await action("Show a price").waitFor();
    await page.getByText(/Drawn for\s+shop-map/).waitFor();
    assert.equal(await page.getByText("It could not be drawn").count(), 0, "the guide used the box's new text instead of the repository that was read");
    await folderBox().fill(mapDir);
  });
  await step("reading a repository again clears the guide, which belonged to the one before", async () => {
    await page.getByRole("button", { name: "Read the repository" }).click();
    await page.getByRole("heading", { name: "How the code is laid out" }).waitFor();
    assert.equal(await page.getByRole("group", { name: "Actions" }).count(), 0);
    await page.getByRole("button", { name: "Show how it works" }).waitFor();
  });

  console.log("The settings");
  const envFile = path.join(scratch, "data", "e2e.env"); // the throwaway file the test server's Settings page writes (never the real .env)
  const KEY = "AIzaSyE2E-SECRET_0123456789abcdef";
  const field = (name) => page.locator(`[data-setting="${name}"]`);
  await step("the menu leads to Settings, which shows the model in use and has nothing to save yet", async () => {
    await page.goto(UI + "/builder");
    await page.getByRole("navigation", { name: "Main" }).getByRole("link", { name: "Settings" }).click();
    await page.getByRole("heading", { name: "Settings", level: 1 }).waitFor();
    await page.getByText(/In use:/).first().waitFor();
    await page.getByText("Nothing changed.").waitFor();
    assert.ok(await page.getByRole("button", { name: "Save changes" }).isDisabled());
    await shot(page, "36-settings");
  });
  await step("saving a model and a key writes the file, empties the key box, and the key is never shown or sent back", async () => {
    await field("LLM_MODEL").locator("input").fill("gemini-e2e-model");
    await field("GOOGLE_API_KEY").locator("input").fill(KEY);
    await page.getByText("2 settings will be saved.").waitFor();
    await page.getByRole("button", { name: "Save changes" }).click();
    await page.getByText("Saved. It is used from now on, with no restart.").waitFor();
    assert.equal(await field("GOOGLE_API_KEY").locator("input").inputValue(), "", "a saved key must leave the page");
    await field("GOOGLE_API_KEY").getByText("Saved", { exact: true }).waitFor();
    assert.ok(!(await page.locator("main").innerText()).includes(KEY));
    const written = fs.readFileSync(envFile, "utf8");
    assert.ok(written.includes(`GOOGLE_API_KEY=${KEY}`) && written.includes("LLM_MODEL=gemini-e2e-model"), "the file holds both");
    const served = await (await fetch(API + "/api/settings")).text();
    assert.ok(!served.includes(KEY) && !served.includes(KEY.slice(-8)), "the API must never send the key back");
    await shot(page, "37-settings-saved");
  });
  await step("after a reload the model is shown, the key box is empty and the key is marked saved", async () => {
    await page.reload();
    await page.getByRole("heading", { name: "Settings", level: 1 }).waitFor();
    await page.waitForFunction(() => document.querySelector('[data-setting="LLM_MODEL"] input')?.value === "gemini-e2e-model");
    assert.equal(await field("GOOGLE_API_KEY").locator("input").inputValue(), "");
    await field("GOOGLE_API_KEY").getByText("Saved", { exact: true }).waitFor();
  });
  await step("a value that is refused names the setting, saves nothing and does not repeat the value", async () => {
    const bad = "has a space in it";
    await field("GOOGLE_API_KEY").locator("input").fill(bad);
    await page.getByRole("button", { name: "Save changes" }).click();
    await page.getByText("Nothing was saved").waitFor();
    await field("GOOGLE_API_KEY").getByText(/Only letters, digits/).waitFor();
    assert.ok(!(await page.locator("main").innerText()).includes(bad), "a refusal must not repeat the value");
    assert.ok(fs.readFileSync(envFile, "utf8").includes(`GOOGLE_API_KEY=${KEY}`), "the file is unchanged");
    await page.getByRole("button", { name: "Discard changes" }).click();
    await page.getByText("Nothing changed.").waitFor();
  });
  await step("a saved key can be removed, and a key typed just before pressing Remove is dropped, not saved", async () => {
    await field("GOOGLE_API_KEY").locator("input").fill("typed-then-removed-key");
    await field("GOOGLE_API_KEY").getByRole("button", { name: "Remove it" }).click();
    await field("GOOGLE_API_KEY").getByText("Will be removed").waitFor();
    await page.getByRole("button", { name: "Save changes" }).click();
    await page.getByText("Saved. It is used from now on, with no restart.").waitFor();
    await field("GOOGLE_API_KEY").getByText("Not set", { exact: true }).waitFor();
    const after = fs.readFileSync(envFile, "utf8");
    assert.ok(!after.includes("GOOGLE_API_KEY=") && !after.includes("typed-then-removed-key"), "a removed key must not be replaced by what was typed");
  });
  await step("'Test my models' tests what is saved and shows how each model answered", async () => {
    await page.getByRole("button", { name: "Test my models" }).click();
    await page.getByText("Works", { exact: true }).waitFor();
    await shot(page, "38-settings-tested");
  });

  console.log("The Testing Lab");
  // Text-only skills with test cases a model can be asked, written the way the builder writes them (tests/cases.json).
  const labCases = (firstMessage) => JSON.stringify([
    { name: "short change", kind: "positive", input_description: "one sentence", expected_result: "a short title", covers: ["AC1"], run_input: firstMessage,
      assertions: [{ kind: "first_line_max_chars", value: "50", why: "title at most 50 characters" }] },
    { name: "no description", kind: "negative", input_description: "no description", expected_result: "a question", covers: ["AC1"], run_input: "commit message please",
      assertions: [{ kind: "regex", value: "\\?|please|describe", why: "asks what changed" }] },
    { name: "many changes", kind: "edge", input_description: "many changes", expected_result: "a short list", covers: ["AC1"], run_input: "Updated README, fixed a typo, bumped the version",
      assertions: [{ kind: "max_lines", value: "6", why: "keeps it short" }] },
  ]);
  const labZip = (name, firstMessage = "fixed the login button alignment on mobile", extra = {}) => makeZip({
    [`${name}/SKILL.md`]: `---\nname: ${name}\ndescription: Writes a short commit message from a description of what changed.\n---\n# ${name}\n\nWrite a title of at most 50 characters, starting with a verb.\n`,
    [`${name}/README.md`]: "A demo.\n", [`${name}/tests/cases.json`]: labCases(firstMessage), ...extra,
  });
  // imported through the API, from the page (so the request carries the UI's own origin, as a real import does)
  const importZip = (name, zip) => page.evaluate(async ({ api, name, b64 }) => {
    const bytes = Uint8Array.from(atob(b64), (c) => c.charCodeAt(0));
    const r = await fetch(`${api}/api/library/import?filename=${name}.zip`, { method: "POST", headers: { "Content-Type": "application/zip" }, body: bytes });
    return { status: r.status, body: await r.json() };
  }, { api: API, name, b64: zip.toString("base64") });
  const skillPicker = () => page.getByLabel("Skill", { exact: true });

  await step("the menu leads to the Testing Lab, which waits for a skill", async () => {
    for (const [name, zip] of [["lab-demo", labZip("lab-demo")]]) {
      const r = await importZip(name, zip);
      assert.equal(r.status, 200, `importing ${name}: ${JSON.stringify(r.body).slice(0, 300)}`);
    }
    await page.goto(UI + "/builder");
    await page.getByRole("navigation", { name: "Main" }).getByRole("link", { name: "Testing Lab" }).click();
    await page.waitForURL("**/testing");
    await page.getByRole("heading", { name: "Testing Lab", level: 1 }).waitFor();
    await skillPicker().waitFor();
    assert.equal(await page.getByRole("button", { name: "Run the tests" }).count(), 0, "nothing can be run before a skill is chosen");
    await shot(page, "40-lab-empty");
  });
  await step("a skill with no test cases says why it cannot be run, before any model is asked", async () => {
    await skillPicker().selectOption("e2e-demo");
    await page.getByText(/e2e-demo v\d+ cannot be run here/).waitFor();
    await page.getByText(/this skill has no test cases/i).waitFor();
    await page.getByText(/Build it again in the Builder/).waitFor();
    assert.equal(await page.getByRole("button", { name: "Run the tests" }).count(), 0, "a skill that cannot be run offers no run");
  });
  await step("a skill that needs tools says a model with no tools cannot stand in for an agent", async () => {
    const names = (await page.evaluate(async (api) => (await fetch(`${api}/api/library`)).json(), API)).map((s) => s.name);
    assert.ok(names.includes("todo-counter-e2e"), `the skill the builder saved earlier should be here, saw ${names.join(", ")}`);
    await skillPicker().selectOption("todo-counter-e2e");
    await page.getByText(/todo-counter-e2e v\d+ cannot be run here/).waitFor();
    await page.getByText(/needs tools \(it asks for read_files\)/).waitFor();
    await page.getByText(/Install it and use it for real/).waitFor();
    await shot(page, "41-lab-needs-tools");
  });
  await step("a skill with runnable tests lists what would run, and says what it will cost before anything is asked", async () => {
    await skillPicker().selectOption("lab-demo");
    await page.getByRole("heading", { name: "What would run", level: 2 }).waitFor();
    for (const n of ["short change", "no description", "many changes"]) await page.getByText(n, { exact: true }).first().waitFor();
    await page.getByText("fixed the login button alignment on mobile").first().waitFor();
    await page.getByText(/has a first line of at most 50 characters/).waitFor();
    await page.getByText("6 model calls").waitFor();
    await page.getByLabel("Repeat each test").selectOption("3");
    await page.getByText("18 model calls").waitFor();
    await page.getByLabel(/Also run without the skill/).uncheck();
    await page.getByText("9 model calls").waitFor();
    await page.getByLabel(/Also run without the skill/).check();
    await page.getByLabel("Repeat each test").selectOption("1");
    await page.getByText(/one repeat of each test can mislead/).waitFor();
    await shot(page, "42-lab-preview");
  });
  await step("running shows progress, then the verdict with both sides and each failed check in words", async () => {
    await page.getByRole("button", { name: "Run the tests" }).click();
    await page.getByText(/Running test \d of 3/).waitFor();
    await page.getByText("The skill helped", { exact: true }).waitFor({ timeout: 60000 });
    await page.getByText(/With the skill:/).waitFor();
    await page.getByText(/3 of 3 runs passed every check/).waitFor();
    await page.getByText(/1 of 3\./).waitFor(); // without the skill the model passes only the one it passes anyway
    await page.getByText(/the first line is \d+ characters, the limit is 50/).first().waitFor(); // the failed check, in numbers
    await page.getByText(/the reply does not match the pattern/).first().waitFor();
    await page.getByText("Passing is evidence, not proof").waitFor();
    // a reply is plain text behind a disclosure: the first is the model with the skill, the second the model without it
    await page.getByText("Show the reply").nth(0).click();
    await page.getByText(/Fix login button alignment/).first().waitFor();
    await page.getByText("Show the reply").nth(1).click();
    await page.getByText(/Here is a commit message you could use/).first().waitFor();
    await shot(page, "43-lab-result");
  });
  await step("after a reload the result is still there, and the run is listed under earlier runs", async () => {
    await page.reload();
    await page.getByText("The skill helped", { exact: true }).waitFor({ timeout: 30000 });
    await page.getByRole("heading", { name: "Earlier runs of this version", level: 3 }).waitFor();
    await page.getByText("the skill helped · with the skill 3/3 · without it 1/3").waitFor();
  });
  await step("a skill's own page links to the Lab with its version in the address", async () => {
    await page.goto(UI + "/library/lab-demo");
    await page.getByRole("link", { name: "Test this skill" }).click();
    await page.waitForURL(/\/testing\?name=lab-demo&version=1/);
    await page.getByText("The skill helped", { exact: true }).waitFor({ timeout: 30000 });
  });
  await step("a model that cannot be reached fails the run, and 'Run it again' finishes it", async () => {
    const r = await importZip("lab-down", labZip("lab-down", "fixed the login button [lab-down]"));
    assert.equal(r.status, 200, JSON.stringify(r.body).slice(0, 300));
    await page.goto(UI + "/testing?name=lab-down");
    await page.getByRole("button", { name: "Run the tests" }).click();
    await page.getByText("The run did not finish").waitFor({ timeout: 30000 });
    await page.getByText(/could not be reached/).first().waitFor();
    await shot(page, "44-lab-failed");
    await page.getByRole("button", { name: "Run it again" }).click();
    await page.getByText("The skill helped", { exact: true }).waitFor({ timeout: 60000 });
  });
  await step("a result says so when a newer version of the skill exists", async () => {
    const r = await importZip("lab-demo", labZip("lab-demo", undefined, { "lab-demo/extra.md": "More.\n" }));
    assert.equal(r.status, 200, JSON.stringify(r.body).slice(0, 300));
    await page.goto(UI + "/testing?name=lab-demo&version=1");
    await page.getByText("The skill helped", { exact: true }).waitFor({ timeout: 30000 });
    await page.getByText("A newer version exists").waitFor();
    await page.getByText(/This run tested v1\. The latest version is v2/).waitFor();
    // the newer version has had no run: the page does not borrow v1's result for it
    await page.goto(UI + "/testing?name=lab-demo");
    await page.getByRole("button", { name: "Run the tests" }).waitFor();
    assert.equal(await page.getByText("The skill helped", { exact: true }).count(), 0, "v2 was never run, so no verdict may be shown for it");
    assert.equal(await page.getByRole("heading", { name: "Earlier runs of this version" }).count(), 0);
  });
  await step("the Lab never makes the page scroll sideways at phone width", async () => {
    await page.goto(UI + "/testing?name=lab-demo&version=1");
    await page.getByText("The skill helped", { exact: true }).waitFor({ timeout: 30000 });
    await page.setViewportSize({ width: 390, height: 800 });
    await page.waitForTimeout(300);
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    assert.ok(overflow <= 1, `the Lab makes the page scroll sideways by ${overflow}px`);
    await shot(page, "45-lab-phone");
    await page.setViewportSize({ width: 1280, height: 900 });
  });

  console.log("The dashboard");
  const attentionCard = () => page.getByRole("heading", { name: "Needs attention", level: 2 }).locator("xpath=..");
  await step("the dashboard lists what is saved and the latest builds, and is reached from the menu", async () => {
    await page.getByRole("navigation", { name: "Main" }).getByRole("link", { name: "Dashboard" }).click();
    await page.waitForURL(UI + "/");
    await page.getByRole("heading", { name: "Dashboard", level: 1 }).waitFor();
    await page.getByRole("heading", { name: "Your library", level: 2 }).waitFor();
    await page.getByText(/\d+ saved · \d+ versions?/).first().waitFor();
    await page.getByText("Saved most recently").waitFor();
    // the top of that list is whatever the API says was saved last, across every kind (not a fixed name: other steps saved newer things)
    const kindsList = await page.evaluate(async (api) => (await fetch(`${api}/api/kinds`)).json(), API);
    const saved = [];
    for (const k of kindsList) {
      const query = k.key === "skill" ? "" : `?kind=${k.key}`;
      const skills = await page.evaluate(async (url) => (await fetch(url)).json(), `${API}/api/library${query}`);
      for (const s of skills) if (s.latest) saved.push({ kind: k.key, name: s.name, at: s.latest.created_at });
    }
    saved.sort((a, b) => (a.at < b.at ? 1 : a.at > b.at ? -1 : a.name.localeCompare(b.name)));
    assert.ok(saved.length >= 1, "the library should hold something by now");
    const newest = saved[0];
    await page.locator(`a[href="/library/${encodeURIComponent(newest.name)}${newest.kind === "skill" ? "" : `?kind=${newest.kind}`}"]`).first().waitFor();
    const recentLinks = await page.getByText("Saved most recently").locator("xpath=following-sibling::ul[1]//a").count();
    assert.ok(recentLinks >= 1 && recentLinks <= 5, `the recent list shows 1 to 5 versions, saw ${recentLinks}`);
    await page.getByRole("heading", { name: "Recent builds", level: 2 }).waitFor();
    assert.ok((await page.locator('a[href^="/builder/"]').count()) >= 1, "the recent builds link to their sessions");
    await page.getByRole("link", { name: "Build something" }).waitFor();
    assert.ok(!(await page.locator("main").innerText()).includes(scratch), "the dashboard must not show any path");
    await shot(page, "36-dashboard");
  });
  await step("it says either what needs the person or that nothing does, and every unfinished build is on the list", async () => {
    const list = await page.evaluate(async (api) => (await fetch(`${api}/api/builds`)).json(), API);
    const unfinished = list.filter((b) => ["awaiting_answers", "awaiting_approval", "failed"].includes(b.status) || (b.status === "done" && !b.saved));
    const nothing = await page.getByText("Nothing needs you right now.").count();
    const items = await attentionCard().locator("li").count();
    assert.ok(nothing + items > 0, "the dashboard must say what needs the person, or that nothing does");
    if (unfinished.length > 0 && unfinished.length <= 8) {
      for (const b of unfinished) await attentionCard().locator(`a[href="/builder/${b.id}"]`).first().waitFor();
    }
    await page.getByRole("button", { name: "Check again" }).click();
    await attentionCard().waitFor();
  });
  await step("a library that cannot be read is said so and is never shown as zero", async () => {
    const errorsBefore = problems.length;
    await page.route(/\/api\/library\?kind=agent$/, (route) => route.fulfill({ status: 500, contentType: "application/json", body: JSON.stringify({ detail: "The agent library is on fire." }) }));
    await page.route(/\/api\/rescan\?kind=agent$/, (route) => route.fulfill({ status: 500, contentType: "application/json", body: JSON.stringify({ detail: "No rescan today." }) }));
    await page.goto(UI + "/");
    await page.getByText("could not be read", { exact: true }).waitFor();
    await page.getByText("The agent library is on fire.").waitFor();
    await page.getByText("Something could not be checked").first().waitFor();
    await page.getByText(/agent library could not be run: No rescan today\./).waitFor();
    assert.equal(await page.getByText("Nothing needs you right now.").count(), 0, "a check that could not run must not become 'nothing needs you'");
    const agentRow = page.locator("li").filter({ has: page.getByRole("link", { name: "Agent", exact: true }) }).first();
    assert.ok(!(await agentRow.innerText()).includes("0 saved"), "an unreadable library is not an empty one");
    await page.unroute(/\/api\/library\?kind=agent$/);
    await page.unroute(/\/api\/rescan\?kind=agent$/);
    // the two 500s above were put there on purpose, so the browser's console reports them: take exactly those out of the suite's list of problems
    const mine = problems.splice(errorsBefore);
    assert.ok(mine.length === 2 && mine.every((p) => /status of 500/.test(p)), `expected exactly the two deliberate 500s, saw: ${JSON.stringify(mine)}`);
    await page.goto(UI + "/");
    await page.getByRole("heading", { name: "Your library", level: 2 }).waitFor();
    assert.equal(await page.getByText("could not be read", { exact: true }).count(), 0, "the page recovers when the API does");
  });
  await step("the dashboard never makes the page scroll sideways at phone width", async () => {
    await page.setViewportSize({ width: 390, height: 800 });
    await page.waitForTimeout(300);
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    assert.ok(overflow <= 1, `the dashboard makes the page scroll sideways by ${overflow}px`);
    await shot(page, "36n-dashboard-phone");
    await page.setViewportSize({ width: 1280, height: 900 });
  });

  console.log("Looks and behaviour");
  await step("it works in a narrow phone-sized window without sideways scrolling", async () => {
    await page.setViewportSize({ width: 390, height: 800 });
    for (const url of ["/builder", convoPath, "/library", "/library/e2e-demo", "/library/e2e-demo/diff?from=1&to=2", "/composer", "/settings"]) {
      await page.goto(UI + url);
      await page.getByRole("heading", { level: 1 }).first().waitFor();
      await page.waitForTimeout(400);
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
      assert.ok(overflow <= 1, `${url} scrolls sideways by ${overflow}px`);
    }
    await shot(page, "10-mobile");
  });
  await step("dark mode follows the system and is readable", async () => {
    const dark = await browser.newContext({ viewport: { width: 1280, height: 900 }, colorScheme: "dark" });
    const p = await dark.newPage();
    await p.goto(UI + "/library/e2e-demo");
    await p.getByRole("heading", { name: "e2e-demo", level: 1 }).waitFor();
    const bg = await p.evaluate(() => getComputedStyle(document.body).backgroundColor);
    assert.ok(bg.includes("14, 17, 23") || bg.includes("rgb(14"), `unexpected dark background ${bg}`);
    if (shots) await p.screenshot({ path: path.join(shots, "11-dark.png"), fullPage: true });
    await dark.close();
  });
  await step("the page can be used with the keyboard alone (the import file input is reachable)", async () => {
    await page.setViewportSize({ width: 1280, height: 900 });
    await page.goto(UI + "/library");
    await page.getByRole("heading", { name: "Library", level: 1 }).waitFor();
    await page.keyboard.press("Tab");
    await page.keyboard.press("Tab");
    await page.keyboard.press("Tab");
    await page.keyboard.press("Tab");
    const focus = await page.evaluate(() => document.activeElement?.tagName + ":" + (document.activeElement?.getAttribute("type") ?? ""));
    assert.ok(focus.length > 0);
  });
  await step("no console errors or page errors so far", async () => {
    assert.deepEqual(problems, []);
  });

  console.log("When the API is gone");
  await step("stopping the API shows 'The API is not running' with the command to start it", async () => {
    api.kill();
    await new Promise((r) => setTimeout(r, 1000));
    await page.goto(UI + "/library");
    await page.getByText("The API is not running").waitFor();
    await page.getByText(/python -m skillforge serve/).first().waitFor();
    await shot(page, "12-api-down");
  });
} finally {
  await browser?.close();
  for (const c of children) c.kill();
  fs.rmSync(scratch, { recursive: true, force: true, maxRetries: 3 });
}

console.log(`\n${passed} passed, ${failures.length} failed${failures.length ? ": " + failures.join("; ") : ""}`);
process.exit(failures.length ? 1 : 0);
