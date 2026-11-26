"use client";

import { useState } from "react";
import { Alert, Badge, Button, Card, Empty, ErrorBox, Loading, PageHeader } from "@/components/ui";
import { api } from "@/lib/api";
import { personName, sinceText } from "@/lib/admin";
import { formatSize } from "@/lib/space";
import type { AdminPerson } from "@/lib/types";
import { useAsync } from "@/lib/useAsync";

/**
 * The owner's People page: who has signed in to this hosted server, what each uses, and a reversible switch to turn an account off. Turning one off
 * signs them out on their very next request and refuses a new sign-in; everything they made is kept. A person who opens this page is told it is the owner's.
 */
export default function PeoplePage() {
  const loaded = useAsync(api.adminPeople, "admin-people");
  const [asking, setAsking] = useState<string | null>(null); // the person whose "turn off" is waiting for a second click
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<Error | null>(null);

  async function change(person: AdminPerson, off: boolean) {
    setBusy(person.id);
    setError(null);
    try {
      await (off ? api.blockPerson(person.id) : api.unblockPerson(person.id));
      setAsking(null);
      loaded.reload();
    } catch (err) {
      setError(err instanceof Error ? err : new Error(String(err)));
    } finally {
      setBusy(null);
    }
  }

  const header = <PageHeader title="People" subtitle="Who has signed in to this server, what each uses, and a switch to turn an account off. Only you, the owner, can see this page." />;
  if (loaded.error && !loaded.data) {
    return (
      <>
        {header}
        <ErrorBox error={loaded.error} onRetry={loaded.reload} />
      </>
    );
  }
  if (!loaded.data) return <Loading what="the people" />;
  if (!loaded.data.hosted) {
    return (
      <>
        {header}
        <Alert tone="info" title="No accounts here">
          <p>Accounts exist only in the hosted version. When you run SkillForge on your own computer, you are the only person.</p>
        </Alert>
      </>
    );
  }
  const people = loaded.data.people;

  return (
    <>
      {header}
      {error && <ErrorBox error={error} />}
      {people.length === 0 ? (
        <Empty title="Nobody has signed in yet">When someone signs in with Google for the first time, they appear here.</Empty>
      ) : (
        <ul className="space-y-3" aria-label="People">
          {people.map((p) => (
            <li key={p.id}>
              <Card className="p-4">
                <div className="flex flex-wrap items-center gap-2">
                  <h2 className="text-base font-semibold">{personName(p)}</h2>
                  {p.blocked && <Badge tone="bad">Turned off</Badge>}
                  {p.has_key && <Badge tone="info">Has a key of their own</Badge>}
                  {p.active > 0 && <Badge tone="warn">{p.active} running</Badge>}
                </div>
                <p className="break-all text-sm text-muted">{p.email}</p>
                <dl className="mt-3 grid grid-cols-2 gap-x-4 gap-y-1 text-sm sm:grid-cols-4">
                  <div>
                    <dt className="text-xs text-muted">Builds kept</dt>
                    <dd>{p.builds}</dd>
                  </div>
                  <div>
                    <dt className="text-xs text-muted">Disk used</dt>
                    <dd>{formatSize(p.disk_used)}</dd>
                  </div>
                  <div>
                    <dt className="text-xs text-muted">Model calls today</dt>
                    <dd>
                      {p.calls_today.server} yours, {p.calls_today.own} theirs
                    </dd>
                  </div>
                  <div>
                    <dt className="text-xs text-muted">Last seen</dt>
                    <dd>{sinceText(p.last_seen)}</dd>
                  </div>
                </dl>
                <div className="mt-3 flex flex-wrap items-center gap-2">
                  {p.blocked ? (
                    <Button className="min-h-11" busy={busy === p.id} disabled={busy !== null} onClick={() => void change(p, false)}>
                      Turn back on
                    </Button>
                  ) : asking === p.id ? (
                    <>
                      <span className="text-sm">Turn off {personName(p)}? They are signed out at once. Their files are kept.</span>
                      <Button variant="danger" className="min-h-11" busy={busy === p.id} disabled={busy !== null} onClick={() => void change(p, true)}>
                        Yes, turn off
                      </Button>
                      <Button variant="ghost" className="min-h-11" disabled={busy !== null} onClick={() => setAsking(null)}>
                        Cancel
                      </Button>
                    </>
                  ) : (
                    <Button variant="ghost" className="min-h-11" disabled={busy !== null} onClick={() => setAsking(p.id)}>
                      Turn off this account
                    </Button>
                  )}
                </div>
              </Card>
            </li>
          ))}
        </ul>
      )}
    </>
  );
}
