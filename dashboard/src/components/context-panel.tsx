"use client";

import type { ContextData } from "@/lib/types";
import { ZoneLabel, MiniBar, VolatilityPill, TrendLabel, MomentumGauge, Metric } from "./ui/metric-components";

interface ContextPanelProps {
  context: ContextData | null;
}

/** I4 Context — compact column layout */
export function ContextPanel({ context }: ContextPanelProps) {
  const c = context;

  return (
    <div className="px-2 py-1">
      <div className="flex items-start gap-2">
        <ZoneLabel tier="I4" />
        <div className="flex flex-wrap items-center gap-x-3 gap-y-0.5">
          {/* Volatility regime */}
          <span className="inline-flex items-center gap-1 whitespace-nowrap">
            <Metric label="Vol" value={<VolatilityPill regime={c?.volatility_regime} />} />
            {c?.vol_expanding !== undefined && (
              <span
                className={`font-data text-[0.55rem] ${c.vol_expanding ? "text-[var(--amber)]" : "text-[var(--blue)]"}`}
              >
                {c.vol_expanding ? "↑" : "↓"}
              </span>
            )}
          </span>

          {/* ATR percentile */}
          {c?.atr_percentile !== undefined && (
            <Metric label="ATR%" value={<MiniBar value={c.atr_percentile} />} />
          )}

          {/* Trend regime */}
          <Metric label="Trend" value={<TrendLabel regime={c?.trend_regime} />} />

          {/* Momentum bias */}
          <Metric label="Mom" value={<MomentumGauge bias={c?.momentum_bias} />} />

          {/* Hurst exponent */}
          {c?.hurst_exponent != null && (
            <span className="inline-flex items-center gap-1 whitespace-nowrap">
              <span className="text-[0.55rem] text-[var(--text-muted)]">H</span>
              <span className={`font-data text-[0.65rem] font-medium ${
                c.hurst_exponent > 0.6 ? "text-up"
                : c.hurst_exponent < 0.4 ? "text-[var(--blue)]"
                : "text-[var(--text-muted)]"
              }`}>
                {c.hurst_exponent.toFixed(2)}
              </span>
            </span>
          )}

          {/* VIX z-score */}
          {c?.vix_z != null && (
            <span className="inline-flex items-center gap-1 whitespace-nowrap">
              <span className="text-[0.55rem] text-[var(--text-muted)]">VIX</span>
              <span className={`font-data text-[0.65rem] font-medium ${
                Math.abs(c.vix_z) > 2 ? "text-[var(--amber)]" : "text-[var(--text-secondary)]"
              }`}>
                {c.vix_level != null ? c.vix_level.toFixed(1) : ""}
                {c.vix_z != null ? <span className="text-[0.5rem] text-[var(--text-muted)]"> ({c.vix_z > 0 ? "+" : ""}{c.vix_z.toFixed(1)}σ)</span> : null}
              </span>
            </span>
          )}

          {/* VWAP deviation */}
          {c?.session_vwap_deviation_sigma != null && Math.abs(c.session_vwap_deviation_sigma) > 0.5 && (
            <span className="inline-flex items-center gap-1 whitespace-nowrap">
              <span className="text-[0.55rem] text-[var(--text-muted)]">VWAP</span>
              <span className={`font-data text-[0.65rem] ${
                c.above_session_vwap ? "text-up" : "text-down"
              }`}>
                {c.session_vwap_deviation_sigma > 0 ? "+" : ""}{c.session_vwap_deviation_sigma.toFixed(1)}σ
              </span>
            </span>
          )}

          {/* LVN breakout zone */}
          {c?.in_lvn && (
            <span className="inline-flex items-center gap-1 whitespace-nowrap px-1 rounded bg-[var(--amber-dim)]">
              <span className="text-[0.55rem] text-[var(--amber)] font-semibold uppercase tracking-wider">LVN</span>
            </span>
          )}
        </div>
      </div>
    </div>
  );
}
