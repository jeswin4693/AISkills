/** How a person's own space is put into words (docs/person-limits.md). Pure: the page only draws what this says. */

import type { PersonSpace } from "./types";

const KB = 1024;
const MB = KB * 1024;
const GB = MB * 1024;

export type SpaceTone = "ok" | "warn" | "bad";
export interface SpaceRow {
  key: "disk" | "builds" | "active";
  label: string;
  text: string;
  /** How full, 0 to 100 (never more); null when there is no limit, so no bar is drawn. */
  percent: number | null;
  tone: SpaceTone;
}

export function formatSize(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes <= 0) return "0 KB";
  if (bytes >= GB) return `${(bytes / GB).toFixed(1)} GB`;
  if (bytes >= MB) return `${(bytes / MB).toFixed(1)} MB`;
  return `${Math.max(1, Math.round(bytes / KB))} KB`;
}

function fill(used: number, limit: number): { percent: number | null; tone: SpaceTone } {
  if (limit <= 0) return { percent: null, tone: "ok" };
  const percent = Math.min(100, Math.round((used / limit) * 100));
  return { percent, tone: used >= limit ? "bad" : percent >= 80 ? "warn" : "ok" };
}

const plural = (n: number, one: string, many: string) => (n === 1 ? one : many);

export function spaceRows(space: PersonSpace): SpaceRow[] {
  const { disk, builds, active } = space;
  return [
    {
      key: "disk", label: "Disk",
      text: disk.limit > 0 ? `${formatSize(disk.used)} of ${formatSize(disk.limit)}` : `${formatSize(disk.used)} used (no limit)`,
      ...fill(disk.used, disk.limit),
    },
    {
      key: "builds", label: "Builds kept",
      text: builds.limit > 0
        ? `${builds.kept} of ${builds.limit} ${plural(builds.limit, "build", "builds")} kept`
        : `${builds.kept} ${plural(builds.kept, "build", "builds")} kept (no limit)`,
      ...fill(builds.kept, builds.limit),
    },
    {
      key: "active", label: "Runs working",
      text: active.limit > 0
        ? `${active.now} of ${active.limit} ${plural(active.limit, "run", "runs")} working`
        : `${active.now} ${plural(active.now, "run", "runs")} working (no limit)`,
      ...fill(active.now, active.limit),
    },
  ];
}

/** What to do about a limit that is reached ("" when none is). */
export function adviceFor(rows: SpaceRow[]): string {
  const full = rows.filter((r) => r.tone === "bad").map((r) => r.key);
  if (full.length === 0) return "";
  const parts: string[] = [];
  if (full.includes("disk") || full.includes("builds")) parts.push("Discard builds you no longer need to make room.");
  if (full.includes("active")) parts.push("Wait for a run to finish before starting another.");
  return parts.join(" ");
}
