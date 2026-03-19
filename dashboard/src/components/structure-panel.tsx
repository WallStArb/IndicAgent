"use client";

import type { StructureData } from "@/lib/types";
import { fmtPrice, fmtNum } from "@/lib/format";
import { ZoneLabel, MiniBar, Metric } from "./ui/metric-components";

interface StructurePanelProps {
  structure: StructureData | null;
}

/** I3 Market Structure — compact column layout */
export function StructurePanel({ structure }: StructurePanelProps) {
  const s = structure;

  const trendIcon =
    s?.swing_trend === "uptrend"
      ? "▲"
      : s?.swing_trend === "downtrend"
        ? "▼"
        : "◆";
  const trendColor =
    s?.swing_trend === "uptrend"
      ? "text-up"
      : s?.swing_trend === "downtrend"
        ? "text-down"
        : "text-neutral";

  return (
    <div className="px-2 py-1">
      <div className="flex items-start gap-2">
        <ZoneLabel tier="I3" />
        <div className="flex flex-wrap items-center gap-x-3 gap-y-0.5">
          {/* Trend */}
          <span className="inline-flex items-center gap-1 whitespace-nowrap">
            <span className={`font-data text-xs font-semibold ${trendColor}`}>
              {trendIcon}
            </span>
            <span className="text-[0.65rem] text-[var(--text-accent)]">
              {s?.swing_trend ?? "—"}
            </span>
            {s?.swing_score !== undefined && (
              <span className="font-data text-[0.55rem] text-[var(--text-muted)]">
                ({fmtNum(s.swing_score, 2)})
              </span>
            )}
          </span>

          {/* Swings */}
          {s?.swing_sequence && (
            <Metric label="Swings" value={s.swing_sequence} valueClassName="text-[var(--text-accent)]" />
          )}

          {/* Integrity bar */}
          {s?.trend_integrity !== undefined && (
            <span className="inline-flex items-center gap-1 whitespace-nowrap">
              <Metric label="Int" value={<MiniBar value={s.trend_integrity} color={s.trend_integrity >= 0.7 ? "var(--green)" : s.trend_integrity >= 0.4 ? "var(--amber)" : "var(--red)"} />} />
            </span>
          )}

          {/* S/R */}
          <span className="inline-flex items-center gap-1 whitespace-nowrap">
            <span className="w-1.5 h-1.5 rounded-sm bg-[var(--green)]" />
            <span className="text-[0.55rem] text-[var(--text-muted)]">S</span>
            <span className="font-data text-[0.7rem] font-medium text-up">
              {fmtPrice(s?.nearest_support)}
            </span>
            {s?.support_strength !== undefined && (
              <span className="font-data text-[0.5rem] text-[var(--text-muted)]">
                ×{s.support_strength}
              </span>
            )}
          </span>
          <span className="inline-flex items-center gap-1 whitespace-nowrap">
            <span className="w-1.5 h-1.5 rounded-sm bg-[var(--red)]" />
            <span className="text-[0.55rem] text-[var(--text-muted)]">R</span>
            <span className="font-data text-[0.7rem] font-medium text-down">
              {fmtPrice(s?.nearest_resistance)}
            </span>
            {s?.resistance_strength !== undefined && (
              <span className="font-data text-[0.5rem] text-[var(--text-muted)]">
                ×{s.resistance_strength}
              </span>
            )}
          </span>
        </div>
      </div>
    </div>
  );
}
