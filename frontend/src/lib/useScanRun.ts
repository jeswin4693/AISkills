"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "./api";
import { pollAfterAnswer, pollAfterMiss } from "./testing";
import type { ScanRun } from "./types";

/**
 * A behaviour scan, fetched now and again every 1.5 seconds while the model is being asked. A scan that is done or failed is a place where the person acts, so the polling
 * stops. `adopt` shows the answer to an action (starting or retrying) at once. After five missed answers in a row it stops and says `stalled`, so the page can tell the
 * person it lost touch with the server (the scan may well still be going) and `check` asks again. The same shape as `useEvalRun`.
 */
export function useScanRun(id: string | null) {
  const [run, setRun] = useState<ScanRun | undefined>();
  const [error, setError] = useState<Error | undefined>();
  const [stalled, setStalled] = useState(false);
  const [tick, setTick] = useState(0);
  const opened = useRef<string | null>(null);

  useEffect(() => {
    if (opened.current !== id) {
      opened.current = id;
      setRun(undefined); // another scan is being opened: never keep showing (or retrying) the previous one
      setError(undefined);
    }
    setStalled(false);
    if (!id) return;
    let alive = true;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let misses = 0;
    const load = async () => {
      try {
        const r = await api.scanRun(id);
        if (!alive) return;
        misses = 0;
        setRun(r);
        setError(undefined);
        const delay = pollAfterAnswer(r.status);
        if (delay !== null) timer = setTimeout(load, delay);
      } catch (e) {
        if (!alive) return;
        setError(e instanceof Error ? e : new Error(String(e)));
        const next = pollAfterMiss(++misses);
        setStalled(next.stalled);
        if (next.delay !== null) timer = setTimeout(load, next.delay); // a hiccup while the model is being asked must not freeze the page
      }
    };
    void load();
    return () => {
      alive = false;
      if (timer) clearTimeout(timer);
    };
  }, [id, tick]);

  const adopt = useCallback((r: ScanRun) => {
    setRun(r);
    setTick((t) => t + 1);
  }, []);
  const check = useCallback(() => setTick((t) => t + 1), []);
  return { run, error, adopt, stalled, check };
}
