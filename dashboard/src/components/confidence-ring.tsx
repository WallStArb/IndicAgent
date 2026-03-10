// dashboard/src/components/confidence-ring.tsx
"use client";

import type { ConfluenceData, SignalData } from "@/lib/types";

interface ConfidenceRingProps {
  confluence: ConfluenceData | null;
  signal: SignalData | null;
  price: number;
}

/** Derive a 0–100 confidence score from I6 + I7 data */
function deriveConfidence(
  confluence: ConfluenceData | null,
  signal: SignalData | null
): number {
  const ctf = confluence?.ctf_score ?? 0; // -1 to +1
  const sig = signal?.confidence ?? 0;    // 0 to 1
  // Weight: 60% CTF alignment, 40% signal confidence
  const raw = Math.abs(ctf) * 0.6 + sig * 0.4;
  return Math.round(Math.min(raw, 1) * 100);
}

export function ConfidenceRing({ confluence, signal, price }: ConfidenceRingProps) {
  const score = deriveConfidence(confluence, signal);
  const isLong = signal?.direction === "long";
  const isShort = signal?.direction === "short";
  const hasSignal = signal !== null;

  // Ring color
  const ringColor =
    score < 40
      ? "var(--border-bright)"
      : score < 65
        ? "var(--cyan)"
        : hasSignal && isLong
          ? "var(--green)"
          : hasSignal && isShort
            ? "var(--red)"
            : "var(--cyan)";

  const shouldPulse = score > 80;

  // SVG ring math
  const R = 36;
  const C = 2 * Math.PI * R;
  const filled = (score / 100) * C;
  const dash = `${filled} ${C - filled}`;

  return (
    <div className="flex flex-col items-center gap-1 py-3">
      <div
        className={`relative ${shouldPulse ? "ring-pulse" : ""}`}
        style={{ width: 96, height: 96 }}
      >
        <svg width={96} height={96} className="-rotate-90" style={{ position: "absolute" }}>
          {/* Track */}
          <circle
            cx={48} cy={48} r={R}
            fill="none"
            stroke="var(--bg-elevated)"
            strokeWidth={6}
          />
          {/* Fill */}
          <circle
            cx={48} cy={48} r={R}
            fill="none"
            stroke={ringColor}
            strokeWidth={6}
            strokeDasharray={dash}
            strokeLinecap="round"
            style={{ transition: "stroke-dasharray 0.4s ease, stroke 0.4s ease" }}
          />
        </svg>
        {/* Center content */}
        <div className="absolute inset-0 flex flex-col items-center justify-center">
          <span
            className="text-xs font-bold font-data leading-none"
            style={{ color: ringColor }}
          >
            {score}
          </span>
          <span className="text-[0.45rem] text-[var(--text-muted)] uppercase tracking-widest">
            conf
          </span>
        </div>
      </div>

      {/* Price below ring */}
      <span className="text-sm font-bold font-data text-[var(--text-primary)]">
        {price > 0 ? price.toFixed(2) : "—"}
      </span>

      {/* Direction badge */}
      {hasSignal && (
        <span
          className="text-[0.5rem] font-bold uppercase tracking-widest px-1.5 py-0 rounded"
          style={{
            backgroundColor: isLong ? "var(--green-dim)" : "var(--red-dim)",
            color: isLong ? "var(--green)" : "var(--red)",
          }}
        >
          {isLong ? "LONG" : "SHORT"}
        </span>
      )}
    </div>
  );
}
