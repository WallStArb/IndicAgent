"use client";

import type { StructureData } from "@/lib/types";
import { fmtPrice, fmtNum } from "@/lib/format";

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
        <span className="zone-label shrink-0 pt-px w-10">I3</span>
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
            <span className="inline-flex items-baseline gap-1 whitespace-nowrap">
              <span className="text-[0.55rem] font-medium uppercase tracking-wider text-[var(--text-muted)]">
                Swings
              </span>
              <span className="font-data text-[0.7rem] text-[var(--text-accent)]">
                {s.swing_sequence}
              </span>
            </span>
          )}

          {/* Integrity bar */}
          {s?.trend_integrity !== undefined && (
            <span className="inline-flex items-center gap-1 whitespace-nowrap">
              <span className="text-[0.55rem] font-medium uppercase tracking-wider text-[var(--text-muted)]">
                Int
              </span>
              <IntegrityBar value={s.trend_integrity} />
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

function IntegrityBar({ value }: { value: number }) {
  const pct = Math.round(value * 100);
  const color =
    value >= 0.7
      ? "var(--green)"
      : value >= 0.4
        ? "var(--amber)"
        : "var(--red)";

  return (
    <>
      <div className="w-8 h-1.5 rounded-full bg-[var(--bg-base)] overflow-hidden">
        <div
          className="h-full rounded-full"
          style={{ width: `${pct}%`, backgroundColor: color }}
        />
      </div>
      <span className="font-data text-[0.55rem] text-[var(--text-muted)]">
        {pct}%
      </span>
    </>
  );
}
