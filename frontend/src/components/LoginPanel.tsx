"use client";

import { useCallback, useEffect, useMemo, useRef, useState, type FormEvent } from "react";
import { api } from "@/lib/api";
import { createGoogleLoader, startGoogleSignIn, type GoogleApi } from "@/lib/google";
import { useAuth } from "@/lib/useAuth";
import { Alert, Button, Card } from "./ui";

/**
 * The hosted version's sign-in. When the server offers "Sign in with Google" that is the main way in; the access token (the owner's key,
 * set when the server was deployed) is always there too, under "Owner". Fits a phone.
 */
export function LoginPanel() {
  const { signIn, signInWithGoogle, googleClientId } = useAuth();
  const [token, setToken] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | undefined>();
  const [googleError, setGoogleError] = useState<string | undefined>();
  const button = useRef<HTMLDivElement>(null);
  const credentialHandler = useRef<(credential: string) => void>(() => {});
  const loader = useMemo(() => createGoogleLoader(document, window as unknown as { google?: GoogleApi }), []);

  // A fresh nonce and a fresh button each time: at the start, and again after any refused attempt (the server's cookie for the nonce is per attempt).
  const setUpGoogle = useCallback(async () => {
    if (!googleClientId || !button.current) return;
    try {
      const [{ nonce }, google] = await Promise.all([api.authNonce(), loader()]);
      const target = button.current;
      if (!target) return;
      target.replaceChildren();
      startGoogleSignIn(google, { clientId: googleClientId, nonce, button: target, width: target.clientWidth, onCredential: (c) => credentialHandler.current(c) });
      setGoogleError(undefined);
    } catch (err) {
      setGoogleError(err instanceof Error ? err.message : "Could not set up Google sign-in.");
    }
  }, [googleClientId, loader]);

  useEffect(() => {
    credentialHandler.current = (credential: string) => {
      setBusy(true);
      setError(undefined);
      signInWithGoogle(credential).catch((err: unknown) => {
        setError(err instanceof Error ? err.message : "Could not sign in.");
        setBusy(false);
        void setUpGoogle();
      });
    };
  }, [signInWithGoogle, setUpGoogle]);

  useEffect(() => {
    void setUpGoogle();
  }, [setUpGoogle]);

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!token.trim()) return;
    setBusy(true);
    setError(undefined);
    try {
      await signIn(token.trim());
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not sign in.");
      setBusy(false);
    }
  }

  const tokenForm = (
    <form onSubmit={(e) => void submit(e)} className="mt-3 space-y-3">
      <label className="block text-sm font-medium" htmlFor="access-token">
        Access token
      </label>
      <input
        id="access-token"
        type="password"
        autoComplete="current-password"
        autoFocus={!googleClientId}
        value={token}
        onChange={(e) => setToken(e.target.value)}
        className="w-full rounded-md border border-border bg-surface px-3 py-2 text-base"
      />
      <Button type="submit" variant="primary" busy={busy} disabled={!token.trim()} className="w-full justify-center">
        Sign in
      </Button>
    </form>
  );

  return (
    <div className="mx-auto max-w-md pt-8">
      <Card className="p-5">
        <h1 className="text-xl font-semibold">Sign in</h1>
        {googleClientId ? (
          <>
            <p className="mt-1 text-sm text-muted">Sign in with your Google account. Only the people the owner of this server has allowed can get in.</p>
            <div ref={button} aria-label="Sign in with Google" className="mt-4 flex min-h-11 justify-center" />
            {googleError && (
              <div className="mt-3">
                <Alert tone="bad" title="Google sign-in is not available">
                  {googleError}
                </Alert>
              </div>
            )}
            {error && (
              <div className="mt-3">
                <Alert tone="bad" title="Not signed in">
                  {error}
                </Alert>
              </div>
            )}
            <details className="mt-5 text-sm" open={Boolean(googleError)}>
              <summary className="cursor-pointer text-muted">Owner of this server? Use the access token</summary>
              {tokenForm}
            </details>
          </>
        ) : (
          <>
            <p className="mt-1 text-sm text-muted">This copy of SkillForge AI is private. Enter the access token that was set when it was deployed.</p>
            {tokenForm}
            {error && (
              <div className="mt-3">
                <Alert tone="bad" title="Not signed in">
                  {error}
                </Alert>
              </div>
            )}
          </>
        )}
      </Card>
    </div>
  );
}
