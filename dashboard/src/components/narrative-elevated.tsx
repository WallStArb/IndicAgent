// dashboard/src/components/narrative-elevated.tsx
"use client";

import type { NarrativeData, SignalData } from "@/lib/types";

interface NarrativeElevatedProps {
  narrative: NarrativeData | null;
  signal: SignalData | null;
}

const FRESH_THRESHOLD_MS = 5 * 60 * 1000; // 5 minutes
const CONFIDENCE_THRESHOLD = 0.75;

export function NarrativeElevated({ narrative, signal }: NarrativeElevatedProps) {
  if (!narrative || !signal) return null;

  const isFresh = Date.now() - narrative.receivedAt < FRESH_THRESHOLD_MS;
  const isHighConfidence = signal.confidence >= CONFIDENCE_THRESHOLD;

  if (!isFresh || !isHighConfidence) return null;

  const isBullish = narrative.action_bias === "bullish";
  const accentColor = isBullish ? "var(--green)" : "var(--red)";

  return (
    <div
      className="px-3 py-2.5 flex flex-col gap-1.5"
      style={{
        borderLeft: `2px solid ${accentColor}`,
        borderBottom: "1px solid var(--border-subtle)",
        background: isBullish
          ? "linear-gradient(135deg, rgba(0,220,130,0.04) 0%, transparent 60%)"
          : "linear-gradient(135deg, rgba(255,71,87,0.04) 0%, transparent 60%)",
      }}
    >
      {/* Header */}
      <div className="flex items-center gap-2">
        <span
          className="text-[0.5rem] font-bold uppercase tracking-widest"
          style={{ color: accentColor }}
        >
          AI · {narrative.action_bias.toUpperCase()}
        </span>
        <span className="text-[0.45rem] text-[var(--text-muted)]">
          {narrative.timeframe.toUpperCase()}
        </span>
      </div>

      {/* Narrative prose */}
      <p className="text-[0.65rem] text-[var(--text-secondary)] leading-relaxed m-0">
        {narrative.narrative}
      </p>
    </div>
  );
}
