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
  SMCContext    — Smart Money Concepts: BOS/CHoCH, FVG, OB, sweeps, BOCPD, HMM, pools, zones (extra='forbid')
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
    macd_hist_12_26_9: float | None = None
    # BollingerBandsPlugin
    bb_20_2_upper: float | None = None
    bb_20_2_lower: float | None = None
    bb_20_2_middle: float | None = None
    # VolumeRatioPlugin
    volume_ratio: float | None = None
    # ROCPlugin
    roc_14: float | None = None
    # StochasticPlugin
    stoch_k: float | None = None
    stoch_d: float | None = None
    # ADXPlugin
    adx_14: float | None = None
    plus_di_14: float | None = None
    minus_di_14: float | None = None
    # CCIPlugin
    cci_14: float | None = None
    # WilliamsRPlugin
    williams_r: float | None = None
    # MFIPlugin
    mfi_14: float | None = None
    # OBVPlugin
    obv: float | None = None
    # SupertrendPlugin
    supertrend_dir: float | None = None
    # SMAPlugin (common cross-detection fields)
    sma_20_gt_50: float | None = None


class I3Structure(BaseModel):
    """I3 market structure outputs — structural facts about price.

    Plugins:
    - struct_SwingDetector (9 fields)
    - struct_SupportResistance (9 fields)
    - struct_TrendStructure (6 fields)
    Total: 24 fields
    """

    model_config = ConfigDict(extra="forbid")

    # SwingDetectorPlugin outputs
    swing_high: float | None = None
    swing_low: float | None = None
    swing_high_idx: float | None = None
    swing_low_idx: float | None = None
    swing_pattern: str | None = None          # "HH->HL" etc — string, not float
    swing_high_type: str | None = None        # "HH" / "LH"
    swing_low_type: str | None = None         # "HL" / "LL"
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
    trend_direction: float | None = None      # -1.0/0.0/1.0 numeric
    trend_strength: float | None = None
    trend_leg_count: float | None = None
    structure_integrity: float | None = None
    price_position: float | None = None
    trend_duration_bars: float | None = None


