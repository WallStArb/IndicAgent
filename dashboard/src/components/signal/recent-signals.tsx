"use client";

import { useMemo, useState, useEffect } from "react";
import type { SignalData } from "@/lib/types";
import { TF_OFFSETS } from "@/lib/timeframe-utils";
import { getApiBase } from "@/lib/api";
import { dbRowToSignalData, type DbSignalRow, type SignalWindowSummary } from "@/lib/signal-utils";
import { RecentSignalCard } from "./recent-signal-card";
import { Empty } from "../ui/primitives";

interface RecentSignalsProps {
  symbol: string;
  timeframe: string;
  signalsHistory: SignalData[];
  selectedSignal: SignalData | null;
  onSignalSelect: (signal: SignalData) => void;
}

/**
 * Recent Signals sidebar — shows last 5 signals for current symbol/TF.
 * Fetches DB history on mount, merges with SSE history (SSE wins on conflicts).
 */
export function RecentSignals({
  symbol,
  timeframe,
  signalsHistory,
  selectedSignal,
  onSignalSelect,
}: RecentSignalsProps) {
  const [dbSignals, setDbSignals] = useState<SignalData[]>([]);

  useEffect(() => {
    const controller = new AbortController();
    const base = getApiBase();
    fetch(
      `${base}/api/signals/recent?symbol=${encodeURIComponent(symbol)}&timeframe=${encodeURIComponent(timeframe)}&limit=20`,
      { signal: controller.signal }
    )
      .then((r) => (r.ok ? r.json() : Promise.reject(r.status)))
      .then((body: { signals: DbSignalRow[]; summary: SignalWindowSummary }) => {
        setDbSignals(body.signals.map((row) => dbRowToSignalData(row, symbol)));
      })
      .catch((err) => {
        if (err instanceof Error && err.name === "AbortError") return;
        // non-fatal — SSE history still works
      });
    return () => controller.abort();
  }, [symbol, timeframe]);

  // Merge DB signals with SSE history — SSE wins on same signal_id
  const mergedSignalsHistory = useMemo(() => {
    const byId = new Map<string, SignalData>();
    for (const s of dbSignals) {
      if (s.signal_id) byId.set(s.signal_id, s);
    }
    for (const s of signalsHistory) {
      if (s.signal_id) byId.set(s.signal_id, s);
      else byId.set(`${s.timestamp}:${s.entry_price}`, s);
    }
    return Array.from(byId.values()).sort((a, b) => {
      const ta = new Date(a.signal_computed_at ?? a.timestamp).getTime();
      const tb = new Date(b.signal_computed_at ?? b.timestamp).getTime();
      return tb - ta;
    });
  }, [dbSignals, signalsHistory]);

  // ~10 bars lookback window using TF_OFFSETS (seconds → ms)
  const windowMs = (TF_OFFSETS[timeframe] ?? 60) * 1000 * 10;

  // Memoized: only recompute when signalsHistory or timeframe changes.
  // cutoff updates on those changes, which is the right cadence (new data = new window).
  const recentSignals = useMemo(() => {
    const cutoff = Date.now() - windowMs;
    return mergedSignalsHistory
      .filter((s) => {
        if (s.timeframe !== timeframe) return false;
        const t = (s.bar_close_ts ?? s.timestamp) ? new Date(s.bar_close_ts ?? s.timestamp).getTime() : NaN;
        return !isNaN(t) && t >= cutoff;
      })
      .slice(0, 5);
  }, [mergedSignalsHistory, timeframe, windowMs]);

  const hasSignals = recentSignals.length > 0;

  return (
    <div className="border-b border-[var(--border-subtle)]">
      <h3 className="text-[0.55rem] font-semibold uppercase tracking-widest text-[var(--text-muted)] mb-2 px-4 pt-3">
        Recent Signals ({recentSignals.length}) — {timeframe}
      </h3>
      {hasSignals ? (
        <div className="px-4 pb-3 flex flex-col gap-2">
          {recentSignals.map((signal) => (
            <RecentSignalCard
              key={signal.signal_id || `${signal.timestamp}-${signal.entry_price}`}
              signal={signal}
              isSelected={selectedSignal?.signal_id === signal.signal_id}
              onClick={() => onSignalSelect(signal)}
            />
          ))}
        </div>
      ) : (
        <div className="px-4 pb-3">
          <Empty>No recent signals for {symbol}:{timeframe}</Empty>
        </div>
      )}
    </div>
  );
}
