"use client";

import { useRef, useEffect, useState } from "react";
import type { TickData, BarData } from "@/lib/types";
import { fmtPrice, fmtChange, fmtPct } from "@/lib/format";

interface PriceHeroProps {
  tick: TickData;
  bar: BarData;
  prevClose: number;
}

/** Clamp a value between 0 and 100 for range bar positioning */
function rangePercent(price: number, lo: number, hi: number): number {
  if (hi <= lo) return 50;
  return Math.min(100, Math.max(0, ((price - lo) / (hi - lo)) * 100));
}

/** Thin horizontal range bar showing where price sits within a range */
function RangeBar({
  percent,
  label,
  lo,
  hi,
  empty,
}: {
  percent: number;
  label: string;
  lo: string;
  hi: string;
  empty: boolean;
}) {
  return (
    <div className="space-y-0.5">
      <div className="flex items-center justify-between">
        <span className="text-[0.55rem] uppercase tracking-wider text-[var(--text-muted)]">
          {label}
        </span>
        <div className="flex gap-1.5 font-data text-[0.55rem] text-[var(--text-muted)]">
          <span>{lo}</span>
          <span className="opacity-40">—</span>
          <span>{hi}</span>
        </div>
      </div>
      <div className="relative h-1 rounded-full bg-[var(--border-subtle)] overflow-visible">
        {empty ? (
          <div className="absolute inset-0 rounded-full bg-[var(--border-default)] opacity-40" />
        ) : (
          <div
            className="absolute top-1/2 -translate-y-1/2 w-1.5 h-1.5 rounded-full bg-[var(--text-accent)] shadow-sm"
            style={{ left: `calc(${percent}% - 3px)` }}
          />
        )}
      </div>
    </div>
  );
}

