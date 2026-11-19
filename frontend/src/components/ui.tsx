"use client";

import Link from "next/link";
import { useEffect, useId, useRef, type ButtonHTMLAttributes, type ReactNode } from "react";
import { ApiError } from "@/lib/api";

type Tone = "neutral" | "ok" | "warn" | "bad" | "info";

const TONE: Record<Tone, string> = {
  neutral: "bg-surface-2 text-muted",
  ok: "bg-ok-bg text-ok",
  warn: "bg-warn-bg text-warn",
  bad: "bg-bad-bg text-bad",
  info: "bg-info-bg text-info",
};

export function Badge({ tone = "neutral", children, title }: { tone?: Tone; children: ReactNode; title?: string }) {
  return (
    <span title={title} className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium whitespace-nowrap ${TONE[tone]}`}>
      {children}
    </span>
  );
}

type Variant = "primary" | "secondary" | "danger" | "ghost";
const VARIANT: Record<Variant, string> = {
  primary: "bg-accent text-accent-fg hover:opacity-90",
  secondary: "border border-border bg-surface hover:bg-surface-2",
  danger: "border border-bad/40 bg-bad-bg text-bad hover:opacity-90",
  ghost: "hover:bg-surface-2",
};
const BUTTON = "inline-flex items-center justify-center gap-2 rounded-md px-3 py-1.5 text-sm font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-50";

export function Button({
  variant = "secondary", busy = false, children, className = "", ...rest
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant; busy?: boolean }) {
  return (
    <button type="button" {...rest} disabled={rest.disabled || busy} aria-busy={busy || undefined} className={`${BUTTON} ${VARIANT[variant]} ${className}`}>
      {busy && <Spinner />}
      {children}
    </button>
  );
}

export function ButtonLink({ href, variant = "secondary", children }: { href: string; variant?: Variant; children: ReactNode }) {
  return (
    <Link href={href} className={`${BUTTON} ${VARIANT[variant]}`}>
      {children}
    </Link>
  );
}

export function Spinner() {
  return <span aria-hidden className="inline-block size-3.5 animate-spin rounded-full border-2 border-current border-t-transparent" />;
}

const ALERT: Record<Exclude<Tone, "neutral">, string> = {
  ok: "border-ok/30 bg-ok-bg text-ok",
  warn: "border-warn/30 bg-warn-bg text-warn",
  bad: "border-bad/30 bg-bad-bg text-bad",
  info: "border-info/30 bg-info-bg text-info",
};

/** A message that is announced to screen readers. Colour is never the only signal: the title says what it is. */
export function Alert({ tone, title, children, onDismiss }: { tone: Exclude<Tone, "neutral">; title: string; children?: ReactNode; onDismiss?: () => void }) {
  return (
    <div role={tone === "bad" ? "alert" : "status"} className={`rounded-lg border p-3 text-sm ${ALERT[tone]}`}>
      <div className="flex items-start justify-between gap-3">
        <p className="font-semibold">{title}</p>
        {onDismiss && (
          <button type="button" onClick={onDismiss} aria-label="Dismiss" className="-mr-1 rounded px-1.5 leading-none hover:bg-black/10">
            ×
          </button>
        )}
      </div>
      {children && <div className="mt-1 text-text">{children}</div>}
    </div>
  );
}

export function ErrorBox({ error, onRetry }: { error: Error; onRetry?: () => void }) {
  const unreachable = error instanceof ApiError && error.status === 0;
  return (
    <Alert tone="bad" title={unreachable ? "The API is not running" : "Something went wrong"}>
      <p>{error.message}</p>
      {onRetry && (
        <div className="mt-2">
          <Button onClick={onRetry}>Try again</Button>
        </div>
      )}
    </Alert>
  );
}

export function PageHeader({ title, subtitle, actions }: { title: ReactNode; subtitle?: ReactNode; actions?: ReactNode }) {
  return (
    <header className="mb-6 flex flex-wrap items-start justify-between gap-3">
      <div className="min-w-0">
        <h1 className="text-2xl font-semibold tracking-tight break-words">{title}</h1>
        {subtitle && <p className="mt-1 max-w-prose text-sm text-muted">{subtitle}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </header>
  );
}

export function Card({ children, className = "" }: { children: ReactNode; className?: string }) {
  return <section className={`rounded-xl border border-border bg-surface ${className}`}>{children}</section>;
}

/** A native <dialog>: the browser gives it a focus trap, Escape to close and a backdrop. Content mounts only while open. */
export function Modal({ open, onClose, title, children }: { open: boolean; onClose: () => void; title: string; children: ReactNode }) {
  const ref = useRef<HTMLDialogElement>(null);
  const titleId = useId();
  useEffect(() => {
    const d = ref.current;
    if (!d) return;
    if (open && !d.open) d.showModal();
    if (!open && d.open) d.close();
  }, [open]);
  return (
    <dialog
      ref={ref}
      aria-labelledby={titleId}
      onClose={onClose}
      onClick={(e) => {
        if (e.target === ref.current) onClose(); // a click on the backdrop
      }}
      className="m-auto w-[min(34rem,calc(100vw-2rem))] rounded-xl border border-border bg-surface p-0 text-text shadow-2xl"
    >
      {open && (
        <div className="p-5">
          <div className="mb-3 flex items-start justify-between gap-3">
            <h2 id={titleId} className="text-lg font-semibold">
              {title}
            </h2>
            <button type="button" onClick={onClose} aria-label="Close" className="-mr-1 rounded px-2 text-xl leading-none text-muted hover:bg-surface-2">
              ×
            </button>
          </div>
          {children}
        </div>
      )}
    </dialog>
  );
}

export function Empty({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="rounded-xl border border-dashed border-border px-6 py-10 text-center">
      <p className="font-medium">{title}</p>
      {children && <div className="mx-auto mt-1 max-w-md text-sm text-muted">{children}</div>}
    </div>
  );
}

export function Loading({ what }: { what: string }) {
  return (
    <p role="status" className="flex items-center gap-2 py-8 text-sm text-muted">
      <Spinner /> Loading {what}…
    </p>
  );
}
