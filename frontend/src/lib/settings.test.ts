import { describe, expect, it } from "vitest";
import {
  buildChanges, changedNames, checkLine, groupItems, isChanged, keyAdvice, keyOf, missingKeys, problemFor, roleText, shownValue, sourceNote, statusLine,
} from "./settings";
import type { ModelCheck, ProviderStatus, SettingItem } from "./types";

const item = (over: Partial<SettingItem> = {}): SettingItem => ({
  name: "LLM_MODEL", group: "model", label: "Model", help: "", kind: "text", provider: "", choices: [], set: false, source: "unset", editable: true, value: "", ...over,
});

const secret = (name: string, provider: string, set = false, over: Partial<SettingItem> = {}): SettingItem => {
  const { value: _ignored, ...rest } = item({ name, group: "keys", label: `${provider} key`, kind: "secret", provider, set, source: set ? "file" : "unset", ...over });
  void _ignored;
  return rest;
};

const items: SettingItem[] = [
  item({ name: "LLM_PROVIDER", kind: "choice", choices: ["gemini", "groq"], value: "gemini", set: true, source: "file" }),
  item({ name: "LLM_MODEL", value: "m1", set: true, source: "file" }),
  secret("GOOGLE_API_KEY", "gemini", true),
  secret("GROQ_API_KEY", "groq", false),
  item({ name: "LLM_BASE_URL", group: "keys", kind: "url", provider: "custom" }),
  item({ name: "LLM_MAX_CALLS", group: "limits", kind: "number", value: "20", set: true, source: "environment", editable: false }),
  item({ name: "LLM_FALLBACKS", group: "backups", value: "" }),
  item({ name: "LLM_CODE_PROVIDER", group: "work", kind: "choice", choices: ["gemini", "groq"], value: "" }),
];

describe("what the page shows in a field", () => {
  it("shows the saved value of a plain setting and what was typed over it", () => {
    expect(shownValue(items[1], {})).toBe("m1");
    expect(shownValue(items[1], { LLM_MODEL: "m2" })).toBe("m2");
    expect(shownValue(items[1], { LLM_MODEL: "" })).toBe("");
  });

  it("never has a saved value for a key, only what was typed", () => {
    expect(shownValue(items[2], {})).toBe("");
    expect(shownValue(items[2], { GOOGLE_API_KEY: "abc" })).toBe("abc");
  });
});

describe("what counts as a change", () => {
  it("is nothing until something differs from what is saved", () => {
    expect(isChanged(items[1], {}, new Set())).toBe(false);
    expect(isChanged(items[1], { LLM_MODEL: "m1" }, new Set())).toBe(false);
    expect(isChanged(items[1], { LLM_MODEL: " m1 " }, new Set())).toBe(false);
    expect(isChanged(items[1], { LLM_MODEL: "m2" }, new Set())).toBe(true);
    expect(isChanged(items[1], { LLM_MODEL: "" }, new Set())).toBe(true); // emptied: remove it
  });

  it("is a key only when something was typed, and asking to remove an unset key is no change", () => {
    expect(isChanged(items[2], {}, new Set())).toBe(false);
    expect(isChanged(items[2], { GOOGLE_API_KEY: "   " }, new Set())).toBe(false);
    expect(isChanged(items[2], { GOOGLE_API_KEY: "new-key" }, new Set())).toBe(true);
    expect(isChanged(items[2], {}, new Set(["GOOGLE_API_KEY"]))).toBe(true);
    expect(isChanged(items[3], {}, new Set(["GROQ_API_KEY"]))).toBe(false);
  });

  it("is never a setting that comes from outside the .env file", () => {
    expect(isChanged(items[5], { LLM_MAX_CALLS: "5" }, new Set())).toBe(false);
    expect(buildChanges(items, { LLM_MAX_CALLS: "5" }, new Set(["LLM_MAX_CALLS"]))).toEqual({});
  });
});

