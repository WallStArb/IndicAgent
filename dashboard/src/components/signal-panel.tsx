"use client";

import type { SignalData } from "@/lib/types";
import { fmtPrice, fmtNum, stalenessRatio, tfToMinutes } from "@/lib/format";

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

  const labels = signal.target_labels ?? [];
  const t1 = signal.profit_target ?? null;
  const t2 = signal.profit_target_2 ?? null;
  const t3 = signal.profit_target_3 ?? null;
  const rr1 = signal.rr_t1 ?? signal.risk_reward_ratio ?? 0;
  const rr2 = signal.rr_t2 ?? 0;
  const rr3 = signal.rr_t3 ?? 0;
  const isStructural = signal.framing_method === "structural";

  const tfMinutes = tfToMinutes(signal.timeframe);
  const staleness = stalenessRatio(signal.timestamp, tfMinutes);
  const lagS = signal.pipeline_lag_s ?? null;
  const lagStr = lagS !== null ? `+${lagS < 1 ? lagS.toFixed(2) : lagS.toFixed(1)}s` : null;

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

        {/* Pipeline lag — only shown when available (live signals only, not backfill) */}
        {lagStr && (
          <span className="text-[0.5rem] font-data text-[var(--text-muted)] opacity-60">
            {lagStr}
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

      {/* Row 2: entry · stop · T1 label · T1 RR */}
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

        {t1 !== null && (
          <>
            <span className="opacity-40 text-[0.5rem]">·</span>
            <span className="text-[0.55rem] text-[var(--text-muted)] whitespace-nowrap">
              <span className="opacity-60">T1 </span>
              <span className="font-data" style={{ color: "var(--green)" }}>{fmtPrice(t1)}</span>
              {labels[0] && (
                <span className="opacity-50 ml-0.5">{_abbreviateLabel(labels[0])}</span>
              )}
            </span>
            {rr1 > 0 && (
              <span className="text-[0.55rem] font-data font-bold whitespace-nowrap" style={{ color: dirColor }}>
                {fmtNum(rr1, 1)}R
              </span>
            )}
          </>
        )}
      </div>

      {/* Row 3: T2 + T3 — only shown when available */}
      {t2 !== null && (
        <div className="flex items-center gap-2 pl-[3.25rem] flex-wrap">
          <span className="text-[0.55rem] text-[var(--text-muted)] whitespace-nowrap">
            <span className="opacity-60">T2 </span>
            <span className="font-data" style={{ color: "var(--green)" }}>{fmtPrice(t2)}</span>
            {labels[1] && (
              <span className="opacity-50 ml-0.5">{_abbreviateLabel(labels[1])}</span>
            )}
            {rr2 > 0 && (
              <span className="font-data font-bold ml-1" style={{ color: dirColor }}>{fmtNum(rr2, 1)}R</span>
            )}
          </span>

          {t3 !== null && isStructural && (
            <>
              <span className="opacity-40 text-[0.5rem]">·</span>
              <span className="text-[0.55rem] text-[var(--text-muted)] whitespace-nowrap">
                <span className="opacity-60">T3 </span>
                <span className="font-data" style={{ color: "var(--green)" }}>{fmtPrice(t3)}</span>
                {labels[2] && (
                  <span className="opacity-50 ml-0.5">{_abbreviateLabel(labels[2])}</span>
                )}
                {rr3 > 0 && (
                  <span className="font-data font-bold ml-1" style={{ color: dirColor }}>{fmtNum(rr3, 1)}R</span>
                )}
              </span>
            </>
          )}
        </div>
      )}

      {/* Staleness ratio — shown only when >= 1.0× (one full bar has elapsed) */}
      {staleness !== null && (
        <div className="pl-[3.25rem]">
          <span
            className="text-[0.5rem] font-data"
            style={{
              // TODO(v1.4-feedback): replace fixed thresholds with p80/p95 from signal_ledger
              color: staleness >= 2.0 ? "var(--red-dim)" : "#f59e0b",
              opacity: 0.7,
            }}
          >
            {staleness.toFixed(1)}× stale
          </span>
        </div>
      )}
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

/** Extract short level type from a target label for compact display.
 *  "BSL (sig=0.72) 4525.00" → "BSL"
 *  "VWAP+1σ 4530.00"        → "VWAP+1σ"
 *  "FVG top 4528.00"        → "FVG"
 *  "ATR T1"                 → "ATR"
 */
function _abbreviateLabel(label: string): string {
  if (!label) return "";
  const word = label.split(" ")[0];
  // Trim trailing punctuation/parens
  return word.replace(/[().,]+$/, "");
}
