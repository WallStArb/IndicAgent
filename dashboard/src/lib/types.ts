// ── Market data types ──

export interface TickData {
  price: number;
  bid: number;
  ask: number;
  timestamp: string;
  lastUpdate: number;
  tickFlash: "up" | "down" | null;
}

export interface SessionState {
  open: number;
  high: number;
  low: number;
  date: string; // "YYYY-MM-DD" for reset detection
  sessionVolume: number; // accumulated bar volumes for current session
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
  ema_13?: number;
  ema_21?: number;
  // ADX / Directional
  adx?: number;
  plus_di?: number;
  minus_di?: number;
  // Supertrend
  supertrend_dir?: number;   // 1 = bullish, -1 = bearish
  supertrend_value?: number;
  // Momentum
  rsi?: number;
  macd?: number;
  macd_signal?: number;
  macd_histogram?: number;
  stoch_k?: number;
  stoch_d?: number;
  williams_r?: number;
  cci?: number;
  roc?: number;              // Rate of Change (14-period)
  // Bill Williams Oscillators
  ao?: number;               // Awesome Oscillator
  ac?: number;               // Accelerator Oscillator
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
  // Market Profile (I3)
  poc_level?: number;
  va_high?: number;
  va_low?: number;
  price_in_va?: boolean;
  poc_dist_pct?: number;
  // Session Levels (I3)
  prior_session_high?: number;
  prior_session_low?: number;
  opening_gap_pct?: number;     // % gap from prior close to today's open
  weekly_pivot?: number;
  overnight_high?: number;
  overnight_low?: number;
  // Fibonacci Zones (I3)
  nearest_fib_level?: number;
  nearest_fib_ratio?: number;   // e.g. 0.618
  nearest_fib_dist_atr?: number;
  fib_cluster_strength?: number; // 0-1
  // Swing Momentum (I3)
  struct_energy?: number;        // 0-1 combined amplitude+velocity score
  swing_velocity_trend?: "accelerating" | "decelerating" | "stable";
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
  // GARCH vol regime (I4)
  garch_vol_regime?: number;       // 0=low, 1=normal, 2=high
  // GARCH volatility model outputs (I4)
  garch_sigma?: number;           // GARCH conditional volatility estimate
  garch_vol_ratio?: number;       // GARCH sigma / realized vol (>1 = vol rising)
  garch_shock?: number;           // standardized return shock (magnitude; pipeline classifies regime)
  // Kalman filter trend outputs (I4)
  kalman_slope?: number;          // trend slope (+= up, -= down)
  kalman_price_position?: number; // price minus Kalman trend (deviation from smoothed level)
  kalman_uncertainty?: number;    // filter uncertainty (lower = more confident)
  // Hurst Exponent (I4)
  hurst_exponent?: number;        // 0.5=random, >0.5=trending, <0.5=mean-reverting
  hurst_trend_quality?: number;   // 0-1 quality as trending instrument
  hurst_mr_quality?: number;      // 0-1 quality as mean-reverting instrument
  // Shannon Entropy (I4)
  shannon_entropy?: number;       // price entropy (lower=more ordered/trending)
  entropy_quality?: number;       // 0-1 signal quality
  // VWAP deviation (I4)
  session_vwap_deviation_sigma?: number;  // sigma distance from session VWAP
  vwap_alignment_score?: number;          // 0-1 multi-VWAP alignment
  above_session_vwap?: boolean;
  // Volume Profile levels (I4)
  nearest_hvn_level?: number;     // nearest high-volume node
  nearest_hvn_dist_atr?: number;
  nearest_lvn_level?: number;     // nearest low-volume node (breakout zone)
  in_lvn?: boolean;               // price inside low-volume node
  // VIX / Cross-asset (I4)
  vix_level?: number;
  vix_z?: number;                 // VIX z-score vs 20-bar mean
  eq_spread_z?: number;           // dominant equity pair spread z-score
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
  // MACD Divergence (I5)
  macd_divergence?: "bullish" | "bearish" | null;
  macd_div_confidence?: number;
  // CMF Divergence (I5)
  cmf_divergence?: "bullish" | "bearish" | null;
  cmf_div_confidence?: number;
  // OBV Divergence (I5)
  obv_divergence?: "bullish" | "bearish" | null;
  obv_div_confidence?: number;
  // Trend Confluence (I5)
  trend_confluence_score?: number;   // 0-1 trend-following confluence
  trend_confluence_strength?: number;
  // Mean-Reversion Confluence (I5)
  confluence_score?: number; // -1 to +1
  confluence_label?: string;
  // Chart Patterns (I5) — only non-zero when pattern is forming/confirmed
  dt_db_pattern?: number;       // 0=none, 1=DT forming, 2=DT confirmed, 3=DB forming, 4=DB confirmed
  dt_db_confidence?: number;
  dt_db_neckline?: number;
  dt_db_target?: number;
  hs_pattern?: number;          // 0=none, 1=H&S forming, 2=confirmed, 3=IH&S forming, 4=confirmed
  hs_confidence?: number;
  hs_neckline?: number;
  hs_target?: number;
  tri_pattern?: number;         // 1=ascending, 2=descending, 3=symmetrical, 4=rising wedge, 5=falling wedge
  tri_confidence?: number;
  tri_breakout_bias?: number;   // -1/0/1
  flag_pattern?: number;        // 1=bull flag, 2=bear flag
  pennant_pattern?: number;
  flag_breakout_target?: number;
  cup_handle_pattern?: number;  // 1=forming, 2=confirmed
  cup_handle_target?: number;
  abcd_pattern_active?: boolean;
  abcd_direction?: number;      // -1/1
  abcd_d_target?: number;
  // Key Level Reaction (I5)
  key_level_reaction_type?: number;    // 1=bounce, -1=break, 0=none
  key_level_confluence_count?: number; // how many levels clustered
  // Candlestick patterns (I5) — top priority ones
  engulfing_bull?: boolean;
  engulfing_bear?: boolean;
  pin_bar_bull?: boolean;
  pin_bar_bear?: boolean;
  hammer_detected?: boolean;
  shooting_star_detected?: boolean;
  doji_detected?: boolean;
  morning_star?: boolean;
  evening_star?: boolean;
  three_white_soldiers?: boolean;
  three_black_crows?: boolean;
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

