"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import type { ReactNode } from "react";
import { StatusPanel } from "./StatusPanel";

const NAV = [{ href: "/library", label: "Library", hint: "Your skills and their versions" }];

export function AppShell({ children }: { children: ReactNode }) {
  const path = usePathname();
  return (
    <div className="min-h-dvh md:grid md:grid-cols-[15rem_1fr]">
      <aside className="border-b border-border bg-surface md:sticky md:top-0 md:h-dvh md:overflow-y-auto md:border-r md:border-b-0">
        <div className="flex flex-col gap-4 p-4 md:h-full">
          <Link href="/library" className="flex items-center gap-2 font-semibold tracking-tight">
            <span aria-hidden className="grid size-7 place-items-center rounded-md bg-accent text-sm text-accent-fg">
              S
            </span>
            SkillForge AI
          </Link>
          <nav aria-label="Main">
            <ul className="flex gap-1 md:flex-col">
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
              <li>
                <span className="flex items-center justify-between gap-2 rounded-md px-3 py-1.5 text-sm text-muted" title="The builder chat comes in the next step">
                  Builder <span className="rounded-full bg-surface-2 px-2 py-0.5 text-xs">soon</span>
                </span>
              </li>
            </ul>
          </nav>
          <div className="md:mt-auto">
            <StatusPanel />
          </div>
        </div>
      </aside>
      <main className="min-w-0 px-4 py-6 md:px-10 md:py-8">
        <div className="mx-auto max-w-5xl">{children}</div>
      </main>
    </div>
  );
}
