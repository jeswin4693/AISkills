"use client";

import { useState } from "react";
import { ApiError, api } from "@/lib/api";
import { conflictPath } from "@/lib/format";
import type { InstallResult, KindInfo, VersionInfo } from "@/lib/types";
import { Alert, Button, Modal } from "./ui";

/** Copy one version to a skills folder where an agent reads it. The person must choose where; nothing is guessed. */
export function InstallDialog(
  { version, kind, kindInfo, open, onClose }: { version: VersionInfo; kind?: string; kindInfo?: KindInfo; open: boolean; onClose: () => void },
) {
  const personal = kindInfo?.personal_label || "~/.claude/skills";
  const asFile = kindInfo?.installs_as_file ?? false; // an agent is installed as one file, a skill as a folder
  const noun = kindInfo?.label.toLowerCase() ?? "skill";
  const folderName = personal.split("/").pop() ?? "skills";
  const [target, setTarget] = useState<"personal" | "folder">("personal");
  const [folder, setFolder] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [conflict, setConflict] = useState<string | null>(null);
  const [done, setDone] = useState<InstallResult | null>(null);

  async function run(force: boolean) {
    setBusy(true);
    setError(null);
    setConflict(null);
    try {
      setDone(await api.install(version.name, { version: version.version, target, folder: target === "folder" ? folder.trim() : undefined, force }, kind));
    } catch (e) {
      if (e instanceof ApiError && e.status === 409) setConflict(e.message);
      else setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  const hasScripts = Object.keys(version.files).some((p) => p.startsWith("scripts/"));
  const needsFolder = target === "folder" && folder.trim() === "";

  return (
    <Modal open={open} onClose={onClose} title={`Install ${version.name} ${version.tag}`}>
      {done ? (
        <div className="space-y-3">
          <Alert tone="ok" title="Installed">
            <p className="break-all font-mono text-xs">{done.path}</p>
            {done.backup && <p className="mt-1">The {asFile ? "file" : "folder"} that was there was copied to <span className="break-all font-mono text-xs">{done.backup}</span> first.</p>}
          </Alert>
          {done.has_scripts && (
            <Alert tone="warn" title="This skill has scripts">
              When an agent uses it they run on this machine, not in the sandbox. Read them first.
            </Alert>
          )}
          <div className="flex justify-end">
            <Button variant="primary" onClick={onClose}>
              Done
            </Button>
          </div>
        </div>
      ) : (
        <form
          className="space-y-4"
          onSubmit={(e) => {
            e.preventDefault();
            void run(false);
          }}
        >
          <fieldset className="space-y-2">
            <legend className="mb-1 text-sm font-medium">Where should it go?</legend>
            <label className="flex items-start gap-2 text-sm">
              <input type="radio" name="target" checked={target === "personal"} onChange={() => setTarget("personal")} className="mt-1" />
              <span>
                Personal: <code className="font-mono">{personal}</code>
                <span className="block text-muted">Every Claude Code session on this machine can use it.</span>
              </span>
            </label>
            <label className="flex items-start gap-2 text-sm">
              <input type="radio" name="target" checked={target === "folder"} onChange={() => setTarget("folder")} className="mt-1" />
              <span className="min-w-0 flex-1">
                A folder I choose
                <span className="block text-muted">{asFile ? `The ${noun} goes to FOLDER/${version.name}.md.` : `The ${noun} goes to FOLDER/${version.name}.`} Give an absolute path, such as a project&apos;s .claude/{folderName}.</span>
                {target === "folder" && (
                  <input
                    autoFocus
                    value={folder}
                    onChange={(e) => setFolder(e.target.value)}
                    aria-label={`${folderName.charAt(0).toUpperCase()}${folderName.slice(1)} folder (absolute path)`}
                    placeholder={`C:\\path\\to\\project\\.claude\\${folderName}`}
                    className="mt-1.5 block w-full rounded-md border border-border bg-bg px-2 py-1.5 font-mono text-xs"
                  />
                )}
              </span>
            </label>
          </fieldset>
          {hasScripts && (
            <Alert tone="warn" title="This skill has scripts">
              Once installed, an agent runs them on this machine, not in the sandbox. Read them first.
            </Alert>
          )}
          {conflict && (
            <Alert tone="warn" title={`That ${asFile ? "file" : "folder"} already exists`}>
              <p className="break-all font-mono text-xs">{conflictPath(conflict)}</p>
              <p className="mt-2">Replacing it saves the old copy to a backup first, so nothing is lost.</p>
              <div className="mt-2">
                <Button variant="danger" busy={busy} onClick={() => void run(true)}>
                  Back it up and replace
                </Button>
              </div>
            </Alert>
          )}
          {error && (
            <Alert tone="bad" title="It could not be installed">
              {error}
            </Alert>
          )}
          <div className="flex justify-end gap-2">
            <Button onClick={onClose}>Cancel</Button>
            <Button type="submit" variant="primary" busy={busy && !conflict} disabled={needsFolder}>
              Install
            </Button>
          </div>
        </form>
      )}
    </Modal>
  );
}
