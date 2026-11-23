"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "./api";
import type { SuggestRun } from "./types";

/**
 * A suggestion run, fetched now and again every 1.5 seconds while the model is being asked. A run that is done or failed is a place
 * where the person acts, so the polling stops. `adopt` shows the answer to an action (starting or retrying) at once.
 */
export function useSuggestRun(id: string | null) {
  const [run, setRun] = useState<SuggestRun | undefined>();
  const [error, setError] = useState<Error | undefined>();
  const [tick, setTick] = useState(0);
  const opened = useRef<string | null>(null);

  useEffect(() => {
    if (opened.current !== id) {
      opened.current = id;
      setRun(undefined); // another run is being opened: never keep showing (or retrying) the previous one
      setError(undefined);
    }
    if (!id) return;
    let alive = true;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let misses = 0;
    const load = async () => {
      try {
        const r = await api.suggestRun(id);
        if (!alive) return;
        misses = 0;
        setRun(r);
        setError(undefined);
        if (r.status === "working") timer = setTimeout(load, 1500);
      } catch (e) {
        if (!alive) return;
        setError(e instanceof Error ? e : new Error(String(e)));
        if (++misses < 5) timer = setTimeout(load, 3000); // a hiccup while the model is being asked must not freeze the page
      }
    };
    void load();
    return () => {
      alive = false;
      if (timer) clearTimeout(timer);
    };
  }, [id, tick]);

  const adopt = useCallback((r: SuggestRun) => {
    setRun(r);
    setTick((t) => t + 1);
  }, []);
  return { run, error, adopt };
}
