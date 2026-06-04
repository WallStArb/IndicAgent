// dashboard/src/components/signals/signal-ledger.tsx
"use client";

import { useState, useEffect, useRef, useMemo } from "react";
import { useVirtualizer } from "@tanstack/react-virtual";
import { getApiBase, fetchJson } from "@/lib/api";
import type { LedgerSignal, SignalTier } from "@/lib/types";
import { FilterState } from "./filter-bar";
import { tierColor, tierOpacity, CIS_SCORE_THRESHOLD } from "@/lib/signal-tier";
import { fmtNum, fmtTimeHMS } from "@/lib/format";
import { TrendingUp, TrendingDown } from "lucide-react";
import { SignalDetailPanel } from "./signal-detail-panel";

// ── Helpers ──
const REGIME_DOT_COLORS: Record<number, string> = {
  0: "var(--green)",
  1: "var(--amber)",
  2: "var(--red)",
};

const EXIT_COLORS: Record<string, string> = {
  stop_loss: "var(--red)",
  ttl_expired: "var(--text-muted)",
  target_1: "rgba(0,220,130,0.7)",
  target_2: "var(--green)",
  target_3: "var(--cyan, #06b6d4)",
  condition_expired: "var(--text-muted)",
};

const STATUS_COLORS: Record<string, string> = {
  pending: "var(--text-muted)",
  active: "var(--cyan, #06b6d4)",
  regime_suppressed: "var(--red)",
  expired: "var(--text-muted)",
};

function ExitCell({ signal }: { signal: LedgerSignal }) {
  const live = signal.status === "pending" || signal.status === "active";
  if (live) {
    return (
      <span className="text-[0.5rem] font-semibold px-1 py-0 rounded"
        style={{
          color: STATUS_COLORS[signal.status] ?? "var(--text-muted)",
          border: `1px solid ${STATUS_COLORS[signal.status] ?? "var(--border-subtle)"}`,
          backgroundColor: "rgba(0,0,0,0.2)",
        }}>
        {signal.status}
      </span>
    );
  }
  const reason = signal.exit_reason ?? signal.status;
  const label = reason === "stop_loss" ? "SL"
    : reason === "ttl_expired" ? "TTL"
    : reason === "target_1" ? "T1"
    : reason === "target_2" ? "T2"
    : reason === "target_3" ? "T3"
    : reason?.toUpperCase().slice(0, 4) ?? "—";
  return (
    <span className="text-[0.5rem] font-semibold px-1 py-0 rounded"
      style={{
        color: EXIT_COLORS[reason] ?? "var(--text-muted)",
        border: `1px solid ${EXIT_COLORS[reason] ?? "var(--border-subtle)"}`,
        backgroundColor: "rgba(0,0,0,0.2)",
      }}>
      {label}
    </span>
  );
}

function AgeCapCell({ signal }: { signal: LedgerSignal }) {
  const live = signal.status === "pending" || signal.status === "active";
  if (live) {
    if (signal.bars_in_trade == null || signal.ttl_bars == null)
      return <span className="text-[var(--text-muted)]">-</span>;
    const ratio = signal.bars_in_trade / signal.ttl_bars;
    const color = ratio < 0.5 ? "var(--text-secondary)"
      : ratio < 0.8 ? "var(--amber)"
      : "var(--red)";
    return <span className="text-[0.6rem] font-data" style={{ color }}>{signal.bars_in_trade}b</span>;
  }
  if (signal.mfe != null && signal.mfe > 0 && signal.pnl_r != null) {
    const cap = signal.pnl_r / signal.mfe;
    const color = cap >= 0.7 ? "var(--green)" : cap >= 0.4 ? "var(--amber)" : "var(--red)";
    return <span className="text-[0.6rem] font-data" style={{ color }}>{fmtNum(cap, 2)}</span>;
  }
  return <span className="text-[var(--text-muted)]">-</span>;
}

// ── Row component ──
function TierDot({ tier }: { tier: SignalTier }) {
  return (
    <span
      className="inline-block w-2 h-2 rounded-full shrink-0"
      style={{ backgroundColor: tierColor(tier) }}
      title={tier}
    />
  );
}

function OutcomeCell({ outcome }: { outcome: string | null }) {
  if (!outcome) return <span className="text-[var(--text-muted)]">-</span>;
  const isWin = ["target_1", "target_1_2", "target_full"].includes(outcome);
  return (
    <span
      className="text-[0.58rem] font-semibold px-1 py-0 rounded"
      style={{
        color: isWin ? "var(--green)" : "var(--red)",
        backgroundColor: isWin ? "rgba(0,220,130,0.1)" : "rgba(255,71,87,0.1)",
      }}
    >
      {outcome.replace(/_/g, " ")}
    </span>
  );
}

