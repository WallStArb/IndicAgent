"use client";

import { useState, useEffect, useRef } from "react";
import type {
  SymbolData,
  IndicatorData,
  StructureData,
  ContextData,
  PatternData,
  ConnectionStatus,
  Timeframe,
} from "@/lib/types";

// ── Realistic base prices and volatility for each instrument ──

const INSTRUMENT_PROFILES: Record<
  string,
  { base: number; vol: number; tickSize: number }
> = {
  ES: { base: 6142, vol: 0.0008, tickSize: 0.25 },
  NQ: { base: 21850, vol: 0.0012, tickSize: 0.25 },
  RTY: { base: 2285, vol: 0.001, tickSize: 0.1 },
  CL: { base: 71.45, vol: 0.0015, tickSize: 0.01 },
  NG: { base: 3.82, vol: 0.002, tickSize: 0.001 },
  GC: { base: 2935, vol: 0.0006, tickSize: 0.1 },
  SI: { base: 33.45, vol: 0.0012, tickSize: 0.005 },
  HG: { base: 4.52, vol: 0.001, tickSize: 0.0005 },
  PL: { base: 1025, vol: 0.0008, tickSize: 0.1 },
  VX: { base: 16.8, vol: 0.003, tickSize: 0.05 },
};

// ── Random helpers ──

function rand(min: number, max: number): number {
  return min + Math.random() * (max - min);
}

function clamp(val: number, min: number, max: number): number {
  return Math.max(min, Math.min(max, val));
}

function pick<T>(arr: T[]): T {
  return arr[Math.floor(Math.random() * arr.length)];
}

// ── Simulation state per symbol ──

interface SimState {
  price: number;
  open: number;
  high: number;
  low: number;
  volume: number;
  rsi: number;
  macd: number;
  macdSignal: number;
  stochK: number;
  atr: number;
  obv: number;
  mfi: number;
  cci: number;
  trendBias: number; // -1 to +1, drifts slowly
  squeezeBars: number;
}

function initSimState(symbol: string): SimState {
  const profile = INSTRUMENT_PROFILES[symbol] || INSTRUMENT_PROFILES.ES;
  const price = profile.base * (1 + rand(-0.005, 0.005));
  return {
    price,
    open: price * (1 + rand(-0.002, 0.002)),
    high: price * (1 + rand(0, 0.003)),
    low: price * (1 - rand(0, 0.003)),
    volume: Math.round(rand(500, 5000)),
    rsi: rand(35, 65),
    macd: rand(-2, 2),
    macdSignal: rand(-1.5, 1.5),
    stochK: rand(25, 75),
    atr: price * rand(0.003, 0.008),
    obv: Math.round(rand(50000, 200000)),
    mfi: rand(35, 65),
    cci: rand(-80, 80),
    trendBias: rand(-0.5, 0.5),
    squeezeBars: 0,
  };
}

function stepSimState(symbol: string, prev: SimState): SimState {
  const profile = INSTRUMENT_PROFILES[symbol] || INSTRUMENT_PROFILES.ES;
  const vol = profile.vol;

  // Drift trend bias slowly
  const trendBias = clamp(
    prev.trendBias + rand(-0.05, 0.05),
    -0.8,
    0.8
  );

  // Price random walk with trend bias
  const pctChange = (trendBias * 0.0002) + rand(-vol, vol);
  const price = Math.max(
    profile.base * 0.9,
    prev.price * (1 + pctChange)
  );

  // Snap to tick size
  const snapped =
    Math.round(price / profile.tickSize) * profile.tickSize;

  const high = Math.max(prev.high, snapped);
  const low = Math.min(prev.low, snapped);
  const volume = prev.volume + Math.round(rand(10, 200));

  // Indicators: mean-revert with noise
  const rsi = clamp(
    prev.rsi + pctChange * 3000 + rand(-1.5, 1.5),
    8,
    95
  );
  const macd = prev.macd * 0.97 + pctChange * 500 + rand(-0.1, 0.1);
  const macdSignal = prev.macdSignal * 0.95 + macd * 0.05;
  const stochK = clamp(
    prev.stochK + pctChange * 2000 + rand(-2, 2),
    2,
    98
  );
  const atr = Math.max(
    0.001,
    prev.atr * 0.98 + Math.abs(pctChange) * price * 0.5
  );
  const obv =
    prev.obv + (pctChange > 0 ? 1 : -1) * Math.round(rand(50, 500));
  const mfi = clamp(
    prev.mfi + pctChange * 2000 + rand(-1, 1),
    5,
    95
  );
  const cci = clamp(
    prev.cci * 0.95 + pctChange * 5000 + rand(-5, 5),
    -250,
    250
  );
  const squeezeBars =
    atr < price * 0.004
      ? prev.squeezeBars + 1
      : 0;

  return {
    price: snapped,
    open: prev.open,
    high,
    low,
    volume,
    rsi,
    macd,
    macdSignal,
    stochK,
    atr,
    obv,
    mfi,
    cci,
    trendBias,
    squeezeBars,
  };
}

// ── Build typed data objects from sim state ──

