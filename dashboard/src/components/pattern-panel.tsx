"use client";

import type { PatternData } from "@/lib/types";
import { fmtNum } from "@/lib/format";
import { ZoneLabel, DirectionalPill, Metric } from "./ui/metric-components";

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
        <ZoneLabel tier="I5" />
        <div className="flex flex-wrap items-center gap-x-2 gap-y-0.5">
          {signals.length > 0 ? (
            signals.map((sig) => <DirectionalPill key={sig.label} {...sig} />)
          ) : (
            <span className="text-[0.6rem] text-[var(--text-muted)] italic">
              No patterns
            </span>
          )}

          {p?.confluence_score !== undefined && (
            <Metric
              label="Conf"
              value={
                <span
                  className="font-bold"
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
                  {fmtNum(p.confluence_score, 2)}
                </span>
              }
            />
          )}
        </div>
      </div>
    </div>
  );
}
