"use client";

import { useCallback, useEffect, useRef, useState } from "react";

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
