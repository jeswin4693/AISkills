import { afterEach, describe, expect, it, vi } from "vitest";
import { api } from "./api";
import { callText, controlSummary, costNote, draftNote, findingsOf, matchesPage, maxCallsText, observationBadge, outcomeInfo, progressText, runChoices, scanLine, severityTone, taskChoices, taskState, taskStateText } from "./scan";
import type { ScanObservation, ScanResult, ScanRunSummary, ScanTaskRun } from "./types";

afterEach(() => vi.unstubAllGlobals());

const reply = (status: number, body: unknown) => new Response(JSON.stringify(body), { status });

const obs = (kind: string, severity: string, detail: string, over: Partial<ScanObservation> = {}): ScanObservation => ({
  kind, severity, detail, tool: "", evidence: "", scenario: "t1", turn: 1, subject: "", ...over,
});
const task = (id: string, over: Partial<ScanTaskRun> = {}): ScanTaskRun => ({
  scenario: { id, message: `Task ${id}`, source: "fixed" }, condition: "with the skill", turns: [], reply: "", finished: true, error: "", observations: [], model_calls: 3, ...over,
});
const result = (over: Partial<ScanResult> = {}): ScanResult => ({
  outcome: "nothing_observed", verdict: "v", limits: "The tools were fake.", skill: "x", kind: "skill", runs: [], controls: [], not_run: [], calls: 10, runs_per_scenario: 1, controlled: true, ...over,
});

describe("the headline of a scan, written from the code the engine decided", () => {
  it.each([
    ["flagged", "bad", "Flagged"],
    ["unclear", "warn", "Unclear"],
    ["caution", "warn", "Caution"],
    ["incomplete", "warn", "Too little ran"],
    ["nothing_observed", "info", "Nothing suspicious observed"],
    ["not_run", "info", "Not run"],
  ])("%s is %s: %s", (code, tone, title) => {
    const info = outcomeInfo(code);
    expect(info.tone).toBe(tone);
    expect(info.title).toBe(title);
    expect(info.summary.length).toBeGreaterThan(20);
  });
  it("says evidence and not proof when nothing was observed, and never calls anything green", () => {
    expect(outcomeInfo("nothing_observed").summary).toContain("evidence, not proof");
    expect(outcomeInfo("nothing_observed").tone).not.toBe("ok");
  });
  it("names a code it does not know instead of guessing", () => {
    const info = outcomeInfo("brand_new");
    expect(info.tone).toBe("info");
    expect(info.summary).toContain("brand_new");
  });
  it("never says safe, in any headline", () => {
    for (const code of ["flagged", "unclear", "caution", "incomplete", "nothing_observed", "not_run", "brand_new"]) {
      const info = outcomeInfo(code);
      expect(`${info.title} ${info.summary}`).not.toMatch(/\bsafe\b/i);
    }
  });
});

describe("what a scan would cost, in words", () => {
  it("says at most, counts calls and says when one of them drafts a task", () => {
    expect(maxCallsText(61, true)).toBe("at most 61 model calls, counting the one that drafts a task");
    expect(maxCallsText(36, false)).toBe("at most 36 model calls");
    expect(maxCallsText(1, false)).toBe("at most 1 model call");
  });
  it("offers every number up to the limit, and at least one", () => {
    expect(runChoices(3)).toEqual([1, 2, 3]);
    expect(runChoices(0)).toEqual([1]);
    expect(taskChoices(6)).toEqual([1, 2, 3, 4, 5, 6]);
  });
  it("says where the run is", () => {
    expect(progressText({ done: 0, total: 0 })).toBe("Starting");
    expect(progressText({ done: 2, total: 5 })).toBe("Task run 3 of 5");
    expect(progressText({ done: 5, total: 5 })).toBe("Task run 5 of 5");
  });
});

describe("severity and the state of one task run", () => {
  it("tones a severity", () => {
    expect(severityTone("critical")).toBe("bad");
    expect(severityTone("high")).toBe("bad");
    expect(severityTone("medium")).toBe("warn");
    expect(severityTone("info")).toBe("neutral");
    expect(severityTone("something-else")).toBe("neutral");
  });
  it("never shows an unfinished run as finished", () => {
    expect(taskState({ finished: true, error: "" })).toBe("finished");
    expect(taskState({ finished: false, error: "the model said no" })).toBe("stopped");
    expect(taskState({ finished: false, error: "" })).toBe("unfinished");
    expect(taskState({ finished: true, error: "late error" })).toBe("stopped");
    expect(taskStateText("finished")).toBe("finished");
    expect(taskStateText("stopped")).toBe("stopped early");
    expect(taskStateText("unfinished")).toBe("did not finish in the steps allowed");
  });
});

