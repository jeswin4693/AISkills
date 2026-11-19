// A MANUAL check, not part of `npm run e2e`: the Builder page in a real browser against the REAL API and a REAL model.
//
//   npm run build && node e2e/live.mjs
//
// It uses the model set up in the repository's .env (the key never leaves the server and is never printed), sends one
// generic sentence to that provider, and saves the result into a throwaway library. It costs a few model calls.
// Same environment variables as run.mjs: SKILLFORGE_PYTHON, E2E_UI_PORT, E2E_API_PORT (build the UI for that API address
// first), E2E_SHOTS for screenshots. Answers to the questions are fixed sentences about a TODO counter; which questions get
// asked depends on the model, so the script answers whatever is asked.
import { spawn } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright-core";

const here = path.dirname(fileURLToPath(import.meta.url));
const frontend = path.resolve(here, "..");
const backend = path.resolve(frontend, "..", "backend");
const python = process.env.SKILLFORGE_PYTHON ?? "python";
const UI_PORT = process.env.E2E_UI_PORT ?? "3000";
const API_PORT = process.env.E2E_API_PORT ?? "8000";
const UI = `http://127.0.0.1:${UI_PORT}`;
const API = `http://127.0.0.1:${API_PORT}`;
const shots = process.env.E2E_SHOTS;
const scratch = fs.mkdtempSync(path.join(os.tmpdir(), "skillforge-live-"));
const t0 = Date.now();
const log = (msg) => console.log(`[${String(Math.round((Date.now() - t0) / 1000)).padStart(3)}s] ${msg}`);

const ANSWER = {
  "What it receives": "A folder path.",
  "What it produces": "A report listing the TODO and FIXME counts for each file.",
  "Rules it must respect": "It must never edit or delete any file.",
  "How we will know it works": "It works when it lists every file that has TODO or FIXME comments with the number of each.",
  "When something goes wrong": "If the folder cannot be read it stops and says so.",
  Goal: "Count TODO and FIXME comments in a folder and report them for each file.",
};

const children = [];
function start(cmd, args, opts) {
  const out = fs.openSync(path.join(scratch, `proc-${children.length}.log`), "w");
  const c = spawn(cmd, args, { ...opts, stdio: ["ignore", out, out], windowsHide: true });
  children.push(c);
  return c;
}
async function waitFor(url, what) {
  for (let i = 0; i < 120; i++) {
    try {
      if ((await fetch(url)).ok) return;
    } catch {
      /* not up yet */
    }
    await new Promise((r) => setTimeout(r, 500));
  }
  throw new Error(`${what} did not start at ${url}`);
}

