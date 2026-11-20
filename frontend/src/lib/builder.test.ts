import { afterEach, describe, expect, it, vi } from "vitest";
import { api } from "./api";
import {
  DEFAULT_SLOTS, activityText, answersToSend, canSendAnswers, elapsedSeconds, kindLabel, parseTests, progressSteps, showKindPicker, slotsOf,
  specRows, statusInfo, tokenLine, traceability, usageText,
} from "./builder";
import type { KindInfo, RequirementSpec, TestCase } from "./types";

afterEach(() => vi.unstubAllGlobals());

const spec: RequirementSpec = {
  kind: "skill", goal: "Count TODO comments", inputs: ["a folder"], outputs: ["a report"], constraints: ["never edit files"],
  acceptance_criteria: ["lists every file"], failure_behavior: "stop and say so",
  quotes: { goal: "counts TODO", inputs: "in a folder", constraints: "never edit" }, user_words: "", rounds: 2,
};

describe("the requirement as rows", () => {
  it("lists the six checklist items in order, each next to the person's own words", () => {
    const rows = specRows(spec);
    expect(rows.map((r) => r.slot)).toEqual(["goal", "inputs", "outputs", "constraints", "acceptance_criteria", "failure_behavior"]);
    expect(rows[0]).toMatchObject({ label: "Goal", values: ["Count TODO comments"], quote: "counts TODO" });
    expect(rows[3].quote).toBe("never edit");
    expect(rows[2].quote).toBe(""); // no quote recorded: shown as such, never invented
    expect(rows[5].values).toEqual(["stop and say so"]); // a single text becomes a one-item list
  });

  it("gives an empty list for an empty text item", () => {
    expect(specRows({ ...spec, failure_behavior: "" })[5].values).toEqual([]);
  });
});

describe("kinds", () => {
  const skill: KindInfo = {
    key: "skill", label: "Skill", install_targets: ["personal", "folder"],
    slots: DEFAULT_SLOTS.map((s) => ({ ...s, question: "?" })),
  };
  const agent: KindInfo = {
    key: "agent", label: "Agent", install_targets: ["personal"],
    slots: [{ key: "goal", label: "What the agent is for", question: "?" }, { key: "constraints", label: "What it must never do", question: "?" }],
  };

  it("shows the picker only when there is something to choose", () => {
    expect(showKindPicker(undefined)).toBe(false);
    expect(showKindPicker([])).toBe(false);
    expect(showKindPicker([skill])).toBe(false);
    expect(showKindPicker([skill, agent])).toBe(true);
  });

  it("builds the requirement rows from the slots the server lists for the kind", () => {
    const rows = specRows(spec, agent.slots);
    expect(rows.map((r) => r.slot)).toEqual(["goal", "constraints"]);
    expect(rows[0]).toMatchObject({ label: "What the agent is for", values: ["Count TODO comments"], quote: "counts TODO" });
    expect(rows[1].values).toEqual(["never edit files"]);
  });

  it("falls back to the built-in skill rows when the server does not list the kind", () => {
    expect(slotsOf(undefined, "skill")).toEqual(DEFAULT_SLOTS);
    expect(slotsOf([agent], "skill")).toEqual(DEFAULT_SLOTS);
    expect(slotsOf([skill, agent], "agent")).toEqual(agent.slots);
    expect(specRows(spec, slotsOf([agent], "skill"))).toEqual(specRows(spec));
  });

  it("names a kind by its label, or by its key when the server does not list it", () => {
    expect(kindLabel([skill, agent], "agent")).toBe("Agent");
    expect(kindLabel(undefined, "skill")).toBe("skill");
    expect(kindLabel([skill], "gone")).toBe("gone");
  });
});

describe("answers", () => {
  const questions = [{ slot: "constraints", text: "?" }, { slot: "outputs", text: "?" }];
  it("needs at least one real answer", () => {
    expect(canSendAnswers(questions, {})).toBe(false);
    expect(canSendAnswers(questions, { constraints: "   " })).toBe(false);
    expect(canSendAnswers(questions, { outputs: "a list" })).toBe(true);
  });
  it("sends only what was answered, trimmed, and only for questions that were asked", () => {
    expect(answersToSend(questions, { constraints: "  none ", outputs: "", goal: "sneaky" })).toEqual({ constraints: "none" });
  });
});

describe("status and activity", () => {
  it("names each state in plain words", () => {
    expect(statusInfo("awaiting_answers")).toEqual({ label: "Needs your answers", tone: "warn" });
    expect(statusInfo("failed").tone).toBe("bad");
    expect(statusInfo("done").label).toBe("Built");
  });
  it("says what the background job is doing", () => {
    const job = (kind: "understand" | "build") => ({ kind, status: "running" as const, started_at: null, finished_at: null, events: [] });
    expect(activityText(null)).toBe("Starting");
    expect(activityText(job("understand"))).toContain("Reading your words");
    expect(activityText(job("build"))).toContain("Writing the skill");
  });
  it("counts elapsed seconds, never negative, and 0 for a missing or broken time", () => {
    const now = new Date("2026-11-19T12:00:30Z").getTime();
    expect(elapsedSeconds("2026-11-19T12:00:00Z", now)).toBe(30);
    expect(elapsedSeconds("2026-11-19T12:01:00Z", now)).toBe(0);
    expect(elapsedSeconds(null, now)).toBe(0);
    expect(elapsedSeconds("nonsense", now)).toBe(0);
  });
});

