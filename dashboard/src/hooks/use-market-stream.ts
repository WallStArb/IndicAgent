"use client";

import { useState, useEffect, useRef, useCallback } from "react";
import { symbolConfig } from "@/lib/symbol-config";
import { pipelineLagS } from "@/lib/format";
import type {
  SymbolData,
  IndicatorData,
  StructureData,
  ContextData,
  PatternData,
  SmartMoneyData,
  ConfluenceData,
  SignalData,
  NarrativeData,
  GroupNarrativeData,
  ConnectionStatus,
  Timeframe,
  PerTfSignal,
  IntelligenceTfData,
  SessionState,
  SignalScorecardData,
  RankedSignal,
} from "@/lib/types";

function emptySymbolData(symbol: string): SymbolData {
  return {
    symbol,
    tick: { price: 0, bid: 0, ask: 0, timestamp: "", lastUpdate: 0, tickFlash: null },
    bar: {
      open: 0,
      high: 0,
      low: 0,
      close: 0,
      volume: 0,
      timestamp: "",
      lastUpdate: 0,
    },
    prevClose: 0,
    session: { open: 0, high: 0, low: 0, date: "", sessionVolume: 0 },
    tickFlash: null,
    indicators: null,
    structure: null,
    context: null,
    patterns: null,
    smartMoney: null,
    confluence: null,
    signal: null,
    tfSignals: {},
    signalsByTf: {},
    indicatorsByTf: {},
    intelligenceByTf: {},
    scorecardByTf: {},
    lastUpdate: 0,
  };
}

/** Map contract code (ESH6) back to base symbol (ES) for dashboard keying. */
function contractToBase(contract: string): string {
  const info = symbolConfig.getSymbolInfo(contract);
  if (info) return info.symbol;
  // Heuristic: strip trailing month+year digits (e.g., ESH6 → ES, RTYH6 → RTY)
  const m = contract.match(/^([A-Z]{1,4}?)[A-Z]\d+$/);
  return m ? m[1] : contract;
}

/** Parse raw intelligence payload into structured I3/I4/I5/SMC/I6 data.
 *
 * Stream format after Plan 01-01 migration:
 *   payload = { event: "<IntelligenceEvent JSON>" }
 * Parse the nested event, then access tiered fields.
 * See src/intelligence/schemas.py for IntelligenceEvent schema.
 */
