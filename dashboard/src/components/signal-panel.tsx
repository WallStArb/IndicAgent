"use client";

import type { SignalData } from "@/lib/types";
import { fmtPrice, fmtNum } from "@/lib/format";

interface SignalPanelProps {
  signal: SignalData | null;
}

/** I7 Active signal — compact 2-row panel inside SymbolCard */
export function SignalPanel({ signal }: SignalPanelProps) {
  if (!signal) {
    return (
      <div className="px-2 py-1">
        <div className="flex items-center gap-2">
          <span className="zone-label shrink-0 w-10">SIG</span>
          <span className="text-[0.6rem] text-[var(--text-muted)] italic">—</span>
        </div>
      </div>
    );
  }

  const isLong = signal.direction === "long";
  const pluginShort = _abbreviatePlugin(signal.setup_plugin);
  const timeLabel = signal.timeframe || "1m";
  const timeStr = signal.timestamp
    ? new Date(signal.timestamp).toLocaleTimeString([], {
        hour: "2-digit",
        minute: "2-digit",
        hour12: false,
      })
    : null;

  const target = signal.profit_target ?? null;
  const rr = signal.risk_reward_ratio ?? 0;

  const dirColor = isLong ? "var(--green)" : "var(--red)";
  const dirDim = isLong ? "var(--green-dim)" : "var(--red-dim)";

  return (
    <div className="px-2 py-1 space-y-0.5">
      {/* Row 1: label · TF · time · direction · plugin · confidence */}
      <div className="flex items-center gap-1.5 flex-wrap">
        <span className="zone-label shrink-0 w-10">SIG</span>

        {/* TF badge */}
        <span
          className="inline-flex items-center px-1 py-0 rounded text-[0.5rem] font-bold uppercase tracking-wider"
          style={{ backgroundColor: dirDim, color: dirColor }}
        >
          {timeLabel}
        </span>

        {/* Timestamp */}
        {timeStr && (
          <span className="text-[0.55rem] font-data text-[var(--text-muted)]">
            {timeStr}
          </span>
        )}

        {/* Direction badge */}
        <span
          className="inline-flex items-center px-1.5 py-0 rounded text-[0.55rem] font-bold uppercase tracking-widest"
          style={{ backgroundColor: dirDim, color: dirColor }}
        >
          {isLong ? "LONG" : "SHORT"}
        </span>

        {/* Setup plugin */}
        <span className="text-[0.6rem] text-[var(--text-muted)] font-medium">
          {pluginShort}
        </span>

        {/* Confidence */}
        <span className="text-[0.6rem] font-data" style={{ color: dirColor }}>
          {fmtNum(signal.confidence * 100, 0)}%
        </span>
      </div>

      {/* Row 2: entry · stop · target · RR */}
      <div className="flex items-center gap-2 pl-[3.25rem] flex-wrap">
        <span className="text-[0.55rem] text-[var(--text-muted)] whitespace-nowrap">
          <span className="opacity-60">E </span>
          <span className="font-data text-[var(--text-secondary)]">{fmtPrice(signal.entry_price)}</span>
        </span>

        <span className="opacity-40 text-[0.5rem]">·</span>

        <span className="text-[0.55rem] text-[var(--text-muted)] whitespace-nowrap">
          <span className="opacity-60">SL </span>
          <span className="font-data" style={{ color: "var(--red)" }}>{fmtPrice(signal.stop_loss)}</span>
        </span>

        {target !== null && (
          <>
            <span className="opacity-40 text-[0.5rem]">·</span>
            <span className="text-[0.55rem] text-[var(--text-muted)] whitespace-nowrap">
              <span className="opacity-60">TP </span>
              <span className="font-data" style={{ color: "var(--green)" }}>{fmtPrice(target)}</span>
            </span>
          </>
        )}

        {rr > 0 && (
          <>
            <span className="opacity-40 text-[0.5rem]">·</span>
            <span
              className="text-[0.55rem] font-data font-bold whitespace-nowrap"
              style={{ color: dirColor }}
            >
              {fmtNum(rr, 1)}R
            </span>
          </>
        )}
      </div>
    </div>
  );
}

/** Shorten plugin name for compact display.
 *  "trad_TrendFollowing" → "TrendF"  |  "MeanRev" stays as-is */
function _abbreviatePlugin(name: string): string {
  const bare = name.replace(/^(ind_|patt_|ctx_|smc_|trad_)/, "");
  if (bare.length <= 8) return bare;
  return bare.slice(0, 6);
}
