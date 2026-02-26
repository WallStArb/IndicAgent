// dashboard/src/components/drill-panel.tsx
"use client";

import { X } from "lucide-react";
import type { SymbolData, SignalData } from "@/lib/types";
import { fmtPrice, fmtNum } from "@/lib/format";

interface DrillPanelProps {
  symbol: string;
  timeframe: string;
  data: SymbolData;
  signal: SignalData | null;
  onClose: () => void;
}

export function DrillPanel({ symbol, timeframe, data, signal, onClose }: DrillPanelProps) {
  const intel = data.intelligenceByTf[timeframe] ?? null;
  const structure = intel?.structure ?? null;
  const context = intel?.context ?? null;
  const patterns = intel?.patterns ?? null;
  const smc = intel?.smartMoney ?? null;
  const confluence = intel?.confluence ?? null;
  const indicators = data.indicatorsByTf[timeframe] ?? null;

  return (
    <>
      {/* Backdrop */}
      <div
        className="fixed inset-0 z-40 bg-black/50 backdrop-blur-sm"
        onClick={onClose}
      />

      {/* Panel */}
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
        <div className="flex-1 overflow-y-auto p-4 flex flex-col gap-3">
          {/* I7 Signal — top priority */}
          <Section label="I7 Signal">
            {signal ? (
              <SignalDetail signal={signal} />
            ) : (
              <Empty>No signal for {timeframe} — signals are generated on 1m</Empty>
            )}
          </Section>

          {/* I3 Structure */}
          <Section label="I3 Structure">
            {structure ? (
              <Grid>
                <KV label="Trend" value={structure.swing_trend ?? "—"} />
                <KV label="Integrity" value={structure.trend_integrity != null ? `${(structure.trend_integrity * 100).toFixed(0)}%` : "—"} />
                <KV label="Support" value={fmtPrice(structure.nearest_support)} />
                <KV label="Resistance" value={fmtPrice(structure.nearest_resistance)} />
                <KV label="Support str" value={fmtNum(structure.support_strength, 2)} />
                <KV label="Resist str" value={fmtNum(structure.resistance_strength, 2)} />
              </Grid>
            ) : <Empty>Awaiting {timeframe} intelligence</Empty>}
          </Section>

          {/* I4 Context */}
          <Section label="I4 Context">
            {context ? (
              <Grid>
                <KV label="Vol regime" value={context.volatility_regime ?? "—"} />
                <KV label="ATR pctile" value={context.atr_percentile != null ? `${(context.atr_percentile * 100).toFixed(0)}%` : "—"} />
                <KV label="Vol expan" value={context.vol_expanding != null ? (context.vol_expanding ? "yes" : "no") : "—"} />
                <KV label="Trend" value={context.trend_regime ?? "—"} />
                <KV label="Mom bias" value={context.momentum_bias != null ? fmtNum(context.momentum_bias, 2) : "—"} />
                <KV label="Mom dir" value={context.momentum_direction ?? "—"} />
              </Grid>
            ) : <Empty>Awaiting {timeframe} intelligence</Empty>}
          </Section>

          {/* I5 Patterns */}
          <Section label="I5 Patterns">
            {patterns ? (
              <Grid>
                <KV label="RSI div" value={patterns.rsi_divergence ?? "none"} />
                <KV label="RSI conf" value={fmtNum(patterns.rsi_div_confidence, 2)} />
                <KV label="BB squeeze" value={patterns.bb_squeeze != null ? (patterns.bb_squeeze ? `yes (${patterns.squeeze_count ?? 0}b)` : "no") : "—"} />
                <KV label="Vol div" value={patterns.volume_divergence ?? "none"} />
                <KV label="Confluence" value={patterns.confluence_score != null ? fmtNum(patterns.confluence_score, 2) : "—"} />
              </Grid>
            ) : <Empty>Awaiting {timeframe} intelligence</Empty>}
          </Section>

          {/* SMC */}
          <Section label="Smart Money">
            {smc ? (
              <Grid>
                <KV label="BOS" value={smc.bos_detected ? `${(smc.bos_direction ?? 0) > 0 ? "bullish" : "bearish"} @ ${fmtPrice(smc.bos_level)}` : "none"} />
                <KV label="CHoCH" value={smc.choch_detected ? `${(smc.choch_direction ?? 0) > 0 ? "bullish" : "bearish"}` : "none"} />
                <KV label="FVG" value={(smc.fvg_type ?? 0) !== 0 ? `${(smc.fvg_type ?? 0) > 0 ? "bull" : "bear"} ${fmtPrice(smc.fvg_bottom)}–${fmtPrice(smc.fvg_top)}` : "none"} />
                <KV label="Order blk" value={(smc.ob_type ?? 0) !== 0 ? `${(smc.ob_type ?? 0) > 0 ? "bull" : "bear"} @ ${fmtPrice(smc.ob_bottom)}` : "none"} />
                <KV label="Sweep" value={smc.sweep_detected ? `${(smc.sweep_type ?? 0) > 0 ? "bullish" : "bearish"}${smc.sweep_reclaimed ? " ✓reclaimed" : ""}` : "none"} />
                <KV label="HMM regime" value={smc.hmm_regime != null ? `${["ranging","up","down"][smc.hmm_regime] ?? smc.hmm_regime} (${((smc.hmm_regime_prob ?? 0) * 100).toFixed(0)}%)` : "—"} />
                <KV label="BSL" value={smc.bsl_level != null ? `${fmtPrice(smc.bsl_level)} (${fmtNum(smc.bsl_dist_atr, 1)} ATR)` : "—"} />
                <KV label="SSL" value={smc.ssl_level != null ? `${fmtPrice(smc.ssl_level)} (${fmtNum(smc.ssl_dist_atr, 1)} ATR)` : "—"} />
              </Grid>
            ) : <Empty>Awaiting {timeframe} intelligence</Empty>}
          </Section>

          {/* I6 Cross-TF Confluence */}
          <Section label="I6 Confluence">
            {confluence ? (
              <Grid>
                <KV label="CTF score" value={fmtNum(confluence.ctf_score, 2)} />
                <KV label="TFs aligned" value={`${confluence.ctf_timeframes_aligned ?? 0}/4`} />
                <KV label="Trend align" value={fmtNum(confluence.ctf_trend_alignment, 2)} />
                <KV label="Structure" value={fmtNum(confluence.ctf_structure_alignment, 2)} />
                <KV label="Regime agr" value={fmtNum(confluence.ctf_regime_agreement, 2)} />
              </Grid>
            ) : <Empty>Awaiting {timeframe} intelligence</Empty>}
          </Section>

          {/* I1 Indicators */}
          <Section label="I1 Indicators">
            {indicators ? (
              <Grid>
                <KV label="RSI" value={fmtNum(indicators.rsi, 1)} />
                <KV label="MACD" value={fmtNum(indicators.macd, 2)} />
                <KV label="Stoch K/D" value={`${fmtNum(indicators.stoch_k, 1)} / ${fmtNum(indicators.stoch_d, 1)}`} />
                <KV label="ATR" value={fmtNum(indicators.atr, 2)} />
                <KV label="VWAP" value={fmtPrice(indicators.vwap)} />
                <KV label="MFI" value={fmtNum(indicators.mfi, 1)} />
                <KV label="EMA 13/21" value={`${fmtPrice(indicators.ema_13)} / ${fmtPrice(indicators.ema_21)}`} />
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

function KV({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-baseline justify-between gap-1 min-w-0">
      <span className="text-[0.55rem] text-[var(--text-muted)] shrink-0">{label}</span>
      <span className="text-[0.6rem] font-data text-[var(--text-secondary)] truncate text-right">{value}</span>
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
  const target = signal.profit_target ?? null;
  const rr = signal.risk_reward_ratio ?? 0;
  const dirColor = isLong ? "var(--green)" : "var(--red)";
  const timeStr = signal.timestamp
    ? new Date(signal.timestamp).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false })
    : "—";

  return (
    <div className="flex flex-col gap-2">
      {/* Direction + meta */}
      <div className="flex items-center gap-2 flex-wrap">
        <span
          className="inline-flex px-2 py-0.5 rounded text-[0.6rem] font-bold uppercase tracking-widest"
          style={{ backgroundColor: isLong ? "var(--green-dim)" : "var(--red-dim)", color: dirColor }}
        >
          {isLong ? "LONG" : "SHORT"}
        </span>
        <span className="text-[0.6rem] text-[var(--text-secondary)]">{signal.signal_type.replace(/_/g, " ")}</span>
        <span className="text-[0.6rem] font-bold font-data" style={{ color: dirColor }}>{(signal.confidence * 100).toFixed(0)}%</span>
        <span className="text-[0.55rem] text-[var(--text-muted)]">{signal.timeframe} · {timeStr}</span>
      </div>
      {/* Levels */}
      <Grid>
        <KV label="Entry" value={fmtPrice(signal.entry_price)} />
        <KV label="Stop loss" value={fmtPrice(signal.stop_loss)} />
        {target !== null && <KV label="Profit target" value={fmtPrice(target)} />}
        {rr > 0 && <KV label="Risk/Reward" value={`${fmtNum(rr, 1)}R`} />}
        <KV label="Regime" value={signal.regime_context} />
        <KV label="Plugin" value={signal.setup_plugin.replace(/^trad_/, "")} />
      </Grid>
    </div>
  );
}