  // HMM Regime (I6 SMC) — from live Redis: hmm_regime: 0.0, hmm_regime_prob: 0.962
  hmm_regime?: number;              // 0=ranging, 1=trending_up, 2=trending_down
  hmm_regime_prob?: number;         // probability of current regime (0-1)
  hmm_prob_ranging?: number;        // probability of ranging regime
  hmm_prob_trending_up?: number;    // probability of trending up
  hmm_prob_trending_down?: number;  // probability of trending down
  hmm_regime_duration?: number;     // bars spent in current regime

  // Liquidity Zones — from live Redis: bsl_level: 6909.19, ssl_level: 6905.75
  bsl_level?: number;               // buy-side liquidity level (resistance above current price)
  bsl_significance?: number;        // 0-1 score (higher = more significant)
  bsl_dist_atr?: number;            // distance to BSL in ATR units
  bsl_touches?: number;             // times tested (higher = stronger level)
  ssl_level?: number;               // sell-side liquidity level (support below current price)
  ssl_significance?: number;
  ssl_dist_atr?: number;
  ssl_touches?: number;
  price_in_premium?: boolean;       // true = price above equilibrium (midpoint of BSL/SSL range)
  premium_position?: number;        // 0.0=full discount, 0.5=equilibrium, 1.0=full premium
  premium_discount_pct?: number;    // % above(+) or below(-) equilibrium
  equilibrium_level?: number;       // midpoint of swing range
  pool_count?: number;              // total liquidity pools detected in range
  // ICT Killzones
  in_asia_killzone?: boolean;
  in_london_killzone?: boolean;
  in_ny_am_killzone?: boolean;
  in_ny_pm_killzone?: boolean;
  killzone_name?: "Asia" | "London" | "NY AM" | "NY PM";
  minutes_in_killzone?: number;
  minutes_until_next_killzone?: number;
  // AMD Cycle (Wyckoff: Accumulation / Manipulation / Distribution)
  amd_phase?: "accumulation" | "manipulation" | "distribution";
  amd_manipulation_detected?: boolean;
  amd_distribution_direction?: number;  // -1 bearish | 0 neutral | 1 bullish
  // Supply / Demand Zones
  nearest_demand_high?: number;
  nearest_demand_low?: number;
  demand_freshness?: number;        // 0-1 (1 = untested)
  demand_strength?: number;         // 0-1
  demand_dist_atr?: number;
  in_demand_zone?: boolean;
  nearest_supply_high?: number;
  nearest_supply_low?: number;
  supply_freshness?: number;
  supply_strength?: number;
  supply_dist_atr?: number;
  in_supply_zone?: boolean;
  // Breaker Blocks
  breaker_block_active?: boolean;
  breaker_block_type?: number;      // -1 bearish | 1 bullish
  breaker_block_top?: number;
  breaker_block_bottom?: number;
  breaker_dist_atr?: number;
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

// ── Per-TF intelligence ──

export interface BarOhlcv {
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

/** Per-TF intelligence snapshot (I3/I4/I5/SMC/I6) */
export interface IntelligenceTfData {
  structure: StructureData;
  context: ContextData;
  patterns: PatternData;
  smartMoney: SmartMoneyData;
  confluence: ConfluenceData;
  barTime?: string;  // ISO bar timestamp from IntelligenceEvent.ts
  barOhlcv?: BarOhlcv;
  receivedAt?: number; // Date.now() when received
}

// ── Combined symbol state ──

export interface SymbolData {
  symbol: string;
  tick: TickData;
  bar: BarData;
  prevClose: number;
  session: SessionState;
  tickFlash: "up" | "down" | null;
  /** @deprecated Use indicatorsByTf[activeTf] in SymbolCard instead */
  indicators: IndicatorData | null;
  /** @deprecated Use intelligenceByTf[activeTf] in SymbolCard instead */
  structure: StructureData | null;
  /** @deprecated Use intelligenceByTf[activeTf] in SymbolCard instead */
  context: ContextData | null;
  /** @deprecated Use intelligenceByTf[activeTf] in SymbolCard instead */
  patterns: PatternData | null;
  /** @deprecated Use intelligenceByTf[activeTf] in SymbolCard instead */
  smartMoney: SmartMoneyData | null;
  /** @deprecated Use intelligenceByTf[activeTf] in SymbolCard instead */
  confluence: ConfluenceData | null;
  /** Per-TF I1 indicator snapshots — keyed by timeframe string ("1m", "5m", …) */
  indicatorsByTf: Record<string, IndicatorData>;
  /** Per-TF I3–I6 intelligence snapshots — keyed by timeframe string */
  intelligenceByTf: Record<string, IntelligenceTfData>;
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

