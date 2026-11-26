import type { AuthStatus, Person } from "./types";

/** Sent on `window` when any call is answered 401: the sign-in ended, so the app should ask again. */
export const SIGNED_OUT_EVENT = "skillforge:signed-out";

/**
 * The status after a session ends (or any 401). What the server said about Google is KEPT: if it were dropped, the login screen
 * would lose its Google button the moment a session expired.
 */
export function signedOutStatus(previous: AuthStatus | undefined): AuthStatus {
  return { required: true, authenticated: false, google_client_id: previous?.google_client_id ?? "", owner_login: previous?.owner_login ?? true, user: null };
}

/** The status after signing in. `user` is the person who used Google, or null for the owner (the access token). */
export function signedInStatus(previous: AuthStatus | undefined, user: Person | null): AuthStatus {
  return { required: true, authenticated: true, google_client_id: previous?.google_client_id ?? "", owner_login: previous?.owner_login ?? true, user };
}

const LABEL_MAX = 40;

/** How a signed-in person is shown in the menu: their name, or their email when Google gave no name, kept short. */
export function personLabel(user: Person | null | undefined): string {
  if (!user) return "";
  const text = user.name.trim() || user.email.trim();
  return text.length > LABEL_MAX ? text.slice(0, LABEL_MAX - 1) + "…" : text;
}

export type AuthPhase = "checking" | "open" | "login";

/**
 * What the app shows. The local version never asks (`required` is false). The hosted version asks until the person has signed in.
 * Until the status is known the app waits, so no page fires a call that would only be refused.
 */
export function authPhase(status: AuthStatus | undefined): AuthPhase {
  if (!status) return "checking";
  return status.required && !status.authenticated ? "login" : "open";
}
