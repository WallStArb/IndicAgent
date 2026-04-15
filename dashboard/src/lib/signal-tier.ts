// dashboard/src/lib/signal-tier.ts
import type { SignalTier } from "@/lib/types";

/** Data-derived breakeven confidence (signal_ledger outcome analysis). */
export const HERO_CONFIDENCE_THRESHOLD = 0.40;

/** CIS fire threshold — eliminates ~80% of fallback-path noise. */
export const CIS_SCORE_THRESHOLD = 0.35;

/**
 * Compute signal quality tier from DB/API fields.
 * Evaluation order: Hero → Monitored → Candidate.
 * NULL cis_score always → Monitored (never Hero).
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
    confidence >= HERO_CONFIDENCE_THRESHOLD &&
    Math.abs(cisScore) > CIS_SCORE_THRESHOLD
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
    confidence >= HERO_CONFIDENCE_THRESHOLD &&
    cisScore != null &&
    Math.abs(cisScore) > CIS_SCORE_THRESHOLD
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