let browser;
let page; // kept outside the try so a failure can still be photographed
let exit = 0;
try {
  start(python, ["-m", "skillforge", "serve", "--port", API_PORT], {
    cwd: backend,
    env: { ...process.env, SKILLFORGE_DATA_DIR: path.join(scratch, "data"), SKILLFORGE_UI_ORIGINS: UI },
  });
  start(process.execPath, [path.join(frontend, "node_modules", "next", "dist", "bin", "next"), "start", "--hostname", "127.0.0.1", "--port", UI_PORT], {
    cwd: frontend,
    env: { ...process.env, NEXT_TELEMETRY_DISABLED: "1" },
  });
  await waitFor(`${API}/api/health`, "the API");
  await waitFor(`${UI}/builder`, "the UI");
  const provider = await (await fetch(`${API}/api/provider`)).json();
  log(`provider: ${provider.configured ? `${provider.provider} / ${provider.model}` : "NOT SET UP: " + provider.detail}`);
  if (!provider.configured) throw new Error("No model is set up in .env, so there is nothing to check.");

  browser = await chromium.launch({ channel: process.env.E2E_BROWSER_CHANNEL ?? "msedge", headless: true });
  page = await (await browser.newContext({ viewport: { width: 1280, height: 900 } })).newPage();
  const problems = [];
  page.on("pageerror", (e) => problems.push(`page error: ${e.message}`));
  page.on("framenavigated", (f) => f === page.mainFrame() && log(`navigated: ${new URL(f.url()).pathname}`));
  page.on("requestfinished", (r) => /\/api\/builds\//.test(r.url()) && log(`  ${r.method()} ${new URL(r.url()).pathname.replace(/[0-9a-f]{32}/, "<id>")}`));
  const shot = async (name) => shots && (fs.mkdirSync(shots, { recursive: true }), page.screenshot({ path: path.join(shots, `live-${name}.png`), fullPage: true }));

  await page.goto(UI + "/builder");
  await page.getByText(/^Model: /).waitFor();
  await page.getByLabel("What should the skill do?").fill("A skill that counts TODO and FIXME comments in a folder.");
  await page.getByRole("button", { name: "Start", exact: true }).click();
  await page.waitForURL(/\/builder\/[0-9a-f]{32}$/);
  log("started; the model is reading the sentence");

  for (let round = 1; round <= 4; round++) {
    const outcome = await Promise.race([
      page.getByText("A few details are missing").waitFor({ timeout: 180000 }).then(() => "questions"),
      page.getByText("Check the requirement").waitFor({ timeout: 180000 }).then(() => "requirement"),
      page.getByText("It stopped").waitFor({ timeout: 180000 }).then(() => "failed"),
    ]);
    if (outcome === "failed") throw new Error("The builder stopped: " + (await page.locator('[role="alert"]').first().innerText()));
    if (outcome === "requirement") break;
    // Answer whichever of the known questions this round asked, found by the label a person sees.
    const asked = [];
    for (const [label, text] of Object.entries(ANSWER)) {
      const box = page.getByLabel(label);
      if ((await box.count()) === 1) {
        asked.push(label);
        await box.fill(text);
      }
    }
    const expected = await page.locator("form textarea").count();
    if (asked.length !== expected) throw new Error(`The page asked ${expected} question(s) but only ${asked.length} were recognised: ${asked.join(", ")}`);
    log(`round ${round}: it asked about ${asked.length} item(s): ${asked.join(" | ")}`);
    await shot(`questions-${round}`);
    await page.getByRole("button", { name: "Send answers" }).click();
    // Wait until the old questions are gone (the page shows the model working) before looking for what comes next:
    // otherwise the next round's wait can be satisfied by the card that is about to be replaced.
    await page.getByText(/Reading your words/).first().waitFor({ timeout: 30000 });
  }

  await page.getByText("Check the requirement").waitFor();
  const rows = await page.locator("dl > div").evaluateAll((els) => els.map((e) => e.innerText.replace(/\s+/g, " ").trim()));
  log("requirement shown for approval:");
  for (const r of rows) console.log("        " + r);
  await shot("requirement");

  await page.getByRole("button", { name: "Approve and build" }).click();
  log("approved; building");
  await page.getByText("Keep it").waitFor({ timeout: 240000 });
  const name = (await page.getByRole("heading", { level: 1 }).first().innerText()).trim();
  const top = (await page.locator("h2").first().locator("xpath=..").innerText()).replace(/\s+/g, " ");
  log(`built: ${name} | ${top.slice(0, 140)}`);
  const trace = await page.locator("section", { hasText: "What you asked for, and what covers it" }).first().innerText();
  console.log("        " + trace.replace(/\s+/g, " ").slice(0, 600));
  await shot("built");

  await page.getByRole("button", { name: "Save to the library" }).click();
  await page.getByText(/Saved to the library as/).waitFor({ timeout: 30000 });
  log("saved: " + (await page.getByText(/Saved to the library as/).first().innerText()));
  log("footer: " + (await page.locator("footer").first().innerText()).replace(/\s+/g, " "));
  if (problems.length) throw new Error("script errors in the page: " + problems.join("; "));
  log("DONE: the whole conversation worked in the browser against a real model");
} catch (e) {
  exit = 1;
  console.log("FAILED: " + (e.message ?? e));
  if (page) {
    try {
      console.log("page at the moment of failure: " + page.url());
      console.log("main text: " + (await page.locator("main").innerText({ timeout: 3000 })).replace(/\s+/g, " ").slice(0, 700));
      if (shots) {
        fs.mkdirSync(shots, { recursive: true });
        await page.screenshot({ path: path.join(shots, "live-failure.png"), fullPage: true });
      }
    } catch {
      /* the page itself may be gone */
    }
  }
} finally {
  await browser?.close();
  for (const c of children) c.kill();
  await new Promise((r) => setTimeout(r, 1500)); // let the servers let go of their files (Windows will not delete an open file)
  try {
    fs.rmSync(scratch, { recursive: true, force: true, maxRetries: 5, retryDelay: 500 });
  } catch {
    console.log(`(could not delete the throwaway folder ${scratch}; it is safe to delete by hand)`);
  }
}
process.exit(exit);
