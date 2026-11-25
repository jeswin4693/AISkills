import { describe, expect, it } from "vitest";
import { attentionItems, buildLabel, libraryOverview, MAX_ATTENTION } from "./dashboard";
import type { BuildSummary, RescanResult, ScanFinding, ScanStatus, SkillSummary, VersionInfo, VersionScan } from "./types";

const finding = (name: string, status: ScanFinding["status"] = "failed"): ScanFinding => ({ status, name, detail: `${name} detail`, was: "passed" });
const scan = (name: string, status: ScanStatus, over: Partial<VersionScan> = {}): VersionScan => ({ name, tag: "v2", status, findings: [], message: "", ...over });
const rescan = (...versions: VersionScan[]): RescanResult => ({ ok: versions.every((v) => v.status === "same"), counts: { same: 0, worse: 0, failing: 0, damaged: 0 }, versions });
const scans = (kind: string, ...versions: VersionScan[]) => ({ kind, label: `${kind}s`, result: rescan(...versions) });

const build = (id: string, status: BuildSummary["status"], over: Partial<BuildSummary> = {}): BuildSummary => ({
  id, kind: "skill", status, description: "Count TODO comments in a folder", created_at: "2026-11-25T10:00:00Z", updated_at: "2026-11-25T10:00:00Z",
  skill: "", draft: false, saved: null, ...over,
});

const READY = { provider: { configured: true, detail: "" }, sandbox: { available: true, reason: "" } };
const quiet = { scans: [scans("skill", scan("a", "same"))], builds: [build("1", "done", { saved: { name: "a", version: "v1" } })], ...READY };

