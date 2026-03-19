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
        </div>
      </div>
    </div>
  );
}
