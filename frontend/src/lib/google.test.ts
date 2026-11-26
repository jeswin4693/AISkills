import { afterEach, describe, expect, it, vi } from "vitest";
import { GOOGLE_SCRIPT, buttonWidth, createGoogleLoader, startGoogleSignIn, type GoogleApi } from "./google";

afterEach(() => vi.useRealTimers());

function fakeGoogle() {
  const calls: { initialize: unknown[]; renderButton: unknown[][] } = { initialize: [], renderButton: [] };
  const g: GoogleApi = {
    accounts: { id: { initialize: (config) => calls.initialize.push(config), renderButton: (el, options) => calls.renderButton.push([el, options]) } },
  };
  return { g, calls };
}

describe("starting Google's button", () => {
  it("hands Google the client id and the server's nonce, and never signs anyone in by itself", () => {
    const { g, calls } = fakeGoogle();
    const button = {} as HTMLElement;
    startGoogleSignIn(g, { clientId: "1234.apps.googleusercontent.com", nonce: "n-123", button, onCredential: () => {} });
    expect(calls.initialize).toHaveLength(1);
    expect(calls.initialize[0]).toMatchObject({ client_id: "1234.apps.googleusercontent.com", nonce: "n-123", auto_select: false, cancel_on_tap_outside: true });
    expect(calls.renderButton[0][0]).toBe(button);
    expect(calls.renderButton[0][1]).toMatchObject({ type: "standard", text: "signin_with", size: "large" });
  });

  it("passes the signed ticket on, and ignores a reply that has none", () => {
    const { g, calls } = fakeGoogle();
    const seen: string[] = [];
    startGoogleSignIn(g, { clientId: "c.apps.googleusercontent.com", nonce: "n", button: {} as HTMLElement, onCredential: (c) => seen.push(c) });
    const callback = (calls.initialize[0] as { callback: (r: unknown) => void }).callback;
    callback({ credential: "the.signed.ticket" });
    callback({});
    callback({ credential: "" });
    callback({ credential: 5 });
    callback(undefined);
    expect(seen).toEqual(["the.signed.ticket"]);
  });

  it("keeps the button a sensible width on any screen", () => {
    expect(buttonWidth(undefined)).toBe(300);
    expect(buttonWidth(120)).toBe(200);
    expect(buttonWidth(250)).toBe(250);
    expect(buttonWidth(900)).toBe(400);
    expect(buttonWidth(Number.NaN)).toBe(300);
  });
});

describe("loading Google's sign-in script", () => {
  function fakePage(win: { google?: GoogleApi } = {}) {
    const added: Record<string, unknown>[] = [];
    const doc = { head: { appendChild: (s: Record<string, unknown>) => added.push(s) }, createElement: () => ({}) as Record<string, unknown> };
    return { win, added, doc: doc as unknown as Pick<Document, "head" | "createElement"> };
  }

  it("adds Google's script once, and resolves with the API when it has loaded", async () => {
    const { win, added, doc } = fakePage();
    const load = createGoogleLoader(doc, win);
    const first = load();
    expect(added).toHaveLength(1);
    expect(added[0]).toMatchObject({ src: GOOGLE_SCRIPT, async: true });
    expect(GOOGLE_SCRIPT).toBe("https://accounts.google.com/gsi/client");
    const { g } = fakeGoogle();
    win.google = g;
    (added[0].onload as () => void)();
    expect(await first).toBe(g);
    expect(await load()).toBe(g); // asked again: the same answer, and no second script
    expect(added).toHaveLength(1);
  });

  it("adds only one script when it is asked again while the first is still loading", async () => {
    // Two callers at once (React mounts a component twice in development): the answer is shared, not a second script tag.
    const { win, added, doc } = fakePage();
    const load = createGoogleLoader(doc, win);
    const first = load();
    const second = load(); // the script has NOT finished: window.google is not there yet
    expect(added).toHaveLength(1);
    expect(second).toBe(first);
    const { g } = fakeGoogle();
    win.google = g;
    (added[0].onload as () => void)();
    expect(await first).toBe(g);
    expect(await second).toBe(g);
  });

  it("does not add a script at all when Google's code is already on the page", async () => {
    const { g } = fakeGoogle();
    const { win, added, doc } = fakePage({ google: g });
    expect(await createGoogleLoader(doc, win)()).toBe(g);
    expect(added).toHaveLength(0);
  });

  it("says plainly when the script could not be loaded, and lets the person try again", async () => {
    const { win, added, doc } = fakePage();
    const load = createGoogleLoader(doc, win);
    const failed = load();
    (added[0].onerror as () => void)();
    await expect(failed).rejects.toThrow(/Google/);
    const again = load(); // a failure is not remembered
    expect(added).toHaveLength(2);
    const { g } = fakeGoogle();
    win.google = g;
    (added[1].onload as () => void)();
    expect(await again).toBe(g);
  });

  it("gives up after the time limit instead of waiting for ever", async () => {
    vi.useFakeTimers();
    const { win, doc } = fakePage();
    const pending = createGoogleLoader(doc, win, 5_000)();
    const outcome = expect(pending).rejects.toThrow(/Google/);
    await vi.advanceTimersByTimeAsync(5_001);
    await outcome;
  });

  it("does not believe a script that loaded but did not bring Google's code", async () => {
    const { win, added, doc } = fakePage();
    const pending = createGoogleLoader(doc, win)();
    (added[0].onload as () => void)(); // loaded, yet window.google is missing (blocked or replaced)
    await expect(pending).rejects.toThrow(/Google/);
  });
});
