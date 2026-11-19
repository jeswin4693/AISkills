export type DiffLineKind = "add" | "del" | "hunk" | "meta" | "ctx";

export interface DiffLine {
  kind: DiffLineKind;
  text: string;
}

/**
 * Read a unified diff line by line. Lines are only ever shown as text, never as markup.
 *
 * The `---` and `+++` file headers exist only before the first `@@`. After that a line starting with `---` is a
 * removed line whose own text starts with `--` (a deleted Markdown `---` rule shows up as `----`), so it is a removal.
 */
export function parseDiff(text: string): DiffLine[] {
  if (!text) return [];
  let inHunk = false;
  return text.split("\n").map((line): DiffLine => {
    if (line.startsWith("@@")) {
      inHunk = true;
      return { kind: "hunk", text: line };
    }
    if (!inHunk && (line.startsWith("---") || line.startsWith("+++"))) return { kind: "meta", text: line };
    if (line.startsWith("... ") && line.endsWith("not shown")) return { kind: "meta", text: line }; // the API's "cut" notice
    if (line.startsWith("+")) return { kind: "add", text: line };
    if (line.startsWith("-")) return { kind: "del", text: line };
    return { kind: "ctx", text: line };
  });
}

export function diffStats(text: string): { added: number; removed: number } {
  let added = 0;
  let removed = 0;
  for (const l of parseDiff(text)) {
    if (l.kind === "add") added += 1;
    else if (l.kind === "del") removed += 1;
  }
  return { added, removed };
}