function parseIntelligence(p: Record<string, string>): {
  structure: StructureData;
  context: ContextData;
  patterns: PatternData;
  smartMoney: SmartMoneyData;
  confluence: ConfluenceData;
} {
  // Parse the nested IntelligenceEvent JSON from the stream payload
  const event = JSON.parse(p.event || "{}");

  // Extract tiers — fall back to empty object if tier is missing
  const i3 = event.i3 ?? {};
  const i4 = event.i4 ?? {};
  const i5 = event.i5 ?? {};
  const smc = event.smc ?? {};
  const i6 = event.i6 ?? {};

  const nf = (v: unknown) => (v != null ? Number(v) : 0);
  // Boolean coercion for Redis-serialized "1"/"0" fields
  const nb = (v: unknown): boolean | undefined => v != null ? Number(v) > 0 : undefined;

  const td = i3.trend_direction != null ? Number(i3.trend_direction) : null;
  const structure: StructureData = {
    nearest_support: i3.nearest_support ?? undefined,
    nearest_resistance: i3.nearest_resistance ?? undefined,
    support_strength: i3.support_strength ?? undefined,
    resistance_strength: i3.resistance_strength ?? undefined,
    trend_integrity: i3.structure_integrity ?? undefined,
    swing_score: i3.trend_strength ?? undefined,
    swing_trend: td != null ? (td > 0 ? "uptrend" : td < 0 ? "downtrend" : "ranging") : undefined,
  };

  // Map numeric vol_regime to label
  const vr = nf(i4.vol_regime);
  const volLabel =
    vr <= -1 ? "low" : vr <= 0 ? "normal" : vr <= 1 ? "high" : "extreme";

  // Map numeric trend_regime to label
  const tr = nf(i4.trend_regime);
  const trendLabel =
    tr <= -0.75
      ? "strong_down"
      : tr <= -0.25
        ? "weak_down"
        : tr <= 0.25
          ? "neutral"
          : tr <= 0.75
            ? "weak_up"
            : "strong_up";

  const mb = nf(i4.momentum_bias);
  const momDir = mb > 0.2 ? "bullish" : mb < -0.2 ? "bearish" : "neutral";

  const context: ContextData = {
    volatility_regime: volLabel as ContextData["volatility_regime"],
    atr_percentile: i4.vol_percentile ?? undefined,
    bb_width: i4.bb_width_pct ?? undefined,
    vol_expanding: i4.vol_expansion != null ? nf(i4.vol_expansion) > 0 : undefined,
    trend_regime: trendLabel as ContextData["trend_regime"],
    momentum_bias: mb,
    momentum_direction: momDir as ContextData["momentum_direction"],
    garch_vol_regime: i4.garch_vol_regime != null ? Number(i4.garch_vol_regime) : undefined,
    garch_sigma: i4.garch_sigma != null ? nf(i4.garch_sigma) : undefined,
    garch_vol_ratio: i4.garch_vol_ratio != null ? nf(i4.garch_vol_ratio) : undefined,
    garch_shock: i4.garch_shock != null ? nf(i4.garch_shock) : undefined,
    kalman_slope: i4.kalman_slope != null ? nf(i4.kalman_slope) : undefined,
    kalman_price_position: i4.kalman_price_position != null ? nf(i4.kalman_price_position) : undefined,
    kalman_uncertainty: i4.kalman_uncertainty != null ? nf(i4.kalman_uncertainty) : undefined,
  };

  const patterns: PatternData = {
    rsi_divergence:
      i5.rsi_div_bullish
        ? "bullish"
        : i5.rsi_div_bearish
          ? "bearish"
          : null,
    rsi_div_confidence: i5.rsi_div_strength ?? undefined,
    bb_squeeze: i5.squeeze_active != null ? nf(i5.squeeze_active) > 0 : undefined,
    squeeze_count: i5.squeeze_duration ?? undefined,
    volume_divergence:
      i5.vol_div_bullish
        ? "bullish"
        : i5.vol_div_bearish
          ? "bearish"
          : null,
    vol_div_confidence: i5.vol_div_strength ?? undefined,
    confluence_score: i5.confluence_score ?? undefined,
  };

  // NOTE: schema renames trend_direction → smc_trend_direction to avoid
  // collision with I3Structure.trend_direction. SmartMoneyData.trend_direction
  // is populated from smc.smc_trend_direction.
  const smartMoney: SmartMoneyData = {
    bos_detected: smc.bos_detected ?? undefined,
    bos_direction: smc.bos_direction ?? undefined,
    bos_level: smc.bos_level ?? undefined,
    choch_detected: smc.choch_detected ?? undefined,
    choch_direction: smc.choch_direction ?? undefined,
    trend_direction: smc.smc_trend_direction ?? undefined,   // renamed in schema
    fvg_type: smc.fvg_type ?? undefined,
    fvg_top: smc.fvg_top ?? undefined,
    fvg_bottom: smc.fvg_bottom ?? undefined,
    fvg_midpoint: smc.fvg_midpoint ?? undefined,
    fvg_size_pct: smc.fvg_size_pct ?? undefined,
    fvg_open_count: smc.fvg_open_count ?? undefined,
    ob_type: smc.ob_type ?? undefined,
    ob_top: smc.ob_top ?? undefined,
    ob_bottom: smc.ob_bottom ?? undefined,
    ob_strength: smc.ob_strength ?? undefined,
    ob_distance_pct: smc.ob_distance_pct ?? undefined,
    sweep_detected: smc.sweep_detected ?? undefined,
    sweep_type: smc.sweep_type ?? undefined,
    sweep_level: smc.sweep_level ?? undefined,
    sweep_depth_pct: smc.sweep_depth_pct ?? undefined,
    sweep_reclaimed: smc.sweep_reclaimed ?? undefined,
    cp_detected: nb(smc.cp_detected),
    cp_probability: smc.cp_probability ?? undefined,
    cp_run_length: smc.cp_run_length ?? undefined,
    cp_confirmation: smc.cp_confirmation ?? undefined,
    // HMM Regime
    hmm_regime: smc.hmm_regime ?? undefined,
    hmm_regime_prob: smc.hmm_regime_prob ?? undefined,
    hmm_prob_ranging: smc.hmm_prob_ranging ?? undefined,
    hmm_prob_trending_up: smc.hmm_prob_trending_up ?? undefined,
    hmm_prob_trending_down: smc.hmm_prob_trending_down ?? undefined,
    hmm_regime_duration: smc.hmm_regime_duration ?? undefined,
    // Liquidity Zones
    bsl_level: smc.bsl_level ?? undefined,
    bsl_significance: smc.bsl_significance ?? undefined,
    bsl_dist_atr: smc.bsl_dist_atr ?? undefined,
    bsl_touches: smc.bsl_touches ?? undefined,
    ssl_level: smc.ssl_level ?? undefined,
    ssl_significance: smc.ssl_significance ?? undefined,
    ssl_dist_atr: smc.ssl_dist_atr ?? undefined,
    ssl_touches: smc.ssl_touches ?? undefined,
    price_in_premium: nb(smc.price_in_premium),
    premium_position: smc.premium_position ?? undefined,
    premium_discount_pct: smc.premium_discount_pct != null ? nf(smc.premium_discount_pct) : undefined,
    equilibrium_level: smc.equilibrium_level != null ? nf(smc.equilibrium_level) : undefined,
    pool_count: smc.pool_count ?? undefined,
    // ICT Killzones
    in_asia_killzone: nb(smc.in_asia_killzone),
    in_london_killzone: nb(smc.in_london_killzone),
    in_ny_am_killzone: nb(smc.in_ny_am_killzone),
    in_ny_pm_killzone: nb(smc.in_ny_pm_killzone),
    killzone_name: smc.killzone_name ?? undefined,
    minutes_in_killzone: smc.minutes_in_killzone != null ? nf(smc.minutes_in_killzone) : undefined,
    minutes_until_next_killzone: smc.minutes_until_next_killzone != null ? nf(smc.minutes_until_next_killzone) : undefined,
    // AMD Cycle
    amd_phase: smc.amd_phase ?? undefined,
    amd_manipulation_detected: nb(smc.amd_manipulation_detected),
    amd_distribution_direction: smc.amd_distribution_direction != null ? nf(smc.amd_distribution_direction) : undefined,
    // Supply / Demand Zones
    nearest_demand_high: smc.nearest_demand_high != null ? nf(smc.nearest_demand_high) : undefined,
    nearest_demand_low: smc.nearest_demand_low != null ? nf(smc.nearest_demand_low) : undefined,
    demand_freshness: smc.demand_freshness != null ? nf(smc.demand_freshness) : undefined,
    demand_strength: smc.demand_strength != null ? nf(smc.demand_strength) : undefined,
    demand_dist_atr: smc.demand_dist_atr != null ? nf(smc.demand_dist_atr) : undefined,
    in_demand_zone: nb(smc.in_demand_zone),
    nearest_supply_high: smc.nearest_supply_high != null ? nf(smc.nearest_supply_high) : undefined,
    nearest_supply_low: smc.nearest_supply_low != null ? nf(smc.nearest_supply_low) : undefined,
    supply_freshness: smc.supply_freshness != null ? nf(smc.supply_freshness) : undefined,
    supply_strength: smc.supply_strength != null ? nf(smc.supply_strength) : undefined,
    supply_dist_atr: smc.supply_dist_atr != null ? nf(smc.supply_dist_atr) : undefined,
    in_supply_zone: nb(smc.in_supply_zone),
    // Breaker Blocks
    breaker_block_active: nb(smc.breaker_block_active),
    breaker_block_type: smc.breaker_block_type != null ? nf(smc.breaker_block_type) : undefined,
    breaker_block_top: smc.breaker_block_top != null ? nf(smc.breaker_block_top) : undefined,
    breaker_block_bottom: smc.breaker_block_bottom != null ? nf(smc.breaker_block_bottom) : undefined,
    breaker_dist_atr: smc.breaker_dist_atr != null ? nf(smc.breaker_dist_atr) : undefined,
  };

  const confluence: ConfluenceData = {
    ctf_score: i6.ctf_score ?? undefined,
    ctf_trend_alignment: i6.ctf_trend_alignment ?? undefined,
    ctf_structure_alignment: i6.ctf_structure_alignment ?? undefined,
    ctf_regime_agreement: i6.ctf_regime_agreement ?? undefined,
    ctf_timeframes_aligned: i6.ctf_timeframes_aligned ?? undefined,
    ctf_highest_aligned_tf: i6.ctf_highest_aligned_tf ?? undefined,
  };

  return { structure, context, patterns, smartMoney, confluence };
}

