// dashboard/src/components/signal-scorecard.tsx
"use client";

import type { SignalScorecardData } from "@/lib/types";
import { stripPluginPrefix } from "@/lib/plugin-utils";

export function SignalScorecard({ data }: { data: SignalScorecardData | undefined }) {
  if (!data || data.ranked.length === 0) {
    return (
      <span className="text-[0.6rem] italic text-[var(--text-muted)]">
        No signals this bar
      </span>
    );
  }

  const firedCount = data.ranked.length;
  const suppressedCount = data.ranked.filter((r) => !r.regime_eligible).length;
  const winner = data.ranked.find((r) => r.is_winner);

  const sorted = [...data.ranked].sort((a, b) => b.adjusted_rank - a.adjusted_rank);

  return (
    <div className="flex flex-col gap-1.5">
      {/* Summary header */}
      <div className="text-[0.55rem] text-[var(--text-muted)]">
        {firedCount} fired · {suppressedCount} regime-gated · winner:{" "}
        <span className="text-[var(--text-secondary)]">
          {winner ? stripPluginPrefix(winner.plugin) : "none"}
        </span>
      </div>

      {/* Signal rows */}
      {sorted.map((signal, idx) => {
        const isWinner = signal.is_winner;
        const isHighQuality = signal.calibrated_confidence >= 0.40;
        const dotColor = isWinner
          ? isHighQuality ? "var(--blue)" : "var(--amber)"
          : "var(--text-muted)";
        const dirArrow =
          signal.direction > 0 ? "▲" : signal.direction < 0 ? "▼" : "–";
        const dirColor =
          signal.direction > 0
            ? "var(--green)"
            : signal.direction < 0
              ? "var(--red)"
              : "var(--text-muted)";
        const confPct = (signal.calibrated_confidence * 100).toFixed(0) + "%";
        const displayName = stripPluginPrefix(signal.plugin);
        const rowOpacity = !isWinner && signal.calibrated_confidence < 0.40 ? 0.6 : 1.0;

        return (
          <div
            key={`${signal.plugin}-${idx}`}
            className="flex items-center gap-2 text-[0.65rem]"
            style={{ opacity: rowOpacity }}
          >
            {/* Rank + dot */}
            <span style={{ color: dotColor, fontFamily: "monospace" }}>
              {isWinner ? "●" : "○"}
            </span>

            {/* Winner badge */}
            {isWinner && isHighQuality && (
              <span
                className="text-[0.4rem] font-bold uppercase px-0.5 rounded"
                style={{ backgroundColor: "rgba(59,130,246,0.15)", color: "var(--blue)" }}
              >
                hero
              </span>
            )}

            {/* Plugin name */}
            <span
              className="flex-1 font-data truncate"
              style={{ color: isWinner ? "var(--text-primary)" : "var(--text-secondary)" }}
            >
              {displayName}
            </span>

            {/* Direction arrow */}
            <span style={{ color: dirColor }}>{dirArrow}</span>

            {/* Confidence */}
            <span className="font-data text-[var(--text-muted)]">{confPct}</span>

            {/* Eligibility */}
            {signal.regime_eligible ? (
              <span style={{ color: "var(--green)" }}>✓</span>
            ) : (
              <span style={{ color: "#f59e0b" }} className="whitespace-nowrap">
                ✗
              </span>
            )}
          </div>
        );
      })}
    </div>
  );
}
