// dashboard/src/components/drill-panel.tsx
"use client";

import { X } from "lucide-react";
import type { SymbolData, SignalData } from "@/lib/types";
import { fmtPrice, fmtNum, fmtPriceRange, fmtMinutesHM, fmtTimeHMS, fmtLagSeconds, pipelineLagS } from "@/lib/format";
import { deriveBarCloseIso, TF_OFFSETS } from "@/lib/timeframe-utils";
import { Tooltip, type TooltipContent } from "@/components/tooltip";
import { useMemo } from "react";
import { OutcomeBadge } from "@/components/signal-panel";
import {
  rsiTooltip, macdTooltip, stochTooltip, atrTooltip, vwapTooltip, mfiTooltip,
  ema13Tooltip, ema21Tooltip,
  adxTooltip, diTooltip, supertrendTooltip, rocTooltip, aoTooltip, acTooltip,
  trendIntegrityTooltip, supportResistanceTooltip, levelStrengthTooltip,
  volRegimeTooltip, atrPercentileTooltip, volExpandingTooltip,
  trendRegimeTooltip, momentumBiasTooltip,
  rsiDivTooltip, bbSqueezeTooltip, volDivTooltip, i5ConfluenceTooltip,
  bosTooltip, chochTooltip, fvgTooltip, orderBlockTooltip, sweepTooltip,
  hmmRegimeTooltip, liquidityLevelTooltip,
  ctfScoreTooltip, ctfTfsAlignedTooltip, ctfTrendAlignTooltip,
  ctfStructureAlignTooltip, ctfRegimeAgreementTooltip,
  killzoneTooltip, amdPhaseTooltip, demandZoneTooltip, supplyZoneTooltip,
  breakerBlockTooltip, premiumDiscountPctTooltip,
} from "@/lib/indicator-tooltips";
import {
  barTimeTooltip,
  sigTimeTooltip,
  timestampTooltip,
  barClosePriceTooltip,
  marketPriceTooltip,
  ttsTooltip,
  entryTooltip,
  slTooltip,
  t1Tooltip,
  t2Tooltip,
  t3Tooltip,
  rrTooltip,
  zoneTooltip,
  exitTooltip,
} from "@/lib/signal-tooltips";

interface DrillPanelProps {
  symbol: string;
  timeframe: string;
  data: SymbolData;
  signal: SignalData | null;
  signalsHistory: SignalData[];
  onSignalSelect: (signal: SignalData) => void;
  onClose: () => void;
}

