/** Timeframe utilities shared across dashboard components */

/** Timeframe offset to seconds: add to bar open ts to get actual close time */
export const TF_OFFSETS: Record<string, number> = {
  "1m": 60,
  "5m": 300,
  "15m": 900,
  "1h": 3600,
  "4h": 14400,
  "1d": 86400,
};

/**
 * Derive bar close ISO timestamp.
 * Uses bar_close_ts if available, else adds timeframe offset to bar open timestamp.
 *
 * @param barCloseTs - Bar close timestamp from signal (optional)
 * @param barOpenTs - Bar open timestamp from signal (usually signal.timestamp)
 * @param tf - Timeframe string (e.g., "5m", "15m")
 * @returns Bar close time in ISO format, or undefined if inputs invalid
 */
export function deriveBarCloseIso(
  barCloseTs: string | undefined,
  barOpenTs: string | undefined,
  tf: string
): string | undefined {
  if (barCloseTs) return barCloseTs;
  const base = barOpenTs;
  if (!base) return undefined;
  const offset = TF_OFFSETS[tf];
  if (offset === undefined) {
    console.warn(`deriveBarCloseIso: unknown timeframe "${tf}"`);
    return undefined;
  }
  const baseMs = new Date(base).getTime();
  if (isNaN(baseMs)) return undefined;
  return new Date(baseMs + offset * 1000).toISOString();
}
