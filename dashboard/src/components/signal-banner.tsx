// dashboard/src/components/signal-banner.tsx
"use client";

import type { SignalData } from "@/lib/types";
import { fmtPrice, fmtPriceRange, fmtNum, fmtTimeHMS, fmtLagSeconds, pipelineLagS } from "@/lib/format";
import { TrendingUp, TrendingDown, ChevronRight } from "lucide-react";
import { useMemo } from "react";
import { deriveBarCloseIso } from "@/lib/timeframe-utils";
import { Tooltip } from "@/components/tooltip";
import { OutcomeBadge } from "@/components/signal-panel";
import {
  barTimeTooltip,
  sigTimeTooltip,
  ttsTooltip,
  barClosePriceTooltip,
  marketPriceTooltip,
  entryTooltip,
  slTooltip,
  zoneTooltip,
} from "@/lib/signal-tooltips";

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
    <div className={signal.resolved ? "opacity-50" : undefined}>
      <button
        onClick={onDrillDown}
        className="w-full flex items-center gap-2 px-2 py-1 cursor-pointer"
        style={{
          backgroundColor: dimColor,
          borderBottom: `1px solid ${color}33`,
        }}
      >
        {signal.resolved && (
          <OutcomeBadge outcome={signal.outcome} />
        )}
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
      <span className="text-[0.5rem] text-[var(--text-muted)] font-data flex items-center gap-1">
        <Tooltip tooltip={entryTooltip()}>
          <span>E</span>
        </Tooltip>
        <span>{fmtPrice(signal.entry_price)}</span>
        {signal.entry_zone_low != null && signal.entry_zone_high != null && (
          <>
            <Tooltip tooltip={zoneTooltip()}>
              <span className="opacity-50 ml-0.5">ZONE</span>
            </Tooltip>
            <span className="opacity-50">{fmtPriceRange(signal.entry_zone_low, signal.entry_zone_high)}</span>
          </>
        )}
        <span className="opacity-30">|</span>
        <Tooltip tooltip={slTooltip()}>
          <span>SL</span>
        </Tooltip>
        <span>{fmtPrice(signal.stop_loss)}</span>
      </span>
      {(barCloseStr || signalTimeStr || signal.bar_close_price != null || signal.market_price_at_signal != null) && (
        <span className="text-[0.45rem] font-data text-[var(--text-muted)] opacity-70 flex items-center gap-1 flex-wrap">
          {barCloseStr && (
            <Tooltip tooltip={barTimeTooltip()}>
              <span className="opacity-50">BAR</span>
            </Tooltip>
          )}
          {barCloseStr && <span>{barCloseStr}</span>}
          {signal.bar_close_price != null && (
            <Tooltip tooltip={barClosePriceTooltip()}>
              <span>@ {fmtPrice(signal.bar_close_price)}</span>
            </Tooltip>
          )}
          {ttsStr && (
            <Tooltip tooltip={ttsTooltip()}>
              <span>{ttsStr}</span>
            </Tooltip>
          )}
          {signalTimeStr && (
            <Tooltip tooltip={sigTimeTooltip()}>
              <span className="opacity-50">SIG</span>
            </Tooltip>
          )}
          {signalTimeStr && <span style={{ color: "var(--text-secondary)" }}>{signalTimeStr}</span>}
          {signal.market_price_at_signal != null && (
            <Tooltip tooltip={marketPriceTooltip()}>
              <span>@ {fmtPrice(signal.market_price_at_signal)}</span>
            </Tooltip>
          )}
        </span>
      )}
        <ChevronRight size={8} className="ml-auto text-[var(--text-muted)]" />
      </button>
    </div>
  );
}