/** Compact 3-row signal card for RecentSignals sidebar hero */
function RecentSignalCard({ signal, isSelected, onClick }: { signal: SignalData; isSelected: boolean; onClick: () => void }) {
  const isLong = signal.direction === "long";
  const pluginShort = _abbreviatePlugin(signal.setup_plugin);

  const barCloseIso = useMemo(
    () => deriveBarCloseIso(signal.bar_close_ts, signal.timestamp, signal.timeframe),
    [signal.bar_close_ts, signal.timestamp, signal.timeframe]
  );
  const signalTimeStr = fmtTimeHMS(signal.signal_computed_at);
  const barCloseStr = fmtTimeHMS(barCloseIso);
  const ttsS = useMemo(
    () => pipelineLagS(signal.signal_computed_at, barCloseIso) ?? (signal.pipeline_lag_s ?? null),
    [signal.signal_computed_at, barCloseIso, signal.pipeline_lag_s]
  );
  const ttsStr = useMemo(() => fmtLagSeconds(ttsS), [ttsS]);

  const t1 = signal.profit_target ?? null;
  const rr1 = signal.rr_t1 ?? signal.risk_reward_ratio ?? 0;

  const dirColor = isLong ? "var(--green)" : "var(--red)";
  const dirDim = isLong ? "var(--green-dim)" : "var(--red-dim)";

  const pnlR = signal.pnl_r != null ? (
    <span className="font-data" style={{ color: signal.pnl_r > 0 ? "var(--green)" : "var(--red)" }}>
      {signal.pnl_r > 0 ? "+" : ""}{fmtNum(signal.pnl_r, 1)}R
    </span>
  ) : null;

  return (
    <div
      onClick={onClick}
      className={`p-2 rounded cursor-pointer transition-all ${
        isSelected ? "ring-1 ring-[var(--accent-cyan)]" : ""
      } ${signal.resolved ? "opacity-60" : ""}`}
      style={{ background: "var(--bg-elevated)" }}
    >
      {/* Row 1: bar close @ price → signal time @ price + TTS, direction, plugin, confidence, outcome */}
      <div className="text-xs flex items-center gap-2 flex-wrap">
        {(barCloseStr || signalTimeStr) && (
          <span className="font-data flex items-center gap-0.5 text-[0.55rem]">
            {barCloseStr && (
              <span className="opacity-60">
                {barCloseStr}
                {signal.bar_close_price != null && (
                  <span className="ml-0.5">@ {fmtPrice(signal.bar_close_price)}</span>
                )}
              </span>
            )}
            {barCloseStr && signalTimeStr && <span className="opacity-30 mx-0.5">→</span>}
            {signalTimeStr && (
              <span style={{ color: "var(--text-secondary)" }}>
                {signalTimeStr}
                {signal.market_price_at_signal != null && (
                  <span className="ml-0.5 opacity-80">@ {fmtPrice(signal.market_price_at_signal)}</span>
                )}
              </span>
            )}
            {ttsStr && <span className="opacity-50 ml-0.5">{ttsStr}</span>}
          </span>
        )}
        <span
          className="inline-flex items-center px-1 py-0 rounded text-[0.55rem] font-bold uppercase tracking-widest"
          style={{ backgroundColor: dirDim, color: dirColor }}
        >
          {isLong ? "LONG" : "SHORT"}
        </span>
        <span className="text-[var(--text-muted)]">{pluginShort}</span>
        <span className="font-data" style={{ color: dirColor }}>{fmtNum(signal.confidence * 100, 0)}%</span>
        {signal.resolved && (
          <OutcomeBadge outcome={signal.outcome} />
        )}
      </div>
      {/* Row 2: entry target, SL, T1 + RR */}
      <div className="text-[0.55rem] flex items-center gap-2 mt-0.5">
        <Tooltip tooltip={entryTooltip()}>
          <span className="opacity-60">E</span>
        </Tooltip>
        <span>{fmtPrice(signal.entry_price)}</span>
        {signal.entry_type && signal.entry_type !== "at_close" && (
          <span className="opacity-40">({signal.entry_type.replace(/_/g, " ")})</span>
        )}
        <span>·</span>
        <Tooltip tooltip={slTooltip()}>
          <span>SL</span>
        </Tooltip>
        <span>{fmtPrice(signal.stop_loss)}</span>
        {t1 !== null && (
          <>
            <span>·</span>
            <Tooltip tooltip={t1Tooltip()}>
              <span>T1</span>
            </Tooltip>
            <span>{fmtPrice(t1)}</span>
            {rr1 > 0 && <Tooltip tooltip={rrTooltip()}><span className="font-data">{fmtNum(rr1, 1)}R</span></Tooltip>}
          </>
        )}
      </div>

      {/* Entry Zone — wait for price to trade into this range */}
      {signal.entry_zone_low != null && signal.entry_zone_high != null && (
        <div className="text-[0.55rem] flex items-center gap-1.5 mt-0.5">
          <Tooltip tooltip={zoneTooltip()}>
            <span style={{ color: "var(--accent-cyan)", opacity: 0.8 }}>WAIT →</span>
          </Tooltip>
          <span className="opacity-50">ZONE</span>
          <span>{fmtPriceRange(signal.entry_zone_low, signal.entry_zone_high)}</span>
          {signal.zone_valid_at_signal === true && (
            <span style={{ color: "var(--green)", opacity: 0.7 }}>✓ in zone</span>
          )}
          {signal.zone_valid_at_signal === false && (
            <span className="opacity-40">not yet</span>
          )}
        </div>
      )}

      {/* Row 3: exit price + PnL (only for resolved) */}
      {signal.resolved && signal.exit_price && (
        <div className="text-[0.55rem] flex items-center gap-2 mt-0.5 text-[var(--text-muted)] opacity-70">
          <Tooltip tooltip={exitTooltip()}>
            <span>X</span>
          </Tooltip>
          <span>{fmtPrice(signal.exit_price)}</span>
          {pnlR && <span className="ml-auto">{pnlR}</span>}
        </div>
      )}
    </div>
  );
}