describe("the request", () => {
  it("holds only what changed: a value to set, or null to remove", () => {
    const draft = { LLM_MODEL: "m2", GROQ_API_KEY: " gsk_new ", GOOGLE_API_KEY: "", LLM_BASE_URL: "" };
    const removed = new Set(["GOOGLE_API_KEY"]);
    expect(buildChanges(items, draft, removed)).toEqual({ LLM_MODEL: "m2", GROQ_API_KEY: "gsk_new", GOOGLE_API_KEY: null });
    expect(changedNames(items, draft, removed)).toEqual(["LLM_MODEL", "GOOGLE_API_KEY", "GROQ_API_KEY"]);
  });

  it("sends an emptied plain setting as a removal", () => {
    expect(buildChanges(items, { LLM_MODEL: "" }, new Set())).toEqual({ LLM_MODEL: null });
  });

  it("is empty when nothing changed", () => {
    expect(buildChanges(items, {}, new Set())).toEqual({});
  });

  it("a remove wins over a key typed before it: the field says \"Will be removed\", so that is what is saved", () => {
    expect(buildChanges(items, { GOOGLE_API_KEY: "replacement" }, new Set(["GOOGLE_API_KEY"]))).toEqual({ GOOGLE_API_KEY: null });
    expect(isChanged(items[2], { GOOGLE_API_KEY: "replacement" }, new Set(["GOOGLE_API_KEY"]))).toBe(true);
  });
});

describe("a provider written in another case", () => {
  it("is shown the way the list spells it, so the field is not blank and the advice still works", () => {
    const hand = item({ name: "LLM_PROVIDER", kind: "choice", choices: ["gemini", "groq"], value: "Gemini", set: true, source: "file" });
    expect(shownValue(hand, {})).toBe("gemini");
    expect(keyAdvice([hand, secret("GOOGLE_API_KEY", "gemini", true)], {}, new Set())).toBeNull();
    expect(keyAdvice([hand, secret("GOOGLE_API_KEY", "gemini", false)], {}, new Set())).toMatch(/no key for gemini/i);
  });
});

describe("keys that backups and other kinds of work need", () => {
  const withBackups = (backups: string, code = "") => [
    ...items.filter((i) => i.name !== "LLM_FALLBACKS" && i.name !== "LLM_CODE_PROVIDER"),
    item({ name: "LLM_FALLBACKS", group: "backups", value: backups, set: backups !== "" }),
    item({ name: "LLM_CODE_PROVIDER", group: "work", kind: "choice", choices: ["gemini", "groq"], value: code, set: code !== "" }),
  ];

  it("names a provider a backup uses when its key is not set, and stops once a key is typed", () => {
    expect(missingKeys(withBackups("groq:some-model"), {}, new Set())).toEqual(["groq"]);
    expect(missingKeys(withBackups("groq:some-model"), { GROQ_API_KEY: "gsk_x" }, new Set())).toEqual([]);
  });

  it("counts a key that is being removed as missing, and a typed backup list as it is typed", () => {
    expect(missingKeys(withBackups("gemini:m"), {}, new Set(["GOOGLE_API_KEY"]))).toEqual(["gemini"]);
    expect(missingKeys(withBackups(""), { LLM_FALLBACKS: "groq:m, gemini:n" }, new Set())).toEqual(["groq"]);
  });

  it("includes a provider chosen for one kind of work, once, and says nothing when no backup or kind of work names a provider", () => {
    expect(missingKeys(withBackups("groq:a,groq:b", "groq"), {}, new Set())).toEqual(["groq"]);
    expect(missingKeys(withBackups(""), {}, new Set())).toEqual([]);
  });
});

