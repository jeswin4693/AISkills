"use client";

import { useId, useState } from "react";
import { Alert, Button, Card, Modal } from "@/components/ui";
import { api } from "@/lib/api";
import { kindNoun } from "@/lib/builder";
import { deleteWords, deletedNotice, typedName } from "@/lib/remove";
import type { KindInfo } from "@/lib/types";

/** The form inside the dialog. It lives inside the modal's own content, which is only mounted while the dialog is open, so the typed text starts empty every time. */
function DeleteForm({
  name, kind, label, versions, onClose, onDeleted,
}: {
  name: string;
  kind: string;
  label: string;
  versions: number;
  onClose: () => void;
  onDeleted: (notice: string) => void;
}) {
  const [typed, setTyped] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const boxId = useId();
  const ready = typedName(typed, name);

  async function remove() {
    if (!ready || busy) return;
    setBusy(true);
    setError(null);
    try {
      const report = await api.deleteEntry(name, typed.trim(), kind); // the server checks the name again: this box only helps
      onDeleted(deletedNotice(report, name));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setBusy(false);
    }
  }

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        void remove();
      }}
      className="space-y-3"
    >
      {deleteWords(label, versions).map((line) => (
        <p key={line} className={line.includes("cannot be undone") ? "text-sm font-semibold" : "text-sm"}>
          {line}
        </p>
      ))}
      <div>
        <label htmlFor={boxId} className="text-sm">
          To confirm, type <strong className="break-all font-mono">{name}</strong>
        </label>
        <input
          id={boxId}
          value={typed}
          onChange={(e) => setTyped(e.target.value)}
          autoComplete="off"
          autoCapitalize="off"
          spellCheck={false}
          className="mt-1 block min-h-11 w-full rounded-md border border-border bg-bg px-2 py-1.5 font-mono"
        />
      </div>
      {error && (
        <Alert tone="bad" title="It was not deleted">
          {error}
        </Alert>
      )}
      <div className="flex justify-end gap-2">
        <Button className="min-h-11" disabled={busy} onClick={onClose}>
          Cancel
        </Button>
        <Button type="submit" variant="danger" className="min-h-11" busy={busy} disabled={!ready}>
          Delete {name} for good
        </Button>
      </div>
    </form>
  );
}

/** The "Danger zone" at the bottom of a library entry's page: delete it, every version and its backups, after typing its name. The server enforces the typed name. */
export function DeleteEntry({
  name, kind, kindInfo, versions, onDeleted,
}: {
  name: string;
  kind: string;
  kindInfo: KindInfo | undefined;
  versions: number;
  onDeleted: (notice: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const label = kindNoun(kindInfo ? [kindInfo] : undefined, kind);
  return (
    <Card className="border-bad/40 p-4">
      <h2 className="font-semibold">Danger zone</h2>
      <div className="mt-2 flex flex-wrap items-center justify-between gap-3">
        <p className="max-w-xl text-sm text-muted">
          Delete this {label} with all of its versions. This cannot be undone. If you only want an older version back, use Restore instead: it deletes nothing.
        </p>
        <Button variant="danger" className="min-h-11" onClick={() => setOpen(true)}>
          Delete this {label}…
        </Button>
      </div>
      <Modal open={open} onClose={() => setOpen(false)} title={`Delete ${name}?`}>
        <DeleteForm name={name} kind={kind} label={label} versions={versions} onClose={() => setOpen(false)} onDeleted={onDeleted} />
      </Modal>
    </Card>
  );
}