function buildIndicators(
  symbol: string,
  s: SimState,
  timeframe: string
): IndicatorData {
  const sma20 = s.price * (1 + s.trendBias * -0.001);
  const sma50 = s.price * (1 + s.trendBias * -0.003);
  const ema12 = s.price * (1 + s.trendBias * 0.0005);
  const ema26 = s.price * (1 + s.trendBias * -0.001);
  const bbWidth = s.atr * 1.5;

  return {
    symbol,
    timeframe,
    timestamp: new Date().toISOString(),
    rsi: s.rsi,
    macd: s.macd,
    macd_signal: s.macdSignal,
    macd_histogram: s.macd - s.macdSignal,
    sma_10: s.price * (1 + s.trendBias * 0.0002),
    sma_20: sma20,
    sma_50: sma50,
    ema_13: ema12,
    ema_21: ema26,
    bb_upper: sma20 + bbWidth,
    bb_middle: sma20,
    bb_lower: sma20 - bbWidth,
    atr: s.atr,
    stoch_k: s.stochK,
    stoch_d: s.stochK * 0.85 + 7.5,
    williams_r: -(100 - s.stochK),
    obv: s.obv,
    mfi: s.mfi,
    vwap: s.price * (1 + rand(-0.001, 0.001)),
    volume_sma: Math.round(s.volume * 0.8),
    cci: s.cci,
  };
}

function buildStructure(s: SimState): StructureData {
  const trend =
    s.trendBias > 0.2
      ? "uptrend"
      : s.trendBias < -0.2
        ? "downtrend"
        : "ranging";

  const swings =
    trend === "uptrend"
      ? "HH → HL → HH"
      : trend === "downtrend"
        ? "LH → LL → LH"
        : "HH → LL → HL";

  return {
    swing_trend: trend,
    swing_sequence: swings,
    swing_score: s.trendBias,
    nearest_support: s.price * (1 - rand(0.005, 0.015)),
    nearest_resistance: s.price * (1 + rand(0.005, 0.015)),
    support_strength: Math.round(rand(2, 8)),
    resistance_strength: Math.round(rand(2, 8)),
    trend_integrity: clamp(0.5 + Math.abs(s.trendBias) * 0.5, 0.1, 0.95),
    price_position:
      s.trendBias > 0.1
        ? "above_sr"
        : s.trendBias < -0.1
          ? "below_sr"
          : "at_sr",
  };
}

function buildContext(s: SimState): ContextData {
  const atrPct = clamp(s.atr / (s.price * 0.01), 0, 1);
  const volRegime: ContextData["volatility_regime"] =
    atrPct > 0.7
      ? "extreme"
      : atrPct > 0.5
        ? "high"
        : atrPct > 0.25
          ? "normal"
          : "low";

  const trendRegime: ContextData["trend_regime"] =
    s.trendBias > 0.4
      ? "strong_up"
      : s.trendBias > 0.15
        ? "weak_up"
        : s.trendBias < -0.4
          ? "strong_down"
          : s.trendBias < -0.15
            ? "weak_down"
            : "neutral";

  const momBias = clamp(
    (s.rsi - 50) / 50 * 0.4 +
    (s.macd > 0 ? 0.2 : -0.2) +
    (s.stochK > 50 ? 0.15 : -0.15) +
    (s.cci > 0 ? 0.1 : -0.1),
    -1,
    1
  );

  return {
    volatility_regime: volRegime,
    atr_percentile: atrPct,
    bb_width: s.atr * 1.5 * 2,
    vol_expanding: atrPct > 0.4,
    trend_regime: trendRegime,
    momentum_bias: momBias,
    momentum_direction:
      momBias > 0.2
        ? "bullish"
        : momBias < -0.2
          ? "bearish"
          : "neutral",
  };
}

function buildPatterns(s: SimState): PatternData {
  const result: PatternData = {};

  // RSI divergence: fire occasionally when RSI is extreme
  if (s.rsi > 72 && s.trendBias < 0.1 && Math.random() > 0.6) {
    result.rsi_divergence = "bearish";
    result.rsi_div_confidence = rand(65, 90);
  } else if (s.rsi < 28 && s.trendBias > -0.1 && Math.random() > 0.6) {
    result.rsi_divergence = "bullish";
    result.rsi_div_confidence = rand(65, 90);
  }

  // Bollinger squeeze
  if (s.squeezeBars > 3) {
    result.bb_squeeze = true;
    result.squeeze_count = s.squeezeBars;
  }

  // Volume divergence: fire occasionally
  if (Math.random() > 0.85) {
    result.volume_divergence = pick(["bullish", "bearish"]);
    result.vol_div_confidence = rand(55, 85);
  }

  // Confluence score: derived from indicators
  const confScore = clamp(
    (s.rsi - 50) / 100 +
    (s.macd > 0 ? 0.15 : -0.15) +
    (s.stochK > 50 ? 0.1 : -0.1),
    -1,
    1
  );
  result.confluence_score = confScore;
  result.confluence_label =
    confScore > 0.3
      ? "bullish"
      : confScore < -0.3
        ? "bearish"
        : "mixed";

  return result;
}

