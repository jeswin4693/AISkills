"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";
import { CheckBadges, CheckList } from "@/components/CheckList";
import { FileViewer } from "@/components/FileViewer";
import { InstallDialog } from "@/components/InstallDialog";
import { RescanPanel } from "@/components/RescanPanel";
import { Alert, Badge, Button, ButtonLink, Card, ErrorBox, Loading, Modal, PageHeader } from "@/components/ui";
import { api } from "@/lib/api";
import { formatWhen, plural, relativeTime, shortHash, sourceText } from "@/lib/format";
import type { VersionInfo } from "@/lib/types";
import { useAsync } from "@/lib/useAsync";

type Notice = { tone: "ok" | "warn" | "bad" | "info"; title: string; text?: string };

/** The notice lives in the page, not here: restoring selects a new version, which remounts this panel. */
function VersionDetails({
  v, latest, previous, onChanged, setNotice,
}: {
  v: VersionInfo;
  latest: boolean;
  previous: VersionInfo | undefined;
  onChanged: (select: number) => void;
  setNotice: (n: Notice | null) => void;
}) {
  const [withoutSpec, setWithoutSpec] = useState(false);
  const [busy, setBusy] = useState<"export" | "restore" | null>(null);
  const [installing, setInstalling] = useState(false);
  const [confirmRestore, setConfirmRestore] = useState(false);
  const hasScripts = Object.keys(v.files).some((p) => p.startsWith("scripts/"));
  const hasSpec = "spec.json" in v.files;

  async function exportZip() {
    setBusy("export");
    setNotice(null);
    try {
      const { blob, filename } = await api.exportZip(v.name, v.version, withoutSpec);
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = filename;
      document.body.append(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
      setNotice({
        tone: hasScripts ? "warn" : "ok",
        title: `Exported ${filename}`,
        text: hasScripts ? "This skill has scripts. Whoever uses it should read them first: an agent runs them on that machine, not in a sandbox." : undefined,
      });
    } catch (e) {
      setNotice({ tone: "bad", title: "It could not be exported", text: e instanceof Error ? e.message : String(e) });
    } finally {
      setBusy(null);
    }
  }

  async function restore() {
    setBusy("restore");
    setNotice(null);
    try {
      const r = await api.rollback(v.name, v.version);
      setConfirmRestore(false);
      setNotice({
        tone: r.created ? "ok" : "info",
        title: r.created ? `Restored: ${r.version.tag} now has the content of ${v.tag}` : "Nothing to do",
        text: r.created ? "Older versions are kept." : `The latest version already has the content of ${v.tag}.`,
      });
      onChanged(r.version.version);
    } catch (e) {
      setConfirmRestore(false);
      setNotice({ tone: "bad", title: "It could not be restored", text: e instanceof Error ? e.message : String(e) });
    } finally {
      setBusy(null);
    }
  }

  return (
    <Card className="p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h2 className="flex flex-wrap items-center gap-2 text-lg font-semibold">
            {v.tag} {latest && <Badge tone="info">latest</Badge>}
            {v.skill_version && <Badge title="The version written inside the skill itself">skill version {v.skill_version}</Badge>}
          </h2>
          <p className="text-sm text-muted">
            <span title={formatWhen(v.created_at)}>{relativeTime(v.created_at)}</span> · {sourceText(v.source_kind, v.source_label)} · {plural(Object.keys(v.files).length, "file")} ·{" "}
            <span title="SHA-256 of all the files together" className="font-mono">
              {shortHash(v.content_hash)}
            </span>
          </p>
          {v.note && <p className="mt-1 text-sm">&ldquo;{v.note}&rdquo;</p>}
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {previous && <ButtonLink href={`/library/${v.name}/diff?from=${previous.version}&to=${v.version}`}>Changes since {previous.tag}</ButtonLink>}
          <Button busy={busy === "export"} onClick={() => void exportZip()}>
            Export .zip
          </Button>
          <Button onClick={() => setInstalling(true)}>Install…</Button>
          {!latest && (
            <Button variant="danger" onClick={() => setConfirmRestore(true)}>
              Restore this version…
            </Button>
          )}
        </div>
      </div>
      {hasSpec && (
        <label className="mt-2 flex items-center gap-2 text-sm text-muted">
          <input type="checkbox" checked={withoutSpec} onChange={(e) => setWithoutSpec(e.target.checked)} />
          Leave spec.json out of the export (it holds the requester&apos;s own words)
        </label>
      )}

      <div className="mt-5 space-y-6">
        <section>
          <h3 className="mb-2 font-semibold">Files</h3>
          <FileViewer id={`${v.name}/${v.version}`} paths={Object.keys(v.files)} hashes={v.files} load={(p) => api.file(v.name, v.version, p)} />
        </section>
        <section>
          <h3 className="mb-2 font-semibold">Checks when it was imported</h3>
          <CheckList checks={v.checks} />
          <p className="mt-2 text-xs text-muted">Static checks only. Passing is not proof that a skill is safe.</p>
        </section>
      </div>

      {installing && <InstallDialog version={v} open onClose={() => setInstalling(false)} />}
      <Modal open={confirmRestore} onClose={() => setConfirmRestore(false)} title={`Restore ${v.tag}?`}>
        <p className="text-sm">
          This adds a <strong>new</strong> version with exactly the content of {v.tag}. Nothing is deleted: every older version stays, and you can restore any of them
          later.
        </p>
        <div className="mt-4 flex justify-end gap-2">
          <Button onClick={() => setConfirmRestore(false)}>Cancel</Button>
          <Button variant="primary" busy={busy === "restore"} onClick={() => void restore()}>
            Restore {v.tag}
          </Button>
        </div>
      </Modal>
    </Card>
  );
}

export default function SkillPage() {
  const { name } = useParams<{ name: string }>();
  const data = useAsync(() => api.versions(name), name);
  const [picked, setPicked] = useState<number | null>(null);
  const [notice, setNotice] = useState<Notice | null>(null);

  if (data.error) {
    return (
      <>
        <PageHeader title={name} />
        <ErrorBox error={data.error} onRetry={data.reload} />
        <p className="mt-4 text-sm">
          <Link href="/library" className="text-accent underline">
            Back to the library
          </Link>
        </p>
      </>
    );
  }
  if (!data.data) return <Loading what={name} />;

  const versions = data.data.versions; // newest first
  const selected = versions.find((v) => v.version === picked) ?? versions[0];
  const previous = versions.find((v) => v.version < selected.version);

  return (
    <>
      <p className="mb-2 text-sm">
        <Link href="/library" className="text-accent underline">
          Library
        </Link>{" "}
        / {name}
      </p>
      <PageHeader
        title={name}
        subtitle={`${plural(versions.length, "version")}. Pick one to read its files and checks, export it, install it or restore it.`}
        actions={versions.length > 1 ? <ButtonLink href={`/library/${name}/diff`}>Compare versions</ButtonLink> : undefined}
      />
      <div className="space-y-6">
        <Card>
          <h2 className="sr-only">Versions</h2>
          <ul className="divide-y divide-border">
            {versions.map((v, i) => (
              <li key={v.version}>
                <button
                  type="button"
                  onClick={() => {
                    setPicked(v.version);
                    setNotice(null);
                  }}
                  aria-current={v.version === selected.version ? "true" : undefined}
                  className={`block w-full px-4 py-3 text-left ${v.version === selected.version ? "bg-accent-soft" : "hover:bg-surface-2"}`}
                >
                  <span className="flex flex-wrap items-center gap-x-3 gap-y-1">
                    <span className="font-medium">{v.tag}</span>
                    {i === 0 && <Badge tone="info">latest</Badge>}
                    <span className="text-sm text-muted" title={formatWhen(v.created_at)}>
                      {relativeTime(v.created_at)} · {sourceText(v.source_kind, v.source_label)}
                    </span>
                    {v.note && <span className="text-sm">&ldquo;{v.note}&rdquo;</span>}
                    <span className="ml-auto">
                      <CheckBadges checks={v.checks} />
                    </span>
                  </span>
                </button>
              </li>
            ))}
          </ul>
        </Card>
        <div aria-live="polite">
          {notice && (
            <Alert tone={notice.tone} title={notice.title} onDismiss={() => setNotice(null)}>
              {notice.text}
            </Alert>
          )}
        </div>
        <VersionDetails
          key={selected.version}
          v={selected}
          latest={selected.version === versions[0].version}
          previous={previous}
          setNotice={setNotice}
          onChanged={(n) => {
            setPicked(n);
            data.reload();
          }}
        />
        <RescanPanel name={name} />
      </div>
    </>
  );
}
