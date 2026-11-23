import type { HookInfo, HookOption, PluginRequest } from "./types";

/** One skill, agent, MCP server or hook chosen for a plugin. A hook may carry the options a person chose for it. */
export interface ComponentPick {
  kind: "skill" | "agent" | "mcp" | "hook";
  name: string;
  options?: Record<string, string[]>;
}

/** What each thing a program's code can do is called on the page (the same words the server's notes use). */
const SERVER_POWERS: Record<string, string> = {
  network: "reach the network", write_files: "write or delete files", read_files: "read files", run_commands: "start other programs",
};

/** A program's powers in plain words; one the page does not know is shown as it is, never dropped. */
export const serverPowers = (capabilities: string[]): string[] => capabilities.map((c) => SERVER_POWERS[c] ?? c);

/** The name of each kind of part, as a person says it. */
export const partLabel = (kind: ComponentPick["kind"]): string => (kind === "mcp" ? "MCP server" : kind);

/** When a hook runs, in plain words: "before Claude uses Read, Write", "after Claude uses any tool". */
export function hookWhen(hook: { event: string; matcher: string }): string {
  const tools = hook.matcher === "" ? "any tool" : hook.matcher.split("|").join(", ");
  if (hook.event === "PreToolUse") return `before Claude uses ${tools}`;
  if (hook.event === "PostToolUse") return `after Claude uses ${tools}`;
  return `on ${hook.event}`;
}

export interface PluginForm {
  name: string;
  description: string;
  author: string;
}

const same = (a: ComponentPick, b: ComponentPick) => a.kind === b.kind && a.name === b.name;

export const isPicked = (picks: ComponentPick[], pick: ComponentPick): boolean => picks.some((p) => same(p, pick));

/** Adds the part, or takes it out when it is already there. The list it was given is never changed. */
export function togglePick(picks: ComponentPick[], pick: ComponentPick): ComponentPick[] {
  return isPicked(picks, pick) ? picks.filter((p) => !same(p, pick)) : [...picks, pick];
}

/** The list with one option of one part set (an empty list clears it). The list it was given is never changed. */
export function setOption(picks: ComponentPick[], pick: ComponentPick, key: string, values: string[]): ComponentPick[] {
  return picks.map((p) => {
    if (!same(p, pick)) return p;
    const options = { ...(p.options ?? {}) };
    if (values.length === 0) delete options[key];
    else options[key] = values;
    return Object.keys(options).length ? { ...p, options } : { kind: p.kind, name: p.name };
  });
}

/** The id of the box where a person types one option of one hook (its label, its text state and the page's `htmlFor` all use it). */
export const optionTextId = (pick: ComponentPick, key: string): string => `hook-${pick.name}-${key}`;

/**
 * What was typed in the option boxes, without the boxes of `pick` when it is a hook. Unticking a hook drops its parts from the request, so what was
 * typed for it must go too: otherwise ticking it again shows old text in the box while the request carries no options.
 */
export function withoutOptionTexts(texts: Record<string, string>, pick: ComponentPick): Record<string, string> {
  if (pick.kind !== "hook") return texts;
  const prefix = `hook-${pick.name}-`;
  return Object.fromEntries(Object.entries(texts).filter(([id]) => !id.startsWith(prefix)));
}

/** The words a person typed (commas, spaces or new lines between them) as a list of values, in order, each once. */
export const parseOptionText = (text: string): string[] => [...new Set(text.split(/[\s,]+/).filter((v) => v !== ""))];

/**
 * Early, friendly feedback on a hook option, from the pattern the server gave. "" means nothing to say. The server decides: a pattern this
 * browser cannot read is never a reason to stop the person.
 */
export function optionProblem(option: HookOption, values: string[]): string {
  if (values.length > option.max_items) return `At most ${option.max_items} values.`;
  let pattern: RegExp | null = null;
  try {
    pattern = new RegExp(`^(?:${option.pattern})$`);
  } catch {
    pattern = null;
  }
  for (const value of values) {
    if (value.length > option.max_length) return `'${value.slice(0, 20)}' is too long: at most ${option.max_length} characters.`;
    if (pattern && !pattern.test(value)) return `'${value.slice(0, 20)}' is not allowed. ${option.help}`;
  }
  return "";
}

/**
 * Early, friendly feedback on a name. The server decides: it refuses a name that is not lowercase letters, digits and single
 * hyphens (at most 64), or that starts "claude-" or "anthropic-" (Claude Code reserves those). "" means nothing to say.
 */
export function nameHint(name: string): string {
  if (name === "") return "";
  if (name.length > 64) return "At most 64 characters.";
  if (!/^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(name)) return "Use lowercase letters, digits and single hyphens only.";
  if (name.startsWith("claude-") || name.startsWith("anthropic-")) return "Names that start with claude- or anthropic- are reserved by Claude Code.";
  return "";
}

export function pluginRequest(form: PluginForm, picks: ComponentPick[]): PluginRequest {
  return {
    name: form.name.trim(), description: form.description.trim(), author: form.author.trim(),
    components: picks.map((p) => (p.options && Object.keys(p.options).length ? { kind: p.kind, name: p.name, options: p.options } : { kind: p.kind, name: p.name })),
  };
}

/**
 * The request to keep what was previewed: every component pinned to the version the preview used. Without this a newer version of a
 * skill, imported between the preview and the keep, would be kept without the person ever having seen what it can do. A hook has no
 * version to pin (its number is the catalogue's revision, "r1"), so it keeps just its options.
 */
export function keepRequest(request: PluginRequest, used: { kind: string; name: string; version: string }[]): PluginRequest {
  return {
    ...request,
    components: request.components.map((c) => {
      const found = used.find((u) => u.kind === c.kind && u.name === c.name);
      const n = found && c.kind !== "hook" ? Number(found.version.replace(/^v/, "")) : NaN;
      return Number.isInteger(n) && n >= 1 ? { ...c, version: n } : c;
    }),
  };
}

/** Whether the form can be previewed. `hooks` is the catalogue, once it has loaded: an option the server would refuse stops the preview early. */
export function canPreview(form: PluginForm, picks: ComponentPick[], hooks: HookInfo[] = []): boolean {
  const name = form.name.trim();
  const optionsOk = picks.every((p) => {
    if (p.kind !== "hook" || !p.options) return true;
    const entry = hooks.find((h) => h.id === p.name);
    return !entry || entry.options.every((o) => optionProblem(o, p.options?.[o.key] ?? []) === "");
  });
  return name !== "" && nameHint(name) === "" && form.description.trim() !== "" && picks.length > 0 && optionsOk;
}
