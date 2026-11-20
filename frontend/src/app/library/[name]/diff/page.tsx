"use client";

import Link from "next/link";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import { Suspense } from "react";
import { DiffView } from "@/components/DiffView";
import { RiskSummary } from "@/components/RiskSummary";
import { Card, Empty, ErrorBox, Loading, PageHeader } from "@/components/ui";
import { ApiError, api } from "@/lib/api";
import { kindNoun } from "@/lib/builder";
import { plural } from "@/lib/format";
import { withKindParam } from "@/lib/kind";
import { useAsync } from "@/lib/useAsync";
import { useKinds } from "@/lib/useKinds";

function num(value: string | null): number | undefined {
  const n = Number(value);
  return value !== null && Number.isInteger(n) && n > 0 ? n : undefined;
}

function Diff() {
  const { name } = useParams<{ name: string }>();
  const router = useRouter();
  const params = useSearchParams();
  const from = num(params.get("from"));
  const to = num(params.get("to"));
  const kind = params.get("kind") ?? "skill";
  const noun = kindNoun(useKinds().data, kind);
  const versions = useAsync(() => api.versions(name, kind), `versions/${kind}/${name}`);
  const diff = useAsync(() => api.diff(name, from, to, kind), `diff/${kind}/${name}/${from}/${to}`);

  const tags = versions.data?.versions ?? [];
  const fromNow = diff.data ? Number(diff.data.from.slice(1)) : from;
  const toNow = diff.data ? Number(diff.data.to.slice(1)) : to;
  const go = (a: number | undefined, b: number | undefined) => router.replace(withKindParam(`/library/${name}/diff?from=${a}&to=${b}`, kind));

  return (
    <>
      <p className="mb-2 text-sm">
        <Link href={withKindParam("/library", kind)} className="text-accent underline">
          Library
        </Link>{" "}
        /{" "}
        <Link href={withKindParam(`/library/${name}`, kind)} className="text-accent underline">
          {name}
        </Link>{" "}
        / changes
      </p>
      <PageHeader title="Compare versions" subtitle={`What differs between two versions of this ${noun}. Lines starting with + were added and lines starting with − were removed.`} />
      {tags.length > 1 && (
        <Card className="mb-5 flex flex-wrap items-center gap-3 p-3 text-sm">
          <label className="flex items-center gap-2">
            From
            <select aria-label="From version" value={fromNow ?? ""} onChange={(e) => go(Number(e.target.value), toNow)} className="rounded-md border border-border bg-bg px-2 py-1">
              {tags.map((v) => (
                <option key={v.version} value={v.version}>
                  {v.tag}
                </option>
              ))}
            </select>
          </label>
          <label className="flex items-center gap-2">
            to
            <select aria-label="To version" value={toNow ?? ""} onChange={(e) => go(fromNow, Number(e.target.value))} className="rounded-md border border-border bg-bg px-2 py-1">
              {tags.map((v) => (
                <option key={v.version} value={v.version}>
                  {v.tag}
                </option>
              ))}
            </select>
          </label>
          {diff.data && <span className="text-muted">{plural(diff.data.changes.length, "file")} differ</span>}
        </Card>
      )}
      {diff.error ? (
        diff.error instanceof ApiError && diff.error.status === 400 ? (
          <Empty title="Nothing to compare yet">{diff.error.message}</Empty>
        ) : (
          <ErrorBox error={diff.error} onRetry={diff.reload} />
        )
      ) : !diff.data ? (
        <Loading what="the changes" />
      ) : diff.data.changes.length === 0 ? (
        <Empty title={`${diff.data.from} and ${diff.data.to} are identical`}>Every file has the same content.</Empty>
      ) : (
        <div className="space-y-3">
          <RiskSummary risk={diff.data.risk} />
          {diff.data.changes.map((c) => (
            <DiffView key={c.path} change={c} />
          ))}
        </div>
      )}
    </>
  );
}

export default function DiffPage() {
  return (
    <Suspense fallback={<Loading what="the changes" />}>
      <Diff />
    </Suspense>
  );
}
