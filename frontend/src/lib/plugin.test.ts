import { describe, expect, it } from "vitest";
import { canPreview, isPicked, keepRequest, nameHint, pluginRequest, togglePick, type ComponentPick } from "./plugin";

const skill: ComponentPick = { kind: "skill", name: "demo-skill" };
const agent: ComponentPick = { kind: "agent", name: "demo-agent" };

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
