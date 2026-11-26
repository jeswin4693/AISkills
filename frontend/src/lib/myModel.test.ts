import { describe, expect, it } from "vitest";
import { KEY_LIMIT, MODEL_LIMIT, allowanceText, canSave, cleanKey, problemsWith } from "./myModel";

// What the server offers a person: the fixed list WITHOUT "custom" (it takes an address, which would send the server anywhere).
const PROVIDERS = ["anthropic", "gemini", "groq", "mistral", "openai", "openrouter"];
const KEY = "AIzaSyDistinctiveFakeKeyForTests_0123456789";
const ok = (provider = "gemini", model = "gemini-3.5-flash-lite", key = KEY) => problemsWith(provider, model, key, PROVIDERS);

describe("the rules for a person's own model, as the page checks them before it asks the server", () => {
  it("accepts a good choice, and a key with whitespace around it", () => {
    expect(ok()).toEqual({});
    expect(canSave(ok())).toBe(true);
    expect(ok("openai", "gpt-x", `\t ${KEY} \r\n`)).toEqual({});
    expect(cleanKey(`\t ${KEY} \r\n`)).toBe(KEY);
  });

  it("refuses custom (it takes an address) and an unknown provider, naming the choices", () => {
    expect(ok("custom").provider).toMatch(/address/i);
    expect(ok("skynet").provider).toContain("gemini");
    expect(ok("skynet").provider).not.toContain("custom");
    expect(ok("").provider).toBeTruthy();
  });

  it("reports an empty model and an empty key, each on its own field", () => {
    const found = problemsWith("gemini", "", "", PROVIDERS);
    expect(Object.keys(found).sort()).toEqual(["key", "model"]);
    expect(canSave(found)).toBe(false);
  });

  it.each(["a b", 'a"b', "a\\b", "a\x00b", "a​b", "a\nb"])("refuses a model name with anything odd in it (%j)", (model) => {
    expect(ok("gemini", model).model).toBeTruthy();
  });

  it("limits a model name to the width the usage table keeps", () => {
    expect(MODEL_LIMIT).toBe(128);
    expect(ok("gemini", "m".repeat(MODEL_LIMIT)).model).toBeUndefined();
    expect(ok("gemini", "m".repeat(MODEL_LIMIT + 1)).model).toMatch(/too long/i);
  });

  it.each(['"AIzaKEY123"', "'AIzaKEY123'", "`AIzaKEY123`", '"AIzaKEY123'])("tells a person to take the quotes off a pasted key (%s)", (quoted) => {
    expect(ok("gemini", "m", quoted).key).toMatch(/quote/i);
  });

  it.each(["Bearer AIzaKEY123", "bearer   AIzaKEY123", "BEARER"])("tells a person to leave the word Bearer out (%s)", (pasted) => {
    expect(ok("gemini", "m", pasted).key).toMatch(/bearer/i);
  });

  it.each(["AIza key", "AIza\x00key", "AIza​key", "AIza$key", "AIza#key"])("refuses a key with a character an HTTP header should never carry (%j)", (key) => {
    expect(ok("gemini", "m", key).key).toBeTruthy();
  });

  it("limits a key's length", () => {
    expect(ok("gemini", "m", "k".repeat(KEY_LIMIT)).key).toBeUndefined();
    expect(ok("gemini", "m", "k".repeat(KEY_LIMIT + 1)).key).toMatch(/too long/i);
  });

  it("never repeats a key in anything it says", () => {
    for (const key of ['"SECRET-VALUE-123"', "Bearer SECRET-VALUE-123", "SECRET VALUE 123", "SECRET\x00VALUE", "S".repeat(500) + "SECRET-VALUE-123", "SECRET$VALUE"]) {
      expect(Object.values(ok("gemini", "m", key)).join(" ")).not.toContain("SECRET");
    }
  });
});

describe("what the page says about the shared allowance", () => {
  it("says nothing when there is none", () => {
    expect(allowanceText(null)).toBe("");
  });

  it("says how many calls are left, when they are not used up", () => {
    expect(allowanceText({ limit: 25, used: 0 })).toMatch(/25/);
    expect(allowanceText({ limit: 25, used: 12 })).toMatch(/12 of 25/);
    expect(allowanceText({ limit: 25, used: 12 })).toMatch(/midnight UTC/);
  });

  it("says plainly when it is used up, and what to do", () => {
    const text = allowanceText({ limit: 25, used: 25 });
    expect(text).toMatch(/all 25/);
    expect(text).toMatch(/own key/i);
    expect(allowanceText({ limit: 25, used: 31 })).toMatch(/all 25/); // a few attempts in flight can go past the limit: still "used up"
  });
});
