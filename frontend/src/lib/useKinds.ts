"use client";

import { api } from "./api";
import type { KindInfo } from "./types";
import { useAsync, type AsyncState } from "./useAsync";

/** The kinds of thing the app builds, from the server. Until they arrive (or if the server cannot say) callers fall back to the skill. */
export function useKinds(): AsyncState<KindInfo[]> {
  return useAsync(api.kinds, "kinds");
}
