// dashboard/src/components/signal-alert-strip.tsx
"use client";

import { useMemo } from "react";
import { fmtPrice, fmtNum } from "@/lib/format";
import { isHeroTier } from "@/lib/signal-tier";
import type { SymbolData, SignalData } from "@/lib/types";
import { TrendingUp, TrendingDown, Zap } from "lucide-react";

const TF_STALENESS_MS: Record<string, number> = {
  "1m":  10 * 60_000,
  "5m":  50 * 60_000,
  "15m": 150 * 60_000,
  "1h":  10 * 3_600_000,
  "4h":  40 * 3_600_000,
  "1d":  10 * 86_400_000,
};

const TIMEFRAMES = ["1m", "5m", "15m", "1h", "4h", "1d"];

interface ActiveSignalInfo {
  symbol: string;
  signal: SignalData;
  tf: string;
}

interface SignalAlertStripProps {
  symbolData: Record<string, SymbolData>;
  symbols: string[];
  onSelectSymbol: (symbol: string) => void;
}

export function SignalAlertStrip({
  symbolData,
  symbols,
  onSelectSymbol,
}: SignalAlertStripProps) {
  const activeSignals = useMemo<ActiveSignalInfo[]>(() => {
    const found: ActiveSignalInfo[] = [];
    for (const sym of symbols) {
      const data = symbolData[sym];
      if (!data) continue;
      for (const tf of TIMEFRAMES) {
        const signal = data.signalsByTf?.[tf];
        if (!signal || signal.resolved) continue;
        if (!isHeroTier(signal.confidence, signal.cis_score)) continue;
        const ts = new Date(signal.timestamp).getTime();
        const cutoff = TF_STALENESS_MS[tf] ?? 3_600_000;
        if (isNaN(ts) || Date.now() - ts > cutoff) continue;
        found.push({ symbol: sym, signal, tf });
      }
    }
    // Deduplicate: one entry per symbol (highest confidence)
    const bySymbol = new Map<string, ActiveSignalInfo>();
    for (const item of found) {
      const existing = bySymbol.get(item.symbol);
      if (!existing || item.signal.confidence > existing.signal.confidence) {
        bySymbol.set(item.symbol, item);
      }
    }
    return [...bySymbol.values()].sort((a, b) => b.signal.confidence - a.signal.confidence);
  }, [symbolData, symbols]);

  if (activeSignals.length === 0) return null;

  return (
    <div
      className="shrink-0 flex items-center gap-0 border-b border-[var(--border-default)] overflow-hidden"
      style={{
        background: "linear-gradient(90deg, rgba(10,14,20,0.95) 0%, rgba(20,26,38,0.85) 100%)",
        minHeight: "28px",
      }}
    >
      {/* Label */}
      <div
        className="shrink-0 flex items-center gap-1.5 px-2.5 py-1 border-r border-[var(--border-default)]"
        style={{ background: "rgba(255,179,71,0.08)" }}
      >
        <Zap size={9} className="text-[var(--amber)]" strokeWidth={2.5} />
        <span className="text-[0.55rem] font-bold uppercase tracking-widest text-[var(--amber)]">
          Signals
        </span>
      </div>

      {/* Signal pills — horizontal scroll */}
      <div className="flex items-center gap-1 px-2 overflow-x-auto flex-1" style={{ scrollbarWidth: "none" }}>
        {activeSignals.map(({ symbol, signal, tf }) => (
          <SignalPill
            key={`${symbol}-${tf}`}
            symbol={symbol}
            signal={signal}
            tf={tf}
            onClick={() => onSelectSymbol(symbol)}
          />
        ))}
      </div>
    </div>
  );
}

function SignalPill({
  symbol,
  signal,
  tf,
  onClick,
}: {
  symbol: string;
  signal: SignalData;
  tf: string;
  onClick: () => void;
}) {
  const isLong = signal.direction === "long";
  const color = isLong ? "var(--green)" : "var(--red)";
  const dimColor = isLong ? "var(--green-dim)" : "var(--red-dim)";
  const Icon = isLong ? TrendingUp : TrendingDown;

  return (
    <button
      onClick={onClick}
      className="shrink-0 flex items-center gap-1 px-2 py-0.5 rounded transition-opacity hover:opacity-80"
      style={{
        background: dimColor,
        border: `1px solid ${isLong ? "#00dc8244" : "#ff475744"}`,
      }}
    >
      <Icon size={9} style={{ color }} strokeWidth={2.5} />
      <span
        className="text-[0.62rem] font-bold"
        style={{ color }}
      >
        {symbol}
      </span>
      <span className="text-[0.55rem] font-data text-[var(--text-secondary)]">
        {fmtNum(signal.confidence * 100, 0)}%
      </span>
      {signal.entry_price > 0 && (
        <span className="text-[0.52rem] font-data text-[var(--text-muted)]">
          @ {fmtPrice(signal.entry_price)}
        </span>
      )}
      <span
        className="text-[0.45rem] font-semibold uppercase px-0.5 rounded"
        style={{
          color: "var(--text-muted)",
          background: "rgba(255,255,255,0.05)",
        }}
      >
        {tf}
      </span>
    </button>
  );
}
