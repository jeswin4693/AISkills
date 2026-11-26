/** Words for the owner's People page (docs/person-limits.md). */

/** "3 min ago", "2 h ago", "5 days ago": how long ago an ISO time was. "never" for nothing, "unknown" for text that is no date, never a negative time. */
export function sinceText(iso: string, now: number = Date.now()): string {
  if (!iso) return "never";
  const then = Date.parse(iso);
  if (Number.isNaN(then)) return "unknown";
  const seconds = Math.round((now - then) / 1000);
  if (seconds < 60) return "just now"; // also a time a little in the future (clocks differ)
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours} h ago`;
  const days = Math.floor(hours / 24);
  return `${days} ${days === 1 ? "day" : "days"} ago`;
}

export const personName = (p: { name: string; email: string }): string => p.name.trim() || p.email;
