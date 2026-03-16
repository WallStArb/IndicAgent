// dashboard/src/components/signals/cluster-strip.tsx
"use client";

import { useState, useEffect } from "react";
import { getApiBase } from "@/lib/api";
import type { LedgerSignal } from "@/lib/types";
import { fmtNum } from "@/lib/format";

interface ClusterEvent {
  barTs: string;         // ISO bar timestamp — cluster key
  tf: string;
  symbols: string[];
  setups: string[];
  avgConf: number;
  diversityScore: number; // distinct_setups / symbols.length
}

const CLUSTER_MIN_SYMBOLS = 3;
const CLUSTER_WINDOW_MS = 5 * 60 * 1000; // 5 minutes

/**
 * ClusterStrip detects clusters from the recent signals API.
 * Fetches /api/signals/recent?tier=all&limit=200 every 30s and
 * groups by (bar_ts ≈ timestamp rounded to 1m, timeframe).
 */
export function ClusterStrip({
  onClusterClick,
}: {
  onClusterClick: (symbols: string[]) => void;
}) {
  const [clusters, setClusters] = useState<ClusterEvent[]>([]);

  useEffect(() => {
    const controller = new AbortController();
    const detect = async () => {
      try {
        const res = await fetch(
          `${getApiBase()}/api/signals/recent?tier=all&limit=200`,
          { signal: controller.signal }
        );
        if (!res.ok) return;

        const data: { signals: LedgerSignal[] } = await res.json();
        const now = Date.now();
        const cutoff = now - CLUSTER_WINDOW_MS;

        // Group by (minute-truncated timestamp, timeframe)
        const byBar = new Map<string, LedgerSignal[]>();
        for (const sig of data.signals) {
          const ts = sig.computed_at ? new Date(sig.computed_at).getTime() : 0;
          if (ts < cutoff) continue;

          // Truncate to minute
          const minuteTs = new Date(Math.floor(ts / 60_000) * 60_000).toISOString();
          const key = `${minuteTs}|${sig.timeframe}`;
          if (!byBar.has(key)) byBar.set(key, []);
          byBar.get(key)!.push(sig);
        }

        const found: ClusterEvent[] = [];
        for (const [key, sigs] of byBar.entries()) {
          if (sigs.length < CLUSTER_MIN_SYMBOLS) continue;

          const [barTs, tf] = key.split("|");
          const symbols = [...new Set(sigs.map((s) => s.symbol))];
          if (symbols.length < CLUSTER_MIN_SYMBOLS) continue;

          const setups = [...new Set(sigs.map((s) => s.setup_plugin))];
          const avgConf = sigs.reduce((a, b) => a + (b.confidence ?? 0), 0) / sigs.length;
          const diversityScore = setups.length / symbols.length;
          found.push({ barTs, tf, symbols, setups, avgConf, diversityScore });
        }

        setClusters(found.sort((a, b) => b.symbols.length - a.symbols.length));
      } catch (err) {
        if (err.name === 'AbortError') {
          // AbortError is expected when component unmounts
          return;
        }
        console.error("Failed to fetch clusters:", err);
      }
    };

    detect();
    const t = setInterval(detect, 30_000);

    return () => {
      clearInterval(t);
      controller.abort();
    };
  }, []);

  if (clusters.length === 0) return null;

  return (
    <div className="flex flex-col gap-2">
      {clusters.map((c, i) => {
        const isConfluence = c.diversityScore >= 0.6;
        const label = isConfluence ? "Confluence" : "Correlated";
        const color = isConfluence ? "var(--cyan)" : "var(--amber)";

        const timeStr = new Date(c.barTs).toLocaleTimeString([], {
          hour: "2-digit",
          minute: "2-digit",
          hour12: false,
          timeZone: "UTC",
        });

        return (
          <button
            key={i}
            onClick={() => onClusterClick(c.symbols)}
            className="w-full flex items-center gap-3 px-3 py-2 rounded text-left transition-opacity hover:opacity-80"
            style={{
              background: isConfluence ? "rgba(0,220,255,0.05)" : "rgba(255,179,71,0.06)",
              border: `1px solid ${color}`,
            }}
          >
            <span className="text-[0.6rem] font-bold uppercase tracking-widest" style={{ color }}>
              {label}
            </span>
            <span className="text-[0.62rem] font-data text-[var(--text-secondary)]">
              {timeStr} · {c.tf} · {c.symbols.length} symbols · avg conf {fmtNum(c.avgConf, 2)} · {c.setups.length} distinct setup{c.setups.length !== 1 ? "s" : ""}
            </span>
            <span className="text-[0.55rem] text-[var(--text-muted)] flex-1 truncate">
              [{c.symbols.join(" ")}]
            </span>
          </button>
        );
      })}
    </div>
  );
}
