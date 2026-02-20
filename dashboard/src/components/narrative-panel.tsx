"use client";

import { useMemo } from "react";
import type { NarrativeData } from "@/lib/types";

interface NarrativePanelProps {
  narratives: Record<string, NarrativeData>;
}

/** Matches the 90s TTL on narrative:SYMBOL:TF:latest hash in Redis */
const STALE_AFTER_MS = 90_000;

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
  const ageMs = Date.now() - data.receivedAt;
  const isStale = ageMs > STALE_AFTER_MS;
  const ageSec = Math.floor(ageMs / 1000);
  const ageLabel = ageSec < 60 ? `${ageSec}s ago` : `${Math.floor(ageSec / 60)}m ago`;

  const isBullish = data.action_bias === "bullish";
  const accentColor = isBullish ? "var(--green)" : "var(--red)";

  return (
    <div
      className="shrink-0 flex flex-col gap-1 px-3 py-2 min-w-[260px] max-w-[340px] border-r border-[var(--border-subtle)]"
      style={{
        borderLeftWidth: "2px",
        borderLeftStyle: "solid",
        borderLeftColor: accentColor,
        opacity: isStale ? 0.4 : 1,
        transition: "opacity 0.5s ease-out",
      }}
    >
      {/* Header: symbol, timeframe, bias, age */}
      <div className="flex items-center gap-1.5">
        <span className="text-[0.55rem] font-bold text-[var(--text-primary)] font-data">
          {data.symbol}
        </span>
        <span className="text-[0.5rem] text-[var(--text-muted)] bg-[var(--bg-elevated)] px-1 rounded">
          {data.timeframe.toUpperCase()}
        </span>
        <span
          className="text-[0.5rem] font-semibold uppercase tracking-wider"
          style={{ color: accentColor }}
        >
          {data.action_bias}
        </span>
        <span className="ml-auto text-[0.5rem] text-[var(--text-muted)] shrink-0">
          {ageLabel}
        </span>
      </div>

      {/* AI narrative text */}
      <p className="text-[0.6rem] text-[var(--text-secondary)] italic leading-relaxed line-clamp-3 m-0">
        {data.narrative}
      </p>
    </div>
  );
}
