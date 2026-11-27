import { describe, expect, it } from "vitest";
import { eraseBlockedReason, personName, sinceText } from "./admin";

const NOW = Date.UTC(2026, 10, 26, 12, 0, 0);
const ago = (ms: number) => new Date(NOW - ms).toISOString();

describe("how long ago, in words", () => {
  it.each([
    [10_000, "just now"],
    [3 * 60_000, "3 min ago"],
    [60_000, "1 min ago"],
    [2 * 3_600_000, "2 h ago"],
    [26 * 3_600_000, "1 day ago"],
    [5 * 86_400_000, "5 days ago"],
  ])("%d ms is %s", (ms, text) => {
    expect(sinceText(ago(ms), NOW)).toBe(text);
  });
  it("says it does not know for nothing or for text that is no date, and never for the future", () => {
    expect(sinceText("", NOW)).toBe("never");
    expect(sinceText("not a date", NOW)).toBe("unknown");
    expect(sinceText(new Date(NOW + 5 * 86_400_000).toISOString(), NOW)).toBe("just now");
  });
});

describe("a person's name on the page", () => {
  it("uses the name, and the email when there is none", () => {
    expect(personName({ name: "Ada L", email: "ada@example.com" })).toBe("Ada L");
    expect(personName({ name: "  ", email: "ada@example.com" })).toBe("ada@example.com");
  });
});

describe("whether the owner may erase a person's data now", () => {
  const person = { id: "a".repeat(32), name: "Ada", email: "ada@example.com", joined: "", last_seen: "", blocked: true, builds: 1, disk_used: 1, active: 0, calls_today: { server: 0, own: 0 }, has_key: false };
  it("is allowed only for a turned-off person with nothing running", () => {
    expect(eraseBlockedReason(person)).toBeNull();
  });
  it("says to turn the account off first, before anything else", () => {
    expect(eraseBlockedReason({ ...person, blocked: false })).toBe("Turn this account off first.");
    expect(eraseBlockedReason({ ...person, blocked: false, active: 2 })).toBe("Turn this account off first.");
  });
  it("says to wait while their work is running", () => {
    expect(eraseBlockedReason({ ...person, active: 1 })).toBe("Wait for their running work to finish.");
  });
});
