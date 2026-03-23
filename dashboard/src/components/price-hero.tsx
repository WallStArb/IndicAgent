"use client";

import type { SymbolData } from "@/lib/types";
import { fmtPrice, fmtTimeHMS } from "@/lib/format";

interface PriceHeroProps {
  data: SymbolData;
  activeTf: string;
  barWindowStr: string;
  barIsStale: boolean;
}

export function PriceHero({ data, activeTf, barWindowStr, barIsStale }: PriceHeroProps) {
  const { tick } = data;

  const isEmpty = tick.price === 0 || tick.lastUpdate === 0;
  const price = isEmpty ? 0 : tick.price;

  // Show time with seconds from the tick (real-time), not the bar
  const displayTime = tick.lastUpdate > 0 ? fmtTimeHMS(new Date(tick.lastUpdate).toISOString()) : null;

  return (
    <div className="px-3 py-1.5 flex items-center gap-3 font-data bg-[var(--bg-elevated)] border-b border-[var(--border-subtle)]">
      {/* Price + flash */}
      <span
        key={data.tickFlash ?? "base"}
        className={`text-lg font-semibold leading-none tracking-tight text-[var(--text-primary)] shrink-0 ${
          data.tickFlash === "up"
            ? "price-flash-up"
            : data.tickFlash === "down"
              ? "price-flash-down"
              : ""
        }`}
      >
        {price > 0 ? fmtPrice(price) : "—"}
      </span>

      {/* Last tick timestamp with seconds */}
      {displayTime && (
        <span className="text-[0.55rem] font-data text-[var(--text-secondary)] tabular-nums shrink-0">
          {displayTime}
        </span>
      )}

      {/* Bar window (with stale indicator) */}
      <span
        className="text-[0.5rem] font-data tabular-nums shrink-0 ml-auto"
        style={{ color: barIsStale ? "var(--red)" : "var(--text-muted)" }}
      >
        {barWindowStr}{barIsStale && " ·stale"}
      </span>
    </div>
  );
}
