"use client";

import { useRouter } from "next/navigation";
import { useEffect, useId, useRef, useState, type FormEvent } from "react";
import { ArchitectureMap } from "@/components/repository/ArchitectureMap";
import { FunctionExplorer } from "@/components/repository/FunctionExplorer";
import { HowItWorks } from "@/components/repository/HowItWorks";
import { IdeaCard } from "@/components/repository/IdeaCard";
import { RepoSummary } from "@/components/repository/RepoSummary";
import { Alert, Badge, Button, Card, Empty, ErrorBox, PageHeader, Spinner } from "@/components/ui";
import { api } from "@/lib/api";
import { plural, relativeTime } from "@/lib/format";
import { buildRequest, canBuild, ideaGroups, ideaKey, isLinkLike, loadRemembered, pathProblem, remember, runInfo, workingRun } from "@/lib/repository";
import type { Guide, Idea, RepoAnalysis } from "@/lib/types";
import { useAsync } from "@/lib/useAsync";
import { useSuggestRun } from "@/lib/useSuggestRun";

export default function RepositoryPage() {
  const router = useRouter();
  const pathId = useId();
  const focusId = useId();
  const provider = useAsync(api.provider, "provider-repository");
  const runs = useAsync(api.suggestRuns, "suggest-runs");
  const [path, setPath] = useState("");
  const [focus, setFocus] = useState("");
  const [analysis, setAnalysis] = useState<RepoAnalysis | null>(null);
  const [reading, setReading] = useState(false);
  const [readError, setReadError] = useState<Error | null>(null);
  const [runId, setRunId] = useState<string | null>(null);
  const { run, error: runError, adopt } = useSuggestRun(runId);
  const [asking, setAsking] = useState(false);
  const [askError, setAskError] = useState<string | null>(null);
  const [edits, setEdits] = useState<Record<string, string>>({}); // the person's own wording of an idea, by run and position
  const [building, setBuilding] = useState<number | null>(null);
  const [buildError, setBuildError] = useState<string | null>(null);
  const [guide, setGuide] = useState<Guide | null>(null);
  const [guiding, setGuiding] = useState(false);
  const [guideError, setGuideError] = useState<string | null>(null);
  // What was last read: the guide is drawn for that, not for whatever the box says now. The counter lets an answer that comes back after another read be ignored.
  const [lastRead, setLastRead] = useState<{ path: string; focus: string } | null>(null);
  const [readCount, setReadCount] = useState(0); // every read starts the function explorer afresh: it belongs to the code as it was read
  const guideSeq = useRef(0);

  useEffect(() => {
    // after mount, so the first render matches the server's: what the browser remembers appears a moment later
    const r = loadRemembered();
    setPath(r.path);
    setFocus(r.focus);
  }, []);

  const modelReady = provider.data?.configured === true;
  const problem = pathProblem(path);

  // a run that is still asking the model (after a reload, or started in another tab) is picked up again instead of asking twice
  useEffect(() => {
    if (runId === null) {
      const working = workingRun(runs.data);
      if (working) setRunId(working.id);
    }
  }, [runs.data, runId]);
  // the list of earlier runs follows the run that is open
  useEffect(() => {
    if (run?.status === "done" || run?.status === "failed") runs.reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [run?.status]);

  async function explain() {
    if (!lastRead) return;
    const mine = ++guideSeq.current;
    setGuiding(true);
    setGuideError(null);
    try {
      const answer = await api.guideRepo(lastRead.path, lastRead.focus);
      if (mine === guideSeq.current) setGuide(answer);
    } catch (err) {
      if (mine === guideSeq.current) setGuideError(err instanceof Error ? err.message : String(err));
    } finally {
      if (mine === guideSeq.current) setGuiding(false);
    }
  }

  async function read() {
    setReading(true);
    setReadError(null);
    guideSeq.current += 1; // a guide still being drawn belonged to the repository before this one: its answer will be ignored
    setGuiding(false);
    setGuide(null); // a guide belongs to the repository it was drawn for: reading another one clears it
    setGuideError(null);
    try {
      const a = await api.analyzeRepo(path.trim(), focus.trim());
      remember({ path: path.trim(), focus: focus.trim() });
      setAnalysis(a);
      setLastRead({ path: path.trim(), focus: focus.trim() });
      setReadCount((n) => n + 1);
    } catch (err) {
      setAnalysis(null);
      setLastRead(null);
      setReadError(err instanceof Error ? err : new Error(String(err)));
    } finally {
      setReading(false);
    }
  }

  async function ask() {
    setAsking(true);
    setAskError(null);
    try {
      const r = await api.startSuggest(path.trim(), focus.trim(), true);
      setRunId(r.id);
      adopt(r);
      runs.reload();
    } catch (err) {
      setAskError(err instanceof Error ? err.message : String(err));
    } finally {
      setAsking(false);
    }
  }

  async function retry() {
    if (!run) return;
    setAskError(null);
    try {
      adopt(await api.retrySuggest(run.id));
    } catch (err) {
      setAskError(err instanceof Error ? err.message : String(err));
    }
  }

  async function build(idea: Idea, index: number) {
    if (!run) return;
    setBuilding(index);
    setBuildError(null);
    try {
      const req = buildRequest(edits[ideaKey(run.id, index)] ?? idea.skill_requirement, run.id, index);
      const s = await api.startBuild(req.description, false, "skill", req.seed); // the server takes the folder and the cited places from the run
      router.push(`/builder/${s.id}`);
    } catch (err) {
      setBuildError(err instanceof Error ? err.message : String(err));
      setBuilding(null);
    }
  }

  const groups = run?.result ? ideaGroups(run.result.suggestions) : { buildable: [], other: [] };

  return (
    <>
      <PageHeader
        title="Repository"
        subtitle="Point SkillForge at a folder on this computer, or at a public GitHub repository. It reads the code into a graph (no model, nothing is run), can explain how the project works from its README and docs, and can ask a model for ideas that must cite code that really exists. A skill built from an idea records those places as evidence."
      />
      <div className="space-y-6">
        <Card className="p-5">
          <form onSubmit={(e: FormEvent) => { e.preventDefault(); void read(); }} className="space-y-3">
            <div>
              <label htmlFor={pathId} className="font-semibold">
                Folder or GitHub link
              </label>
              <input
                id={pathId}
                value={path}
                onChange={(e) => setPath(e.target.value)}
                placeholder="C:\code\shop-api   or   https://github.com/owner/repo"
                autoComplete="off"
                spellCheck={false}
                className="mt-1.5 block w-full rounded-md border border-border bg-bg px-3 py-2 font-mono text-sm"
              />
              {problem && <p className="mt-1 text-sm text-warn">{problem}</p>}
              <p className="mt-1 text-xs text-muted">
                {isLinkLike(path)
                  ? "A link is downloaded from GitHub into a copy on this computer: public repositories only, only source files and README and doc files are kept, and nothing in it is run. The first read takes a little while."
                  : "The path stays on this computer. This page remembers it in your browser only, and shows you the folder's name, never the path."}
              </p>
            </div>
            <div>
              <label htmlFor={focusId} className="font-semibold">
                Only this folder inside it <span className="font-normal text-muted">(optional)</span>
              </label>
              <input
                id={focusId}
                value={focus}
                onChange={(e) => setFocus(e.target.value)}
                placeholder="src"
                autoComplete="off"
                spellCheck={false}
                className="mt-1.5 block w-full max-w-xs rounded-md border border-border bg-bg px-3 py-2 font-mono text-sm"
              />
            </div>
            <div className="flex flex-wrap items-center gap-3">
              <Button type="submit" variant="primary" busy={reading} disabled={!path.trim() || !!problem}>
                Read the repository
              </Button>
              {reading && (
                <span className="text-sm text-muted">
                  {isLinkLike(path) ? "Downloading from GitHub and reading the code (a large repository can take a little while)…" : "Reading the code (a large repository can take a little while)…"}
                </span>
              )}
            </div>
          </form>
        </Card>

        {readError && <ErrorBox error={readError} onRetry={() => void read()} />}
        {analysis && <RepoSummary analysis={analysis} />}
        {analysis && <ArchitectureMap architecture={analysis.architecture} />}
        {analysis && lastRead && <FunctionExplorer key={readCount} path={lastRead.path} focus={lastRead.focus} starters={analysis.hotspots.core_symbols} />}

        {analysis && (
          <section className="space-y-3">
            <div>
              <h2 className="text-lg font-semibold">How it works</h2>
              <p className="mt-0.5 max-w-prose text-sm text-muted">
                For someone new to the project: a model reads the README and docs and draws the main parts, the layers they sit in, and the route an action takes through them. Every
                quote is checked by code against the documents, and each step of the route says whether the code confirms it. That proves the quotes are real, not that the docs are
                up to date.
              </p>
            </div>
            {provider.data && !provider.data.configured && (
              <Alert tone="warn" title="No AI model is set up yet">
                <p>{provider.data.detail}</p>
                <p className="mt-1">This needs a model. Put its settings in the Settings page or the <code className="font-mono">.env</code> file, then reload this page.</p>
              </Alert>
            )}
            <div className="flex flex-wrap items-center gap-3">
              <Button variant="primary" busy={guiding} disabled={!modelReady || !lastRead} onClick={() => void explain()}>
                {guide ? "Draw it again" : "Show how it works"}
              </Button>
              {modelReady && provider.data && <span className="text-sm text-muted">Model: {provider.data.model}. One model call; this uses a little of its quota and nothing is saved.</span>}
            </div>
            {guiding && (
              <p role="status" className="flex items-center gap-2 text-sm text-muted">
                <Spinner /> Reading the docs and asking the model. This takes a few seconds to a minute.
              </p>
            )}
            {guideError && (
              <Alert tone="bad" title="It could not be drawn">
                {guideError}
              </Alert>
            )}
            {guide && <HowItWorks guide={guide} />}
          </section>
        )}

        {(analysis || run) && (
          <section className="space-y-4">
            <div>
              <h2 className="text-lg font-semibold">Ideas for it</h2>
              <p className="mt-0.5 max-w-prose text-sm text-muted">
                A model reads the facts above and suggests what to do. An idea is kept only if every place it cites exists in the graph, and a number it quotes is checked against
                the facts. That proves the places are real, not that the advice is good.
              </p>
            </div>
            {provider.data && !provider.data.configured && (
              <Alert tone="warn" title="No AI model is set up yet">
                <p>{provider.data.detail}</p>
                <p className="mt-1">Ideas need a model. Put its settings in the <code className="font-mono">.env</code> file in the repository&apos;s root folder, then reload this page.</p>
              </Alert>
            )}
            <div className="flex flex-wrap items-center gap-3">
              <Button variant="primary" busy={asking || run?.status === "working"} disabled={!modelReady || !path.trim() || !!problem} onClick={() => void ask()}>
                {run ? "Ask for new ideas" : "Ask for ideas"}
              </Button>
              {modelReady && provider.data && <span className="text-sm text-muted">Model: {provider.data.model}. This uses a little of its quota.</span>}
            </div>
            {askError && (
              <Alert tone="bad" title="It could not be started">
                {askError}
              </Alert>
            )}

            {runError && (
              <Alert tone="warn" title="Lost contact with the API while waiting for this run">
                <p>{runError.message}</p>
                <p className="mt-1">The run itself carries on. Reload this page to look at it again.</p>
              </Alert>
            )}
            {run?.status === "working" && (
              <p role="status" className="flex items-center gap-2 text-sm text-muted">
                <Spinner /> Asking the model for ideas. This takes a few seconds to a minute.
              </p>
            )}
            {run?.status === "failed" && (
              <Alert tone="bad" title="No ideas this time">
                <p>{run.error}</p>
                {run.retryable && (
                  <div className="mt-2">
                    <Button onClick={() => void retry()}>Try again</Button>
                  </div>
                )}
              </Alert>
            )}

            {run?.status === "done" && run.result && (
              <div className="space-y-5">
                <p className="text-sm text-muted">
                  These ideas were made for <strong className="text-text">{run.repo}</strong>
                  {run.focus ? ` (only ${run.focus})` : ""}. A build from one uses that folder and the places the idea cited, whatever the box above says.
                </p>
                {buildError && (
                  <Alert tone="bad" title="The build could not be started">
                    {buildError}
                  </Alert>
                )}
                {run.result.suggestions.length === 0 && (
                  <Empty title="No idea survived">Every suggestion the model made cited something that is not in the graph, so none was kept. Asking again may help.</Empty>
                )}
                {groups.buildable.length > 0 && (
                  <div className="space-y-3">
                    <h3 className="font-semibold">Skills and automations you can build from this</h3>
                    {groups.buildable.map((idea) => {
                      const index = run.result!.suggestions.indexOf(idea); // its position in the run: the server finds the idea by it
                      const key = ideaKey(run.id, index);
                      const text = edits[key] ?? idea.skill_requirement;
                      return (
                        <IdeaCard
                          key={key}
                          idea={idea}
                          requirement={text}
                          onRequirement={(t) => setEdits((e) => ({ ...e, [key]: t }))}
                          canStart={canBuild({ ...idea, skill_requirement: text }) && building === null}
                          why="It needs a requirement of at least a sentence and at least one place it cites, so it cannot start a build."
                          busy={building === index}
                          onBuild={() => void build(idea, index)}
                        />
                      );
                    })}
                  </div>
                )}
                {groups.other.length > 0 && (
                  <div className="space-y-3">
                    <h3 className="font-semibold">Suggestions for the code itself</h3>
                    <p className="-mt-2 text-sm text-muted">These are for you to act on; they do not become skills.</p>
                    {groups.other.map((idea) => (
                      <IdeaCard key={idea.title} idea={idea} canStart={false} busy={false} onBuild={() => undefined} />
                    ))}
                  </div>
                )}
                {run.result.dropped.length > 0 && (
                  <p className="text-sm text-muted">
                    {plural(run.result.dropped.length, "other suggestion")} {run.result.dropped.length === 1 ? "was" : "were"} dropped because{" "}
                    {run.result.dropped.length === 1 ? "it" : "they"} cited nothing that exists in the graph (or repeated another idea).
                  </p>
                )}
                {run.result.notes.map((n) => (
                  <p key={n} className="text-xs text-muted">
                    {n}
                  </p>
                ))}
              </div>
            )}
          </section>
        )}

        {runs.data && runs.data.length > 0 && (
          <section>
            <h2 className="mb-2 font-semibold">Earlier runs</h2>
            <Card>
              <ul className="divide-y divide-border">
                {runs.data.slice(0, 6).map((r) => {
                  const s = runInfo(r.status);
                  return (
                    <li key={r.id}>
                      <button type="button" onClick={() => setRunId(r.id)} className="flex w-full flex-wrap items-center gap-x-3 gap-y-1 px-4 py-2.5 text-left hover:bg-surface-2">
                        <span className="min-w-0 flex-1 truncate font-medium">{r.repo}</span>
                        <Badge tone={s.tone}>{s.label}</Badge>
                        {r.status === "done" && <span className="text-sm text-muted">{plural(r.ideas, "idea")}</span>}
                        <span className="text-sm text-muted">{relativeTime(r.updated_at)}</span>
                      </button>
                    </li>
                  );
                })}
              </ul>
            </Card>
          </section>
        )}
      </div>
    </>
  );
}
