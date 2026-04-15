// dashboard/src/components/signals/filter-bar.tsx
"use client";

import { useCallback } from "react";

export interface FilterState {
  symbol: string[];
  asset_class: string[];
  setup_plugin: string[];
  timeframe: string[];
  tier: string[];
  confidence_min: number;
  confidence_max: number;
  cis_filter: "all" | "cis_only" | "fallback_only";
  status: string[];
  date_from: string;   // YYYY-MM-DD
  date_to: string;     // YYYY-MM-DD
}

// Factory function that returns fresh default filters on each call
function getDefaultFilters(): FilterState {
  const d = new Date();
  d.setDate(d.getDate() - 7);
  return {
    symbol: [],
    asset_class: [],
    setup_plugin: [],
    timeframe: [],
    tier: ["hero", "monitored"],   // exclude candidate noise by default
    confidence_min: 0.35,           // match hero/monitored threshold
    confidence_max: 1,
    cis_filter: "all",
    status: [],
    date_from: d.toISOString().slice(0, 10),
    date_to: new Date().toISOString().slice(0, 10),
  };
}

// Export defaultFilters constant for backward compatibility
export const defaultFilters = getDefaultFilters();

const TIER_OPTIONS = ["hero", "monitored", "candidate"] as const;
const TF_OPTIONS = ["1m", "5m", "15m", "1h", "4h", "1d"] as const;
const STATUS_OPTIONS = ["pending", "active", "regime_suppressed", "expired"] as const;
const ASSET_CLASS_OPTIONS = ["equity_index", "energy", "metals", "interest_rates", "fx", "crypto"] as const;

function PillToggle<T extends string>({
  label,
  options,
  selected,
  onChange,
}: {
  label: string;
  options: readonly T[];
  selected: T[];
  onChange: (val: T[]) => void;
}) {
  const toggle = (v: T) => {
    if (selected.includes(v)) {
      onChange(selected.filter((x) => x !== v));
    } else {
      onChange([...selected, v]);
    }
  };
  return (
    <div className="flex items-center gap-1.5 flex-wrap">
      <span className="text-[0.52rem] uppercase tracking-widest text-[var(--text-muted)] shrink-0">
        {label}
      </span>
      {options.map((opt) => (
        <button
          key={opt}
          onClick={() => toggle(opt)}
          className="px-2 py-0.5 rounded text-[0.6rem] font-semibold transition-colors"
          style={{
            backgroundColor: selected.includes(opt)
              ? "var(--bg-elevated)"
              : "transparent",
            color: selected.includes(opt)
              ? "var(--text-primary)"
              : "var(--text-muted)",
            border: `1px solid ${selected.includes(opt) ? "var(--border-right)" : "var(--border-subtle)"}`,
          }}
        >
          {opt}
        </button>
      ))}
    </div>
  );
}

export function FilterBar({
  filters,
  onChange,
}: {
  filters: FilterState;
  onChange: (next: Partial<FilterState>) => void;
}) {
  return (
    <div
      className="flex flex-wrap gap-3 p-3 rounded"
      style={{ background: "var(--bg-surface)", border: "1px solid var(--border-subtle)" }}
    >
      {/* Tier */}
      <PillToggle
        label="Tier"
        options={TIER_OPTIONS}
        selected={filters.tier as typeof TIER_OPTIONS[number][]}
        onChange={(v) => onChange({ tier: v })}
      />

      {/* Timeframe */}
      <PillToggle
        label="TF"
        options={TF_OPTIONS}
        selected={filters.timeframe as typeof TF_OPTIONS[number][]}
        onChange={(v) => onChange({ timeframe: v })}
      />

      {/* Asset class */}
      <PillToggle
        label="Asset"
        options={ASSET_CLASS_OPTIONS}
        selected={filters.asset_class as typeof ASSET_CLASS_OPTIONS[number][]}
        onChange={(v) => onChange({ asset_class: v })}
      />

      {/* CIS filter */}
      <div className="flex items-center gap-1.5">
        <span className="text-[0.52rem] uppercase tracking-widest text-[var(--text-muted)]">CIS</span>
        {(["all", "cis_only", "fallback_only"] as const).map((opt) => (
          <button
            key={opt}
            onClick={() => onChange({ cis_filter: opt })}
            className="px-2 py-0.5 rounded text-[0.6rem] font-semibold transition-colors"
            style={{
              backgroundColor: filters.cis_filter === opt
                ? "var(--bg-elevated)"
                : "transparent",
              color: filters.cis_filter === opt
                ? "var(--text-primary)"
                : "var(--text-muted)",
              border: `1px solid ${filters.cis_filter === opt ? "var(--border-right)" : "var(--border-subtle)"}`,
            }}
          >
            {opt.replace("_", " ")}
          </button>
        ))}
      </div>

      {/* Confidence range */}
      <div className="flex items-center gap-2">
        <span className="text-[0.52rem] uppercase tracking-widest text-[var(--text-muted)]">Conf</span>
        <input
          type="range"
          min={0} max={1} step={0.05}
          value={filters.confidence_min}
          onChange={(e) => onChange({ confidence_min: parseFloat(e.target.value) })}
          className="w-20 h-1 accent-[var(--blue)]"
        />
        <span className="text-[0.6rem] font-data text-[var(--text-secondary)]">
          {(filters.confidence_min * 100).toFixed(0)}%–{(filters.confidence_max * 100).toFixed(0)}%
        </span>
        <input
          type="range"
          min={0} max={1} step={0.05}
          value={filters.confidence_max}
          onChange={(e) => onChange({ confidence_max: parseFloat(e.target.value) })}
          className="w-20 h-1 accent-[var(--blue)]"
        />
      </div>

      {/* Date range */}
      <div className="flex items-center gap-1.5">
        <span className="text-[0.52rem] uppercase tracking-widest text-[var(--text-muted)]">Date</span>
        <input
          type="date"
          value={filters.date_from}
          onChange={(e) => onChange({ date_from: e.target.value })}
          className="text-[0.6rem] font-data bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded px-1 py-0.5 text-[var(--text-secondary)]"
        />
        <span className="text-[0.52rem] text-[var(--text-muted)]">→</span>
        <input
          type="date"
          value={filters.date_to}
          onChange={(e) => onChange({ date_to: e.target.value })}
          className="text-[0.6rem] font-data bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded px-1 py-0.5 text-[var(--text-secondary)]"
        />
      </div>

      {/* Reset */}
      <button
        onClick={() => onChange(getDefaultFilters())}
        className="ml-auto text-[0.55rem] text-[var(--text-muted)] hover:text-[var(--text-secondary)] transition-colors"
      >
        Reset
      </button>
    </div>
  );
}
