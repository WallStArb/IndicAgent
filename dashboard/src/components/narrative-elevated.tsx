// dashboard/src/components/narrative-elevated.tsx
"use client";

import { useState } from "react";
import type { NarrativeData, SignalData } from "@/lib/types";
import { stalenessRatio, tfToMinutes } from "@/lib/format";

interface NarrativeElevatedProps {
  narrative: NarrativeData | null;
  signal: SignalData | null;
}

const FRESH_THRESHOLD_MS = 5 * 60 * 1000; // 5 minutes
const CONFIDENCE_THRESHOLD = 0.75;

export function NarrativeElevated({ narrative, signal }: NarrativeElevatedProps) {
  const [expanded, setExpanded] = useState(false);

  if (!narrative || !signal) return null;

  const isFresh = Date.now() - narrative.receivedAt < FRESH_THRESHOLD_MS;
  const isHighConfidence = signal.confidence >= CONFIDENCE_THRESHOLD;

  if (!isFresh || !isHighConfidence) return null;

  const isBullish = narrative.action_bias === "bullish";
  const accentColor = isBullish ? "var(--green)" : "var(--red)";
  const tfMinutes = tfToMinutes(narrative.timeframe);
  const staleness = stalenessRatio(narrative.timestamp, tfMinutes);
  const actionTag = narrative.action_tag ?? "";
  const shortText = narrative.narrative_short ?? narrative.narrative ?? null;
  const deepText = narrative.narrative_deep ?? null;

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
        {narrative.timestamp && (
          <span className="text-[0.45rem] font-data text-[var(--text-muted)] ml-auto">
            {new Date(narrative.timestamp).toLocaleTimeString([], {
              hour: "2-digit",
              minute: "2-digit",
              hour12: false,
            })}
          </span>
        )}
        {staleness !== null && (
          <span
            className="text-[0.45rem] font-data"
            style={{
              color: staleness >= 2.0 ? "var(--red-dim)" : "#f59e0b",
              opacity: 0.7,
            }}
          >
            {staleness.toFixed(1)}× stale
          </span>
        )}
      </div>

      {/* Action tag badge */}
      {actionTag && (
        <div className="text-xs font-mono text-amber-400">{actionTag}</div>
      )}

      {/* Short narrative */}
      {shortText ? (
        <p className="text-[0.65rem] text-[var(--text-secondary)] leading-relaxed m-0">
          {shortText}
        </p>
      ) : (
        <div className="h-8 bg-white/5 rounded animate-pulse" />
      )}

      {/* Expand toggle + deep narrative */}
      {shortText && (
        <button
          className="text-xs text-white/40 hover:text-white/60 mt-1 block text-left"
          onClick={() => setExpanded((e) => !e)}
        >
          {expanded ? "▲ Hide analysis" : "▼ Full analysis"}
        </button>
      )}
      {expanded && (
        deepText ? (
          <p className="text-[0.65rem] leading-relaxed mt-1 text-white/80 italic m-0">
            {deepText}
          </p>
        ) : (
          <div className="h-12 bg-white/5 rounded animate-pulse mt-1" />
        )
      )}
    </div>
  );
}
