"use client";

import { useState, useEffect, useMemo } from "react";
import type { SignalData, SymbolData, NarrativeData } from "@/lib/types";

/** Derive compact intelligence context labels from SymbolData. Returns only truthy items. */
function getIntelCtxTags(data: SymbolData, timeframe: string): string[] {
  const intel = data.intelligenceByTf?.[timeframe];
  const ctx = intel?.context;
  const smc = intel?.smartMoney;
  const ind = data.indicatorsByTf?.[timeframe];
  const tags: string[] = [];

  // Regime (HMM preferred, fallback to trend_regime)
  if (smc?.hmm_regime != null) {
    const label = smc.hmm_regime === 1 ? "TRENDING ↑" : smc.hmm_regime === 2 ? "TRENDING ↓" : "RANGING";
    tags.push(label);
  } else if (ctx?.trend_regime && ctx.trend_regime !== "neutral") {
    tags.push(ctx.trend_regime.replace("_", " ").toUpperCase());
  }

  // ADX (only show if meaningful: > 20)
  if (ind?.adx != null && ind.adx > 20) {
    const di =
      ind.plus_di != null && ind.minus_di != null
        ? ind.plus_di > ind.minus_di ? " ↑" : " ↓"
        : "";
    tags.push(`ADX ${Math.round(ind.adx)}${di}`);
  }

  // Killzone (from SMC tier)
  const inKillzone =
    smc?.in_london_killzone || smc?.in_ny_am_killzone ||
    smc?.in_ny_pm_killzone || smc?.in_asia_killzone;
  if (inKillzone && smc?.killzone_name) {
    tags.push(smc.killzone_name.toUpperCase());
  }

  // AMD phase
  if (smc?.amd_phase) {
    const label =
      smc.amd_phase === "accumulation" ? "ACCUM" :
      smc.amd_phase === "manipulation" ? "MANIP" : "DIST";
    tags.push(label);
  }

  // GARCH vol regime
  if (ctx?.garch_vol_regime != null && ctx.garch_vol_regime >= 2) {
    tags.push("VOL ↑");
  }

  // SMC zone
  if (smc?.in_demand_zone) tags.push("IN DEMAND");
  else if (smc?.in_supply_zone) tags.push("IN SUPPLY");

  return tags;
}
import { fmtPrice, fmtTimeHMS, fmtLagSeconds } from "@/lib/format";
import { DrillPanel } from "@/components/drill-panel";
import { X, Brain } from "lucide-react";

interface SignalCardProps {
  symbol: string;
  displayName: string;
  signal: SignalData;
  data: SymbolData;
  assetClass: string;
  narrative: NarrativeData | null;
  onExpand?: () => void;
}

// Returns absolute label, relative label, and whether the signal is stale (>1h old).
// Uses a 1-second tick so absolute correctly updates at midnight.
function useFormattedTimestamp(ts: string): {
  absolute: string;
  relative: string;
  isStale: boolean;
} {
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, []);

  const tsMs = useMemo(() => {
    const t = new Date(ts).getTime();
    return isNaN(t) ? 0 : t;
  }, [ts]);

  const ageMs = tsMs ? now - tsMs : 0;

  const absolute = useMemo(() => {
    if (!tsMs) return "";
    const d = new Date(tsMs);
    const today = new Date(now);
    const isToday = today.toDateString() === d.toDateString();
    const time = d.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
    return isToday ? time : `${d.getMonth() + 1}/${d.getDate()} ${time}`;
  }, [tsMs, now]);

  const relative = useMemo(() => {
    if (!tsMs) return "";
    const diff = Math.floor(ageMs / 1000);
    if (diff < 60) return `${diff}s ago`;
    if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
    return `${Math.floor(diff / 3600)}h ago`;
  }, [tsMs, ageMs]);

  return { absolute, relative, isStale: ageMs > 3_600_000 };
}