class I4Context(BaseModel):
    """I4 context classification outputs — quantitative regime assessment.

    Plugins:
    - VolatilityRegime (5 fields)
    - TrendRegime (4 fields)
    - MomentumContext (4 fields)
    - GARCHVolatility (4 fields)
    - KalmanTrend (7 fields)
    Total: 24 fields
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
    garch_vol_regime: int | None = None       # int: 0/1/2 regime levels, NOT float
    garch_shock: float | None = None

    # KalmanTrendPlugin outputs
    kalman_trend: float | None = None
    kalman_slope: float | None = None
    kalman_price_position: float | None = None
    kalman_uncertainty: float | None = None
    kalman_upper: float | None = None
    kalman_lower: float | None = None
    kalman_gain: float | None = None


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
    Total: 35 fields
    """

    model_config = ConfigDict(extra="forbid")

    # RSIDivergencePlugin outputs
    rsi_div_bullish: bool | None = None
    rsi_div_bearish: bool | None = None
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
    vol_div_bullish: bool | None = None
    vol_div_bearish: bool | None = None
    vol_div_strength: float | None = None

    # DoubleTBPlugin outputs (double top/bottom)
    dt_db_pattern: float | None = None        # 0=none, 1=DT forming, 2=DT confirmed, 3=DB forming, 4=DB confirmed
    dt_db_neckline: float | None = None
    dt_db_target: float | None = None
    dt_db_confidence: float | None = None

    # HeadShouldersPlugin outputs
    hs_pattern: float | None = None           # 0=none, 1=H&S forming, 2=confirmed, 3=IH&S forming, 4=confirmed
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
    tri_pattern: float | None = None          # 0=none, 1=ascending, 2=descending, 3=symmetrical, 4=rising wedge, 5=falling wedge
    tri_upper_slope: float | None = None
    tri_lower_slope: float | None = None
    tri_apex_bars: float | None = None
    tri_breakout_bias: float | None = None    # -1/0/1
    tri_confidence: float | None = None


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
    Total: 61 fields

    NOTE: SMC has smc_trend_direction (not trend_direction) to avoid collision
    with I3Structure.trend_direction. Both I3 TrendStructure and SMC BOSCHoCH
    output a field called 'trend_direction'. We rename SMC's to smc_trend_direction.
    """

    model_config = ConfigDict(extra="forbid")

    # BOSCHoCHPlugin outputs
    bos_detected: bool | None = None
    bos_direction: int | None = None          # -1/0/1
    bos_level: float | None = None
    choch_detected: bool | None = None
    choch_direction: int | None = None        # -1/0/1
    smc_trend_direction: int | None = None    # renamed from trend_direction to avoid I3 collision

    # FairValueGapPlugin outputs
    fvg_type: int | None = None               # -1/0/1
    fvg_top: float | None = None
    fvg_bottom: float | None = None
    fvg_midpoint: float | None = None
    fvg_size_pct: float | None = None
    fvg_open_count: int | None = None

    # OrderBlocksPlugin outputs
    ob_type: int | None = None                # -1/0/1
    ob_top: float | None = None
    ob_bottom: float | None = None
    ob_strength: float | None = None
    ob_mitigated: bool | None = None
    ob_distance_pct: float | None = None

    # LiquiditySweepsPlugin outputs
    sweep_detected: bool | None = None
    sweep_type: int | None = None             # -1/0/1
    sweep_level: float | None = None
    sweep_depth_pct: float | None = None
    sweep_reclaimed: bool | None = None

    # BOCPDChangePointPlugin outputs
    cp_probability: float | None = None
    cp_raw_probability: float | None = None
    cp_run_length: float | None = None
    cp_confirmation: float | None = None
    cp_detected: float | None = None          # 0.0/1.0 detection flag

    # HMMRegimePlugin outputs
    hmm_regime: float | None = None           # 0=ranging, 1=trending-up, 2=trending-down
    hmm_regime_prob: float | None = None
    hmm_prob_ranging: float | None = None
    hmm_prob_trending_up: float | None = None
    hmm_prob_trending_down: float | None = None
    hmm_regime_duration: float | None = None

    # LiquidityPoolsPlugin outputs
    bsl_level: float | None = None
    bsl_type: float | None = None             # significance score (float encoding)
    bsl_significance: float | None = None
    bsl_dist_atr: float | None = None
    bsl_touches: float | None = None
    ssl_level: float | None = None
    ssl_type: float | None = None
    ssl_significance: float | None = None
    ssl_dist_atr: float | None = None
    ssl_touches: float | None = None
    price_in_premium: float | None = None     # 0.0/1.0 flag
    premium_position: float | None = None     # -1.0 to 1.0
    pool_count: float | None = None

    # SupplyDemandZonesPlugin outputs
    nearest_demand_high: float | None = None
    nearest_demand_low: float | None = None
    demand_freshness: float | None = None
    demand_strength: float | None = None
    demand_dist_atr: float | None = None
    in_demand_zone: float | None = None       # 0.0/1.0 flag
    nearest_supply_high: float | None = None
    nearest_supply_low: float | None = None
    supply_freshness: float | None = None
    supply_strength: float | None = None
    supply_dist_atr: float | None = None
    in_supply_zone: float | None = None       # 0.0/1.0 flag
    active_demand_zones: float | None = None
    active_supply_zones: float | None = None


class I6Confluence(BaseModel):
    """I6 cross-timeframe confluence outputs.

    Plugins:
    - CrossTimeframeConfluence (6 fields)
    """

    model_config = ConfigDict(extra="forbid")

    # CrossTimeframeConfluencePlugin outputs
    ctf_score: float | None = None
    ctf_trend_alignment: float | None = None
    ctf_structure_alignment: float | None = None
    ctf_regime_agreement: float | None = None
    ctf_timeframes_aligned: float | None = None
    ctf_highest_aligned_tf: float | None = None


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
    platform: str = "futures"               # Multi-platform prep; always "futures" for now
    source: Literal["live", "backfill"] = "live"

    bar: OHLCVBar
    i1: I1Indicators
    i3: I3Structure
    i4: I4Context
    i5: I5Patterns
    smc: SMCContext
    i6: I6Confluence
