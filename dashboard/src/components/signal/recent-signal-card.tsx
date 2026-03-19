"use client";

import { useMemo } from "react";
import type { SignalData } from "@/lib/types";
import { fmtPrice, fmtNum, fmtPriceRange, fmtTimeHMS, fmtLagSeconds, pipelineLagS } from "@/lib/format";
import { deriveBarCloseIso, TF_OFFSETS } from "@/lib/timeframe-utils";
import { OutcomeBadge } from "@/components/outcome-badge";
import { computeSignalTier, tierColor } from "@/lib/signal-tier";
import { abbreviatePlugin } from "@/lib/signal-utils";

interface RecentSignalCardProps {
  signal: SignalData;
  isSelected: boolean;
  onClick: () => void;
}

/**
 * Compact 3-row signal card for RecentSignals sidebar.
 * Shows tier, direction, confidence, plugin, prices, and outcome.
 */
export function RecentSignalCard({ signal, isSelected, onClick }: RecentSignalCardProps) {
  const isLong = signal.direction === "long";
  const pluginShort = abbreviatePlugin(signal.setup_plugin);

  const barCloseIso = useMemo(
    () => deriveBarCloseIso(signal.bar_close_ts, signal.timestamp, signal.timeframe),
    [signal.bar_close_ts, signal.timestamp, signal.timeframe]
  );
  const signalTimeStr = useMemo(() => fmtTimeHMS(signal.signal_computed_at), [signal.signal_computed_at]);
  const ttsS = useMemo(
    () => pipelineLagS(signal.signal_computed_at, barCloseIso) ?? (signal.pipeline_lag_s ?? null),
    [signal.signal_computed_at, barCloseIso, signal.pipeline_lag_s]
  );
  const ttsStr = useMemo(() => fmtLagSeconds(ttsS), [ttsS]);

  const t1 = signal.profit_target ?? null;
  const rr1 = signal.rr_t1 ?? signal.risk_reward_ratio ?? 0;

  const dirColor = isLong ? "var(--green)" : "var(--red)";
  const dirDim = isLong ? "var(--green-dim)" : "var(--red-dim)";

  const tier = (signal as any).signal_tier ?? computeSignalTier(
    (signal as any).was_selected ?? true,
    signal.confidence,
    (signal as any).cis_score ?? null,
  );

  const pnlR = signal.pnl_r != null ? (
    <span className="font-data" style={{ color: signal.pnl_r > 0 ? "var(--green)" : "var(--red)" }}>
      {signal.pnl_r > 0 ? "+" : ""}{fmtNum(signal.pnl_r, 1)}R
    </span>
  ) : null;

  return (
    <div
      onClick={onClick}
      className={`px-2 py-1.5 rounded cursor-pointer transition-all flex flex-col gap-1 ${
        isSelected ? "ring-1 ring-[var(--accent-cyan)]" : ""
      } ${signal.resolved ? "opacity-60" : ""}`}
      style={{ background: "var(--bg-elevated)" }}
    >
      {/* Row 1: tier dot · badge · confidence · plugin · outcome · pnl | time */}
      <div className="flex items-center gap-1.5">
        <span
          className="shrink-0 w-1.5 h-1.5 rounded-full inline-block"
          style={{ backgroundColor: tierColor(tier) }}
          title={`${tier} tier`}
        />
        <span
          className="inline-flex items-center px-1.5 py-0.5 rounded text-[0.55rem] font-bold uppercase tracking-widest"
          style={{ backgroundColor: dirDim, color: dirColor }}
        >
          {isLong ? "LONG" : "SHORT"}
        </span>
        <span className="text-[0.6rem] font-bold font-data" style={{ color: dirColor }}>
          {signal.calibrated_confidence != null
            ? `${(signal.calibrated_confidence * 100).toFixed(0)}%`
            : `${fmtNum(signal.confidence * 100, 0)}%`}
        </span>
        <span className="text-[0.55rem] text-[var(--text-muted)]">{pluginShort}</span>
        {signal.resolved && <OutcomeBadge outcome={signal.outcome} />}
        {pnlR && <span className="ml-auto">{pnlR}</span>}
        {signalTimeStr && (
          <span className={`text-[0.52rem] font-data text-[var(--text-muted)] ${pnlR ? "" : "ml-auto"}`}>
            {signalTimeStr}{ttsStr && <span className="opacity-50 ml-0.5">{ttsStr}</span>}
          </span>
        )}
      </div>

      {/* Row 2: E target · SL · T1 rr */}
      <div className="flex items-center gap-1 text-[0.58rem] font-data flex-wrap">
        <span className="text-[var(--text-muted)]">E</span>
        <span style={{ color: dirColor }}>{fmtPrice(signal.entry_price)}</span>
        {signal.market_price_at_signal != null && (
          <span className="text-[var(--text-muted)] opacity-50">
            ({fmtPrice(signal.market_price_at_signal)} live)
          </span>
        )}
        <span className="opacity-20">·</span>
        <span className="text-[var(--text-muted)]">SL</span>
        <span className="text-[var(--text-secondary)]">{fmtPrice(signal.stop_loss)}</span>
        {t1 !== null && (
          <>
            <span className="opacity-20">·</span>
            <span className="text-[var(--text-muted)]">T1</span>
            <span className="text-[var(--text-secondary)]">{fmtPrice(t1)}</span>
            {rr1 > 0 && <span className="font-semibold" style={{ color: dirColor }}>{fmtNum(rr1, 1)}R</span>}
          </>
        )}
        {signal.resolved && signal.exit_price != null && (
          <>
            <span className="opacity-20">·</span>
            <span className="text-[var(--text-muted)]">X</span>
            <span className="text-[var(--text-secondary)]">{fmtPrice(signal.exit_price)}</span>
          </>
        )}
      </div>

      {/* Row 3: zone + perf */}
      {((signal.entry_zone_low != null && signal.entry_zone_high != null) || signal.setup_win_rate != null) && (
        <div className="flex items-center gap-2 text-[0.52rem] font-data text-[var(--text-muted)]">
          {signal.entry_zone_low != null && signal.entry_zone_high != null && (
            <span className="flex items-center gap-1">
              <span className="uppercase tracking-widest font-semibold" style={{ color: "var(--accent-cyan)", opacity: 0.8 }}>
                Zone
              </span>
              <span className="text-[var(--text-secondary)]">{fmtPriceRange(signal.entry_zone_low, signal.entry_zone_high)}</span>
              {signal.zone_valid_at_signal === true && <span style={{ color: "var(--green)", opacity: 0.7 }}>✓</span>}
              {signal.zone_valid_at_signal === false && <span className="opacity-40">not yet</span>}
            </span>
          )}
          {signal.setup_win_rate != null && (
            <span className="ml-auto opacity-70">
              {Math.round(signal.setup_win_rate * 100)}% win
              {signal.setup_avg_pnl_r != null && ` · ${signal.setup_avg_pnl_r >= 0 ? "+" : ""}${fmtNum(signal.setup_avg_pnl_r, 1)}R`}
            </span>
          )}
        </div>
      )}
    </div>
  );
}
