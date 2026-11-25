"use client";

import { NoSkillsHere, SkillVersionPicker, useSkillTarget } from "@/components/SkillVersionPicker";
import { ErrorBox, Loading, PageHeader } from "@/components/ui";
import { api } from "@/lib/api";
import { useAsync } from "@/lib/useAsync";
import { QualityReportView } from "./QualityReportView";

/** The report of one version, read when it is chosen (and again with "Check again"): it only reads, so looking costs nothing. */
function ReportFor({ name, version }: { name: string; version: number }) {
  const report = useAsync(() => api.qualityReport(name, version), `quality/${name}/${version}`);
  if (report.error) return <ErrorBox error={report.error} onRetry={report.reload} />;
  if (!report.data) return <Loading what={`the report on ${name} v${version}`} />;
  return <QualityReportView report={report.data} />;
}

/** The Quality Report: what the checks found on one version of a skill, what did not run, and what to do next. */
export function QualityPage() {
  const target = useSkillTarget("/quality");
  const { name, version, latest } = target;
  return (
    <>
      <PageHeader
        title="Quality Report"
        subtitle="What the checks found on one version of a skill, what did not run, and what to do next. It lists what ran and never says a skill is safe."
      />
      <div className="space-y-6">
        <SkillVersionPicker target={target} onChoose={target.go} emptyTitle="No skills to report on yet" emptyText={NoSkillsHere} />
        {name && version !== undefined && latest !== undefined && <ReportFor key={`${name}/${version}`} name={name} version={version} />}
      </div>
    </>
  );
}
