"use client";

import { useCallback, useEffect, useState } from "react";
import { api } from "./api";
import type { BuildSession } from "./types";

/**
 * The session, fetched now and then again every second while it is "working" (a background job is running).
 * Every other status is a place where the person acts, so the polling stops there. `refresh` fetches again and, if
 * the session is working, starts polling again. `adopt` shows the answer to an action at once.
 */
export function useBuildSession(id: string) {
  const [session, setSession] = useState<BuildSession | undefined>();
  const [error, setError] = useState<Error | undefined>();
  const [tick, setTick] = useState(0);

  useEffect(() => {
    let alive = true;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const load = async () => {
      try {
        const s = await api.build(id);
        if (!alive) return;
        setSession(s);
        setError(undefined);
        if (s.status === "working") timer = setTimeout(load, 1000);
      } catch (e) {
        if (alive) setError(e instanceof Error ? e : new Error(String(e)));
      }
    };
    void load();
    return () => {
      alive = false;
      if (timer) clearTimeout(timer);
    };
  }, [id, tick]);

  const refresh = useCallback(() => setTick((t) => t + 1), []);
  const adopt = useCallback((s: BuildSession) => {
    setSession(s);
    setTick((t) => t + 1);
  }, []);
  return { session, error, refresh, adopt };
}

/** The current time, updated every second, for "working for 12 s". */
export function useNow(active: boolean): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!active) return;
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, [active]);
  return now;
}