function LedgerRow({
  signal,
  isSelected,
  onClick,
}: {
  signal: LedgerSignal;
  isSelected: boolean;
  onClick: () => void;
}) {
  const tier = signal.signal_tier;
  const opacity = tierOpacity(tier);
  const isLong = signal.direction === 1;
  const timeStr = fmtTimeHMS(signal.computed_at ?? undefined);
  const pnlColor =
    signal.pnl_r != null
      ? signal.pnl_r >= 0
        ? "var(--green)"
        : "var(--red)"
      : "var(--text-muted)";
  const cisStr =
    signal.cis_score != null
      ? (signal.cis_score >= 0 ? "+" : "") + fmtNum(signal.cis_score, 2)
      : "-";

  return (
    <div
      onClick={onClick}
      className="flex items-center gap-0 cursor-pointer hover:bg-[var(--bg-elevated)] transition-colors border-b border-[var(--border-subtle)]"
      style={{
        opacity,
        borderLeft: tier === "hero" ? "2px solid var(--blue)" : "2px solid transparent",
        backgroundColor: isSelected ? "var(--bg-elevated)" : undefined,
        height: "28px",
      }}
    >
      <span className="w-[90px] shrink-0 px-2 text-[0.6rem] font-data text-[var(--text-muted)]">{timeStr ?? "-"}</span>
      <span className="w-[70px] shrink-0 px-1 text-[0.65rem] font-bold font-data text-[var(--text-secondary)]">{signal.symbol}</span>
      <span className="w-[36px] shrink-0 px-1 text-[0.6rem] font-data text-[var(--text-muted)]">{signal.timeframe}</span>
      <span className="w-[22px] shrink-0 px-1 flex items-center justify-center">
        <span className="inline-block w-2 h-2 rounded-full"
          style={{ backgroundColor: signal.hmm_regime_at_fire != null
            ? (REGIME_DOT_COLORS[signal.hmm_regime_at_fire] ?? "var(--text-muted)")
            : "var(--bg-elevated)" }}
          title={signal.hmm_regime_at_fire != null ? (["Trend","Range","Vol"][signal.hmm_regime_at_fire] ?? "") : "unknown"} />
      </span>
      <span className={`w-[130px] shrink-0 px-1 text-[0.62rem] font-data truncate ${tier === "candidate" ? "italic" : ""}`}
        style={{ color: "var(--text-secondary)" }}>
        {signal.setup_plugin.replace(/^(trad_|ind_|smc_)/, "")}
      </span>
      <span className="w-[28px] shrink-0 px-1 flex items-center justify-center">
        {isLong ? <TrendingUp size={10} style={{ color: "var(--green)" }} /> : <TrendingDown size={10} style={{ color: "var(--red)" }} />}
      </span>
      <span className="w-[48px] shrink-0 px-1 text-right text-[0.62rem] font-data text-[var(--text-secondary)]">
        {signal.r_ratio != null ? `${fmtNum(signal.r_ratio, 1)}x` : "-"}
      </span>
      <span className="w-[22px] shrink-0 px-1 flex items-center justify-center"><TierDot tier={tier} /></span>
      <span className="w-[56px] shrink-0 px-1 text-right text-[0.62rem] font-data"
        style={{ color: signal.cis_score != null ? signal.cis_score >= 0 ? "var(--green)" : "var(--red)" : "var(--text-muted)" }}>
        {cisStr}
      </span>
      <span className="w-[64px] shrink-0 px-1 flex items-center"><ExitCell signal={signal} /></span>
      <span className="w-[96px] shrink-0 px-1"><OutcomeCell outcome={signal.outcome} /></span>
      <span className="w-[56px] shrink-0 px-1 text-right text-[0.62rem] font-data" style={{ color: pnlColor }}>
        {signal.pnl_r != null
          ? (signal.outcome === "never_activated" ? "~" : "") + (signal.pnl_r >= 0 ? "+" : "") + fmtNum(signal.pnl_r, 1) + "R"
          : "-"}
      </span>
      <span className="w-[52px] shrink-0 px-1 text-right"><AgeCapCell signal={signal} /></span>
    </div>
  );
}

// ── Header row ──
function LedgerHeader() {
  return (
    <div
      className="flex items-center gap-0 border-b border-[var(--border-default)] sticky top-0 z-10"
      style={{ background: "var(--bg-surface)", height: "28px" }}
    >
      {(
        [
          { label: "Time", w: 90 },
          { label: "Symbol", w: 70 },
          { label: "TF", w: 36 },
          { label: "●", w: 22 },
          { label: "Setup", w: 130 },
          { label: "Dir", w: 28 },
          { label: "R:R", w: 48, right: true },
          { label: "Tier", w: 22 },
          { label: "CIS", w: 56, right: true },
          { label: "Exit", w: 64 },
          { label: "Outcome", w: 96 },
          { label: "PnL R", w: 56, right: true },
          { label: "Age/Cap", w: 52, right: true },
        ] as { label: string; w: number; right?: boolean }[]
      ).map(({ label, w, right }) => (
        <span
          key={label}
          className={`shrink-0 px-1 text-[0.52rem] font-semibold uppercase tracking-widest text-[var(--text-muted)] ${right ? "text-right" : ""}`}
          style={{ width: `${w}px` }}
        >
          {label}
        </span>
      ))}
    </div>
  );
}

