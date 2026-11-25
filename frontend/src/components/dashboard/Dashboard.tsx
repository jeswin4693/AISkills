"use client";

import Link from "next/link";
import { api } from "@/lib/api";
import { statusInfo } from "@/lib/builder";
import { attentionItems, buildLabel, libraryOverview, type AttentionItem, type AttentionTone } from "@/lib/dashboard";
import { formatWhen, plural, relativeTime } from "@/lib/format";
import { withKindParam } from "@/lib/kind";
import type { RescanResult, SkillSummary } from "@/lib/types";
import { useAsync } from "@/lib/useAsync";
import { useKinds } from "@/lib/useKinds";
import { Alert, Badge, Button, ButtonLink, Card, Empty, Loading, PageHeader } from "../ui";

type KindRef = { key: string; label: string };
type Library = { kind: string; label: string; skills?: SkillSummary[]; error?: string };
type Scan = { kind: string; label: string; result?: RescanResult; error?: string };

const TONE_WORD: Record<AttentionTone, string> = { bad: "Problem", warn: "Warning", info: "To do" };
const messageOf = (e: unknown): string => (e instanceof Error ? e.message : String(e));

async function loadLibraries(kinds: KindRef[]): Promise<Library[]> {
  return Promise.all(
    kinds.map(async (k) => {
      try {
        return { kind: k.key, label: k.label, skills: await api.listSkills(k.key) };
      } catch (e) {
        return { kind: k.key, label: k.label, error: messageOf(e) };
      }
    }),
  );
}

async function loadScans(kinds: KindRef[]): Promise<Scan[]> {
  return Promise.all(
    kinds.map(async (k) => {
      try {
        return { kind: k.key, label: k.label, result: await api.rescan(undefined, k.key) };
      } catch (e) {
        return { kind: k.key, label: k.label, error: messageOf(e) };
      }
    }),
  );
}

function Item({ item }: { item: AttentionItem }) {
  return (
    <li className="flex gap-3 py-2.5">
      <span className="w-16 shrink-0 pt-0.5">
        <Badge tone={item.tone}>{TONE_WORD[item.tone]}</Badge>
      </span>
      <span className="min-w-0 text-sm">
        {item.href ? (
          <Link href={item.href} className="font-medium underline-offset-2 hover:underline">
            {item.title}
          </Link>
        ) : (
          <span className="font-medium">{item.title}</span>
        )}
        {item.detail && <span className="block break-words text-muted">{item.detail}</span>}
      </span>
    </li>
  );
}

/**
 * The first page: what needs the person, what the library holds, the latest builds, and where to start. Everything comes from endpoints that already exist,
 * every part loads on its own, and a part that cannot be read says so: "nothing needs you" is only ever said about what was really looked at.
 */