describe("the findings of a scan", () => {
  it("lists those of the runs with the skill, most serious first, each with its task and step", () => {
    const r = result({
      runs: [
        task("a", { observations: [obs("unknown_tool", "info", "used a tool it does not have", { turn: 2 }), obs("installs", "medium", "installed a package", { turn: 1 })] }),
        task("b", { observations: [obs("canary_sent", "critical", "sent a secret away", { scenario: "b", turn: 3 })] }),
      ],
      controls: [task("a", { condition: "control (without it)", observations: [obs("reads_secret", "critical", "the bare model read a secret")] })],
    });
    const found = findingsOf(r);
    expect(found.map((f) => f.severity)).toEqual(["critical", "medium", "info"]);
    expect(found[0]).toMatchObject({ taskId: "b", task: "Task b", step: 3, kind: "canary_sent", detail: "sent a secret away" });
    expect(found.some((f) => f.detail.includes("bare model"))).toBe(false); // a control's finding is not the skill's
  });
  it("is empty when nothing was observed, and puts an unknown severity last", () => {
    expect(findingsOf(result({ runs: [task("a")] }))).toEqual([]);
    const odd = findingsOf(result({ runs: [task("a", { observations: [obs("x", "weird", "d1"), obs("y", "medium", "d2")] })] }));
    expect(odd.map((f) => f.severity)).toEqual(["medium", "weird"]);
  });
  it("says what the same task did without the skill", () => {
    expect(controlSummary(result({ runs: [task("a")] }), "a")).toBeNull();
    const none = result({ controls: [task("a", { condition: "control (without it)" })] });
    expect(controlSummary(none, "a")).toBe("The same task without the skill: nothing observed.");
    const some = result({ controls: [task("a", { condition: "control (without it)", observations: [obs("reads_secret", "high", "d"), obs("reads_secret", "high", "d"), obs("canary_sent", "critical", "d")] })] });
    expect(controlSummary(some, "a")).toBe("The same task without the skill also did: canary_sent, reads_secret.");
    expect(controlSummary(some, "zzz")).toBeNull();
  });
  it("writes a tool call as plain text, leaving out what is empty", () => {
    expect(callText({ tool: "http_request", target: "https://x.test/a", content: "k=1", method: "POST" })).toBe('http_request(target="https://x.test/a", content="k=1", method="POST")');
    expect(callText({ tool: "list_files", target: "/work", content: "", method: "" })).toBe('list_files(target="/work")');
    expect(callText({ tool: "x" })).toBe("x()");
  });
});

describe("one line for the list of earlier scans", () => {
  const base: ScanRunSummary = {
    id: "a".repeat(32), status: "done", kind: "skill", name: "s", version: 1, tag: "v1", content_hash: "h", runs: 1, scenarios: 5, control: true, draft: true,
    progress: { done: 5, total: 5 }, error: "", retryable: false, created_at: "", updated_at: "", summary: { outcome: "flagged", calls: 40, findings: 7, finished: 5, total: 5 },
  };
  it("says the headline, the findings and how many task runs finished", () => {
    expect(scanLine(base)).toBe("Flagged: 7 findings, 5 of 5 task runs finished");
    expect(scanLine({ ...base, summary: { outcome: "nothing_observed", calls: 30, findings: 0, finished: 3, total: 5 } })).toBe("Nothing suspicious observed: no findings, 3 of 5 task runs finished");
    expect(scanLine({ ...base, summary: { outcome: "caution", calls: 30, findings: 1, finished: 5, total: 5 } })).toBe("Caution: 1 finding, 5 of 5 task runs finished");
  });
  it("says so when it is still going or did not finish", () => {
    expect(scanLine({ ...base, status: "working", summary: null })).toBe("still running");
    expect(scanLine({ ...base, status: "failed", summary: null })).toBe("did not finish");
  });
});

describe("the five calls", () => {
  it("previews with everything in the address, encoded", async () => {
    const f = vi.fn().mockResolvedValue(reply(200, { tasks: [] }));
    vi.stubGlobal("fetch", f);
    await api.scanPreview({ name: "my skill&x", version: 2, kind: "agent", runs: 2, scenarios: 3, control: false, draft: false });
    const url = String(f.mock.calls[0][0]);
    expect(url).toContain("/api/scans/preview?");
    expect(url).toContain("name=my+skill%26x");
    expect(url).toContain("version=2");
    expect(url).toContain("kind=agent");
    expect(url).toContain("runs=2");
    expect(url).toContain("scenarios=3");
    expect(url).toContain("control=false");
    expect(url).toContain("draft=false");
  });
  it("starts with POST and the options as the server names them", async () => {
    const f = vi.fn().mockResolvedValue(reply(201, { id: "a".repeat(32) }));
    vi.stubGlobal("fetch", f);
    await api.startScan({ name: "s", version: 1, kind: "skill", runs: 2, scenarios: 4, control: true, draft: false });
    expect(f.mock.calls[0][1].method).toBe("POST");
    expect(String(f.mock.calls[0][0])).toContain("/api/scans");
    expect(JSON.parse(f.mock.calls[0][1].body)).toEqual({ name: "s", version: 1, kind: "skill", runs: 2, scenarios: 4, control: true, draft: false });
  });
  it("lists with the name and version asked for, reads one, and retries one", async () => {
    const f = vi.fn().mockResolvedValue(reply(200, []));
    vi.stubGlobal("fetch", f);
    await api.scanRuns({ name: "s", version: 2 });
    expect(String(f.mock.calls[0][0])).toContain("/api/scans?name=s&version=2");
    await api.scanRuns();
    expect(String(f.mock.calls[1][0])).toMatch(/\/api\/scans$/);
    await api.scanRun("a".repeat(32));
    expect(String(f.mock.calls[2][0])).toContain(`/api/scans/${"a".repeat(32)}`);
    await api.retryScan("a".repeat(32));
    expect(f.mock.calls[3][1].method).toBe("POST");
    expect(String(f.mock.calls[3][0])).toContain(`/api/scans/${"a".repeat(32)}/retry`);
  });
  it("raises the server's own words when a scan is refused", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(reply(429, { detail: "You already have 2 runs working at once." })));
    await expect(api.startScan({ name: "s", runs: 1, scenarios: 5, control: true, draft: true })).rejects.toMatchObject({ status: 429, message: "You already have 2 runs working at once." });
  });
});

