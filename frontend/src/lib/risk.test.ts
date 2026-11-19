import { afterEach, describe, expect, it, vi } from "vitest";
import { api } from "./api";
import { DIRECTION_LABEL, findingText, rescanHeadline, riskCounts, riskHeadline, SCAN_LABEL } from "./risk";
import type { RescanResult, RiskInfo, RiskLevel, ScanStatus, VersionScan } from "./types";

afterEach(() => vi.unstubAllGlobals());

const risk = (counts: Partial<RiskInfo["counts"]>): RiskInfo => ({
  older: "v1", newer: "v2", level: "look", changes: [], note: "n", counts: { riskier: 0, look: 0, safer: 0, ...counts },
});

const scan = (status: ScanStatus): VersionScan => ({ name: "s", tag: "v1", status, findings: [], message: "" });
const result = (...statuses: ScanStatus[]): RescanResult => ({
  ok: statuses.every((s) => s === "same"),
  counts: { same: statuses.filter((s) => s === "same").length, worse: statuses.filter((s) => s === "worse").length, failing: statuses.filter((s) => s === "failing").length, damaged: statuses.filter((s) => s === "damaged").length },
  versions: statuses.map(scan),
});

describe("risk headline", () => {
  const levels: RiskLevel[] = ["more_risk", "look", "less_risk", "no_new_risk"];

  it("gives every level its own words and colour", () => {
    expect(riskHeadline("more_risk")).toEqual({ tone: "bad", title: "More risk than the version before" });
    expect(riskHeadline("look").tone).toBe("warn");
    expect(riskHeadline("less_risk").tone).toBe("ok");
    expect(riskHeadline("no_new_risk")).toEqual({ tone: "info", title: "No new risk found by these checks" });
  });

  it("never says a skill is safe: code reads patterns, not meaning", () => {
    for (const level of levels) expect(riskHeadline(level).title).not.toMatch(/\bsafe\b/i);
    for (const label of Object.values(DIRECTION_LABEL)) expect(label).not.toMatch(/\bsafe\b/i);
  });

  it("lists only the counts that are not zero", () => {
    expect(riskCounts(risk({ riskier: 2, look: 1 }))).toBe("2 more risk, 1 to look at");
    expect(riskCounts(risk({ safer: 3 }))).toBe("3 less risk");
    expect(riskCounts(risk({}))).toBe("");
  });
});

describe("rescan headline", () => {
  it("says so when nothing got worse, and counts the versions", () => {
    expect(rescanHeadline(result("same", "same", "same"))).toEqual({ tone: "ok", title: "Nothing got worse: 3 versions checked" });
    expect(rescanHeadline(result("same")).title).toBe("Nothing got worse: 1 version checked");
  });

  it("says there is nothing to check for an empty library", () => {
    expect(rescanHeadline(result())).toEqual({ tone: "info", title: "There is nothing to re-check yet" });
  });

  it("is a warning for a version that got worse, and bad for one that fails or is damaged", () => {
    expect(rescanHeadline(result("same", "worse"))).toEqual({ tone: "warn", title: "1 version worse than at import (of 2)" });
    expect(rescanHeadline(result("failing", "same"))).toEqual({ tone: "bad", title: "1 version fails today (of 2)" });
    expect(rescanHeadline(result("failing", "failing", "damaged", "worse"))).toEqual({
      tone: "bad", title: "2 versions fail today, 1 version damaged, 1 version worse than at import (of 4)",
    });
  });

  it("has a label for every status that does not claim safety", () => {
    for (const label of Object.values(SCAN_LABEL)) expect(label).not.toMatch(/\bsafe\b/i);
  });
});

describe("finding text", () => {
  it("says whether the check failed or warned, and what it said at import", () => {
    expect(findingText({ status: "warning", name: "no wording", detail: "", was: "passed" })).toBe("Warns: no wording (it was passed at import)");
    expect(findingText({ status: "failed", name: "no binaries", detail: "", was: "found now" })).toBe("Fails: no binaries (this check did not exist at import)");
  });
});

describe("rescan request", () => {
  it("asks for one skill by name, encoded, or for all of them", async () => {
    const fetchMock = vi.fn(async () => new Response(JSON.stringify(result("same")), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    await api.rescan();
    await api.rescan("my skill/../x");
    const urls = fetchMock.mock.calls.map((c) => String((c as unknown[])[0]));
    expect(urls[0]).toMatch(/\/api\/rescan$/);
    expect(urls[1]).toMatch(/\/api\/rescan\?name=my%20skill%2F\.\.%2Fx$/);
  });
});
