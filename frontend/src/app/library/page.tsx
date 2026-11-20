"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense } from "react";
import { CheckBadges } from "@/components/CheckList";
import { ImportPanel } from "@/components/ImportPanel";
import { RescanPanel } from "@/components/RescanPanel";
import { Badge, Card, Empty, ErrorBox, Loading, PageHeader } from "@/components/ui";
import { api } from "@/lib/api";
import { kindNoun, withArticle } from "@/lib/builder";
import { formatWhen, plural, relativeTime, sourceText } from "@/lib/format";
import { withKindParam } from "@/lib/kind";
import { useAsync } from "@/lib/useAsync";
import { useKinds } from "@/lib/useKinds";

const capital = (text: string) => text.charAt(0).toUpperCase() + text.slice(1);

function LibraryContent({ kind }: { kind: string }) {
  const kinds = useKinds();
  const noun = kindNoun(kinds.data, kind);
  const skills = useAsync(() => api.listSkills(kind), `skills/${kind}`);
  return (
    <>
      <PageHeader
        title="Library"
        subtitle={`${capital(noun)}s you have kept, as numbered versions. Every ${noun} passed the static checks to get in, and is checked again before it leaves.`}
      />
      <div className="space-y-6">
        {(kinds.data?.length ?? 0) > 1 && (
          <nav aria-label="What is kept" className="flex flex-wrap gap-2">
            {(kinds.data ?? []).map((k) => (
              <Link
                key={k.key}
                href={withKindParam("/library", k.key)}
                aria-current={k.key === kind ? "page" : undefined}
                className={`rounded-full border px-3 py-1 text-sm ${k.key === kind ? "border-accent bg-accent-soft font-medium" : "border-border hover:bg-surface-2"}`}
              >
                {k.label}s
              </Link>
            ))}
          </nav>
        )}
        <ImportPanel
          onImported={skills.reload} kind={kind} noun={noun}
          definitionFile={kinds.data?.find((k) => k.key === kind)?.definition_file ?? "SKILL.md"}
        />
        {skills.error ? (
          <ErrorBox error={skills.error} onRetry={skills.reload} />
        ) : skills.data === undefined ? (
          <Loading what={`${noun}s`} />
        ) : skills.data.length === 0 ? (
          <Empty title={`No ${noun}s yet`}>
            Import a .zip above. {capital(withArticle(noun))} built in the builder will appear here once you save it.
          </Empty>
        ) : (
          <Card>
            <ul className="divide-y divide-border">
              {skills.data.map((s) => (
                <li key={s.name}>
                  <Link href={withKindParam(`/library/${s.name}`, kind)} className="block px-4 py-3 hover:bg-surface-2 focus-visible:bg-surface-2">
                    <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
                      <span className="font-medium">{s.name}</span>
                      {s.latest && <Badge tone="info">{s.latest.tag}</Badge>}
                      <span className="text-sm text-muted">{plural(s.versions, "version")}</span>
                      {s.latest && (
                        <span className="text-sm text-muted" title={formatWhen(s.latest.created_at)}>
                          updated {relativeTime(s.latest.created_at)} · {sourceText(s.latest.source_kind, s.latest.source_label)}
                        </span>
                      )}
                    </div>
                    <div className="mt-1.5">
                      {s.error ? <Badge tone="bad" title={s.error}>damaged: open it for details</Badge> : s.latest && <CheckBadges checks={s.latest.checks} />}
                    </div>
                  </Link>
                </li>
              ))}
            </ul>
          </Card>
        )}
        {skills.data !== undefined && skills.data.length > 0 && <RescanPanel kind={kind} />}
      </div>
    </>
  );
}

/** Keyed by the kind, so switching tabs starts a fresh page: no rows, import result or re-check from the other kind stay behind. */
function LibraryByKind() {
  const kind = useSearchParams().get("kind") ?? "skill";
  return <LibraryContent key={kind} kind={kind} />;
}

/** The kind is read from the address, which a statically built page may only do inside a Suspense boundary. */
export default function LibraryPage() {
  return (
    <Suspense fallback={<Loading what="the library" />}>
      <LibraryByKind />
    </Suspense>
  );
}
