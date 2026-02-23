// dashboard/src/components/timeframe-matrix.tsx
"use client";

import type { TfSignalMap, ConfluenceData } from "@/lib/types";
import { TIMEFRAMES } from "@/lib/types";

interface TimeframeMatrixProps {
  tfSignals: TfSignalMap;
  confluence: ConfluenceData | null;
  activeTf: string;
  onSelectTf: (tf: string) => void;
}

const STALE_THRESHOLD_MS = 5 * 60 * 1000;

export function TimeframeMatrix({
  tfSignals,
  confluence,
  activeTf,
  onSelectTf,
}: TimeframeMatrixProps) {
  const aligned = confluence?.ctf_timeframes_aligned ?? 0;
  const showConfluence = aligned >= 4;

  return (
    <div className="px-2 py-2 flex items-center gap-1.5 flex-wrap border-b border-[var(--border-subtle)]">
      <span className="text-[0.5rem] font-semibold uppercase tracking-widest text-[var(--text-muted)] shrink-0">
        TF
      </span>

      {TIMEFRAMES.map(({ value, short }) => {
        const sig = tfSignals[value];
        const isStale = sig && Date.now() - sig.updatedAt > STALE_THRESHOLD_MS;
        const direction = sig && !isStale ? sig.direction : null;
        const isActive = activeTf === value;

        const bgColor =
          direction === "long"
            ? "var(--green-dim)"
            : direction === "short"
              ? "var(--red-dim)"
              : "var(--bg-elevated)";

        const textColor =
          direction === "long"
            ? "var(--green)"
            : direction === "short"
              ? "var(--red)"
              : "var(--text-muted)";

        return (
          <button
            key={value}
            onClick={() => onSelectTf(value)}
            className="rounded px-1.5 py-0.5 text-[0.5rem] font-bold uppercase tracking-wider cursor-pointer transition-all duration-150"
            style={{
              backgroundColor: bgColor,
              color: textColor,
              outline: isActive ? `1px solid ${textColor}` : "none",
              opacity: isStale ? 0.4 : 1,
            }}
          >
            {short}
          </button>
        );
      })}

      {showConfluence && (
        <span
          className="ml-auto text-[0.45rem] font-bold uppercase tracking-widest px-1.5 py-0.5 rounded"
          style={{
            backgroundColor:
              (confluence?.ctf_score ?? 0) > 0
                ? "var(--green-dim)"
                : "var(--red-dim)",
            color:
              (confluence?.ctf_score ?? 0) > 0
                ? "var(--green)"
                : "var(--red)",
          }}
        >
          CONFLUENCE {aligned}/6
        </span>
      )}
    </div>
  );
}
