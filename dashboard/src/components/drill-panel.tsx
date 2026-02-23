// dashboard/src/components/drill-panel.tsx
"use client";

import { X } from "lucide-react";
import type { SymbolData } from "@/lib/types";

interface DrillPanelProps {
  symbol: string;
  timeframe: string;
  data: SymbolData;
  onClose: () => void;
}

export function DrillPanel({ symbol, timeframe, data, onClose }: DrillPanelProps) {
  return (
    <>
      {/* Backdrop */}
      <div
        className="fixed inset-0 z-40 bg-black/50 backdrop-blur-sm"
        onClick={onClose}
      />

      {/* Panel */}
      <div
        className="fixed top-0 right-0 bottom-0 z-50 w-full max-w-md flex flex-col"
        style={{
          backgroundColor: "var(--bg-surface)",
          borderLeft: "1px solid var(--border-default)",
        }}
      >
        {/* Header */}
        <div
          className="flex items-center justify-between px-4 py-3 shrink-0"
          style={{ borderBottom: "1px solid var(--border-subtle)" }}
        >
          <div className="flex items-center gap-2">
            <span className="text-sm font-bold text-[var(--text-primary)] font-data">
              {symbol}
            </span>
            <span
              className="text-[0.55rem] font-semibold px-1.5 py-0.5 rounded"
              style={{
                backgroundColor: "var(--bg-elevated)",
                color: "var(--text-secondary)",
              }}
            >
              {timeframe.toUpperCase()}
            </span>
          </div>
          <button
            onClick={onClose}
            className="p-1 rounded cursor-pointer text-[var(--text-muted)] hover:text-[var(--text-primary)] transition-colors"
          >
            <X size={14} />
          </button>
        </div>

        {/* Level 2: Tier breakdown */}
        <div className="flex-1 overflow-y-auto p-4 flex flex-col gap-3">
          <TierBreakdown data={data} />
        </div>
      </div>
    </>
  );
}

/** Level 2: I3→I7 tier breakdown — shows each tier's status + brief reason */
function TierBreakdown({ data }: { data: SymbolData }) {
  const tiers = [
    {
      label: "I3 Structure",
      value: data.structure
        ? `Trend: ${data.structure.swing_trend ?? "—"} · Integrity: ${((data.structure.trend_integrity ?? 0) * 100).toFixed(0)}%`
        : null,
    },
    {
      label: "I4 Context",
      value: data.context
        ? `Vol: ${data.context.volatility_regime ?? "—"} · Trend: ${data.context.trend_regime ?? "—"}`
        : null,
    },
    {
      label: "I5 Patterns",
      value: data.patterns
        ? `Confluence: ${((data.patterns.confluence_score ?? 0) * 100).toFixed(0)}% · RSI div: ${data.patterns.rsi_divergence ?? "none"}`
        : null,
    },
    {
      label: "SMC",
      value: data.smartMoney
        ? [
            data.smartMoney.bos_detected ? `BOS ${(data.smartMoney.bos_direction ?? 0) > 0 ? "▲" : "▼"}` : null,
            data.smartMoney.choch_detected ? "CHoCH" : null,
            (data.smartMoney.fvg_type ?? 0) !== 0 ? `FVG ${(data.smartMoney.fvg_type ?? 0) > 0 ? "bull" : "bear"}` : null,
            data.smartMoney.sweep_detected ? "Sweep" : null,
          ]
            .filter(Boolean)
            .join(" · ") || "—"
        : null,
    },
    {
      label: "I6 Confluence",
      value: data.confluence
        ? `CTF score: ${(data.confluence.ctf_score ?? 0).toFixed(2)} · ${data.confluence.ctf_timeframes_aligned ?? 0}/4 TFs`
        : null,
    },
    {
      label: "I7 Signal",
      value: data.signal
        ? `${data.signal.direction.toUpperCase()} · ${data.signal.signal_type} · ${(data.signal.confidence * 100).toFixed(0)}% conf`
        : "No signal",
    },
  ];

  return (
    <div className="flex flex-col gap-1">
      <h3 className="text-[0.55rem] font-semibold uppercase tracking-widest text-[var(--text-muted)] mb-2">
        Intelligence Breakdown
      </h3>
      {tiers.map((tier) => (
        <div
          key={tier.label}
          className="flex items-start gap-3 px-3 py-2 rounded"
          style={{ backgroundColor: "var(--bg-elevated)" }}
        >
          <span className="text-[0.55rem] font-bold text-[var(--text-muted)] shrink-0 w-20">
            {tier.label}
          </span>
          <span className="text-[0.6rem] text-[var(--text-secondary)] flex-1">
            {tier.value ?? (
              <span className="italic text-[var(--text-muted)]">Awaiting data</span>
            )}
          </span>
        </div>
      ))}
    </div>
  );
}
