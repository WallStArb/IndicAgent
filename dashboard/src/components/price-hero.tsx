"use client";

import type { SymbolData } from "@/lib/types";
import {
  fmtPrice,
  fmtChange,
  fmtPct,
  fmtCompact,
  dirClass,
  freshness,
} from "@/lib/format";

interface PriceHeroProps {
  data: SymbolData;
}

/** Compact column-friendly price display with symbol header */
export function PriceHero({ data }: PriceHeroProps) {
  const { tick, bar, prevClose } = data;
  const price = tick.price || bar.close;
  const change = prevClose ? price - prevClose : 0;
  const changePct = prevClose ? (change / prevClose) * 100 : 0;
  const fresh = freshness(data.lastUpdate);

  return (
    <div className="px-3 py-2 space-y-1">
      {/* Row 1: Symbol name + live dot + bid/ask */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="text-sm font-bold text-[var(--text-primary)]">
            {data.symbol}
          </span>
          <span
            className={`inline-block w-1.5 h-1.5 rounded-full ${
              fresh === "live"
                ? "bg-[var(--green)] live-pulse"
                : fresh === "stale"
                  ? "bg-[var(--amber)]"
                  : "bg-[var(--text-muted)]"
            }`}
          />
        </div>
        <div className="font-data text-[0.6rem] text-right">
          <span className="text-up">{fmtPrice(tick.bid)}</span>
          <span className="text-[var(--text-muted)] mx-0.5">/</span>
          <span className="text-down">{fmtPrice(tick.ask)}</span>
        </div>
      </div>

      {/* Row 2: Big price + change */}
      <div className="flex items-baseline justify-between">
        <span className="font-data text-2xl font-semibold leading-none tracking-tight">
          {fmtPrice(price)}
        </span>
        <div className="flex items-baseline gap-1.5">
          <span
            className={`font-data text-sm font-medium ${dirClass(change)}`}
          >
            {fmtChange(change)}
          </span>
          <span className={`font-data text-xs ${dirClass(changePct)}`}>
            {fmtPct(changePct)}
          </span>
        </div>
      </div>

      {/* Row 3: OHLCV inline */}
      <div className="flex items-center justify-between font-data text-[0.6rem]">
        <span>
          <L>O</L> <V>{fmtPrice(bar.open)}</V>
        </span>
        <span>
          <L>H</L> <V>{fmtPrice(bar.high)}</V>
        </span>
        <span>
          <L>L</L> <V>{fmtPrice(bar.low)}</V>
        </span>
        <span>
          <L>Vol</L> <V>{fmtCompact(bar.volume)}</V>
        </span>
        <span>
          <L>VWAP</L> <V>{fmtPrice(data.indicators?.vwap)}</V>
        </span>
      </div>
    </div>
  );
}

function L({ children }: { children: React.ReactNode }) {
  return (
    <span className="uppercase tracking-wider text-[var(--text-muted)] mr-0.5">
      {children}
    </span>
  );
}

function V({ children }: { children: React.ReactNode }) {
  return <span className="text-[var(--text-accent)]">{children}</span>;
}
