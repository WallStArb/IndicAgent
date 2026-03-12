// dashboard/src/components/signal-banner.tsx
"use client";

import type { SignalData } from "@/lib/types";
import { fmtPrice, fmtPriceRange, fmtNum, fmtTimeHMS, fmtLagSeconds, pipelineLagS } from "@/lib/format";
import { TrendingUp, TrendingDown, ChevronRight } from "lucide-react";
import { useMemo } from "react";
import { deriveBarCloseIso } from "@/lib/timeframe-utils";
import { OutcomeBadge } from "@/components/signal-panel";

interface SignalBannerProps {
  signal: SignalData | null;
  onDrillDown?: () => void;
}

const HIGH_CONFIDENCE_THRESHOLD = 0.75;

function fmtSignalType(raw: string): string {
  return raw.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

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
  const ttsS = useMemo(
    () => signal ? (pipelineLagS(signal.signal_computed_at, barCloseIso) ?? (signal.pipeline_lag_s ?? null)) : null,
    [signal?.signal_computed_at, barCloseIso, signal?.pipeline_lag_s]
  );
  const ttsStr = useMemo(() => fmtLagSeconds(ttsS), [ttsS]);

  if (!signal || signal.confidence < HIGH_CONFIDENCE_THRESHOLD) return null;

  const hasZone = signal.entry_zone_low != null && signal.entry_zone_high != null;
  const hasLine2 = hasZone || !!signalTimeStr;

  return (
    <div className={signal.resolved ? "opacity-50" : undefined}>
      <button
        onClick={onDrillDown}
        className="w-full flex flex-col px-2 py-1 cursor-pointer"
        style={{
          backgroundColor: dimColor,
          borderBottom: `1px solid ${color}33`,
        }}
      >
        {/* Line 1: trade info */}
        <div className="flex items-center gap-1.5 w-full">
          {signal.resolved && <OutcomeBadge outcome={signal.outcome} small />}
          <Icon size={10} style={{ color }} />
          <span
            className="text-[0.55rem] font-bold uppercase tracking-widest"
            style={{ color }}
          >
            {isLong ? "LONG" : "SHORT"}
          </span>
          <span className="text-[0.55rem] font-data" style={{ color }}>
            @ {fmtPrice(signal.entry_price)}
          </span>
          <span className="text-[0.5rem] text-[var(--text-muted)]">
            ({fmtNum(signal.confidence * 100, 0)}% {fmtSignalType(signal.signal_type)})
          </span>
          <span className="text-[0.5rem] text-[var(--text-muted)]">
            | SL: {fmtPrice(signal.stop_loss)}
          </span>
          {signal.profit_target != null && (
            <span className="text-[0.5rem] text-[var(--text-muted)]">
              | T1: {fmtPrice(signal.profit_target)}
              {signal.rr_t1 != null && ` (${fmtNum(signal.rr_t1, 1)}R)`}
            </span>
          )}
          <ChevronRight size={8} className="ml-auto text-[var(--text-muted)]" />
        </div>

        {/* Line 2: zone + timing context */}
        {hasLine2 && (
          <div className="flex items-center gap-1 text-[0.45rem] font-data text-[var(--text-muted)] opacity-70 mt-0.5">
            {hasZone && (
              <span>Zone: {fmtPriceRange(signal.entry_zone_low!, signal.entry_zone_high!)}</span>
            )}
            {hasZone && signalTimeStr && (
              <span className="opacity-50">|</span>
            )}
            {signalTimeStr && (
              <span>
                Sig: {signalTimeStr}
                {ttsStr && ` (${ttsStr})`}
              </span>
            )}
          </div>
        )}
      </button>
    </div>
  );
}
