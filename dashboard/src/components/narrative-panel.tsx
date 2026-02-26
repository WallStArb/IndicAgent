"use client";

import { useMemo } from "react";
import type { NarrativeData } from "@/lib/types";

interface NarrativePanelProps {
  narratives: Record<string, NarrativeData>;
}

/** Age threshold after which a narrative is considered stale (1 hour) */
const STALE_AFTER_MS = 60 * 60 * 1000;

/** I8 AI Narrative feed — full-width horizontal strip below the symbol grid */
export function NarrativePanel({ narratives }: NarrativePanelProps) {
  const entries = useMemo(
    () => Object.values(narratives).sort((a, b) => b.receivedAt - a.receivedAt),
    [narratives]
  );

  if (entries.length === 0) {
    return (
      <div className="px-3 py-1.5 flex items-center gap-2 border-t border-[var(--border-subtle)] bg-[var(--bg-surface)]">
        <span className="text-[0.55rem] font-semibold uppercase tracking-widest text-[var(--text-muted)] shrink-0">
          AI
        </span>
        <span className="text-[0.6rem] text-[var(--text-muted)] italic">
          Waiting for signals...
        </span>
      </div>
    );
  }

  return (
    <div className="border-t border-[var(--border-subtle)] bg-[var(--bg-surface)] shrink-0">
      <div className="flex items-stretch overflow-x-auto">
        {entries.map((n) => (
          <NarrativeCard key={`${n.symbol}:${n.timeframe}`} data={n} />
        ))}
      </div>
    </div>
  );
}

function NarrativeCard({ data }: { data: NarrativeData }) {
  const isStale = Date.now() - data.receivedAt > STALE_AFTER_MS;

  // Show the bar timestamp (when the signal that triggered the narrative occurred)
  const barTimeStr = data.timestamp
    ? new Date(data.timestamp).toLocaleTimeString([], {
        hour: "2-digit",
        minute: "2-digit",
        hour12: false,
      })
    : null;

  // Show staleness as date if older than today
  const barDate = data.timestamp ? new Date(data.timestamp) : null;
  const isToday = barDate
    ? barDate.toDateString() === new Date().toDateString()
    : true;
  const barDateStr =
    barDate && !isToday
      ? barDate.toLocaleDateString([], { month: "short", day: "numeric" })
      : null;

  const isBullish = data.action_bias === "bullish";
  const accentColor = isBullish ? "var(--green)" : "var(--red)";

  return (
    <div
      className="shrink-0 flex flex-col gap-1 px-3 py-2 min-w-[280px] max-w-[380px] border-r border-[var(--border-subtle)]"
      style={{
        borderLeftWidth: "2px",
        borderLeftStyle: "solid",
        borderLeftColor: isStale ? "var(--border-subtle)" : accentColor,
        opacity: isStale ? 0.45 : 1,
        transition: "opacity 0.5s ease-out",
      }}
    >
      {/* Header: symbol · TF · bias · bar time */}
      <div className="flex items-center gap-1.5">
        <span className="text-[0.55rem] font-bold text-[var(--text-primary)] font-data">
          {data.symbol}
        </span>
        <span className="text-[0.5rem] text-[var(--text-muted)] bg-[var(--bg-elevated)] px-1 rounded">
          {data.timeframe.toUpperCase()}
        </span>
        <span
          className="text-[0.5rem] font-semibold uppercase tracking-wider"
          style={{ color: isStale ? "var(--text-muted)" : accentColor }}
        >
          {data.action_bias}
        </span>
        <div className="ml-auto flex items-center gap-1 shrink-0">
          {barDateStr && (
            <span className="text-[0.5rem] text-[var(--text-muted)]">{barDateStr}</span>
          )}
          {barTimeStr && (
            <span className="text-[0.5rem] font-data text-[var(--text-muted)]">
              {barTimeStr}
            </span>
          )}
          {isStale && (
            <span className="text-[0.45rem] text-[var(--text-muted)] italic">stale</span>
          )}
        </div>
      </div>

      {/* AI narrative text — up to 5 lines */}
      <p className="text-[0.6rem] text-[var(--text-secondary)] italic leading-relaxed line-clamp-5 m-0">
        {data.narrative}
      </p>
    </div>
  );
}
