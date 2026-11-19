"use client";

import { useState, type FormEvent } from "react";
import { useAuth } from "@/lib/useAuth";
import { Alert, Button, Card } from "./ui";

/** The hosted version's sign-in: one field for the access token the owner set on the host. Fits a phone. */
export function LoginPanel() {
  const { signIn } = useAuth();
  const [token, setToken] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | undefined>();

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

  return (
    <div className="mx-auto max-w-md pt-8">
      <Card className="p-5">
        <h1 className="text-xl font-semibold">Sign in</h1>
        <p className="mt-1 text-sm text-muted">This copy of SkillForge AI is private. Enter the access token that was set when it was deployed.</p>
        <form onSubmit={(e) => void submit(e)} className="mt-4 space-y-3">
          <label className="block text-sm font-medium" htmlFor="access-token">
            Access token
          </label>
          <input
            id="access-token"
            type="password"
            autoComplete="current-password"
            autoFocus
            value={token}
            onChange={(e) => setToken(e.target.value)}
            className="w-full rounded-md border border-border bg-surface px-3 py-2 text-base"
          />
          {error && (
            <Alert tone="bad" title="Not signed in">
              {error}
            </Alert>
          )}
          <Button type="submit" variant="primary" busy={busy} disabled={!token.trim()} className="w-full justify-center">
            Sign in
          </Button>
        </form>
      </Card>
    </div>
  );
}
