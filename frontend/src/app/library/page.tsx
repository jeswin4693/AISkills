"use client";

import Link from "next/link";
import { CheckBadges } from "@/components/CheckList";
import { ImportPanel } from "@/components/ImportPanel";
import { Badge, Card, Empty, ErrorBox, Loading, PageHeader } from "@/components/ui";
import { api } from "@/lib/api";
import { formatWhen, plural, relativeTime, sourceText } from "@/lib/format";
import { useAsync } from "@/lib/useAsync";

export default function LibraryPage() {
  const skills = useAsync(api.listSkills, "skills");
  return (
    <>
      <PageHeader
        title="Library"
        subtitle="Skills you have kept, as numbered versions. Every skill passed the static checks to get in, and is checked again before it leaves."
      />
      <div className="space-y-6">
        <ImportPanel onImported={skills.reload} />
        {skills.error ? (
          <ErrorBox error={skills.error} onRetry={skills.reload} />
        ) : skills.data === undefined ? (
          <Loading what="skills" />
        ) : skills.data.length === 0 ? (
          <Empty title="No skills yet">Import a .zip above. A skill built in the builder will appear here once you save it.</Empty>
        ) : (
          <Card>
            <ul className="divide-y divide-border">
              {skills.data.map((s) => (
                <li key={s.name}>
                  <Link href={`/library/${s.name}`} className="block px-4 py-3 hover:bg-surface-2 focus-visible:bg-surface-2">
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
      </div>
    </>
  );
}
