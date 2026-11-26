import { describe, expect, it } from "vitest";
import { adviceFor, formatSize, spaceRows } from "./space";
import type { PersonSpace } from "./types";

const MB = 1024 * 1024;
const person = (over: Partial<PersonSpace> = {}): PersonSpace => ({
  mode: "person",
  disk: { used: 120 * MB, limit: 500 * MB },
  builds: { kept: 12, limit: 50 },
  active: { now: 1, limit: 2 },
  ...over,
});

describe("sizes in words", () => {
  it.each([
    [0, "0 KB"],
    [1, "1 KB"],
    [1536, "2 KB"],
    [MB, "1.0 MB"],
    [Math.round(1.5 * MB), "1.5 MB"],
    [500 * MB, "500.0 MB"],
    [3 * 1024 * MB, "3.0 GB"],
  ])("%d bytes is %s", (bytes, text) => {
    expect(formatSize(bytes)).toBe(text);
  });
  it("never says a negative or an unreadable size", () => {
    expect(formatSize(-5)).toBe("0 KB");
    expect(formatSize(Number.NaN)).toBe("0 KB");
  });
});

describe("what a person is shown about their own space", () => {
  it("says used of the limit, with how full each is", () => {
    const rows = spaceRows(person());
    expect(rows.map((r) => r.key)).toEqual(["disk", "builds", "active"]);
    expect(rows[0].text).toBe("120.0 MB of 500.0 MB");
    expect(rows[0].percent).toBe(24);
    expect(rows[1].text).toBe("12 of 50 builds kept");
    expect(rows[2].text).toBe("1 of 2 runs working");
    expect(rows.every((r) => r.tone === "ok")).toBe(true);
  });

  it("warns from 80 percent and says bad at the limit, never over 100 percent", () => {
    const rows = spaceRows(person({ disk: { used: 450 * MB, limit: 500 * MB }, builds: { kept: 50, limit: 50 }, active: { now: 5, limit: 2 } }));
    expect(rows[0].tone).toBe("warn");
    expect(rows[1].tone).toBe("bad");
    expect(rows[2].tone).toBe("bad");
    expect(rows[2].percent).toBe(100);
  });

  it("says plainly when there is no limit, and shows no bar for it", () => {
    const rows = spaceRows(person({ disk: { used: 5 * MB, limit: 0 }, builds: { kept: 3, limit: 0 }, active: { now: 0, limit: 0 } }));
    expect(rows[0].text).toBe("5.0 MB used (no limit)");
    expect(rows[1].text).toBe("3 builds kept (no limit)");
    expect(rows[2].text).toBe("0 runs working (no limit)");
    expect(rows.every((r) => r.percent === null && r.tone === "ok")).toBe(true);
  });

  it("says one build and one run, not 1 builds", () => {
    const rows = spaceRows(person({ builds: { kept: 1, limit: 0 }, active: { now: 1, limit: 0 } }));
    expect(rows[1].text).toBe("1 build kept (no limit)");
    expect(rows[2].text).toBe("1 run working (no limit)");
  });
});

describe("what to do when a limit is reached", () => {
  it("says nothing when nothing is full", () => {
    expect(adviceFor(spaceRows(person()))).toBe("");
  });
  it("says to discard builds for disk and builds, and to wait for runs", () => {
    expect(adviceFor(spaceRows(person({ disk: { used: 500 * MB, limit: 500 * MB } })))).toMatch(/discard/i);
    expect(adviceFor(spaceRows(person({ builds: { kept: 50, limit: 50 } })))).toMatch(/discard/i);
    expect(adviceFor(spaceRows(person({ active: { now: 2, limit: 2 } })))).toMatch(/wait/i);
  });
});