// ── Main SignalLedger ──
function buildQueryParams(filters: FilterState): string {
  const params = new URLSearchParams();
  params.set("limit", "500");

  // Single-tier: pass directly. Multi-tier or empty: fetch all and client-filter.
  if (filters.tier.length === 1) {
    params.set("tier", filters.tier[0]);
  } else {
    params.set("tier", "all");
  }

  // Server-side filters (single values only — multi handled client-side)
  if (filters.symbol.length === 1) params.set("symbol", filters.symbol[0]);
  if (filters.timeframe.length === 1) params.set("timeframe", filters.timeframe[0]);

  // Confidence floor and date range — sent for future API support; filtered client-side for now
  if (filters.confidence_min > 0) params.set("confidence_min", String(filters.confidence_min));
  if (filters.date_from) params.set("date_from", filters.date_from);
  if (filters.date_to) params.set("date_to", filters.date_to);

  return params.toString();
}

export function SignalLedger({ filters }: { filters: FilterState }) {
  const [signals, setSignals] = useState<LedgerSignal[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const parentRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const qs = buildQueryParams(filters);

    fetchJson<{ signals?: LedgerSignal[] }>(`${getApiBase()}/api/signals/recent?${qs}`)
      .then((d) => {
        const seen = new Set<string>();
        setSignals(
          (d.signals ?? []).filter((s) => {
            if (seen.has(s.signal_id)) return false;
            seen.add(s.signal_id);
            return true;
          }),
        );
      })
      .catch((err) => {
        console.error("Failed to fetch signals:", err);
        setSignals([]);
      });
  }, [filters]);

  // Client-side filtering for multi-select cases
  const filtered = useMemo(() => {
    return signals.filter((s) => {
      if (filters.tier.length > 0 && !filters.tier.includes(s.signal_tier))
        return false;
      if (
        filters.timeframe.length > 0 &&
        !filters.timeframe.includes(s.timeframe)
      )
        return false;
      if (filters.symbol.length > 0 && !filters.symbol.includes(s.symbol))
        return false;
      if (filters.setup_plugin.length > 0 && !filters.setup_plugin.includes(s.setup_plugin))
        return false;
      if (filters.status.length > 0 && !filters.status.includes(s.status))
        return false;
      if (
        filters.regime.length > 0 &&
        (s.hmm_regime_at_fire == null || !filters.regime.includes(s.hmm_regime_at_fire))
      )
        return false;

      if (s.confidence === null) {
        if (filters.confidence_min > 0 || filters.confidence_max < 1) return false;
      } else {
        if (filters.confidence_min > 0 && s.confidence < filters.confidence_min) return false;
        if (filters.confidence_max < 1 && s.confidence > filters.confidence_max) return false;
      }

      // CIS filter - only active when CIS score exists and meets threshold
      if (
        filters.cis_filter === "cis_only" &&
        (s.cis_score == null || Math.abs(s.cis_score) <= CIS_SCORE_THRESHOLD)
      )
        return false;

      // Fallback filter - only active when CIS score exists and exceeds threshold
      if (
        filters.cis_filter === "fallback_only" &&
        (s.cis_score != null && Math.abs(s.cis_score) > CIS_SCORE_THRESHOLD)
      )
        return false;

      return true;
    });
  }, [signals, filters]);

  const rowVirtualizer = useVirtualizer({
    count: filtered.length,
    getScrollElement: () => parentRef.current,
    estimateSize: () => 28,
    overscan: 20,
  });

  return (
    <div className="flex rounded overflow-hidden" style={{ border: "1px solid var(--border-subtle)", background: "var(--bg-surface)", height: "600px" }}>
      {/* Table */}
      <div className="flex flex-col flex-1 min-w-0">
        <LedgerHeader />
        <div ref={parentRef} className="flex-1 overflow-y-auto overflow-x-auto" style={{ position: "relative" }}>
          <div style={{ height: `${rowVirtualizer.getTotalSize()}px`, position: "relative" }}>
            {rowVirtualizer.getVirtualItems().map((vi) => {
              const sig = filtered[vi.index];
              return (
                <div
                  key={sig.signal_id}
                  style={{ position: "absolute", top: vi.start, width: "100%" }}
                >
                  <LedgerRow
                    signal={sig}
                    isSelected={sig.signal_id === selectedId}
                    onClick={() =>
                      setSelectedId(
                        sig.signal_id === selectedId ? null : sig.signal_id,
                      )
                    }
                  />
                </div>
              );
            })}
          </div>
        </div>
        <div className="px-3 py-1 border-t border-[var(--border-subtle)] text-[0.55rem] text-[var(--text-muted)]">
          {filtered.length} signals
        </div>
      </div>
      {/* Detail panel */}
      {selectedId && (
        <SignalDetailPanel
          signalId={selectedId}
          onClose={() => setSelectedId(null)}
        />
      )}
    </div>
  );
}
