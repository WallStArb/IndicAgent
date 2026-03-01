"use client";

import { useState } from "react";

export interface SignalFilters {
  confidence: "all" | "65+" | "75+";
  cis: "all" | "cis-only";
  timeframe: "all" | "1m" | "5m" | "15m" | "1h";
  assetClass: "all" | "Equity" | "Energy" | "Metals" | "Rates" | "FX" | "Crypto" | "Agriculture";
}

interface SignalFiltersProps {
  filters: SignalFilters;
  onFiltersChange: (filters: SignalFilters) => void;
}

function FilterPill<T extends string>({
  label,
  options,
  value,
  onChange,
}: {
  label: string;
  options: readonly T[];
  value: T;
  onChange: (value: T) => void;
}) {
  return (
    <div className="flex items-center gap-2">
      <span
        className="text-xs font-medium whitespace-nowrap"
        style={{ color: "var(--text-muted)" }}
      >
        {label}
      </span>
      <div className="flex gap-1.5">
        {options.map((opt) => (
          <button
            key={opt}
            onClick={() => onChange(opt)}
            className={`px-3 py-1.5 text-xs font-medium rounded-md transition-all duration-200 ${
              value === opt
                ? "ring-1 ring-[var(--accent-cyan-dim)]"
                : "hover:bg-[var(--bg-hover)]"
            }`}
            style={{
              background: value === opt ? "var(--accent-cyan-dim)" : "var(--bg-elevated)",
              color: value === opt ? "var(--accent-cyan)" : "var(--text-secondary)",
              border: "1px solid var(--border-subtle)",
            }}
          >
            {opt}
          </button>
        ))}
      </div>
    </div>
  );
}

export function SignalFilters({ filters, onFiltersChange }: SignalFiltersProps) {
  const confidenceOptions: readonly ("all" | "65+" | "75+")[] = ["all", "65+", "75+"];
  const cisOptions: readonly ("all" | "cis-only")[] = ["all", "cis-only"];
  const timeframeOptions: readonly ("all" | "1m" | "5m" | "15m" | "1h")[] = [
    "all",
    "1m",
    "5m",
    "15m",
    "1h",
  ];
  const assetClassOptions: readonly (
    | "all"
    | "Equity"
    | "Energy"
    | "Metals"
    | "Rates"
    | "FX"
    | "Crypto"
    | "Agriculture"
  )[] = [
    "all",
    "Equity",
    "Energy",
    "Metals",
    "Rates",
    "FX",
    "Crypto",
    "Agriculture",
  ];

  return (
    <div className="flex flex-wrap items-center gap-x-6 gap-y-3 p-4 mb-6 border-b">
      <FilterPill
        label="Confidence"
        options={confidenceOptions}
        value={filters.confidence}
        onChange={(val) => onFiltersChange({ ...filters, confidence: val })}
      />
      <FilterPill
        label="CIS"
        options={cisOptions}
        value={filters.cis}
        onChange={(val) => onFiltersChange({ ...filters, cis: val })}
      />
      <FilterPill
        label="TF"
        options={timeframeOptions}
        value={filters.timeframe}
        onChange={(val) => onFiltersChange({ ...filters, timeframe: val })}
      />
      <FilterPill
        label="Asset"
        options={assetClassOptions}
        value={filters.assetClass}
        onChange={(val) => onFiltersChange({ ...filters, assetClass: val })}
      />
    </div>
  );
}
