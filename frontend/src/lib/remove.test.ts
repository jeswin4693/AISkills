import { afterEach, describe, expect, it, vi } from "vitest";
import { api } from "./api";
import { deleteWords, deletedNotice, eraseWords, erasedNotice, typedEmail, typedName } from "./remove";
import type { DeleteReport, EraseReport } from "./types";

afterEach(() => vi.unstubAllGlobals());

const reply = (status: number, body: unknown) => new Response(JSON.stringify(body), { status });

describe("the typed confirmation, which is only a help: the server checks it again", () => {
  it("accepts the name exactly (trimmed) and nothing else", () => {
    expect(typedName("commit-writer", "commit-writer")).toBe(true);
    expect(typedName("  commit-writer  ", "commit-writer")).toBe(true);
    expect(typedName("Commit-Writer", "commit-writer")).toBe(false);
    expect(typedName("commit-writ", "commit-writer")).toBe(false);
    expect(typedName("", "commit-writer")).toBe(false);
    expect(typedName("", "")).toBe(false); // an empty name is never confirmed by an empty box
    expect(typedName("   ", "   ")).toBe(false);
  });
  it("accepts the address whatever its case, trimmed, and never an empty one", () => {
    expect(typedEmail("Ada@Example.com ", "ada@example.com")).toBe(true);
    expect(typedEmail("ada@example.co", "ada@example.com")).toBe(false);
    expect(typedEmail("bob@example.com", "ada@example.com")).toBe(false);
    expect(typedEmail("", "")).toBe(false);
  });
});

describe("the words of the delete dialog", () => {
  const lines = deleteWords("skill", 3).join(" ");
  it("says what goes, that it cannot be undone, and what is not touched", () => {
    expect(lines).toContain("3 versions");
    expect(lines.toLowerCase()).toContain("cannot be undone");
    expect(lines).toContain("backups");
    expect(lines).toContain("Plugins you already built keep their own copies");
    expect(lines).toContain("Folders you installed it into are not touched");
  });
  it("uses the singular for one version and the kind's own noun", () => {
    expect(deleteWords("agent", 1).join(" ")).toContain("the agent and its 1 version");
  });
});

describe("what was deleted, in words", () => {
  const done: DeleteReport = { deleted: true, name: "commit-writer", kind: "skill", versions: 2, backups: 1, leftover: false };
  it("counts the versions and the backups", () => {
    expect(deletedNotice(done, "commit-writer")).toBe("Deleted commit-writer: 2 versions and 1 backup.");
    expect(deletedNotice({ ...done, versions: 1, backups: 0 }, "commit-writer")).toBe("Deleted commit-writer: 1 version.");
  });
  it("says plainly when something could not be removed from the disk", () => {
    const text = deletedNotice({ ...done, leftover: true }, "commit-writer");
    expect(text).toContain("could not be removed from the disk");
    expect(text).toContain("no longer part of your library");
  });
});

describe("the words of the erase dialog", () => {
  it("lists what goes and what stays, including why the usage record stays", () => {
    const { removes, keeps } = eraseWords();
    expect(removes.join(" ")).toContain("library");
    expect(removes.join(" ")).toContain("builds");
    expect(removes.join(" ")).toContain("model key");
    expect(keeps.join(" ")).toContain("stays turned off");
    expect(keeps.join(" ")).toContain("model calls");
  });
  const done: EraseReport = { erased: true, builds: 3, suggestion_runs: 1, lab_runs: 2, scan_runs: 1, key_removed: true, files_left: false };
  it("counts what was erased", () => {
    const text = erasedNotice(done);
    expect(text).toContain("3 builds");
    expect(text).toContain("1 suggestion run");
    expect(text).toContain("2 test runs");
    expect(text).toContain("1 behaviour scan");
    expect(text).toContain("saved model key");
    expect(text).toContain("files are gone");
  });
  it("does not mention a key that was not there, and says plainly when files are left", () => {
    const text = erasedNotice({ ...done, key_removed: false, files_left: true });
    expect(text).not.toContain("model key");
    expect(text).toContain("could not be removed from the disk");
    expect(text).toContain("Erase again");
    expect(text).not.toContain("Their files are gone");
  });
});

describe("the two calls", () => {
  it("deletes with DELETE, the typed name and the kind in the address", async () => {
    const f = vi.fn().mockResolvedValue(reply(200, { deleted: true, name: "my skill?", kind: "agent", versions: 1, backups: 0, leftover: false }));
    vi.stubGlobal("fetch", f);
    await api.deleteEntry("commit-writer", "commit-writer", "agent");
    expect(f.mock.calls[0][1].method).toBe("DELETE");
    const url = String(f.mock.calls[0][0]);
    expect(url).toContain("/api/library/commit-writer?confirm=commit-writer");
    expect(url).toContain("kind=agent");
    await api.deleteEntry("commit-writer", "commit-writer");
    expect(String(f.mock.calls[1][0])).not.toContain("kind=");
  });
  it("encodes what was typed, so nothing typed can change the address", async () => {
    const f = vi.fn().mockResolvedValue(reply(400, { detail: "Type the name to confirm: nothing was deleted." }));
    vi.stubGlobal("fetch", f);
    await expect(api.deleteEntry("commit-writer", "x&kind=agent#../", "skill")).rejects.toMatchObject({ status: 400 });
    const url = String(f.mock.calls[0][0]);
    expect(url).toContain("confirm=x%26kind%3Dagent%23..%2F");
    expect(url).not.toContain("kind=agent");
  });
  it("raises the server's message when work is running", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(reply(409, { detail: "You have work running. Wait for it to finish, then delete." })));
    await expect(api.deleteEntry("commit-writer", "commit-writer")).rejects.toMatchObject({ status: 409, message: "You have work running. Wait for it to finish, then delete." });
  });
  it("erases with POST and the typed address in the body", async () => {
    const f = vi.fn().mockResolvedValue(reply(200, { erased: true, builds: 0, suggestion_runs: 0, lab_runs: 0, scan_runs: 0, key_removed: false, files_left: false }));
    vi.stubGlobal("fetch", f);
    await api.erasePerson("a".repeat(32), "ada@example.com");
    expect(f.mock.calls[0][1].method).toBe("POST");
    expect(String(f.mock.calls[0][0])).toContain(`/api/admin/people/${"a".repeat(32)}/erase`);
    expect(JSON.parse(f.mock.calls[0][1].body)).toEqual({ confirm: "ada@example.com" });
  });
});