describe("traceability: each criterion next to the tests that cover it", () => {
  const tests: TestCase[] = [
    { name: "finds a pair", kind: "positive", input_description: "", expected_result: "", covers: ["AC1"] },
    { name: "unreadable path", kind: "negative", input_description: "", expected_result: "", covers: ["AC1", "AC2"] },
  ];
  it("numbers criteria the way the builder does and attaches the tests", () => {
    const t = traceability(["lists every pair", "stops on a bad path"], tests);
    expect(t.map((x) => x.id)).toEqual(["AC1", "AC2"]);
    expect(t[0].tests.map((x) => x.name)).toEqual(["finds a pair", "unreadable path"]);
    expect(t[1].tests.map((x) => x.name)).toEqual(["unreadable path"]);
  });
  it("skips empty items and 'none' without shifting the numbering of the rest", () => {
    const t = traceability(["", "None", "works"], [{ ...tests[0], covers: ["AC1"] }]);
    expect(t).toHaveLength(1);
    expect(t[0]).toMatchObject({ id: "AC1", text: "works" });
    expect(t[0].tests).toHaveLength(1);
  });
  it("shows a criterion no test covers as having no tests, not as covered", () => {
    expect(traceability(["x"], [])[0].tests).toEqual([]);
  });
  it("reads tests.json defensively", () => {
    expect(parseTests("not json")).toEqual([]);
    expect(parseTests('{"a":1}')).toEqual([]);
    expect(parseTests('[{"name":"a","kind":"positive","covers":["AC1",5]},{"kind":"x"},7]')).toEqual([
      { name: "a", kind: "positive", input_description: "", expected_result: "", covers: ["AC1"] },
    ]);
  });
});

describe("the progress strip", () => {
  const strip = (s: Parameters<typeof progressSteps>[0]) => progressSteps(s).map((x) => `${x.label}:${x.state}`).join(" ");
  const job = (kind: "understand" | "build") => ({ kind, status: "running" as const, started_at: null, finished_at: null, events: [] });

  it("starts by reading the words", () => {
    expect(strip({ status: "working", round: 1, job: job("understand"), saved: null })).toBe("Describe:current Answer:todo Approve:todo Build:todo Save:todo");
  });
  it("waits at each step where the person acts", () => {
    expect(strip({ status: "awaiting_answers", round: 1, job: null, saved: null })).toBe("Describe:done Answer:current Approve:todo Build:todo Save:todo");
    expect(strip({ status: "awaiting_approval", round: 2, job: null, saved: null })).toBe("Describe:done Answer:done Approve:current Build:todo Save:todo");
  });
  it("shows the build, then the save, then everything done", () => {
    expect(strip({ status: "working", round: 2, job: job("build"), saved: null })).toBe("Describe:done Answer:done Approve:done Build:current Save:todo");
    expect(strip({ status: "done", round: 2, job: job("build"), saved: null })).toBe("Describe:done Answer:done Approve:done Build:done Save:current");
    expect(strip({ status: "done", round: 2, job: job("build"), saved: { name: "x", version: "v1" } })).toBe("Describe:done Answer:done Approve:done Build:done Save:done");
  });
  it("marks the step that failed", () => {
    expect(strip({ status: "failed", round: 2, job: job("build"), saved: null })).toContain("Build:failed");
    expect(strip({ status: "failed", round: 1, job: job("understand"), saved: null })).toContain("Describe:failed");
  });
});

