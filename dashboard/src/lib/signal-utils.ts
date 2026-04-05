import type { SignalData } from "./types";

/** Window summary statistics from /api/signals/recent endpoint */
export interface SignalWindowSummary {
  total: number;
  wins: number;
  losses: number;
  pending: number;
  win_rate: number | null;
  avg_pnl_r: number | null;
}

/** DB signal row shape from /api/signals/recent endpoint */
export interface DbSignalRow {
  signal_id: string;
  setup_plugin: string;
  signal_type: string;
  direction: number;
  entry_price: number | null;
  stop_loss: number | null;
  confidence: number | null;
  status: string;
  outcome: string | null;
  exit_price: number | null;
  pnl_r: number | null;
  computed_at: string | null;
  timeframe: string;
  setup_win_rate: number | null;
  setup_avg_pnl_r: number | null;
}

/**
 * Convert DB signal row to SignalData shape used by frontend components.
 * Handles null coalescing and direction mapping.
 */
export function dbRowToSignalData(row: DbSignalRow, symbol: string): SignalData {
  const dir = row.direction > 0 ? ("long" as const) : ("short" as const);
  return {
    symbol,
    signal_id: row.signal_id,
    setup_plugin: row.setup_plugin,
    signal_type: row.signal_type,
    direction: dir,
    entry_price: row.entry_price ?? 0,
    stop_loss: row.stop_loss ?? 0,
    confidence: row.confidence ?? 0,
    profit_target: null,
    risk_reward_ratio: 0,
    regime_context: "",
    timeframe: row.timeframe,
    timestamp: row.computed_at ?? "",
    signal_computed_at: row.computed_at ?? undefined,
    resolved: row.status !== "pending" && row.status !== "active",
    outcome: row.outcome ?? undefined,
    exit_price: row.exit_price ?? undefined,
    setup_win_rate: row.setup_win_rate ?? undefined,
    setup_avg_pnl_r: row.setup_avg_pnl_r ?? undefined,
  };
}

/**
 * Shorten plugin name for compact display.
 * Removes tier prefix and truncates to 6 chars if longer than 8.
 */
export function abbreviatePlugin(name: string): string {
  const bare = name.replace(/^(ind_|patt_|ctx_|smc_|trad_)/, "");
  if (bare.length <= 8) return bare;
  return bare.slice(0, 6);
}

/** Entry type labels for signal detail display */
export const ENTRY_TYPE_LABELS: Record<string, string> = {
  at_close: "at close",
  at_reclaim: "at reclaim",
  zone_proximal: "zone proximal",
};

/** Stop type labels for signal detail display */
export const STOP_TYPE_LABELS: Record<string, string> = {
  demand_zone: "demand zone",
  supply_zone: "supply zone",
  sweep_level: "sweep level",
  ob_bottom: "OB bottom",
  ob_top: "OB top",
  swing_low: "swing low",
  swing_high: "swing high",
  sr_support: "S/R",
  atr: "ATR×2",
};
