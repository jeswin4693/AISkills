import type { PluginRequest } from "./types";

/** One skill or agent chosen for a plugin. */
export interface ComponentPick {
  kind: "skill" | "agent";
  name: string;
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
    components: picks.map((p) => ({ kind: p.kind, name: p.name })),
  };
}

export function canPreview(form: PluginForm, picks: ComponentPick[]): boolean {
  const name = form.name.trim();
  return name !== "" && nameHint(name) === "" && form.description.trim() !== "" && picks.length > 0;
}
