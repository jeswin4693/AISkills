"use client";

import { useCallback, useEffect, useRef, useState } from "react";

/** Something changed that the status panel shows (for example the model was just set up): it should look again now. */
export const STATUS_EVENT = "skillforge:status-changed";

export function notifyStatusChanged(): void {
  if (typeof window !== "undefined") window.dispatchEvent(new Event(STATUS_EVENT));
}

export interface AsyncState<T> {
  data?: T;
  error?: Error;
  loading: boolean;
  reload: () => void;
}

/** Run an async function when `key` changes, and again on reload(). A slow answer to an old request is dropped. */
export function useAsync<T>(fn: () => Promise<T>, key: string): AsyncState<T> {
  const [state, setState] = useState<{ data?: T; error?: Error; loading: boolean }>({ loading: true });
  const [tick, setTick] = useState(0);
  const latest = useRef(fn);
  latest.current = fn;

  useEffect(() => {
    let current = true;
    setState((s) => ({ data: s.data, loading: true }));
    latest.current().then(
      (data) => current && setState({ data, loading: false }),
      (error: unknown) => current && setState({ error: error instanceof Error ? error : new Error(String(error)), loading: false }),
    );
    return () => {
      current = false;
    };
  }, [key, tick]);

  const reload = useCallback(() => setTick((t) => t + 1), []);
  return { ...state, reload };
}
