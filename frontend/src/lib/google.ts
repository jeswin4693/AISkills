/**
 * "Sign in with Google", on the page.
 *
 * Google's own script draws the button. When someone picks their account it hands THIS page a signed ticket (an ID token); the page posts it to
 * our server, which checks it against Google's public keys. The page never decides who anybody is, and there is no secret here: the client id is
 * public by design. Everything that touches the browser is passed in, so this is plain logic that tests can drive.
 */

export const GOOGLE_SCRIPT = "https://accounts.google.com/gsi/client";

export interface GoogleInit {
  client_id: string;
  nonce: string;
  auto_select: boolean;
  cancel_on_tap_outside: boolean;
  callback: (response: unknown) => void;
}

export interface GoogleApi {
  accounts: { id: { initialize: (config: GoogleInit) => void; renderButton: (element: HTMLElement, options: Record<string, unknown>) => void } };
}

const BUTTON_MIN = 200;
const BUTTON_MAX = 400;
const BUTTON_DEFAULT = 300;

/** A width Google's button accepts, from the room there is (a phone is narrow). */
export function buttonWidth(available: number | undefined): number {
  if (available === undefined || !Number.isFinite(available)) return BUTTON_DEFAULT;
  return Math.min(BUTTON_MAX, Math.max(BUTTON_MIN, Math.round(available)));
}

export interface StartOptions {
  clientId: string;
  /** From our server, for this one attempt: the ticket Google returns carries it, and only this browser's cookie matches it. */
  nonce: string;
  button: HTMLElement;
  onCredential: (credential: string) => void;
  width?: number;
}

/** Hand Google the client id and the nonce and draw its button. Google calls `onCredential` with the signed ticket; a reply without one is ignored. */
export function startGoogleSignIn(google: GoogleApi, options: StartOptions): void {
  google.accounts.id.initialize({
    client_id: options.clientId,
    nonce: options.nonce,
    auto_select: false, // never sign anyone in without a click
    cancel_on_tap_outside: true,
    callback: (response) => {
      const credential = (response as { credential?: unknown } | undefined)?.credential;
      if (typeof credential === "string" && credential) options.onCredential(credential);
    },
  });
  google.accounts.id.renderButton(options.button, {
    type: "standard", theme: "outline", size: "large", text: "signin_with", shape: "pill", logo_alignment: "left", width: buttonWidth(options.width),
  });
}

const FAILED = "Could not load Google sign-in. Check your connection (or an ad blocker), reload the page, or use the access token below.";

/**
 * A loader that adds Google's script once and resolves with its API. Asked again it gives the same answer without a second script; a failure
 * is not remembered, so trying again works. It gives up after `timeoutMs`, and does not believe a script that loaded without bringing Google's code.
 */
export function createGoogleLoader(
  doc: Pick<Document, "head" | "createElement">, win: { google?: GoogleApi }, timeoutMs = 10_000,
): () => Promise<GoogleApi> {
  let pending: Promise<GoogleApi> | undefined;
  return () => {
    if (win.google?.accounts?.id) return Promise.resolve(win.google);
    if (pending) return pending;
    pending = new Promise<GoogleApi>((resolve, reject) => {
      const script = doc.createElement("script");
      const timer = setTimeout(() => fail(), timeoutMs);
      function fail() {
        clearTimeout(timer);
        pending = undefined;
        reject(new Error(FAILED));
      }
      script.src = GOOGLE_SCRIPT;
      script.async = true;
      script.defer = true;
      script.onload = () => {
        clearTimeout(timer);
        if (win.google?.accounts?.id) resolve(win.google);
        else fail();
      };
      script.onerror = () => fail();
      doc.head.appendChild(script);
    });
    return pending;
  };
}
