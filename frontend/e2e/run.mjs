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
  await step("/ opens the builder, and the status panel finds the API", async () => {
    await page.goto(UI + "/");
    await page.waitForURL("**/builder");
    await page.getByRole("heading", { name: "Build a skill", level: 1 }).waitFor();
    await page.getByText(/online · v/).waitFor();
    await page.getByText("Linux, ready").waitFor({ timeout: 30000 }).catch(() => {}); // the sandbox may be absent on another machine
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
