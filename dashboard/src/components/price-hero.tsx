"use client";

// Connection status: StatusDot in trading-dashboard.tsx correctly reflects SSE readyState semantics:
// - connected (es.onopen) → green "Live"
// - connecting (initial state) → amber "Connecting"
// - disconnected (es.onerror) → red "Disconnected"
// Label was "Offline" — fixed to "Disconnected" per DASH-08 spec.

import type { SymbolData } from "@/lib/types";
import { fmtPrice, fmtChange, fmtPct, fmtCompact } from "@/lib/format";

interface PriceHeroProps {
  data: SymbolData;
  activeTf: string;
}

/** Clamp a ratio between 0 and 1 for range bar positioning */
function clampRatio(value: number, lo: number, hi: number): number | null {
  if (hi <= lo) return null;
  return Math.min(1, Math.max(0, (value - lo) / (hi - lo)));
}

/** Thin horizontal range bar — dot shows where price sits within the range */
function RangeBar({
  ratio,
  label,
  lo,
  hi,
}: {
  ratio: number | null;
  label: string;
  lo: string;
  hi: string;
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
        {ratio === null ? (
          <div className="absolute inset-0 rounded-full bg-[var(--border-default)] opacity-40" />
        ) : (
          <div
            className="absolute top-1/2 -translate-y-1/2 w-1.5 h-1.5 rounded-full bg-[var(--text-accent)] shadow-sm"
            style={{ left: `calc(${ratio * 100}% - 3px)` }}
          />
        )}
      </div>
    </div>
  );
}

/** Full price hero — bid/ask/last, flash, dual % change, H/L/Vol/VWAP, dual range bars */
export function PriceHero({ data, activeTf }: PriceHeroProps) {
  const { tick, bar, prevClose, session, tickFlash } = data;
  const indicators = data.indicatorsByTf[activeTf] ?? null;

  const isEmpty = tick.price === 0 || tick.lastUpdate === 0;
  const price = isEmpty ? 0 : tick.price;
  const bid = isEmpty ? 0 : tick.bid;
  const ask = isEmpty ? 0 : tick.ask;
  const spread = bid > 0 && ask > 0 ? ask - bid : 0;

  // Last price colour vs prev close
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
  const sessionOpen = session.open;
  const chgOpen = sessionOpen > 0 && !isEmpty ? price - sessionOpen : null;
  const chgOpenPct =
    sessionOpen > 0 && !isEmpty ? ((price - sessionOpen) / sessionOpen) * 100 : null;

  // Range bar ratios
  const barRatio = isEmpty ? null : clampRatio(price, bar.low, bar.high);
  const sessionRatio = isEmpty ? null : clampRatio(price, session.low, session.high);

  // Direction colour helper for change values
  function chgColor(val: number | null): string {
    if (val === null) return "text-[var(--text-muted)]";
    if (val > 0) return "text-[var(--green)]";
    if (val < 0) return "text-[var(--red)]";
    return "text-[var(--text-muted)]";
  }

  // Flash CSS class — keyed on tickFlash so React re-mounts the element and restarts animation
  const flashClass =
    tickFlash === "up"
      ? "price-flash-up"
      : tickFlash === "down"
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
            key={tickFlash ?? "base"}
            className={`font-data text-xl font-semibold leading-none tracking-tight rounded px-1 transition-colors duration-150 ${lastPriceColor()} ${flashClass}`}
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

      {/* Row 2: Dual % change lines */}
      <div className="space-y-0.5">
        {/* vs prev close */}
        <div className="flex items-center justify-between">
          <span className="text-[0.55rem] uppercase tracking-wider text-[var(--text-muted)]">
            Prev Close
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
          <span className="text-[0.55rem] uppercase tracking-wider text-[var(--text-muted)]">
            Session
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

      {/* Row 3: H/L/Vol/VWAP row */}
      {!isEmpty && (
        <div className="flex items-center justify-between font-data text-[0.55rem] text-[var(--text-muted)]">
          <span>
            <span className="text-[var(--green)]">H</span>&nbsp;{fmtPrice(bar.high)}
          </span>
          <span>
            <span className="text-[var(--red)]">L</span>&nbsp;{fmtPrice(bar.low)}
          </span>
          <span>Vol&nbsp;{fmtCompact(bar.volume)}</span>
          {indicators?.vwap != null && (
            <span>VWAP&nbsp;{fmtPrice(indicators.vwap)}</span>
          )}
        </div>
      )}

      {/* Row 4: Dual range bars */}
      <div className="space-y-1.5 pt-0.5">
        <RangeBar
          label="Bar"
          ratio={barRatio}
          lo={isEmpty ? "—" : fmtPrice(bar.low)}
          hi={isEmpty ? "—" : fmtPrice(bar.high)}
        />
        <RangeBar
          label="Session"
          ratio={sessionRatio}
          lo={isEmpty || session.low === 0 ? "—" : fmtPrice(session.low)}
          hi={isEmpty || session.high === 0 ? "—" : fmtPrice(session.high)}
        />
      </div>
    </div>
  );
}
