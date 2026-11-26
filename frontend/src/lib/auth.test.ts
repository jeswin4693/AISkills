import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, api } from "./api";
import { authPhase, personLabel, signedInStatus, signedOutStatus } from "./auth";
import { modelSummary } from "./format";
import type { ProviderStatus } from "./types";

afterEach(() => vi.unstubAllGlobals());

const reply = (status: number, body: unknown) => new Response(JSON.stringify(body), { status });

describe("what the app shows for a sign-in status", () => {
  it("waits until it knows, opens when no sign-in is needed or the person is signed in, asks otherwise", () => {
    expect(authPhase(undefined)).toBe("checking");
    expect(authPhase({ required: false, authenticated: true })).toBe("open");
    expect(authPhase({ required: true, authenticated: true })).toBe("open");
    expect(authPhase({ required: true, authenticated: false })).toBe("login");
  });
});

describe("what the app remembers about the server's sign-in settings", () => {
  const ada = { email: "ada@example.com", name: "Ada Lovelace", picture: "https://x.example/p.png" };

  it("keeps the Google client id when a session ends, so the login screen still has its button", () => {
    const before = { required: true, authenticated: true, google_client_id: "c.apps.googleusercontent.com", owner_login: true, user: ada };
    expect(signedOutStatus(before)).toEqual({ required: true, authenticated: false, google_client_id: "c.apps.googleusercontent.com", owner_login: true, user: null });
    expect(authPhase(signedOutStatus(before))).toBe("login");
  });

  it("knows nothing about Google until the server said something, and still asks for a sign-in", () => {
    expect(signedOutStatus(undefined)).toEqual({ required: true, authenticated: false, google_client_id: "", owner_login: true, user: null });
  });

  it("records who signed in, and keeps the rest", () => {
    const before = { required: true, authenticated: false, google_client_id: "c.apps.googleusercontent.com", owner_login: true, user: null };
    expect(signedInStatus(before, ada)).toEqual({ required: true, authenticated: true, google_client_id: "c.apps.googleusercontent.com", owner_login: true, user: ada });
    expect(signedInStatus(before, null).user).toBeNull(); // the owner signs in with the token: no person to show
    expect(authPhase(signedInStatus(before, ada))).toBe("open");
  });

  it("shows a person by name, falls back to the email, and keeps it short", () => {
    expect(personLabel(ada)).toBe("Ada Lovelace");
    expect(personLabel({ ...ada, name: "  " })).toBe("ada@example.com");
    expect(personLabel(null)).toBe("");
    expect(personLabel(undefined)).toBe("");
    expect(personLabel({ ...ada, name: "A".repeat(80) })).toBe("A".repeat(39) + "…");
  });

  it("still understands the older server that sends only two fields", () => {
    expect(authPhase({ required: true, authenticated: false })).toBe("login");
    expect(authPhase({ required: false, authenticated: true })).toBe("open");
  });
});

describe("the Google sign-in calls", () => {
  it("asks for a nonce and posts the signed ticket as JSON, never anything else", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(reply(200, { nonce: "n-123" }))
      .mockResolvedValueOnce(reply(200, { authenticated: true, user: { email: "a@b.c", name: "A", picture: "" } }));
    vi.stubGlobal("fetch", fetchMock);
    expect(await api.authNonce()).toEqual({ nonce: "n-123" });
    expect((await api.googleLogin("the.signed.ticket")).user.email).toBe("a@b.c");
    const [nonce, google] = fetchMock.mock.calls;
    expect(String(nonce[0])).toMatch(/\/api\/auth\/nonce$/);
    expect(String(google[0])).toMatch(/\/api\/auth\/google$/);
    expect(google[1]).toMatchObject({ method: "POST", body: JSON.stringify({ credential: "the.signed.ticket" }) });
  });

  it("gives the server's own words when the account is not allowed or the ticket is not believed", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValueOnce(reply(403, { detail: "That Google account is not allowed on this server. Ask the person who runs it to add your email address." })));
    await expect(api.googleLogin("t")).rejects.toMatchObject({ status: 403, message: expect.stringContaining("not allowed") });
    vi.stubGlobal("fetch", vi.fn().mockResolvedValueOnce(reply(401, { detail: "That Google sign-in could not be verified." })));
    await expect(api.googleLogin("t")).rejects.toBeInstanceOf(ApiError);
  });
});

describe("the sign-in calls", () => {
  it("asks the API for the status, signs in with the token as JSON and signs out", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(reply(200, { required: true, authenticated: false }))
      .mockResolvedValueOnce(reply(200, { authenticated: true }))
      .mockResolvedValueOnce(reply(200, { authenticated: false }));
    vi.stubGlobal("fetch", fetchMock);
    expect(await api.authStatus()).toEqual({ required: true, authenticated: false });
    expect(await api.login("the-token")).toEqual({ authenticated: true });
    await api.logout();
    const [status, login, logout] = fetchMock.mock.calls;
    expect(String(status[0])).toMatch(/\/api\/auth\/status$/);
    expect(String(login[0])).toMatch(/\/api\/auth\/login$/);
    expect(login[1]).toMatchObject({ method: "POST", body: JSON.stringify({ token: "the-token" }) });
    expect(String(logout[0])).toMatch(/\/api\/auth\/logout$/);
  });

  it("gives the server's own words for a wrong token and for a lock", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValueOnce(reply(401, { detail: "That is not the access token." })));
    await expect(api.login("nope")).rejects.toMatchObject({ status: 401, message: "That is not the access token." });
    vi.stubGlobal("fetch", vi.fn().mockResolvedValueOnce(reply(429, { detail: "Too many wrong tries. Try again in 42 seconds." })));
    await expect(api.login("nope")).rejects.toBeInstanceOf(ApiError);
  });
});

describe("the model line in the status panel", () => {
  const base: ProviderStatus = { configured: true, provider: "gemini", model: "gemini-3.5-flash-lite", detail: "" };

  it("says it is not set up, shows the model alone, and counts backups with their providers", () => {
    expect(modelSummary({ ...base, configured: false })).toBeNull();
    expect(modelSummary(base)).toBe("gemini-3.5-flash-lite");
    expect(modelSummary({ ...base, fallbacks: [] })).toBe("gemini-3.5-flash-lite");
    expect(modelSummary({ ...base, fallbacks: [{ provider: "groq", model: "g" }] })).toBe("gemini-3.5-flash-lite + 1 backup (groq)");
    expect(
      modelSummary({ ...base, fallbacks: [{ provider: "groq", model: "g" }, { provider: "openai", model: "o" }, { provider: "groq", model: "h" }] }),
    ).toBe("gemini-3.5-flash-lite + 3 backups (groq, openai)");
  });
});
