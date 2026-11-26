"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { api } from "./api";
import { SIGNED_OUT_EVENT, authPhase, signedInStatus, signedOutStatus, type AuthPhase } from "./auth";
import type { AuthStatus, Person } from "./types";

interface Auth {
  phase: AuthPhase;
  /** True when this server asks for a sign-in (the hosted version). */
  required: boolean;
  /** True for the hosted version: things that only make sense on your own computer, such as installing into a folder, are hidden. */
  hosted: boolean;
  /** The person who signed in with Google, or null (nobody, or the owner who used the access token). */
  user: Person | null;
  /** True when the owner has turned this person's account off (the sign-in screen says so). */
  blocked: boolean;
  /** The PUBLIC Google client id when this server offers "Sign in with Google"; "" when it does not. */
  googleClientId: string;
  signIn: (token: string) => Promise<void>;
  signInWithGoogle: (credential: string) => Promise<void>;
  signOut: () => Promise<void>;
}

const Ctx = createContext<Auth>({
  phase: "open", required: false, hosted: false, user: null, blocked: false, googleClientId: "",
  signIn: async () => {}, signInWithGoogle: async () => {}, signOut: async () => {},
});

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
    const signedOut = () => setStatus((s) => signedOutStatus(s)); // keeps what the server said about Google, so the login screen keeps its button
    window.addEventListener(SIGNED_OUT_EVENT, signedOut);
    return () => {
      alive = false;
      window.removeEventListener(SIGNED_OUT_EVENT, signedOut);
    };
  }, []);

  const signIn = useCallback(async (token: string) => {
    await api.login(token);
    setStatus((s) => signedInStatus(s, null));
  }, []);
  const signInWithGoogle = useCallback(async (credential: string) => {
    const answer = await api.googleLogin(credential);
    setStatus((s) => signedInStatus(s, answer.user));
  }, []);
  const signOut = useCallback(async () => {
    await api.logout();
    setStatus((s) => signedOutStatus(s));
  }, []);

  const value = useMemo<Auth>(
    () => ({
      phase: authPhase(status), required: status?.required ?? false, hosted, user: status?.user ?? null, blocked: status?.blocked === true,
      googleClientId: status?.google_client_id ?? "", signIn, signInWithGoogle, signOut,
    }),
    [status, hosted, signIn, signInWithGoogle, signOut],
  );
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}
