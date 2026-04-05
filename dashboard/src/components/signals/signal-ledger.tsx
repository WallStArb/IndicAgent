// dashboard/src/components/signals/signal-ledger.tsx
"use client";

import { useState, useEffect, useRef, useMemo } from "react";
import { useVirtualizer } from "@tanstack/react-virtual";
import { getApiBase, fetchJson } from "@/lib/api";
import type { LedgerSignal, SignalTier } from "@/lib/types";
import { FilterState } from "./filter-bar";
import { tierColor, tierOpacity } from "@/lib/signal-tier";
import { fmtNum, fmtTimeHMS } from "@/lib/format";
import { TrendingUp, TrendingDown, X } from "lucide-react";

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
        borderLeft:
          tier === "hero"
            ? "2px solid var(--blue)"
            : "2px solid transparent",
        backgroundColor: isSelected ? "var(--bg-elevated)" : undefined,
        height: "28px",
      }}
    >
      {/* Time */}
      <span className="w-[90px] shrink-0 px-2 text-[0.6rem] font-data text-[var(--text-muted)]">
        {timeStr ?? "-"}
      </span>
      {/* Symbol */}
      <span className="w-[70px] shrink-0 px-1 text-[0.65rem] font-bold font-data text-[var(--text-secondary)]">
        {signal.symbol}
      </span>
      {/* TF */}
      <span className="w-[36px] shrink-0 px-1 text-[0.6rem] font-data text-[var(--text-muted)]">
        {signal.timeframe}
      </span>
      {/* Setup */}
      <span
        className={`w-[130px] shrink-0 px-1 text-[0.62rem] font-data truncate ${tier === "candidate" ? "italic" : ""}`}
        style={{ color: "var(--text-secondary)" }}
      >
        {signal.setup_plugin.replace(/^(trad_|ind_|smc_)/, "")}
      </span>
      {/* Dir */}
      <span className="w-[28px] shrink-0 px-1 flex items-center justify-center">
        {isLong ? (
          <TrendingUp size={10} style={{ color: "var(--green)" }} />
        ) : (
          <TrendingDown size={10} style={{ color: "var(--red)" }} />
        )}
      </span>
      {/* Tier dot */}
      <span className="w-[22px] shrink-0 px-1 flex items-center justify-center">
        <TierDot tier={tier} />
      </span>
      {/* Confidence */}
      <span
        className="w-[56px] shrink-0 px-1 text-right text-[0.62rem] font-data"
        style={{
          color:
            (signal.confidence ?? 0) >= 0.4
              ? "var(--text-primary)"
              : "var(--text-muted)",
        }}
      >
        {signal.confidence != null ? fmtNum(signal.confidence, 2) : "-"}
      </span>
      {/* CIS */}
      <span
        className="w-[56px] shrink-0 px-1 text-right text-[0.62rem] font-data"
        style={{
          color:
            signal.cis_score != null
              ? signal.cis_score >= 0
                ? "var(--green)"
                : "var(--red)"
              : "var(--text-muted)",
        }}
      >
        {cisStr}
      </span>
      {/* Status */}
      <span className="w-[76px] shrink-0 px-1 text-[0.58rem] font-data text-[var(--text-muted)] truncate">
        {signal.status}
      </span>
      {/* Outcome */}
      <span className="w-[96px] shrink-0 px-1">
        <OutcomeCell outcome={signal.outcome} />
      </span>
      {/* PnL R */}
      <span
        className="w-[56px] shrink-0 px-1 text-right text-[0.62rem] font-data"
        style={{ color: pnlColor }}
      >
        {signal.pnl_r != null
          ? (signal.outcome === "never_activated" ? "~" : "")
            + (signal.pnl_r >= 0 ? "+" : "")
            + fmtNum(signal.pnl_r, 1) + "R"
          : "-"}
      </span>
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
          { label: "Setup", w: 130 },
          { label: "Dir", w: 28 },
          { label: "Tier", w: 22 },
          { label: "Conf", w: 56, right: true },
          { label: "CIS", w: 56, right: true },
          { label: "Status", w: 76 },
          { label: "Outcome", w: 96 },
          { label: "PnL R", w: 56, right: true },
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