export function Dashboard() {
  const kinds = useKinds();
  // Until the server says which kinds there are (or if it cannot say) the skill is the one kind everyone has.
  const kindList: KindRef[] | undefined = kinds.data ?? (kinds.error ? [{ key: "skill", label: "Skill" }] : undefined);
  const kindKey = kindList?.map((k) => k.key).join(",") ?? "unknown";
  const libraries = useAsync(() => (kindList ? loadLibraries(kindList) : Promise.resolve([])), `dashboard-library/${kindKey}`);
  const scans = useAsync(() => (kindList ? loadScans(kindList) : Promise.resolve([])), `dashboard-scan/${kindKey}`);
  const builds = useAsync(api.builds, "dashboard-builds");
  const provider = useAsync(api.provider, "dashboard-provider");
  const sandbox = useAsync(api.sandbox, "dashboard-sandbox");

  const checking = !kindList || libraries.loading || scans.loading || builds.loading;
  const problems = [
    ...(scans.data ?? []).filter((s) => s.error !== undefined).map((s) => `Today's checks on the ${s.label.toLowerCase()} library could not be run: ${s.error}`),
    ...(builds.error ? [`The builds could not be read: ${builds.error.message}`] : []),
  ];
  const readable = (scans.data ?? []).flatMap((s) => (s.result ? [{ kind: s.kind, label: s.label, result: s.result }] : []));
  const { items, more } = attentionItems({ scans: readable, builds: builds.data ?? [], provider: provider.data, sandbox: sandbox.data });
  const overview = libraryOverview(libraries.data ?? []);
  const checkedVersions = readable.reduce((sum, s) => sum + s.result.versions.length, 0);
  const again = () => {
    kinds.reload();
    libraries.reload();
    scans.reload();
    builds.reload();
    provider.reload();
    sandbox.reload();
  };

  return (
    <>
      <PageHeader
        title="Dashboard"
        subtitle="What needs you, what you have, and where to start. It only reads: today's checks on what is stored, your builds, and whether the model and the sandbox are ready."
        actions={
          <Button onClick={again} busy={checking}>
            Check again
          </Button>
        }
      />
      <div className="space-y-6">
        <Card className="p-5">
          <h2 className="text-lg font-semibold">Needs attention</h2>
          {checking ? (
            <div className="mt-2">
              <Loading what="what needs you" />
            </div>
          ) : (
            <>
              {items.length > 0 && (
                <ul className="mt-2 divide-y divide-border">
                  {items.map((item) => (
                    <Item key={item.key} item={item} />
                  ))}
                </ul>
              )}
              {more > 0 && <p className="mt-2 text-sm text-muted">…and {plural(more, "more item")}. Open the Library and the builds to see them.</p>}
              {items.length === 0 && problems.length === 0 && (
                <>
                  <p className="mt-2 font-medium">Nothing needs you right now.</p>
                  <p className="mt-0.5 text-sm text-muted">
                    That is about what was looked at: today&apos;s checks on {plural(checkedVersions, "stored version")}, {plural((builds.data ?? []).length, "build")}, the model and the sandbox.
                  </p>
                </>
              )}
              {problems.length > 0 && (
                <div className="mt-3 space-y-2">
                  {problems.map((p) => (
                    <Alert key={p} tone="warn" title="Something could not be checked">
                      {p}
                    </Alert>
                  ))}
                </div>
              )}
            </>
          )}
        </Card>

        <div className="grid gap-6 md:grid-cols-2">
          <Card className="p-5">
            <h2 className="text-lg font-semibold">Your library</h2>
            {!kindList || libraries.loading ? (
              <div className="mt-2">
                <Loading what="the library" />
              </div>
            ) : (
              <>
                <ul className="mt-2 divide-y divide-border">
                  {overview.rows.map((r) => (
                    <li key={r.kind} className="flex items-baseline justify-between gap-3 py-2 text-sm">
                      <Link href={withKindParam("/library", r.kind)} className="font-medium underline-offset-2 hover:underline">
                        {r.label}
                      </Link>
                      {r.error !== undefined ? (
                        <span className="text-right">
                          <Badge tone="bad">could not be read</Badge>
                          <span className="block break-words text-muted">{r.error}</span>
                        </span>
                      ) : (
                        <span className="text-muted">
                          {r.skills} saved · {plural(r.versions, "version")}
                        </span>
                      )}
                    </li>
                  ))}
                </ul>
                {overview.total.skills === 0 && overview.rows.every((r) => r.error === undefined) ? (
                  <div className="mt-3">
                    <Empty title="Nothing saved yet">Build one, or import a .zip in the Library.</Empty>
                  </div>
                ) : (
                  overview.recent.length > 0 && (
                    <>
                      <h3 className="mt-4 text-xs font-semibold uppercase tracking-wide text-muted">Saved most recently</h3>
                      <ul className="mt-1 divide-y divide-border">
                        {overview.recent.map((r) => (
                          <li key={`${r.kind}/${r.name}`} className="flex items-baseline justify-between gap-3 py-1.5 text-sm">
                            <Link href={r.href} className="min-w-0 truncate font-medium underline-offset-2 hover:underline">
                              {r.name} <span className="font-normal text-muted">{r.tag}</span>
                            </Link>
                            <span className="shrink-0 text-muted" title={formatWhen(r.created_at)}>
                              {relativeTime(r.created_at)}
                            </span>
                          </li>
                        ))}
                      </ul>
                    </>
                  )
                )}
              </>
            )}
          </Card>

          <Card className="p-5">
            <h2 className="text-lg font-semibold">Recent builds</h2>
            {builds.loading ? (
              <div className="mt-2">
                <Loading what="the builds" />
              </div>
            ) : builds.error ? (
              <p className="mt-2 text-sm text-muted">They could not be read: {builds.error.message}</p>
            ) : (builds.data ?? []).length === 0 ? (
              <div className="mt-3">
                <Empty title="No builds yet">Describe what you want in the Builder.</Empty>
              </div>
            ) : (
              <ul className="mt-2 divide-y divide-border">
                {(builds.data ?? []).slice(0, 5).map((b) => {
                  const s = statusInfo(b.status);
                  return (
                    <li key={b.id} className="flex flex-wrap items-center gap-x-3 gap-y-1 py-2 text-sm">
                      <Link href={`/builder/${b.id}`} className="min-w-0 flex-1 truncate font-medium underline-offset-2 hover:underline">
                        {buildLabel(b)}
                      </Link>
                      <Badge tone={s.tone}>{s.label}</Badge>
                      {b.status === "done" && b.draft && <Badge tone="warn">draft</Badge>}
                      {b.saved && <Badge tone="ok">saved {b.saved.version}</Badge>}
                      <span className="text-muted" title={formatWhen(b.updated_at)}>
                        {relativeTime(b.updated_at)}
                      </span>
                    </li>
                  );
                })}
              </ul>
            )}
          </Card>
        </div>

        <Card className="p-5">
          <h2 className="text-lg font-semibold">Start something</h2>
          <div className="mt-3 flex flex-wrap gap-3">
            <ButtonLink href="/builder" variant="primary">
              Build something
            </ButtonLink>
            <ButtonLink href="/repository">Read a repository</ButtonLink>
            <ButtonLink href="/library">Import into the library</ButtonLink>
            <ButtonLink href="/composer">Combine into a plugin</ButtonLink>
          </div>
        </Card>
      </div>
    </>
  );
}