describe("the builder's api calls", () => {
  const reply = (status: number, body: unknown) => new Response(JSON.stringify(body), { status });

  it("sends the description and the scripts choice with the names the API expects", async () => {
    const f = vi.fn().mockResolvedValue(reply(201, { id: "a".repeat(32) }));
    vi.stubGlobal("fetch", f);
    await api.startBuild("A skill that does something", true);
    expect(JSON.parse(f.mock.calls[0][1].body)).toEqual({ description: "A skill that does something", with_scripts: true });
  });

  it("sends a kind other than skill, and leaves it out for a skill so that request is unchanged", async () => {
    const f = vi.fn().mockImplementation(() => Promise.resolve(reply(201, { id: "a".repeat(32) })));
    vi.stubGlobal("fetch", f);
    await api.startBuild("An agent that reviews code", false, "agent");
    await api.startBuild("A skill that does something", false);
    expect(JSON.parse(f.mock.calls[0][1].body)).toEqual({ description: "An agent that reviews code", with_scripts: false, kind: "agent" });
    expect(JSON.parse(f.mock.calls[1][1].body)).toEqual({ description: "A skill that does something", with_scripts: false });
  });

  it("asks which kinds there are", async () => {
    const f = vi.fn().mockResolvedValue(reply(200, []));
    vi.stubGlobal("fetch", f);
    await api.kinds();
    expect(String(f.mock.calls[0][0])).toMatch(/\/api\/kinds$/);
  });

  it("adds ?kind= to the library calls only for a kind other than skill, so every skill URL is unchanged", async () => {
    const f = vi.fn().mockImplementation(() => Promise.resolve(reply(200, {})));
    vi.stubGlobal("fetch", f);
    await api.listSkills();
    await api.listSkills("skill");
    await api.listSkills("agent");
    await api.versions("demo", "agent");
    await api.diff("demo", 1, 2, "agent");
    await api.file("demo", 1, "a/b.txt", "agent");
    await api.rescan("demo", "agent");
    await api.rescan(undefined, "agent");
    await api.rollback("demo", 2, "agent");
    await api.install("demo", { target: "personal" }, "agent");
    await api.importZip(new File(["x"], "a.zip"), { kind: "agent" });
    await api.importZip(new File(["x"], "a.zip"));
    const urls = f.mock.calls.map((c) => String(c[0]).replace(/^https?:\/\/[^/]+/, ""));
    expect(urls).toEqual([
      "/api/library", "/api/library", "/api/library?kind=agent", "/api/library/demo?kind=agent",
      "/api/library/demo/diff?frm=1&to=2&kind=agent", "/api/library/demo/versions/1/files/a/b.txt?kind=agent",
      "/api/rescan?name=demo&kind=agent", "/api/rescan?kind=agent", "/api/library/demo/rollback?kind=agent",
      "/api/library/demo/install?kind=agent", "/api/library/import?filename=a.zip&kind=agent", "/api/library/import?filename=a.zip",
    ]);
  });

  it("adds the kind to an export too", async () => {
    const f = vi.fn().mockImplementation(() => Promise.resolve(new Response("zip", { status: 200, headers: { "Content-Disposition": 'attachment; filename="a-v1.zip"' } })));
    vi.stubGlobal("fetch", f);
    await api.exportZip("demo", 1, false, "agent");
    await api.exportZip("demo", 1, false);
    expect(String(f.mock.calls[0][0])).toContain("kind=agent");
    expect(String(f.mock.calls[1][0])).not.toContain("kind=");
  });

  it("returns a refused save as a result, but raises for a draft that was not accepted", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValueOnce(reply(422, { refused: true, checks: [] })).mockResolvedValueOnce(reply(409, { detail: "This skill is a DRAFT" })));
    expect((await api.saveBuild("x".repeat(32))).refused).toBe(true);
    await expect(api.saveBuild("x".repeat(32))).rejects.toMatchObject({ status: 409, message: "This skill is a DRAFT" });
  });

  it("discards with DELETE and raises the server's message when it is still running", async () => {
    const f = vi.fn().mockResolvedValueOnce(reply(200, { discarded: true })).mockResolvedValueOnce(reply(409, { detail: "It is still running." }));
    vi.stubGlobal("fetch", f);
    await api.discardBuild("a".repeat(32));
    expect(f.mock.calls[0][1].method).toBe("DELETE");
    await expect(api.discardBuild("a".repeat(32))).rejects.toMatchObject({ status: 409 });
  });

  it("refuses a generated file path that is not a plain path", async () => {
    vi.stubGlobal("fetch", vi.fn());
    await expect(Promise.resolve().then(() => api.buildFile("a".repeat(32), "../x"))).rejects.toMatchObject({ status: 400 });
  });
});

describe("what using the skill costs", () => {
  it("says what is paid on every task and what only when the skill is used, and that these are estimates", () => {
    expect(tokenLine({ always: 56, when_used: 1299, on_demand: 1703 })).toBe(
      "Costs about 56 tokens on every task (its name and description) and 1,299 more when the agent uses it. Estimates.",
    );
  });

  it("shows nothing for a session saved before the cost was worked out", () => {
    expect(tokenLine(undefined)).toBeNull();
    expect(tokenLine(null)).toBeNull();
  });
});

describe("what the model was asked, in words", () => {
  it("counts attempts, says how many failed, gives the tokens the provider reported and the model", () => {
    expect(usageText({ calls: 5, errors: 1, input_tokens: 6100, output_tokens: 2000, models: ["gemini-3.5-flash-lite"] })).toBe(
      "5 attempts at the model (1 failed) · 6,100 tokens in and 2,000 out · gemini-3.5-flash-lite.",
    );
  });

  it("says plainly when a provider reported no token counts, and lists every model used", () => {
    expect(usageText({ calls: 1, errors: 0, input_tokens: null, output_tokens: null, models: ["a", "b"] })).toBe(
      "1 attempt at the model · no token counts reported · a, b.",
    );
  });

  it("shows nothing when there was no attempt, or the server did not send usage", () => {
    expect(usageText({ calls: 0, errors: 0, input_tokens: null, output_tokens: null, models: [] })).toBe("");
    expect(usageText(undefined)).toBe("");
  });
});