/** Recent Signals sidebar hero — shows last N signals for current symbol/TF */
function RecentSignals({ symbol, timeframe, signalsHistory, selectedSignal, onSignalSelect }: {
  symbol: string;
  timeframe: string;
  signalsHistory: SignalData[];
  selectedSignal: SignalData | null;
  onSignalSelect: (signal: SignalData) => void;
}) {
  // ~10 bars lookback window using TF_OFFSETS (seconds → ms)
  const windowMs = (TF_OFFSETS[timeframe] ?? 60) * 1000 * 10;

  // Memoized: only recompute when signalsHistory or timeframe changes.
  // cutoff updates on those changes, which is the right cadence (new data = new window).
  const recentSignals = useMemo(() => {
    const cutoff = Date.now() - windowMs;
    return signalsHistory
      .filter(s => {
        if (s.timeframe !== timeframe) return false;
        const t = new Date(s.bar_close_ts ?? s.timestamp).getTime();
        return !isNaN(t) && t >= cutoff;
      })
      .sort((a, b) => {
        const timeA = new Date(a.bar_close_ts ?? a.timestamp).getTime();
        const timeB = new Date(b.bar_close_ts ?? b.timestamp).getTime();
        return timeB - timeA;
      })
      .slice(0, 5)
      .reverse();
  }, [signalsHistory, timeframe, windowMs]);

  const hasSignals = recentSignals.length > 0;

  return (
    <div className="border-b border-[var(--border-subtle)]">
      <h3 className="text-[0.55rem] font-semibold uppercase tracking-widest text-[var(--text-muted)] mb-2 px-4 pt-3">
        Recent Signals ({recentSignals.length}) — {timeframe}
      </h3>
      {hasSignals ? (
        <div className="px-4 pb-3 flex flex-col gap-2">
          {recentSignals.map((signal) => (
            <RecentSignalCard
              key={signal.signal_id || `${signal.timestamp}-${signal.entry_price}`}
              signal={signal}
              isSelected={selectedSignal?.signal_id === signal.signal_id}
              onClick={() => onSignalSelect(signal)}
            />
          ))}
        </div>
      ) : (
        <div className="px-4 pb-3">
          <Empty>No recent signals for {symbol}:{timeframe}</Empty>
        </div>
      )}
    </div>
  );
}

/** Shorten plugin name for compact display */
function _abbreviatePlugin(name: string): string {
  const bare = name.replace(/^(ind_|patt_|ctx_|smc_|trad_)/, "");
  if (bare.length <= 8) return bare;
  return bare.slice(0, 6);
}

