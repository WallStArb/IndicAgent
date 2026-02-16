"use client";

import type { SmartMoneyData } from "@/lib/types";
import { fmtPrice, fmtNum } from "@/lib/format";

interface SmartMoneyPanelProps {
  smartMoney: SmartMoneyData | null;
}

/** SMC Smart Money Concepts — compact row layout */
export function SmartMoneyPanel({ smartMoney }: SmartMoneyPanelProps) {
  const s = smartMoney;

  const signals: {
    label: string;
    type: "bullish" | "bearish" | "neutral";
    detail: string;
  }[] = [];

  // BOS / CHoCH
  if (s?.choch_detected) {
    signals.push({
      label: "CHoCH",
      type: s.choch_direction === 1 ? "bullish" : "bearish",
      detail: s.choch_direction === 1 ? "Bull" : "Bear",
    });
  } else if (s?.bos_detected) {
    signals.push({
      label: "BOS",
      type: s.bos_direction === 1 ? "bullish" : s.bos_direction === -1 ? "bearish" : "neutral",
      detail: s.bos_level ? fmtPrice(s.bos_level) : "",
    });
  }

  // Fair Value Gap
  if (s?.fvg_type && s.fvg_type !== 0) {
    signals.push({
      label: "FVG",
      type: s.fvg_type > 0 ? "bullish" : "bearish",
      detail: `${fmtNum(s.fvg_open_count, 0)} open`,
    });
  }

  // Order Blocks
  if (s?.ob_type && s.ob_type !== 0) {
    signals.push({
      label: "OB",
      type: s.ob_type > 0 ? "bullish" : "bearish",
      detail: `${fmtNum((s.ob_strength ?? 0) * 100, 0)}%`,
    });
  }

  // Liquidity Sweeps
  if (s?.sweep_detected) {
    signals.push({
      label: "Sweep",
      type: s.sweep_type === 1 ? "bullish" : "bearish",
      detail: s.sweep_reclaimed ? "Reclaimed" : `${fmtNum(s.sweep_depth_pct, 2)}%`,
    });
  }

  return (
    <div className="px-2 py-1">
      <div className="flex items-start gap-2">
        <span className="zone-label shrink-0 pt-px w-10">SMC</span>
        <div className="flex flex-wrap items-center gap-x-2 gap-y-0.5">
          {signals.length > 0 ? (
            signals.map((sig) => <Pill key={sig.label} {...sig} />)
          ) : (
            <span className="text-[0.6rem] text-[var(--text-muted)] italic">
              No signals
            </span>
          )}

          {/* Change Point probability */}
          {s?.cp_probability !== undefined && s.cp_probability > 0.01 && (
            <span className="inline-flex items-center gap-1 whitespace-nowrap">
              <span className="text-[0.55rem] font-medium uppercase tracking-wider text-[var(--text-muted)]">
                CP
              </span>
              <span
                className="font-data text-[0.7rem] font-bold"
                style={{
                  color: s.cp_detected
                    ? "var(--amber)"
                    : "var(--text-secondary)",
                }}
              >
                {(s.cp_probability * 100).toFixed(0)}%
              </span>
              {s.cp_detected && (
                <span className="w-1.5 h-1.5 rounded-full bg-[var(--amber)] animate-pulse" />
              )}
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
      {detail && <span className="opacity-70">{detail}</span>}
    </span>
  );
}
