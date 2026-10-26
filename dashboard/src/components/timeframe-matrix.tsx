// dashboard/src/components/timeframe-matrix.tsx
"use client";

import type { ConfluenceData } from "@/lib/types";
import { TIMEFRAMES } from "@/lib/types";
import { ChevronRight } from "lucide-react";

interface TimeframeMatrixProps {
  confluence: ConfluenceData | null;
  activeTf: string;
  onSelectTf: (tf: string) => void;
  onDrillDown?: () => void;
  /** Compact mode: no wrapper border/padding, no drill-down, no TF label */
  compact?: boolean;
}

export function TimeframeMatrix({
  confluence,
  activeTf,
  onSelectTf,
  onDrillDown,
  compact = false,
}: TimeframeMatrixProps) {
  const aligned = confluence?.ctf_timeframes_aligned ?? 0;
  const showConfluence = aligned >= 4;

  const handleMatrixClick = (e: React.MouseEvent) => {
    if (compact) return;
    if (!(e.target as HTMLElement).closest('[data-tf-button]')) {
      onDrillDown?.();
    }
  };

  if (compact) {
    return (
      <div className="flex items-center gap-1">
        {TIMEFRAMES.map(({ value, short }) => {
          const isActive = activeTf === value;
          const bgColor = "var(--bg-base)";
          const textColor = isActive ? "var(--text-primary)" : "var(--text-muted)";
          return (
            <button
              key={value}
              data-tf-button="true"
              onClick={(e) => { e.stopPropagation(); onSelectTf(value); }}
              className="rounded px-1.5 py-0.5 text-[0.5rem] font-bold uppercase tracking-wider cursor-pointer transition-all duration-150"
              style={{
                backgroundColor: bgColor,
                color: textColor,
                outline: isActive ? `1px solid ${textColor}` : "none",
              }}
            >
              {short}
            </button>
          );
        })}
      </div>
    );
  }

  return (
    <div
      onClick={handleMatrixClick}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          onDrillDown?.();
        }
      }}
      className="px-2 py-2 flex items-center gap-1.5 flex-wrap border-b border-[var(--border-subtle)] cursor-pointer hover:bg-[var(--bg-elevated)] transition-colors"
      role={onDrillDown ? "button" : undefined}
      tabIndex={onDrillDown ? 0 : undefined}
    >
      <span className="text-[0.5rem] font-semibold uppercase tracking-widest text-[var(--text-muted)] shrink-0">
        TF
      </span>

      {TIMEFRAMES.map(({ value, short }) => {
        const isActive = activeTf === value;
        const bgColor = "var(--bg-elevated)";
        const textColor = isActive ? "var(--text-primary)" : "var(--text-muted)";

        return (
          <button
            key={value}
            data-tf-button="true"
            onClick={(e) => {
              e.stopPropagation();
              onSelectTf(value);
            }}
            className="rounded px-1.5 py-0.5 text-[0.5rem] font-bold uppercase tracking-wider cursor-pointer transition-all duration-150"
            style={{
              backgroundColor: bgColor,
              color: textColor,
              outline: isActive ? `1px solid ${textColor}` : "none",
            }}
          >
            {short}
          </button>
        );
      })}

      {showConfluence ? (
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
      ) : onDrillDown && (
        <ChevronRight size={10} className="ml-auto text-[var(--text-muted)] opacity-50 hover:opacity-100 transition-opacity" />
      )}
    </div>
  );
}
