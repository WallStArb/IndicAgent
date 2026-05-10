// dashboard/src/components/signal-banner.tsx
"use client";

import type { SignalData } from "@/lib/types";
import { fmtPrice, fmtPriceRange, fmtNum, fmtTimeHMS, fmtLagSeconds, pipelineLagS } from "@/lib/format";
import { TrendingUp, TrendingDown, ChevronRight } from "lucide-react";
import { useMemo } from "react";
import { deriveBarCloseIso } from "@/lib/timeframe-utils";
import { OutcomeBadge } from "@/components/outcome-badge";
import { isHeroTier } from "@/lib/signal-tier";
import { formatSignalType } from "@/lib/plugin-utils";

interface SignalBannerProps {
  signal: SignalData | null;
  onDrillDown?: () => void;
  isLoading?: boolean;
}

export function SignalBanner({ signal, onDrillDown, isLoading }: SignalBannerProps) {
  const isLong = signal?.direction === "long";
  const dirColor = isLong ? "text-green-600" : "text-red-600";

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

  if (isLoading) {
    return (
      <div className="w-full h-12 bg-[var(--bg-hover)] animate-pulse rounded-md" />
    );
  }

  if (!signal || !isHeroTier(signal.confidence, signal.cis_score)) return null;

  const hasZone = signal.entry_zone_low != null && signal.entry_zone_high != null;
  const hasLine2 = hasZone || !!signalTimeStr;

  return (
    <div className={signal.resolved ? "opacity-50" : undefined}>
      <button
        onClick={onDrillDown}
        aria-label={`Drill down into ${isLong ? "long" : "short"} signal details`}
        className={`w-full flex flex-col px-2 py-1 cursor-pointer rounded-sm border-b transition-colors ${
          isLong 
            ? "bg-green-50 border-green-200 hover:bg-green-100" 
            : "bg-red-50 border-red-200 hover:bg-red-100"
        }`}
      >
        {/* Line 1: trade info */}
        <div className="flex items-center gap-1.5 w-full">
          {signal.resolved && <OutcomeBadge outcome={signal.outcome} small />}
          {isLong ? (
            <TrendingUp size={12} className={dirColor} />
          ) : (
            <TrendingDown size={12} className={dirColor} />
          )}
          <span className={`text-[0.65rem] font-bold uppercase tracking-widest ${dirColor}`}>
            {isLong ? "LONG" : "SHORT"}
          </span>
          <span className={`text-[0.65rem] font-data ${dirColor}`}>
            @ {fmtPrice(signal.entry_price)}
          </span>
          <span className="text-[0.6rem] font-data text-slate-500">
            ({fmtNum(signal.confidence * 100, 0)}% {formatSignalType(signal.signal_type)})
          </span>
          <span className="text-[0.6rem] font-data text-slate-500">
            | SL: {fmtPrice(signal.stop_loss)}
          </span>
          {signal.profit_target != null && (
            <span className="text-[0.6rem] font-data text-slate-500">
              | T1: {fmtPrice(signal.profit_target)}
              {signal.rr_t1 != null && ` (${fmtNum(signal.rr_t1, 1)}R)`}
            </span>
          )}
          <ChevronRight size={10} className="ml-auto text-slate-400" />
        </div>

        {/* Line 2: zone + timing context */}
        {hasLine2 && (
          <div className="flex items-center gap-1 text-[0.55rem] font-data text-slate-500 mt-0.5">
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