// ── Detail panel ──
function SignalDetailPanel({
  signalId,
  onClose,
}: {
  signalId: string;
  onClose: () => void;
}) {
  const [detail, setDetail] = useState<Record<string, unknown> | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const fetchSignalDetail = async () => {
      setLoading(true);
      try {
        const d = await fetchJson<Record<string, unknown>>(`${getApiBase()}/api/signals/detail/${signalId}`);
        setDetail(d);
      } catch (err) {
        console.error("Failed to fetch signal detail:", err);
      } finally {
        setLoading(false);
      }
    };

    fetchSignalDetail();
  }, [signalId]);

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [onClose]);

  return (
    <div
      className="flex flex-col border-l border-[var(--border-subtle)] overflow-y-auto shrink-0"
      style={{ width: "320px", background: "var(--bg-surface)" }}
    >
      <div className="flex items-center justify-between px-3 py-2 border-b border-[var(--border-subtle)]">
        <span className="text-[0.62rem] font-bold uppercase tracking-widest text-[var(--text-secondary)]">
          Signal Detail
        </span>
        <button
          onClick={onClose}
          aria-label="Close signal detail panel"
          className="text-[var(--text-muted)] hover:text-[var(--text-primary)]"
        >
          <X size={14} />
        </button>
      </div>
      {loading && (
        <div className="p-4 text-[0.62rem] text-[var(--text-muted)] italic">
          Loading...
        </div>
      )}
      {!loading && detail && (
        <div className="p-3 flex flex-col gap-2 text-[0.65rem]">
          <div className="grid grid-cols-2 gap-1">
            {(
              [
                ["Symbol", detail.symbol],
                ["TF", detail.timeframe],
                [
                  "Setup",
                  typeof detail.setup_plugin === "string"
                    ? detail.setup_plugin.replace(/^(trad_|ind_|smc_)/, "")
                    : detail.setup_plugin,
                ],
                [
                  "Direction",
                  detail.direction === 1 ? "LONG ▲" : "SHORT ▼",
                ],
                [
                  "Tier",
                  typeof detail.signal_tier === "string"
                    ? detail.signal_tier.toUpperCase()
                    : detail.signal_tier,
                ],
                [
                  "Confidence",
                  typeof detail.confidence === "number"
                    ? fmtNum(detail.confidence, 3)
                    : "-",
                ],
                [
                  "CIS Score",
                  detail.cis_score != null
                    ? fmtNum(detail.cis_score as number, 3)
                    : "-",
                ],
                [
                  "Entry",
                  detail.entry_price != null
                    ? fmtNum(detail.entry_price as number, 2)
                    : "-",
                ],
                [
                  "Stop",
                  detail.stop_loss != null
                    ? fmtNum(detail.stop_loss as number, 2)
                    : "-",
                ],
                [
                  "Status",
                  detail.status,
                ],
                [
                  "Outcome",
                  detail.outcome ?? "-",
                ],
                [
                  "PnL R",
                  detail.pnl_r != null
                    ? fmtNum(detail.pnl_r as number, 2) + "R"
                    : "-",
                ],
                [
                  "MAE",
                  detail.mae != null
                    ? fmtNum(detail.mae as number, 2)
                    : "-",
                ],
                [
                  "MFE",
                  detail.mfe != null
                    ? fmtNum(detail.mfe as number, 2)
                    : "-",
                ],
                [
                  "Bars",
                  detail.bars_in_trade != null
                    ? String(detail.bars_in_trade)
                    : "-",
                ],
              ] as [string, unknown][]
            ).map(([k, v]) => (
              <div key={k} className="flex flex-col gap-0.5">
                <span className="text-[0.48rem] uppercase tracking-widest text-[var(--text-muted)]">
                  {k}
                </span>
                <span className="text-[0.65rem] font-data text-[var(--text-primary)]">
                  {v != null ? String(v) : "-"}
                </span>
              </div>
            ))}
          </div>
          {detail.bucket_scores != null && (
            <div className="mt-2">
              <span className="text-[0.52rem] uppercase tracking-widest text-[var(--text-muted)]">
                CIS Buckets
              </span>
              <pre className="text-[0.55rem] font-data text-[var(--text-secondary)] mt-1 whitespace-pre-wrap">
                {JSON.stringify(detail.bucket_scores, null, 2)}
              </pre>
            </div>
          )}
        </div>
      )}
      {!loading && !detail && (
        <div className="p-4 text-[0.62rem] text-[var(--red)] italic">
          Signal not found
        </div>
      )}
    </div>
  );
}

// ── Main SignalLedger ──
function buildQueryParams(filters: FilterState): string {
  const params = new URLSearchParams();
  params.set("limit", "500");

  if (filters.tier.length === 1 && filters.tier[0] === "hero") {
    params.set("tier", "hero");
  } else if (filters.tier.length === 1 && filters.tier[0] === "monitored") {
    params.set("tier", "monitored");
  } else {
    params.set("tier", "all");
  }

  if (filters.symbol.length === 1) params.set("symbol", filters.symbol[0]);
  if (filters.timeframe.length === 1) params.set("timeframe", filters.timeframe[0]);

  return params.toString();
}

export function SignalLedger({ filters }: { filters: FilterState }) {
  const [signals, setSignals] = useState<LedgerSignal[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const parentRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const qs = buildQueryParams(filters);

    fetchJson<{ signals?: LedgerSignal[] }>(`${getApiBase()}/api/signals/recent?${qs}`)
      .then((d) => setSignals(d.signals ?? []))
      .catch((err) => {
        console.error("Failed to fetch signals:", err);
        setSignals([]);
      });
  }, [filters]);

  // Client-side filtering for multi-select cases
  const filtered = useMemo(() => {
    return signals.filter((s) => {
      // Null confidence signals should NOT bypass filters when a confidence range is set
      if (s.confidence === null) return false;

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

      // Check confidence min filter
      if (filters.confidence_min > 0 && s.confidence < filters.confidence_min)
        return false;

      // Check confidence max filter (if set)
      if (filters.confidence_max < 1 && s.confidence > filters.confidence_max)
        return false;

      // CIS filter - only active when CIS score exists and meets threshold
      if (
        filters.cis_filter === "cis_only" &&
        (s.cis_score == null || Math.abs(s.cis_score) <= 0.35)
      )
        return false;

      // Fallback filter - only active when CIS score exists and exceeds threshold
      if (
        filters.cis_filter === "fallback_only" &&
        (s.cis_score != null && Math.abs(s.cis_score) > 0.35)
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
