import { describe, expect, it } from "vitest";
import {
  canPreview, hookWhen, isPicked, keepRequest, nameHint, optionProblem, optionTextId, parseOptionText, partLabel, pluginRequest, serverPowers, setOption,
  togglePick, withoutOptionTexts, type ComponentPick,
} from "./plugin";
import type { HookInfo } from "./types";

const skill: ComponentPick = { kind: "skill", name: "demo-skill" };
const agent: ComponentPick = { kind: "agent", name: "demo-agent" };
const server: ComponentPick = { kind: "mcp", name: "word-tools" };
const secrets: ComponentPick = { kind: "hook", name: "block-secret-files" };
const option = {
  key: "also", label: "More file names to protect", help: "File names or patterns.", max_items: 3, max_length: 20,
  pattern: "(?=.*[A-Za-z0-9])[A-Za-z0-9._*?][A-Za-z0-9._*?-]{0,59}",
};
const hooks: HookInfo[] = [
  { id: "block-secret-files", title: "Keep secret files out of reach", summary: "s", event: "PreToolUse", matcher: "Read|Write", effect: "blocks", sees: "x", timeout: 10, powers: [], revision: 1, options: [option] },
  { id: "log-tool-calls", title: "Log", summary: "s", event: "PostToolUse", matcher: "", effect: "observes", sees: "x", timeout: 10, powers: ["write_files"], revision: 1, options: [] },
];

describe("a hook as a part of a plugin", () => {
  it("is told apart from other parts, carries its options without changing the list it was given, and is requested with them", () => {
    const none: ComponentPick[] = [secrets, skill];
    const set = setOption(none, secrets, "also", ["secrets.json", "*.token"]);
    expect(set).toEqual([{ ...secrets, options: { also: ["secrets.json", "*.token"] } }, skill]);
    expect(none).toEqual([secrets, skill]);
    expect(isPicked(set, secrets)).toBe(true);
    expect(isPicked([skill], { kind: "hook", name: "demo-skill" })).toBe(false);
    const form = { name: "my-plugin", description: "Safety hooks.", author: "" };
    expect(pluginRequest(form, set).components).toEqual([{ kind: "hook", name: "block-secret-files", options: { also: ["secrets.json", "*.token"] } }, { kind: "skill", name: "demo-skill" }]);
    expect(pluginRequest(form, [secrets]).components).toEqual([{ kind: "hook", name: "block-secret-files" }]); // no empty options are sent
    expect(pluginRequest(form, setOption([secrets], secrets, "also", [])).components).toEqual([{ kind: "hook", name: "block-secret-files" }]);
  });

  it("keeps its options when the request is pinned for keeping, and is not given a version (the catalogue has none)", () => {
    const form = { name: "my-plugin", description: "Safety hooks.", author: "" };
    const request = pluginRequest(form, setOption([secrets], secrets, "also", ["a.key"]));
    const kept = keepRequest(request, [{ kind: "hook", name: "block-secret-files", version: "r1" }]);
    expect(kept.components).toEqual([{ kind: "hook", name: "block-secret-files", options: { also: ["a.key"] } }]);
  });

  it("reads the words a person types into a list of names", () => {
    expect(parseOptionText("secrets.json, *.token\n  other.key ,, secrets.json ")).toEqual(["secrets.json", "*.token", "other.key"]);
    expect(parseOptionText("   ")).toEqual([]);
    expect(parseOptionText("a b")).toEqual(["a", "b"]);
  });

  it("explains an option value early, from the pattern the server gave, and leaves the final say to the server", () => {
    expect(optionProblem(option, ["secrets.json", "*.token"])).toBe("");
    expect(optionProblem(option, [])).toBe("");
    expect(optionProblem(option, ["a;rm -rf /"])).toMatch(/not allowed/);
    expect(optionProblem(option, ["--force"])).toMatch(/not allowed/);
    expect(optionProblem(option, ["*"])).toMatch(/not allowed/);
    expect(optionProblem(option, ["x".repeat(21)])).toMatch(/at most 20/);
    expect(optionProblem(option, ["a", "b", "c", "d"])).toMatch(/at most 3/i);
    expect(optionProblem({ ...option, pattern: "(" }, ["x"])).toBe(""); // a pattern the browser cannot read is not a reason to stop the person
  });

  it("cannot be previewed while an option the server would refuse is in the form", () => {
    const form = { name: "my-plugin", description: "Safety hooks.", author: "" };
    expect(canPreview(form, [secrets], hooks)).toBe(true);
    expect(canPreview(form, setOption([secrets], secrets, "also", ["ok.key"]), hooks)).toBe(true);
    expect(canPreview(form, setOption([secrets], secrets, "also", ["a;b"]), hooks)).toBe(false);
    expect(canPreview(form, setOption([secrets], secrets, "also", ["a;b"]))).toBe(true); // the catalogue has not loaded: the server will say
  });

  it("forgets what was typed in a hook's option boxes when the hook is unticked, so ticking it again never shows text the request does not carry", () => {
    const texts = { "hook-block-secret-files-also": "secrets.json, *.token", "hook-block-force-push-x": "keep", "hook-block-secret-files-other": "gone too" };
    expect(optionTextId(secrets, "also")).toBe("hook-block-secret-files-also");
    expect(withoutOptionTexts(texts, secrets)).toEqual({ "hook-block-force-push-x": "keep" });
    expect(texts["hook-block-secret-files-also"]).toBe("secrets.json, *.token"); // the object it was given is not changed
    expect(withoutOptionTexts(texts, { kind: "skill", name: "block-secret-files" })).toEqual(texts); // only a hook has option boxes
  });

  it("is called a hook, and says in plain words when it runs", () => {
    expect(partLabel("hook")).toBe("hook");
    expect(hookWhen(hooks[0])).toBe("before Claude uses Read, Write");
    expect(hookWhen(hooks[1])).toBe("after Claude uses any tool");
    expect(hookWhen({ event: "PreToolUse", matcher: "Bash" })).toBe("before Claude uses Bash");
    expect(hookWhen({ event: "SessionStart", matcher: "" })).toBe("on SessionStart");
  });
});

