"use client";

import { createContext, useContext, useEffect, useState } from "react";
import { fetchJson } from "@/lib/api";

export const DEFAULT_REFRESH_MS = 60_000;

/** The APR poll interval (`ui.dashboard.refresh_seconds`), provided once by the app shell. */
export const RefreshContext = createContext<number>(DEFAULT_REFRESH_MS);

/**
 * Poll a read-only API route at the dashboard-wide APR interval unless the caller passes one.
 * The last good payload is kept on a failed poll so a transient error does not blank the page;
 * the error is shown beside it. A poll is skipped while the tab is hidden (and runs again when it
 * becomes visible) and while the previous request is still in flight.
 */
export function useApi<T>(path: string, refreshMs?: number) {
  const contextMs = useContext(RefreshContext);
  const intervalMs = refreshMs ?? contextMs;
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    // A new path is a new resource: never show the previous path's payload under it.
    setData(null);
    setError(null);
    let cancelled = false;
    let inFlight = false;
    const controller = new AbortController();

    async function poll() {
      if (inFlight || document.hidden) return;
      inFlight = true;
      try {
        const next = await fetchJson<T>(path, { signal: controller.signal });
        if (!cancelled) {
          setData(next);
          setError(null);
        }
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : String(err));
      } finally {
        inFlight = false;
      }
    }

    function onVisible() {
      if (!document.hidden) void poll();
    }

    void poll();
    const id = setInterval(poll, intervalMs);
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      cancelled = true;
      clearInterval(id);
      document.removeEventListener("visibilitychange", onVisible);
      controller.abort();
    };
  }, [path, intervalMs]);

  return { data, error, loading: !data && !error };
}
