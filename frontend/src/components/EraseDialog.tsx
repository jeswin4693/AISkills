"use client";

import { useId, useState } from "react";
import { Alert, Button, Modal } from "@/components/ui";
import { api } from "@/lib/api";
import { personName } from "@/lib/admin";
import { eraseWords, erasedNotice, typedEmail } from "@/lib/remove";
import type { AdminPerson } from "@/lib/types";

/** The form inside the dialog (mounted only while it is open, so the typed address starts empty every time). */
function EraseForm({ person, onClose, onErased }: { person: AdminPerson; onClose: () => void; onErased: (notice: string) => void }) {
  const [typed, setTyped] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const boxId = useId();
  const ready = typedEmail(typed, person.email);
  const words = eraseWords();

  async function erase() {
    if (!ready || busy) return;
    setBusy(true);
    setError(null);
    try {
      const report = await api.erasePerson(person.id, typed.trim()); // the server checks the address again: this box only helps
      onErased(erasedNotice(report));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setBusy(false);
    }
  }

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        void erase();
      }}
      className="space-y-3"
    >
      <p className="text-sm font-semibold">This cannot be undone.</p>
      <div>
        <p className="text-sm font-medium">This removes</p>
        <ul className="list-disc space-y-0.5 pl-5 text-sm">
          {words.removes.map((line) => (
            <li key={line}>{line}</li>
          ))}
        </ul>
      </div>
      <div>
        <p className="text-sm font-medium">This keeps</p>
        <ul className="list-disc space-y-0.5 pl-5 text-sm">
          {words.keeps.map((line) => (
            <li key={line}>{line}</li>
          ))}
        </ul>
      </div>
      <div>
        <label htmlFor={boxId} className="text-sm">
          To confirm, type <strong className="break-all">{person.email}</strong>
        </label>
        <input
          id={boxId}
          value={typed}
          onChange={(e) => setTyped(e.target.value)}
          autoComplete="off"
          autoCapitalize="off"
          spellCheck={false}
          className="mt-1 block min-h-11 w-full rounded-md border border-border bg-bg px-2 py-1.5"
        />
      </div>
      {error && (
        <Alert tone="bad" title="Nothing was erased">
          {error}
        </Alert>
      )}
      <div className="flex justify-end gap-2">
        <Button className="min-h-11" disabled={busy} onClick={onClose}>
          Cancel
        </Button>
        <Button type="submit" variant="danger" className="min-h-11" busy={busy} disabled={!ready}>
          Erase their data for good
        </Button>
      </div>
    </form>
  );
}

/** The owner's "Erase their data" dialog for one turned-off person. The server refuses it for anyone who is not turned off or has work running, and checks the typed address. */
export function EraseDialog({ person, onClose, onErased }: { person: AdminPerson | null; onClose: () => void; onErased: (notice: string) => void }) {
  return (
    <Modal open={person !== null} onClose={onClose} title={person ? `Erase the data of ${personName(person)}?` : "Erase"}>
      {person && <EraseForm person={person} onClose={onClose} onErased={onErased} />}
    </Modal>
  );
}
