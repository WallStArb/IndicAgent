// dashboard/src/components/drill-panel.tsx
"use client";

import { X } from "lucide-react";
import type { SymbolData, SignalData } from "@/lib/types";
import { fmtPrice, fmtNum, fmtPriceRange, fmtMinutesHM, fmtTimeHMS, fmtLagSeconds, pipelineLagS } from "@/lib/format";
import { deriveBarCloseIso, TF_OFFSETS } from "@/lib/timeframe-utils";
import { Tooltip, type TooltipContent } from "@/components/tooltip";
import { useMemo, useState, useEffect } from "react";
import { OutcomeBadge } from "@/components/outcome-badge";
import { TierTooltip } from "@/components/tier-tooltip";
import { SignalScorecard } from "@/components/signal-scorecard";
import { getApiBase } from "@/lib/api";
import { computeSignalTier, tierColor } from "@/lib/signal-tier";
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

interface DbSignalRow {
  signal_id: string;
  setup_plugin: string;
  signal_type: string;
  direction: number;
  entry_price: number | null;
  stop_loss: number | null;
  confidence: number | null;
  status: string;
  outcome: string | null;
  exit_price: number | null;
  pnl_r: number | null;
  computed_at: string | null;
  timeframe: string;
  setup_win_rate: number | null;
  setup_avg_pnl_r: number | null;
}

interface SignalWindowSummary {
  n_total: number;
  n_resolved: number;
  n_suppressed: number;
  win_rate: number | null;
  avg_pnl_r: number | null;
}

