import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, api } from "./api";
import { authPhase } from "./auth";
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
