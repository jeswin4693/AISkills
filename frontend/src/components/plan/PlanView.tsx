"use client";

import { useState, type ReactNode } from "react";
import { plural } from "@/lib/format";
import { budgetSentence, gapGroups, gapSource, modelLine, namedCode, notReadText, readLine, signalLine, tierSentence } from "@/lib/plan";
import type { PlanGap, PlanItem, TaskPlan } from "@/lib/types";
import { Badge, Button, Card } from "../ui";

const TH = "border-b border-border px-2 py-1.5 text-left font-medium";
const TD = "border-b border-border px-2 py-1.5 align-top";

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="space-y-3">
      <h3 className="text-base font-semibold">{title}</h3>
      {children}
    </section>
  );
}

function Table({ head, children, label }: { head: string[]; children: ReactNode; label: string }) {
  return (
    <div className="overflow-x-auto">
      <table aria-label={label} className="w-full min-w-[32rem] border-collapse text-sm">
        <thead>
          <tr>
            {head.map((h) => (
              <th key={h} scope="col" className={TH}>
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>{children}</tbody>
      </table>
    </div>
  );
}

/** What the person asked for, each with the words that say so (the server checked that the words are really in the request). */
function Said({ title, items }: { title: string; items: PlanItem[] }) {
  return (
    <div>
      <h4 className="font-medium">{title}</h4>
      {items.length === 0 ? (
        <p className="text-muted">None.</p>
      ) : (
        <ul className="mt-1 list-disc space-y-1 pl-5">
          {items.map((i) => (
            <li key={`${i.text}|${i.quote}`}>
              {i.text} <span className="text-muted">— “{i.quote}”</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function Question({ gap }: { gap: PlanGap }) {
  return (
    <li className="space-y-0.5">
      <p>
        {gap.blocking && <Badge tone="bad">Blocking</Badge>} <span className="font-medium">{gap.question}</span>
      </p>
      <p className="text-muted">
        {gap.why} ({gapSource(gap)})
      </p>
    </li>
  );
}

/** Copy the plan as Markdown (the same text the command prints), or save it as a file. The page keeps nothing: this is how a plan leaves it. */
function Share({ markdown, repo }: { markdown: string; repo: string }) {
  const [state, setState] = useState<"idle" | "copied" | "failed">("idle");
  async function copy() {
    try {
      await navigator.clipboard.writeText(markdown);
      setState("copied");
    } catch {
      setState("failed"); // a browser that refuses the clipboard: the download below still works
    }
  }
  function download() {
    const url = URL.createObjectURL(new Blob([markdown], { type: "text/markdown" }));
    const link = document.createElement("a");
    link.href = url;
    link.download = `task-plan${repo ? `-${repo.replace(/[^A-Za-z0-9._-]+/g, "-")}` : ""}.md`;
    link.click();
    URL.revokeObjectURL(url);
  }
  return (
    <div className="flex flex-wrap items-center gap-2">
      <Button onClick={() => void copy()}>Copy as Markdown</Button>
      <Button onClick={download}>Download .md</Button>
      <span role="status" className="text-sm text-muted">
        {state === "copied" ? "Copied." : state === "failed" ? "The browser did not allow copying: use Download." : ""}
      </span>
    </div>
  );
}

/** A Task Plan in the order the command prints it. Everything here comes from the server's answer; nothing is added that the plan does not say. */
export function PlanView({ plan }: { plan: TaskPlan }) {
  const r = plan.reading;
  const modelRead = plan.mode === "model";
  const groups = gapGroups(r.gaps);
  const named = namedCode(plan);
  const tp = plan.token_plan;
  return (
    <Card className="space-y-6 p-5">
      <div className="space-y-2">
        <div className="flex flex-wrap items-center gap-2">
          <h2 className="text-lg font-semibold">Task plan</h2>
          <Badge tone={modelRead ? "info" : "neutral"}>{modelRead ? "Read by a model" : "Facts only"}</Badge>
        </div>
        <p className="text-sm text-muted">{modelLine(plan)}</p>
        <p className="text-sm font-medium">A plan only. Nothing was run, and nothing was changed or created.</p>
        <blockquote className="border-l-2 border-border pl-3 text-sm break-words whitespace-pre-wrap">{plan.prompt}</blockquote>
        <Share markdown={plan.markdown} repo={plan.repo} />
      </div>

      <Section title={modelRead ? "1. What your request contains" : "1. What your request contains, and what it does not say"}>
        <div className="space-y-3 text-sm">
          {modelRead ? (
            <>
              <p>
                <span className="font-medium">Kind of task:</span> {r.task_type}. {r.summary}
              </p>
              <Said title="You asked for" items={r.stated} />
              <Said title="Rules you gave" items={r.constraints} />
              <Said title="You said NOT to" items={r.out_of_scope} />
              <Said title="Risks you named" items={r.declared_risks} />
            </>
          ) : (
            <p>{notReadText(plan)}</p>
          )}
          <div>
            <h4 className="font-medium">Code your request names (matched in the repository)</h4>
            {named.length === 0 ? (
              <p className="text-muted">None.</p>
            ) : (
              <ul className="mt-1 list-disc space-y-0.5 pl-5">
                {named.map((line) => (
                  <li key={line} className="font-mono break-all">
                    {line}
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>
      </Section>

      <Section title={modelRead ? "2. What it does NOT say" : "2. Questions the code graph found"}>
        <div className="space-y-3 text-sm">
          <div>
            <h4 className="font-medium">
              Questions ({groups.blocking.length} blocking, {groups.other.length} other)
              {modelRead ? ": answer these before work starts" : ""}
            </h4>
            {r.gaps.length === 0 ? (
              <p className="text-muted">None.</p>
            ) : (
              <ul className="mt-1 space-y-2">
                {[...groups.blocking, ...groups.other].map((g) => (
                  <Question key={g.question} gap={g} />
                ))}
              </ul>
            )}
          </div>
          {modelRead && (
            <div>
              <h4 className="font-medium">Assumptions (not facts: none is used until you approve it)</h4>
              {r.assumptions.length === 0 ? (
                <p className="text-muted">None.</p>
              ) : (
                <ul className="mt-1 list-disc space-y-1 pl-5">
                  {r.assumptions.map((a) => (
                    <li key={a.text}>
                      {a.text} <span className="text-muted">{a.why}</span>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          )}
        </div>
      </Section>

      <Section title="3. Size and process">
        <div className="space-y-3 text-sm">
          <p className="font-medium">{tierSentence(plan)}</p>
          <p className="text-muted">The highest signal wins:</p>
          <ul className="list-disc space-y-0.5 pl-5">
            {plan.tier.signals.map((s) => (
              <li key={s.name}>{signalLine(s)}</li>
            ))}
          </ul>
          {plan.tier.note && <p className="text-muted italic">{plan.tier.note}</p>}
          <p>Phases, each reading one file and writing one file:</p>
          <Table label="Phases" head={["#", "Phase", "Reads", "Writes", "Done when", "A person approves"]}>
            {plan.phases.map((ph, i) => (
              <tr key={ph.id}>
                <td className={TD}>{i + 1}</td>
                <td className={`${TD} font-medium`}>{ph.title}</td>
                <td className={`${TD} break-words`}>{ph.reads}</td>
                <td className={`${TD} break-words`}>{ph.writes}</td>
                <td className={TD}>{ph.gate}</td>
                <td className={TD}>{ph.approval ? "yes" : "no"}</td>
              </tr>
            ))}
          </Table>
          <div>
            <h4 className="font-medium">It stops and asks when</h4>
            <ul className="mt-1 list-disc space-y-0.5 pl-5">
              {plan.stop_triggers.map((s) => (
                <li key={s}>{s}</li>
              ))}
            </ul>
          </div>
        </div>
      </Section>

      <Section title="4. Rules that apply">
        <div className="space-y-3 text-sm">
          <p>
            {plural(plan.rules.length, "rule")} listed, from {plan.rules_found} found in the repository&apos;s rule files and your own words. <strong>None is enforced yet</strong>:
            a person must review each one.
          </p>
          <Table label="Rules" head={["Id", "Source", "Rule", "Why it applies", "Enforcement"]}>
            {plan.rules.length === 0 ? (
              <tr>
                <td className={TD} colSpan={5}>
                  (none)
                </td>
              </tr>
            ) : (
              plan.rules.map((x) => (
                <tr key={`${x.id}|${x.source}|${x.line}|${x.text}`}>
                  <td className={TD}>{x.id}</td>
                  <td className={`${TD} break-all`}>
                    {x.source}
                    {x.line ? `:${x.line}` : ""}
                  </td>
                  <td className={TD}>{x.text}</td>
                  <td className={TD}>{x.why}</td>
                  <td className={TD}>{x.enforcement}</td>
                </tr>
              ))
            )}
          </Table>
        </div>
      </Section>

      <Section title="5. Token plan (estimates)">
        <div className="space-y-3 text-sm">
          <p>
            {budgetSentence(tp)} Method: {tp.method}.
          </p>
          <p className="text-muted">Read in this order, cheapest useful context first:</p>
          <Table label="What to read" head={["#", "What", "Tokens", "Why"]}>
            {tp.reads.length === 0 ? (
              <tr>
                <td className={TD} colSpan={4}>
                  (nothing to read)
                </td>
              </tr>
            ) : (
              tp.reads.map((x, i) => (
                <tr key={`${x.path}|${x.symbol}|${x.lines}`}>
                  <td className={TD}>{i + 1}</td>
                  <td className={`${TD} font-mono break-all`}>{readLine(x)}</td>
                  <td className={TD}>{x.tokens.toLocaleString("en-US")}</td>
                  <td className={TD}>{x.why}</td>
                </tr>
              ))
            )}
          </Table>
          {tp.dropped.length > 0 && (
            <div>
              <h4 className="font-medium">Not planned (over the budget, or beyond the most relevant tests)</h4>
              <ul className="mt-1 list-disc space-y-0.5 pl-5">
                {tp.dropped.map((x) => (
                  <li key={`${x.path}|${x.symbol}|${x.lines}`} className="break-all">
                    <span className="font-mono">{x.path}</span> {x.symbol} ({x.tokens.toLocaleString("en-US")} tokens): {x.why}
                  </li>
                ))}
              </ul>
            </div>
          )}
          <div>
            <h4 className="font-medium">Files the work would create</h4>
            {tp.create.length === 0 ? (
              <p className="text-muted">None.</p>
            ) : (
              <Table label="Files to create" head={["Path", "For", "Size", "Tokens"]}>
                {tp.create.map((c) => (
                  <tr key={c.path}>
                    <td className={`${TD} font-mono break-all`}>{c.path}</td>
                    <td className={TD}>{c.purpose}</td>
                    <td className={TD}>{c.size}</td>
                    <td className={TD}>{c.tokens.toLocaleString("en-US")}</td>
                  </tr>
                ))}
              </Table>
            )}
          </div>
        </div>
      </Section>

      {plan.notes.length > 0 && (
        <Section title="Notes">
          <ul className="list-disc space-y-0.5 pl-5 text-sm">
            {plan.notes.map((x) => (
              <li key={x}>{x}</li>
            ))}
          </ul>
        </Section>
      )}

      <Section title="What was NOT checked">
        <ul className="list-disc space-y-0.5 pl-5 text-sm">
          {plan.not_checked.map((x) => (
            <li key={x}>{x}</li>
          ))}
        </ul>
      </Section>
    </Card>
  );
}
