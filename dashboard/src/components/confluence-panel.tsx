"use client";

import type { ConfluenceData } from "@/lib/types";

interface ConfluencePanelProps {
  confluence: ConfluenceData | null;
}

const TF_LABELS: Record<number, string> = {
  1: "1m",
  5: "5m",
  15: "15m",
  60: "1H",
  240: "4H",
  1440: "1D",
};

/** I6 Cross-Timeframe Confluence — compact score bar */
export function ConfluencePanel({ confluence }: ConfluencePanelProps) {
  const c = confluence;
  const score = c?.ctf_score ?? 0;
  const aligned = c?.ctf_timeframes_aligned ?? 0;
  const highestTf = c?.ctf_highest_aligned_tf
    ? TF_LABELS[c.ctf_highest_aligned_tf] ?? `${c.ctf_highest_aligned_tf}m`
    : null;

  const hasData = c && c.ctf_score !== undefined;

  // Bar position: 0 = center (neutral), -1 = full left, +1 = full right
  const pct = ((score + 1) / 2) * 100; // 0–100
  const barColor =
    score > 0.2
      ? "var(--green)"
      : score < -0.2
        ? "var(--red)"
        : "var(--amber)";

  return (
    <div className="px-2 py-1">
      <div className="flex items-start gap-2">
        <span className="zone-label shrink-0 pt-px w-10">CTF</span>

        {hasData ? (
          <div className="flex-1 flex items-center gap-2 min-w-0">
            {/* Score bar */}
            <div className="flex-1 relative h-2.5 rounded-sm bg-[var(--bg-base)] overflow-hidden">
              {/* Center line */}
              <div className="absolute left-1/2 top-0 bottom-0 w-px bg-[var(--border-bright)]" />
              {/* Fill */}
              <div
                className="absolute top-0 bottom-0 rounded-sm transition-all duration-300"
                style={{
                  left: score >= 0 ? "50%" : `${pct}%`,
                  width: `${Math.abs(score) * 50}%`,
                  backgroundColor: barColor,
                  opacity: 0.8,
                }}
              />
            </div>

            {/* Score value */}
            <span
              className="font-data text-[0.7rem] font-bold shrink-0 w-8 text-right"
              style={{ color: barColor }}
            >
              {score > 0 ? "+" : ""}
              {score.toFixed(2)}
            </span>

            {/* Aligned count */}
            <span className="text-[0.55rem] font-medium text-[var(--text-muted)] shrink-0 whitespace-nowrap">
              {aligned}/4 TFs
            </span>

            {/* Highest aligned TF */}
            {highestTf && (
              <span
                className="inline-flex px-1 py-0 rounded text-[0.5rem] font-semibold uppercase tracking-wider"
                style={{
                  backgroundColor:
                    score > 0
                      ? "var(--green-dim)"
                      : score < 0
                        ? "var(--red-dim)"
                        : "var(--amber-dim)",
                  color: barColor,
                }}
              >
                {highestTf}
              </span>
            )}
          </div>
        ) : (
          <span className="text-[0.6rem] text-[var(--text-muted)] italic">
            Awaiting data
          </span>
        )}
      </div>
    </div>
  );
}
