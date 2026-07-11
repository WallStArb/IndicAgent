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

import dataclasses
from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from src.core.schemas.bar_message import SessionType
from src.core.schemas.intelligence_journal import IntelligenceJournal, ProvenanceChain  # noqa: F401

# Single source of truth for intelligence_features JSONB column names.
# Migrations 125-127 renamed tier-code columns to functional names.
# All tools/scripts querying intelligence_features MUST use these, not bare tier keys.
TIER_DB_COLUMNS: dict[str, str] = {
    "i1": "technical_indicators",
    "i2": "composite_events",
    "i3": "regime_features",
    "i4": "confluence_scores",
    "i5": "pattern_detections",
    "i6": "cross_timeframe_context",
    "i7": "trading_signals",
    "smc": "smc",
}


async def validate_intelligence_features_columns(conn: Any) -> None:
    """Assert every TIER_DB_COLUMNS value exists as a real column in intelligence_features.

    Call at service startup or in integration test fixtures.
    Raises RuntimeError if any column is missing — silent wrong answers are worse than loud crashes.
    """
    expected = list(TIER_DB_COLUMNS.values())
    rows = await conn.fetch(
        "SELECT column_name FROM information_schema.columns"
        " WHERE table_name = 'intelligence_features' AND column_name = ANY($1)",
        expected,
    )
    existing = {row["column_name"] for row in rows}
    missing = sorted(set(expected) - existing)
    if missing:
        raise RuntimeError(
            f"intelligence_features missing expected columns: {missing}. " "Run pending migrations."
        )


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
    atr_20: float | None = None  # Standard Keltner Channels period
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

    Strict schema (extra="forbid"): 45 declared fields across 10 plugins.

    Plugins and field counts:
    - evt_RSIEvents (6): rsi_crossed_30_up, rsi_crossed_70_down, rsi_crossed_50_up,
      rsi_crossed_50_down, rsi_extreme_reversal, rsi_bars_in_extreme
    - evt_StochasticEvents (6): stoch_cross_bullish, stoch_cross_bearish,
      stoch_oversold_reversal, stoch_overbought_reversal, stoch_both_oversold, stoch_both_overbought
    - evt_ADXEvents (6): adx_trend_confirmed, adx_ranging_confirmed, di_cross_bullish,
      di_cross_bearish, di_cross_bars_ago, di_spread
    - evt_VolumeEvents (6): vol_spike, vol_drying, bb_upper_touch, bb_lower_touch,
      bb_walking_upper, bb_walking_lower
    - Bridge composites/DonchianPosition (1): donchian_position_20
    - Bridge composites/OBVMomentum (1): obv_slope_sign
    - cmp_MomentumAccel (9): rsi_accel, macd_accel, roc_accel, inflection_flag,
      rsi_curvature, macd_hist_slope, price_accel, hma_slope, hma_accel
    - cmp_DerivativeOscillator (4): deriv_osc, deriv_osc_signal,
      deriv_osc_cross_bullish, deriv_osc_cross_bearish
    - cmp_ExhaustionScore (3): exhaustion_score, exhaustion_side, exhaustion_bars
    - cmp_AccelerationRegime (3): accel_regime, accel_score, accel_agreement

    Note: evt_MACDEvents (8 fields) was removed — those fields belong to
    I3Structure.struct_MACDEvents which uses I3 support/resistance data.

    Total: 45 declared fields.
    """

    model_config = ConfigDict(extra="forbid")

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

    # cmp_MomentumAccel (9 fields)
    rsi_accel: float | None = None
    macd_accel: float | None = None
    roc_accel: float | None = None
    inflection_flag: float | None = None
    rsi_curvature: float | None = None
    macd_hist_slope: float | None = None
    price_accel: float | None = None
    hma_slope: float | None = None
    hma_accel: float | None = None

    # cmp_DerivativeOscillator (4 fields)
    deriv_osc: float | None = None
    deriv_osc_signal: float | None = None
    deriv_osc_cross_bullish: float | None = None
    deriv_osc_cross_bearish: float | None = None

    # cmp_ExhaustionScore (3 fields)
    exhaustion_score: float | None = None
    exhaustion_side: str | None = None
    exhaustion_bars: float | None = None

    # cmp_AccelerationRegime (3 fields)
    accel_regime: str | None = None
    accel_score: float | None = None
    accel_agreement: float | None = None


class I3Structure(BaseModel):
    """I3 market structure outputs — structural facts about price.

    Plugins:
    - struct_SwingDetector (9 fields)
    - struct_SupportResistance (9 fields)
    - struct_TrendStructure (6 fields)
    - struct_MarketProfile (11 fields)
    - struct_SessionLevels (16 fields)
    - struct_FibonacciZones (12 fields)
    - struct_SwingMomentum (6 fields)
    - struct_MACDEvents (8 fields, migrated from I2Events — uses I3 support data)
    Total: 77 fields
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
    # MarketProfile gradient companions
    va_position_pct: float | None = None  # position within VA as percentage [0, 1]
    va_distance_atr: float | None = None  # distance from VA boundary in ATR units

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
    swing_amplitude_intensity: float | None = None  # continuous expansion intensity [0, 1]
    swing_velocity_bars: float | None = None
    swing_velocity_trend: Literal["accelerating", "decelerating", "stable"] | None = None
    struct_energy: float | None = None
    struct_accel_bias: Literal[-1, 0, 1] | None = None

    # MACDEventsPlugin outputs (migrated from I2Events — uses I3 support/resistance data)
    macd_cross_bullish: float | None = None
    macd_cross_bearish: float | None = None
    macd_cross_bars_ago: float | None = None
    macd_hist_positive: float | None = None
    macd_hist_turning_up: float | None = None
    macd_negative_support_test: float | None = None
    macd_hist_accel: float | None = None
    macd_hist_contracting: float | None = None