export function useMarketStream(timeframe: Timeframe, symbols: string[]) {
  const [symbolData, setSymbolData] = useState<Record<string, SymbolData>>({});
  const [connectionStatus, setConnectionStatus] =
    useState<ConnectionStatus>("connecting");
  const [lastUpdate, setLastUpdate] = useState(0);
  const [narratives, setNarratives] = useState<Record<string, NarrativeData>>({});
  const [groupNarratives, setGroupNarratives] = useState<Record<string, GroupNarrativeData>>({});
  const [signalsHistory, setSignalsHistory] = useState<Record<string, SignalData[]>>({});
  const esRef = useRef<EventSource | null>(null);
  // Ref to track latest intelligence snapshots synchronously so signal_data handler
  // can read them without relying on state updater closure timing.
  const intelligenceSnapshotRef = useRef<Record<string, Record<string, IntelligenceTfData>>>({});

  // Max signals to keep in history per symbol (all TFs combined)
  const HISTORY_LIMIT = 50;

  // Stable identity for the symbols list
  const symbolsCsv = symbols.join(",");

  // Initialize symbol slots when symbols change
  useEffect(() => {
    const initial: Record<string, SymbolData> = {};
    for (const s of symbols) {
      initial[s] = emptySymbolData(s);
    }
    setSymbolData(initial);
  }, [symbolsCsv]); // eslint-disable-line react-hooks/exhaustive-deps

  const touch = useCallback(() => setLastUpdate(Date.now()), []);

  // Connect to SSE stream
  useEffect(() => {

    // Teardown previous
    esRef.current?.close();
    esRef.current = null;

    const base =
      process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000";
    const ALL_TFS = "1m,5m,15m,1h,4h,1d";
    const url = `${base}/api/sse/events?symbols=${encodeURIComponent(symbolsCsv)}&timeframe=${encodeURIComponent(ALL_TFS)}`;
    const es = new EventSource(url);
    esRef.current = es;

    es.onopen = () => setConnectionStatus("connected");
    es.onerror = () => setConnectionStatus("disconnected");

    // Seed session state from REST API (session data since 6pm ET boundary).
    // This runs in parallel with the SSE snapshot; the setState call will overwrite
    // any incomplete session values the SSE snapshot may have set first.
    const fetchSession = async () => {
      try {
        const sessionUrl = `${base}/api/market-data/session?symbols=${encodeURIComponent(symbolsCsv)}`;
        const res = await fetch(sessionUrl);
        if (!res.ok) return;
        const body = await res.json() as {
          session: Record<string, {
            session_open: number | null;
            session_high: number | null;
            session_low: number | null;
            session_volume: number;
            prev_close: number | null;
          }>
        };
        setSymbolData((prev) => {
          const next = { ...prev };
          for (const [sym, s] of Object.entries(body.session)) {
            if (!next[sym]) continue;
            next[sym] = {
              ...next[sym],
              prevClose: s.prev_close ?? next[sym].prevClose,
              session: {
                open: s.session_open ?? next[sym].session.open,
                high: s.session_high ?? next[sym].session.high,
                low: s.session_low ?? next[sym].session.low,
                date: next[sym].session.date,
                sessionVolume: s.session_volume,
              },
            };
          }
          return next;
        });
      } catch {
        // non-fatal — SSE bars will still accumulate session data
      }
    };
    void fetchSession();

    // Seed signalsByTf and signalsHistory from REST API on mount.
    // Ensures signals appear immediately on refresh/load without waiting
    // for a live SSE signal birth event.
    const fetchActiveSignals = async () => {
      try {
        const RESOLVED_STATUSES = new Set([
          "stopped_at_entry", "stopped_in_trade",
          "target_1", "target_1_2", "target_full",
          "ttl_expired_ahead", "ttl_expired_behind",
          "never_activated",
        ]);
        for (const sym of symbols) {
          const url = `${base}/api/signals/${encodeURIComponent(sym)}?limit=10`;
          const res = await fetch(url);
          if (!res.ok) continue;
          const body = await res.json() as {
            signals: Array<{
              signal_id: string;
              symbol: string;
              timeframe: string;
              setup_plugin: string;
              signal_type: string;
              direction: number;
              entry_price: number | null;
              stop_loss: number | null;
              confidence: number | null;
              status: string;
              outcome: string | null;
              exit_price: number | null;
              signal_computed_at: string | null;
              market_price_at_signal: number | null;
              entry_zone_low: number | null;
              entry_zone_high: number | null;
            }>;
          };
          // Group by timeframe — take the most recent per TF (results are DESC)
          const byTf: Record<string, SignalData> = {};
          for (const row of body.signals) {
            const tf = row.timeframe;
            if (byTf[tf]) continue; // already have one for this TF
            const dir = row.direction;
            if (dir === 0) continue; // skip terminal rows
            const isResolved = RESOLVED_STATUSES.has(row.status);
            const signal: SignalData = {
              symbol: sym,
              direction: dir > 0 ? "long" : "short",
              signal_type: row.signal_type || "",
              setup_plugin: row.setup_plugin || "",
              confidence: row.confidence ?? 0,
              entry_price: row.entry_price ?? 0,
              entry_type: "at_close",
              stop_loss: row.stop_loss ?? 0,
              stop_type: "atr",
              framing_method: "atr_fallback",
              risk_reward_ratio: 0,
              regime_context: "",
              timeframe: tf,
              timestamp: row.signal_computed_at || "",
              signal_computed_at: row.signal_computed_at ?? undefined,
              profit_target: null,
              signal_id: row.signal_id,
              market_price_at_signal: row.market_price_at_signal ?? undefined,
              entry_zone_low: row.entry_zone_low ?? undefined,
              entry_zone_high: row.entry_zone_high ?? undefined,
              resolved: isResolved || undefined,
              outcome: row.outcome ?? undefined,
              exit_price: row.exit_price ?? undefined,
            };
            byTf[tf] = signal;
          }
          if (Object.keys(byTf).length === 0) continue;
          setSymbolData((prev) => {
            const old = prev[sym];
            if (!old) return prev;
            // Only seed TFs that have no live signal yet (don't overwrite SSE data)
            const mergedByTf: Record<string, SignalData | null> = { ...byTf };
            for (const [tf, existing] of Object.entries(old.signalsByTf)) {
              mergedByTf[tf] = existing; // live data wins
            }
            return {
              ...prev,
              [sym]: {
                ...old,
                signalsByTf: mergedByTf,
                lastUpdate: Date.now(),
              },
            };
          });
          // Also seed signalsHistory (don't overwrite entries already present)
          setSignalsHistory((prev) => {
            const existing = prev[sym] || [];
            const existingIds = new Set(existing.map((s) => s.signal_id));
            const newEntries = Object.values(byTf).filter((s) => !existingIds.has(s.signal_id ?? ""));
            if (newEntries.length === 0) return prev;
            const merged = [...newEntries, ...existing].slice(0, HISTORY_LIMIT);
            return { ...prev, [sym]: merged };
          });
        }
      } catch {
        // non-fatal — SSE stream will populate signals as they arrive
      }
    };
    void fetchActiveSignals();

    // --- Tick data ---
    es.addEventListener("tick_data", (evt) => {
      const { payload } = JSON.parse(evt.data);
      const sym = contractToBase(payload.symbol || "");
      if (!sym) return;
      let flashDir: "up" | "down" | null = null;
      setSymbolData((prev) => {
        const old = prev[sym];
        if (!old) return prev;
        const price = parseFloat(String(payload.price || payload.last || old.tick.price));
        const prevPrice = old.tick.price;
        flashDir = price > prevPrice ? "up" : price < prevPrice ? "down" : null;
        return {
          ...prev,
          [sym]: {
            ...old,
            tick: {
              price,
              bid: parseFloat(String(payload.bid || old.tick.bid)),
              ask: parseFloat(String(payload.ask || old.tick.ask)),
              timestamp: String(payload.timestamp || ""),
              lastUpdate: Date.now(),
              tickFlash: flashDir,
            },
            tickFlash: flashDir,
            lastUpdate: Date.now(),
          },
        };
      });
      // Clear tickFlash after 350ms — done OUTSIDE setSymbolData callback
      if (flashDir) {
        setTimeout(() => {
          setSymbolData((prev) => ({
            ...prev,
            [sym]: prev[sym]
              ? { ...prev[sym], tickFlash: null, tick: { ...prev[sym].tick, tickFlash: null } }
              : prev[sym],
          }));
        }, 350);
      }
      touch();
    });

    // --- Market data (OHLCV bars) ---
    es.addEventListener("market_data", (evt) => {
      const { payload } = JSON.parse(evt.data);
      const sym = contractToBase(payload.symbol || "");
      if (!sym) return;
      setSymbolData((prev) => {
        const old = prev[sym];
        if (!old) return prev;
        const close = parseFloat(String(payload.close || 0));
        const barHigh = parseFloat(String(payload.high || 0));
        const barLow = parseFloat(String(payload.low || 0));
        const barOpen = parseFloat(String(payload.open || 0));
        const barDate = String(payload.timestamp || "").slice(0, 10);
        const barVol = parseFloat(String(payload.volume || 0));
        const sess = old.session;
        // Only initialize session from a bar when not yet seeded.
        // Once session.open > 0 (either from the REST seed or a prior bar), accumulate only.
        // This avoids false resets at calendar midnight (futures sessions span midnight).
        const notSeeded = sess.open === 0;
        const newSession: SessionState = notSeeded
          ? { open: barOpen, high: barHigh, low: barLow, date: barDate, sessionVolume: barVol }
          : {
              open: sess.open,
              high: Math.max(sess.high, barHigh),
              low: sess.low > 0 ? Math.min(sess.low, barLow) : barLow,
              date: barDate,
              sessionVolume: sess.sessionVolume + barVol,
            };
        return {
          ...prev,
          [sym]: {
            ...old,
            bar: {
              open: barOpen,
              high: barHigh,
              low: barLow,
              close,
              volume: barVol,
              timestamp: String(payload.timestamp || ""),
              lastUpdate: Date.now(),
            },
            // Only update prevClose when initializing session; REST seed takes priority.
            prevClose: notSeeded ? (old.bar.close || close) : old.prevClose,
            session: newSession,
            lastUpdate: Date.now(),
          },
        };
      });
      touch();
    });

    // --- Indicator data (flat dict with all indicators per event) ---
    es.addEventListener("indicator_data", (evt) => {
      const { payload } = JSON.parse(evt.data);
      const sym = contractToBase(payload.symbol || "");
      if (!sym) return;
      const tf = String(payload.timeframe || timeframe);

      const n = (k: string): number | undefined => {
        const v = payload[k];
        if (v == null) return undefined;
        const f = parseFloat(String(v));
        return isNaN(f) ? undefined : f;
      };

      // Map stream field names (e.g. rsi_14) → IndicatorData field names (e.g. rsi)
      const mapped: Partial<IndicatorData> = {
        rsi: n("rsi_14"),
        macd: n("macd_12_26_9"),
        macd_signal: n("macd_signal_12_26_9"),
        macd_histogram: n("macd_histogram_12_26_9"),
        stoch_k: n("stoch_k_14_3"),
        stoch_d: n("stoch_d_14_3"),
        williams_r: n("williams_r_14"),
        cci: n("cci_14"),
        atr: n("atr_14"),
        bb_upper: n("bb_20_2_upper"),
        bb_middle: n("bb_20_2_mid"),
        bb_lower: n("bb_20_2_lower"),
        sma_20: n("sma_20"),
        sma_50: n("sma_50"),
        ema_13: n("ema_13"),
        ema_21: n("ema_21"),
        obv: n("obv"),
        mfi: n("mfi_14"),
        vwap: n("vwap"),
        // ADX / Directional
        adx: n("adx_14"),
        plus_di: n("plus_di_14"),
        minus_di: n("minus_di_14"),
        // Supertrend
        supertrend_dir: n("supertrend_dir"),
        supertrend_value: n("supertrend_value"),
        // Momentum extras
        roc: n("roc_14"),
        // Bill Williams
        ao: n("ao"),
        ac: n("ac"),
      };

      setSymbolData((prev) => {
        const old = prev[sym];
        if (!old) return prev;
        const existing = old.indicatorsByTf[tf] ?? { symbol: sym, timeframe: tf, timestamp: "" };
        const merged: IndicatorData = {
          ...existing,
          ...mapped,
          symbol: sym,
          timeframe: tf,
          timestamp: String(payload.timestamp || ""),
        };
        return {
          ...prev,
          [sym]: {
            ...old,
            indicatorsByTf: { ...old.indicatorsByTf, [tf]: merged },
            lastUpdate: Date.now(),
          },
        };
      });
      touch();
    });

    // --- Intelligence data (I3/I4/I5 combined) ---
    es.addEventListener("intelligence_data", (evt) => {
      const { payload } = JSON.parse(evt.data);
      // Symbol and timeframe are nested inside payload.event (IntelligenceEvent JSON)
      const event = JSON.parse(payload.event || "{}");
      const sym = contractToBase(event.symbol || "");
      if (!sym) return;
      // FIX: IntelligenceEvent uses 'tf' not 'timeframe' (see src/intelligence/schemas.py)
      const tf = String(event.tf || timeframe);
      const { structure, context, patterns, smartMoney, confluence } = parseIntelligence(payload);

      const rawBar = event.bar;
      const barOhlcv = rawBar && typeof rawBar === "object" ? {
        open: Number(rawBar.open),
        high: Number(rawBar.high),
        low: Number(rawBar.low),
        close: Number(rawBar.close),
        volume: Number(rawBar.volume),
      } : undefined;

      const intelligenceSnapshot: IntelligenceTfData = {
        structure, context, patterns, smartMoney, confluence,
        barTime: String(event.ts || ""),
        barOhlcv,
        receivedAt: Date.now(),
      };

      // Keep ref in sync so signal_data handler can read synchronously
      if (!intelligenceSnapshotRef.current[sym]) intelligenceSnapshotRef.current[sym] = {};
      intelligenceSnapshotRef.current[sym][tf] = intelligenceSnapshot;

      setSymbolData((prev) => {
        const old = prev[sym];
        if (!old) return prev;
        return {
          ...prev,
          [sym]: {
            ...old,
            intelligenceByTf: { ...old.intelligenceByTf, [tf]: intelligenceSnapshot },
            lastUpdate: Date.now(),
          },
        };
      });
      touch();
    });

    // --- Aggregated signal data (I7) ---
    es.addEventListener("signal_data", (evt) => {
      const { payload } = JSON.parse(evt.data);
      const sym = contractToBase(payload.symbol || "");
      if (!sym) return;
      const dir = parseInt(String(payload.direction || "0"));
      const tf = String(payload.timeframe || timeframe);

      const _parseOptFloat = (v: unknown): number | null => {
        const n = parseFloat(String(v || "0"));
        return isNaN(n) || n === 0 ? null : n;
      };
      const _parseLabels = (v: unknown): string[] => {
        if (!v) return [];
        try { return JSON.parse(String(v)) as string[]; } catch { return []; }
      };
      const _signalComputedAt = payload.signal_computed_at
        ? String(payload.signal_computed_at) : undefined;
      const _barCloseTs = payload.bar_close_ts
        ? String(payload.bar_close_ts) : undefined;

      // Terminal lifecycle event — direction=0 with status + signal_id
      // Published by signal_lifecycle_service on every signal exit.
      // Match by signal_id so stale events for preempted signals are no-ops.
      if (dir === 0 && payload.status && payload.signal_id) {
        const resolvedId = String(payload.signal_id);
        setSymbolData((prev) => {
          const old2 = prev[sym];
          if (!old2) return prev;
          const currentSignal = old2.signalsByTf[tf];
          if (!currentSignal || currentSignal.signal_id !== resolvedId) {
            return prev; // stale resolved event for a preempted signal — no-op
          }
          const resolvedSignal: SignalData = {
            ...currentSignal,
            resolved: true,
            outcome: String(payload.status),
            exit_price: _parseOptFloat(payload.exit_price) ?? undefined,
          };
          return {
            ...prev,
            [sym]: {
              ...old2,
              signal: tf === timeframe ? resolvedSignal : old2.signal,
              signalsByTf: { ...old2.signalsByTf, [tf]: resolvedSignal },
              lastUpdate: Date.now(),
            },
          };
        });
        touch();
        return;
      }

      // Standard signal birth (direction != 0)
      if (dir !== 0) {
        // Build the signal object synchronously BEFORE any setState calls.
        // Reading intelligence from ref (not state) avoids the async updater trap
        // where assignments inside setSymbolData run during render, not immediately.
        const intelSnapshot = intelligenceSnapshotRef.current[sym]?.[tf] ?? null;

        const fullSignal: SignalData = {
          symbol: sym,
          direction: dir > 0 ? "long" : "short",
          signal_type: String(payload.signal_type || ""),
          setup_plugin: String(payload.setup_plugin || ""),
          confidence: parseFloat(String(payload.confidence || "0")),
          entry_price: parseFloat(String(payload.entry_price || "0")),
          entry_type: String(payload.entry_type || "at_close"),
          stop_loss: parseFloat(String(payload.stop_loss || "0")),
          stop_type: String(payload.stop_type || "atr"),
          profit_target: _parseOptFloat(payload.profit_target),
          profit_target_2: _parseOptFloat(payload.profit_target_2),
          profit_target_3: _parseOptFloat(payload.profit_target_3),
          target_labels: _parseLabels(payload.target_labels),
          rr_t1: _parseOptFloat(payload.rr_t1) ?? undefined,
          rr_t2: _parseOptFloat(payload.rr_t2) ?? undefined,
          rr_t3: _parseOptFloat(payload.rr_t3) ?? undefined,
          framing_method: String(payload.framing_method || "atr_fallback"),
          risk_reward_ratio: parseFloat(String(payload.risk_reward_ratio || "0")),
          regime_context: String(payload.regime_context || ""),
          timeframe: tf,
          timestamp: String(payload.timestamp || ""),
          signal_computed_at: _signalComputedAt,
          bar_close_ts: _barCloseTs,
          pipeline_lag_s: pipelineLagS(_signalComputedAt, _barCloseTs) ?? undefined,
          bar_close_price: _parseOptFloat(payload.bar_close_price) ?? undefined,
          market_price_at_signal: _parseOptFloat(payload.market_price_at_signal) ?? undefined,
          ask_at_signal: _parseOptFloat(payload.ask_at_signal) ?? undefined,
          bid_at_signal: _parseOptFloat(payload.bid_at_signal) ?? undefined,
          entry_zone_low: _parseOptFloat(payload.entry_zone_low) ?? undefined,
          entry_zone_high: _parseOptFloat(payload.entry_zone_high) ?? undefined,
          zone_valid_at_signal: payload.zone_valid_at_signal != null ? Number(payload.zone_valid_at_signal) > 0 : undefined,
          signal_id: String(payload.signal_id || ""),
          intelligence_snapshot: intelSnapshot,
        };

        // Lightweight matrix entry
        const tfSignal: PerTfSignal = {
          direction: dir > 0 ? "long" : dir < 0 ? "short" : null,
          confidence: parseFloat(String(payload.confidence || "0")),
          updatedAt: Date.now(),
        };

        setSymbolData((prev) => {
          const old = prev[sym];
          if (!old) return prev;

          // Card-level signal: only update for the selected global timeframe.
          // Per-TF signals (signalsByTf) are always stored for all TFs.
          const isSelectedTf = tf === timeframe;
          const signal = isSelectedTf ? fullSignal : old.signal;

          return {
            ...prev,
            [sym]: {
              ...old,
              signal,
              tfSignals: { ...old.tfSignals, [tf]: tfSignal },
              signalsByTf: { ...old.signalsByTf, [tf]: fullSignal },
              lastUpdate: Date.now(),
            },
          };
        });

        // Accumulate to history — fullSignal is synchronously available here
        setSignalsHistory((prev) => {
          const symHistory = prev[sym] || [];
          const newHistory = [fullSignal, ...symHistory].slice(0, HISTORY_LIMIT);
          return { ...prev, [sym]: newHistory };
        });

        touch();
      }
    });

    // --- Signal Scorecard (I7 all_ranked — which signals competed and why) ---
    es.addEventListener("signal_scorecard", (evt) => {
      const { payload } = JSON.parse(evt.data);
      const sym = contractToBase(payload.symbol || "");
      if (!sym) return;
      const tf = String(payload.tf || payload.timeframe || timeframe);
      let ranked: RankedSignal[] = [];
      try {
        ranked = JSON.parse(String(payload.data || "[]")) as RankedSignal[];
      } catch {
        return; // malformed payload — skip silently
      }
      const scorecard: SignalScorecardData = {
        ts: String(payload.ts || ""),
        symbol: sym,
        tf,
        ranked,
      };
      setSymbolData((prev) => {
        const old = prev[sym];
        if (!old) return prev;
        return {
          ...prev,
          [sym]: {
            ...old,
            scorecardByTf: { ...old.scorecardByTf, [tf]: scorecard },
            lastUpdate: Date.now(),
          },
        };
      });
      touch();
    });

    // --- AI narrative data (I8) — per-symbol and group ---
    es.addEventListener("narrative_data", (evt) => {
      const { stream, payload } = JSON.parse(evt.data);
      const streamStr = stream as string;
      const narrativeType: string = payload.narrative_type ?? "short";

      if (streamStr.includes(":group:")) {
        // Group synthesis narrative: stream = "narratives:group:equity"
        const parts = streamStr.split(":");
        const groupName = parts[parts.length - 1];
        if (!groupName || !payload.narrative) return;
        setGroupNarratives((prev) => ({
          ...prev,
          [groupName]: {
            group: groupName,
            narrative: String(payload.narrative),
            timestamp: String(payload.timestamp || ""),
            receivedAt: Date.now(),
            model: String(payload.model || ""),
          },
        }));
      } else {
        // Per-symbol narrative: stream = "narratives:ESH6:5m"
        // Short and deep merge into the same key so both are available simultaneously
        const sym = contractToBase(payload.symbol || "");
        if (!sym || !payload.narrative) return;
        const parts = streamStr.split(":");
        const tf = parts[parts.length - 1] || timeframe;
        const key = `${sym}:${tf}`;
        setNarratives((prev) => {
          const existing = prev[key] ?? {
            symbol: sym,
            timeframe: tf,
            action_bias: "",
            action_tag: "",
            timestamp: "",
            receivedAt: 0,
          };
          return {
            ...prev,
            [key]: {
              ...existing,
              action_bias: String(payload.action_bias ?? existing.action_bias),
              action_tag: String(payload.action_tag ?? existing.action_tag),
              timestamp: String(payload.timestamp ?? existing.timestamp),
              signal_id: String(payload.signal_id ?? existing.signal_id ?? ""),
              receivedAt: Date.now(),
              ...(narrativeType === "short"
                ? { narrative_short: String(payload.narrative), narrative: String(payload.narrative) }
                : { narrative_deep: String(payload.narrative) }
              ),
            },
          };
        });
      }
      touch();
    });

    // --- Pipeline reset sentinel — clear stale intelligence/signal/narrative state ---
    es.addEventListener("system_event", (evt) => {
      const { payload } = JSON.parse(evt.data) as { payload: Record<string, string> };
      if (payload.event !== "pipeline_reset") return;

      let resetSymbols: string[];
      try {
        resetSymbols = (JSON.parse(String(payload.symbols || "[]")) as string[]).map(contractToBase);
      } catch {
        resetSymbols = symbols;
      }

      setSymbolData((prev) => {
        const next = { ...prev };
        for (const sym of resetSymbols) {
          if (!next[sym]) continue;
          next[sym] = {
            ...next[sym],
            indicators: null,
            structure: null,
            context: null,
            patterns: null,
            smartMoney: null,
            confluence: null,
            signal: null,
            tfSignals: {},
            signalsByTf: {},
            indicatorsByTf: {},
            intelligenceByTf: {},
          };
        }
        return next;
      });

      setNarratives((prev) => {
        const next = { ...prev };
        for (const sym of resetSymbols) {
          for (const key of Object.keys(next).filter((k) => k.startsWith(`${sym}:`))) {
            delete next[key];
          }
        }
        return next;
      });

      setGroupNarratives({});
      touch();
    });

    return () => {
      es.close();
      esRef.current = null;
    };
  }, [timeframe, symbolsCsv, touch]);

  return { symbolData, connectionStatus, lastUpdate, narratives, groupNarratives, signalsHistory };
}
