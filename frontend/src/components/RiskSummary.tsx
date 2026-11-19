import { DIRECTION_LABEL, DIRECTION_TONE, riskCounts, riskHeadline } from "@/lib/risk";
import type { RiskInfo } from "@/lib/types";
import { Alert, Badge } from "./ui";

/**
 * What got riskier between two versions, as code saw it. The headline never says "safe", the limit is always shown
 * under the list, and every line carries its own label so colour is never the only signal.
 */
export function RiskSummary({ risk }: { risk: RiskInfo }) {
  const { tone, title } = riskHeadline(risk.level);
  const counts = riskCounts(risk);
  return (
    <Alert tone={tone} title={`${risk.older} → ${risk.newer}: ${title}`}>
      {counts && <p className="mb-2 text-muted">{counts}</p>}
      {risk.changes.length > 0 && (
        <ul className="space-y-1.5">
          {risk.changes.map((c, i) => (
            <li key={i} className="flex flex-wrap items-start gap-x-2 gap-y-0.5">
              <Badge tone={DIRECTION_TONE[c.direction]}>{DIRECTION_LABEL[c.direction]}</Badge>
              <span className="min-w-0 flex-1 break-words">{c.detail}</span>
            </li>
          ))}
        </ul>
      )}
      <p className="mt-2 text-xs text-muted">{risk.note}</p>
    </Alert>
  );
}