class I4Context(BaseModel):
    """I4 context classification outputs — quantitative regime assessment.

    Plugins:
    - VolatilityRegime (5 fields)
    - TrendRegime (5 fields)
    - MomentumContext (4 fields)
    - GARCHVolatility (4 fields)
    - KalmanTrend (7 fields)
    - SessionContext (27 fields: 12 legacy + 6 exchange-active + 3 break + 2 overlap + 4 sub-session)
    - HurstExponent (3 fields)
    - ShannonEntropy (2 fields)
    - AnchoredVWAP (15 fields)
    - VolumeProfile (18 fields, migrated from I5Patterns in Phase 34-02)
    - VIXRegime (2 fields)
    - CrossAssetContext (2 fields)
    - MacroContext (5 fields: yield_curve_slope, yield_curve_regime, ftq_score, ftq_regime, corr_z)
    Total: 98 fields
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
    trend_regime_continuous: float | None = None
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

    # HurstExponentPlugin outputs
    hurst_exponent: float | None = None
    hurst_trend_quality: float | None = None
    hurst_mr_quality: float | None = None

    # ShannonEntropyPlugin outputs
    shannon_entropy: float | None = None
    entropy_quality: float | None = None

    # AnchoredVWAPPlugin outputs (migrated from I3Structure)
    session_vwap: float | None = None
    session_vwap_dist_pct: float | None = None
    swing_vwap: float | None = None
    weekly_vwap: float | None = None
    above_session_vwap: float | None = None
    above_swing_vwap: float | None = None
    above_weekly_vwap: float | None = None
    vwap_alignment_score: float | None = None
    # New I4 VWAP fields
    avwap_upper_band: float | None = None
    avwap_lower_band: float | None = None
    swing_vwap_upper_band: float | None = None
    swing_vwap_lower_band: float | None = None
    session_vwap_deviation_sigma: float | None = None
    swing_vwap_deviation_sigma: float | None = None
    session_vwap_deviation_velocity: float | None = None

    # VolumeProfilePlugin outputs (migrated from I5Patterns in Phase 34-02)
    nearest_hvn_level: float | None = None
    nearest_hvn_dist_atr: float | None = None
    nearest_lvn_level: float | None = None
    in_lvn: float | None = None
    # New I4 volume profile fields
    poc_price: float | None = None
    vah: float | None = None
    val: float | None = None
    nearest_hvn_above: float | None = None
    nearest_hvn_below: float | None = None
    nearest_lvn_above: float | None = None
    nearest_lvn_below: float | None = None
    poc_price_rolling: float | None = None
    vah_rolling: float | None = None
    val_rolling: float | None = None
    price_in_value_area: float | None = None
    va_width_atr: float | None = None
    distance_to_vah_atr: float | None = None
    distance_to_val_atr: float | None = None

    # VIXRegimePlugin + CrossAssetContextPlugin outputs (Phase 46.1)
    vix_level: float | None = None  # VIX close price; computed from 1h bars always
    vix_z: float | None = None  # VIX z-score, 20-bar rolling mean, 1h window
    eq_spread_z: float | None = None  # dominant EQ pair spread z-score; EQ_INDEX only
    eq_pairs_confirming: float | None = None  # 0.0-2.0 confirming pairs; EQ_INDEX only

    # ctx_SRConsensus outputs (Phase 116)
    sr_nearest_support: float | None = None
    sr_nearest_resistance: float | None = None
    sr_support_confluence_score: float | None = None
    sr_resistance_confluence_score: float | None = None
    sr_support_dist_atr: float | None = None
    sr_resistance_dist_atr: float | None = None

    # MacroContextPlugin outputs (Phase 121 Wave 2)
    yield_curve_slope: float | None = None
    yield_curve_regime: str | None = None
    ftq_score: float | None = None
    ftq_regime: str | None = None
    # Stock-bond correlation z-score (MacroContextPlugin)
    corr_z: float | None = None


class I5Patterns(BaseModel):
    """I5 pattern detection outputs.

    Plugins:
    - patt_RSIDivergence (3 fields)
    - patt_BollingerSqueeze (4 fields)
    - patt_Confluence (6 fields)
    - patt_VolumeDivergence (3 fields) + obv_div_* extension (3 fields)
    - patt_MACDDivergence (3 fields)
    - patt_CMFDivergence (3 fields)
    - patt_DoubleTB (4 fields)
    - patt_HeadShoulders (5 fields)
    - TrendConfluence (4 fields)
    - patt_TriangleWedge (6 fields)
    - patt_CandlestickPatterns (31 fields)
    - patt_FlagPennant (4 fields)
    - patt_CupHandle (3 fields)
    - patt_MeasuredMove (4 fields)
    - patt_KeyLevelReaction (2 fields)
    - patt_MTFVolatility (4 fields, migrated from I4Context)
    Total: 91 fields

    NOTE: VolumeProfile (18 fields) migrated to I4Context in Phase 34-02.

    NOTE: DivergenceStack I7 outputs (div_weighted_score, div_n_agreeing, per-input scores,
    age_bars, magnitudes) are NOT here -- they are I7-tier outputs that bypass the I5 schema check.
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

    # VolumeDivergencePlugin OBV extension outputs (computed from OBV cumulative series via linreg)
    obv_div_bullish: float | None = None
    obv_div_bearish: float | None = None
    obv_div_strength: float | None = None

    # MACDDivergencePlugin outputs (patt_MACDDivergence)
    macd_div_bullish: float | None = None
    macd_div_bearish: float | None = None
    macd_div_strength: float | None = None

    # CMFDivergencePlugin outputs (patt_CMFDivergence)
    cmf_div_bullish: float | None = None
    cmf_div_bearish: float | None = None
    cmf_div_strength: float | None = None

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

    # CandlestickPatternsPlugin outputs (29 total fields)
    engulfing_bull: float | None = None
    engulfing_bear: float | None = None
    pin_bar_bull: float | None = None
    pin_bar_bear: float | None = None
    hammer_detected: float | None = None
    shooting_star_detected: float | None = None
    inside_bar: float | None = None
    outside_bar: float | None = None
    doji_detected: float | None = None
    # CandlestickPatterns gradient companions
    inside_bar_depth: float | None = None  # how contained: min margin / bar_range, [0, 1]
    outside_bar_expansion: float | None = None  # expansion ratio vs prev range, [0, inf)
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
    # 10 new candlestick patterns (Phase 42)
    harami_bull: float | None = None
    harami_bear: float | None = None
    abandoned_baby_bull: float | None = None
    abandoned_baby_bear: float | None = None
    tweezer_top: float | None = None
    tweezer_bottom: float | None = None
    belt_hold_bull: float | None = None
    belt_hold_bear: float | None = None
    kicker_bull: float | None = None
    kicker_bear: float | None = None

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

    # KeyLevelReactionPlugin outputs
    key_level_reaction_type: float | None = None
    key_level_confluence_count: float | None = None

    # MTFVolatilityPlugin outputs (migrated from I4Context — reads squeeze_active from I5)
    mtf_vol_expansion_15m: float | None = None
    mtf_vol_expansion_1h: float | None = None
    squeeze_within_expansion: float | None = None
    vol_divergence_score: float | None = None


