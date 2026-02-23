// ── Market data types ──

export interface TickData {
  price: number;
  bid: number;
  ask: number;
  timestamp: string;
  lastUpdate: number;
}

export interface BarData {
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
  timestamp: string;
  lastUpdate: number;
}

export interface IndicatorData {
  symbol: string;
  timeframe: string;
  timestamp: string;
  // Trend
  sma_10?: number;
  sma_20?: number;
  sma_50?: number;
  ema_12?: number;
  ema_26?: number;
  // Momentum
  rsi?: number;
  macd?: number;
  macd_signal?: number;
  macd_histogram?: number;
  stoch_k?: number;
  stoch_d?: number;
  williams_r?: number;
  cci?: number;
  // Volatility
  atr?: number;
  bb_upper?: number;
  bb_middle?: number;
  bb_lower?: number;
  // Volume
  obv?: number;
  mfi?: number;
  vwap?: number;
  volume_sma?: number;
}

// ── I3 Market Structure ──

export interface StructureData {
  // Swing detection
  swing_trend?: "uptrend" | "downtrend" | "ranging";
  swing_sequence?: string; // e.g. "HH → HL → HH"
  swing_score?: number; // -1 to +1
  // Support/Resistance
  nearest_support?: number;
  nearest_resistance?: number;
  support_strength?: number;
  resistance_strength?: number;
  // Trend structure
  trend_integrity?: number; // 0 to 1
  price_position?: "above_sr" | "below_sr" | "at_sr";
}

// ── I4 Context Classification ──

export interface ContextData {
  // Volatility regime
  volatility_regime?: "low" | "normal" | "high" | "extreme";
  atr_percentile?: number;
  bb_width?: number;
  vol_expanding?: boolean;
  // Trend regime
  trend_regime?:
    | "strong_up"
    | "weak_up"
    | "neutral"
    | "weak_down"
    | "strong_down";
  // Momentum context
  momentum_bias?: number; // -1 to +1
  momentum_direction?: "bullish" | "bearish" | "neutral";
}

// ── I5 Pattern Detection ──

export interface PatternData {
  // RSI Divergence
  rsi_divergence?: "bullish" | "bearish" | null;
  rsi_div_confidence?: number;
  // Bollinger Squeeze
  bb_squeeze?: boolean;
  squeeze_count?: number;
  // Volume Divergence
  volume_divergence?: "bullish" | "bearish" | null;
  vol_div_confidence?: number;
  // Confluence
  confluence_score?: number; // -1 to +1
  confluence_label?: string;
}

// ── Smart Money Concepts ──

export interface SmartMoneyData {
  // BOS / CHoCH
  bos_detected?: boolean;
  bos_direction?: number; // -1 bearish, 0 none, +1 bullish
  bos_level?: number;
  choch_detected?: boolean;
  choch_direction?: number;
  trend_direction?: number;
  // Fair Value Gap
  fvg_type?: number; // -1 bearish, 0 none, +1 bullish
  fvg_top?: number;
  fvg_bottom?: number;
  fvg_midpoint?: number;
  fvg_size_pct?: number;
  fvg_open_count?: number;
  // Order Blocks
  ob_type?: number; // -1 bearish, 0 none, +1 bullish
  ob_top?: number;
  ob_bottom?: number;
  ob_strength?: number;
  ob_distance_pct?: number;
  // Liquidity Sweeps
  sweep_detected?: boolean;
  sweep_type?: number; // -1 bearish, +1 bullish
  sweep_level?: number;
  sweep_depth_pct?: number;
  sweep_reclaimed?: boolean;
  // BOCPD Change Point
  cp_detected?: boolean;
  cp_probability?: number;
  cp_run_length?: number;
  cp_confirmation?: number;
}

// ── I6 Cross-Timeframe Confluence ──

export interface ConfluenceData {
  ctf_score?: number; // -1 to +1
  ctf_trend_alignment?: number;
  ctf_structure_alignment?: number;
  ctf_regime_agreement?: number;
  ctf_timeframes_aligned?: number; // 0-4
  ctf_highest_aligned_tf?: number; // minutes (5, 15, 60, etc.)
}

// ── I7 Trading Signals ──

export interface SignalData {
  direction: "long" | "short";
  signal_type: string;           // e.g., "trend_long", "mean_rev_short"
  setup_plugin: string;          // e.g., "ind_TrendFollowing"
  confidence: number;            // 0.0–1.0
  entry_price: number;
  stop_loss: number;
  regime_context: string;        // "bullish" | "bearish"
  timestamp: string;
}

// ── I8 AI Narratives ──

export interface NarrativeData {
  symbol: string;
  timeframe: string;
  narrative: string;             // AI-generated text (Redis key: "narrative")
  action_bias: string;           // "bullish" | "bearish"
  timestamp: string;
  receivedAt: number;            // Date.now() when received — for staleness tracking
}

/** Per-timeframe signal direction for cross-TF matrix */
export interface PerTfSignal {
  direction: "long" | "short" | null;
  confidence: number;
  updatedAt: number;
}

export type TfSignalMap = Record<string, PerTfSignal>; // key = timeframe string "1m" etc.

// ── Combined symbol state ──

export interface SymbolData {
  symbol: string;
  tick: TickData;
  bar: BarData;
  prevClose: number;
  indicators: IndicatorData | null;
  structure: StructureData | null;
  context: ContextData | null;
  patterns: PatternData | null;
  smartMoney: SmartMoneyData | null;
  confluence: ConfluenceData | null;
  signal: SignalData | null;
  tfSignals: TfSignalMap; // per-TF signal direction for matrix
  lastUpdate: number;
}

export type ConnectionStatus = "connecting" | "connected" | "disconnected";

export type Timeframe = "1m" | "5m" | "15m" | "1h" | "4h" | "1d";

export const TIMEFRAMES: { value: Timeframe; label: string; short: string }[] =
  [
    { value: "1m", label: "1 Minute", short: "1m" },
    { value: "5m", label: "5 Minutes", short: "5m" },
    { value: "15m", label: "15 Minutes", short: "15m" },
    { value: "1h", label: "1 Hour", short: "1H" },
    { value: "4h", label: "4 Hours", short: "4H" },
    { value: "1d", label: "1 Day", short: "1D" },
  ];