export function DrillPanel({ symbol, timeframe, data, signal, signalsHistory, onSignalSelect, onClose }: DrillPanelProps) {
  // Renaissance: Use intelligence snapshot from signal when available (historical context), otherwise use current data
  const intel = signal?.intelligence_snapshot ?? (data.intelligenceByTf[timeframe] ?? null);
  const structure = intel?.structure ?? null;
  const context = intel?.context ?? null;
  const patterns = intel?.patterns ?? null;
  const smc = intel?.smartMoney ?? null;
  const confluence = intel?.confluence ?? null;
  const indicators = data.indicatorsByTf[timeframe] ?? null;

  return (
    <>
      <div
        className="fixed top-0 right-0 bottom-0 z-50 w-full max-w-md flex flex-col"
        style={{
          backgroundColor: "var(--bg-surface)",
          borderLeft: "1px solid var(--border-default)",
        }}
      >
        {/* Header */}
        <div
          className="flex items-center justify-between px-4 py-3 shrink-0"
          style={{ borderBottom: "1px solid var(--border-subtle)" }}
        >
          <div className="flex items-center gap-2">
            <span className="text-sm font-bold text-[var(--text-primary)] font-data">
              {symbol}
            </span>
            <span
              className="text-[0.55rem] font-semibold px-1.5 py-0.5 rounded"
              style={{
                backgroundColor: "var(--bg-elevated)",
                color: "var(--text-secondary)",
              }}
            >
              {timeframe.toUpperCase()}
            </span>
          </div>
          <button
            onClick={onClose}
            className="p-1 rounded cursor-pointer text-[var(--text-muted)] hover:text-[var(--text-primary)] transition-colors"
          >
            <X size={14} />
          </button>
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto p-0 flex flex-col gap-3">
          {/* Recent Signals Hero */}
          <RecentSignals
            symbol={symbol}
            timeframe={timeframe}
            signalsHistory={signalsHistory}
            selectedSignal={signal}
            onSignalSelect={onSignalSelect}
          />

          {/* I7 Signal */}
          <Section label="I7 Signal">
            {signal ? (
              <SignalDetail signal={signal} />
            ) : timeframe === "1m" ? (
              <Empty>No active 1m signal</Empty>
            ) : (
              <Empty>No signal for {timeframe} — signals are generated on 1m</Empty>
            )}
          </Section>

          {/* I3 Structure */}
          <Section label="I3 Structure">
            {structure ? (
              <Grid>
                <KV label="Trend" value={structure.swing_trend ?? "—"} />
                <KV
                  label="Integrity"
                  value={structure.trend_integrity != null ? `${(structure.trend_integrity * 100).toFixed(0)}%` : "—"}
                  tooltip={trendIntegrityTooltip(structure.trend_integrity)}
                />
                <KV
                  label="Support"
                  value={fmtPrice(structure.nearest_support)}
                  tooltip={supportResistanceTooltip("support")}
                />
                <KV
                  label="Resistance"
                  value={fmtPrice(structure.nearest_resistance)}
                  tooltip={supportResistanceTooltip("resistance")}
                />
                <KV
                  label="Support str"
                  value={fmtNum(structure.support_strength, 2)}
                  tooltip={levelStrengthTooltip("support", structure.support_strength)}
                />
                <KV
                  label="Resist str"
                  value={fmtNum(structure.resistance_strength, 2)}
                  tooltip={levelStrengthTooltip("resistance", structure.resistance_strength)}
                />
              </Grid>
            ) : <Empty>Awaiting {timeframe} intelligence</Empty>}
          </Section>

          {/* I4 Context */}
          <Section label="I4 Context">
            {context ? (
              <Grid>
                <KV
                  label="Vol regime"
                  value={context.volatility_regime ?? "—"}
                  tooltip={volRegimeTooltip(context.volatility_regime)}
                />
                <KV
                  label="ATR pctile"
                  value={context.atr_percentile != null ? `${(context.atr_percentile * 100).toFixed(0)}%` : "—"}
                  tooltip={atrPercentileTooltip(context.atr_percentile)}
                />
                <KV
                  label="Vol expan"
                  value={context.vol_expanding != null ? (context.vol_expanding ? "yes" : "no") : "—"}
                  tooltip={volExpandingTooltip(context.vol_expanding)}
                />
                <KV
                  label="Trend"
                  value={context.trend_regime ?? "—"}
                  tooltip={trendRegimeTooltip(context.trend_regime)}
                />
                <KV
                  label="Mom bias"
                  value={context.momentum_bias != null ? fmtNum(context.momentum_bias, 2) : "—"}
                  tooltip={momentumBiasTooltip(context.momentum_bias)}
                />
                <KV label="Mom dir" value={context.momentum_direction ?? "—"} />
              </Grid>
            ) : <Empty>Awaiting {timeframe} intelligence</Empty>}
          </Section>

          {/* I5 Patterns */}
          <Section label="I5 Patterns">
            {patterns ? (
              <Grid>
                <KV
                  label="RSI div"
                  value={patterns.rsi_divergence ?? "none"}
                  tooltip={rsiDivTooltip(patterns.rsi_divergence)}
                />
                <KV label="RSI conf" value={fmtNum(patterns.rsi_div_confidence, 2)} />
                <KV
                  label="BB squeeze"
                  value={patterns.bb_squeeze != null ? (patterns.bb_squeeze ? `yes (${patterns.squeeze_count ?? 0}b)` : "no") : "—"}
                  tooltip={bbSqueezeTooltip(patterns.bb_squeeze, patterns.squeeze_count)}
                />
                <KV
                  label="Vol div"
                  value={patterns.volume_divergence ?? "none"}
                  tooltip={volDivTooltip(patterns.volume_divergence)}
                />
                <KV
                  label="Confluence"
                  value={patterns.confluence_score != null ? fmtNum(patterns.confluence_score, 2) : "—"}
                  tooltip={i5ConfluenceTooltip(patterns.confluence_score)}
                />
              </Grid>
            ) : <Empty>Awaiting {timeframe} intelligence</Empty>}
          </Section>

          {/* SMC */}
          <Section label="Smart Money">
            {smc ? (
              <Grid>
                <KV
                  label="BOS"
                  value={smc.bos_detected ? `${(smc.bos_direction ?? 0) > 0 ? "bullish" : "bearish"} @ ${fmtPrice(smc.bos_level)}` : "none"}
                  tooltip={bosTooltip()}
                />
                <KV
                  label="CHoCH"
                  value={smc.choch_detected ? `${(smc.choch_direction ?? 0) > 0 ? "bullish" : "bearish"}` : "none"}
                  tooltip={chochTooltip()}
                />
                <KV
                  label="FVG"
                  value={(smc.fvg_type ?? 0) !== 0 ? `${(smc.fvg_type ?? 0) > 0 ? "bull" : "bear"} ${fmtPrice(smc.fvg_bottom)}–${fmtPrice(smc.fvg_top)}` : "none"}
                  tooltip={fvgTooltip()}
                />
                <KV
                  label="Order blk"
                  value={(smc.ob_type ?? 0) !== 0 ? `${(smc.ob_type ?? 0) > 0 ? "bull" : "bear"} @ ${fmtPrice(smc.ob_bottom)}` : "none"}
                  tooltip={orderBlockTooltip()}
                />
                <KV
                  label="Sweep"
                  value={smc.sweep_detected ? `${(smc.sweep_type ?? 0) > 0 ? "bullish" : "bearish"}${smc.sweep_reclaimed ? " ✓reclaimed" : ""}` : "none"}
                  tooltip={sweepTooltip(smc.sweep_reclaimed)}
                />
                <KV
                  label="HMM regime"
                  value={smc.hmm_regime != null ? `${["ranging","up","down"][smc.hmm_regime] ?? smc.hmm_regime} (${((smc.hmm_regime_prob ?? 0) * 100).toFixed(0)}%)` : "—"}
                  tooltip={hmmRegimeTooltip(smc.hmm_regime, smc.hmm_regime_prob)}
                />
                <KV
                  label="BSL"
                  value={smc.bsl_level != null ? `${fmtPrice(smc.bsl_level)} (${fmtNum(smc.bsl_dist_atr, 1)} ATR)` : "—"}
                  tooltip={liquidityLevelTooltip("BSL")}
                />
                <KV
                  label="SSL"
                  value={smc.ssl_level != null ? `${fmtPrice(smc.ssl_level)} (${fmtNum(smc.ssl_dist_atr, 1)} ATR)` : "—"}
                  tooltip={liquidityLevelTooltip("SSL")}
                />
                {/* Breaker Block */}
                <KV
                  label="Breaker"
                  value={smc.breaker_block_active
                    ? `${(smc.breaker_block_type ?? 0) > 0 ? "bull" : "bear"} ${fmtPrice(smc.breaker_block_bottom)}–${fmtPrice(smc.breaker_block_top)}`
                    : "none"}
                  tooltip={breakerBlockTooltip(smc.breaker_block_type, smc.breaker_dist_atr)}
                />
                {/* Premium / Discount */}
                <KV
                  label="Prem/disc"
                  value={smc.premium_discount_pct != null
                    ? `${smc.premium_discount_pct > 0 ? "+" : ""}${smc.premium_discount_pct.toFixed(1)}%`
                    : "—"}
                  tooltip={premiumDiscountPctTooltip(smc.premium_discount_pct)}
                />
              </Grid>
            ) : <Empty>Awaiting {timeframe} intelligence</Empty>}
          </Section>

          {/* Killzones & AMD */}
          <Section label="Session & Killzones">
            {smc ? (
              <Grid>
                <KV
                  label="Killzone"
                  value={smc.killzone_name
                    ? smc.killzone_name
                    : smc.minutes_until_next_killzone != null
                      ? `next ${fmtMinutesHM(smc.minutes_until_next_killzone)}`
                      : "—"}
                  tooltip={killzoneTooltip(smc.killzone_name, smc.minutes_until_next_killzone)}
                />
                <KV
                  label="AMD phase"
                  value={smc.amd_phase ?? "—"}
                  tooltip={amdPhaseTooltip(smc.amd_phase, smc.amd_manipulation_detected)}
                />
              </Grid>
            ) : <Empty>Awaiting {timeframe} intelligence</Empty>}
          </Section>

          {/* Supply / Demand Zones */}
          <Section label="Supply / Demand">
            {smc ? (
              <Grid>
                <KV
                  label="Demand"
                  value={smc.nearest_demand_low != null && smc.nearest_demand_high != null
                    ? `${fmtPrice(smc.nearest_demand_low)}–${fmtPrice(smc.nearest_demand_high)}`
                    : "none"}
                  tooltip={demandZoneTooltip(smc.nearest_demand_high, smc.nearest_demand_low, smc.demand_dist_atr)}
                />
                <KV
                  label="In demand"
                  value={smc.in_demand_zone != null ? (smc.in_demand_zone ? "yes ✓" : "no") : "—"}
                />
                <KV label="D-strength" value={smc.demand_strength != null ? fmtNum(smc.demand_strength, 2) : "—"} />
                <KV label="D-freshness" value={smc.demand_freshness != null ? fmtNum(smc.demand_freshness, 2) : "—"} />
                <KV
                  label="Supply"
                  value={smc.nearest_supply_low != null && smc.nearest_supply_high != null
                    ? `${fmtPrice(smc.nearest_supply_low)}–${fmtPrice(smc.nearest_supply_high)}`
                    : "none"}
                  tooltip={supplyZoneTooltip(smc.nearest_supply_high, smc.nearest_supply_low, smc.supply_dist_atr)}
                />
                <KV
                  label="In supply"
                  value={smc.in_supply_zone != null ? (smc.in_supply_zone ? "yes ✓" : "no") : "—"}
                />
                <KV label="S-strength" value={smc.supply_strength != null ? fmtNum(smc.supply_strength, 2) : "—"} />
                <KV label="S-freshness" value={smc.supply_freshness != null ? fmtNum(smc.supply_freshness, 2) : "—"} />
              </Grid>
            ) : <Empty>Awaiting {timeframe} intelligence</Empty>}
          </Section>

          {/* I6 Cross-TF Confluence */}
          <Section label="I6 Confluence">
            {confluence ? (
              <Grid>
                <KV
                  label="CTF score"
                  value={fmtNum(confluence.ctf_score, 2)}
                  tooltip={ctfScoreTooltip(confluence.ctf_score)}
                />
                <KV
                  label="TFs aligned"
                  value={`${confluence.ctf_timeframes_aligned ?? 0}/4`}
                  tooltip={ctfTfsAlignedTooltip(confluence.ctf_timeframes_aligned)}
                />
                <KV
                  label="Trend align"
                  value={fmtNum(confluence.ctf_trend_alignment, 2)}
                  tooltip={ctfTrendAlignTooltip(confluence.ctf_trend_alignment)}
                />
                <KV
                  label="Structure"
                  value={fmtNum(confluence.ctf_structure_alignment, 2)}
                  tooltip={ctfStructureAlignTooltip(confluence.ctf_structure_alignment)}
                />
                <KV
                  label="Regime agr"
                  value={fmtNum(confluence.ctf_regime_agreement, 2)}
                  tooltip={ctfRegimeAgreementTooltip(confluence.ctf_regime_agreement)}
                />
              </Grid>
            ) : <Empty>Awaiting {timeframe} intelligence</Empty>}
          </Section>

          {/* I1 Indicators */}
          <Section label="I1 Indicators">
            {indicators ? (
              <Grid>
                <KV
                  label="RSI"
                  value={fmtNum(indicators.rsi, 1)}
                  tooltip={rsiTooltip(indicators.rsi)}
                />
                <KV
                  label="MACD"
                  value={fmtNum(indicators.macd, 2)}
                  tooltip={macdTooltip(indicators.macd_histogram)}
                />
                <KV
                  label="Stoch K/D"
                  value={`${fmtNum(indicators.stoch_k, 1)} / ${fmtNum(indicators.stoch_d, 1)}`}
                  tooltip={stochTooltip(indicators.stoch_k)}
                />
                <KV
                  label="ATR"
                  value={fmtNum(indicators.atr, 2)}
                  tooltip={atrTooltip()}
                />
                <KV
                  label="VWAP"
                  value={fmtPrice(indicators.vwap)}
                  tooltip={vwapTooltip()}
                />
                <KV
                  label="MFI"
                  value={fmtNum(indicators.mfi, 1)}
                  tooltip={mfiTooltip(indicators.mfi)}
                />
                <KV
                  label="EMA 13/21"
                  value={`${fmtPrice(indicators.ema_13)} / ${fmtPrice(indicators.ema_21)}`}
                  tooltip={ema13Tooltip()}
                />
                <KV
                  label="ADX"
                  value={fmtNum(indicators.adx, 1)}
                  tooltip={adxTooltip(indicators.adx)}
                />
                <KV
                  label="+DI / −DI"
                  value={`${fmtNum(indicators.plus_di, 1)} / ${fmtNum(indicators.minus_di, 1)}`}
                  tooltip={diTooltip(indicators.plus_di, indicators.minus_di)}
                />
                <KV
                  label="Supertrend"
                  value={indicators.supertrend_dir != null
                    ? (indicators.supertrend_dir > 0 ? "bullish ▲" : "bearish ▼")
                    : "—"}
                  tooltip={supertrendTooltip(indicators.supertrend_dir, indicators.supertrend_value)}
                />
                <KV
                  label="ROC"
                  value={indicators.roc != null
                    ? `${indicators.roc > 0 ? "+" : ""}${fmtNum(indicators.roc, 2)}%`
                    : "—"}
                  tooltip={rocTooltip(indicators.roc)}
                />
                <KV
                  label="AO"
                  value={fmtNum(indicators.ao, 2)}
                  tooltip={aoTooltip(indicators.ao)}
                />
                <KV
                  label="AC"
                  value={fmtNum(indicators.ac, 2)}
                  tooltip={acTooltip(indicators.ac)}
                />
              </Grid>
            ) : <Empty>Awaiting {timeframe} indicators</Empty>}
          </Section>
        </div>
      </div>
    </>
  );
}

