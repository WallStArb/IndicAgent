"use client";

import type { PatternData } from "@/lib/types";
import { fmtNum } from "@/lib/format";

interface PatternPanelProps {
  patterns: PatternData | null;
}

/** I5 Pattern Detection — compact column layout */
export function PatternPanel({ patterns }: PatternPanelProps) {
  const p = patterns;

  const signals: {
    label: string;
    type: "bullish" | "bearish" | "neutral";
    detail: string;
  }[] = [];

  if (p?.rsi_divergence) {
    signals.push({
      label: "RSI Div",
      type: p.rsi_divergence === "bullish" ? "bullish" : "bearish",
      detail: `${fmtNum(p.rsi_div_confidence, 0)}%`,
    });
  }
  if (p?.bb_squeeze) {
    signals.push({
      label: "Squeeze",
      type: "neutral",
      detail: `×${p.squeeze_count ?? 0}`,
    });
  }
  if (p?.volume_divergence) {
    signals.push({
      label: "Vol Div",
      type: p.volume_divergence === "bullish" ? "bullish" : "bearish",
      detail: `${fmtNum(p.vol_div_confidence, 0)}%`,
    });
  }

  return (
    <div className="px-2 py-1">
      <div className="flex items-start gap-2">
        <span className="zone-label shrink-0 pt-px w-10">I5</span>
        <div className="flex flex-wrap items-center gap-x-2 gap-y-0.5">
          {signals.length > 0 ? (
            signals.map((sig) => <Pill key={sig.label} {...sig} />)
          ) : (
            <span className="text-[0.6rem] text-[var(--text-muted)] italic">
              No patterns
            </span>
          )}

          {p?.confluence_score !== undefined && (
            <span className="inline-flex items-center gap-1 whitespace-nowrap">
              <span className="text-[0.55rem] font-medium uppercase tracking-wider text-[var(--text-muted)]">
                Conf
              </span>
              <span
                className="font-data text-[0.7rem] font-bold"
                style={{
                  color:
                    p.confluence_score > 0.3
                      ? "var(--green)"
                      : p.confluence_score < -0.3
                        ? "var(--red)"
                        : "var(--text-secondary)",
                }}
              >
                {p.confluence_score > 0 ? "+" : ""}
                {p.confluence_score.toFixed(2)}
              </span>
            </span>
          )}
        </div>
      </div>
    </div>
  );
}

function Pill({
  label,
  type,
  detail,
}: {
  label: string;
  type: "bullish" | "bearish" | "neutral";
  detail: string;
}) {
  const styles = {
    bullish: "bg-[var(--green-dim)] text-[var(--green)]",
    bearish: "bg-[var(--red-dim)] text-[var(--red)]",
    neutral: "bg-[var(--amber-dim)] text-[var(--amber)]",
  };

  return (
    <span
      className={`inline-flex items-center gap-0.5 px-1.5 py-0 rounded text-[0.55rem] font-semibold uppercase tracking-wider ${styles[type]}`}
    >
      {label}
      <span className="opacity-70">{detail}</span>
    </span>
  );
}
