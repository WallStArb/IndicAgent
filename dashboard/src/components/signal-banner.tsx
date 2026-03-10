// dashboard/src/components/signal-banner.tsx
"use client";

import type { SignalData } from "@/lib/types";
import { fmtPrice, fmtNum, fmtTimeHMS, fmtLagSeconds, pipelineLagS } from "@/lib/format";
import { TrendingUp, TrendingDown, ChevronRight } from "lucide-react";
import { useMemo } from "react";
import { deriveBarCloseIso } from "@/lib/timeframe-utils";

interface SignalBannerProps {
  signal: SignalData | null;
  onDrillDown?: () => void;
}

const HIGH_CONFIDENCE_THRESHOLD = 0.75;

export function SignalBanner({ signal, onDrillDown }: SignalBannerProps) {
  const isLong = signal?.direction === "long";
  const color = isLong ? "var(--green)" : "var(--red)";
  const dimColor = isLong ? "var(--green-dim)" : "var(--red-dim)";
  const Icon = isLong ? TrendingUp : TrendingDown;

  const barCloseIso = useMemo(
    () => signal ? deriveBarCloseIso(signal.bar_close_ts, signal.timestamp, signal.timeframe) : undefined,
    [signal?.bar_close_ts, signal?.timestamp, signal?.timeframe]
  );
  const signalTimeStr = useMemo(() => fmtTimeHMS(signal?.signal_computed_at), [signal?.signal_computed_at]);
  const barCloseStr = useMemo(() => fmtTimeHMS(barCloseIso), [barCloseIso]);
  const ttsS = useMemo(
    () => signal ? (pipelineLagS(signal.signal_computed_at, barCloseIso) ?? (signal.pipeline_lag_s ?? null)) : null,
    [signal?.signal_computed_at, barCloseIso, signal?.pipeline_lag_s]
  );
  const ttsStr = useMemo(() => fmtLagSeconds(ttsS), [ttsS]);

  if (!signal || signal.confidence < HIGH_CONFIDENCE_THRESHOLD) return null;

  return (
    <button
      onClick={onDrillDown}
      className="w-full flex items-center gap-2 px-2 py-1 cursor-pointer"
      style={{
        backgroundColor: dimColor,
        borderBottom: `1px solid ${color}33`,
      }}
    >
      <Icon size={10} style={{ color }} />
      <span
        className="text-[0.55rem] font-bold uppercase tracking-widest"
        style={{ color }}
      >
        {isLong ? "LONG" : "SHORT"}
      </span>
      <span className="text-[0.55rem] text-[var(--text-muted)]">
        {signal.signal_type.replace(/_/g, " ")}
      </span>
      <span className="text-[0.55rem] font-data font-bold" style={{ color }}>
        {fmtNum(signal.confidence * 100, 0)}%
      </span>
      <span className="text-[0.5rem] text-[var(--text-muted)] font-data">
        {fmtPrice(signal.entry_price)} → {fmtPrice(signal.stop_loss)}
      </span>
      {(barCloseStr || signalTimeStr) && (
        <span className="text-[0.45rem] font-data text-[var(--text-muted)] opacity-60 flex items-center gap-0.5">
          {barCloseStr && <span>{barCloseStr}</span>}
          {barCloseStr && signalTimeStr && <span className="opacity-30">→</span>}
          {signalTimeStr && <span style={{ color: "var(--text-secondary)" }}>{signalTimeStr}</span>}
          {ttsStr && <span className="opacity-50 ml-0.5">{ttsStr}</span>}
          {signal.market_price_at_signal != null && (
            <span className="ml-0.5">@ {fmtPrice(signal.market_price_at_signal)}</span>
          )}
        </span>
      )}
      <ChevronRight size={8} className="ml-auto text-[var(--text-muted)]" />
    </button>
  );
}