function Section({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <h3 className="text-[0.55rem] font-semibold uppercase tracking-widest text-[var(--text-muted)] mb-1.5">
        {label}
      </h3>
      <div
        className="rounded px-3 py-2"
        style={{ backgroundColor: "var(--bg-elevated)" }}
      >
        {children}
      </div>
    </div>
  );
}

function Grid({ children }: { children: React.ReactNode }) {
  return (
    <div className="grid grid-cols-2 gap-x-4 gap-y-1">
      {children}
    </div>
  );
}

function KV({
  label,
  value,
  tooltip,
}: {
  label: string;
  value: string;
  tooltip?: TooltipContent;
}) {
  const labelEl = (
    <span className="text-[0.55rem] text-[var(--text-muted)] shrink-0">{label}</span>
  );

  return (
    <div className="flex items-baseline justify-between gap-1 min-w-0">
      {tooltip ? (
        <Tooltip tooltip={tooltip}>{labelEl}</Tooltip>
      ) : (
        labelEl
      )}
      <span className="text-[0.6rem] font-data text-[var(--text-secondary)] truncate text-right">
        {value}
      </span>
    </div>
  );
}

function Empty({ children }: { children: React.ReactNode }) {
  return (
    <span className="text-[0.6rem] italic text-[var(--text-muted)]">{children}</span>
  );
}

