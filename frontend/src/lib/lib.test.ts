import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, api, detailOf, encodePath } from "./api";
import { diffStats, parseDiff } from "./diff";
import { conflictPath, countChecks, formatWhen, plural, relativeTime, shortHash, sortChecks, sourceText } from "./format";
import type { Check } from "./types";

afterEach(() => vi.unstubAllGlobals());

const reply = (status: number, body: unknown, headers: Record<string, string> = {}) =>
  new Response(typeof body === "string" ? body : JSON.stringify(body), { status, headers });

describe("diff", () => {
  it("tells headers, hunks, additions, removals and context apart", () => {
    const text = ["--- a.md (before)", "+++ a.md (after)", "@@ -1,2 +1,2 @@", " same", "-old", "+new"].join("\n");
    expect(parseDiff(text).map((l) => l.kind)).toEqual(["meta", "meta", "hunk", "ctx", "del", "add"]);
  });

  it("treats a removed Markdown rule as a removal, not as a file header", () => {
    const text = ["--- SKILL.md (before)", "+++ SKILL.md (after)", "@@ -1,3 +1,2 @@", "----", " name: x", "+++ added line"].join("\n");
    expect(parseDiff(text).map((l) => l.kind)).toEqual(["meta", "meta", "hunk", "del", "ctx", "add"]);
    expect(diffStats(text)).toEqual({ added: 1, removed: 1 });
  });

  it("shows the API's 'cut' notice as a note and counts only real changes", () => {
    const text = ["@@ -1 +1 @@", "-a", "+b", "... 40 more line(s) not shown"].join("\n");
    expect(parseDiff(text)[3].kind).toBe("meta");
    expect(diffStats(text)).toEqual({ added: 1, removed: 1 });
  });

  it("gives nothing for no text", () => {
    expect(parseDiff("")).toEqual([]);
    expect(diffStats("")).toEqual({ added: 0, removed: 0 });
  });
});

describe("format", () => {
  const checks: Check[] = [
    { name: "a", status: "passed", detail: "" },
    { name: "b", status: "failed", detail: "x" },
    { name: "c", status: "not run", detail: "" },
    { name: "d", status: "warning", detail: "" },
    { name: "e", status: "passed", detail: "" },
  ];

  it("counts every status, including the ones with none", () => {
    expect(countChecks(checks)).toEqual({ passed: 2, warning: 1, failed: 1, "not run": 1 });
    expect(countChecks([])).toEqual({ passed: 0, warning: 0, failed: 0, "not run": 0 });
  });

  it("lists failures first, then warnings, then what did not run, then what passed, without changing the input", () => {
    expect(sortChecks(checks).map((c) => c.status)).toEqual(["failed", "warning", "not run", "passed", "passed"]);
    expect(checks[0].name).toBe("a");
  });

  it("shows only the folder from the API's command-line style conflict message", () => {
    expect(conflictPath("C:\\a b\\skills\\demo already exists. Use --force to replace it (the old copy is saved to a backup first).")).toBe("C:\\a b\\skills\\demo");
    expect(conflictPath("something else entirely")).toBe("something else entirely");
  });

  it("writes plurals, hashes and sources plainly", () => {
    expect(plural(1, "file")).toBe("1 file");
    expect(plural(2, "version")).toBe("2 versions");
    expect(plural(0, "check")).toBe("0 checks");
    expect(shortHash("0123456789abcdef")).toBe("0123456789ab");
    expect(sourceText("zip", "x.zip")).toBe("zip x.zip");
    expect(sourceText("rollback", "v1")).toBe("restored v1");
  });

  it("says how long ago, and falls back to the text it was given when it is not a date", () => {
    const now = new Date("2026-11-19T12:00:00Z").getTime();
    expect(relativeTime("2026-11-19T11:59:40Z", now)).toBe("just now");
    expect(relativeTime("2026-11-19T11:30:00Z", now)).toBe("30 min ago");
    expect(relativeTime("2026-11-19T09:00:00Z", now)).toBe("3 h ago");
    expect(relativeTime("2026-11-17T12:00:00Z", now)).toBe("2 days ago");
    expect(relativeTime("nonsense", now)).toBe("nonsense");
    expect(formatWhen("nonsense")).toBe("nonsense");
    expect(formatWhen("2026-11-19T05:34:42.123+00:00")).toMatch(/^2026-11-19 \d\d:\d\d$/);
  });
});

