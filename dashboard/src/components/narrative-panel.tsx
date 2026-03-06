"use client";

import { useMemo } from "react";
import type { NarrativeData, GroupNarrativeData } from "@/lib/types";
import { stalenessRatio, tfToMinutes } from "@/lib/format";

/** Map base symbol → asset group name (matches backend ASSET_GROUPS). */
const SYMBOL_TO_GROUP: Record<string, string> = {
  ES: "equity", NQ: "equity", RTY: "equity", YM: "equity", VX: "equity",
  CL: "energy", BZ: "energy", NG: "energy",
  GC: "metals", SI: "metals", HG: "metals", PL: "metals",
  ZN: "rates", ZF: "rates", ZB: "rates", ZT: "rates", SR1: "rates",
  "6E": "fx_crypto", "6J": "fx_crypto", BTC: "fx_crypto",
  ZS: "ag", ZC: "ag", ZW: "ag",
};

interface NarrativePanelProps {
  narratives: Record<string, NarrativeData>;
  groupNarratives: Record<string, GroupNarrativeData>;
  activeSymbol: string;       // base symbol, e.g. "ES"
  activeTimeframe: string;    // e.g. "5m"
}

const STALE_AFTER_MS = 60 * 60 * 1000;

export function NarrativePanel({
  narratives,
  groupNarratives,
  activeSymbol,
  activeTimeframe,
}: NarrativePanelProps) {
  const { displayNarrative, isGroup } = useMemo(() => {
    // Prefer per-signal narrative for active symbol+TF
    const perSignalKey = `${activeSymbol}:${activeTimeframe}`;
    const perSignal = narratives[perSignalKey];
    if (perSignal) {
      return { displayNarrative: perSignal, isGroup: false };
    }

    // Fall back to group narrative
    const group = SYMBOL_TO_GROUP[activeSymbol];
    const groupNarrative = group ? groupNarratives[group] : undefined;
    if (groupNarrative) {
      return { displayNarrative: groupNarrative, isGroup: true };
    }

    return { displayNarrative: null, isGroup: false };
  }, [narratives, groupNarratives, activeSymbol, activeTimeframe]);

  if (!displayNarrative) {
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

  if (isGroup) {
    const gn = displayNarrative as GroupNarrativeData;
    const isStale = Date.now() - gn.receivedAt > STALE_AFTER_MS;
    const group = SYMBOL_TO_GROUP[activeSymbol] ?? "group";
    return (
      <div
        className="border-t border-[var(--border-subtle)] bg-[var(--bg-surface)] shrink-0 px-3 py-2"
        style={{ opacity: isStale ? 0.45 : 1 }}
      >
        <div className="flex items-center gap-1.5 mb-1">
          <span className="text-[0.55rem] font-bold text-[var(--text-primary)] uppercase font-data">
            {group}
          </span>
          <span className="text-[0.5rem] text-[var(--text-muted)] bg-[var(--bg-elevated)] px-1 rounded">
            GROUP
          </span>
          {isStale && (
            <span className="text-[0.45rem] text-[var(--text-muted)] italic ml-auto">stale</span>
          )}
        </div>
        <p className="text-[0.6rem] text-[var(--text-secondary)] italic leading-relaxed line-clamp-3 m-0">
          {gn.narrative}
        </p>
      </div>
    );
  }

  // Per-signal narrative
  const n = displayNarrative as NarrativeData;
  return (
    <div className="border-t border-[var(--border-subtle)] bg-[var(--bg-surface)] shrink-0">
      <NarrativeCard data={n} />
    </div>
  );
}

function NarrativeCard({ data }: { data: NarrativeData }) {
  const isStale = Date.now() - data.receivedAt > STALE_AFTER_MS;
  const tfMinutes = tfToMinutes(data.timeframe);
  const staleness = stalenessRatio(data.timestamp, tfMinutes);
  const barTimeStr = data.timestamp
    ? new Date(data.timestamp).toLocaleTimeString([], {
        hour: "2-digit", minute: "2-digit", hour12: false,
      })
    : null;
  const barDate = data.timestamp ? new Date(data.timestamp) : null;
  const isToday = barDate ? barDate.toDateString() === new Date().toDateString() : true;
  const barDateStr =
    barDate && !isToday
      ? barDate.toLocaleDateString([], { month: "short", day: "numeric" })
      : null;
  const isBullish = data.action_bias === "bullish";
  const accentColor = isBullish ? "var(--green)" : "var(--red)";

  return (
    <div
      className="flex flex-col gap-1 px-3 py-2"
      style={{
        borderLeftWidth: "2px",
        borderLeftStyle: "solid",
        borderLeftColor: isStale ? "var(--border-subtle)" : accentColor,
        opacity: isStale ? 0.45 : 1,
        transition: "opacity 0.5s ease-out",
      }}
    >
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
          {barDateStr && <span className="text-[0.5rem] text-[var(--text-muted)]">{barDateStr}</span>}
          {barTimeStr && <span className="text-[0.5rem] font-data text-[var(--text-muted)]">{barTimeStr}</span>}
          {staleness !== null && (
            <span
              className="text-[0.45rem] font-data"
              style={{
                color: staleness >= 2.0 ? "var(--red-dim)" : "#f59e0b",
                opacity: 0.7,
              }}
            >
              {staleness.toFixed(1)}×
            </span>
          )}
          {isStale && staleness === null && (
            <span className="text-[0.45rem] text-[var(--text-muted)] italic">stale</span>
          )}
        </div>
      </div>
      <p className="text-[0.6rem] text-[var(--text-secondary)] italic leading-relaxed line-clamp-5 m-0">
        {data.narrative}
      </p>
    </div>
  );
}