describe("an MCP server as a part of a plugin", () => {
  it("is told apart from a skill or an agent of the same name, requested as mcp and pinned like the others", () => {
    const sameName: ComponentPick = { kind: "mcp", name: "demo-skill" };
    expect(isPicked([skill], sameName)).toBe(false);
    expect(togglePick([skill, server], server)).toEqual([skill]);
    const form = { name: "my-plugin", description: "Word tools.", author: "" };
    const request = pluginRequest(form, [server]);
    expect(request.components).toEqual([{ kind: "mcp", name: "word-tools" }]);
    expect(canPreview(form, [server])).toBe(true); // a server alone is enough for a plugin
    expect(keepRequest(request, [{ kind: "mcp", name: "word-tools", version: "v3" }]).components).toEqual([{ kind: "mcp", name: "word-tools", version: 3 }]);
  });

  it("is called an MCP server, and what its code can do is said in plain words, with an unknown one kept as it is", () => {
    expect(partLabel("mcp")).toBe("MCP server");
    expect(partLabel("agent")).toBe("agent");
    expect(serverPowers(["network", "run_commands", "teleport"])).toEqual(["reach the network", "start other programs", "teleport"]);
    expect(serverPowers([])).toEqual([]);
  });
});

describe("choosing the parts of a plugin", () => {
  it("adds a part, then takes it out again, without changing the list it was given", () => {
    const none: ComponentPick[] = [];
    const one = togglePick(none, skill);
    expect(one).toEqual([skill]);
    expect(none).toEqual([]);
    expect(togglePick(togglePick(one, agent), skill)).toEqual([agent]);
  });

  it("tells a skill from an agent that has the same name", () => {
    const sameName: ComponentPick = { kind: "agent", name: "demo-skill" };
    expect(isPicked([skill], sameName)).toBe(false);
    expect(isPicked([skill, sameName], sameName)).toBe(true);
    expect(togglePick([skill], sameName)).toEqual([skill, sameName]);
  });
});

describe("the plugin request", () => {
  const form = { name: "  my-plugin ", description: " Two helpers. ", author: " Jeswin " };

  it("trims the words and lists the parts in the order they were chosen", () => {
    expect(pluginRequest(form, [agent, skill])).toEqual({
      name: "my-plugin", description: "Two helpers.", author: "Jeswin",
      components: [{ kind: "agent", name: "demo-agent" }, { kind: "skill", name: "demo-skill" }],
    });
  });

  it("can only be previewed with a name, a description and at least one part", () => {
    expect(canPreview(form, [skill])).toBe(true);
    expect(canPreview(form, [])).toBe(false);
    expect(canPreview({ ...form, name: "  " }, [skill])).toBe(false);
    expect(canPreview({ ...form, description: "" }, [skill])).toBe(false);
    expect(canPreview({ ...form, name: "Claude-x" }, [skill])).toBe(false); // a name the server would refuse
  });
});

describe("the name hint", () => {
  it("says nothing for a good name or an empty box", () => {
    expect(nameHint("my-plugin")).toBe("");
    expect(nameHint("")).toBe("");
    expect(nameHint("a1-b2")).toBe("");
  });

  it("explains a reserved start, capitals, spaces, stray hyphens and a name that is too long", () => {
    expect(nameHint("claude-helpers")).toMatch(/reserved/);
    expect(nameHint("anthropic-x")).toMatch(/reserved/);
    for (const bad of ["Bad", "has space", "-x", "x-", "a--b", "a_b"]) expect(nameHint(bad)).toMatch(/lowercase/);
    expect(nameHint("a".repeat(65))).toMatch(/64/);
  });
});

describe("keeping exactly what was previewed", () => {
  const form = { name: "my-plugin", description: "Two helpers.", author: "" };

  it("pins each component to the version the preview used, so a newer version cannot slip in between", () => {
    const request = pluginRequest(form, [skill, agent]);
    const kept = keepRequest(request, [
      { kind: "skill", name: "demo-skill", version: "v2" },
      { kind: "agent", name: "demo-agent", version: "v1" },
    ]);
    expect(kept.components).toEqual([
      { kind: "skill", name: "demo-skill", version: 2 },
      { kind: "agent", name: "demo-agent", version: 1 },
    ]);
    expect(kept.name).toBe("my-plugin");
    expect(request.components).toEqual([{ kind: "skill", name: "demo-skill" }, { kind: "agent", name: "demo-agent" }]); // the request itself is not changed
  });

  it("leaves a component unpinned when the preview did not name it or gave a version that cannot be read", () => {
    const request = pluginRequest(form, [skill, agent]);
    const kept = keepRequest(request, [{ kind: "skill", name: "demo-skill", version: "latest" }]);
    expect(kept.components).toEqual([{ kind: "skill", name: "demo-skill" }, { kind: "agent", name: "demo-agent" }]);
  });
});
