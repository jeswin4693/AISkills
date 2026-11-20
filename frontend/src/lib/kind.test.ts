import { describe, expect, it } from "vitest";
import { kindQuery, withKindParam } from "./kind";

describe("the kind in an address", () => {
  it("leaves a skill's address exactly as it was", () => {
    expect(withKindParam("/library/demo", "skill")).toBe("/library/demo");
    expect(withKindParam("/library/demo", undefined)).toBe("/library/demo");
    expect(kindQuery("skill")).toBe("");
    expect(kindQuery(undefined)).toBe("");
  });

  it("adds ?kind= for any other kind, with & when there already is a query", () => {
    expect(withKindParam("/library/demo", "agent")).toBe("/library/demo?kind=agent");
    expect(withKindParam("/library/demo/diff?from=1&to=2", "agent")).toBe("/library/demo/diff?from=1&to=2&kind=agent");
    expect(kindQuery("agent")).toBe("?kind=agent");
  });

  it("encodes what it is given, so a kind can never add another parameter", () => {
    expect(withKindParam("/library", "a&b=c")).toBe("/library?kind=a%26b%3Dc");
  });
});
