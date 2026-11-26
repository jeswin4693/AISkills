/**
 * The rules for a person's own model, as the page checks them BEFORE it asks the server (docs/per-person-keys.md). The server checks again
 * (settings/rules.py `check_person_model`); this only tells the person early, and its messages never repeat a key.
 */

export const MODEL_LIMIT = 128; // the width of the usage table's model column, so a usage row can always hold it
export const KEY_LIMIT = 400;

const SAFE = /^[A-Za-z0-9._~:/,@+=%-]+$/; // no space, quote, #, $, backslash, control or invisible character: a key travels in an HTTP header
const QUOTES = ['"', "'", "`"];
const UNSAFE = "Only letters, digits and . _ ~ : / , @ + = % - can be used here.";

export type Problems = { provider?: string; model?: string; key?: string };

/** A pasted key often carries a space or a newline at either end. */
export const cleanKey = (raw: string): string => raw.trim();

export const canSave = (problems: Problems): boolean => Object.keys(problems).length === 0;

/** The key a person saved earlier, as far as the page may rely on it: which provider it is for, and whether the server can still open it. */
export type SavedKey = { provider: string; readable: boolean } | null;

/**
 * What is wrong with these three values, field by field. `providers` is the list the server offers a person (it never includes "custom").
 * `saved`: with a saved key that can still be opened and the same provider, an empty key box is fine (the server keeps the key); with another provider it is not.
 */
export function problemsWith(provider: string, model: string, key: string, providers: readonly string[], saved: SavedKey = null): Problems {
  const found: Problems = {};

  const name = provider.trim().toLowerCase();
  if (!name) found.provider = "Choose a provider.";
  else if (name === "custom") {
    found.provider = `The 'custom' provider sends the server to an address you type, so it is not offered here. Choose one of: ${providers.join(", ")}.`;
  } else if (!providers.includes(name)) found.provider = `That is not a provider this app supports. Use one of: ${providers.join(", ")}.`;

  const named = model.trim();
  if (!named) found.model = "Give the model name your key can use.";
  else if (named.length > MODEL_LIMIT) found.model = `That is too long (the limit is ${MODEL_LIMIT} characters).`;
  else if (!SAFE.test(named)) found.model = UNSAFE;

  const secret = cleanKey(key);
  if (!secret) {
    if (saved && saved.readable) {
      if (saved.provider !== name) found.key = `Paste your key for the new provider: the saved key is for ${saved.provider}.`;
    } else found.key = "Paste your key.";
  } else if (QUOTES.includes(secret[0]) || QUOTES.includes(secret[secret.length - 1])) found.key = "Remove the quotes around the key: paste only the key itself.";
  else if (/^bearer([\s:]|$)/i.test(secret)) found.key = "Paste only the key, without the word Bearer in front of it.";
  else if (secret.length > KEY_LIMIT) found.key = `That is too long (the limit is ${KEY_LIMIT} characters).`;
  else if (!SAFE.test(secret)) found.key = UNSAFE;

  return found;
}

/** The sentence about the server's shared model: how many calls a person has left today, or that none are. Empty when nothing is shared. */
export function allowanceText(allowance: { limit: number; used: number } | null): string {
  if (!allowance) return "";
  const { limit, used } = allowance;
  if (used >= limit) return `You have used all ${limit} of today's calls on this server's model (it resets at midnight UTC). Add your own key to go on.`;
  if (used === 0) return `You may make up to ${limit} model calls a day on this server's model; none used so far today.`;
  return `${used} of ${limit} model calls used today on this server's model (it resets at midnight UTC).`;
}
