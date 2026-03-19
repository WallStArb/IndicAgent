"use client";

import type { SignalData } from "@/lib/types";

/**
 * Confidence pipeline visualization: raw CIS → Kalman-filtered → isotonic-calibrated.
 * Shows the Phase 35 signal processing flow.
 */
export function SignalConfidencePipeline({ signal }: { signal: SignalData }) {
  if (
    signal.raw_cis_score == null &&
    signal.filtered_cis_score == null &&
    signal.calibrated_confidence == null
  ) {
    return null;
  }

  return (
    <div className="flex gap-4 text-xs text-[var(--text-muted)]">
      <span>
        <span className="font-medium text-[var(--text-primary)]">Raw CIS:</span>{" "}
        {signal.raw_cis_score != null ? signal.raw_cis_score.toFixed(3) : "—"}
      </span>
      <span>
        <span className="font-medium text-[var(--text-primary)]">Filtered:</span>{" "}
        {signal.filtered_cis_score != null ? signal.filtered_cis_score.toFixed(3) : "—"}
      </span>
      <span>
        <span className="font-medium text-[var(--text-primary)]">Calibrated:</span>{" "}
        {signal.calibrated_confidence != null
          ? `${(signal.calibrated_confidence * 100).toFixed(1)}%`
          : "—"}
      </span>
    </div>
  );
}