function dbRowToSignalData(row: DbSignalRow, symbol: string): SignalData {
  const dir = row.direction > 0 ? "long" as const : "short" as const;
  return {
    symbol,
    signal_id: row.signal_id,
    setup_plugin: row.setup_plugin,
    signal_type: row.signal_type,
    direction: dir,
    entry_price: row.entry_price ?? 0,
    stop_loss: row.stop_loss ?? 0,
    confidence: row.confidence ?? 0,
    profit_target: null,
    risk_reward_ratio: 0,
    regime_context: "",
    timeframe: row.timeframe,
    timestamp: row.computed_at ?? "",
    signal_computed_at: row.computed_at ?? undefined,
    resolved: row.status !== "pending" && row.status !== "active",
    outcome: row.outcome ?? undefined,
    exit_price: row.exit_price ?? undefined,
    setup_win_rate: row.setup_win_rate ?? undefined,
    setup_avg_pnl_r: row.setup_avg_pnl_r ?? undefined,
  };
}

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
          {fmtNum(signal.confidence * 100, 0)}%
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

      {/* Row 2: E target · SL · T1 rr  (mirroring SignalBanner line 1) */}
      <div className="flex items-center gap-1 text-[0.58rem] font-data flex-wrap">
        <Tooltip tooltip={entryTooltip()}>
          <span className="text-[var(--text-muted)]">E</span>
        </Tooltip>
        <span style={{ color: dirColor }}>{fmtPrice(signal.entry_price)}</span>
        {signal.market_price_at_signal != null && (
          <span className="text-[var(--text-muted)] opacity-50">
            ({fmtPrice(signal.market_price_at_signal)} live)
          </span>
        )}
        <span className="opacity-20">·</span>
        <Tooltip tooltip={slTooltip()}>
          <span className="text-[var(--text-muted)]">SL</span>
        </Tooltip>
        <span className="text-[var(--text-secondary)]">{fmtPrice(signal.stop_loss)}</span>
        {t1 !== null && (
          <>
            <span className="opacity-20">·</span>
            <Tooltip tooltip={t1Tooltip()}>
              <span className="text-[var(--text-muted)]">T1</span>
            </Tooltip>
            <span className="text-[var(--text-secondary)]">{fmtPrice(t1)}</span>
            {rr1 > 0 && (
              <Tooltip tooltip={rrTooltip()}>
                <span className="font-semibold" style={{ color: dirColor }}>{fmtNum(rr1, 1)}R</span>
              </Tooltip>
            )}
          </>
        )}
        {signal.resolved && signal.exit_price != null && (
          <>
            <span className="opacity-20">·</span>
            <Tooltip tooltip={exitTooltip()}>
              <span className="text-[var(--text-muted)]">X</span>
            </Tooltip>
            <span className="text-[var(--text-secondary)]">{fmtPrice(signal.exit_price)}</span>
          </>
        )}
      </div>

      {/* Row 3: zone + perf  (mirroring SignalBanner line 2) */}
      {((signal.entry_zone_low != null && signal.entry_zone_high != null) || signal.setup_win_rate != null) && (
        <div className="flex items-center gap-2 text-[0.52rem] font-data text-[var(--text-muted)]">
          {signal.entry_zone_low != null && signal.entry_zone_high != null && (
            <span className="flex items-center gap-1">
              <Tooltip tooltip={zoneTooltip()}>
                <span className="uppercase tracking-widest font-semibold" style={{ color: "var(--accent-cyan)", opacity: 0.8 }}>Zone</span>
              </Tooltip>
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

  // DB-backed signal history — fetched on mount, merged with SSE history
  const [dbSignals, setDbSignals] = useState<SignalData[]>([]);
  const [windowSummary, setWindowSummary] = useState<SignalWindowSummary | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    const base = getApiBase();
    fetch(
      `${base}/api/signals/recent?symbol=${encodeURIComponent(symbol)}&timeframe=${encodeURIComponent(timeframe)}&limit=20`,
      { signal: controller.signal }
    )
      .then(r => r.ok ? r.json() : Promise.reject(r.status))
      .then((body: { signals: DbSignalRow[]; summary: SignalWindowSummary }) => {
        setDbSignals(body.signals.map(row => dbRowToSignalData(row, symbol)));
        setWindowSummary(body.summary);
      })
      .catch((err) => {
        if (err instanceof Error && err.name === "AbortError") return;
        // non-fatal — SSE history still works, summary stays null
      });
    return () => controller.abort();
  }, [symbol, timeframe]);

  // Merge DB signals with SSE history — SSE wins on same signal_id (more up-to-date lifecycle state)
  const mergedSignalsHistory = useMemo(() => {
    const byId = new Map<string, SignalData>();
    for (const s of dbSignals) {
      if (s.signal_id) byId.set(s.signal_id, s);
    }
    for (const s of signalsHistory) {
      if (s.signal_id) byId.set(s.signal_id, s);
      else byId.set(`${s.timestamp}:${s.entry_price}`, s);
    }
    return Array.from(byId.values()).sort((a, b) => {
      const ta = new Date(a.signal_computed_at ?? a.timestamp).getTime();
      const tb = new Date(b.signal_computed_at ?? b.timestamp).getTime();
      return tb - ta;
    });
  }, [dbSignals, signalsHistory]);

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
          {windowSummary && (windowSummary.n_resolved > 0 || windowSummary.n_suppressed > 0) && (
            <div className="text-xs text-muted-foreground px-4 pt-3 pb-0 flex gap-2 flex-wrap">
              <span className="text-[0.55rem] text-[var(--text-muted)]">{windowSummary.n_resolved} resolved</span>
              {windowSummary.win_rate != null && (
                <span className={`text-[0.55rem] ${windowSummary.win_rate >= 0.5 ? "text-green-400" : "text-red-400"}`}>
                  {Math.round(windowSummary.win_rate * 100)}% win
                </span>
              )}
              {windowSummary.avg_pnl_r != null && (
                <span className={`text-[0.55rem] ${windowSummary.avg_pnl_r >= 0 ? "text-green-400" : "text-red-400"}`}>
                  avg {windowSummary.avg_pnl_r >= 0 ? "+" : ""}{windowSummary.avg_pnl_r.toFixed(2)}R
                </span>
              )}
              {windowSummary.n_suppressed > 0 && (
                <span className="text-[0.55rem] text-amber-400">{windowSummary.n_suppressed} suppressed</span>
              )}
            </div>
          )}
          <RecentSignals
            symbol={symbol}
            timeframe={timeframe}
            signalsHistory={mergedSignalsHistory}
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

function Section({ label, children }: { label: React.ReactNode; children: React.ReactNode }) {
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
  valueClassName,
}: {
  label: string;
  value: string;
  tooltip?: TooltipContent;
  valueClassName?: string;
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
      <span className={`text-[0.6rem] font-data truncate text-right ${valueClassName ?? "text-[var(--text-secondary)]"}`}>
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
