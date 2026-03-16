// dashboard/src/lib/signal-tier.ts
import type { SignalTier } from "@/lib/types";

/**
 * Compute signal quality tier from DB/API fields.
 * Evaluation order: Hero → Monitored → Candidate.
 * NULL cis_score always → Monitored (never Hero).
 *
 * Thresholds:
 *   confidence >= 0.40  — data-derived breakeven (signal_ledger outcome analysis)
 *   abs(cis_score) > 0.35 — CIS fire threshold (eliminates 80% fallback-path noise)
 */
export function computeSignalTier(
  wasSelected: boolean,
  confidence: number | null | undefined,
  cisScore: number | null | undefined,
): SignalTier {
  if (
    wasSelected &&
    confidence != null &&
    cisScore != null &&
    confidence >= 0.40 &&
    Math.abs(cisScore) > 0.35
  ) {
    return "hero";
  }
  if (wasSelected) return "monitored";
  return "candidate";
}

/**
 * Hero tier gate for SSE SignalData where was_selected is always true.
 * If cis_score is absent (pre-Task-6 service), returns false — safe default.
 */
export function isHeroTier(
  confidence: number,
  cisScore: number | null | undefined,
): boolean {
  return (
    confidence >= 0.40 &&
    cisScore != null &&
    Math.abs(cisScore) > 0.35
  );
}

/** Color for a tier dot/badge. */
export function tierColor(tier: SignalTier): string {
  if (tier === "hero") return "var(--blue)";
  if (tier === "monitored") return "var(--amber)";
  return "var(--text-muted)";
}

/** CSS opacity for a tier row. */
export function tierOpacity(tier: SignalTier): number {
  if (tier === "hero") return 1.0;
  if (tier === "monitored") return 0.85;
  return 0.6;
}
