"use client";
import { useCallback, useEffect, useRef, useState } from "react";

export interface Async<T> {
  data: T | null;
  error: Error | null;
  loading: boolean;
  reload: () => void;
}

interface Result<T> { key: string; tick: number; data: T | null; error: Error | null }

/** Load on key change or reload. Keeps the previous data while reloading so screens do not flash empty. */
export function useAsync<T>(fn: () => Promise<T>, key: string): Async<T> {
  const [res, setRes] = useState<Result<T>>({ key: "", tick: -1, data: null, error: null });
  const [tick, setTick] = useState(0);
  const fnRef = useRef(fn);
  useEffect(() => { fnRef.current = fn; });
  useEffect(() => {
    let live = true;
    fnRef.current().then(
      (data) => { if (live) setRes({ key, tick, data, error: null }); },
      (e: unknown) => { if (live) setRes((r) => ({ key, tick, data: r.data, error: e instanceof Error ? e : new Error(String(e)) })); },
    );
    return () => { live = false; };
  }, [key, tick]);
  const reload = useCallback(() => setTick((t) => t + 1), []);
  return { data: res.data, error: res.error, loading: res.key !== key || res.tick !== tick, reload };
}
