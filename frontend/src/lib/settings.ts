import type { ModelCheck, ProviderStatus, SettingItem, SettingProblem } from "./types";

/** What the person typed, by setting name. A key is only ever here as typed: the server never sends one back. */
export type Draft = Record<string, string>;

/** The value a field shows: what was typed, else what is saved. A key has no saved value to show. */
export function shownValue(item: SettingItem, draft: Draft): string {
  const value = draft[item.name] ?? item.value ?? "";
  return item.kind === "choice" ? value.toLowerCase() : value; // a provider written by hand as "Gemini" is the list's "gemini"
}

/** Would saving change this setting? Typing a key replaces it; asking to remove a key that is not set changes nothing. A remove wins
 * over anything typed: the field says "Will be removed", so that is what a save does. */
export function isChanged(item: SettingItem, draft: Draft, removed: ReadonlySet<string>): boolean {
  if (!item.editable) return false;
  if (removed.has(item.name)) return item.set;
  const typed = draft[item.name];
  if (typed === undefined) return false;
  if (item.kind === "secret") return typed.trim() !== "";
  const same = item.kind === "choice" ? (a: string, b: string) => a.toLowerCase() === b.toLowerCase() : (a: string, b: string) => a === b;
  return !same(typed.trim(), (item.value ?? "").trim());
}

/** The request body's `changes`: a value to set, or null to remove. Only what changed. */
export function buildChanges(items: SettingItem[], draft: Draft, removed: ReadonlySet<string>): Record<string, string | null> {
  const changes: Record<string, string | null> = {};
  for (const item of items) {
    if (!isChanged(item, draft, removed)) continue;
    const typed = (draft[item.name] ?? "").trim();
    changes[item.name] = removed.has(item.name) || typed === "" ? null : typed;
  }
  return changes;
}

export function changedNames(items: SettingItem[], draft: Draft, removed: ReadonlySet<string>): string[] {
  return items.filter((i) => isChanged(i, draft, removed)).map((i) => i.name);
}

export function groupItems(items: SettingItem[], group: string): SettingItem[] {
  return items.filter((i) => i.group === group);
}

export function keyOf(items: SettingItem[], provider: string): SettingItem | undefined {
  return items.find((i) => i.kind === "secret" && i.provider === provider);
}

/** A note for a setting the page cannot change, or null. */
export function sourceNote(item: SettingItem): string | null {
  return item.source === "environment"
    ? "Set outside the .env file (in this computer's environment), so it cannot be changed here. Change or remove it there, then restart the server."
    : null;
}

export function problemFor(problems: SettingProblem[], name: string): string | undefined {
  return problems.find((p) => p.name === name)?.message;
}

/** What is still missing for the provider the person has chosen (saved or typed), or null. */
export function keyAdvice(items: SettingItem[], draft: Draft, removed: ReadonlySet<string>): string | null {
  const providerItem = items.find((i) => i.name === "LLM_PROVIDER");
  const provider = (providerItem ? shownValue(providerItem, draft) : "").trim();
  if (!provider) return "Choose a provider.";
  const key = keyOf(items, provider);
  if (key) {
    const typed = (draft[key.name] ?? "").trim() !== "";
    const has = typed || (key.set && !removed.has(key.name));
    if (!has) return `No key for ${provider} yet. Add it below.`;
  }
  if (provider === "custom") {
    const address = items.find((i) => i.name === "LLM_BASE_URL");
    if (address && shownValue(address, draft).trim() === "" && !address.set) return "Add the address of your custom endpoint.";
  }
  return null;
}

/** Providers that a backup model or a kind of work uses but that have no key (set, or typed, and not being removed). In the order they appear. */
export function missingKeys(items: SettingItem[], draft: Draft, removed: ReadonlySet<string>): string[] {
  const used: string[] = [];
  const add = (provider: string) => {
    const p = provider.trim().toLowerCase();
    if (p && !used.includes(p)) used.push(p);
  };
  const backups = items.find((i) => i.name === "LLM_FALLBACKS");
  if (backups) for (const part of shownValue(backups, draft).split(",")) add(part.split(":")[0]);
  for (const i of items) if (i.kind === "choice" && /^LLM_[A-Z]+_PROVIDER$/.test(i.name) && i.name !== "LLM_PROVIDER") add(shownValue(i, draft));
  return used.filter((provider) => {
    const key = keyOf(items, provider);
    if (!key) return false; // not a provider the page knows: the server says what is wrong when it is saved
    const typed = (draft[key.name] ?? "").trim() !== "";
    return !(typed || (key.set && !removed.has(key.name)));
  });
}

const KIND_TEXT: Record<string, string> = {
  auth: "The key was refused. Check it, or add it again.",
  model_missing: "This key cannot use that model name. Pick another model.",
  quota: "Out of quota, or not allowed to use this model.",
  rate_limit: "Rate limited. Try again in a minute.",
  timeout: "No answer in time.",
  overloaded: "The provider is busy. Try again.",
  connection: "Could not reach the provider.",
  bad_request: "The provider did not accept the request.",
  too_long: "The request was too long for this model.",
  invalid_output: "It answered, but not in the shape that was asked for.",
  refused: "The model refused to answer.",
};

/** One line for one model's test: it worked (and how fast), or why it did not, in plain words. */
export function checkLine(c: ModelCheck): { tone: "ok" | "bad"; text: string } {
  if (c.ok) return { tone: "ok", text: `Worked, in ${(c.latency_ms / 1000).toFixed(1)} s` };
  return { tone: "bad", text: KIND_TEXT[c.kind] ?? "It did not answer." };
}

const ROLE_TEXT: Record<string, string> = {
  default: "your main model",
  fallback: "a backup",
  escalation: "a second try",
  fast: "reading your words",
  design: "writing a skill",
  code: "writing scripts",
  actor: "running a skill's tests",
};

export function roleText(roles: string[]): string {
  return roles.map((r) => ROLE_TEXT[r] ?? r).join(", ");
}

/** The line about the model in use, from the server's own status (it never holds a key). */
export function statusLine(s: ProviderStatus): { tone: "ok" | "warn"; text: string } {
  if (s.configured) return { tone: "ok", text: `In use: ${s.provider} / ${s.model}` };
  return { tone: "warn", text: `No model is usable yet.${s.detail ? ` ${s.detail}` : ""}` };
}
