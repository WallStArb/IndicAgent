"use client";

import { createContext, useContext, useEffect, useRef, useState } from "react";
import { fetchJson } from "@/lib/api";

/**
 * The APR poll intervals, provided once by the app shell: `refresh` for the summary pages
 * (`ui.dashboard.refresh_seconds`), `passport` for an instrument passport
 * (`ui.dashboard.passport_refresh_seconds`). Each matches its route's server cache TTL, so a poll
 * never re-downloads an unchanged cached answer.
 */
export interface PollIntervals {
  refresh: number;
  passport: number;
}

export const DEFAULT_INTERVALS: PollIntervals = { refresh: 60_000, passport: 900_000 };

export const RefreshContext = createContext<PollIntervals>(DEFAULT_INTERVALS);

/**
 * Poll a read-only API route at one of the dashboard's APR intervals.
 * The last good payload is kept on a failed poll so a transient error does not blank the page;
 * the error is shown beside it. Only a new path resets the payload: an interval change (the shell's
 * config read landing) applies from the next poll without refetching or blanking the page. A poll is skipped while the tab is hidden (and runs again when it
 * becomes visible) and while the previous request is still in flight.
 */
export function useApi<T>(path: string, interval: keyof PollIntervals = "refresh") {
  const intervalMs = useContext(RefreshContext)[interval];
  const intervalRef = useRef(intervalMs);
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    intervalRef.current = intervalMs;
  }, [intervalMs]);

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

    let timer: ReturnType<typeof setTimeout>;
    function schedule() {
      timer = setTimeout(() => {
        void poll();
        schedule();
      }, intervalRef.current);
    }

    void poll();
    schedule();
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      cancelled = true;
      clearTimeout(timer);
      document.removeEventListener("visibilitychange", onVisible);
      controller.abort();
    };
  }, [path]);

  return { data, error, loading: !data && !error };
}