describe("the review's findings (2026-11-27)", () => {
  it("does not blame the skill when no control run was made", () => {
    const controlled = outcomeInfo("flagged", true);
    expect(controlled.summary).toContain("likely cause");
    const uncontrolled = outcomeInfo("flagged", false);
    expect(uncontrolled.summary).toContain("No control run was made");
    expect(uncontrolled.summary).not.toContain("likely cause");
    expect(uncontrolled.tone).toBe("bad"); // still serious: only what is claimed about the cause changes
    expect(`${uncontrolled.title} ${uncontrolled.summary}`).not.toMatch(/\bsafe\b/i);
  });
  it("says what the control runs did, all of them, and never reads an unfinished control as clean", () => {
    const stopped = result({ controls: [task("a", { condition: "control (without it)", finished: false, error: "the model said no" })] });
    const text = controlSummary(stopped, "a") ?? "";
    expect(text).toContain("did not finish");
    expect(text).not.toBe("The same task without the skill: nothing observed.");
    const repeats = result({
      controls: [task("a", { condition: "control (without it)" }), task("a", { condition: "control (without it)", observations: [obs("reads_secret", "high", "d")] })],
    });
    expect(controlSummary(repeats, "a")).toBe("The same task without the skill also did: reads_secret.");
    const mixed = result({
      controls: [task("a", { condition: "control (without it)" }), task("a", { condition: "control (without it)", finished: false, error: "x" })],
    });
    expect(controlSummary(mixed, "a")).toContain("1 of 2 control runs did not finish");
  });
  it("shows nothing-observed only for a task run that finished", () => {
    expect(observationBadge(task("a"))).toEqual({ text: "nothing observed", tone: "neutral" });
    expect(observationBadge(task("a", { finished: false }))).toBeNull();
    expect(observationBadge(task("a", { finished: false, error: "stopped" }))).toBeNull();
    expect(observationBadge(task("a", { observations: [obs("x", "medium", "d")] }))).toEqual({ text: "1 finding", tone: "warn" });
    expect(observationBadge(task("a", { finished: false, observations: [obs("x", "medium", "d"), obs("y", "high", "d")] }))).toEqual({ text: "2 findings", tone: "warn" });
  });
  it("shows a scan only on the page of the kind, entry and version it is about", () => {
    const run = { kind: "agent", name: "reviewer", version: 1 };
    expect(matchesPage(run, { kind: "agent", name: "reviewer", version: 1 })).toBe(true);
    expect(matchesPage(run, { kind: "skill", name: "reviewer", version: 1 })).toBe(false);
    expect(matchesPage(run, { kind: "agent", name: "other", version: 1 })).toBe(false);
    expect(matchesPage(run, { kind: "agent", name: "reviewer", version: 2 })).toBe(false);
  });
  it("asks the list for the kind", async () => {
    const f = vi.fn().mockResolvedValue(reply(200, []));
    vi.stubGlobal("fetch", f);
    await api.scanRuns({ name: "reviewer", version: 1, kind: "agent" });
    expect(String(f.mock.calls[0][0])).toContain("kind=agent");
    await api.scanRuns({ name: "reviewer", version: 1, kind: "skill" });
    expect(String(f.mock.calls[1][0])).toContain("kind=skill"); // always, so a skill's page never gets an agent's scans
  });
  it("says the truth about the tasks a model may draft and about the calls that are extra", () => {
    const note = draftNote("skill", 6);
    expect(note).toContain("up to three");
    expect(note).toContain("take the place of some");
    expect(note).toContain("no more than 6");
    expect(note).not.toContain("one more task");
    expect(costNote()).toContain("on top");
  });
});
