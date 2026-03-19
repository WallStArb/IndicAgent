/**
 * Plugin and signal name utilities.
 * Extracted from signal-scorecard, signal-banner, and pattern-panel.
 */

/** Remove tier prefix from plugin names for display */
export function stripPluginPrefix(name: string): string {
  return name.replace(/^(trad_|ind_|smc_)/, "");
}

/** Format signal type for display (e.g., "choch_reversal" → "Choch Reversal") */
export function formatSignalType(raw: string): string {
  return raw.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

/** Suppression reason labels from signal-scorecard */
export const SUPPRESSION_LABELS: Record<string, string> = {
  regime_prob: "< 60% conf",
  regime_duration: "< 5 bars",
  regime_type: "wrong regime",
} as const;

/** Get human-readable suppression label */
export function suppressionLabel(reason: string | null): string {
  if (!reason) return "";
  return SUPPRESSION_LABELS[reason] ?? reason;
}
