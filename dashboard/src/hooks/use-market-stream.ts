"use client";

import { useState, useEffect, useRef, useCallback } from "react";
import { symbolConfig } from "@/lib/symbol-config";
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
  ConnectionStatus,
  Timeframe,
  PerTfSignal,
} from "@/lib/types";

function emptySymbolData(symbol: string): SymbolData {
  return {
    symbol,
    tick: { price: 0, bid: 0, ask: 0, timestamp: "", lastUpdate: 0 },
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
    indicators: null,
    structure: null,
    context: null,
    patterns: null,
    smartMoney: null,
    confluence: null,
    signal: null,
    tfSignals: {},
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

  const structure: StructureData = {
    nearest_support: i3.nearest_support ?? undefined,
    nearest_resistance: i3.nearest_resistance ?? undefined,
    support_strength: i3.support_strength ?? undefined,
    resistance_strength: i3.resistance_strength ?? undefined,
    trend_integrity: i3.structure_integrity ?? undefined,
    swing_score: i3.trend_strength ?? undefined,
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
    cp_detected: smc.cp_detected != null ? nf(smc.cp_detected) > 0 : undefined,
    cp_probability: smc.cp_probability ?? undefined,
    cp_run_length: smc.cp_run_length ?? undefined,
    cp_confirmation: smc.cp_confirmation ?? undefined,
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

    const base =
      process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000";
    const ALL_TFS = "1m,5m,15m,1h,4h,1d";
    const url = `${base}/api/sse/events?symbols=${encodeURIComponent(symbolsCsv)}&timeframe=${encodeURIComponent(ALL_TFS)}`;
    const es = new EventSource(url);
    esRef.current = es;

    es.onopen = () => setConnectionStatus("connected");
    es.onerror = () => setConnectionStatus("disconnected");

    // --- Tick data ---
    es.addEventListener("tick_data", (evt) => {
      const { payload } = JSON.parse(evt.data);
      const sym = contractToBase(payload.symbol || "");
      if (!sym) return;
      setSymbolData((prev) => {
        const old = prev[sym];
        if (!old) return prev;
        return {
          ...prev,
          [sym]: {
            ...old,
            tick: {
              price: parseFloat(String(payload.price || payload.last || old.tick.price)),
              bid: parseFloat(String(payload.bid || old.tick.bid)),
              ask: parseFloat(String(payload.ask || old.tick.ask)),
              timestamp: String(payload.timestamp || ""),
              lastUpdate: Date.now(),
            },
            lastUpdate: Date.now(),
          },
        };
      });
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
        return {
          ...prev,
          [sym]: {
            ...old,
            bar: {
              open: parseFloat(String(payload.open || 0)),
              high: parseFloat(String(payload.high || 0)),
              low: parseFloat(String(payload.low || 0)),
              close,
              volume: parseFloat(String(payload.volume || 0)),
              timestamp: String(payload.timestamp || ""),
              lastUpdate: Date.now(),
            },
            prevClose: old.bar.close || close,
            lastUpdate: Date.now(),
          },
        };
      });
      touch();
    });

    // --- Indicator data (one indicator per event, merge into map) ---
    es.addEventListener("indicator_data", (evt) => {
      const { payload } = JSON.parse(evt.data);
      const sym = contractToBase(payload.symbol || "");
      if (!sym) return;
      const name = (payload.indicator_name || "").toLowerCase();
      const value = parseFloat(String(payload.value || "0"));
      if (!name) return;

      setSymbolData((prev) => {
        const old = prev[sym];
        if (!old) return prev;
        const merged: IndicatorData = {
          ...(old.indicators || { symbol: sym, timeframe, timestamp: "" }),
          symbol: sym,
          timeframe,
          timestamp: String(payload.timestamp || ""),
          [name]: value,
        };
        return {
          ...prev,
          [sym]: { ...old, indicators: merged, lastUpdate: Date.now() },
        };
      });
      touch();
    });

    // --- Intelligence data (I3/I4/I5 combined) ---
    es.addEventListener("intelligence_data", (evt) => {
      const { payload } = JSON.parse(evt.data);
      const sym = contractToBase(payload.symbol || "");
      if (!sym) return;
      const { structure, context, patterns, smartMoney, confluence } = parseIntelligence(payload);

      setSymbolData((prev) => {
        const old = prev[sym];
        if (!old) return prev;
        return {
          ...prev,
          [sym]: {
            ...old,
            structure,
            context,
            patterns,
            smartMoney,
            confluence,
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

      setSymbolData((prev) => {
        const old = prev[sym];
        if (!old) return prev;

        // Update tfSignals for this specific timeframe
        const tfSignal: PerTfSignal = {
          direction: dir > 0 ? "long" : dir < 0 ? "short" : null,
          confidence: parseFloat(String(payload.confidence || "0")),
          updatedAt: Date.now(),
        };

        // Only update the card-level signal for the user's selected timeframe
        const isSelectedTf = tf === timeframe;
        const signal: SignalData | null =
          isSelectedTf && dir !== 0
            ? {
                direction: dir > 0 ? "long" : "short",
                signal_type: String(payload.signal_type || ""),
                setup_plugin: String(payload.setup_plugin || ""),
                confidence: parseFloat(String(payload.confidence || "0")),
                entry_price: parseFloat(String(payload.entry_price || "0")),
                stop_loss: parseFloat(String(payload.stop_loss || "0")),
                regime_context: String(payload.regime_context || ""),
                timestamp: String(payload.timestamp || ""),
              }
            : old.signal;

        return {
          ...prev,
          [sym]: {
            ...old,
            signal: signal ?? old.signal,
            tfSignals: { ...old.tfSignals, [tf]: tfSignal },
            lastUpdate: Date.now(),
          },
        };
      });
      touch();
    });

    // --- AI narrative data (I8) ---
    es.addEventListener("narrative_data", (evt) => {
      const { stream, payload } = JSON.parse(evt.data);
      const sym = contractToBase(payload.symbol || "");
      if (!sym || !payload.narrative) return;

      // Key by "SYMBOL:TF" — extract TF from stream name "narratives:ESH6:5m"
      const parts = (stream as string).split(":");
      const tf = parts[parts.length - 1] || timeframe;
      const key = `${sym}:${tf}`;

      setNarratives((prev) => ({
        ...prev,
        [key]: {
          symbol: sym,
          timeframe: tf,
          narrative: String(payload.narrative),
          action_bias: String(payload.action_bias || ""),
          timestamp: String(payload.timestamp || ""),
          receivedAt: Date.now(),
        },
      }));
      touch();
    });

    return () => {
      es.close();
      esRef.current = null;
    };
  }, [timeframe, symbolsCsv, touch]);

  return { symbolData, connectionStatus, lastUpdate, narratives };
}
