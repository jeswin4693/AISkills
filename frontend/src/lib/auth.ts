import type { AuthStatus } from "./types";

/** Sent on `window` when any call is answered 401: the sign-in ended, so the app should ask again. */
export const SIGNED_OUT_EVENT = "skillforge:signed-out";

export type AuthPhase = "checking" | "open" | "login";

/**
 * What the app shows. The local version never asks (`required` is false). The hosted version asks until the person has signed in.
 * Until the status is known the app waits, so no page fires a call that would only be refused.
 */
export function authPhase(status: AuthStatus | undefined): AuthPhase {
  if (!status) return "checking";
  return status.required && !status.authenticated ? "login" : "open";
}
