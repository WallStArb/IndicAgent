"use client";

import type { SignalData } from "@/lib/types";
import { Tooltip } from "@/components/tooltip";
import { timestampTooltip } from "@/lib/signal-tooltips";
import { fmtPrice } from "@/lib/format";

interface SignalDetailHeaderProps {
  signal: SignalData;
  dirColor: string;
}

/**
 * Signal detail header: direction badge, type, confidence, timestamps.
 * Extracted for testability and reuse across signal display contexts.
 */
export function SignalDetailHeader({ signal, dirColor }: SignalDetailHeaderProps) {
  const isLong = signal.direction === "long";
  const timeStr = signal.timestamp
    ? new Date(signal.timestamp).toLocaleTimeString([], {
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
        hour12: false,
      })
    : "—";
  const sigTimeStr = signal.signal_computed_at
    ? new Date(signal.signal_computed_at).toLocaleTimeString([], {
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
        hour12: false,
      })
    : null;

  return (
    <div className="flex items-center gap-2 flex-wrap">
      <span
        className="inline-flex px-2 py-0.5 rounded text-[0.6rem] font-bold uppercase tracking-widest"
        style={{ backgroundColor: isLong ? "var(--green-dim)" : "var(--red-dim)", color: dirColor }}
      >
        {isLong ? "LONG" : "SHORT"}
      </span>
      <span className="text-[0.6rem] text-[var(--text-secondary)]">{signal.signal_type.replace(/_/g, " ")}</span>
      <span className="text-[0.6rem] font-bold font-data" style={{ color: dirColor }}>
        {signal.calibrated_confidence != null
          ? `${(signal.calibrated_confidence * 100).toFixed(0)}%`
          : `${(signal.confidence * 100).toFixed(0)}%`}
      </span>
      <span className="text-[0.55rem] text-[var(--text-muted)]">
        <Tooltip tooltip={timestampTooltip()}>
          <span>{signal.timeframe} · {timeStr}</span>
        </Tooltip>
      </span>
      {sigTimeStr && (
        <span className="text-[0.5rem] font-data text-[var(--text-muted)] opacity-70">
          sig {sigTimeStr}
          {signal.market_price_at_signal != null && (
            <span className="ml-0.5 opacity-80">@ {fmtPrice(signal.market_price_at_signal)}</span>
          )}
        </span>
      )}
    </div>
  );
}
