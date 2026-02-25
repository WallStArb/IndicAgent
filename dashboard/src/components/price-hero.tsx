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
}: {
  ratio: number | null;
  label: string;
  lo: string;
  hi: string;
}) {
  return (
    <div className="flex items-center gap-2">
      <span className="text-[0.5rem] uppercase tracking-wider text-[var(--text-muted)] w-8 shrink-0">
        {label}
      </span>
      <span className="font-data text-[0.5rem] text-[var(--text-muted)] tabular-nums w-12 text-right shrink-0">
        {lo}
      </span>
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
      <span className="font-data text-[0.5rem] text-[var(--text-muted)] tabular-nums w-12 shrink-0">
        {hi}
      </span>
    </div>
  );
}

/** Format a bar timestamp string (ISO or ms epoch) to HH:MM */
function fmtBarTime(ts: string | number | undefined): string {
  if (!ts) return "";
  try {
    const d = typeof ts === "number" ? new Date(ts) : new Date(ts);
    if (isNaN(d.getTime())) return "";
    return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", hour12: false });
  } catch {
    return "";
  }
}

/** Compact price details: bid/ask, bar H/L/Vol/VWAP/time, dual range bars */
export function PriceHero({ data, activeTf }: PriceHeroProps) {
  const { tick, bar, session } = data;
  const indicators = data.indicatorsByTf[activeTf] ?? null;

  const isEmpty = tick.price === 0 || tick.lastUpdate === 0;
  const price = isEmpty ? 0 : tick.price;
  const bid = isEmpty ? 0 : tick.bid;
  const ask = isEmpty ? 0 : tick.ask;

  const barRatio = isEmpty ? null : clampRatio(price, bar.low, bar.high);
  const sessionRatio = isEmpty ? null : clampRatio(price, session.low, session.high);
  const barTime = fmtBarTime(bar.timestamp);

  return (
    <div className="px-3 py-1.5 space-y-1.5">
      {/* Bid / Ask / Spread row */}
      <div className="flex items-center gap-3 font-data text-[0.6rem]">
        <span>
          <span className="text-[var(--text-muted)]">Bid </span>
          <span className="text-[var(--red)] tabular-nums">{isEmpty ? "—" : fmtPrice(bid)}</span>
        </span>
        <span>
          <span className="text-[var(--text-muted)]">Ask </span>
          <span className="text-[var(--green)] tabular-nums">{isEmpty ? "—" : fmtPrice(ask)}</span>
        </span>
        {!isEmpty && bid > 0 && ask > 0 && (
          <span className="text-[var(--text-muted)] tabular-nums">
            spd {fmtPrice(ask - bid)}
          </span>
        )}
      </div>

      {/* Bar H / L / Vol / VWAP / timestamp */}
      <div className="flex items-center gap-2.5 font-data text-[0.55rem] text-[var(--text-muted)] flex-wrap">
        <span>
          <span className="text-[var(--green)]">H</span>&nbsp;{isEmpty ? "—" : fmtPrice(bar.high)}
        </span>
        <span>
          <span className="text-[var(--red)]">L</span>&nbsp;{isEmpty ? "—" : fmtPrice(bar.low)}
        </span>
        <span>Vol&nbsp;{isEmpty ? "—" : fmtCompact(bar.volume)}</span>
        {indicators?.vwap != null && (
          <span>VWAP&nbsp;{fmtPrice(indicators.vwap)}</span>
        )}
        {barTime && (
          <span className="ml-auto opacity-60">{barTime}</span>
        )}
      </div>

      {/* Session change row */}
      {!isEmpty && data.session.open > 0 && (() => {
        const chgOpen = price - data.session.open;
        const chgOpenPct = (chgOpen / data.session.open) * 100;
        const col = chgOpen > 0 ? "text-[var(--green)]" : chgOpen < 0 ? "text-[var(--red)]" : "text-[var(--text-muted)]";
        return (
          <div className="flex items-center gap-1 font-data text-[0.55rem]">
            <span className="text-[var(--text-muted)]">Session</span>
            <span className={`${col} tabular-nums`}>
              {chgOpen >= 0 ? "+" : ""}{chgOpen.toFixed(2)} ({chgOpenPct >= 0 ? "+" : ""}{chgOpenPct.toFixed(2)}%)
            </span>
          </div>
        );
      })()}

      {/* Dual range bars */}
      <div className="space-y-1 pt-0.5">
        <RangeBar
          label="Bar"
          ratio={barRatio}
          lo={isEmpty ? "—" : fmtPrice(bar.low)}
          hi={isEmpty ? "—" : fmtPrice(bar.high)}
        />
        <RangeBar
          label="Sess"
          ratio={sessionRatio}
          lo={isEmpty || session.low === 0 ? "—" : fmtPrice(session.low)}
          hi={isEmpty || session.high === 0 ? "—" : fmtPrice(session.high)}
        />
      </div>
    </div>
  );
}
