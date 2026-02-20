"use client";

import type { SignalData } from "@/lib/types";
import { fmtPrice, fmtNum } from "@/lib/format";

interface SignalPanelProps {
  signal: SignalData | null;
}

/** I7 Active signal — compact row inside SymbolCard */
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

  return (
    <div className="px-2 py-1">
      <div className="flex items-center gap-2 flex-wrap">
        <span className="zone-label shrink-0 w-10">SIG</span>

        {/* Direction badge */}
        <span
          className={`inline-flex items-center px-1.5 py-0 rounded text-[0.55rem] font-bold uppercase tracking-widest ${
            isLong
              ? "bg-[var(--green-dim)] text-[var(--green)]"
              : "bg-[var(--red-dim)] text-[var(--red)]"
          }`}
        >
          {isLong ? "LONG" : "SHORT"}
        </span>

        {/* Setup plugin abbreviation */}
        <span className="text-[0.6rem] text-[var(--text-muted)] font-medium">
          {pluginShort}
        </span>

        {/* Confidence */}
        <span className="text-[0.6rem] font-data text-[var(--text-secondary)]">
          {fmtNum(signal.confidence * 100, 0)}%
        </span>

        {/* Entry → Stop */}
        <span className="text-[0.6rem] font-data text-[var(--text-muted)] whitespace-nowrap">
          {fmtPrice(signal.entry_price)}
          <span className="opacity-40 mx-0.5">→</span>
          {fmtPrice(signal.stop_loss)}
        </span>
      </div>
    </div>
  );
}

/** Shorten plugin name for compact display.
 *  "ind_TrendFollowing" → "TrendF"  |  "MeanRev" stays as-is */
function _abbreviatePlugin(name: string): string {
  const bare = name.replace(/^(ind_|patt_|ctx_|smc_)/, "");
  if (bare.length <= 8) return bare;
  return bare.slice(0, 6);
}
