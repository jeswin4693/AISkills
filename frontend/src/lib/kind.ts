/**
 * `?kind=` for a kind other than skill. A skill's address is exactly what it always was, so every old link and bookmark
 * keeps working and the pages for skills do not change.
 */
export function withKindParam(href: string, kind: string | undefined): string {
  if (!kind || kind === "skill") return href;
  return `${href}${href.includes("?") ? "&" : "?"}kind=${encodeURIComponent(kind)}`;
}

/** Just the query part: "" for a skill, "?kind=agent" for an agent. */
export const kindQuery = (kind: string | undefined): string => withKindParam("", kind);
