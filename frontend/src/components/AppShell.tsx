"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import type { ReactNode } from "react";
import { personLabel } from "@/lib/auth";
import { AuthProvider, useAuth } from "@/lib/useAuth";
import { LoginPanel } from "./LoginPanel";
import { StatusPanel } from "./StatusPanel";
import { Loading } from "./ui";

const NAV = [
  { href: "/", label: "Dashboard", hint: "What needs you, and what you have" },
  { href: "/builder", label: "Builder", hint: "Describe what you want and build it" },
  { href: "/repository", label: "Repository", hint: "Read a repository and get ideas grounded in its code" },
  { href: "/library", label: "Library", hint: "Your skills and their versions" },
  { href: "/testing", label: "Testing Lab", hint: "Run a skill's test cases with the skill and without it" },
  { href: "/quality", label: "Quality Report", hint: "What the checks found on a skill, what did not run, and what to do next" },
  { href: "/composer", label: "Plugins", hint: "Combine skills and agents into a plugin" },
  { href: "/settings", label: "Settings", hint: "Choose your model and add its key" },
];

function Shell({ children }: { children: ReactNode }) {
  const path = usePathname();
  const { phase, required, signOut, user } = useAuth();
  const open = phase === "open"; // the pages, the menu and the status panel appear only once no sign-in is needed or it is done
  return (
    <div className="min-h-dvh md:grid md:grid-cols-[15rem_1fr]">
      <aside className="border-b border-border bg-surface md:sticky md:top-0 md:h-dvh md:overflow-y-auto md:border-r md:border-b-0">
        <div className="flex flex-col gap-4 p-4 md:h-full">
          <Link href="/" className="flex items-center gap-2 font-semibold tracking-tight">
            <span aria-hidden className="grid size-7 place-items-center rounded-md bg-accent text-sm text-accent-fg">
              S
            </span>
            SkillForge AI
          </Link>
          {open && (
            <nav aria-label="Main">
              <ul className="flex flex-wrap gap-1 md:flex-col">
                {NAV.map((item) => {
                  const here = path === item.href || path.startsWith(item.href + "/");
                  return (
                    <li key={item.href}>
                      <Link
                        href={item.href}
                        title={item.hint}
                        aria-current={here ? "page" : undefined}
                        className={`block rounded-md px-3 py-1.5 text-sm font-medium ${here ? "bg-accent-soft text-accent" : "text-text hover:bg-surface-2"}`}
                      >
                        {item.label}
                      </Link>
                    </li>
                  );
                })}
              </ul>
            </nav>
          )}
          {open && (
            <div className="space-y-2 md:mt-auto">
              <StatusPanel />
              {required && user && (
                <p className="truncate px-3 text-xs text-muted" title={user.email}>
                  Signed in as {personLabel(user)}
                </p>
              )}
              {required && (
                <button type="button" onClick={() => void signOut()} className="w-full rounded-md px-3 py-1.5 text-left text-sm text-muted hover:bg-surface-2">
                  Sign out
                </button>
              )}
            </div>
          )}
        </div>
      </aside>
      <main className="min-w-0 px-4 py-6 md:px-10 md:py-8">
        <div className="mx-auto max-w-5xl">{phase === "checking" ? <Loading what="the app" /> : phase === "login" ? <LoginPanel /> : children}</div>
      </main>
    </div>
  );
}

export function AppShell({ children }: { children: ReactNode }) {
  return (
    <AuthProvider>
      <Shell>{children}</Shell>
    </AuthProvider>
  );
}
