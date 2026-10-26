"use client";

import { useState, useEffect, useRef, useCallback } from "react";
import { symbolConfig } from "@/lib/symbol-config";
import { getApiBase } from "@/lib/api";
import type {
  SymbolData,
  IndicatorData,
  StructureData,
  ContextData,
  PatternData,
  SmartMoneyData,
  ConfluenceData,
  ConnectionStatus,
  Timeframe,
  IntelligenceTfData,
  SessionState,
} from "@/lib/types";

const FLASH_DURATION_MS = 350;
const STALE_BAR_THRESHOLD_MS = 5 * 60_000;

function priceDirection(newPrice: number, oldPrice: number): "up" | "down" | null {
  if (newPrice > oldPrice) return "up";
  if (newPrice < oldPrice) return "down";
  return null;
}

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
    indicatorsByTf: {},
    intelligenceByTf: {},
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
// eslint-disable-next-line @typescript-eslint/no-explicit-any
function parseIntelligence(p: Record<string, any>): {
  structure: StructureData;
  context: ContextData;
  patterns: PatternData;
  smartMoney: SmartMoneyData;
  confluence: ConfluenceData;
} {
  // Payload IS the IntelligenceEvent dict (flat dict, not wrapped {"event": "<json>"})
  const event = p;

  // Extract tiers — fall back to empty object if tier is missing
  const i3 = event.i3 ?? {};
  const i4 = event.i4 ?? {};
  const i5 = event.i5 ?? {};
  const smc = event.smc ?? {};
  const i6 = event.i6 ?? {};

  const nf = (v: unknown) => (v != null ? Number(v) : 0);
  // Nullable variant: returns undefined instead of 0 when value is absent
  const nfn = (v: unknown): number | undefined => v != null ? Number(v) : undefined;
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
    // Market Profile
    poc_level: nfn(i3.poc_level),
    va_high: nfn(i3.va_high),
    va_low: nfn(i3.va_low),
    price_in_va: i3.price_in_va != null ? nf(i3.price_in_va) > 0 : undefined,
    poc_dist_pct: nfn(i3.poc_dist_pct),
    // Session Levels
    prior_session_high: nfn(i3.prior_session_high),
    prior_session_low: nfn(i3.prior_session_low),
    opening_gap_pct: nfn(i3.opening_gap_pct),
    weekly_pivot: nfn(i3.weekly_pivot),
    overnight_high: nfn(i3.overnight_high),
    overnight_low: nfn(i3.overnight_low),
    // Fibonacci
    nearest_fib_level: nfn(i3.nearest_fib_level),
    nearest_fib_ratio: nfn(i3.nearest_fib_ratio),
    nearest_fib_dist_atr: nfn(i3.nearest_fib_dist_atr),
    fib_cluster_strength: nfn(i3.fib_cluster_strength),
    // Swing Momentum
    struct_energy: nfn(i3.struct_energy),
    swing_velocity_trend: i3.swing_velocity_trend ?? undefined,
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
    garch_sigma: nfn(i4.garch_sigma),
    garch_vol_ratio: nfn(i4.garch_vol_ratio),
    garch_shock: nfn(i4.garch_shock),
    kalman_slope: nfn(i4.kalman_slope),
    kalman_price_position: nfn(i4.kalman_price_position),
    kalman_uncertainty: nfn(i4.kalman_uncertainty),
    // Hurst
    hurst_exponent: nfn(i4.hurst_exponent),
    hurst_trend_quality: nfn(i4.hurst_trend_quality),
    hurst_mr_quality: nfn(i4.hurst_mr_quality),
    // Shannon Entropy
    shannon_entropy: nfn(i4.shannon_entropy),
    entropy_quality: nfn(i4.entropy_quality),
    // VWAP
    session_vwap_deviation_sigma: nfn(i4.session_vwap_deviation_sigma),
    vwap_alignment_score: nfn(i4.vwap_alignment_score),
    above_session_vwap: i4.above_session_vwap != null ? nf(i4.above_session_vwap) > 0 : undefined,
    // Volume Profile levels
    nearest_hvn_level: nfn(i4.nearest_hvn_level),
    nearest_hvn_dist_atr: nfn(i4.nearest_hvn_dist_atr),
    nearest_lvn_level: nfn(i4.nearest_lvn_level),
    in_lvn: i4.in_lvn != null ? nf(i4.in_lvn) > 0 : undefined,
    // VIX / cross-asset
    vix_level: nfn(i4.vix_level),
    vix_z: nfn(i4.vix_z),
    eq_spread_z: nfn(i4.eq_spread_z),
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
    macd_divergence: i5.macd_div_bullish ? "bullish" : i5.macd_div_bearish ? "bearish" : null,
    macd_div_confidence: nfn(i5.macd_div_strength),
    cmf_divergence: i5.cmf_div_bullish ? "bullish" : i5.cmf_div_bearish ? "bearish" : null,
    cmf_div_confidence: nfn(i5.cmf_div_strength),
    obv_divergence: i5.obv_div_bullish ? "bullish" : i5.obv_div_bearish ? "bearish" : null,
    obv_div_confidence: nfn(i5.obv_div_strength),
    trend_confluence_score: nfn(i5.trend_confluence_score),
    trend_confluence_strength: nfn(i5.trend_confluence_strength),
    confluence_score: i5.confluence_score ?? undefined,
    // Chart patterns
    dt_db_pattern: nfn(i5.dt_db_pattern),
    dt_db_confidence: nfn(i5.dt_db_confidence),
    dt_db_neckline: nfn(i5.dt_db_neckline),
    dt_db_target: nfn(i5.dt_db_target),
    hs_pattern: nfn(i5.hs_pattern),
    hs_confidence: nfn(i5.hs_confidence),
    hs_neckline: nfn(i5.hs_neckline),
    hs_target: nfn(i5.hs_target),
    tri_pattern: nfn(i5.tri_pattern),
    tri_confidence: nfn(i5.tri_confidence),
    tri_breakout_bias: nfn(i5.tri_breakout_bias),
    flag_pattern: nfn(i5.flag_pattern),
    pennant_pattern: nfn(i5.pennant_pattern),
    flag_breakout_target: nfn(i5.flag_breakout_target),
    cup_handle_pattern: nfn(i5.cup_handle_pattern),
    cup_handle_target: nfn(i5.cup_handle_target),
    abcd_pattern_active: i5.abcd_pattern_active != null ? nf(i5.abcd_pattern_active) > 0 : undefined,
    abcd_direction: nfn(i5.abcd_direction),
    abcd_d_target: nfn(i5.abcd_d_target),
    key_level_reaction_type: nfn(i5.key_level_reaction_type),
    key_level_confluence_count: nfn(i5.key_level_confluence_count),
    // Candlestick patterns
    engulfing_bull: i5.engulfing_bull != null ? nf(i5.engulfing_bull) > 0 : undefined,
    engulfing_bear: i5.engulfing_bear != null ? nf(i5.engulfing_bear) > 0 : undefined,
    pin_bar_bull: i5.pin_bar_bull != null ? nf(i5.pin_bar_bull) > 0 : undefined,
    pin_bar_bear: i5.pin_bar_bear != null ? nf(i5.pin_bar_bear) > 0 : undefined,
    hammer_detected: i5.hammer_detected != null ? nf(i5.hammer_detected) > 0 : undefined,
    shooting_star_detected: i5.shooting_star_detected != null ? nf(i5.shooting_star_detected) > 0 : undefined,
    doji_detected: i5.doji_detected != null ? nf(i5.doji_detected) > 0 : undefined,
    morning_star: i5.morning_star != null ? nf(i5.morning_star) > 0 : undefined,
    evening_star: i5.evening_star != null ? nf(i5.evening_star) > 0 : undefined,
    three_white_soldiers: i5.three_white_soldiers != null ? nf(i5.three_white_soldiers) > 0 : undefined,
    three_black_crows: i5.three_black_crows != null ? nf(i5.three_black_crows) > 0 : undefined,
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
    premium_discount_pct: nfn(smc.premium_discount_pct),
    equilibrium_level: nfn(smc.equilibrium_level),
    pool_count: smc.pool_count ?? undefined,
    // ICT Killzones
    in_asia_killzone: nb(smc.in_asia_killzone),
    in_london_killzone: nb(smc.in_london_killzone),
    in_ny_am_killzone: nb(smc.in_ny_am_killzone),
    in_ny_pm_killzone: nb(smc.in_ny_pm_killzone),
    killzone_name: smc.killzone_name ?? undefined,
    minutes_in_killzone: nfn(smc.minutes_in_killzone),
    minutes_until_next_killzone: nfn(smc.minutes_until_next_killzone),
    // AMD Cycle
    amd_phase: smc.amd_phase ?? undefined,
    amd_manipulation_detected: nb(smc.amd_manipulation_detected),
    amd_distribution_direction: nfn(smc.amd_distribution_direction),
    // Supply / Demand Zones
    nearest_demand_high: nfn(smc.nearest_demand_high),
    nearest_demand_low: nfn(smc.nearest_demand_low),
    demand_freshness: nfn(smc.demand_freshness),
    demand_strength: nfn(smc.demand_strength),
    demand_dist_atr: nfn(smc.demand_dist_atr),
    in_demand_zone: nb(smc.in_demand_zone),
    nearest_supply_high: nfn(smc.nearest_supply_high),
    nearest_supply_low: nfn(smc.nearest_supply_low),
    supply_freshness: nfn(smc.supply_freshness),
    supply_strength: nfn(smc.supply_strength),
    supply_dist_atr: nfn(smc.supply_dist_atr),
    in_supply_zone: nb(smc.in_supply_zone),
    // Breaker Blocks
    breaker_block_active: nb(smc.breaker_block_active),
    breaker_block_type: nfn(smc.breaker_block_type),
    breaker_block_top: nfn(smc.breaker_block_top),
    breaker_block_bottom: nfn(smc.breaker_block_bottom),
    breaker_dist_atr: nfn(smc.breaker_dist_atr),
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
  const esRef = useRef<EventSource | null>(null);
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

    const base = getApiBase();
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
        flashDir = priceDirection(price, prevPrice);
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
      // Flash-clear: CSS-like fade via delayed state reset
      if (flashDir) {
        setTimeout(() => {
          setSymbolData((prev) => {
            const s = prev[sym];
            return s ? { ...prev, [sym]: { ...s, tickFlash: null, tick: { ...s.tick, tickFlash: null } } } : prev;
          });
        }, FLASH_DURATION_MS);
      }
      touch();
    });

    // --- Market data (OHLCV bars) ---
    es.addEventListener("market_data", (evt) => {
      const { payload } = JSON.parse(evt.data);
      const sym = contractToBase(payload.symbol || "");
      if (!sym) return;
      const close = parseFloat(String(payload.close || 0));
      let barFlash: "up" | "down" | null = null;
      setSymbolData((prev) => {
        const old = prev[sym];
        if (!old) return prev;
        const barHigh = parseFloat(String(payload.high || 0));
        const barLow = parseFloat(String(payload.low || 0));
        const barOpen = parseFloat(String(payload.open || 0));
        const barDate = String(payload.ts || "").slice(0, 10);
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
        // Guard: skip stale bars from gap-fill replay (older than 5 minutes)
        const barTs = new Date(payload.ts || 0).getTime();
        const now = Date.now();
        const staleBar = barTs > 0 && (now - barTs) > STALE_BAR_THRESHOLD_MS;
        // Log delivery latency: time since bar close (barTs + 60s) should be ~2-5s for live bars
        if (barTs > 0 && !staleBar) {
          const deliveryLatencyMs = now - (barTs + 60_000);
          if (deliveryLatencyMs > 10_000) {
            console.warn(`[market_data] slow bar delivery: ${payload.symbol} ts=${payload.ts} latency=${(deliveryLatencyMs / 1000).toFixed(1)}s`);
          }
        }
        const prevTick = old.tick;
        const tickFlash = priceDirection(close, prevTick.price);
        barFlash = tickFlash;
        const newTick = close > 0 && !staleBar
          ? {
              price: close,
              bid: prevTick.bid || close,
              ask: prevTick.ask || close,
              timestamp: String(payload.ts || ""),
              lastUpdate: Date.now(),
              tickFlash,
            }
          : prevTick;
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
              timestamp: String(payload.ts || ""),
              lastUpdate: Date.now(),
            },
            // Only update prevClose when initializing session; REST seed takes priority.
            prevClose: notSeeded ? (old.bar.close || close) : old.prevClose,
            session: newSession,
            tick: newTick,
            tickFlash,
            lastUpdate: Date.now(),
          },
        };
      });
      if (barFlash) {
        setTimeout(() => {
          setSymbolData((prev) => {
            const s = prev[sym];
            return s ? { ...prev, [sym]: { ...s, tickFlash: null, tick: { ...s.tick, tickFlash: null } } } : prev;
          });
        }, FLASH_DURATION_MS);
      }
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

    // --- Intelligence data (I1 + I3/I4/I5 combined) ---
    // NOTE: indicator_service is retired — I1 is now carried inside IntelligenceEvent.i1.
    // Extract both I1 (→ indicatorsByTf) and I3–I6 (→ intelligenceByTf) here.
    es.addEventListener("intelligence_data", (evt) => {
      const { payload } = JSON.parse(evt.data);
      // Payload IS the IntelligenceEvent dict (flat dict, not wrapped {"event": "<json>"})
      const event = payload;
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

      // Extract I1 indicators from event.i1 (same field names as old indicator_service)
      const i1 = event.i1 && typeof event.i1 === "object" ? event.i1 : {};
      const n1 = (k: string): number | undefined => {
        const v = i1[k];
        if (v == null) return undefined;
        const f = parseFloat(String(v));
        return isNaN(f) ? undefined : f;
      };
      const i1Mapped: Partial<IndicatorData> = {
        rsi: n1("rsi_14"),
        macd: n1("macd_12_26_9"),
        macd_signal: n1("macd_signal_12_26_9"),
        macd_histogram: n1("macd_histogram_12_26_9"),
        stoch_k: n1("stoch_k_14_3"),
        stoch_d: n1("stoch_d_14_3"),
        williams_r: n1("williams_r_14"),
        cci: n1("cci_14"),
        atr: n1("atr_14"),
        bb_upper: n1("bb_20_2_upper"),
        bb_middle: n1("bb_20_2_mid"),
        bb_lower: n1("bb_20_2_lower"),
        sma_20: n1("sma_20"),
        sma_50: n1("sma_50"),
        ema_13: n1("ema_13"),
        ema_21: n1("ema_21"),
        obv: n1("obv"),
        mfi: n1("mfi_14"),
        vwap: n1("vwap"),
        adx: n1("adx_14"),
        plus_di: n1("plus_di_14"),
        minus_di: n1("minus_di_14"),
        supertrend_dir: n1("supertrend_dir"),
        supertrend_value: n1("supertrend_value"),
        roc: n1("roc_14"),
        ao: n1("ao"),
        ac: n1("ac"),
      };

      setSymbolData((prev) => {
        const old = prev[sym];
        if (!old) return prev;
        const existingInd = old.indicatorsByTf[tf] ?? { symbol: sym, timeframe: tf, timestamp: "" };
        const mergedInd: IndicatorData = {
          ...existingInd,
          ...i1Mapped,
          symbol: sym,
          timeframe: tf,
          timestamp: String(event.ts || ""),
        };
        return {
          ...prev,
          [sym]: {
            ...old,
            intelligenceByTf: { ...old.intelligenceByTf, [tf]: intelligenceSnapshot },
            indicatorsByTf: { ...old.indicatorsByTf, [tf]: mergedInd },
            lastUpdate: Date.now(),
          },
        };
      });
      touch();
    });

    // --- Pipeline reset sentinel — clear stale intelligence state ---
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
            indicatorsByTf: {},
            intelligenceByTf: {},
          };
        }
        return next;
      });

      touch();
    });

    return () => {
      es.close();
      esRef.current = null;
    };
  }, [timeframe, symbolsCsv, touch]);

  return { symbolData, connectionStatus, lastUpdate };
}
