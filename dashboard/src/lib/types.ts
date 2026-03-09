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

// ── I7 Trading Signals ──

export interface SignalData {
  direction: "long" | "short";
  signal_type: string;           // e.g., "trend_long", "mean_rev_short"
  setup_plugin: string;          // e.g., "ind_TrendFollowing"
  confidence: number;            // 0.0–1.0
  entry_price: number;
  entry_type?: string;           // "at_close" | "at_reclaim" | "zone_proximal"
  stop_loss: number;
  stop_type?: string;            // "demand_zone" | "sweep_level" | "ob_bottom" | "swing_low" | "sr_support" | "atr"
  profit_target: number | null;  // targets[0] — T1
  profit_target_2?: number | null; // targets[1] — T2
  profit_target_3?: number | null; // targets[2] — T3
  target_labels?: string[];      // ["S/R 4521.25", "BSL 4530.00", "VWAP+2σ 4545.00"]
  rr_t1?: number;                // RR to T1
  rr_t2?: number;                // RR to T2
  rr_t3?: number;                // RR to T3 (only if structural and >= 4.0R)
  framing_method?: string;       // "structural" | "atr_fallback"
  risk_reward_ratio: number;     // computed from entry/stop/T1
  regime_context: string;        // "bullish" | "bearish"
  timeframe: string;             // which TF generated this signal, e.g. "1m"
  timestamp: string;             // ISO timestamp when signal was generated
  signal_computed_at?: string;   // ISO — when signal_generator_service fired this signal
  bar_close_ts?: string;         // ISO — when bar closed (pipeline lag start)
  pipeline_lag_s?: number;       // computed client-side: signal_computed_at - bar_close_ts
  bar_close_price?: number;      // close price of the bar that triggered the signal
  market_price_at_signal?: number; // live bid (short) or ask (long) at signal creation
  ask_at_signal?: number;        // live ask at signal creation
  bid_at_signal?: number;        // live bid at signal creation
  entry_zone_low?: number;       // proximal edge of entry zone
  entry_zone_high?: number;      // distal edge of entry zone
  zone_valid_at_signal?: boolean; // true = market was inside entry zone when signal fired
  signal_id?: string;            // unique identifier — used to match terminal lifecycle events
  // Resolved state — set when lifecycle service publishes direction=0 terminal event
  resolved?: boolean;            // true = signal closed, outcome known
  outcome?: string;              // 8-class: "never_activated" | "stopped_at_entry" | "stopped_in_trade" | "target_1" | "target_1_2" | "target_full" | "ttl_expired_behind" | "ttl_expired_ahead"
  exit_price?: number;           // price at which signal was closed
}

// ── I8 AI Narratives ──

export interface NarrativeData {
  symbol: string;
  timeframe: string;
  action_bias: string;           // "bullish" | "bearish"
  action_tag: string;            // "[BULLISH RECLAIM]" etc. — deterministic from signal
  narrative_short?: string;      // 2-sentence Context+Execution (~500ms)
  narrative_deep?: string;       // 3-sentence confluence story (~5-8s)
  timestamp: string;
  receivedAt: number;            // Date.now() when received — for staleness tracking
  signal_id?: string;            // correlates short + deep events for same signal
  // Keep for backward compat during transition
  narrative?: string;
}

export interface GroupNarrativeData {
  group: string;                 // e.g. "equity"
  narrative: string;
  timestamp: string;
  receivedAt: number;
  model: string;
}

/** Per-timeframe signal direction for cross-TF matrix */
export interface PerTfSignal {
  direction: "long" | "short" | null;
  confidence: number;
  updatedAt: number;
}

export type TfSignalMap = Record<string, PerTfSignal>; // key = timeframe string "1m" etc.

/** Per-TF intelligence snapshot (I3/I4/I5/SMC/I6) */
export interface IntelligenceTfData {
  structure: StructureData;
  context: ContextData;
  patterns: PatternData;
  smartMoney: SmartMoneyData;
  confluence: ConfluenceData;
  barTime?: string;  // ISO bar timestamp from IntelligenceEvent.ts
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
  signal: SignalData | null;
  tfSignals: TfSignalMap; // per-TF signal direction for matrix
  /** Full signal data per TF — keyed by timeframe string */
  signalsByTf: Record<string, SignalData | null>;
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