function SignalCard({
  symbol,
  displayName,
  signal,
  data,
  assetClass,
  narrative,
  onExpand,
}: SignalCardProps) {
  const [isExpanded, setIsExpanded] = useState(false);

  const isCisQualified = signal.confidence >= 0.7;
  const isHighConfidence = signal.confidence >= 0.75;
  const { absolute, relative, isStale } = useFormattedTimestamp(signal.timestamp);

  const barCloseTimeStr = useMemo(() => fmtTimeHMS(signal.bar_close_ts), [signal.bar_close_ts]);
  const computedTimeStr = useMemo(() => fmtTimeHMS(signal.signal_computed_at), [signal.signal_computed_at]);
  const lagStr = useMemo(() => fmtLagSeconds(signal.pipeline_lag_s), [signal.pipeline_lag_s]);

  const intelTags = useMemo(
    () => getIntelCtxTags(data, signal.timeframe),
    [data, signal.timeframe]
  );

  const hasT1 = signal.profit_target != null;
  const hasT2 = signal.profit_target_2 != null;
  const narrativeText = narrative?.narrative?.trim();

  return (
    <>
      <div
        onClick={onExpand ?? (() => setIsExpanded(true))}
        className={`relative p-3 rounded-lg border transition-all duration-300 cursor-pointer hover:scale-[1.02] group ${
          isStale ? "opacity-50" : ""
        }`}
        style={{
          background: "var(--surface-card)",
          borderColor: isHighConfidence
            ? "var(--accent-amber-dim)"
            : "var(--border-subtle)",
          boxShadow: isCisQualified
            ? "0 0 12px rgba(78, 214, 200, 0.4)"
            : undefined,
        }}
      >
        {/* Header: symbol + badges left, confidence right; timestamp under left */}
        <div className="flex items-start justify-between mb-1.5">
          <div>
            <div className="flex items-center gap-1.5 flex-wrap">
              <span
                className="text-sm font-semibold"
                style={{ color: "var(--text-primary)" }}
              >
                {displayName}
              </span>
              <span
                className="text-xs px-1.5 py-0.5 rounded leading-none"
                style={{
                  background:
                    signal.direction === "long" ? "var(--green-dim)" : "var(--red-dim)",
                  color: signal.direction === "long" ? "var(--green)" : "var(--red)",
                }}
              >
                {signal.direction.toUpperCase()}
              </span>
              <span className="text-xs" style={{ color: "var(--text-muted)" }}>
                {assetClass} · {signal.timeframe}
              </span>
            </div>
            <div className="mt-0.5 font-data text-xs" style={{ color: "var(--text-muted)" }}>
              {absolute}
              {relative && (
                <> · <span style={{ color: "var(--text-secondary)" }}>{relative}</span></>
              )}
              {/* Price context: bar close / market at signal / entry zone */}
              {(signal.bar_close_ts || signal.bar_close_price != null || signal.market_price_at_signal != null) && (
                <div className="text-[0.65rem] mt-0.5 space-y-0.5 opacity-80 font-data tabular-nums">
                  {/* BAR: time @ price  +lag→  SIG: time @ price */}
                  <div className="flex items-center gap-1 flex-wrap">
                    <span className="opacity-50">BAR</span>
                    {barCloseTimeStr && <span>{barCloseTimeStr}</span>}
                    {signal.bar_close_price != null && (
                      <span style={{ color: "var(--text-secondary)" }}>@ {signal.bar_close_price.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 5 })}</span>
                    )}
                    {computedTimeStr && lagStr && (
                      <>
                        <span className="opacity-40">{lagStr}</span>
                        <span className="opacity-30">→</span>
                      </>
                    )}
                    {computedTimeStr && (
                      <>
                        <span className="opacity-50">SIG</span>
                        <span>{computedTimeStr}</span>
                      </>
                    )}
                    {signal.market_price_at_signal != null && (
                      <span style={{ color: "var(--text-secondary)" }}>@ {signal.market_price_at_signal.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 5 })}</span>
                    )}
                  </div>
                  {/* ZONE: low – high  [✓ in zone / ↑ above] */}
                  {signal.entry_zone_low != null && signal.entry_zone_high != null && (
                    <div className="flex items-center gap-1">
                      <span className="opacity-50">ZONE</span>
                      <span>{signal.entry_zone_low.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 5 })}</span>
                      <span className="opacity-30">–</span>
                      <span>{signal.entry_zone_high.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 5 })}</span>
                      {signal.zone_valid_at_signal != null && (
                        <span style={{ color: signal.zone_valid_at_signal ? "var(--green)" : "#f59e0b", fontWeight: 600 }}>
                          {signal.zone_valid_at_signal ? "✓ in zone" : "↑ above zone"}
                        </span>
                      )}
                    </div>
                  )}
                </div>
              )}
            </div>
          </div>

          <div
            className={`text-xs font-semibold px-2 py-1 rounded shrink-0 ml-2 ${
              isHighConfidence ? "ring-1 ring-[var(--accent-amber)]" : ""
            }`}
            style={{
              background: isHighConfidence
                ? "var(--accent-amber-dim)"
                : isCisQualified
                  ? "var(--accent-cyan-dim)"
                  : "var(--bg-elevated)",
              color: isHighConfidence
                ? "var(--accent-amber)"
                : isCisQualified
                  ? "var(--accent-cyan)"
                  : "var(--text-secondary)",
            }}
          >
            {Math.round(signal.confidence * 100)}%
          </div>
        </div>

        {/* Price strip: Entry/SL on row 1, T1+T2 on row 2 */}
        <div
          className="py-1.5 border-t border-b text-xs font-data tabular-nums space-y-0.5"
          style={{ borderColor: "var(--border-subtle)" }}
        >
          <div className="flex items-center gap-3">
            <span style={{ color: "var(--text-muted)" }}>
              Entry{" "}
              <span style={{ color: "var(--text-primary)" }}>
                {fmtPrice(signal.entry_price)}
              </span>
            </span>
            <span style={{ color: "var(--border-subtle)" }}>|</span>
            <span style={{ color: "var(--text-muted)" }}>
              SL{" "}
              <span style={{ color: "var(--red)" }}>
                {fmtPrice(signal.stop_loss)}
              </span>
            </span>
          </div>

          {hasT1 && (
            <div className="flex items-center gap-3">
              <span style={{ color: "var(--text-muted)" }}>
                T1{" "}
                <span style={{ color: "var(--green)" }}>
                  {fmtPrice(signal.profit_target!)}
                </span>
                {signal.rr_t1 != null && (
                  <span
                    className="ml-1 px-1 py-px rounded"
                    style={{
                      background: "var(--bg-elevated)",
                      color: "var(--text-muted)",
                      fontSize: "0.65rem",
                    }}
                  >
                    {signal.rr_t1.toFixed(1)}R
                  </span>
                )}
              </span>
              {hasT2 && (
                <>
                  <span style={{ color: "var(--border-subtle)" }}>·</span>
                  <span style={{ color: "var(--text-muted)" }}>
                    T2{" "}
                    <span style={{ color: "var(--green)" }}>
                      {fmtPrice(signal.profit_target_2!)}
                    </span>
                    {signal.rr_t2 != null && (
                      <span
                        className="ml-1 px-1 py-px rounded"
                        style={{
                          background: "var(--bg-elevated)",
                          color: "var(--text-muted)",
                          fontSize: "0.65rem",
                        }}
                      >
                        {signal.rr_t2.toFixed(1)}R
                      </span>
                    )}
                  </span>
                </>
              )}
            </div>
          )}
        </div>

        {/* Intelligence context row */}
        {intelTags.length > 0 && (
          <div
            className="py-1 border-b flex flex-wrap gap-1"
            style={{ borderColor: "var(--border-subtle)" }}
          >
            {intelTags.map((tag) => (
              <span
                key={tag}
                className="text-[0.6rem] px-1.5 py-px rounded font-medium leading-none"
                style={{
                  background: "var(--bg-elevated)",
                  color:
                    tag.includes("DEMAND") || tag.includes("↑")
                      ? "var(--green)"
                      : tag.includes("SUPPLY") || tag.includes("↓")
                        ? "var(--red)"
                        : tag === "MANIP"
                          ? "#f59e0b"
                          : "var(--text-secondary)",
                }}
              >
                {tag}
              </span>
            ))}
          </div>
        )}

        {/* Footer: signal type tags + narrative */}
        <div className="pt-1.5">
          <div className="flex flex-wrap gap-1 items-center">
            <span className="text-xs" style={{ color: "var(--text-muted)" }}>
              {signal.signal_type}
            </span>
            <span
              className="text-xs px-1.5 py-px rounded"
              style={{ background: "var(--bg-elevated)", color: "var(--text-secondary)" }}
            >
              {signal.setup_plugin}
            </span>
            {signal.entry_type && (
              <span
                className="text-xs px-1.5 py-px rounded"
                style={{ background: "var(--bg-elevated)", color: "var(--text-muted)" }}
              >
                {signal.entry_type}
              </span>
            )}
          </div>

          {narrativeText && (
            <div className="flex gap-1 mt-1">
              <Brain size={10} className="mt-0.5 shrink-0" style={{ color: "var(--accent-cyan)" }} />
              <p
                className="text-xs italic line-clamp-2 leading-snug"
                style={{ color: "var(--text-muted)" }}
              >
                {narrativeText}
              </p>
            </div>
          )}
        </div>

        {isHighConfidence && (
          <div
            className="absolute inset-0 rounded-lg pointer-events-none"
            style={{
              border: "1px solid var(--accent-amber)",
              boxShadow: "0 0 8px rgba(212, 168, 75, 0.2)",
            }}
          />
        )}
      </div>

      {isExpanded && !onExpand && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center p-4"
          style={{ background: "rgba(10, 14, 20, 0.9)" }}
          onClick={() => setIsExpanded(false)}
        >
          <div
            className="relative w-full max-w-4xl max-h-[90vh] overflow-hidden rounded-lg"
            style={{ background: "var(--bg-surface)", border: "1px solid var(--border-subtle)" }}
            onClick={(e) => e.stopPropagation()}
          >
            <button
              onClick={() => setIsExpanded(false)}
              className="absolute top-3 right-3 p-1.5 rounded-md hover:bg-[var(--bg-hover)] transition-colors"
              style={{ color: "var(--text-muted)" }}
            >
              <X size={20} />
            </button>
            <div className="h-full overflow-y-auto pt-4 pb-2">
              <DrillPanel
                symbol={symbol}
                timeframe={signal.timeframe}
                data={data}
                signal={signal}
                onClose={() => setIsExpanded(false)}
              />
            </div>
          </div>
        </div>
      )}
    </>
  );
}

export default SignalCard;