class SMCContext(BaseModel):
    """Smart Money Concepts outputs.

    Plugins:
    - smc_BOSCHoCH (8 fields)
    - smc_FairValueGap (6 fields)
    - smc_OrderBlocks (6 fields)
    - smc_LiquiditySweeps (7 fields)
    - smc_BOCPDChangePoint (5 fields)
    - smc_HMMRegime (6 fields)
    - smc_LiquidityPools (13 fields)
    - smc_SupplyDemandZones (14 fields)
    - smc_ICTKillzones (11 fields)
    - smc_AMDCycle (4 fields)
    - smc_BreakerBlocks (5 fields)
    - smc_MitigationBlocks (2 fields)
    - smc_PremiumDiscount (2 fields)
    Total: 89 fields

    NOTE: SMC has smc_trend_direction (not trend_direction) to avoid collision
    with I3Structure.trend_direction. Both I3 TrendStructure and SMC BOSCHoCH
    output a field called 'trend_direction'. We rename SMC's to smc_trend_direction.
    """

    model_config = ConfigDict(extra="forbid")

    # BOSCHoCHPlugin outputs
    bos_detected: float | None = None  # 0.0/1.0 flag (plugin returns float, not bool)
    bos_direction: int | None = None  # -1/0/1
    bos_level: float | None = None
    bos_confidence: float | None = None  # structural quality score alias from BOSCHoCH
    choch_detected: float | None = None  # 0.0/1.0 flag
    choch_direction: int | None = None  # -1/0/1
    smc_trend_direction: int | None = None  # renamed from trend_direction to avoid I3 collision
    # BOSCHoCH gradient companions
    bos_strength: float | None = None  # break distance / ATR, continuous [0, inf)
    choch_strength: float | None = None  # break magnitude / ATR, continuous [0, inf)

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
    # LiquiditySweeps gradient companions
    sweep_strength: float | None = None  # depth normalized [0, 1]
    reclaim_velocity: float | None = None  # 1/bars_to_reclaim normalized [0, 1]

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
    hmm_n_dims: int | None = None  # 2 or 5 — emission dimensionality this bar
    hmm_warmed_up: bool | None = None  # False during convergence window post-reset
    hmm_regime_entropy: float | None = None  # Shannon entropy across 3 state probs
    hmm_regime_velocity: float | None = None  # Rate of change of dominant state prob
    hmm_probability: float | None = None  # P(trending) = P(up) + P(down)

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
    # ICTKillzones gradient companions
    kz_asia_progress: float | None = None  # progress fraction [0, 1]
    kz_london_progress: float | None = None
    kz_ny_am_progress: float | None = None
    kz_ny_pm_progress: float | None = None

    # AMDCyclePlugin outputs
    amd_phase: str | None = None  # "accumulation"/"manipulation"/"distribution"/"unknown"
    amd_manipulation_detected: float | None = None
    amd_distribution_direction: float | None = None  # -1/0/1
    # AMDCycle gradient companion
    manip_strength: float | None = None  # spike z-score or impulse magnitude, [0, inf)

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

    # Derived zone friction metric — computed by smc_SupplyDemandZones plugin (Phase 126-06).
    # Tier decision: SMC, because all inputs (demand/supply freshness, strength, dist_atr)
    # are produced by smc_SupplyDemandZones and live in this same sub-model.
    # Formula: freshness * strength * (1 / (1 + dist_atr)) for the nearest active zone.
    # None = cold-start (no zones detected), 0.0 = genuine zero (zero freshness or strength).
    zone_friction_score: float | None = None


