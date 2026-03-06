"use client";

import type { SignalData } from "@/lib/types";
import { fmtPrice, fmtNum, fmtTimeHMS, fmtLagSeconds } from "@/lib/format";

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

  if (signal.resolved) {
    const badgeLabel = _outcomeLabel(signal.outcome);
    const badgeColor =
      signal.outcome?.startsWith("target") ? "var(--green-dim)"
      : signal.outcome?.startsWith("stopped") ? "var(--red-dim)"
      : "var(--bg-secondary)";
    const badgeText =
      signal.outcome?.startsWith("target") ? "var(--green)"
      : signal.outcome?.startsWith("stopped") ? "var(--red)"
      : "var(--text-secondary)";

    return (
      <div className="px-2 py-1 space-y-0.5 opacity-50">
        <div className="flex items-center gap-1.5 flex-wrap">
          <span className="zone-label shrink-0 w-10">SIG</span>
          <span
            className="inline-flex items-center px-1 py-0 rounded text-[0.5rem] font-bold uppercase tracking-wider"
            style={{ backgroundColor: "var(--bg-secondary)", color: "var(--text-muted)" }}
          >
            {signal.timeframe || "1m"}
          </span>
          {(signal.bar_close_ts || signal.timestamp) && (
            <span className="text-[0.55rem] font-data text-[var(--text-muted)]">
              {new Date(signal.bar_close_ts ?? signal.timestamp).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false })}
            </span>
          )}
          <span
            className="inline-flex items-center px-1.5 py-0 rounded text-[0.5rem] font-bold uppercase tracking-widest"
            style={{ backgroundColor: badgeColor, color: badgeText }}
          >
            {badgeLabel}
          </span>
          <span className="text-[0.6rem] text-[var(--text-muted)] font-medium line-through">
            {_abbreviatePlugin(signal.setup_plugin)}
          </span>
        </div>
        <div className="flex items-center gap-2 pl-[3.25rem] flex-wrap">
          <span className="text-[0.55rem] text-[var(--text-muted)] whitespace-nowrap opacity-60">
            <span className="opacity-60">E </span>
            <span className="font-data">{fmtPrice(signal.entry_price)}</span>
          </span>
          {signal.exit_price && (
            <>
              <span className="opacity-40 text-[0.5rem]">→</span>
              <span className="text-[0.55rem] text-[var(--text-muted)] whitespace-nowrap opacity-60">
                <span className="opacity-60">X </span>
                <span className="font-data">{fmtPrice(signal.exit_price)}</span>
              </span>
            </>
          )}
        </div>
      </div>
    );
  }

  const isLong = signal.direction === "long";
  const pluginShort = _abbreviatePlugin(signal.setup_plugin);
  const timeLabel = signal.timeframe || "1m";
  const barStr = fmtTimeHMS(signal.bar_close_ts) ?? fmtTimeHMS(signal.timestamp);
  const computedStr = fmtTimeHMS(signal.signal_computed_at);
  const lagStr = fmtLagSeconds(signal.pipeline_lag_s);

  const labels = signal.target_labels ?? [];
  const t1 = signal.profit_target ?? null;
  const t2 = signal.profit_target_2 ?? null;
  const t3 = signal.profit_target_3 ?? null;
  const rr1 = signal.rr_t1 ?? signal.risk_reward_ratio ?? 0;
  const rr2 = signal.rr_t2 ?? 0;
  const rr3 = signal.rr_t3 ?? 0;
  const isStructural = signal.framing_method === "structural";

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

        {/* Bar close time + latency to signal */}
        {barStr && (
          <span className="text-[0.55rem] font-data text-[var(--text-muted)]">
            {barStr}
            {computedStr && lagStr && (
              <span className="opacity-50 ml-0.5">{lagStr}</span>
            )}
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

      {/* Price context: bar close / market at signal / entry zone */}
      <div className="pl-[3.25rem] space-y-0.5">
        {/* Row: BAR @ price  →  SIG @ price */}
        {(signal.bar_close_price != null || signal.market_price_at_signal != null) && (
          <div className="flex items-center gap-1.5 flex-wrap">
            {signal.bar_close_price != null && (
              <span className="text-[0.5rem] font-data text-[var(--text-muted)]">
                <span className="opacity-50">BAR </span>
                <span>{fmtPrice(signal.bar_close_price)}</span>
              </span>
            )}
            {signal.bar_close_price != null && signal.market_price_at_signal != null && (
              <span className="opacity-30 text-[0.45rem]">→</span>
            )}
            {signal.market_price_at_signal != null && (
              <span className="text-[0.5rem] font-data" style={{ color: "var(--text-secondary)" }}>
                <span className="opacity-50">SIG </span>
                {computedStr && (
                  <>
                    <span>{computedStr}</span>
                    <span className="opacity-40 mx-0.5">@</span>
                  </>
                )}
                <span>{fmtPrice(signal.market_price_at_signal)}</span>
              </span>
            )}
          </div>
        )}
        {/* Row: ZONE low – high  [✓ in zone / ✗ outside] */}
        {signal.entry_zone_low != null && signal.entry_zone_high != null && (
          <div className="flex items-center gap-1">
            <span className="text-[0.5rem] font-data text-[var(--text-muted)]">
              <span className="opacity-50">ZONE </span>
              <span>{fmtPrice(signal.entry_zone_low)}</span>
              <span className="opacity-40 mx-0.5">–</span>
              <span>{fmtPrice(signal.entry_zone_high)}</span>
            </span>
            {signal.zone_valid_at_signal != null && (
              <span
                className="text-[0.45rem] font-bold"
                style={{ color: signal.zone_valid_at_signal ? "var(--green)" : "#f59e0b" }}
              >
                {signal.zone_valid_at_signal ? "✓" : "↑"}
              </span>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

function _outcomeLabel(outcome: string | undefined): string {
  if (!outcome) return "CLOSED";
  if (outcome.startsWith("ttl_expired") || outcome === "never_activated") return "EXPIRED";
  if (outcome.startsWith("stopped")) return "STOPPED";
  if (outcome === "target_full") return "FULL TARGET";
  if (outcome === "target_1_2") return "T1+T2 HIT";
  if (outcome === "target_1") return "T1 HIT";
  return "CLOSED";
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
