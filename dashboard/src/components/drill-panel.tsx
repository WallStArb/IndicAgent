// dashboard/src/components/drill-panel.tsx
"use client";

import { X } from "lucide-react";
import type { SymbolData, SignalData } from "@/lib/types";
import { fmtPrice, fmtNum, fmtMinutesHM } from "@/lib/format";
import { TierTooltip } from "@/components/tier-tooltip";
import { SignalScorecard } from "@/components/signal-scorecard";
import { Section, Grid, KV, Empty } from "./ui/primitives";
import { SignalDetail, RecentSignals, type SignalWindowSummary } from "./signal";
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

interface DrillPanelProps {
  symbol: string;
  timeframe: string;
  data: SymbolData;
  signal: SignalData | null;
  signalsHistory: SignalData[];
  onSignalSelect: (signal: SignalData) => void;
  onClose: () => void;
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
          <Section label={<TierTooltip tier="I7">I7 Signal</TierTooltip>}>
            {signal ? (
              <SignalDetail signal={signal} />
            ) : timeframe === "1m" ? (
              <Empty>No active 1m signal</Empty>
            ) : (
              <Empty>No signal for {timeframe} — signals are generated on 1m</Empty>
            )}
          </Section>

          {/* Signal Scorecard — all ranked signals for current bar */}
          <Section label="Signal Scorecard">
            <SignalScorecard data={data.scorecardByTf?.[timeframe]} />
          </Section>

          {/* I3 Structure */}
          <Section label={<TierTooltip tier="I3">I3 Structure</TierTooltip>}>
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
          <Section label={<TierTooltip tier="I4">I4 Context</TierTooltip>}>
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
                {/* GARCH vol model — regime label styled by pipeline classification, not hardcoded threshold */}
                {context.garch_vol_regime != null && (
                  <KV
                    label="GARCH regime"
                    value={["low", "normal", "high"][context.garch_vol_regime] ?? String(context.garch_vol_regime)}
                    valueClassName={context.garch_vol_regime === 2 ? "text-amber-400" : undefined}
                  />
                )}
                {context.garch_sigma != null && (
                  <KV label="GARCH σ" value={fmtNum(context.garch_sigma, 4)} />
                )}
                {context.garch_vol_ratio != null && (
                  <KV label="GARCH ratio" value={fmtNum(context.garch_vol_ratio, 2)} />
                )}
                {context.garch_shock != null && (
                  <KV label="GARCH shock" value={fmtNum(context.garch_shock, 2)} />
                )}
                {/* Kalman trend filter */}
                {context.kalman_slope != null && (
                  <KV label="Kalman slope" value={fmtNum(context.kalman_slope, 4)} />
                )}
                {context.kalman_price_position != null && (
                  <KV label="Kalman pos" value={fmtNum(context.kalman_price_position, 2)} />
                )}
                {context.kalman_uncertainty != null && (
                  <KV label="K-uncertainty" value={fmtNum(context.kalman_uncertainty, 4)} />
                )}
              </Grid>
            ) : <Empty>Awaiting {timeframe} intelligence</Empty>}
          </Section>

          {/* I5 Patterns */}
          <Section label={<TierTooltip tier="I5">I5 Patterns</TierTooltip>}>
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
          <Section label={<TierTooltip tier="SMC">Smart Money</TierTooltip>}>
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
                {smc.bsl_touches != null && (
                  <KV label="BSL touches" value={String(smc.bsl_touches)} />
                )}
                {smc.bsl_significance != null && (
                  <KV label="BSL sig" value={fmtNum(smc.bsl_significance, 2)} />
                )}
                <KV
                  label="SSL"
                  value={smc.ssl_level != null ? `${fmtPrice(smc.ssl_level)} (${fmtNum(smc.ssl_dist_atr, 1)} ATR)` : "—"}
                  tooltip={liquidityLevelTooltip("SSL")}
                />
                {smc.ssl_touches != null && (
                  <KV label="SSL touches" value={String(smc.ssl_touches)} />
                )}
                {smc.ssl_significance != null && (
                  <KV label="SSL sig" value={fmtNum(smc.ssl_significance, 2)} />
                )}
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
                {smc.price_in_premium != null && (
                  <KV label="In premium" value={smc.price_in_premium ? "yes ▲" : "no ▼"} />
                )}
                {smc.equilibrium_level != null && (
                  <KV label="Equilibrium" value={fmtPrice(smc.equilibrium_level)} />
                )}
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
          <Section label={<TierTooltip tier="I6">I6 Confluence</TierTooltip>}>
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
          <Section label={<TierTooltip tier="I1">I1 Indicators</TierTooltip>}>
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

