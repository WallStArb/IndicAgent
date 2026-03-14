"""Canonical typed intelligence event schema for the intelligence bus.

All intelligence outputs flow through one IntelligenceEvent model.
Publishers validate plugin outputs via sub-model constructors (extra='forbid').
Consumers deserialize via IntelligenceEvent.model_validate_json().

Sub-model structure:
  OHLCVBar      — OHLCV snapshot that triggered computation
  I1Indicators  — I1 indicator plugin outputs (extra='allow': 23 plugins, ~50+ dynamic fields)
  I3Structure   — I3 market structure: swing, S/R, trend structure (extra='forbid')
  I4Context     — I4 context classification: regimes, GARCH, Kalman (extra='forbid')
  I5Patterns    — I5 pattern detection: divergence, squeeze, chart patterns (extra='forbid')
  SMCContext    — Smart Money Concepts: BOS/CHoCH, FVG, OB, sweeps,
                          BOCPD, HMM, pools, zones (extra="forbid")
  I6Confluence  — I6 cross-timeframe confluence (extra='forbid')

Field names are extracted from each plugin's outputs frozenset — no guesswork.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict


class OHLCVBar(BaseModel):
    """OHLCV snapshot that triggered this intelligence computation.

    Named OHLCVBar per locked CONTEXT.md decision (distinct from
    src/providers/base.py OHLCVBar which carries a source field).
    """

    model_config = ConfigDict(extra="forbid")
    o: float
    h: float
    l: float
    c: float
    v: int


class I1Indicators(BaseModel):
    """I1 indicator outputs — 23 plugins, ~50+ fields with period-encoded names.

    Uses extra='allow' because:
    - I1 field names include dynamic period suffixes (rsi_14, atr_14, etc.)
    - I1 outputs are already validated by indicator_service upstream
    - Strict forbid on I3–I6 where schema drift matters most

    Core fields declared for IDE/type-checker support.
    """

    model_config = ConfigDict(extra="allow")

    # RSIPlugin
    rsi_14: float | None = None
    # ATRPlugin
    atr_14: float | None = None
    # MACDPlugin
    macd_12_26_9: float | None = None
    macd_signal_12_26_9: float | None = None
    macd_histogram_12_26_9: float | None = None
    # BollingerBandsPlugin
    bb_20_2_upper: float | None = None
    bb_20_2_lower: float | None = None
    bb_20_2_mid: float | None = None
    # VolumeRatioPlugin
    volume_ratio: float | None = None
    # ROCPlugin
    roc_14: float | None = None
    # StochasticPlugin
    stoch_k_14_3: float | None = None
    stoch_d_14_3: float | None = None
    # ADXPlugin
    adx_14: float | None = None
    plus_di_14: float | None = None
    minus_di_14: float | None = None
    # CCIPlugin
    cci_14: float | None = None
    # WilliamsRPlugin
    williams_r_14: float | None = None
    # MFIPlugin
    mfi_14: float | None = None
    # OBVPlugin
    obv: float | None = None
    # SupertrendPlugin
    supertrend_dir: float | None = None
    # SMAPlugin (common cross-detection fields)
    sma_20_gt_50: float | None = None


class I2Events(BaseModel):
    """I2 composite indicator event outputs — crossovers, threshold crossings, extremes.

    Plugins: evt_MACDEvents, evt_RSIEvents, evt_StochasticEvents, evt_ADXEvents, evt_VolumeEvents
    MAComposite golden/death cross fields flow through I1Indicators (extra='allow').
    """

    model_config = ConfigDict(extra="allow")

    # MACDEvents
    macd_cross_bullish: float | None = None
    macd_cross_bearish: float | None = None
    macd_cross_bars_ago: float | None = None
    macd_hist_positive: float | None = None
    macd_hist_turning_up: float | None = None
    macd_negative_support_test: float | None = None
    macd_price_divergence_bullish: float | None = None
    macd_price_divergence_bearish: float | None = None

    # RSIEvents
    rsi_crossed_30_up: float | None = None
    rsi_crossed_70_down: float | None = None
    rsi_crossed_50_up: float | None = None
    rsi_crossed_50_down: float | None = None
    rsi_extreme_reversal: float | None = None
    rsi_bars_in_extreme: float | None = None

    # StochasticEvents
    stoch_cross_bullish: float | None = None
    stoch_cross_bearish: float | None = None
    stoch_oversold_reversal: float | None = None
    stoch_overbought_reversal: float | None = None
    stoch_both_oversold: float | None = None
    stoch_both_overbought: float | None = None

    # ADXEvents
    adx_trend_confirmed: float | None = None
    adx_ranging_confirmed: float | None = None
    di_cross_bullish: float | None = None
    di_cross_bearish: float | None = None
    di_cross_bars_ago: float | None = None
    di_spread: float | None = None

    # VolumeEvents
    vol_spike: float | None = None
    vol_drying: float | None = None
    bb_upper_touch: float | None = None
    bb_lower_touch: float | None = None
    bb_walking_upper: float | None = None
    bb_walking_lower: float | None = None

    # Bridge composites — translate I1 price-relative outputs into directional signals
    donchian_position_20: float | None = None  # DonchianPosition composite
    obv_slope_sign: float | None = None  # OBVMomentum composite


class I3Structure(BaseModel):
    """I3 market structure outputs — structural facts about price.

    Plugins:
    - struct_SwingDetector (9 fields)
    - struct_SupportResistance (9 fields)
    - struct_TrendStructure (6 fields)
    - struct_MarketProfile (9 fields)
    - struct_SessionLevels (16 fields)
    - struct_AnchoredVWAP (8 fields)
    - struct_FibonacciZones (12 fields)
    - struct_SwingMomentum (6 fields)
    Total: 75 fields
    """

    model_config = ConfigDict(extra="forbid")

    # SwingDetectorPlugin outputs
    swing_high: float | None = None
    swing_low: float | None = None
    swing_high_idx: float | None = None
    swing_low_idx: float | None = None
    swing_pattern: float | None = None
    # 1.0=uptrend (HH+HL), -1.0=downtrend (LH+LL), 0.0=mixed
    swing_high_type: float | None = None  # 1.0=HH, -1.0=LH, 0.0=none
    swing_low_type: float | None = None  # 1.0=HL, -1.0=LL, 0.0=none
    swing_high_age_bars: float | None = None
    swing_low_age_bars: float | None = None

    # SupportResistancePlugin outputs
    nearest_resistance: float | None = None
    nearest_support: float | None = None
    resistance_strength: float | None = None
    support_strength: float | None = None
    resistance_dist_pct: float | None = None
    support_dist_pct: float | None = None
    sr_level_count: float | None = None
    resistance_age_bars: float | None = None
    support_age_bars: float | None = None

    # TrendStructurePlugin outputs
    trend_direction: float | None = None  # -1.0/0.0/1.0 numeric
    trend_strength: float | None = None
    trend_leg_count: float | None = None
    structure_integrity: float | None = None
    price_position: float | None = None
    trend_duration_bars: float | None = None

    # MarketProfilePlugin outputs
    poc_level: float | None = None
    va_high: float | None = None
    va_low: float | None = None
    va_width_pct: float | None = None
    price_in_va: float | None = None
    price_above_va: float | None = None
    price_below_va: float | None = None
    poc_dist_pct: float | None = None
    poc_dist_atr: float | None = None

    # SessionLevelsPlugin outputs
    prior_session_high: float | None = None
    prior_session_low: float | None = None
    prior_session_close: float | None = None
    overnight_high: float | None = None
    overnight_low: float | None = None
    overnight_range_pct: float | None = None
    opening_gap_pct: float | None = None
    weekly_pivot: float | None = None
    weekly_r1: float | None = None
    weekly_r2: float | None = None
    weekly_s1: float | None = None
    weekly_s2: float | None = None
    nearest_session_level: float | None = None
    nearest_level_dist_atr: float | None = None
    asian_session_high: float | None = None
    asian_session_low: float | None = None

    # AnchoredVWAPPlugin outputs
    session_vwap: float | None = None
    session_vwap_dist_pct: float | None = None
    swing_vwap: float | None = None
    weekly_vwap: float | None = None
    above_session_vwap: float | None = None
    above_swing_vwap: float | None = None
    above_weekly_vwap: float | None = None
    vwap_alignment_score: float | None = None

    # FibonacciZonesPlugin outputs
    fib_swing_high: float | None = None
    fib_swing_low: float | None = None
    fib_236: float | None = None
    fib_382: float | None = None
    fib_500: float | None = None
    fib_618: float | None = None
    fib_786: float | None = None
    nearest_fib_level: float | None = None
    nearest_fib_ratio: float | None = None
    nearest_fib_dist_atr: float | None = None
    fib_cluster_strength: float | None = None
    in_fib_discount_zone: float | None = None

    # SwingMomentumPlugin outputs
    swing_amplitude_ratio: float | None = None
    swing_amplitude_expanding: int | None = None
    swing_velocity_bars: float | None = None
    swing_velocity_trend: Literal["accelerating", "decelerating", "stable"] | None = None
    struct_energy: float | None = None
    struct_accel_bias: Literal[-1, 0, 1] | None = None


class I4Context(BaseModel):
    """I4 context classification outputs — quantitative regime assessment.

    Plugins:
    - VolatilityRegime (5 fields)
    - TrendRegime (4 fields)
    - MomentumContext (4 fields)
    - GARCHVolatility (4 fields)
    - KalmanTrend (7 fields)
    - SessionContext (27 fields: 12 legacy + 6 exchange-active + 3 break + 2 overlap + 4 sub-session)
    - MTFVolatility (4 fields)
    - ShannonEntropy (2 fields)
    Total: 57 fields
    """

    model_config = ConfigDict(extra="forbid")

    # VolatilityRegimePlugin outputs
    vol_regime: float | None = None
    vol_percentile: float | None = None
    vol_expansion: float | None = None
    bb_width_pct: float | None = None
    bb_width_percentile: float | None = None

    # TrendRegimePlugin outputs
    trend_regime: float | None = None
    trend_confidence: float | None = None
    ma_alignment: float | None = None
    price_vs_sma20_pct: float | None = None

    # MomentumContextPlugin outputs
    momentum_bias: float | None = None
    momentum_strength: float | None = None
    momentum_agreement: float | None = None
    momentum_n_signals: float | None = None

    # GARCHVolatilityPlugin outputs
    garch_sigma: float | None = None
    garch_vol_ratio: float | None = None
    garch_vol_regime: int | None = None  # int: 0/1/2 regime levels, NOT float
    garch_shock: float | None = None

    # KalmanTrendPlugin outputs
    kalman_trend: float | None = None
    kalman_slope: float | None = None
    kalman_price_position: float | None = None
    kalman_uncertainty: float | None = None
    kalman_upper: float | None = None
    kalman_lower: float | None = None
    kalman_gain: float | None = None

    # SessionContextPlugin outputs
    session_asia: float | None = None
    session_london: float | None = None
    session_ny: float | None = None
    session_london_ny_overlap: float | None = None
    session_after_hours: float | None = None
    in_london_killzone: float | None = None
    in_ny_killzone: float | None = None
    minutes_to_ny_open: float | None = None
    minutes_to_london_open: float | None = None
    bars_since_session_start: float | None = None
    is_monday: float | None = None
    is_friday: float | None = None

    # SessionContextPlugin — exchange-active flags (equity expansion)
    session_nyse_active: float | None = None
    session_lse_active: float | None = None
    session_tse_active: float | None = None
    session_hkex_active: float | None = None
    session_sse_active: float | None = None
    session_asx_active: float | None = None
    # SessionContextPlugin — trading break flags
    session_tse_in_break: float | None = None
    session_hkex_in_break: float | None = None
    session_sse_in_break: float | None = None
    # SessionContextPlugin — market overlap flags
    session_tokyo_london_overlap: float | None = None
    session_ny_sydney_overlap: float | None = None
    # SessionContextPlugin — instrument sub-session
    session_elapsed_frac: float | None = None
    is_opening_range: float | None = None
    is_lunch_consolidation: float | None = None
    is_power_hour: float | None = None

    # MTFVolatilityPlugin outputs
    mtf_vol_expansion_15m: float | None = None
    mtf_vol_expansion_1h: float | None = None
    squeeze_within_expansion: float | None = None
    vol_divergence_score: float | None = None

    # ShannonEntropyPlugin outputs
    shannon_entropy: float | None = None
    entropy_quality: float | None = None


class I5Patterns(BaseModel):
    """I5 pattern detection outputs.

    Plugins:
    - patt_RSIDivergence (3 fields)
    - patt_BollingerSqueeze (4 fields)
    - patt_Confluence (6 fields)
    - patt_VolumeDivergence (3 fields)
    - patt_DoubleTB (4 fields)
    - patt_HeadShoulders (5 fields)
    - TrendConfluence (4 fields)
    - patt_TriangleWedge (6 fields)
    - patt_CandlestickPatterns (19 fields)
    - patt_FlagPennant (4 fields)
    - patt_CupHandle (3 fields)
    - patt_MeasuredMove (4 fields)
    - patt_VolumeProfile (4 fields)
    - patt_KeyLevelReaction (2 fields)
    Total: 70 fields
    """

    model_config = ConfigDict(extra="forbid")

    # RSIDivergencePlugin outputs
    rsi_div_bullish: float | None = None  # confidence score 0.0–1.0 (not a boolean flag)
    rsi_div_bearish: float | None = None  # confidence score 0.0–1.0
    rsi_div_strength: float | None = None

    # BollingerSqueezePlugin outputs
    squeeze_active: float | None = None
    squeeze_duration: float | None = None
    squeeze_bandwidth_pctile: float | None = None
    squeeze_fired: float | None = None

    # ConfluencePlugin outputs (mean-reversion)
    confluence_score: float | None = None
    confluence_n_signals: float | None = None
    confluence_agreement: float | None = None
    meanrev_confluence_score: float | None = None
    meanrev_confluence_n_signals: float | None = None
    meanrev_confluence_agreement: float | None = None

    # VolumeDivergencePlugin outputs
    vol_div_bullish: float | None = None  # confidence score 0.0–1.0 (not a boolean flag)
    vol_div_bearish: float | None = None  # confidence score 0.0–1.0
    vol_div_strength: float | None = None

    # DoubleTBPlugin outputs (double top/bottom)
    dt_db_pattern: float | None = None
    # 0=none, 1=DT forming, 2=DT confirmed, 3=DB forming, 4=DB confirmed
    dt_db_neckline: float | None = None
    dt_db_target: float | None = None
    dt_db_confidence: float | None = None

    # HeadShouldersPlugin outputs
    hs_pattern: float | None = None
    # 0=none, 1=H&S forming, 2=confirmed, 3=IH&S forming, 4=confirmed
    hs_neckline: float | None = None
    hs_target: float | None = None
    hs_confidence: float | None = None
    hs_neckline_distance: float | None = None

    # TrendConfluencePlugin outputs (trend-following confluece)
    trend_confluence_score: float | None = None
    trend_confluence_n_signals: float | None = None
    trend_confluence_agreement: float | None = None
    trend_confluence_strength: float | None = None

    # TriangleWedgePlugin outputs
    tri_pattern: float | None = None
    # 0=none, 1=ascending, 2=descending, 3=symmetrical, 4=rising wedge, 5=falling wedge
    tri_upper_slope: float | None = None
    tri_lower_slope: float | None = None
    tri_apex_bars: float | None = None
    tri_breakout_bias: float | None = None  # -1/0/1
    tri_confidence: float | None = None

    # CandlestickPatternsPlugin outputs (19 total fields)
    engulfing_bull: float | None = None
    engulfing_bear: float | None = None
    pin_bar_bull: float | None = None
    pin_bar_bear: float | None = None
    hammer_detected: float | None = None
    shooting_star_detected: float | None = None
    inside_bar: float | None = None
    outside_bar: float | None = None
    doji_detected: float | None = None
    # 10 new three-bar candlestick patterns (added 2026-03-08)
    three_white_soldiers: float | None = None
    three_black_crows: float | None = None
    morning_star: float | None = None
    evening_star: float | None = None
    three_inside_up: float | None = None
    three_inside_down: float | None = None
    harami_cross: float | None = None
    dark_cloud_cover: float | None = None
    piercing_line: float | None = None

    # FlagPennantPlugin outputs
    flag_pattern: float | None = None
    pennant_pattern: float | None = None
    flag_breakout_target: float | None = None
    consolidation_compression_ratio: float | None = None

    # CupHandlePlugin outputs
    cup_handle_pattern: float | None = None
    cup_depth_pct: float | None = None
    cup_handle_target: float | None = None

    # MeasuredMovePlugin outputs
    abcd_pattern_active: float | None = None
    abcd_direction: float | None = None
    abcd_d_target: float | None = None
    abcd_completion_pct: float | None = None

    # VolumeProfilePlugin outputs
    nearest_hvn_level: float | None = None
    nearest_hvn_dist_atr: float | None = None
    nearest_lvn_level: float | None = None
    in_lvn: float | None = None

    # KeyLevelReactionPlugin outputs
    key_level_reaction_type: float | None = None
    key_level_confluence_count: float | None = None


class SMCContext(BaseModel):
    """Smart Money Concepts outputs.

    Plugins:
    - smc_BOSCHoCH (6 fields)
    - smc_FairValueGap (6 fields)
    - smc_OrderBlocks (6 fields)
    - smc_LiquiditySweeps (5 fields)
    - smc_BOCPDChangePoint (5 fields)
    - smc_HMMRegime (6 fields)
    - smc_LiquidityPools (13 fields)
    - smc_SupplyDemandZones (14 fields)
    - smc_ICTKillzones (7 fields)
    - smc_AMDCycle (3 fields)
    - smc_BreakerBlocks (5 fields)
    - smc_MitigationBlocks (2 fields)
    - smc_PremiumDiscount (2 fields)
    Total: 80 fields

    NOTE: SMC has smc_trend_direction (not trend_direction) to avoid collision
    with I3Structure.trend_direction. Both I3 TrendStructure and SMC BOSCHoCH
    output a field called 'trend_direction'. We rename SMC's to smc_trend_direction.
    """

    model_config = ConfigDict(extra="forbid")

    # BOSCHoCHPlugin outputs
    bos_detected: float | None = None  # 0.0/1.0 flag (plugin returns float, not bool)
    bos_direction: int | None = None  # -1/0/1
    bos_level: float | None = None
    choch_detected: float | None = None  # 0.0/1.0 flag
    choch_direction: int | None = None  # -1/0/1
    smc_trend_direction: int | None = None  # renamed from trend_direction to avoid I3 collision

    # FairValueGapPlugin outputs
    fvg_type: int | None = None  # -1/0/1
    fvg_top: float | None = None
    fvg_bottom: float | None = None
    fvg_midpoint: float | None = None
    fvg_size_pct: float | None = None
    fvg_open_count: int | None = None

    # OrderBlocksPlugin outputs
    ob_type: int | None = None  # -1/0/1
    ob_top: float | None = None
    ob_bottom: float | None = None
    ob_strength: float | None = None
    ob_mitigated: float | None = None  # 0.0/1.0 flag
    ob_distance_pct: float | None = None

    # LiquiditySweepsPlugin outputs
    sweep_detected: float | None = None  # 0.0/1.0 flag
    sweep_type: int | None = None  # -1/0/1
    sweep_level: float | None = None
    sweep_depth_pct: float | None = None
    sweep_reclaimed: float | None = None  # 0.0/1.0 flag

    # BOCPDChangePointPlugin outputs
    cp_probability: float | None = None
    cp_raw_probability: float | None = None
    cp_run_length: float | None = None
    cp_confirmation: float | None = None
    cp_detected: float | None = None  # 0.0/1.0 detection flag

    # HMMRegimePlugin outputs
    hmm_regime: float | None = None  # 0=ranging, 1=trending-up, 2=trending-down
    hmm_regime_prob: float | None = None
    hmm_prob_ranging: float | None = None
    hmm_prob_trending_up: float | None = None
    hmm_prob_trending_down: float | None = None
    hmm_regime_duration: float | None = None

    # LiquidityPoolsPlugin outputs
    bsl_level: float | None = None
    bsl_type: float | None = None  # significance score (float encoding)
    bsl_significance: float | None = None
    bsl_dist_atr: float | None = None
    bsl_touches: float | None = None
    ssl_level: float | None = None
    ssl_type: float | None = None
    ssl_significance: float | None = None
    ssl_dist_atr: float | None = None
    ssl_touches: float | None = None
    price_in_premium: float | None = None  # 0.0/1.0 flag
    premium_position: float | None = None  # -1.0 to 1.0
    pool_count: float | None = None

    # SupplyDemandZonesPlugin outputs
    nearest_demand_high: float | None = None
    nearest_demand_low: float | None = None
    demand_freshness: float | None = None
    demand_strength: float | None = None
    demand_dist_atr: float | None = None
    in_demand_zone: float | None = None  # 0.0/1.0 flag
    nearest_supply_high: float | None = None
    nearest_supply_low: float | None = None
    supply_freshness: float | None = None
    supply_strength: float | None = None
    supply_dist_atr: float | None = None
    in_supply_zone: float | None = None  # 0.0/1.0 flag
    active_demand_zones: float | None = None
    active_supply_zones: float | None = None

    # ICTKillzonesPlugin outputs
    in_asia_killzone: float | None = None
    in_london_killzone: float | None = None
    in_ny_am_killzone: float | None = None
    in_ny_pm_killzone: float | None = None
    killzone_name: str | None = None
    minutes_in_killzone: float | None = None
    minutes_until_next_killzone: float | None = None

    # AMDCyclePlugin outputs
    amd_phase: str | None = None  # "accumulation"/"manipulation"/"distribution"/"unknown"
    amd_manipulation_detected: float | None = None
    amd_distribution_direction: float | None = None  # -1/0/1

    # BreakerBlocksPlugin outputs
    breaker_block_active: float | None = None
    breaker_block_type: float | None = None  # -1 (bearish breaker) / +1 (bullish breaker)
    breaker_block_top: float | None = None
    breaker_block_bottom: float | None = None
    breaker_dist_atr: float | None = None

    # MitigationBlocksPlugin outputs
    ob_mitigation_status: str | None = None  # "fresh"/"partial"/"void"
    ob_mitigation_pct: float | None = None

    # PremiumDiscountPlugin outputs
    equilibrium_level: float | None = None
    premium_discount_pct: float | None = None  # -1.0 to +1.0


class I6Confluence(BaseModel):
    """I6 cross-timeframe confluence outputs.

    Plugins:
    - CrossTimeframeConfluence (10 fields)
    """

    model_config = ConfigDict(extra="forbid")

    # CrossTimeframeConfluencePlugin outputs
    ctf_score: float | None = None
    ctf_trend_alignment: float | None = None
    ctf_structure_alignment: float | None = None
    ctf_regime_agreement: float | None = None
    ctf_timeframes_aligned: float | None = None
    ctf_highest_aligned_tf: float | None = None

    # SMC cross-TF alignment sub-scores
    i6_smc_bos_alignment: float | None = None
    i6_fvg_tf_alignment: float | None = None
    i6_ob_tf_alignment: float | None = None

    # I2 event signal score
    i6_i2_event_score: float | None = None


class IntelligenceEvent(BaseModel):
    """Canonical typed intelligence event published to intelligence:SYMBOL:TF Redis stream.

    Publishers construct this model from plugin outputs and call model_dump_json()
    to produce the stream payload. Consumers call model_validate_json() to deserialize.

    Stream format: single field {"event": "<json_string>"}
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"] = "1.0"
    ts: datetime
    symbol: str
    tf: str
    platform: str = "futures"  # Multi-platform prep; always "futures" for now
    source: Literal["live", "backfill"] = "live"

    # Pipeline timing fields — enable lag measurement from bar close to signal.
    # bar_close_ts is always set (live + backfill); computed_at fields are live-only.
    bar_close_ts: datetime | None = None  # Actual close (differs from ts for 5m+)
    i1_computed_at: datetime | None = None  # When indicator_service finished I1
    computed_at: datetime | None = None  # When market_analysis_service built event

    bar: OHLCVBar
    i1: I1Indicators
    i2: I2Events = I2Events()
    i3: I3Structure
    i4: I4Context
    i5: I5Patterns
    smc: SMCContext
    i6: I6Confluence
