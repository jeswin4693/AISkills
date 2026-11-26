// The HOSTED sign-in screen, driven in a real browser (Edge) at phone size with touch, against a throwaway hosted server. (The main suite, run.mjs, runs the
// local version, which has no sign-in screen at all.) Run from frontend/:   npm run e2e:phone
//
// What it does: starts the API in hosted mode with a random access token and a made-up Google Client ID, starts the built web app, opens the page as an iPhone-sized
// touch device, and checks: Google's button draws (its script comes from the internet) or the page says why not; no sideways scroll; tap targets are 44 px;
// the token box is 16 px (iOS does not zoom in on focus); a wrong token is refused visibly; the right token signs the owner in; the signed-in page does not scroll
// sideways; Sign out is reachable and works. It never prints the token, and the throwaway data folder is under the temp folder.
//
// Needs: the UI built THE WAY THE HOSTED IMAGE BUILDS IT, with the page and the API sharing one address (the session is a cookie, and a browser neither keeps nor
// sends a cookie between two different origins, so a page on one port and an API on another can never stay signed in):
//   NEXT_PUBLIC_API_URL=same-origin SKILLFORGE_PROXY_API=http://127.0.0.1:8100 npm run build
// This build replaces the one the main suite (run.mjs) needs, which calls the API on its own port: rebuild with the other settings before running that again.
// Settings (all optional): SKILLFORGE_PYTHON (default "python"), E2E_UI_PORT (default 3100), E2E_API_PORT (default 8100; it must match SKILLFORGE_PROXY_API above),
// E2E_BROWSER_CHANNEL (default "msedge"). It uses side ports on purpose so it can run next to your own `serve` and `npm run dev`.
import { spawn } from "node:child_process";
import { randomBytes } from "node:crypto";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright-core";

const frontend = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const backend = path.resolve(frontend, "..", "backend");
const python = process.env.SKILLFORGE_PYTHON ?? "python";
const UI = Number(process.env.E2E_UI_PORT ?? 3100);
const API = Number(process.env.E2E_API_PORT ?? 8100);
const TOKEN = randomBytes(30).toString("base64url").slice(0, 40);
const out = fs.mkdtempSync(path.join(os.tmpdir(), "skillforge-phone-"));
const log = fs.openSync(path.join(out, "servers.log"), "w");
const kids = [];
const start = (cmd, args, env, cwd) => {
  const child = spawn(cmd, args, { env: { ...process.env, ...env }, cwd, stdio: ["ignore", log, log], windowsHide: true });
  kids.push(child);
  return child;
};

const results = [];
const note = (ok, what, detail = "") => {
  results.push({ ok, what });
  console.log(`${ok ? "ok  " : "FAIL"} ${what}${detail ? "  -> " + detail : ""}`);
};

async function waitFor(url, ms = 60_000) {
  const end = Date.now() + ms;
  while (Date.now() < end) {
    try {
      if ((await fetch(url)).status < 500) return true;
    } catch {
      /* not up yet */
    }
    await new Promise((r) => setTimeout(r, 500));
  }
  return false;
}