describe("api", () => {
  it("encodes each path segment so a file name cannot add a query or a fragment", () => {
    expect(encodePath("schemas/input.schema.json")).toBe("schemas/input.schema.json");
    expect(encodePath("a b/c?d#e.md")).toBe("a%20b/c%3Fd%23e.md");
  });

  it("refuses dot segments and empty segments, which a URL parser would collapse", () => {
    for (const bad of ["../x", "a/../b", "./x", "a//b", "/abs", "a/", "..", "%2e%2e".replace(/%2e/g, ".")]) {
      expect(() => encodePath(bad), bad).toThrow(ApiError);
    }
  });

  it("reads FastAPI's detail whether it is a string or a list of problems", () => {
    expect(detailOf({ detail: "nope" }, "fallback")).toBe("nope");
    expect(detailOf({ detail: [{ msg: "bad a" }, { msg: "bad b" }] }, "fallback")).toBe("bad a; bad b");
    expect(detailOf({ detail: [] }, "fallback")).toBe("fallback");
    expect(detailOf(null, "fallback")).toBe("fallback");
  });

  it("says plainly that the API is not running when the connection fails", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")));
    const err = await api.health().catch((e) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect(err.status).toBe(0);
    expect(err.message).toContain("python -m skillforge serve");
  });

  it("turns an error answer into an ApiError with the server's message", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(reply(409, { detail: "C:\\x already exists." })));
    const err = await api.install("demo", { target: "personal" }).catch((e) => e);
    expect(err).toMatchObject({ status: 409, message: "C:\\x already exists." });
  });

  it("falls back to a generic message when an error answer is not JSON", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(reply(500, "<html>boom</html>")));
    const err = await api.listSkills().catch((e) => e);
    expect(err).toMatchObject({ status: 500, message: "The API answered 500." });
  });

  it("returns a refused import as a result with its checks, not as an error", async () => {
    const body = { refused: true, created: false, name: null, version: null, previous: null, checks: [{ name: "n", status: "failed", detail: "d" }], changes: [] };
    const fetchMock = vi.fn().mockResolvedValue(reply(422, body));
    vi.stubGlobal("fetch", fetchMock);
    const result = await api.importZip(new File(["x"], "bad skill.zip"), { note: " first ", testScripts: true });
    expect(result.refused).toBe(true);
    const [url, init] = fetchMock.mock.calls[0];
    expect(String(url)).toContain("/api/library/import?filename=bad+skill.zip&note=first&test_scripts=true");
    expect(init.headers).toEqual({ "Content-Type": "application/zip" });
  });

  it("still raises for an upload the API cannot read at all", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(reply(400, { detail: "upload.zip is not a zip file." })));
    await expect(api.importZip(new File(["x"], "upload.zip"))).rejects.toMatchObject({ status: 400 });
  });

  it("asks for a diff with the API's own parameter names, and for the default when none are given", async () => {
    const fetchMock = vi.fn().mockResolvedValue(reply(200, { name: "demo", from: "v1", to: "v2", changes: [] }));
    vi.stubGlobal("fetch", fetchMock);
    await api.diff("demo", 1, 3);
    await api.diff("demo");
    expect(String(fetchMock.mock.calls[0][0])).toMatch(/\/api\/library\/demo\/diff\?frm=1&to=3$/);
    expect(String(fetchMock.mock.calls[1][0])).toMatch(/\/api\/library\/demo\/diff$/);
  });

  it("takes the file name for an export from the API's header, or makes one", async () => {
    const withHeader = reply(200, "zipbytes", { "Content-Disposition": 'attachment; filename="demo-v3.zip"' });
    vi.stubGlobal("fetch", vi.fn().mockResolvedValueOnce(withHeader).mockResolvedValueOnce(reply(200, "zipbytes")));
    expect((await api.exportZip("demo", 3, false)).filename).toBe("demo-v3.zip");
    expect((await api.exportZip("demo", 2, true)).filename).toBe("demo-v2.zip");
  });

  it("raises the server's message when an export is refused", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(reply(400, { detail: "demo v1 was changed after import" })));
    await expect(api.exportZip("demo", 1, false)).rejects.toMatchObject({ status: 400, message: "demo v1 was changed after import" });
  });
});