describe("helpers", () => {
  it("finds the key of a provider and the items of a group", () => {
    expect(keyOf(items, "groq")?.name).toBe("GROQ_API_KEY");
    expect(keyOf(items, "nothing")).toBeUndefined();
    expect(groupItems(items, "keys").map((i) => i.name)).toEqual(["GOOGLE_API_KEY", "GROQ_API_KEY", "LLM_BASE_URL"]);
  });

  it("says a note for a setting that comes from the environment, and none for a file setting", () => {
    expect(sourceNote(items[5])).toMatch(/outside the \.env file/);
    expect(sourceNote(items[1])).toBeNull();
  });

  it("finds the problem for one setting", () => {
    const problems = [{ name: "LLM_MODEL", message: "too long" }, { name: "", message: "general" }];
    expect(problemFor(problems, "LLM_MODEL")).toBe("too long");
    expect(problemFor(problems, "GOOGLE_API_KEY")).toBeUndefined();
  });
});

describe("advice about the chosen provider", () => {
  it("is nothing when the chosen provider has its key", () => {
    expect(keyAdvice(items, {}, new Set())).toBeNull();
  });

  it("says the key is missing when the provider is changed to one without a key, and not once one is typed", () => {
    expect(keyAdvice(items, { LLM_PROVIDER: "groq" }, new Set())).toMatch(/groq key has no key yet|no key/i);
    expect(keyAdvice(items, { LLM_PROVIDER: "groq", GROQ_API_KEY: "gsk_x" }, new Set())).toBeNull();
  });

  it("says so when the chosen provider's key is being removed", () => {
    expect(keyAdvice(items, {}, new Set(["GOOGLE_API_KEY"]))).toMatch(/no key/i);
  });

  it("asks for a provider when none is chosen, and for the address of a custom endpoint", () => {
    expect(keyAdvice(items, { LLM_PROVIDER: "" }, new Set())).toMatch(/choose a provider/i);
    const custom = [...items, secret("LLM_API_KEY", "custom", true)];
    expect(keyAdvice(custom, { LLM_PROVIDER: "custom" }, new Set())).toMatch(/address/i);
    expect(keyAdvice(custom, { LLM_PROVIDER: "custom", LLM_BASE_URL: "http://localhost:1234/v1" }, new Set())).toBeNull();
  });
});

describe("the test of the models", () => {
  const check = (over: Partial<ModelCheck> = {}): ModelCheck => ({
    provider: "gemini", model: "m1", roles: ["default"], ok: true, kind: "", detail: "", latency_ms: 840, input_tokens: 12, output_tokens: 3, ...over,
  });

  it("says how long a working model took", () => {
    expect(checkLine(check())).toEqual({ tone: "ok", text: "Worked, in 0.8 s" });
  });

  it("explains a failure in plain words, by its kind", () => {
    expect(checkLine(check({ ok: false, kind: "auth" })).text).toMatch(/key was refused/i);
    expect(checkLine(check({ ok: false, kind: "model_missing" })).text).toMatch(/model/i);
    expect(checkLine(check({ ok: false, kind: "rate_limit" })).tone).toBe("bad");
    expect(checkLine(check({ ok: false, kind: "something_new" })).text).toMatch(/did not answer/i);
  });

  it("names what each model is for", () => {
    expect(roleText(["default"])).toBe("your main model");
    expect(roleText(["fallback"])).toBe("a backup");
    expect(roleText(["code", "actor"])).toBe("writing scripts, running a skill's tests");
    expect(roleText([])).toBe("");
  });
});

describe("the line about the model in use", () => {
  const status = (over: Partial<ProviderStatus> = {}): ProviderStatus => ({ configured: true, provider: "gemini", model: "m1", detail: "", ...over });

  it("names the provider and model", () => {
    expect(statusLine(status())).toEqual({ tone: "ok", text: "In use: gemini / m1" });
  });

  it("says why no model is usable, in the server's words", () => {
    expect(statusLine(status({ configured: false, provider: "", model: "", detail: "GOOGLE_API_KEY is empty." }))).toEqual({
      tone: "warn", text: "No model is usable yet. GOOGLE_API_KEY is empty.",
    });
  });
});