describe("attentionItems", () => {
  it("lists nothing when nothing needs the person", () => {
    expect(attentionItems(quiet)).toEqual({ items: [], more: 0 });
  });

  it("says a version whose files are damaged is bad, with the reason, and links to it", () => {
    const { items } = attentionItems({ ...quiet, scans: [scans("skill", scan("a b", "damaged", { tag: "", message: "SKILL.md is missing" }))] });
    expect(items).toHaveLength(1);
    expect(items[0]).toMatchObject({ tone: "bad", title: "a b cannot be read", detail: "SKILL.md is missing", href: "/library/a%20b" });
  });

  it("gives a damaged version without a reason a plain one", () => {
    const { items } = attentionItems({ ...quiet, scans: [scans("skill", scan("a", "damaged", { tag: "" }))] });
    expect(items[0].detail).toBe("Its files are damaged or missing.");
  });

  it("says a version that fails checks today is bad, and names the first two checks and how many more", () => {
    const failing = scan("a", "failing", { findings: [finding("x"), finding("y"), finding("z"), finding("w", "warning")] });
    const { items } = attentionItems({ ...quiet, scans: [scans("skill", failing)] });
    expect(items[0]).toMatchObject({ tone: "bad", title: "a v2 fails 3 checks today", href: "/library/a" });
    expect(items[0].detail).toBe("x, y and 1 more");
  });

  it("uses the singular for one failing check and names it alone", () => {
    const { items } = attentionItems({ ...quiet, scans: [scans("skill", scan("a", "failing", { findings: [finding("only")] }))] });
    expect(items[0].title).toBe("a v2 fails 1 check today");
    expect(items[0].detail).toBe("only");
  });

  it("says a version whose checks got worse is a warning", () => {
    const worse = scan("a", "worse", { findings: [finding("x", "warning"), finding("y", "warning")] });
    const { items } = attentionItems({ ...quiet, scans: [scans("skill", worse)] });
    expect(items[0]).toMatchObject({ tone: "warn", title: "a v2: 2 checks got worse since it was imported", detail: "x, y" });
  });

  it("puts a kind other than skill in the link, and keeps two kinds with the same name apart", () => {
    const { items } = attentionItems({ ...quiet, scans: [scans("skill", scan("a", "damaged", { tag: "" })), scans("agent", scan("a", "damaged", { tag: "" }))] });
    expect(items.map((i) => i.href)).toEqual(["/library/a", "/library/a?kind=agent"]);
    expect(new Set(items.map((i) => i.key)).size).toBe(2);
  });

  it("turns each unfinished build into what the person should do about it", () => {
    const builds = [
      build("q", "awaiting_answers", { skill: "todo-counter" }),
      build("p", "awaiting_approval"),
      build("f", "failed", { skill: "broken" }),
      build("d", "done", { skill: "half", draft: true }),
      build("n", "done", { skill: "plain" }),
      build("w", "working"),
      build("s", "done", { skill: "kept", saved: { name: "kept", version: "v1" } }),
    ];
    const { items } = attentionItems({ ...quiet, builds });
    const by = Object.fromEntries(items.map((i) => [i.key, i]));
    expect(by["build:q"]).toMatchObject({ tone: "info", title: "Waiting for your answers: todo-counter", href: "/builder/q" });
    expect(by["build:p"]).toMatchObject({ tone: "info", title: "Waiting for your approval: Count TODO comments in a folder", href: "/builder/p" });
    expect(by["build:f"]).toMatchObject({ tone: "bad", title: "A build failed: broken", href: "/builder/f" });
    expect(by["build:d"]).toMatchObject({ tone: "warn", title: "A draft was not saved: half" });
    expect(by["build:n"]).toMatchObject({ tone: "info", title: "Finished, not saved to the library: plain" });
    expect(Object.keys(by).sort()).toEqual(["build:d", "build:f", "build:n", "build:p", "build:q"]); // working and saved ones are not asks
  });

  it("says when no model is set up, and when there is no sandbox, and says nothing while those are still unknown", () => {
    const { items } = attentionItems({ ...quiet, provider: { configured: false, detail: "LLM_PROVIDER is ''." }, sandbox: { available: false, reason: "No Linux container engine." } });
    expect(items.find((i) => i.key === "provider")).toMatchObject({ tone: "warn", title: "No AI model is set up", detail: "LLM_PROVIDER is ''.", href: "/settings" });
    expect(items.find((i) => i.key === "sandbox")).toMatchObject({ tone: "info", title: "The sandbox is not available", detail: "No Linux container engine.", href: null });
    expect(attentionItems({ scans: [], builds: [] })).toEqual({ items: [], more: 0 });
  });

  it("cuts a very long reason from the model or the sandbox to two hundred characters", () => {
    const long = "x".repeat(500);
    const { items } = attentionItems({ ...quiet, provider: { configured: false, detail: long }, sandbox: { available: false, reason: long } });
    for (const key of ["provider", "sandbox"]) {
      const detail = items.find((i) => i.key === key)!.detail;
      expect(detail).toHaveLength(200);
      expect(detail.endsWith("…")).toBe(true);
    }
  });

  it("lists the worst first and keeps the order the data came in within one tone", () => {
    const { items } = attentionItems({
      scans: [scans("skill", scan("w1", "worse", { findings: [finding("x", "warning")] }), scan("d1", "damaged", { tag: "" }), scan("w2", "worse", { findings: [finding("y", "warning")] }))],
      builds: [build("i1", "awaiting_answers"), build("b1", "failed"), build("i2", "awaiting_approval")],
      provider: { configured: false, detail: "" }, sandbox: { available: true, reason: "" },
    });
    expect(items.map((i) => i.key)).toEqual(["scan:skill:d1:", "build:b1", "scan:skill:w1:v2", "scan:skill:w2:v2", "provider", "build:i1", "build:i2"]);
  });

  it("shows at most ten and counts the rest", () => {
    expect(MAX_ATTENTION).toBe(10);
    const many = Array.from({ length: 13 }, (_, i) => scan(`s${i}`, "damaged", { tag: "" }));
    const { items, more } = attentionItems({ ...quiet, scans: [scans("skill", ...many)] });
    expect(items).toHaveLength(10);
    expect(more).toBe(3);
    expect(items[0].key).toBe("scan:skill:s0:"); // the first ten, in order
  });

  it("takes a smaller limit when asked", () => {
    const many = Array.from({ length: 5 }, (_, i) => scan(`s${i}`, "damaged", { tag: "" }));
    expect(attentionItems({ ...quiet, scans: [scans("skill", ...many)] }, 2)).toMatchObject({ more: 3 });
  });
});