class I6Confluence(BaseModel):
    """I6 cross-timeframe confluence outputs.

    Plugins:
    - CrossTimeframeConfluence (16 fields)
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

    # ctf_* aliases for i6_fvg/ob_tf_alignment — consistent naming for I7 plugin consumers.
    # i6_* fields preserved for backward compatibility.
    ctf_fvg_alignment: float | None = None
    ctf_ob_alignment: float | None = None

    # I2 event signal score
    i6_i2_event_score: float | None = None

    # Per-timeframe FVG/OB alignment scores — Renaissance standard (Phase 46)
    # Each TF score is a separate ML training feature (not dict) to satisfy:
    # "Every score must be decomposable" — ML layer needs per-TF coefficients
    # Written by CrossTimeframeConfluencePlugin when multiple TFs contribute
    # DESIGN NOTE: Using flat fields not dict[str,float] because:
    # 1. ML feature matrix expects columns, not nested structures
    # 2. Per-TF feature importance analysis requires separable fields
    # 3. SQL queries can filter/index specific TF scores efficiently
    i6_fvg_tf_1m: float | None = None
    i6_fvg_tf_5m: float | None = None
    i6_fvg_tf_15m: float | None = None
    i6_fvg_tf_1h: float | None = None
    i6_fvg_tf_4h: float | None = None
    i6_fvg_tf_1d: float | None = None
    i6_ob_tf_1m: float | None = None
    i6_ob_tf_5m: float | None = None
    i6_ob_tf_15m: float | None = None
    i6_ob_tf_1h: float | None = None
    i6_ob_tf_4h: float | None = None
    i6_ob_tf_1d: float | None = None

    # Cross-TF momentum divergence (Plan 64-01, D-06)
    # CrossTFMomentumDivergencePlugin outputs
    ctf_momentum_divergence: float | None = None  # [-1, +1] HTF-LTF momentum divergence
    # Regime: aligned_htf_bull/aligned_htf_bear/pullback/bounce/mixed
    ctf_momentum_regime: str | None = None

    # Plan 64-02: 4 additional cross-TF plugins (D-01)

    # CrossTFSRConfluence: HTF/LTF S/R level alignment via pivot proximity decay
    ctf_sr_confluence: float | None = None  # [-1, +1] HTF-LTF S/R alignment
    # Regime: aligned_both_resistance/aligned_both_support/aligned_htf_only/aligned_ltf_only/no_confluence
    ctf_sr_regime: str | None = None

    # CrossTFRegimeAgreement: HMM regime agreement across TFs
    # NOTE: named ctf_hmm_regime_* to avoid conflict with ctf_regime_agreement
    # (CrossTimeframeConfluencePlugin) which scores regime consensus differently
    ctf_hmm_regime_agreement: float | None = (
        None  # [-1, +1] HMM regime agreement (+trending/-ranging)
    )
    # Label: all_trending/all_ranging/mostly_trending/mostly_ranging/mixed
    ctf_hmm_regime_label: str | None = None

    # SqueezeExpansionDivergence: ATR + entropy volatility divergence HTF-LTF
    ctf_volatility_divergence: float | None = None  # [-1, +1] HTF-LTF volatility divergence
    # Regime: both_squeezing/both_expanding/squeeze_htf_expand_ltf/squeeze_ltf_expand_htf/mixed
    ctf_volatility_regime: str | None = None

    # CrossTFOrderFlowAlignment: OFI/CVD buying/selling pressure alignment
    ctf_orderflow_alignment: float | None = None  # [-1, +1] OFI/CVD alignment
    # Regime: aligned_bull/aligned_bear/mostly_bull/mostly_bear/divergent/missing_data
    ctf_orderflow_regime: str | None = None


FEATURE_SCHEMA_VERSION: int = 2
"""Version integer stamped on every freshly-produced row in intelligence_features
and signal_ledger.  Pre-fix rows remain NULL.  Downstream training queries filter
with WHERE feature_schema_version >= 2 to exclude contaminated data."""

# Phase-130 CTF scalar columns promoted to dedicated intelligence_features columns.
# Exclude from cross_timeframe_context JSONB; must exist in DB before feature_writer starts.
CTF_DEDICATED_COLUMNS: frozenset[str] = frozenset(
    {"ctf_score", "ctf_trend_alignment", "ctf_structure_alignment", "ctf_regime_agreement"}
)


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

    # Feature pipeline enrichment fields (D-22, Phase 44.1)
    # session_type: trading session at bar close, carried from BarMessage ingestion
    # pipeline_latency_ms: wall-clock ms from bar_close_ts to IntelligenceEvent publish
    session_type: SessionType = SessionType.RTH
    pipeline_latency_ms: float = 0.0

    # bar_id: unique UUID tracing back to the BarMessage that generated this event.
    # None during transition period (backward compat for pre-68-03 events).
    # Phase 68-03 — end-to-end bar traceability.
    bar_id: UUID | None = None

    # Contamination boundary marker (Phase 112).  Every freshly-produced event
    # carries FEATURE_SCHEMA_VERSION = 2 via the field default.
    # feature_writer persists this into intelligence_features.feature_schema_version;
    # signal_ledger_repository persists it into signal_ledger.feature_schema_version.
    # Downstream training queries filter WHERE feature_schema_version >= 2 to exclude
    # pre-fix contaminated rows (which remain NULL in the DB, written before this deploy).
    feature_schema_version: int = FEATURE_SCHEMA_VERSION


class RankedSignal(BaseModel):
    """A single I7 signal after all 6 pipeline stages have been applied.

    Produced by the in-process pipeline in SignalGeneratorService.
    Consumed by BarIntelligenceRecord and the signal ledger writer.
    """

    model_config = ConfigDict(extra="allow")

    signal_id: str
    plugin: str
    direction: int
    raw_confidence: float
    calibrated_confidence: float
    regime_eligible: bool
    quality_score: float
    tod_multiplier: float
    adjusted_rank: float
    is_winner: bool = False


# Fields consumed by explicit kwargs in signal_dict_to_ranked — excluded from **extras.
_RANKED_CONSUMED_KEYS: frozenset[str] = frozenset(
    {
        "signal_id",
        "setup_plugin",
        "direction",
        "pre_quality_confidence",
        "confidence",
        "calibrated_confidence",
        "regime_eligible",
        "quality_score",
        "tod_multiplier",
        "adjusted_rank",
        "was_selected",
    }
)


def signal_dict_to_ranked(sig: dict) -> RankedSignal:
    """Map a raw pipeline signal dict to RankedSignal, translating field names.

    Key renames: setup_plugin→plugin, pre_quality_confidence→raw_confidence,
    was_selected→is_winner. calibrated_confidence falls back to confidence when absent.
    All other keys pass through via extra="allow".
    """
    _cc = sig.get("calibrated_confidence")
    _raw_sid = sig.get("signal_id")
    if not _raw_sid:
        raise ValueError(
            f"signal_dict_to_ranked: signal missing signal_id field — "
            f"setup_plugin={sig.get('setup_plugin')!r} direction={sig.get('direction')!r}"
        )
    return RankedSignal(
        signal_id=str(_raw_sid),
        plugin=sig.get("setup_plugin", "unknown"),
        direction=int(sig.get("direction", 0)),
        raw_confidence=float(sig.get("pre_quality_confidence", sig.get("confidence", 0.0))),
        calibrated_confidence=float(_cc if _cc is not None else sig.get("confidence", 0.0)),
        regime_eligible=bool(sig.get("regime_eligible", True)),
        quality_score=float(sig.get("quality_score", 1.0)),
        tod_multiplier=float(sig.get("tod_multiplier", 1.0)),
        adjusted_rank=float(sig.get("adjusted_rank", 0.0)),
        is_winner=bool(sig.get("was_selected", False)),
        **{k: v for k, v in sig.items() if k not in _RANKED_CONSUMED_KEYS},
    )


class BarIntelligenceRecord(BaseModel):
    """Atomic record of a single bar's full intelligence pipeline output.

    Contains the IntelligenceEvent plus all ranked signals, funnel counts,
    and pipeline metadata. Published to topic_intelligence_record() after
    winner selection. Single atomic persistence source for PIPE-06.
    """

    model_config = ConfigDict(extra="allow")

    schema_version: str = "1.0"
    intelligence: IntelligenceEvent
    ranked_signals: list[RankedSignal]
    winner_plugin: str | None = None
    winner_confidence: float | None = None
    winner_direction: int | None = None
    signals_evaluated: int
    signals_after_quality: int
    signals_after_regime: int
    signals_after_tod: int
    signals_after_calibration: int
    ledger_written: bool
    session_type: str = "rth"
    days_to_expiry: int | None = None
    i7_computed_at: datetime
    pipeline_latency_ms: float


class MacroSignals(BaseModel):
    """Macro factor signals from MacroAnalyzer.

    Published to topic_macro_signals.
    Consumed by IntelligencePipeline (frames["cross_asset"]).
    Written to macro_features hypertable by DataWriterAgent.
    """

    model_config = ConfigDict(frozen=True)

    ts: datetime
    symbol: str
    timeframe: str

    # Yield curve slope factor (Plan 64-03A)
    yield_curve_slope: float | None = None
    yield_curve_regime: str | None = None

    # Flight-to-quality factor (Plan 64-03B)
    # ftq_score: float | None = None
    # ftq_regime: str | None = None

    # USD strength factor (Plan 64-03C)
    # usd_strength_score: float | None = None
    # usd_strength_regime: str | None = None


@dataclasses.dataclass
class ShadowTransitionEvent:
    """Published to topic_shadow_transitions on any promotion or demotion.

    Fields match shadow_transition_log columns for easy DB audit correlation.
    triggered_at is UTC ISO-8601 string with Z suffix (e.g., '2026-04-28T12:00:00.000Z').
    """

    component_name: str
    component_type: str  # 'i7_plugin' | 'swarm_agent'
    from_state: str  # 'shadow' | 'live'
    to_state: str  # 'shadow' | 'live'
    trigger_reason: str  # 'promotion_gate_cleared' | 'demotion_ev_r_degraded'
    n: int
    ev_r: float
    ci_lower: float
    win_rate: float
    triggered_at: str  # UTC ISO-8601 with Z suffix


class MetricsComputedEvent(BaseModel):
    """Kafka payload for event_type='metrics_computed' on topic_signal_metrics.

    Field list derived from SignalMetricsWriter._handle_metrics_computed() signature.
    """

    model_config = ConfigDict(extra="forbid")

    event_type: Literal["metrics_computed"]
    track: str
    setup_plugin: str
    tf: str
    regime_type: str
    window_days: int
    symbol: str = "*"
    entry_type: str = "*"
    n: int
    n_outliers: int
    never_activated_pct: float | None = None
    win_rate: float | None = None
    avg_r: float | None = None
    std_r: float | None = None
    sharpe: float | None = None
    p_value: float | None = None
    avg_mae: float | None = None
    avg_mfe: float | None = None
    skewness: float | None = None
    kurtosis: float | None = None
    min_r: float | None = None
    p5_r: float | None = None
    recovery_factor: float | None = None
    cvar_5: float | None = None
    computed_at: str


class ICComputedEvent(BaseModel):
    """Kafka payload for event_type='ic_computed' on topic_signal_metrics.

    Field list derived from SignalMetricsWriter._handle_ic_computed() signature.
    """

    model_config = ConfigDict(extra="forbid")

    event_type: Literal["ic_computed"]
    setup_plugin: str
    tf: str
    regime_type: str
    window_days: int
    symbol: str = "*"
    n: int
    ic: float | None = None
    p_value: float | None = None
    is_significant: bool = False
    computed_at: str


class MetricsDQFailureEvent(BaseModel):
    """Kafka payload for event_type='metrics_dq_failure' on topic_signal_metrics.

    Field list derived from SignalMetricsWriter._handle_dq_failure() signature.
    """

    model_config = ConfigDict(extra="forbid")

    event_type: Literal["metrics_dq_failure"]
    signal_id: str
    reason_code: str
    entry_price: float | None = None
    stop_loss: float | None = None
    pnl_r: float | None = None
    direction: int | None = None
    hmm_regime: int | None = None
    setup_plugin: str | None = None


SignalMetricsEvent = Annotated[
    MetricsComputedEvent | ICComputedEvent | MetricsDQFailureEvent,
    Field(discriminator="event_type"),
]


# ---------------------------------------------------------------------------
# v3.0 AlphaEngine: Feature Vector contracts (Phase 137)
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class FeatureVector:
    """142 orthogonal feature primitives computed per bar by FeatureFactory
    (61 v3.0 baseline + 18 Phase 142.5 Plan 01 + 22 Phase 142.5 Plan 02 +
    12 Phase 142.5 Plan 05 + 21 Phase 142.5 Plan 03 + 8 Phase 142.5 Plan 04
    Renaissance primitives).

    Frozen dataclass (not Pydantic) per D-08: pure-function output, no IO,
    immutable after construction. Non-optional fields typed float, no defaults
    — every field must be supplied by the caller. Optional fields are
    cross-sectional ranks populated by Phase 139 enrichment pass.

    Groups and field order are binding (schema column names in feature_vectors):
      Momentum (7): fast/mid/slow return z-scores, range, intra-bar close position, gap, reversal z
      Volume/flow (8): informed flow, volume, OFI, OFI divergence, CVD slope, CMF, rel volume, VWAP dev
      Volatility (2): ATR z-score, short/long vol ratio
      Session-level (4): volume profile POC/VA, S/R proximity
      Regime-level (10): HMM prob/entropy/duration, Hurst, Shannon, GARCH ratio, HMA slope, ADX, Aroon fast/slow
      Oscillators (6): RSI and CCI at fast/mid/slow scales
      Cross-asset (3): VIX z-score, flight-to-quality, yield slope
      Calendar (11): NY/London session, overlap, power hour, opening range, weekly VWAP, dow sin/cos, month position, quarter position, days to month end
      Cross-timeframe (3): momentum/VWAP/regime alignment from HTF cache
      Statistical/liquidity (4): Amihud illiquidity, 52w high distance, return skewness, return autocorrelation
      Bar Anatomy Ratios (8, Phase 142.5 Plan 01): body/wick ratios, range vs ATR, direction, overnight gap(+z), range efficiency
      Lagged Return Series (6, Phase 142.5 Plan 01): ret_lag_1/2/3 + fast/mid/slow gradient windows
      Open-to-Close Split (4, Phase 142.5 Plan 01): open_ret, intraday_ret, open_vs_intraday, session_time_pos
      Temporal Coordinates (10, Phase 142.5 Plan 02): hour_of_day/week_of_month/day_of_month/week_of_year sin+cos, month_sin/cos
      Volume Structure (12, Phase 142.5 Plan 02): vol_acceleration, dollar_vol_z, vol_range_ratio, vol_trend_ratio, up_vol_ratio_fast/slow, vol_percentile, vol_persistence, vol_std_z, mfi_fast/slow, obv_z
      Breakout Distance (12, Phase 142.5 Plan 05): dist_from_high/low_fast/slow, range_pct_fast/slow, stoch_k_fast/slow, price_percentile_fast/slow, efficiency_ratio_fast/slow
      Return Distribution (7, Phase 142.5 Plan 03): ret_kurtosis_z_fast/slow, ret_autocorr_1/5, updown_ratio_fast/slow, streak_z
      Realized Variance / Volatility (14, Phase 142.5 Plan 03): realized_var_ratio_fast/slow, range_to_close, true_range_pct, vol_of_vol, high_low_corr, variance_ratio_fast/slow, vol_asymmetry_z, bb_pct_b_fast/slow, hv_z_fast/slow, hv_ratio
      Alternative Volatility Estimators (3, Phase 142.5 Plan 04): parkinson_vol_z, garman_klass_vol_z, yang_zhang_vol_z
      Volatility Dynamics (5, Phase 142.5 Plan 04): parkinson/garman_klass/yang_zhang_vol_velocity, vol_velocity_z, intraday_noise_ratio
      Canary / Control Predictors (5, Phase 143.1 Plan 02, todo 068): canary_noise_gaussian, canary_noise_uniform, canary_constant, canary_near_constant, canary_acausal_placebo
      Cross-sectional (3, nullable): momentum/volume/volatility rank z-scores
      Total: 155 (147 required + 8 optional [3 cross-sectional + 5 canary, defaulted for
      cold-start/construction-site blast-radius reasons -- see Canary field comments])
    """

    # Momentum (7 total: 5 original + 2 new scale-named)
    momentum_z_fast: float  # fast-scale return z-score (APR: feature.momentum.window_fast)
    momentum_z_mid: float  # mid-scale return z-score (APR: feature.momentum.window_mid)
    range_position: float
    bar_close_pos: float
    gap_z: float
    momentum_z_slow: float  # slow-scale return z-score (APR: feature.momentum.window_slow)
    momentum_reversal_z: float  # 1-bar return z-score (concept-named: short-term reversal)
    # Volume and order flow (8)
    informed_flow: float
    volume_z: float
    ofi_z: float
    ofi_div: float
    cvd_slope_z: float
    cmf: float
    rel_volume: float
    vwap_dev_sigma: float
    # Volatility (2) - part of bar-level computation
    atr_z: float
    vol_ratio: float
    # Session-level (4, nullable in batch — requires I3 intraday injection unavailable in batch path)
    poc_dist_atr: float | None
    va_position: float | None
    sr_support_dist: float | None
    sr_resist_dist: float | None
    # Regime-level (11)
    hmm_regime_prob: float
    hmm_entropy: float
    hmm_duration: float
    hurst: float
    shannon: float
    garch_ratio: float
    hma_slope_z: float
    adx: float
    aroon_fast: float
    aroon_slow: float
    # Oscillators (6)
    rsi_fast: float
    rsi_mid: float
    rsi_slow: float
    cci_fast: float
    cci_mid: float
    cci_slow: float
    # Cross-asset (3)
    vix_z: float
    flight_quality: float
    yield_slope_z: float
    # Calendar (11: 9 original + 2 new)
    in_ny_session: float
    in_london_kz: float
    in_overlap: float
    power_hour: float
    opening_range: float
    above_wk_vwap: float
    dow_sin: float
    dow_cos: float
    month_position: float
    quarter_position: float  # position within calendar quarter [0, 1]; earnings/rebalancing cycle
    days_to_month_end: float  # (days remaining to month end) / (days in month) [0, 1]
    # Cross-timeframe (3)
    ctf_momentum: float
    ctf_vwap_align: float
    ctf_regime_align: float
    # Statistical / liquidity (4)
    amihud_illiq_z: float
    high_52w_dist: float
    ret_skew_z: float
    ret_acf1_z: float
    # Renaissance Primitives — Bar Anatomy Ratios (8, Phase 142.5 Plan 01)
    body_ratio: float  # (C - O) / (H - L), bounded [-1, 1]
    upper_wick_ratio: float  # (H - max(O,C)) / (H - L), bounded [0, 1]
    lower_wick_ratio: float  # (min(O,C) - L) / (H - L), bounded [0, 1]
    range_vs_atr: float  # (H - L) / ATR_N, unbounded positive
    close_vs_open_direction: float  # sign(C - O), categorical {-1, 0, 1}
    overnight_gap: float  # (O - prev_C) / prev_C, unbounded
    overnight_gap_z: float  # z-score of overnight_gap (APR: feature.overnight_gap.window)
    range_efficiency: float  # abs(C - prev_C) / (H - L), bounded [0, 1]
    # Renaissance Primitives — Lagged Return Series (6, Phase 142.5 Plan 01)
    ret_lag_1: float  # log(C_t / C_{t-1}), definitional
    ret_lag_2: float  # log(C_t / C_{t-2}), definitional
    ret_lag_3: float  # log(C_t / C_{t-3}), definitional
    ret_lag_fast: float  # log(C_t / C_{t-N}) (APR: feature.ret_lag.fast)
    ret_lag_mid: float  # log(C_t / C_{t-N}) (APR: feature.ret_lag.mid)
    ret_lag_slow: float  # log(C_t / C_{t-N}) (APR: feature.ret_lag.slow)
    # Renaissance Primitives — Open-to-Close Split (4, Phase 142.5 Plan 01)
    open_ret: float  # log(O_t / prev_C), overnight component
    intraday_ret: float  # log(C_t / O_t), intraday component
    open_vs_intraday: float  # open_ret - intraday_ret
    session_time_pos: float  # continuous [0, 1] position within the NY session
    # Renaissance Primitives — Temporal Coordinates (10, Phase 142.5 Plan 02)
    hour_of_day_sin: float  # sin(2*pi*(hour+minute/60)/24), bounded [-1, 1]
    hour_of_day_cos: float  # cos(2*pi*(hour+minute/60)/24), bounded [-1, 1]
    week_of_month_sin: float  # sin(2*pi*week/5), week=(day-1)//7+1, bounded [-1, 1]
    week_of_month_cos: float  # cos(2*pi*week/5), week=(day-1)//7+1, bounded [-1, 1]
    day_of_month_sin: float  # sin(2*pi*day/31), bounded [-1, 1]
    day_of_month_cos: float  # cos(2*pi*day/31), bounded [-1, 1]
    week_of_year_sin: float  # sin(2*pi*isocalendar_week/52), bounded [-1, 1]
    week_of_year_cos: float  # cos(2*pi*isocalendar_week/52), bounded [-1, 1]
    month_sin: (
        float  # sin(2*pi*month/12), bounded [-1, 1] (NEW pair; only month_position existed before)
    )
    month_cos: (
        float  # cos(2*pi*month/12), bounded [-1, 1] (NEW pair; only month_position existed before)
    )
    # Renaissance Primitives — Volume Structure (12, Phase 142.5 Plan 02)
    vol_acceleration: float  # V_t / V_{t-1}, unbounded positive (APR: none, bar-relative)
    dollar_vol_z: float  # z-score of (V*C) (APR: feature.dollar_vol.window)
    vol_range_ratio: float  # V_t/(H-L) normalized over N (APR: feature.vol_range_ratio.window)
    vol_trend_ratio: float  # vol_MA_fast/vol_MA_slow (APR: feature.vol_trend.fast/.slow)
    up_vol_ratio_fast: float  # sum(V|C>O)/sum(V), bounded [0,1] (APR: feature.up_vol_ratio.fast)
    up_vol_ratio_slow: float  # sum(V|C>O)/sum(V), bounded [0,1] (APR: feature.up_vol_ratio.slow)
    vol_percentile: (
        float  # rolling percentile rank of V_t, bounded [0,1] (APR: feature.vol_percentile.window)
    )
    vol_persistence: (
        float  # lag-1 autocorrelation of V, bounded [-1,1] (APR: feature.vol_persistence.window)
    )
    vol_std_z: float  # z-score of rolling std(V) (APR: feature.vol_std.window)
    mfi_fast: float  # Money Flow Index, bounded [0,100] (APR: feature.mfi.fast)
    mfi_slow: float  # Money Flow Index, bounded [0,100] (APR: feature.mfi.slow)
    obv_z: float  # z-score of OBV (APR: feature.obv.window)
    # Renaissance Primitives — Breakout Distance (14, Phase 142.5 Plan 05)
    dist_from_high_fast: (
        float  # (rolling_high-C)/ATR, unbounded non-neg (APR: feature.breakout.dist_window_fast)
    )
    dist_from_high_slow: (
        float  # (rolling_high-C)/ATR, unbounded non-neg (APR: feature.breakout.dist_window_slow)
    )
    dist_from_low_fast: (
        float  # (C-rolling_low)/ATR, unbounded non-neg (APR: feature.breakout.dist_window_fast)
    )
    dist_from_low_slow: (
        float  # (C-rolling_low)/ATR, unbounded non-neg (APR: feature.breakout.dist_window_slow)
    )
    range_pct_fast: float  # (rolling_high-rolling_low)/C, unbounded non-neg (APR: feature.breakout.range_window_fast)
    range_pct_slow: float  # (rolling_high-rolling_low)/C, unbounded non-neg (APR: feature.breakout.range_window_slow)
    stoch_k_fast: (
        float  # (C-L_N)/(H_N-L_N), bounded [0,1] (APR: feature.breakout.stoch_window_fast)
    )
    stoch_k_slow: (
        float  # (C-L_N)/(H_N-L_N), bounded [0,1] (APR: feature.breakout.stoch_window_slow)
    )
    price_percentile_fast: float  # rolling percentile rank of C, bounded [0,1] (APR: feature.breakout.percentile_window_fast)
    price_percentile_slow: float  # rolling percentile rank of C, bounded [0,1] (APR: feature.breakout.percentile_window_slow)
    efficiency_ratio_fast: float  # Kaufman ER, bounded [0,1] (0=chop,1=trend) (APR: feature.breakout.efficiency_window_fast)
    efficiency_ratio_slow: float  # Kaufman ER, bounded [0,1] (0=chop,1=trend) (APR: feature.breakout.efficiency_window_slow)
    # Renaissance Primitives — Return Distribution (7, Phase 142.5 Plan 03)
    ret_kurtosis_z_fast: (
        float  # z-score of rolling excess kurtosis (APR: feature.ret_kurtosis.fast)
    )
    ret_kurtosis_z_slow: (
        float  # z-score of rolling excess kurtosis (APR: feature.ret_kurtosis.slow)
    )
    ret_autocorr_1: (
        float  # lag-1 Pearson autocorrelation of log returns, bounded [-1,1] (definitional, no APR)
    )
    ret_autocorr_5: (
        float  # lag-5 Pearson autocorrelation of log returns, bounded [-1,1] (definitional, no APR)
    )
    updown_ratio_fast: (
        float  # count(up)/count(down) returns, unbounded non-neg (APR: feature.updown_ratio.fast)
    )
    updown_ratio_slow: (
        float  # count(up)/count(down) returns, unbounded non-neg (APR: feature.updown_ratio.slow)
    )
    streak_z: float  # z-score of signed directional streak length (APR: feature.streak.window)
    # Renaissance Primitives — Realized Variance / Volatility (14, Phase 142.5 Plan 03)
    realized_var_ratio_fast: float  # var(ret,fast)/var(ret,slow), unbounded non-neg (APR: feature.realized_var.fast/slow)
    realized_var_ratio_slow: float  # var(ret,fast)/var(ret,slow), unbounded non-neg (APR: feature.realized_var.fast/slow)
    range_to_close: float  # (H-L)/C, unbounded non-neg (no APR)
    true_range_pct: float  # TR/C, unbounded non-neg (no APR)
    vol_of_vol: float  # z-score of rolling std(atr_z) (APR: feature.vol_of_vol.window)
    high_low_corr: (
        float  # correlation of H and L, bounded [-1,1] (APR: feature.high_low_corr.window)
    )
    variance_ratio_fast: float  # Lo-MacKinlay VR, unbounded non-neg, ~1.0 under random walk (APR: feature.variance_ratio.fast)
    variance_ratio_slow: float  # Lo-MacKinlay VR, unbounded non-neg, ~1.0 under random walk (APR: feature.variance_ratio.slow)
    vol_asymmetry_z: (
        float  # z-score of std(ret|up)/std(ret|down) (APR: feature.vol_asymmetry.window)
    )
    bb_pct_b_fast: float  # (C-lower_band)/(upper_band-lower_band) (APR: feature.bb_pct_b.fast)
    bb_pct_b_slow: float  # (C-lower_band)/(upper_band-lower_band) (APR: feature.bb_pct_b.slow)
    hv_z_fast: float  # z-score of close-to-close historical volatility (APR: feature.hv.fast)
    hv_z_slow: float  # z-score of close-to-close historical volatility (APR: feature.hv.slow)
    hv_ratio: (
        float  # hv_fast / rolling_mean(hv, N), unbounded non-neg (APR: feature.hv.ratio_window)
    )
    # Renaissance Primitives — Alternative Volatility Estimators (3, Phase 142.5 Plan 04)
    parkinson_vol_z: float  # z-score of rolling-avg ln(H/L)^2/(4ln2) (APR: feature.parkinson_vol.window/.zscore_window)
    garman_klass_vol_z: float  # z-score of rolling-avg GK term (APR: feature.garman_klass_vol.window/.zscore_window)
    yang_zhang_vol_z: float  # z-score of rolling YZ variance estimator (APR: feature.yang_zhang_vol.window/.zscore_window)
    # Renaissance Primitives — Volatility Dynamics (5, Phase 142.5 Plan 04)
    parkinson_vol_velocity: float  # parkinson_vol_z_t - parkinson_vol_z_{t-1}, unbounded (no APR)
    garman_klass_vol_velocity: (
        float  # garman_klass_vol_z_t - garman_klass_vol_z_{t-1}, unbounded (no APR)
    )
    yang_zhang_vol_velocity: (
        float  # yang_zhang_vol_z_t - yang_zhang_vol_z_{t-1}, unbounded (no APR)
    )
    vol_velocity_z: float  # z-score of rolling atr_z velocity (APR: feature.vol_velocity.window)
    intraday_noise_ratio: float  # sum(|ret|)/|net_ret| over session, unbounded non-neg (APR: feature.intraday_noise.window)
    # Renaissance Primitives — Price-Volume Interactions (8, Phase 142.5 Plan 05.5)
    vol_body_product: float  # body_ratio * volume_z, unbounded symmetric around 0 (no APR)
    ret_vol_product_fast: float  # ret_lag_fast * volume_z, unbounded symmetric around 0 (no APR)
    price_vol_corr_fast: float  # rolling Pearson(|log ret|, volume), bounded [-1,1] (APR: feature.price_vol_corr.fast)
    price_vol_corr_slow: float  # rolling Pearson(|log ret|, volume), bounded [-1,1] (APR: feature.price_vol_corr.slow)
    range_vol_product: float  # range_vs_atr * volume_z, unbounded symmetric around 0 (no APR)
    up_vol_body_diff: float  # up_vol_ratio_fast - body_ratio, approx bounded [-1,1] (no APR)
    ret_vol_ratio_fast: float  # ret_lag_fast / atr_z, unbounded symmetric around 0 (no APR)
    vol_skew_product: float  # ret_skew_z * volume_z, unbounded symmetric around 0 (no APR)
    # Canary / Control Predictors (5, Phase 143.1 Plan 02, todo 068) — genuine
    # FeatureVector fields (not measurement-time-only diagnostics), so
    # feature_registry's row-count/name-set alignment gates stay satisfied.
    # is_control=true rows, status='candidate' (never promoted) in feature_registry
    # -- second line of defense beyond is_control. Negative controls (noise,
    # constant, near-constant) must never clear an IC significance gate; the
    # acausal placebo positive control must clear one spectacularly, proving
    # this pipeline can detect look-ahead leakage. See ops_canary_integrity_assert.py.
    # Defaulted (unlike the rest of this dataclass) purely to avoid a blast
    # radius across every pre-existing hardcoded FeatureVector(...) test
    # constructor in the suite -- every real compute path (compute()/
    # compute_batch()/_cold_start_vector()) always supplies an explicit value.
    canary_noise_gaussian: float = (
        0.0  # seeded N(0,1) (APR: alpha.ic.canary_rng_seed), negative control
    )
    canary_noise_uniform: float = (
        0.0  # seeded Uniform[0,1), independent sub-seed of same APR key, negative control
    )
    canary_constant: float = (
        1.0  # fixed literal (no APR -- definitional degenerate-input control), negative control
    )
    canary_near_constant: float = (
        1.0  # literal + tiny deterministic epsilon noise, negative control
    )
    canary_acausal_placebo: float = (
        0.0  # existing feature deliberately paired against a forward-shifted return window (look-ahead leak), positive control
    )
    # Cross-sectional (3, nullable — populated by Phase 139 enrichment pass)
    momentum_rank_z: float | None = None  # cross-sectional momentum rank z-score
    volume_rank_z: float | None = None  # cross-sectional volume rank z-score
    volatility_rank_z: float | None = None  # cross-sectional volatility rank z-score


@dataclasses.dataclass(frozen=True)
class FeatureVectorRecord:
    """Wire envelope for Kafka transport: FeatureVector + persistence metadata.

    Published by IntelligencePipeline after FeatureFactory.compute().
    Consumed by feature_writer for persistence to feature_vectors hypertable.

    regime_label_source is always 'filtered' per D-07 (forward Viterbi only;
    backward smoother banned to prevent lookahead bias in IC measurement).
    """

    symbol: str
    tf: str
    bar_ts: datetime  # UTC bar open timestamp
    pipeline_version: str  # e.g. "3.0.0"
    feature_factory_version: str  # e.g. "1.0.0"; bump on any compute algorithm change
    regime: str | None  # HMM state label: "ranging", "trending_up", "trending_down"
    regime_label_source: str  # always "filtered" (D-07)
    vector: FeatureVector