/** Compact bid/ask/last price display with flash + dual range bars */
export function PriceHero({ tick, bar, prevClose }: PriceHeroProps) {
  const isEmpty = tick.price === 0 || tick.lastUpdate === 0;

  // Flash state: "up" | "down" | null — drives CSS class on last price span
  const [flash, setFlash] = useState<"up" | "down" | null>(null);
  const prevPriceRef = useRef<number>(0);
  const flashTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    if (isEmpty) return;
    const prev = prevPriceRef.current;
    const curr = tick.price;

    if (prev !== 0 && curr !== prev) {
      // Clear any running flash so the animation restarts cleanly
      if (flashTimerRef.current) clearTimeout(flashTimerRef.current);
      setFlash(curr > prev ? "up" : "down");
      flashTimerRef.current = setTimeout(() => setFlash(null), 650);
    }
    prevPriceRef.current = curr;

    return () => {
      if (flashTimerRef.current) clearTimeout(flashTimerRef.current);
    };
  }, [tick.price, tick.lastUpdate, isEmpty]);

  // Derived values — all collapse to "—" when empty
  const price = isEmpty ? 0 : tick.price;
  const bid = isEmpty ? 0 : tick.bid;
  const ask = isEmpty ? 0 : tick.ask;
  const spread = bid > 0 && ask > 0 ? ask - bid : 0;

  // Last price color vs prev close
  function lastPriceColor(): string {
    if (isEmpty || prevClose === 0) return "text-[var(--text-primary)]";
    if (price > prevClose) return "text-[var(--green)]";
    if (price < prevClose) return "text-[var(--red)]";
    return "text-[var(--text-muted)]";
  }

  // Change vs prev close
  const chgClose = prevClose > 0 && !isEmpty ? price - prevClose : null;
  const chgClosePct =
    prevClose > 0 && !isEmpty ? ((price - prevClose) / prevClose) * 100 : null;

  // Change vs session open
  const sessionOpen = bar.open;
  const chgOpen =
    sessionOpen > 0 && !isEmpty ? price - sessionOpen : null;
  const chgOpenPct =
    sessionOpen > 0 && !isEmpty
      ? ((price - sessionOpen) / sessionOpen) * 100
      : null;

  // Range bars
  const barRangePct = rangePercent(price, bar.low, bar.high);
  const sessionRangePct = rangePercent(price, bar.low, bar.high); // same data (bar = current bar)

  // Direction helper for change values
  function chgColor(val: number | null): string {
    if (val === null) return "text-[var(--text-muted)]";
    if (val > 0) return "text-[var(--green)]";
    if (val < 0) return "text-[var(--red)]";
    return "text-[var(--text-muted)]";
  }

  // Flash class — key trick: we toggle the element out/in using the flash state
  // so the CSS animation always restarts from frame 0
  const flashClass =
    flash === "up"
      ? "price-flash-up"
      : flash === "down"
        ? "price-flash-down"
        : "";

  return (
    <div className="px-3 py-2 space-y-2">
      {/* Row 1: Bid / Last / Ask spread */}
      <div className="flex items-center justify-between gap-2">
        {/* Bid */}
        <div className="flex flex-col items-center min-w-0">
          <span className="text-[0.5rem] uppercase tracking-wider text-[var(--text-muted)] mb-0.5">
            Bid
          </span>
          <span className="font-data text-xs text-[var(--red)] tabular-nums">
            {isEmpty ? "—" : fmtPrice(bid)}
          </span>
        </div>

        {/* Last price — center, large */}
        <div className="flex flex-col items-center flex-1 min-w-0">
          <span className="text-[0.5rem] uppercase tracking-wider text-[var(--text-muted)] mb-0.5">
            Last
          </span>
          <span
            key={flash ?? "base"}
            className={`font-data text-xl font-semibold leading-none tracking-tight rounded px-1 transition-colors ${lastPriceColor()} ${flashClass}`}
          >
            {isEmpty ? "—" : fmtPrice(price)}
          </span>
          {/* Bar H/L under last price */}
          {!isEmpty && (
            <span className="font-data text-[0.5rem] text-[var(--text-muted)] mt-0.5 tabular-nums">
              H&nbsp;{fmtPrice(bar.high)}&nbsp;·&nbsp;L&nbsp;{fmtPrice(bar.low)}
            </span>
          )}
        </div>

        {/* Ask */}
        <div className="flex flex-col items-center min-w-0">
          <span className="text-[0.5rem] uppercase tracking-wider text-[var(--text-muted)] mb-0.5">
            Ask
          </span>
          <span className="font-data text-xs text-[var(--green)] tabular-nums">
            {isEmpty ? "—" : fmtPrice(ask)}
          </span>
        </div>
      </div>

      {/* Spread chip */}
      {!isEmpty && spread > 0 && (
        <div className="flex justify-center">
          <span className="font-data text-[0.5rem] text-[var(--text-muted)] bg-[var(--border-subtle)] rounded px-1 py-px tabular-nums">
            spd&nbsp;{fmtPrice(spread)}
          </span>
        </div>
      )}

      {/* Row 2: Change lines */}
      <div className="space-y-0.5">
        {/* vs prev close */}
        <div className="flex items-center justify-between">
          <span className="text-[0.55rem] text-[var(--text-muted)]">
            vs prev close
          </span>
          <div className="flex items-baseline gap-1 font-data">
            <span className={`text-xs font-medium ${chgColor(chgClose)}`}>
              {chgClose !== null ? fmtChange(chgClose) : "—"}
            </span>
            <span className={`text-[0.6rem] ${chgColor(chgClosePct)}`}>
              {chgClosePct !== null ? fmtPct(chgClosePct) : "—"}
            </span>
          </div>
        </div>

        {/* vs session open */}
        <div className="flex items-center justify-between">
          <span className="text-[0.55rem] text-[var(--text-muted)]">
            vs session open
          </span>
          <div className="flex items-baseline gap-1 font-data">
            <span className={`text-xs font-medium ${chgColor(chgOpen)}`}>
              {chgOpen !== null ? fmtChange(chgOpen) : "—"}
            </span>
            <span className={`text-[0.6rem] ${chgColor(chgOpenPct)}`}>
              {chgOpenPct !== null ? fmtPct(chgOpenPct) : "—"}
            </span>
          </div>
        </div>
      </div>

      {/* Row 3: Dual range bars */}
      <div className="space-y-1.5 pt-0.5">
        <RangeBar
          label="Bar range"
          percent={barRangePct}
          lo={isEmpty ? "—" : fmtPrice(bar.low)}
          hi={isEmpty ? "—" : fmtPrice(bar.high)}
          empty={isEmpty}
        />
        <RangeBar
          label="Session range"
          percent={sessionRangePct}
          lo={isEmpty ? "—" : fmtPrice(bar.low)}
          hi={isEmpty ? "—" : fmtPrice(bar.high)}
          empty={isEmpty}
        />
      </div>
    </div>
  );
}
