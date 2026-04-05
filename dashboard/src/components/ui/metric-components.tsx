"use client";

import { fmtNum } from "@/lib/format";

/** Color threshold constants for metric bars */
const COLOR_THRESHOLDS = {
  INTEGRITY_HIGH: 0.7,
  INTEGRITY_MED: 0.4,
  ATR_HIGH: 0.8,
  ATR_MED: 0.5,
  ATR_LOW: 0.3,
} as const;

/**
 * Reusable metric display components for intelligence panels.
 * Extracted from structure-panel, context-panel, pattern-panel to eliminate duplication.
 */

/**
 * Mini progress bar with percentage label.
 * Used for: trend integrity, ATR percentile, and other 0-1 metrics.
 */
export function MiniBar({
  value,
  color,
}: {
  value: number;
  color?: string;
}) {
  const pct = Math.round(value * 100);

  return (
    <div className="inline-flex items-center gap-1">
      <div className="w-8 h-1.5 rounded-full bg-[var(--bg-base)] overflow-hidden">
        <div
          className="h-full rounded-full transition-all"
          style={{ width: `${pct}%`, backgroundColor: color ?? "var(--blue)" }}
        />
      </div>
      <span className="font-data text-[0.55rem] text-[var(--text-muted)]">
        {pct}
      </span>
    </div>
  );
}

/** Color mappings for DirectionalPill component */
const PILL_STYLES = {
  bullish: "bg-[var(--green-dim)] text-[var(--green)]",
  bearish: "bg-[var(--red-dim)] text-[var(--red)]",
  neutral: "bg-[var(--amber-dim)] text-[var(--amber)]",
} as const;

/** Color mappings for VolatilityPill component */
const VOLATILITY_COLORS = {
  low: "bg-[var(--blue-dim)] text-[var(--blue)]",
  normal: "bg-[var(--bg-elevated)] text-[var(--text-accent)]",
  high: "bg-[var(--amber-dim)] text-[var(--amber)]",
  extreme: "bg-[var(--red-dim)] text-[var(--red)]",
} as const;

/** Trend regime mapping for TrendLabel component */
const TREND_REGIME_MAP: Record<string, { label: string; cls: string }> = {
  strong_up: { label: "Strong▲", cls: "text-up" },
  weak_up: { label: "Weak▲", cls: "text-up opacity-60" },
  neutral: { label: "Neutral", cls: "text-neutral" },
  weak_down: { label: "Weak▼", cls: "text-down opacity-60" },
  strong_down: { label: "Strong▼", cls: "text-down" },
} as const;

/**
 * Directional pill badge (bullish/bearish/neutral).
 * Used for: divergence signals, regime states, trend direction.
 */
export function DirectionalPill({
  label,
  type = "neutral",
  detail,
}: {
  label: string;
  type?: "bullish" | "bearish" | "neutral";
  detail?: string;
}) {
  const styleClass = PILL_STYLES[type];

  return (
    <span
      className={`inline-flex items-center gap-0.5 px-1.5 py-0 rounded text-[0.55rem] font-semibold uppercase tracking-wider ${styleClass}`}
    >
      {label}
      {detail != null && <span className="opacity-70">{detail}</span>}
    </span>
  );
}

/**
 * Volatility regime pill badge.
 * Maps regime strings to appropriate color coding.
 */
export function VolatilityPill({ regime }: { regime?: string }) {
  const colorClass = (VOLATILITY_COLORS as Record<string, string>)[regime ?? ""] ?? VOLATILITY_COLORS.normal;

  return (
    <span
      className={`px-1 rounded text-[0.55rem] font-semibold uppercase tracking-wider ${colorClass}`}
    >
      {regime ?? "—"}
    </span>
  );
}

/**
 * Trend regime label with directional styling.
 */
export function TrendLabel({ regime }: { regime?: string }) {
  const entry = TREND_REGIME_MAP[regime ?? ""] ?? { label: "—", cls: "text-neutral" };

  return (
    <span className={`font-data text-[0.7rem] font-semibold ${entry.cls}`}>
      {entry.label}
    </span>
  );
}

/**
 * Momentum bias gauge with directional color.
 */
export function MomentumGauge({ bias }: { bias?: number }) {
  if (bias === undefined) {
    return <span className="font-data text-[0.7rem] text-neutral">—</span>;
  }

  const color = bias > 0 ? "var(--green)" : bias < 0 ? "var(--red)" : "var(--text-muted)";

  return (
    <span className="font-data text-[0.7rem] font-semibold" style={{ color }}>
      {bias > 0 ? "+" : ""}
      {fmtNum(bias, 1)}
    </span>
  );
}

/**
 * Zone label wrapper for tier panels (I3, I4, I5, etc.).
 * Provides consistent sizing and alignment across all intelligence panels.
 */
export function ZoneLabel({ tier }: { tier: string }) {
  return (
    <span className="zone-label shrink-0 pt-px w-10 text-[0.55rem] font-semibold text-[var(--text-muted)]">
      {tier}
    </span>
  );
}

/**
 * Inline metric display with label and value.
 * Used throughout panels for consistent metric presentation.
 */
export function Metric({
  label,
  value,
  valueClassName,
}: {
  label: string;
  value: React.ReactNode;
  valueClassName?: string;
}) {
  return (
    <span className="inline-flex items-center gap-1 whitespace-nowrap">
      <span className="text-[0.55rem] font-medium uppercase tracking-wider text-[var(--text-muted)]">
        {label}
      </span>
      <span className={`font-data text-[0.7rem] ${valueClassName ?? ""}`}>{value}</span>
    </span>
  );
}
