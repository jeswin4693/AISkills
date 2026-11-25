"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useId, type ReactNode } from "react";
import { api } from "@/lib/api";
import { parseVersion, pickVersion } from "@/lib/testing";
import { useAsync } from "@/lib/useAsync";
import { Card, Empty, ErrorBox, Loading } from "./ui";

export const SELECT = "rounded-md border border-border bg-surface px-3 py-1.5 text-sm";

/**
 * A label tied to its control by id, not wrapped around it: a wrapping label's text includes every option of a select, so it would name the
 * control "SkillChoose a skill…e2e-demo…" for anything that reads the label's text.
 */
export function Field({ label, children }: { label: string; children: (id: string) => ReactNode }) {
  const id = useId();
  return (
    <div className="text-sm">
      <label htmlFor={id} className="mb-1 block font-medium">
        {label}
      </label>
      {children(id)}
    </div>
  );
}

/**
 * Which skill and which version a page is about, kept in the address (`?name=&version=`) so a link can point straight at one. The version asked for
 * is used when it exists, otherwise the latest. Shared by the Testing Lab and the Quality Report.
 */
export function useSkillTarget(path: string) {
  const router = useRouter();
  const params = useSearchParams();
  const name = params.get("name") ?? "";
  const wanted = parseVersion(params.get("version"));
  const skills = useAsync(() => api.listSkills("skill"), "picker-skills");
  const versions = useAsync(() => (name ? api.versions(name) : Promise.resolve(null)), `picker-versions/${name}`);
  const list = versions.data?.versions ?? [];
  const version = pickVersion(list, wanted);
  const latest = list.length ? Math.max(...list.map((v) => v.version)) : undefined;
  const go = (n: string, v?: number) => router.replace(`${path}${n ? `?name=${encodeURIComponent(n)}${v ? `&version=${v}` : ""}` : ""}`, { scroll: false });
  return { name, version, latest, list, skills, versions, go, reloadVersions: versions.reload };
}

export type SkillTarget = ReturnType<typeof useSkillTarget>;

/** The two selects, and what to show while the skills or the versions load, fail, or are not there. */
export function SkillVersionPicker({
  target, onChoose, emptyTitle, emptyText,
}: { target: SkillTarget; onChoose: (name: string, version?: number) => void; emptyTitle: string; emptyText: ReactNode }) {
  const { name, version, latest, list, skills, versions } = target;
  return (
    <>
      {skills.error ? (
        <ErrorBox error={skills.error} onRetry={skills.reload} />
      ) : skills.data === undefined ? (
        <Loading what="your skills" />
      ) : skills.data.length === 0 ? (
        <Empty title={emptyTitle}>{emptyText}</Empty>
      ) : (
        <Card className="p-4">
          <div className="flex flex-wrap items-end gap-4">
            <Field label="Skill">
              {(id) => (
                <select id={id} className={SELECT} value={name} onChange={(e) => onChoose(e.target.value)}>
                  <option value="">Choose a skill…</option>
                  {(skills.data ?? []).map((s) => (
                    <option key={s.name} value={s.name}>
                      {s.name}
                    </option>
                  ))}
                </select>
              )}
            </Field>
            {name && list.length > 0 && version !== undefined && (
              <Field label="Version">
                {(id) => (
                  <select id={id} className={SELECT} value={version} onChange={(e) => onChoose(name, Number(e.target.value))}>
                    {list.map((v) => (
                      <option key={v.version} value={v.version}>
                        {v.tag}
                        {v.version === latest ? " (latest)" : ""}
                      </option>
                    ))}
                  </select>
                )}
              </Field>
            )}
          </div>
        </Card>
      )}
      {name && versions.error && <ErrorBox error={versions.error} onRetry={versions.reload} />}
      {name && !versions.error && versions.data === undefined && <Loading what={name} />}
    </>
  );
}

/** The usual text of the empty state: where a skill comes from. */
export const NoSkillsHere = (
  <>
    Build one in the Builder or import one into the{" "}
    <Link href="/library" className="underline">
      Library
    </Link>
    , then come back.
  </>
);
