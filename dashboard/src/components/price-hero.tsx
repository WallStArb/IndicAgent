"use client";

import type { SymbolData } from "@/lib/types";
import { fmtPrice, fmtCompact } from "@/lib/format";

interface PriceHeroProps {
  data: SymbolData;
  activeTf: string;
}

/** Clamp a ratio between 0 and 1 for range bar positioning */
function clampRatio(value: number, lo: number, hi: number): number | null {
  if (hi <= lo) return null;
  return Math.min(1, Math.max(0, (value - lo) / (hi - lo)));
}

/** Thin horizontal range bar with a dot showing price position */
function RangeBar({
  ratio,
  label,
  lo,
  hi,
  accent,
}: {
  ratio: number | null;
  label: string;
  lo: string;
  hi: string;
  accent?: boolean;
}) {
  return (
    <div className="flex items-center gap-1.5">
      <span className={`text-[0.5rem] uppercase tracking-wider w-7 shrink-0 ${accent ? "text-[var(--text-secondary)]" : "text-[var(--text-muted)]"}`}>
        {label}
      </span>
      <span className="font-data text-[0.5rem] text-[var(--text-muted)] tabular-nums w-11 text-right shrink-0">
        {lo}
      </span>
      <div className={`relative flex-1 rounded-full overflow-visible ${accent ? "h-1.5" : "h-1"} bg-[var(--border-subtle)]`}>
        {ratio === null ? (
          <div className="absolute inset-0 rounded-full bg-[var(--border-default)] opacity-40" />
        ) : (
          <div
            className={`absolute top-1/2 -translate-y-1/2 rounded-full bg-[var(--text-accent)] shadow-sm ${accent ? "w-2 h-2" : "w-1.5 h-1.5"}`}
            style={{ left: `calc(${ratio * 100}% - ${accent ? 4 : 3}px)` }}
          />
        )}
      </div>
      <span className="font-data text-[0.5rem] text-[var(--text-muted)] tabular-nums w-11 shrink-0">
        {hi}
      </span>
    </div>
  );
}

/** Format a timestamp string/ms to HH:MM */
function fmtTime(ts: string | number | undefined): string {
  if (!ts) return "";
  try {
    const d = typeof ts === "number" ? new Date(ts) : new Date(ts);
    if (isNaN(d.getTime())) return "";
    return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", hour12: false });
  } catch {
    return "";
  }
}

/** Price detail section: session range, bid/ask, bar H/L/Vol at bottom */
export function PriceHero({ data, activeTf }: PriceHeroProps) {
  const { tick, bar, session } = data;
  const indicators = data.indicatorsByTf[activeTf] ?? null;

  const isEmpty = tick.price === 0 || tick.lastUpdate === 0;
  const price = isEmpty ? 0 : tick.price;
  const bid = isEmpty ? 0 : tick.bid;
  const ask = isEmpty ? 0 : tick.ask;

  const sessionRatio = isEmpty || session.high <= session.low ? null : clampRatio(price, session.low, session.high);
  const barRatio = isEmpty ? null : clampRatio(price, bar.low, bar.high);

  // Timestamp of the bar that indicators were computed from
  const indicatorBarTime = fmtTime(indicators?.timestamp);
  const barTime = fmtTime(bar.timestamp);
  const displayTime = indicatorBarTime || barTime;

  return (
    <div className="px-3 pt-1.5 pb-2 space-y-2">
      {/* Session range bar — prominent */}
      <RangeBar
        label="Sess"
        ratio={sessionRatio}
        lo={session.low > 0 ? fmtPrice(session.low) : "—"}
        hi={session.high > 0 ? fmtPrice(session.high) : "—"}
        accent
      />

      {/* Bid / Ask / Spread */}
      <div className="flex items-center gap-3 font-data text-[0.6rem]">
        <span>
          <span className="text-[var(--text-muted)]">Bid </span>
          <span className="text-[var(--red)] tabular-nums">{isEmpty || bid === 0 ? "—" : fmtPrice(bid)}</span>
        </span>
        <span>
          <span className="text-[var(--text-muted)]">Ask </span>
          <span className="text-[var(--green)] tabular-nums">{isEmpty || ask === 0 ? "—" : fmtPrice(ask)}</span>
        </span>
        {!isEmpty && bid > 0 && ask > 0 && (
          <span className="text-[var(--text-muted)] tabular-nums">
            spd {fmtPrice(ask - bid)}
          </span>
        )}
        {/* Indicator timestamp — right-aligned, tells user when bars/signals were computed */}
        {displayTime && (
          <span className="ml-auto font-data text-[0.5rem] text-[var(--text-muted)] opacity-70">
            as of {displayTime}
          </span>
        )}
      </div>

      {/* Bar H / L / Vol / VWAP — small, at bottom */}
      <div className="space-y-1">
        <div className="flex items-center gap-2.5 font-data text-[0.5rem] text-[var(--text-muted)]">
          <span><span className="text-[var(--green)]">H</span>&nbsp;{isEmpty ? "—" : fmtPrice(bar.high)}</span>
          <span><span className="text-[var(--red)]">L</span>&nbsp;{isEmpty ? "—" : fmtPrice(bar.low)}</span>
          <span>Vol&nbsp;{isEmpty ? "—" : fmtCompact(bar.volume)}</span>
          {indicators?.vwap != null && (
            <span>VWAP&nbsp;{fmtPrice(indicators.vwap)}</span>
          )}
        </div>
        <RangeBar
          label="Bar"
          ratio={barRatio}
          lo={isEmpty ? "—" : fmtPrice(bar.low)}
          hi={isEmpty ? "—" : fmtPrice(bar.high)}
        />
      </div>
    </div>
  );
}