let browser;
try {
  // hosted_server.py, not `skillforge serve`: it has no model and an empty settings file, so this check can never read your real .env or spend a key.
  fs.mkdirSync(path.join(out, "data"), { recursive: true });
  start(python, [path.join(frontend, "e2e", "hosted_server.py")], {
    E2E_API_PORT: String(API), PYTHONPATH: backend, SKILLFORGE_DATA_DIR: path.join(out, "data"), SKILLFORGE_MODE: "hosted", SKILLFORGE_ACCESS_TOKEN: TOKEN,
    SKILLFORGE_ALLOWED_HOSTS: "127.0.0.1,localhost",
    SKILLFORGE_GOOGLE_CLIENT_ID: "111111111111-test.apps.googleusercontent.com", SKILLFORGE_ALLOWED_EMAILS: "tester@example.com",
  }, backend);
  start(process.execPath, [path.join(frontend, "node_modules", "next", "dist", "bin", "next"), "start", "--hostname", "127.0.0.1", "--port", String(UI)], {}, frontend);
  if (!(await waitFor(`http://127.0.0.1:${API}/api/health`)) || !(await waitFor(`http://127.0.0.1:${UI}/`))) {
    throw new Error(`the servers did not start (is the UI built? see ${path.join(out, "servers.log")})`);
  }

  browser = await chromium.launch({ channel: process.env.E2E_BROWSER_CHANNEL ?? "msedge", headless: true });
  const PHONE = {
    viewport: { width: 390, height: 844 }, deviceScaleFactor: 3, isMobile: true, hasTouch: true,
    userAgent: "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1",
  };
  const context = await browser.newContext(PHONE);
  const page = await context.newPage();
  const problems = [];
  page.on("pageerror", (e) => problems.push("page error: " + e.message));
  page.on("console", (m) => {
    if (m.type() === "error") problems.push("console: " + m.text().slice(0, 200));
  });
  const shot = (name) => page.screenshot({ path: path.join(out, name), fullPage: true });
  const shotOf = (p, name) => p.screenshot({ path: path.join(out, name), fullPage: true });
  const sideways = () => page.evaluate(() => ({ scroll: document.documentElement.scrollWidth, inner: window.innerWidth }));
  const signInButton = () => page.getByRole("button", { name: "Sign in", exact: true }); // Google's own button also has "Sign in" in its name

  await page.goto(`http://127.0.0.1:${UI}/`);
  await page.getByRole("heading", { name: "Sign in", level: 1 }).waitFor({ timeout: 20_000 });
  note(true, "the hosted sign-in screen opens on a phone-sized touch browser");

  // Google's script comes from the internet and the Client ID is made up: the button may draw or the page may say why not. Either is a clear screen.
  const google = await Promise.race([
    page.getByRole("button", { name: /Sign in with Google/i }).first().waitFor({ timeout: 12_000 }).then(() => "Google's button was drawn"),
    page.getByText("Google sign-in is not available").waitFor({ timeout: 12_000 }).then(() => "the page said Google sign-in is not available (script blocked or unreachable)"),
  ]).catch(() => "neither the button nor the message appeared within 12 s");
  note(!google.startsWith("neither"), "Google's area ends in a clear state", google);

  const w1 = await sideways();
  note(w1.scroll <= w1.inner, "the sign-in screen does not scroll sideways", `${w1.scroll} px wide in a ${w1.inner} px window`);
  await shot("01-login.png");

  const summary = page.getByText("Owner of this server? Use the access token");
  const sbox = await summary.boundingBox();
  note(sbox !== null && sbox.height >= 44, "the 'Owner? Use the access token' line is a 44 px tap target", sbox ? `${Math.round(sbox.width)} x ${Math.round(sbox.height)} px` : "not found");

  if (!(await page.locator("#access-token").isVisible())) await summary.tap();
  await page.locator("#access-token").waitFor({ timeout: 5_000 });
  const fontSize = await page.locator("#access-token").evaluate((el) => parseFloat(getComputedStyle(el).fontSize));
  note(fontSize >= 16, "the token box text is 16 px or larger (iPhone does not zoom in on focus)", `${fontSize}px`);
  const bbox = await signInButton().boundingBox();
  note(bbox !== null && bbox.height >= 44, "the Sign in button is a 44 px tap target", bbox ? `${Math.round(bbox.width)} x ${Math.round(bbox.height)} px` : "not found");
  await shot("02-token-form.png");

  await page.locator("#access-token").fill("this-is-the-wrong-token-0000000000");
  await signInButton().tap();
  await page.getByText("Not signed in").waitFor({ timeout: 8_000 });
  note(true, "a wrong token is refused with a visible message");
  await shot("03-wrong-token.png");

  await page.locator("#access-token").fill(TOKEN);
  await signInButton().tap();
  await page.getByRole("button", { name: /sign out/i }).first().waitFor({ timeout: 15_000 }).catch(() => {});
  await page.waitForTimeout(1_000);
  const signedIn = !(await page.getByRole("heading", { name: "Sign in", level: 1 }).isVisible().catch(() => false));
  note(signedIn, "the right token signs the owner in on the phone");
  const provider = await page.evaluate(() => fetch("/api/provider").then((r) => r.json()).catch(() => null));
  note(provider !== null && provider.configured === false, "the throwaway server has no model, so it cannot be reading your real .env", provider ? `configured: ${provider.configured}` : "no answer");
  const w2 = await sideways();
  note(w2.scroll <= w2.inner, "the signed-in page does not scroll sideways", `${w2.scroll} px wide in a ${w2.inner} px window`);
  await shot("04-signed-in.png");

  // The owner's Settings page: no personal model, and they are told so (their model is the server's own settings).
  await page.goto(`http://127.0.0.1:${UI}/settings`);
  await page.getByText("You are the owner of this server").waitFor({ timeout: 15_000 }).then(
    () => note(true, "the owner is told on the Settings page that the server's own settings are used"),
    async () => {
      const seen = ((await page.locator("body").innerText().catch(() => "")) || "").replace(/\s+/g, " ").slice(0, 300);
      await shot("owner-settings-failed.png").catch(() => {});
      note(false, "the owner is told on the Settings page that the server's own settings are used", `the page said: ${seen}`);
    },
  );

  let signOut = page.getByRole("button", { name: /sign out/i }).first();
  if (!(await signOut.isVisible().catch(() => false))) {
    const menu = page.getByRole("button", { name: /menu|navigation/i }).first();
    if (await menu.isVisible().catch(() => false)) {
      await menu.tap();
      await page.waitForTimeout(400);
      signOut = page.getByRole("button", { name: /sign out/i }).first();
    }
  }
  const canSignOut = await signOut.isVisible().catch(() => false);
  note(canSignOut, "a Sign out control can be reached on the phone");
  if (canSignOut) {
    await signOut.tap();
    await page.getByRole("heading", { name: "Sign in", level: 1 }).waitFor({ timeout: 10_000 }).then(
      () => note(true, "signing out returns to the sign-in screen"),
      () => note(false, "signing out returns to the sign-in screen"),
    );
  }

  // ---- a signed-in PERSON (not the owner): their own model and key on the Settings page ----
  // hosted_server.py wrote a real session cookie for one made-up person (made by the product's own make_cookie), so no Google ticket is needed.
  const personCookie = fs.readFileSync(path.join(out, "data", "person-cookie.txt"), "utf8").trim();
  const personContext = await browser.newContext(PHONE);
  await personContext.addCookies([{ name: "skillforge_session", value: personCookie, domain: "127.0.0.1", path: "/", httpOnly: true, sameSite: "Lax" }]);
  const me = await personContext.newPage();
  me.on("pageerror", (e) => problems.push("page error: " + e.message));
  me.on("console", (m) => {
    if (m.type() === "error") problems.push("console: " + m.text().slice(0, 200));
  });
  const answers = []; // every body the server sent about models: the key must be in none of them
  me.on("response", async (r) => {
    if (/\/api\/(me\/model|provider)/.test(r.url())) await r.text().then((t) => answers.push(t), () => {});
  });
  const KEY = "PHONE-CHECK-KEY-0123456789";

  await me.goto(`http://127.0.0.1:${UI}/builder`);
  await me.getByText("No AI model is set up yet").waitFor({ timeout: 15_000 });
  note(await me.getByText(/Add your own model key in/).first().isVisible(), "with no model, a person is told to add their own key in Settings (not to edit a .env file)");

  await me.goto(`http://127.0.0.1:${UI}/settings`);
  await me.getByRole("heading", { name: "Use your own model" }).waitFor({ timeout: 15_000 });
  note(true, "a signed-in person sees My model on the Settings page");
  const provider2 = me.getByLabel("Provider");
  const model2 = me.getByLabel("Model", { exact: true });
  const key2 = me.getByLabel("Key", { exact: true });
  const save2 = me.getByRole("button", { name: "Save my model" });
  const options = await provider2.locator("option").allTextContents();
  note(options.length > 0 && !options.includes("custom"), "the providers offered leave out custom (it takes an address)", options.join(", "));
  const boxes = await Promise.all([provider2, model2, key2, save2].map((l) => l.boundingBox()));
  note(boxes.every((b) => b !== null && b.height >= 44), "the form's fields and Save button are 44 px tall", boxes.map((b) => (b ? Math.round(b.height) : "?")).join(", "));
  note((await key2.getAttribute("type")) === "password" && (await key2.evaluate((el) => parseFloat(getComputedStyle(el).fontSize))) >= 16, "the key box is a password field with 16 px text");
  const w3 = await me.evaluate(() => ({ scroll: document.documentElement.scrollWidth, inner: window.innerWidth }));
  note(w3.scroll <= w3.inner, "My model does not scroll sideways", `${w3.scroll} px wide in a ${w3.inner} px window`);

  await provider2.selectOption("groq");
  await model2.fill("llama-phone-check");
  await key2.fill(`"${KEY}"`);
  await me.getByText(/Remove the quotes/).waitFor({ timeout: 5_000 });
  note(await save2.isDisabled(), "a key pasted in quotes is refused before Save, saying what to remove");
  await key2.fill(` ${KEY} `); // a space at either end is fine: it is trimmed
  await save2.tap();
  await me.getByText(/Saved\. It is used/).waitFor({ timeout: 10_000 }).then(
    () => note(true, "saving works and says so"),
    () => note(false, "saving works and says so"),
  );
  note((await key2.inputValue()) === "", "the key box is empty again the moment it is saved");
  const pageText = await me.locator("body").innerText();
  const pageHtml = await me.content();
  note(!pageText.includes(KEY) && !pageHtml.includes(KEY), "the key is nowhere on the page after saving");
  note(!answers.join(" ").includes(KEY) && answers.length > 0, "the key is in no answer the server gave", `${answers.length} answers checked`);
  await shotOf(me, "05-my-model-saved.png");

  await me.reload();
  await me.getByText("Your own key").first().waitFor({ timeout: 15_000 });
  note((await me.getByLabel("Key", { exact: true }).inputValue()) === "", "after a reload the model is still saved and the key box is still empty");

  await me.getByRole("button", { name: "Test my key" }).tap();
  await me.getByText("Works", { exact: true }).waitFor({ timeout: 10_000 }).then(
    () => note(true, "testing the key works (against the launcher's fake model: no network is used)"),
    () => note(false, "testing the key works (against the launcher's fake model: no network is used)"),
  );

  await me.getByRole("button", { name: "Remove my key" }).tap();
  await me.getByText("Not set up", { exact: true }).waitFor({ timeout: 10_000 }).then(
    () => note(true, "removing the key puts the person back to having no model"),
    () => note(false, "removing the key puts the person back to having no model"),
  );
  const w4 = await me.evaluate(() => ({ scroll: document.documentElement.scrollWidth, inner: window.innerWidth }));
  note(w4.scroll <= w4.inner, "My model does not scroll sideways afterwards either", `${w4.scroll} px wide in a ${w4.inner} px window`);

  // Google's own script logs its own complaints (a made-up Client ID, third-party cookies): only errors from OUR pages and API count.
  const ours = problems.filter((p) => !/accounts\.google\.com|gsi|googleusercontent|GSI_LOGGER|Failed to load resource/i.test(p));
  note(ours.length === 0, "no page errors or console errors of our own", ours.slice(0, 3).join(" | "));
  console.log(`screenshots: ${out}`);
} catch (err) {
  note(false, "the check itself ran to the end", String((err && err.message) || err));
} finally {
  if (browser) await browser.close().catch(() => {});
  for (const child of kids) {
    try {
      child.kill();
    } catch {
      /* already gone */
    }
  }
}
const bad = results.filter((r) => !r.ok);
console.log(`\n${results.length - bad.length} of ${results.length} phone checks passed`);
process.exit(bad.length ? 1 : 0);
