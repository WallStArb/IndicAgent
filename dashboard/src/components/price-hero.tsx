"use client";

import type { SymbolData } from "@/lib/types";
import { fmtPrice, fmtCompact } from "@/lib/format";

interface PriceHeroProps {
  data: SymbolData;
  activeTf: string;
}

function clampRatio(value: number, lo: number, hi: number): number | null {
  if (hi <= lo) return null;
  return Math.min(1, Math.max(0, (value - lo) / (hi - lo)));
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

/** Compact inline range bar — dot showing price position within session envelope */
function InlineRangeBar({ ratio }: { ratio: number | null }) {
  return (
    <div className="relative flex-1 h-1 rounded-full bg-[var(--border-subtle)] overflow-visible">
      {ratio === null ? (
        <div className="absolute inset-0 rounded-full bg-[var(--border-default)] opacity-40" />
      ) : (
        <div
          className="absolute top-1/2 -translate-y-1/2 w-1.5 h-1.5 rounded-full bg-[var(--text-accent)] shadow-sm"
          style={{ left: `calc(${ratio * 100}% - 3px)` }}
        />
      )}
    </div>
  );
}

export function PriceHero({ data, activeTf }: PriceHeroProps) {
  const { tick, bar, session } = data;
  const indicators = data.indicatorsByTf[activeTf] ?? null;

  const isEmpty = tick.price === 0 || tick.lastUpdate === 0;
  const price = isEmpty ? 0 : tick.price;
  const bid = isEmpty ? 0 : tick.bid;
  const ask = isEmpty ? 0 : tick.ask;

  const sessionOpen = session.open;
  const ref = data.prevClose > 0 ? data.prevClose : sessionOpen;
  const chg = ref > 0 && price > 0 ? price - ref : null;
  const chgPct = ref > 0 && price > 0 ? ((price - ref) / ref) * 100 : null;

  const sessionRatio =
    isEmpty || session.high <= session.low
      ? null
      : clampRatio(price, session.low, session.high);

  // "as of" — show when data was last received in the browser (Date.now()), not the server bar
  // timestamp, which can lag by minutes during low-liquidity periods.
  const displayTime = data.lastUpdate > 0 ? fmtTime(data.lastUpdate) : (fmtTime(indicators?.timestamp) || fmtTime(bar.timestamp));

  const sessionVol = session.sessionVolume > 0 ? fmtCompact(session.sessionVolume) : null;

  function chgColor(v: number | null): string {
    if (v === null) return "text-[var(--text-muted)]";
    if (v > 0) return "text-[var(--green)]";
    if (v < 0) return "text-[var(--red)]";
    return "text-[var(--text-muted)]";
  }

  function priceColor(): string {
    if (!price || !ref) return "text-[var(--text-primary)]";
    if (price > ref) return "text-[var(--green)]";
    if (price < ref) return "text-[var(--red)]";
    return "text-[var(--text-primary)]";
  }

  return (
    <div className="px-3 pt-1.5 pb-2 space-y-1.5">
      {/* Line 1: Big price + session change + session volume */}
      <div className="flex items-baseline gap-1.5">
        <span
          key={data.tickFlash ?? "base"}
          className={`font-data text-xl font-semibold leading-none tracking-tight ${priceColor()} ${
            data.tickFlash === "up"
              ? "price-flash-up"
              : data.tickFlash === "down"
                ? "price-flash-down"
                : ""
          }`}
        >
          {price > 0 ? fmtPrice(price) : "—"}
        </span>
        {chg !== null && (
          <span className={`font-data text-[0.65rem] ${chgColor(chg)}`}>
            {chg >= 0 ? "+" : ""}
            {chg.toFixed(2)}
            {chgPct !== null && (
              <span className="ml-0.5 opacity-80">
                ({chgPct >= 0 ? "+" : ""}
                {chgPct.toFixed(2)}%)
              </span>
            )}
          </span>
        )}
        {sessionVol && (
          <span className="font-data text-[0.5rem] text-[var(--text-muted)] ml-1">
            vol {sessionVol}
          </span>
        )}
      </div>

      {/* Line 2: Bid / Ask / spread + timestamp */}
      <div className="flex items-center gap-3 font-data text-[0.6rem]">
        <span>
          <span className="text-[var(--text-muted)]">Bid </span>
          <span className="text-[var(--red)] tabular-nums">
            {isEmpty || bid === 0 ? "—" : fmtPrice(bid)}
          </span>
        </span>
        <span>
          <span className="text-[var(--text-muted)]">Ask </span>
          <span className="text-[var(--green)] tabular-nums">
            {isEmpty || ask === 0 ? "—" : fmtPrice(ask)}
          </span>
        </span>
        {!isEmpty && bid > 0 && ask > 0 && (
          <span className="text-[var(--text-muted)] tabular-nums">
            spd {fmtPrice(ask - bid)}
          </span>
        )}
        {displayTime && (
          <span className="ml-auto font-data text-[0.5rem] text-[var(--text-muted)] opacity-70">
            as of {displayTime}
          </span>
        )}
      </div>

      {/* Line 3: Session O/H/L + compact inline range bar */}
      {session.high > 0 && (
        <div className="flex items-center gap-2 font-data text-[0.5rem] text-[var(--text-muted)]">
          <span>O&nbsp;{fmtPrice(session.open)}</span>
          <span className="text-[var(--green)]">H&nbsp;{fmtPrice(session.high)}</span>
          <span className="text-[var(--red)]">L&nbsp;{fmtPrice(session.low)}</span>
          <InlineRangeBar ratio={sessionRatio} />
        </div>
      )}
    </div>
  );
}