// ── The hook ──

export function useDemoData(
  timeframe: Timeframe,
  symbols: string[]
) {
  const [symbolData, setSymbolData] = useState<Record<string, SymbolData>>({});
  const [connectionStatus] = useState<ConnectionStatus>("connected");
  const [lastUpdate, setLastUpdate] = useState(0);
  const simStates = useRef<Record<string, SimState>>({});

  // Stable key for symbol list identity
  const symbolsKey = symbols.join(",");

  // Initialize
  useEffect(() => {
    const activeSymbols = symbolsKey.split(",");
    const initial: Record<string, SymbolData> = {};
    const states: Record<string, SimState> = {};

    for (const sym of activeSymbols) {
      states[sym] = initSimState(sym);
      const s = states[sym];
      const today = new Date().toISOString().slice(0, 10);
      initial[sym] = {
        symbol: sym,
        tick: {
          price: s.price,
          bid: s.price - (INSTRUMENT_PROFILES[sym]?.tickSize || 0.25),
          ask: s.price + (INSTRUMENT_PROFILES[sym]?.tickSize || 0.25),
          timestamp: new Date().toISOString(),
          lastUpdate: Date.now(),
          tickFlash: null,
        },
        bar: {
          open: s.open,
          high: s.high,
          low: s.low,
          close: s.price,
          volume: s.volume,
          timestamp: new Date().toISOString(),
          lastUpdate: Date.now(),
        },
        prevClose: s.open,
        session: { open: s.open, high: s.high, low: s.low, date: today, sessionVolume: 0 },
        tickFlash: null,
        indicators: buildIndicators(sym, s, timeframe),
        structure: buildStructure(s),
        context: buildContext(s),
        patterns: buildPatterns(s),
        smartMoney: null,
        confluence: null,
        signal: null,
        tfSignals: {}, signalsByTf: {},
        indicatorsByTf: {},
        intelligenceByTf: {},
        lastUpdate: Date.now(),
      };
    }

    simStates.current = states;
    setSymbolData(initial);
    setLastUpdate(Date.now());
  }, [symbolsKey, timeframe]);

  // Tick simulation: update prices every 800-1500ms
  useEffect(() => {
    const activeSymbols = symbolsKey.split(",");
    const interval = setInterval(() => {
      const now = Date.now();

      setSymbolData((prev) => {
        const next = { ...prev };

        for (const sym of activeSymbols) {
          const oldState = simStates.current[sym];
          if (!oldState) continue;

          const newState = stepSimState(sym, oldState);
          simStates.current[sym] = newState;

          const tickSize =
            INSTRUMENT_PROFILES[sym]?.tickSize || 0.25;

          const prevPrice = prev[sym]?.tick.price ?? 0;
          const tickDir: "up" | "down" | null =
            newState.price > prevPrice ? "up" : newState.price < prevPrice ? "down" : null;
          const prevSess = prev[sym]?.session ?? { open: newState.open, high: newState.high, low: newState.low, date: "" };
          const nowDate = new Date().toISOString().slice(0, 10);
          const isNewSession = nowDate !== prevSess.date && prevSess.date !== "";
          const newSession = isNewSession
            ? { open: newState.open, high: newState.high, low: newState.low, date: nowDate, sessionVolume: 0 }
            : prevSess.date === ""
              ? { open: newState.open, high: newState.high, low: newState.low, date: nowDate, sessionVolume: 0 }
              : {
                  open: prevSess.open,
                  high: Math.max(prevSess.high, newState.high),
                  low: Math.min(prevSess.low > 0 ? prevSess.low : newState.low, newState.low),
                  date: nowDate,
                  sessionVolume: prevSess.sessionVolume,
                };
          next[sym] = {
            symbol: sym,
            tick: {
              price: newState.price,
              bid: newState.price - tickSize,
              ask: newState.price + tickSize,
              timestamp: new Date().toISOString(),
              lastUpdate: now,
              tickFlash: tickDir,
            },
            bar: {
              open: newState.open,
              high: newState.high,
              low: newState.low,
              close: newState.price,
              volume: newState.volume,
              timestamp: new Date().toISOString(),
              lastUpdate: now,
            },
            prevClose: prev[sym]?.prevClose || newState.open,
            session: newSession,
            tickFlash: tickDir,
            indicators: buildIndicators(sym, newState, timeframe),
            structure: buildStructure(newState),
            context: buildContext(newState),
            patterns: buildPatterns(newState),
            smartMoney: null,
            confluence: null,
            signal: null,
            tfSignals: prev[sym]?.tfSignals ?? {}, signalsByTf: prev[sym]?.signalsByTf ?? {},
            indicatorsByTf: prev[sym]?.indicatorsByTf ?? {},
            intelligenceByTf: prev[sym]?.intelligenceByTf ?? {},
            lastUpdate: now,
          };
        }

        return next;
      });

      setLastUpdate(now);
    }, 1000 + Math.random() * 500);

    return () => clearInterval(interval);
  }, [symbolsKey, timeframe]);

  return { symbolData, connectionStatus, lastUpdate };
}
