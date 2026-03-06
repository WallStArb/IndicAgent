// ── Number formatting for trading data ──

/** Format price with appropriate decimal places based on magnitude */
export function fmtPrice(price: number | undefined): string {
  if (!price) return "—";
  if (price >= 1000) return price.toFixed(2);
  if (price >= 100) return price.toFixed(3);
  return price.toFixed(4);
}

/** Format a number to fixed decimals, dash if undefined */
export function fmtNum(
  value: number | undefined | null,
  decimals: number = 2
): string {
  if (value === undefined || value === null || isNaN(value)) return "—";
  return value.toFixed(decimals);
}

/** Format percentage change with sign */
export function fmtPct(value: number | undefined): string {
  if (value === undefined || isNaN(value)) return "—";
  const sign = value > 0 ? "+" : "";
  return `${sign}${value.toFixed(2)}%`;
}

/** Format price change with sign and points */
export function fmtChange(value: number | undefined): string {
  if (value === undefined || isNaN(value)) return "—";
  const sign = value > 0 ? "+" : "";
  return `${sign}${value.toFixed(2)}`;
}

/** Get direction class based on value */
export function dirClass(value: number | undefined): string {
  if (!value) return "text-neutral";
  return value > 0 ? "text-up" : "text-down";
}

/** Get direction class for oscillators (centered on threshold) */
export function oscClass(
  value: number | undefined,
  overbought: number = 70,
  oversold: number = 30
): string {
  if (value === undefined) return "text-neutral";
  if (value >= overbought) return "text-up";
  if (value <= oversold) return "text-down";
  return "text-[var(--text-accent)]";
}

/** Data freshness: how stale is the last update? */
export function freshness(lastUpdate: number): "live" | "stale" | "dead" {
  const age = Date.now() - lastUpdate;
  if (age < 5000) return "live";
  if (age < 30000) return "stale";
  return "dead";
}

/** Compact large numbers (1234567 → 1.23M) */
export function fmtCompact(value: number | undefined): string {
  if (value === undefined || isNaN(value)) return "—";
  if (Math.abs(value) >= 1e9) return `${(value / 1e9).toFixed(1)}B`;
  if (Math.abs(value) >= 1e6) return `${(value / 1e6).toFixed(1)}M`;
  if (Math.abs(value) >= 1e3) return `${(value / 1e3).toFixed(1)}K`;
  return value.toFixed(0);
}

// ── Signal timing utilities ──

const _TF_MINUTES: Record<string, number> = {
  "1m": 1, "5m": 5, "15m": 15, "1h": 60, "4h": 240, "1d": 1440,
};

/** Convert timeframe string to minutes. */
export function tfToMinutes(tf: string): number {
  return _TF_MINUTES[tf] ?? 1;
}

/**
 * Returns staleness ratio (elapsed / bar_period_minutes) when >= 1.0, else null.
 * >= 1.0 means at least one full bar period has elapsed since the signal/narrative fired.
 * TODO(v1.4-feedback): replace provisional 1.0 display threshold with empirically-derived
 * percentile from signal_ledger outcomes once N > 100 resolved signals.
 */
export function stalenessRatio(timestamp: string, tfMinutes: number): number | null {
  const ms = Date.parse(timestamp);
  if (isNaN(ms)) return null;
  const ratio = (Date.now() - ms) / (tfMinutes * 60 * 1000);
  return ratio >= 1.0 ? ratio : null;
}

/**
 * Returns pipeline lag in seconds (signal_computed_at - bar_close_ts).
 * Returns null if either timestamp is missing or invalid.
 */
export function pipelineLagS(
  signalComputedAt: string | undefined,
  barCloseTs: string | undefined
): number | null {
  if (!signalComputedAt || !barCloseTs) return null;
  const computed = Date.parse(signalComputedAt);
  const barClose = Date.parse(barCloseTs);
  if (isNaN(computed) || isNaN(barClose)) return null;
  return (computed - barClose) / 1000;
}
