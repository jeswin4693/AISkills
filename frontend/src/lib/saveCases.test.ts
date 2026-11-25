import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, api } from "./api";

/** The save route answers 422 in two different ways: an import report (a static check refused it) and FastAPI's own validation error. */
const answer = (status: number, body: unknown) => vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } })));
const REQUEST = { base_version: 1, note: "", cases: [] };

afterEach(() => vi.unstubAllGlobals());

describe("saveCases", () => {
  it("returns an import report that a check refused (a 422 with the checks)", async () => {
    const report = { refused: true, created: false, name: "s", version: null, previous: null, checks: [{ name: "no hidden characters", status: "failed", detail: "found" }], changes: [], risk: null };
    answer(422, report);
    expect(await api.saveCases("s", REQUEST)).toMatchObject({ refused: true, checks: [{ name: "no hidden characters" }] });
  });

  it("returns a kept version", async () => {
    answer(200, { refused: false, created: true, name: "s", version: { version: 2, tag: "v2" }, previous: "v1", checks: [], changes: [], risk: null });
    expect(await api.saveCases("s", REQUEST)).toMatchObject({ created: true, version: { tag: "v2" } });
  });

  it("raises the server's validation error instead of letting it look like an import report, so it is never shown as 'Nothing changed'", async () => {
    answer(422, { detail: [{ loc: ["body", "cases", 0, "checks", 0, "why"], msg: "String should have at most 200 characters", type: "string_too_long" }] });
    const error = await api.saveCases("s", REQUEST).then(() => null, (e: unknown) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).status).toBe(422);
    expect((error as ApiError).message).toContain("at most 200 characters");
  });

  it("raises a refusal the server words (a case that could not be run, a stale edit)", async () => {
    answer(400, { detail: "Case 1: it needs a message to send." });
    expect(await api.saveCases("s", REQUEST).then(() => "", (e: ApiError) => e.message)).toBe("Case 1: it needs a message to send.");
    answer(409, { detail: "The version you edited (s v1) is not the latest." });
    expect(await api.saveCases("s", REQUEST).then(() => 0, (e: ApiError) => e.status)).toBe(409);
  });
});
