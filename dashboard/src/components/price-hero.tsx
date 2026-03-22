"use client";

import type { SymbolData } from "@/lib/types";
import { fmtPrice } from "@/lib/format";

interface PriceHeroProps {
  data: SymbolData;
  activeTf: string;
}

function fmtTime(ts: string | number | undefined): string {
  if (!ts) return "";
  try {
    const d = new Date(ts);
    if (isNaN(d.getTime())) return "";
    return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", hour12: false });
  } catch {
    return "";
  }
}

/** Session range bar — colored fill between open and price, glowing price dot */
function SessionRangeBar({
  low,
  high,
  open,
  price,
}: {
  low: number;
  high: number;
  open: number;
  price: number;
}) {
  if (high <= low || price === 0) return null;

  const ratio = (v: number) => Math.min(1, Math.max(0, (v - low) / (high - low)));
  const priceR = ratio(price);
  const openR = ratio(open);
  const isUp = price >= open;

  const fillLeft = Math.min(priceR, openR);
  const fillWidth = Math.abs(priceR - openR);
  const glowColor = isUp ? "rgba(34,197,94,0.6)" : "rgba(239,68,68,0.6)";
  const fillClass = isUp ? "bg-[var(--green)]" : "bg-[var(--red)]";

  return (
    <div className="flex items-center gap-1.5 font-data text-[0.5rem] text-[var(--text-secondary)] flex-1 min-w-0">
      <span className="tabular-nums shrink-0">{fmtPrice(low)}</span>
      <div className="relative flex-1 h-1.5 rounded-full bg-[var(--border-subtle)]">
        {/* Colored fill: open → price */}
        <div
          className={`absolute top-0 h-full rounded-full ${fillClass} opacity-35`}
          style={{ left: `${fillLeft * 100}%`, width: `${fillWidth * 100}%` }}
        />
        {/* Open marker */}
        {open > 0 && (
          <div
            className="absolute top-0 h-full w-px bg-[var(--text-muted)] opacity-40"
            style={{ left: `${openR * 100}%` }}
          />
        )}
        {/* Price dot — glowing */}
        <div
          className={`absolute top-1/2 -translate-y-1/2 w-2 h-2 rounded-full ${fillClass}`}
          style={{
            left: `calc(${priceR * 100}% - 4px)`,
            boxShadow: `0 0 5px 1px ${glowColor}`,
          }}
        />
      </div>
      <span className="tabular-nums shrink-0">{fmtPrice(high)}</span>
    </div>
  );
}

export function PriceHero({ data, activeTf }: PriceHeroProps) {
  const { tick, bar, session } = data;
  const indicators = data.indicatorsByTf[activeTf] ?? null;

  const isEmpty = tick.price === 0 || tick.lastUpdate === 0;
  const price = isEmpty ? 0 : tick.price;

  const changeFromOpen =
    !isEmpty && session.open > 0 && price > 0
      ? ((price - session.open) / session.open) * 100
      : null;
  const isUp = changeFromOpen !== null ? changeFromOpen >= 0 : null;

  const displayTime =
    data.lastUpdate > 0
      ? fmtTime(data.lastUpdate)
      : fmtTime(indicators?.timestamp) || fmtTime(bar.timestamp);

  const hasRange = session.high > 0 && session.low > 0;

  return (
    <div className="px-3 py-1.5 flex items-center gap-2.5 font-data bg-[var(--bg-elevated)] border-b border-[var(--border-subtle)]">
      {/* Price + flash */}
      <span
        key={data.tickFlash ?? "base"}
        className={`text-xl font-semibold leading-none tracking-tight text-[var(--text-primary)] shrink-0 ${
          data.tickFlash === "up"
            ? "price-flash-up"
            : data.tickFlash === "down"
              ? "price-flash-down"
              : ""
        }`}
      >
        {price > 0 ? fmtPrice(price) : "—"}
      </span>

      {/* % change from session open */}
      {changeFromOpen !== null && (
        <span
          className={`text-[0.55rem] font-medium tabular-nums leading-none shrink-0 ${
            isUp ? "text-[var(--green)]" : "text-[var(--red)]"
          }`}
        >
          {isUp ? "▲" : "▼"}&nbsp;{Math.abs(changeFromOpen).toFixed(2)}%
        </span>
      )}

      {/* Timestamp — adjacent to price */}
      {displayTime && (
        <span className="text-[0.5rem] font-data text-[var(--text-secondary)] shrink-0">
          {displayTime}
        </span>
      )}

      {/* Session range bar — fills remaining space */}
      {hasRange && (
        <SessionRangeBar
          low={session.low}
          high={session.high}
          open={session.open}
          price={price}
        />
      )}
    </div>
  );
}
