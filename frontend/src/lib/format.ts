import type { Check, CheckStatus } from "./types";

const ORDER: CheckStatus[] = ["failed", "warning", "not run", "passed"];

export function countChecks(checks: Check[]): Record<CheckStatus, number> {
  const counts: Record<CheckStatus, number> = { passed: 0, warning: 0, failed: 0, "not run": 0 };
  for (const c of checks) counts[c.status] += 1;
  return counts;
}

/** Most important first: what failed, then what to read, then what did not run, then what passed. */
export function sortChecks(checks: Check[]): Check[] {
  return [...checks].sort((a, b) => ORDER.indexOf(a.status) - ORDER.indexOf(b.status));
}

export function plural(n: number, one: string, many = `${one}s`): string {
  return `${n} ${n === 1 ? one : many}`;
}

export function shortHash(hash: string): string {
  return hash.slice(0, 12);
}

/** "2026-11-19 05:34" in the viewer's own time zone. */
export function formatWhen(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  const p = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`;
}

export function relativeTime(iso: string, now: number = Date.now()): string {
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return iso;
  const s = Math.max(0, Math.round((now - then) / 1000));
  if (s < 45) return "just now";
  const m = Math.round(s / 60);
  if (m < 60) return `${m} min ago`;
  const h = Math.round(m / 60);
  if (h < 24) return `${h} h ago`;
  const d = Math.round(h / 24);
  if (d < 30) return `${d} day${d === 1 ? "" : "s"} ago`;
  return formatWhen(iso).slice(0, 10);
}

/** The API's message is written for the command line ("... Use --force ..."). The dialog has its own button, so show only the path. */
export function conflictPath(message: string): string {
  const m = /^(.*?) already exists\b/s.exec(message);
  return m ? m[1] : message;
}

/** Where a version came from, in a few words. */
export function sourceText(kind: string, label: string): string {
  if (kind === "rollback") return `restored ${label}`;
  return `${kind} ${label}`;
}