describe("buildLabel", () => {
  it("prefers the skill's name", () => {
    expect(buildLabel({ skill: "todo-counter", description: "anything" })).toBe("todo-counter");
  });

  it("falls back to the person's words, on one line and cut at sixty characters", () => {
    expect(buildLabel({ skill: "", description: "Count  TODO\ncomments in a folder" })).toBe("Count TODO comments in a folder");
    const long = buildLabel({ skill: "", description: "word ".repeat(30) });
    expect(long.length).toBe(60);
    expect(long.endsWith("…")).toBe(true);
  });

  it("has a name for a build with neither", () => {
    expect(buildLabel({ skill: "", description: "   " })).toBe("(untitled)");
  });
});

const version = (name: string, created: string, tag = "v1"): VersionInfo => ({
  name, version: 1, tag, created_at: created, content_hash: "h", files: {}, source_kind: "folder", source_label: "", note: "", skill_version: "", checks: [],
});
const skill = (name: string, versions: number, created: string | null): SkillSummary => ({ name, versions, latest: created ? version(name, created) : null });

describe("libraryOverview", () => {
  it("counts the skills and versions of each kind, and in all", () => {
    const got = libraryOverview([
      { kind: "skill", label: "Skills", skills: [skill("a", 3, "2026-11-20T00:00:00Z"), skill("b", 1, "2026-11-21T00:00:00Z")] },
      { kind: "agent", label: "Agents", skills: [skill("c", 2, "2026-11-22T00:00:00Z")] },
    ]);
    expect(got.rows).toEqual([{ kind: "skill", label: "Skills", skills: 2, versions: 4 }, { kind: "agent", label: "Agents", skills: 1, versions: 2 }]);
    expect(got.total).toEqual({ skills: 3, versions: 6 });
  });

  it("lists the most recently saved versions first, across kinds, at most five, with a link that carries the kind", () => {
    const skills = ["2026-11-01", "2026-11-05", "2026-11-03", "2026-11-04", "2026-11-02", "2026-11-06"].map((d, i) => skill(`s${i}`, 1, `${d}T00:00:00Z`));
    const got = libraryOverview([{ kind: "skill", label: "Skills", skills }, { kind: "agent", label: "Agents", skills: [skill("ag", 1, "2026-11-07T00:00:00Z")] }]);
    expect(got.recent.map((r) => r.name)).toEqual(["ag", "s5", "s1", "s3", "s2"]);
    expect(got.recent[0]).toEqual({ kind: "agent", name: "ag", tag: "v1", created_at: "2026-11-07T00:00:00Z", href: "/library/ag?kind=agent" });
    expect(got.recent[1].href).toBe("/library/s5");
  });

  it("breaks a tie by name, and leaves out a skill with no readable latest version", () => {
    const got = libraryOverview([{ kind: "skill", label: "Skills", skills: [skill("b", 1, "2026-11-01T00:00:00Z"), skill("a", 1, "2026-11-01T00:00:00Z"), skill("broken", 1, null)] }]);
    expect(got.recent.map((r) => r.name)).toEqual(["a", "b"]);
    expect(got.rows[0].skills).toBe(3); // it is still one of the skills
  });

  it("says that a kind could not be read, and does not count it as empty", () => {
    const got = libraryOverview([{ kind: "skill", label: "Skills", skills: [skill("a", 1, "2026-11-01T00:00:00Z")] }, { kind: "agent", label: "Agents", error: "The API answered 500." }]);
    expect(got.rows[1]).toEqual({ kind: "agent", label: "Agents", skills: 0, versions: 0, error: "The API answered 500." });
    expect(got.total).toEqual({ skills: 1, versions: 1 });
  });

  it("is empty and zero for an empty library", () => {
    expect(libraryOverview([{ kind: "skill", label: "Skills", skills: [] }])).toEqual({ rows: [{ kind: "skill", label: "Skills", skills: 0, versions: 0 }], recent: [], total: { skills: 0, versions: 0 } });
    expect(libraryOverview([])).toEqual({ rows: [], recent: [], total: { skills: 0, versions: 0 } });
  });
});
