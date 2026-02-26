"use client";

import type { IndicatorData } from "@/lib/types";
import { fmtNum, oscClass, dirClass } from "@/lib/format";

interface IndicatorGridProps {
  indicators: IndicatorData | null;
}

/** Compact indicator display for column layout: wrapping metric pairs */
export function IndicatorGrid({ indicators }: IndicatorGridProps) {
  const ind = indicators;

  return (
    <div className="divide-y divide-[var(--border-subtle)]">
      {/* Momentum */}
      <Zone label="MTM">
        <M label="RSI" value={fmtNum(ind?.rsi, 1)} cls={oscClass(ind?.rsi)} />
        <M
          label="MACD"
          value={fmtNum(ind?.macd, 2)}
          cls={dirClass(ind?.macd_histogram)}
        />
        <M
          label="Stoch"
          value={`${fmtNum(ind?.stoch_k, 0)}/${fmtNum(ind?.stoch_d, 0)}`}
          cls={oscClass(ind?.stoch_k, 80, 20)}
        />
        <M label="CCI" value={fmtNum(ind?.cci, 0)} cls={dirClass(ind?.cci)} />
        <M
          label="W%R"
          value={fmtNum(ind?.williams_r, 0)}
          cls={oscClass(
            ind?.williams_r !== undefined ? -ind.williams_r : undefined,
            70,
            30
          )}
        />
      </Zone>

      {/* Volatility & Trend */}
      <Zone label="VOL">
        <M label="ATR" value={fmtNum(ind?.atr, 2)} />
        <M
          label="BB"
          value={`${fmtNum(ind?.bb_lower, 0)}–${fmtNum(ind?.bb_upper, 0)}`}
        />
        <M
          label="SMA20"
          value={fmtNum(ind?.sma_20, 0)}
          cls="text-[var(--text-accent)]"
          title="SMA 20 — Short-term trend (20 bars). Price above = near-term bullish."
        />
        <M
          label="SMA50"
          value={fmtNum(ind?.sma_50, 0)}
          cls="text-[var(--text-accent)]"
          title="SMA 50 — Medium-term trend (50 bars). Key institutional reference level."
        />
        <M
          label="EMA13"
          value={fmtNum(ind?.ema_13, 0)}
          cls="text-[var(--text-accent)]"
          title="EMA 13 — Fast signal line. Reacts quickly to momentum shifts."
        />
        <M
          label="EMA21"
          value={fmtNum(ind?.ema_21, 0)}
          cls="text-[var(--text-accent)]"
          title="EMA 21 — Fibonacci EMA. Trend confirmation; crossover with EMA13 signals entries."
        />
      </Zone>

      {/* Volume */}
      <Zone label="VLME">
        <M
          label="MFI"
          value={fmtNum(ind?.mfi, 1)}
          cls={oscClass(ind?.mfi, 80, 20)}
        />
        <M label="OBV" value={fmtNum(ind?.obv, 0)} />
        <M
          label="VWAP"
          value={fmtNum(ind?.vwap, 2)}
          cls="text-[var(--blue)]"
        />
      </Zone>
    </div>
  );
}

function Zone({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div className="px-2 py-1">
      <div className="flex items-start gap-2">
        <span className="zone-label shrink-0 pt-px w-10">{label}</span>
        <div className="flex flex-wrap items-center gap-x-3 gap-y-0.5">
          {children}
        </div>
      </div>
    </div>
  );
}

function M({
  label,
  value,
  cls = "text-[var(--text-accent)]",
  title,
}: {
  label: string;
  value: string;
  cls?: string;
  title?: string;
}) {
  return (
    <span className="inline-flex items-baseline gap-1 whitespace-nowrap" title={title}>
      <span className="text-[0.55rem] font-medium uppercase tracking-wider text-[var(--text-muted)]">
        {label}
      </span>
      <span className={`font-data text-[0.7rem] font-medium ${cls}`}>
        {value}
      </span>
    </span>
  );
}
