"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { api } from "./api";
import { SIGNED_OUT_EVENT, authPhase, type AuthPhase } from "./auth";
import type { AuthStatus } from "./types";

interface Auth {
  phase: AuthPhase;
  /** True when this server asks for a sign-in (the hosted version). */
  required: boolean;
  /** True for the hosted version: things that only make sense on your own computer, such as installing into a folder, are hidden. */
  hosted: boolean;
  signIn: (token: string) => Promise<void>;
  signOut: () => Promise<void>;
}

const Ctx = createContext<Auth>({ phase: "open", required: false, hosted: false, signIn: async () => {}, signOut: async () => {} });

export const useAuth = () => useContext(Ctx);

/** Asks the server once whether a sign-in is needed, and listens for it ending. In the local version nothing is ever asked. */
export function AuthProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<AuthStatus | undefined>();
  const [hosted, setHosted] = useState(false);

  useEffect(() => {
    let alive = true;
    // If the API cannot be reached at all, show the pages: each says "cannot reach the API" in its own words.
    api.authStatus().then((s) => alive && setStatus(s)).catch(() => alive && setStatus({ required: false, authenticated: true }));
    api.health().then((h) => alive && setHosted(h.mode === "hosted")).catch(() => {});
    const signedOut = () => setStatus({ required: true, authenticated: false });
    window.addEventListener(SIGNED_OUT_EVENT, signedOut);
    return () => {
      alive = false;
      window.removeEventListener(SIGNED_OUT_EVENT, signedOut);
    };
  }, []);

  const signIn = useCallback(async (token: string) => {
    await api.login(token);
    setStatus({ required: true, authenticated: true });
  }, []);
  const signOut = useCallback(async () => {
    await api.logout();
    setStatus({ required: true, authenticated: false });
  }, []);

  const value = useMemo<Auth>(
    () => ({ phase: authPhase(status), required: status?.required ?? false, hosted, signIn, signOut }),
    [status, hosted, signIn, signOut],
  );
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}
