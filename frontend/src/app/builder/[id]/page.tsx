"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useState } from "react";
import { FailedCard } from "@/components/builder/FailedCard";
import { ProgressStrip } from "@/components/builder/ProgressStrip";
import { QuestionsCard } from "@/components/builder/QuestionsCard";
import { RequirementCard } from "@/components/builder/RequirementCard";
import { ResultCard } from "@/components/builder/ResultCard";
import { WorkingCard } from "@/components/builder/WorkingCard";
import { Alert, Badge, Button, Card, ErrorBox, Loading, Modal, PageHeader } from "@/components/ui";
import { api } from "@/lib/api";
import { kindNoun, statusInfo, withArticle } from "@/lib/builder";
import { formatWhen } from "@/lib/format";
import { useBuildSession } from "@/lib/useBuildSession";
import { useKinds } from "@/lib/useKinds";

export default function SessionPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const { session, error, refresh, adopt } = useBuildSession(id);
  const kinds = useKinds();
  const [confirmDiscard, setConfirmDiscard] = useState(false);
  const [discarding, setDiscarding] = useState(false);
  const [discardError, setDiscardError] = useState<string | null>(null);

  if (error && !session) {
    return (
      <>
        <PageHeader title="Builder session" />
        <ErrorBox error={error} onRetry={refresh} />
        <p className="mt-4 text-sm">
          <Link href="/builder" className="text-accent underline">
            Back to the builder
          </Link>
        </p>
      </>
    );
  }
  if (!session) return <Loading what="the session" />;
  const noun = kindNoun(kinds.data, session.kind);

  // A draft is built, but it is not "Built" in the green sense: say so at the top, where the eye goes first.
  const info = session.status === "done" && session.result?.status === "draft" ? { label: "Built as a DRAFT", tone: "warn" as const } : statusInfo(session.status);

  async function discard() {
    setDiscarding(true);
    setDiscardError(null);
    try {
      await api.discardBuild(id);
      router.push("/builder");
    } catch (e) {
      setDiscardError(e instanceof Error ? e.message : String(e));
      setDiscarding(false);
    }
  }

  return (
    <>
      <p className="mb-2 text-sm">
        <Link href="/builder" className="text-accent underline">
          Builder
        </Link>{" "}
        / {session.result?.name ?? `a new ${noun}`}
      </p>
      <PageHeader title={session.result?.name ?? `Building ${withArticle(noun)}`} actions={<Badge tone={info.tone}>{info.label}</Badge>} />
      <ProgressStrip session={session} />

      <div className="space-y-5">
        <Card className="p-4">
          <p className="text-xs font-medium tracking-wide text-muted uppercase">You asked for</p>
          <blockquote className="mt-1 border-l-2 border-border pl-3 break-words whitespace-pre-line">{session.description}</blockquote>
          {session.seed && (
            <p className="mt-2 text-sm text-muted">
              Started from an idea about <strong className="text-text">{session.seed.repo}</strong>
              {session.seed.focus ? ` (only ${session.seed.focus})` : ""}. The {noun} will record the {session.seed.places} place{session.seed.places === 1 ? "" : "s"} the idea cited as
              evidence, so you can recheck it when the code changes.
            </p>
          )}
        </Card>

        {error && (
          <Alert tone="warn" title="Lost contact with the API">
            <p>{error.message}</p>
            <div className="mt-2">
              <Button onClick={refresh}>Try again</Button>
            </div>
          </Alert>
        )}

        {session.status === "working" && <WorkingCard session={session} />}
        {session.status === "awaiting_answers" && <QuestionsCard key={session.round} session={session} onSession={adopt} />}
        {session.status === "awaiting_approval" && <RequirementCard session={session} onSession={adopt} />}
        {session.status === "failed" && <FailedCard session={session} onSession={adopt} />}
        {session.status === "done" && session.result && <ResultCard session={session} onSession={adopt} />}
      </div>

      <footer className="mt-8 flex flex-wrap items-center justify-between gap-3 border-t border-border pt-4 text-sm text-muted">
        <span>
          Started {formatWhen(session.created_at)} · {session.model_calls} model call{session.model_calls === 1 ? "" : "s"} · round {session.round}
        </span>
        <Button variant="ghost" disabled={session.status === "working"} onClick={() => setConfirmDiscard(true)}>
          Discard this session…
        </Button>
      </footer>

      <Modal open={confirmDiscard} onClose={() => setConfirmDiscard(false)} title="Discard this session?">
        <p className="text-sm">
          The conversation and the files built here are removed. {session.saved ? `The skill you saved to the library (${session.saved.name} ${session.saved.version}) is not affected.` : "Nothing has been saved to the library from it."}
        </p>
        {discardError && (
          <div className="mt-3">
            <Alert tone="bad" title="It could not be discarded">
              {discardError}
            </Alert>
          </div>
        )}
        <div className="mt-4 flex justify-end gap-2">
          <Button onClick={() => setConfirmDiscard(false)}>Cancel</Button>
          <Button variant="danger" busy={discarding} onClick={() => void discard()}>
            Discard
          </Button>
        </div>
      </Modal>
    </>
  );
}
