// dashboard/src/components/watchlist-rail.tsx
"use client";

import { useState } from "react";
import { fmtPrice } from "@/lib/format";
import type { SymbolData } from "@/lib/types";

const TF_STALENESS_MS: Record<string, number> = {
  "1m":  10 * 60_000,
  "5m":  50 * 60_000,
  "15m": 150 * 60_000,
  "1h":  10 * 3_600_000,
  "4h":  40 * 3_600_000,
  "1d":  10 * 86_400_000,
};

function getRegimeAccent(data: SymbolData, tf: string): string {
  const regime = data.intelligenceByTf[tf]?.context?.trend_regime;
  if (!regime) return "var(--border-default)";
  if (regime === "strong_up")   return "var(--green)";
  if (regime === "weak_up")     return "#00dc8266";
  if (regime === "strong_down") return "var(--red)";
  if (regime === "weak_down")   return "#ff475766";
  return "var(--border-bright)"; // neutral
}

function getActiveSignal(data: SymbolData, tf: string) {
  const signal = data.signalsByTf[tf] ?? null;
  if (!signal) return null;
  const ts = new Date(signal.timestamp).getTime();
  const cutoff = TF_STALENESS_MS[tf] ?? 3_600_000;
  return isNaN(ts) || Date.now() - ts > cutoff ? null : signal;
}

interface WatchlistRailProps {
  symbols: string[];
  symbolData: Record<string, SymbolData>;
  selectedSymbol: string | null;
  globalTf: string;
  onSelect: (symbol: string) => void;
}

export function WatchlistRail({
  symbols,
  symbolData,
  selectedSymbol,
  globalTf,
  onSelect,
}: WatchlistRailProps) {
  const [collapsed, setCollapsed] = useState(false);

  return (
    <aside
      className="shrink-0 flex flex-col overflow-hidden border-r border-[var(--border-subtle)] transition-all duration-200"
      style={{
        width: collapsed ? "36px" : "120px",
        background: "var(--bg-surface)",
      }}
    >
      {/* Rail header / toggle */}
      <button
        onClick={() => setCollapsed((c) => !c)}
        className="px-2 py-1.5 border-b border-[var(--border-subtle)] shrink-0 flex items-center w-full transition-colors hover:bg-[var(--bg-elevated)]"
        style={{ background: "var(--bg-elevated)" }}
        title={collapsed ? "Expand watchlist" : "Collapse watchlist"}
      >
        <span
          className="text-[0.6rem] text-[var(--text-muted)] leading-none transition-transform duration-200"
          style={{ transform: collapsed ? "rotate(180deg)" : "rotate(0deg)" }}
        >
          ‹
        </span>
        {!collapsed && (
          <span className="text-[0.55rem] font-semibold uppercase tracking-widest text-[var(--text-muted)] ml-1.5">
            {symbols.length}
          </span>
        )}
      </button>

      {/* Instrument rows */}
      <div className="flex-1 overflow-y-auto overflow-x-hidden">
        {symbols.map((sym) => {
          const data = symbolData[sym];
          return (
            <WatchlistRow
              key={sym}
              sym={sym}
              data={data ?? null}
              globalTf={globalTf}
              isSelected={sym === selectedSymbol}
              collapsed={collapsed}
              onSelect={onSelect}
            />
          );
        })}
      </div>
    </aside>
  );
}

function WatchlistRow({
  sym,
  data,
  globalTf,
  isSelected,
  collapsed,
  onSelect,
}: {
  sym: string;
  data: SymbolData | null;
  globalTf: string;
  isSelected: boolean;
  collapsed: boolean;
  onSelect: (s: string) => void;
}) {
  const regimeColor = data ? getRegimeAccent(data, globalTf) : "var(--border-default)";
  const activeSignal = data ? getActiveSignal(data, globalTf) : null;

  // Also scan 1m for signals since that's where they currently fire
  const signal1m = data && globalTf !== "1m" ? getActiveSignal(data, "1m") : null;
  const bestSignal = activeSignal ?? signal1m;

  const isLong = bestSignal?.direction === "long";
  const price = data?.tick?.price ?? 0;
  const tickFlash = data?.tickFlash ?? null;

  const hasSignal = bestSignal !== null && !bestSignal.resolved;
  const borderColor = hasSignal ? (isLong ? "var(--green)" : "var(--red)") : regimeColor;

  return (
    <button
      onClick={() => onSelect(sym)}
      className="w-full flex items-center gap-1.5 px-2 py-1.5 text-left transition-colors"
      style={{
        borderLeft: `3px solid ${borderColor}`,
        backgroundColor: isSelected
          ? "var(--bg-elevated)"
          : hasSignal
            ? isLong
              ? "rgba(0,220,130,0.04)"
              : "rgba(255,71,87,0.04)"
            : "transparent",
        borderBottom: "1px solid var(--border-subtle)",
      }}
    >
      {/* Symbol — always visible */}
      <span
        className="text-[0.7rem] font-bold leading-none min-w-0"
        style={{
          color: isSelected ? "var(--text-primary)" : "var(--text-secondary)",
          flex: collapsed ? "none" : "1",
        }}
      >
        {sym}
      </span>

      {/* Price + signal pill — hidden when collapsed */}
      {!collapsed && (
        <>
          {price > 0 && (
            <span
              key={tickFlash ?? "base"}
              className={`font-data text-[0.58rem] font-semibold shrink-0 tabular-nums ${
                tickFlash === "up"
                  ? "price-flash-up"
                  : tickFlash === "down"
                    ? "price-flash-down"
                    : ""
              }`}
              style={{ color: "var(--text-primary)" }}
            >
              {fmtPrice(price)}
            </span>
          )}
          {hasSignal && (
            <span
              className="shrink-0 text-[0.48rem] font-bold uppercase tracking-wider px-1 py-0.5 rounded leading-none"
              style={{
                backgroundColor: isLong ? "var(--green-dim)" : "var(--red-dim)",
                color: isLong ? "var(--green)" : "var(--red)",
              }}
            >
              {isLong ? "L" : "S"}
            </span>
          )}
        </>
      )}
    </button>
  );
}