function SignalDetail({ signal }: { signal: SignalData }) {
  const isLong = signal.direction === "long";
  const dirColor = isLong ? "var(--green)" : "var(--red)";
  const timeStr = signal.timestamp
    ? new Date(signal.timestamp).toLocaleTimeString([], {
        hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false,
      })
    : "—";
  const sigTimeStr = signal.signal_computed_at
    ? new Date(signal.signal_computed_at).toLocaleTimeString([], {
        hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false,
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

  const entryTypeLabel: Record<string, string> = {
    at_close: "at close",
    at_reclaim: "at reclaim",
    zone_proximal: "zone proximal",
  };
  const stopTypeLabel: Record<string, string> = {
    demand_zone: "demand zone",
    supply_zone: "supply zone",
    sweep_level: "sweep level",
    ob_bottom: "OB bottom",
    ob_top: "OB top",
    swing_low: "swing low",
    swing_high: "swing high",
    sr_support: "S/R",
    atr: "ATR×2",
  };

  return (
    <div className="flex flex-col gap-2">
      {/* Header row */}
      <div className="flex items-center gap-2 flex-wrap">
        <span
          className="inline-flex px-2 py-0.5 rounded text-[0.6rem] font-bold uppercase tracking-widest"
          style={{ backgroundColor: isLong ? "var(--green-dim)" : "var(--red-dim)", color: dirColor }}
        >
          {isLong ? "LONG" : "SHORT"}
        </span>
        <span className="text-[0.6rem] text-[var(--text-secondary)]">{signal.signal_type.replace(/_/g, " ")}</span>
        <span className="text-[0.6rem] font-bold font-data" style={{ color: dirColor }}>{(signal.confidence * 100).toFixed(0)}%</span>
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

      {/* Bar close + signal price context */}
      <Grid>
        {signal.bar_close_price != null && (
          <KV
            label="Bar close"
            tooltip={{ description: "Close price of the bar that triggered this signal — what the analysis is based on", context: null }}
            value={fmtPrice(signal.bar_close_price)}
          />
        )}
        {signal.market_price_at_signal != null && (
          <KV
            label="Signal price"
            tooltip={{ description: "Live market price (bid/ask) at the moment this signal was computed", context: null }}
            value={fmtPrice(signal.market_price_at_signal)}
          />
        )}
      </Grid>

      {/* Entry target / Stop */}
      <Grid>
        <KV
          label="Entry target"
          value={`${fmtPrice(signal.entry_price)}${signal.entry_type ? ` (${entryTypeLabel[signal.entry_type] ?? signal.entry_type})` : ""}`}
        />
        <KV
          label="Stop"
          value={`${fmtPrice(signal.stop_loss)}${signal.stop_type ? ` (${stopTypeLabel[signal.stop_type] ?? signal.stop_type})` : ""}`}
        />
      </Grid>

      {/* Entry Zone — wait for price to trade into this range before executing */}
      {signal.entry_zone_low != null && signal.entry_zone_high != null && (
        <Grid>
          <KV
            label="Wait → enter zone"
            tooltip={zoneTooltip()}
            value={fmtPriceRange(signal.entry_zone_low, signal.entry_zone_high)}
          />
          {signal.zone_valid_at_signal != null && (
            <KV
              label="In zone at signal"
              value={signal.zone_valid_at_signal ? "yes ✓" : "not yet"}
            />
          )}
        </Grid>
      )}

      {/* Targets */}
      {t1 !== null && (
        <div className="flex flex-col gap-0.5">
          <span className="text-[0.5rem] font-semibold uppercase tracking-widest text-[var(--text-muted)] mb-0.5">
            Targets {isStructural ? <span className="text-[var(--green)] opacity-70">structural</span> : <span className="opacity-50">ATR fallback</span>}
          </span>
          <Grid>
            <KV
              label={`T1${labels[0] ? ` · ${labels[0].split(" ")[0]}` : ""}`}
              value={`${fmtPrice(t1)}${rr1 > 0 ? `  ${fmtNum(rr1, 1)}R` : ""}`}
            />
            {t2 !== null && (
              <KV
                label={`T2${labels[1] ? ` · ${labels[1].split(" ")[0]}` : ""}`}
                value={`${fmtPrice(t2)}${rr2 > 0 ? `  ${fmtNum(rr2, 1)}R` : ""}`}
              />
            )}
            {t3 !== null && isStructural && (
              <KV
                label={`T3${labels[2] ? ` · ${labels[2].split(" ")[0]}` : ""}`}
                value={`${fmtPrice(t3)}${rr3 > 0 ? `  ${fmtNum(rr3, 1)}R` : ""}`}
              />
            )}
          </Grid>
        </div>
      )}

      {/* Meta */}
      <Grid>
        <KV label="Regime" value={signal.regime_context} />
        <KV label="Plugin" value={signal.setup_plugin.replace(/^trad_/, "")} />
      </Grid>
    </div>
  );
}
