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

/** Parse raw intelligence payload into structured I3/I4/I5/SMC/I6 data. */
function parseIntelligence(p: Record<string, string>): {
  structure: StructureData;
  context: ContextData;
  patterns: PatternData;
  smartMoney: SmartMoneyData;
  confluence: ConfluenceData;
} {
  const f = (k: string) => parseFloat(p[k] || "0");

  const structure: StructureData = {
    nearest_support: f("nearest_support"),
    nearest_resistance: f("nearest_resistance"),
    support_strength: f("support_strength"),
    resistance_strength: f("resistance_strength"),
    trend_integrity: f("structure_integrity"),
    swing_score: f("trend_strength"),
  };

  // Map numeric vol_regime to label
  const vr = f("vol_regime");
  const volLabel =
    vr <= -1 ? "low" : vr <= 0 ? "normal" : vr <= 1 ? "high" : "extreme";

  // Map numeric trend_regime to label
  const tr = f("trend_regime");
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

  const mb = f("momentum_bias");
  const momDir = mb > 0.2 ? "bullish" : mb < -0.2 ? "bearish" : "neutral";

  const context: ContextData = {
    volatility_regime: volLabel as ContextData["volatility_regime"],
    atr_percentile: f("vol_percentile"),
    bb_width: f("bb_width_pct"),
    vol_expanding: f("vol_expansion") > 0,
    trend_regime: trendLabel as ContextData["trend_regime"],
    momentum_bias: mb,
    momentum_direction: momDir as ContextData["momentum_direction"],
  };

  const patterns: PatternData = {
    rsi_divergence:
      f("rsi_div_bullish") > 0
        ? "bullish"
        : f("rsi_div_bearish") > 0
          ? "bearish"
          : null,
    rsi_div_confidence: f("rsi_div_strength"),
    bb_squeeze: f("squeeze_active") > 0,
    squeeze_count: f("squeeze_duration"),
    volume_divergence:
      f("vol_div_bullish") > 0
        ? "bullish"
        : f("vol_div_bearish") > 0
          ? "bearish"
          : null,
    vol_div_confidence: f("vol_div_strength"),
    confluence_score: f("confluence_score"),
  };

  const smartMoney: SmartMoneyData = {
    bos_detected: f("bos_detected") > 0,
    bos_direction: f("bos_direction"),
    bos_level: f("bos_level"),
    choch_detected: f("choch_detected") > 0,
    choch_direction: f("choch_direction"),
    trend_direction: f("trend_direction"),
    fvg_type: f("fvg_type"),
    fvg_top: f("fvg_top"),
    fvg_bottom: f("fvg_bottom"),
    fvg_midpoint: f("fvg_midpoint"),
    fvg_size_pct: f("fvg_size_pct"),
    fvg_open_count: f("fvg_open_count"),
    ob_type: f("ob_type"),
    ob_top: f("ob_top"),
    ob_bottom: f("ob_bottom"),
    ob_strength: f("ob_strength"),
    ob_distance_pct: f("ob_distance_pct"),
    sweep_detected: f("sweep_detected") > 0,
    sweep_type: f("sweep_type"),
    sweep_level: f("sweep_level"),
    sweep_depth_pct: f("sweep_depth_pct"),
    sweep_reclaimed: f("sweep_reclaimed") > 0,
    cp_detected: f("cp_detected") > 0,
    cp_probability: f("cp_probability"),
    cp_run_length: f("cp_run_length"),
    cp_confirmation: f("cp_confirmation"),
  };

  const confluence: ConfluenceData = {
    ctf_score: f("ctf_score") || undefined,
    ctf_trend_alignment: f("ctf_trend_alignment") || undefined,
    ctf_structure_alignment: f("ctf_structure_alignment") || undefined,
    ctf_regime_agreement: f("ctf_regime_agreement") || undefined,
    ctf_timeframes_aligned: f("ctf_timeframes_aligned") || undefined,
    ctf_highest_aligned_tf: f("ctf_highest_aligned_tf") || undefined,
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
