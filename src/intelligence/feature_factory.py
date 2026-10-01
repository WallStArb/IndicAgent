"""FeatureFactory — pure-function library for computing all 300 FeatureVector primitives.

STATELESS CONTRACT (D-08): FeatureFactory has no __init__ and stores no config.
The FeatureFactoryConfig frozen dataclass is built ONCE by the caller
(IntelligencePipeline._prewarm_threshold_config in P6, or the backfill init in P5)
and passed as an explicit argument on EVERY compute() call. The signature is:

    FeatureFactory.compute(bars, symbol, tf, cache: FeatureCache, config: FeatureFactoryConfig) -> FeatureVector

Config is never stored on the class — always passed as a compute() argument.

PURITY CONTRACT: compute() performs zero IO. No ConfigService.get(), no DB reads,
no Kafka. No async def or await. Deterministic: same inputs -> identical output.

CAUSAL PURITY:
- HMM: forward Viterbi only (D-07). No lookahead via reverse pass. Regime values
  served from FeatureCache (refreshed every regime_cache_refresh_bars by caller).
- OFI/CVD: OHLCV bar proxy path only. No live tick data path.
- Cross-asset (vix_z/flight_quality/yield_slope_z): read from FeatureCache populated
  by update_cross_asset(). Not computed inside compute().
- hmm_duration / above_wk_vwap: state tracked in FeatureCache; incremented/reset by caller.

APR CONTRACT (SC-9): All tunable numeric values come from the FeatureFactoryConfig
argument. Zero inline magic numbers in primitive bodies.
"""

from __future__ import annotations

import dataclasses
import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import numpy as np
import structlog

from src.intelligence.features.contract.registry import Alignment, compute_kernels, default_registry
from src.intelligence.features.kernels._cache_state import FeatureCache
from src.intelligence.features.kernels._hmm import HmmConfig
from src.intelligence.features.kernels._primitives import KeyGroup, none_mask_name
from src.intelligence.features.kernels.calendar import (
    _day_of_month_cos,
    _day_of_month_sin,
    _days_since_quarter_end,
    _days_to_month_end_fraction,
    _dow_encoding,
    _earnings_season_flag,
    _hour_of_day_cos,
    _hour_of_day_sin,
    _in_london_kz,
    _in_ny_session,
    _in_overlap,
    _minute_of_hour_encoding,
    _month_cos,
    _month_position,
    _month_sin,
    _opening_range,
    _opex_flag,
    _power_hour,
    _quad_witching_flag,
    _quarter_cycle_encoding,
    _quarter_position,
    _session_time_pos,
    _tdom_encoding,
    _week_of_month_cos,
    _week_of_month_sin,
    _week_of_year_cos,
    _week_of_year_sin,
)
from src.intelligence.features.kernels.control import (
    _CANARY_CONSTANT_VALUE,
    _canary_acausal_placebo,
    _canary_near_constant,
    _canary_noise_gaussian,
    _canary_noise_uniform,
)
from src.intelligence.features.kernels.cross_tf import (
    CtfSeries,
    ctf_row_inputs,
)
from src.intelligence.features.kernels.macro import (
    RECORD_COLUMNS,
    CrossAssetRecord,
    bar_ts_ns,
    daily_asof_indices,
    daily_close_availability,
)
from src.intelligence.features.kernels.price import (
    _aroon_osc,
    _bar_close_pos,
    _body_ratio,
    _cci,
    _close_vs_open_direction,
    _intraday_ret,
    _lower_wick_ratio,
    _open_ret,
    _open_vs_intraday,
    _overnight_gap,
    _overnight_gap_z,
    _product,
    _range_efficiency,
    _range_position,
    _range_vs_atr,
    _ret_lag_1,
    _ret_lag_2,
    _ret_lag_3,
    _ret_lag_fast,
    _ret_lag_mid,
    _ret_lag_slow,
    _ret_vol_ratio,
    _up_vol_body_diff,
    _upper_wick_ratio,
    _vol_ratio,
)
from src.intelligence.features.kernels.smc import (
    _FVG_OUTPUT_KEYS,
    _POOL_OUTPUT_KEYS,
    BOS,
    FVG,
    OB,
    POOL,
    SWEEP,
    ZONE,
    _compute_bos_choch,
    _compute_fvg,
    _compute_liquidity_pools,
    _compute_liquidity_sweeps,
    _compute_order_blocks,
    _compute_supply_demand_zones,
    _derive_amd_cycle,
)
from src.intelligence.features.kernels.volume import (
    _cmf,
    _informed_flow,
)
from src.intelligence.features.kernels.vp_sr import (
    _NEUTRAL_VP_EXTRA,
    _SWING_STRUCTURE_OUTPUT_KEYS,
    FIB,
    SR,
    SWING,
    SWING_MOMENTUM,
    SWING_STRUCTURE,
    TREND,
    _compute_fib_zones,
    _compute_sr_dist_atr,
    _compute_swing_momentum,
    _compute_swing_structure,
    _compute_trend_structure,
    _derive_session_levels,
    _derive_session_vp,
    _rolling_poc_price,
)
from src.intelligence.schemas import FeatureVector

# ---------------------------------------------------------------------------
# Algorithm version tracking
# ---------------------------------------------------------------------------

# Bump on any algorithm change; IC engine filters by version to avoid mixing IC estimates.
FEATURE_FACTORY_VERSION: str = "1.0.0"


# Module logger for _guard_counted's observability tripwire report ONLY
# (Phase 151 Plan 06) -- this is the sole logging call site in this module;
# compute()'s own docstring purity contract ("zero IO") is preserved because
# the report is only ever invoked from compute_batch(), never from compute().
_logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Feature-to-vector domain registry (IC Engine reads this at startup)
# ---------------------------------------------------------------------------

FEATURE_VECTOR_DOMAIN: dict[str, str] = {
    # Momentum
    "momentum_z_fast": "quant",
    "momentum_z_mid": "quant",
    "range_position": "quant",
    "bar_close_pos": "quant",
    "gap_z": "quant",
    "momentum_z_slow": "quant",
    "momentum_reversal_z": "quant",
    # Volume and order flow
    "informed_flow": "quant",
    "volume_z": "quant",
    "ofi_z": "quant",
    "ofi_div": "quant",
    "cvd_slope_z": "quant",
    "cmf": "quant",
    "rel_volume": "quant",
    "vwap_dev_sigma": "quant",
    # Volatility
    "atr_z": "quant",
    "vol_ratio": "quant",
    # Session-level / market structure
    "poc_dist_atr": "structural",
    "va_position": "structural",
    "sr_support_dist": "structural",
    "sr_resist_dist": "structural",
    # Session-level — Volume Profile (12, Phase 163 Plan 01)
    "nearest_hvn_above_dist_atr": "structural",
    "nearest_hvn_below_dist_atr": "structural",
    "nearest_lvn_above_dist_atr": "structural",
    "nearest_lvn_below_dist_atr": "structural",
    "price_in_value_area": "structural",
    "in_lvn": "structural",
    "va_width_atr": "structural",
    "distance_to_vah_atr": "structural",
    "distance_to_val_atr": "structural",
    "nearest_hvn_dist_atr": "structural",
    "poc_rolling_dist_atr": "structural",
    "poc_session_rolling_divergence_atr": "structural",
    # Session-level — Support/Resistance (5, Phase 163 Plan 01)
    "resistance_strength": "structural",
    "support_strength": "structural",
    "resistance_age_bars": "structural",
    "support_age_bars": "structural",
    "sr_level_count": "structural",
    # Session-level — Swing/Fib/Trend/Session Structure (41, Phase 165 Plan 01)
    "swing_high_dist_atr": "structural",
    "swing_low_dist_atr": "structural",
    "swing_high_type": "structural",
    "swing_low_type": "structural",
    "swing_pattern": "structural",
    "swing_high_age_bars": "structural",
    "swing_low_age_bars": "structural",
    "trend_direction": "structural",
    "trend_strength": "structural",
    "trend_leg_count": "structural",
    "structure_integrity": "structural",
    "price_position": "structural",
    "trend_duration_bars": "structural",
    "swing_amplitude_ratio": "structural",
    "swing_amplitude_expanding": "structural",
    "swing_amplitude_intensity": "structural",
    "swing_velocity_bars": "structural",
    "swing_velocity_bias": "structural",
    "struct_energy": "structural",
    "struct_accel_bias": "structural",
    "swing_volume_confirmation": "structural",
    "nearest_fib_ratio": "structural",
    "nearest_fib_dist_atr": "structural",
    "fib_cluster_strength": "structural",
    "in_fib_discount_zone": "structural",
    "prior_session_high_dist_atr": "structural",
    "prior_session_low_dist_atr": "structural",
    "prior_session_close_dist_atr": "structural",
    "overnight_high_dist_atr": "structural",
    "overnight_low_dist_atr": "structural",
    "overnight_range_pct": "structural",
    "opening_gap_pct": "structural",
    "weekly_pivot_dist_atr": "structural",
    "weekly_r1_dist_atr": "structural",
    "weekly_r2_dist_atr": "structural",
    "weekly_s1_dist_atr": "structural",
    "weekly_s2_dist_atr": "structural",
    "nearest_level_dist_atr": "structural",
    "asian_session_high_dist_atr": "structural",
    "asian_session_low_dist_atr": "structural",
    "gap_filled": "structural",
    # Regime-level
    "hmm_regime_prob": "regime",
    "hmm_entropy": "regime",
    "hmm_duration": "regime",
    "hurst": "quant",
    "shannon": "quant",
    "garch_ratio": "regime",
    "hma_slope_z": "quant",
    "adx": "quant",
    "aroon_fast": "quant",
    "aroon_slow": "quant",
    # Oscillators
    "rsi_fast": "quant",
    "rsi_mid": "quant",
    "rsi_slow": "quant",
    "cci_fast": "quant",
    "cci_mid": "quant",
    "cci_slow": "quant",
    # Cross-asset / macro
    "vix_z": "macro",
    "flight_quality": "macro",
    "yield_slope_z": "macro",
    # Calendar / session
    "in_ny_session": "calendar",
    "in_london_kz": "calendar",
    "in_overlap": "calendar",
    "power_hour": "calendar",
    "opening_range": "calendar",
    "above_wk_vwap": "calendar",
    "dow_sin": "calendar",
    "dow_cos": "calendar",
    "month_position": "calendar",
    "quarter_position": "calendar",
    "days_to_month_end": "calendar",
    # Calendar — Cycle/TDOM/Minute Coordinates (Phase 151 Plan 01)
    "quarter_cycle_sin": "calendar",
    "quarter_cycle_cos": "calendar",
    "tdom_sin": "calendar",
    "tdom_cos": "calendar",
    "minute_of_hour_sin": "calendar",
    "minute_of_hour_cos": "calendar",
    # Velocity Primitives (Phase 151 Plan 01 Task 2)
    "momentum_z_velocity_fast": "quant",
    "momentum_z_velocity_mid": "quant",
    "momentum_z_velocity_slow": "quant",
    "vwap_dev_sigma_velocity": "quant",
    # Velocity Primitives Extension (todo 320)
    "rsi_velocity_fast": "quant",
    "rsi_velocity_mid": "quant",
    "rsi_velocity_slow": "quant",
    "ofi_z_velocity": "quant",
    "cvd_slope_z_velocity": "quant",
    "volume_z_velocity": "quant",
    # Recency / Statistical Atomics (Phase 151 Plan 03, todo 180)
    "bars_since_high_fast": "quant",
    "bars_since_high_slow": "quant",
    "bars_since_low_fast": "quant",
    "bars_since_low_slow": "quant",
    "bars_since_52w_high": "quant",
    "bars_since_52w_low": "quant",
    "bars_since_extreme_move_fast": "quant",
    "bars_since_extreme_move_slow": "quant",
    "bars_since_vol_spike_fast": "quant",
    "bars_since_vol_spike_slow": "quant",
    "abs_ret_autocorr_1": "quant",
    # Cross-asset — Spread/Beta Atomics (Phase 151 Plan 04)
    "tip_tlt_ret_z": "macro",
    "hyg_lqd_ret_z": "macro",
    "sb_corr_fast": "macro",
    "sb_corr_slow": "macro",
    "sb_corr_z": "macro",
    "equity_beta_z": "macro",
    "rate_beta_z": "macro",
    # Named Interaction Primitives (Phase 151 Plan 05, todos 066/104)
    "ret_div_1m_5m": "quant",
    "ret_div_5m_1h": "quant",
    "ret_div_1h_1d": "quant",
    "opex_flag": "calendar",
    "quad_witching_flag": "calendar",
    "earnings_season_flag": "calendar",
    "days_since_quarter_end": "calendar",
    # Theory-Motivated Interactions (Phase 151 Plan 06). "quant" for the 8
    # momentum/breakout/reversion/volume products, "macro" for the 2
    # term-structure/VIX-conditioned products (#8/#9).
    "momentum_vol_regime_product": "quant",
    "momentum_trend_product": "quant",
    "breakout_volume_product": "quant",
    "reversion_hurst_product": "quant",
    "quarter_momentum_product": "quant",
    "variance_ratio_momentum_product": "quant",
    "illiquidity_momentum_product": "quant",
    "yield_slope_momentum_product": "macro",
    "vix_reversion_product": "macro",
    "efficiency_volume_product": "quant",
    # Cross-timeframe
    "ctf_momentum": "quant",
    "ctf_vwap_align": "quant",
    "ctf_regime_align": "regime",
    # Statistical / liquidity
    "amihud_illiq_z": "quant",
    "high_52w_dist": "quant",
    "ret_skew_z": "quant",
    "ret_acf1_z": "quant",
    # Renaissance Primitives — Bar Anatomy Ratios (Phase 142.5 Plan 01)
    "body_ratio": "quant",
    "upper_wick_ratio": "quant",
    "lower_wick_ratio": "quant",
    "range_vs_atr": "quant",
    "close_vs_open_direction": "quant",
    "overnight_gap": "quant",
    "overnight_gap_z": "quant",
    "range_efficiency": "quant",
    # Renaissance Primitives — Lagged Return Series (Phase 142.5 Plan 01)
    "ret_lag_1": "quant",
    "ret_lag_2": "quant",
    "ret_lag_3": "quant",
    "ret_lag_fast": "quant",
    "ret_lag_mid": "quant",
    "ret_lag_slow": "quant",
    # Renaissance Primitives — Open-to-Close Split (Phase 142.5 Plan 01)
    "open_ret": "quant",
    "intraday_ret": "quant",
    "open_vs_intraday": "quant",
    "session_time_pos": "calendar",
    # Renaissance Primitives — Temporal Coordinates (Phase 142.5 Plan 02)
    "hour_of_day_sin": "calendar",
    "hour_of_day_cos": "calendar",
    "week_of_month_sin": "calendar",
    "week_of_month_cos": "calendar",
    "day_of_month_sin": "calendar",
    "day_of_month_cos": "calendar",
    "week_of_year_sin": "calendar",
    "week_of_year_cos": "calendar",
    "month_sin": "calendar",
    "month_cos": "calendar",
    # Renaissance Primitives — Volume Structure (Phase 142.5 Plan 02)
    "vol_acceleration": "quant",
    "dollar_vol_z": "quant",
    "vol_range_ratio": "quant",
    "vol_trend_ratio": "quant",
    "up_vol_ratio_fast": "quant",
    "up_vol_ratio_slow": "quant",
    "vol_percentile": "quant",
    "vol_persistence": "quant",
    "vol_std_z": "quant",
    "mfi_fast": "quant",
    "mfi_slow": "quant",
    "obv_z": "quant",
    # Renaissance Primitives — Breakout Distance (Phase 142.5 Plan 05)
    "dist_from_high_fast": "quant",
    "dist_from_high_slow": "quant",
    "dist_from_low_fast": "quant",
    "dist_from_low_slow": "quant",
    "range_pct_fast": "quant",
    "range_pct_slow": "quant",
    "stoch_k_fast": "quant",
    "stoch_k_slow": "quant",
    "price_percentile_fast": "quant",
    "price_percentile_slow": "quant",
    "efficiency_ratio_fast": "quant",
    "efficiency_ratio_slow": "quant",
    # Renaissance Primitives — Return Distribution (Phase 142.5 Plan 03)
    "ret_kurtosis_z_fast": "quant",
    "ret_kurtosis_z_slow": "quant",
    "ret_autocorr_1": "quant",
    "ret_autocorr_5": "quant",
    "updown_ratio_fast": "quant",
    "updown_ratio_slow": "quant",
    "streak_z": "quant",
    # Renaissance Primitives — Realized Variance / Volatility (Phase 142.5 Plan 03)
    "realized_var_ratio_fast": "quant",
    "realized_var_ratio_slow": "quant",
    "range_to_close": "quant",
    "true_range_pct": "quant",
    "vol_of_vol": "quant",
    "high_low_corr": "quant",
    "variance_ratio_fast": "quant",
    "variance_ratio_slow": "quant",
    "vol_asymmetry_z": "quant",
    "bb_pct_b_fast": "quant",
    "bb_pct_b_slow": "quant",
    "hv_z_fast": "quant",
    "hv_z_slow": "quant",
    "hv_ratio": "quant",
    # Renaissance Primitives — Alternative Volatility Estimators (Phase 142.5 Plan 04)
    "parkinson_vol_z": "quant",
    "garman_klass_vol_z": "quant",
    "yang_zhang_vol_z": "quant",
    # Renaissance Primitives — Volatility Dynamics (Phase 142.5 Plan 04)
    "parkinson_vol_velocity": "quant",
    "garman_klass_vol_velocity": "quant",
    "yang_zhang_vol_velocity": "quant",
    "vol_velocity_z": "quant",
    "intraday_noise_ratio": "quant",
    # Renaissance Primitives — Price-Volume Interactions (Phase 142.5 Plan 05.5)
    "vol_body_product": "quant",
    "ret_vol_product_fast": "quant",
    "price_vol_corr_fast": "quant",
    "price_vol_corr_slow": "quant",
    "range_vol_product": "quant",
    "up_vol_body_diff": "quant",
    "ret_vol_ratio_fast": "quant",
    "vol_skew_product": "quant",
    # Canary / Control Predictors (Phase 143.1 Plan 02, todo 068)
    "canary_noise_gaussian": "control",
    "canary_noise_uniform": "control",
    "canary_constant": "control",
    "canary_near_constant": "control",
    "canary_acausal_placebo": "control",
    # Session-level — Smart Money Concepts (36, Phase 164 Plan 01). Tag matches
    # the archived plugins' own capability_tags value (RESEARCH.md A5) -- this
    # is a separate screening vocabulary from concept_registry (domain='feature')
    # .group_name (which uses 'structure' instead, see migration 266's header
    # note). Phase 170 Plan 07: group_name is deliberately UNCONSTRAINED TEXT on
    # concept_registry (migration 283 L-10), unlike the retired predecessor
    # table's 11-value CHECK -- this FEATURE_VECTOR_DOMAIN dict remains its own
    # separate, always-unconstrained vocabulary regardless of that change.
    "ob_bull_dist_atr": "smart_money",
    "ob_bear_dist_atr": "smart_money",
    "ob_strength": "smart_money",
    "ob_mitigated_flag": "smart_money",
    "breaker_dist_atr": "smart_money",
    "breaker_block_active": "smart_money",
    "ob_mitigation_pct": "smart_money",
    "fvg_dist_atr": "smart_money",
    "fvg_size_atr": "smart_money",
    "fvg_open_count": "smart_money",
    "sweep_detected": "smart_money",
    "sweep_strength": "smart_money",
    "reclaim_velocity": "smart_money",
    "bars_since_last_sweep": "smart_money",
    "bsl_dist_atr": "smart_money",
    "ssl_dist_atr": "smart_money",
    "bsl_touches": "smart_money",
    "ssl_touches": "smart_money",
    "pool_count": "smart_money",
    "demand_dist_atr": "smart_money",
    "supply_dist_atr": "smart_money",
    "demand_freshness": "smart_money",
    "supply_freshness": "smart_money",
    "active_demand_zones": "smart_money",
    "active_supply_zones": "smart_money",
    "zone_friction_score": "smart_money",
    "bos_strength": "smart_money",
    "choch_strength": "smart_money",
    "bos_direction": "smart_money",
    "choch_direction": "smart_money",
    "smc_trend_direction": "smart_money",
    "bars_since_last_shift": "smart_money",
    "amd_phase": "smart_money",
    "amd_manipulation_detected": "smart_money",
    "amd_distribution_direction": "smart_money",
    "manip_strength": "smart_money",
    # Cross-sectional (nullable — populated by Phase 139)
    "momentum_rank_z": "quant",
    "volume_rank_z": "quant",
    "volatility_rank_z": "quant",
}

# ---------------------------------------------------------------------------
# APR-backed configuration (frozen, built once by caller)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FeatureFactoryConfig:
    """Frozen APR-backed parameter container for FeatureFactory.compute().

    Built ONCE by IntelligencePipeline._prewarm_threshold_config() or the
    backfill init. Passed as an explicit argument to compute() on every bar.
    APR keys (feature.* namespace) map directly to these fields.

    Fields:
        momentum_window_fast: APR feature.momentum.window_fast
        momentum_window_mid: APR feature.momentum.window_mid
        momentum_window_slow: APR feature.momentum.window_slow
        momentum_zscore_window: APR feature.momentum.zscore_window
        volume_zscore_window: APR feature.volume.zscore_window
        ofi_zscore_window: APR feature.ofi.zscore_window
        cvd_slope_bars: APR feature.cvd.slope_bars
        cmf_period: APR feature.cmf.period
        vol_short_bars: APR feature.vol.short_bars
        vol_long_bars: APR feature.vol.long_bars
        hma_period: APR feature.hma.period
        adx_period: APR feature.adx.period
        hurst_window: APR feature.hurst.window
        garch_window: APR feature.garch.window
        vix_zscore_window: APR feature.vix.zscore_window
        yield_curve_zscore_window: APR feature.yield_curve.zscore_window
        regime_cache_refresh_bars: APR feature.regime.cache_refresh_bars
        min_bars_warmup: APR feature.cache.min_bars_warmup
        cross_asset_rv_window: APR feature.cross_asset.rv_window
        ny_session_start_utc_hour: APR feature.session.ny_start_utc_hour
        ny_session_start_utc_minute: APR feature.session.ny_start_utc_minute
        ny_session_end_utc_hour: APR feature.session.ny_end_utc_hour
        overlap_start_utc_hour: APR feature.session.overlap_start_utc_hour
        overlap_end_utc_hour: APR feature.session.overlap_end_utc_hour
        london_kz_start_utc_hour: APR feature.session.london_kz_start_utc_hour
        london_kz_end_utc_hour: APR feature.session.london_kz_end_utc_hour
        power_hour_start_utc_hour: APR feature.session.power_hour_start_utc_hour
        power_hour_end_utc_hour: APR feature.session.power_hour_end_utc_hour
        opening_range_start_minute: APR feature.session.opening_range_start_minute
        opening_range_end_minute: APR feature.session.opening_range_end_minute
        ret_lag_fast: APR feature.ret_lag.fast
        ret_lag_mid: APR feature.ret_lag.mid
        ret_lag_slow: APR feature.ret_lag.slow
        overnight_gap_window: APR feature.overnight_gap.window
        dollar_vol_window: APR feature.dollar_vol.window
        vol_range_ratio_window: APR feature.vol_range_ratio.window
        vol_trend_fast: APR feature.vol_trend.fast
        vol_trend_slow: APR feature.vol_trend.slow
        up_vol_ratio_fast: APR feature.up_vol_ratio.fast
        up_vol_ratio_slow: APR feature.up_vol_ratio.slow
        vol_percentile_window: APR feature.vol_percentile.window
        vol_persistence_window: APR feature.vol_persistence.window
        vol_std_window: APR feature.vol_std.window
        mfi_fast: APR feature.mfi.fast
        mfi_slow: APR feature.mfi.slow
        obv_window: APR feature.obv.window
        dist_window_fast: APR feature.breakout.dist_window_fast
        dist_window_slow: APR feature.breakout.dist_window_slow
        range_window_fast: APR feature.breakout.range_window_fast
        range_window_slow: APR feature.breakout.range_window_slow
        stoch_window_fast: APR feature.breakout.stoch_window_fast
        stoch_window_slow: APR feature.breakout.stoch_window_slow
        percentile_window_fast: APR feature.breakout.percentile_window_fast
        percentile_window_slow: APR feature.breakout.percentile_window_slow
        efficiency_window_fast: APR feature.breakout.efficiency_window_fast
        efficiency_window_slow: APR feature.breakout.efficiency_window_slow
        ret_kurtosis_fast: APR feature.ret_kurtosis.fast
        ret_kurtosis_slow: APR feature.ret_kurtosis.slow
        ret_kurtosis_zscore_window: APR feature.ret_kurtosis.zscore_window
        updown_ratio_fast: APR feature.updown_ratio.fast
        updown_ratio_slow: APR feature.updown_ratio.slow
        streak_window: APR feature.streak.window
        realized_var_fast: APR feature.realized_var.fast
        realized_var_slow: APR feature.realized_var.slow
        vol_of_vol_window: APR feature.vol_of_vol.window
        high_low_corr_window: APR feature.high_low_corr.window
        variance_ratio_fast: APR feature.variance_ratio.fast
        variance_ratio_slow: APR feature.variance_ratio.slow
        vol_asymmetry_window: APR feature.vol_asymmetry.window
        bb_pct_b_fast: APR feature.bb_pct_b.fast
        bb_pct_b_slow: APR feature.bb_pct_b.slow
        hv_fast: APR feature.hv.fast
        hv_slow: APR feature.hv.slow
        hv_ratio_window: APR feature.hv.ratio_window
        parkinson_vol_window: APR feature.parkinson_vol.window
        parkinson_vol_zscore_window: APR feature.parkinson_vol.zscore_window
        garman_klass_vol_window: APR feature.garman_klass_vol.window
        garman_klass_vol_zscore_window: APR feature.garman_klass_vol.zscore_window
        yang_zhang_vol_window: APR feature.yang_zhang_vol.window
        yang_zhang_vol_zscore_window: APR feature.yang_zhang_vol.zscore_window
        vol_velocity_window: APR feature.vol_velocity.window
        intraday_noise_window: APR feature.intraday_noise.window
        price_vol_corr_fast: APR feature.price_vol_corr.fast
        price_vol_corr_slow: APR feature.price_vol_corr.slow
        momentum_velocity_window: APR feature.momentum_velocity.window
        vwap_velocity_window: APR feature.vwap_velocity.window
        rsi_velocity_window: APR feature.rsi_velocity.window
        ofi_velocity_window: APR feature.ofi_velocity.window
        cvd_velocity_window: APR feature.cvd_velocity.window
        volume_velocity_window: APR feature.volume_velocity.window
        extreme_move_sigma_threshold: APR feature.bars_since_extreme_move.sigma_threshold
        vol_spike_threshold: APR feature.bars_since_vol_spike.threshold
        tip_tlt_zscore_window: APR feature.tip_tlt.zscore_window
        hyg_lqd_zscore_window: APR feature.hyg_lqd.zscore_window
        sb_corr_window_fast: APR feature.sb_corr.window_fast
        sb_corr_window_slow: APR feature.sb_corr.window_slow
        sb_corr_zscore_window: APR feature.sb_corr.zscore_window
        factor_beta_window: APR feature.factor_beta.window
        factor_beta_zscore_window: APR feature.factor_beta.zscore_window
        session_vp_value_area_pct: APR feature.session_vp.value_area_pct
        session_vp_n_buckets: APR feature.session_vp.n_buckets
        session_vp_hvn_threshold: APR feature.session_vp.hvn_threshold
        session_vp_lvn_threshold: APR feature.session_vp.lvn_threshold
        session_vp_rolling_window: APR feature.session_vp.rolling_window
        sr_window: APR feature.sr.window
        sr_cluster_atr_mult: APR feature.sr.cluster_atr_mult
        sr_lookback_by_tf: APR feature.sr.lookback_by_tf
        smc_order_blocks_lookback: APR feature.smc.order_blocks.lookback
        smc_order_blocks_impulse_bars: APR feature.smc.order_blocks.impulse_bars
        smc_order_blocks_significant_move_pct: APR feature.smc.order_blocks.significant_move_pct
        smc_order_blocks_opposing_candle_lookback: APR feature.smc.order_blocks.opposing_candle_lookback
        smc_order_blocks_strength_fallback: APR feature.smc.order_blocks.strength_fallback
        smc_fvg_lookback: APR feature.smc.fvg.lookback
        smc_liquidity_sweeps_lookback: APR feature.smc.liquidity_sweeps.lookback
        smc_liquidity_sweeps_swing_neighbor: APR feature.smc.liquidity_sweeps.swing_neighbor
        smc_liquidity_sweeps_reclaim_bars: APR feature.smc.liquidity_sweeps.reclaim_bars
        smc_liquidity_sweeps_depth_ramp_max_pct: APR feature.smc.liquidity_sweeps.depth_ramp_max_pct
        smc_liquidity_sweeps_reclaim_velocity_ramp_max: APR feature.smc.liquidity_sweeps.reclaim_velocity_ramp_max
        smc_liquidity_pools_lookback: APR feature.smc.liquidity_pools.lookback
        smc_liquidity_pools_swing_neighbor: APR feature.smc.liquidity_pools.swing_neighbor
        smc_liquidity_pools_equal_level_tolerance_atr_mult: APR feature.smc.liquidity_pools.equal_level_tolerance_atr_mult
        smc_liquidity_pools_session_bars: APR feature.smc.liquidity_pools.session_bars
        smc_liquidity_pools_significance_weights: APR feature.smc.liquidity_pools.significance_weights
        smc_zones_lookback: APR feature.smc.zones.lookback
        smc_zones_impulse_atr_mult: APR feature.smc.zones.impulse_atr_mult
        smc_zones_base_body_ratio: APR feature.smc.zones.base_body_ratio
        smc_zones_base_atr_mult: APR feature.smc.zones.base_atr_mult
        smc_zones_max_base_bars: APR feature.smc.zones.max_base_bars
        smc_zones_zone_height_cap_atr_mult: APR feature.smc.zones.zone_height_cap_atr_mult
        smc_zones_impulse_overlap_atr_mult: APR feature.smc.zones.impulse_overlap_atr_mult
        smc_zones_freshness_decay_k: APR feature.smc.zones.freshness_decay_k
        smc_zones_strength_premium_align_mult: APR feature.smc.zones.strength_premium_align_mult
        smc_zones_strength_fvg_align_mult: APR feature.smc.zones.strength_fvg_align_mult
        smc_zones_age_penalty_floor: APR feature.smc.zones.age_penalty_floor
        smc_zones_age_penalty_window_bars: APR feature.smc.zones.age_penalty_window_bars
        smc_zones_age_penalty_max_pct: APR feature.smc.zones.age_penalty_max_pct
        smc_zones_max_tracked_zones: APR feature.smc.zones.max_tracked_zones
        smc_bos_choch_lookback: APR feature.smc.bos_choch.lookback
        smc_bos_choch_swing_neighbor: APR feature.smc.bos_choch.swing_neighbor
        smc_amd_accum_start_utc_hour: APR feature.smc.amd.accum_start_utc_hour
        smc_amd_manip_end_utc_hour: APR feature.smc.amd.manip_end_utc_hour
        smc_amd_dist_end_utc_hour: APR feature.smc.amd.dist_end_utc_hour
        swing_pivot_window: APR feature.swing.pivot_window
        swing_lookback_bars: APR feature.swing.lookback_bars
        trend_structure_atr_strength_divisor: APR feature.trend_structure.atr_strength_divisor
        trend_structure_range_lookback_bars: APR feature.trend_structure.range_lookback_bars
        swing_momentum_confirm_n: APR feature.swing_momentum.confirm_n
        swing_momentum_max_extremes: APR feature.swing_momentum.max_extremes
        swing_momentum_lookback_bars: APR feature.swing_momentum.lookback_bars
        swing_momentum_reference_bars: APR feature.swing_momentum.reference_bars
        swing_momentum_speed_factor_min: APR feature.swing_momentum.speed_factor_min
        swing_momentum_speed_factor_max: APR feature.swing_momentum.speed_factor_max
        swing_momentum_energy_divisor: APR feature.swing_momentum.energy_divisor
        swing_momentum_intensity_ramp_lo: APR feature.swing_momentum.intensity_ramp_lo
        swing_momentum_intensity_ramp_hi: APR feature.swing_momentum.intensity_ramp_hi
        fib_cluster_atr_divisor: APR feature.fib.cluster_atr_divisor
        session_levels_asia_start_et_hour: APR feature.session_levels.asia_start_et_hour
        session_levels_asia_end_et_hour: APR feature.session_levels.asia_end_et_hour
        atr_normalization_min_pct: APR feature.atr_normalization.min_atr_pct
        ctf_higher_tf_map: APR feature.ctf.higher_tf_map
    """

    momentum_window_fast: int  # feature.momentum.window_fast
    momentum_window_mid: int  # feature.momentum.window_mid
    momentum_window_slow: int  # feature.momentum.window_slow
    momentum_zscore_window: int  # feature.momentum.zscore_window
    volume_zscore_window: int  # feature.volume.zscore_window
    ofi_zscore_window: int  # feature.ofi.zscore_window
    cvd_slope_bars: int  # feature.cvd.slope_bars
    cmf_period: int  # feature.cmf.period
    vol_short_bars: int  # feature.vol.short_bars
    vol_long_bars: int  # feature.vol.long_bars
    hma_period: int  # feature.hma.period
    adx_period: int  # feature.adx.period
    hurst_window: int  # feature.hurst.window
    garch_window: int  # feature.garch.window
    vix_zscore_window: int  # feature.vix.zscore_window
    yield_curve_zscore_window: int  # feature.yield_curve.zscore_window
    regime_cache_refresh_bars: int  # feature.regime.cache_refresh_bars
    # Cache warmup / cross-asset
    min_bars_warmup: int  # feature.cache.min_bars_warmup
    cross_asset_rv_window: int  # feature.cross_asset.rv_window
    # Session / calendar (APR-backed so DST/market-hour adjustments are operationally safe)
    ny_session_start_utc_hour: int  # feature.session.ny_start_utc_hour
    ny_session_start_utc_minute: int  # feature.session.ny_start_utc_minute
    ny_session_end_utc_hour: int  # feature.session.ny_end_utc_hour
    overlap_start_utc_hour: int  # feature.session.overlap_start_utc_hour
    overlap_end_utc_hour: int  # feature.session.overlap_end_utc_hour
    london_kz_start_utc_hour: int  # feature.session.london_kz_start_utc_hour
    london_kz_end_utc_hour: int  # feature.session.london_kz_end_utc_hour
    power_hour_start_utc_hour: int  # feature.session.power_hour_start_utc_hour
    power_hour_end_utc_hour: int  # feature.session.power_hour_end_utc_hour
    opening_range_start_minute: int  # feature.session.opening_range_start_minute
    opening_range_end_minute: int  # feature.session.opening_range_end_minute
    # Oscillators (added in P7)
    rsi_fast_period: int  # feature.period.rsi.fast
    rsi_mid_period: int  # feature.period.rsi.mid
    rsi_slow_period: int  # feature.period.rsi.slow
    cci_fast_period: int  # feature.period.cci.fast
    cci_mid_period: int  # feature.period.cci.mid
    cci_slow_period: int  # feature.period.cci.slow
    # Trend freshness
    aroon_fast_period: int  # feature.period.aroon.fast
    aroon_slow_period: int  # feature.period.aroon.slow
    # Statistical / liquidity
    amihud_zscore_window: int  # feature.amihud.zscore_window
    ret_skew_window: int  # feature.ret_skew.window
    ret_skew_zscore_window: int  # feature.ret_skew.zscore_window
    ret_acf_window: int  # feature.ret_acf.window
    ret_acf_zscore_window: int  # feature.ret_acf.zscore_window
    high_52w_window: int  # feature.high_52w.window
    # Renaissance Primitives — lagged returns + overnight gap z-score (Phase 142.5 Plan 01)
    ret_lag_fast: int  # feature.ret_lag.fast
    ret_lag_mid: int  # feature.ret_lag.mid
    ret_lag_slow: int  # feature.ret_lag.slow
    overnight_gap_window: int  # feature.overnight_gap.window
    # Renaissance Primitives — volume structure (Phase 142.5 Plan 02)
    dollar_vol_window: int  # feature.dollar_vol.window
    vol_range_ratio_window: int  # feature.vol_range_ratio.window
    vol_trend_fast: int  # feature.vol_trend.fast
    vol_trend_slow: int  # feature.vol_trend.slow
    up_vol_ratio_fast: int  # feature.up_vol_ratio.fast
    up_vol_ratio_slow: int  # feature.up_vol_ratio.slow
    vol_percentile_window: int  # feature.vol_percentile.window
    vol_persistence_window: int  # feature.vol_persistence.window
    vol_std_window: int  # feature.vol_std.window
    mfi_fast: int  # feature.mfi.fast
    mfi_slow: int  # feature.mfi.slow
    obv_window: int  # feature.obv.window
    # Renaissance Primitives — breakout distance (Phase 142.5 Plan 05)
    dist_window_fast: int  # feature.breakout.dist_window_fast
    dist_window_slow: int  # feature.breakout.dist_window_slow
    range_window_fast: int  # feature.breakout.range_window_fast
    range_window_slow: int  # feature.breakout.range_window_slow
    stoch_window_fast: int  # feature.breakout.stoch_window_fast
    stoch_window_slow: int  # feature.breakout.stoch_window_slow
    percentile_window_fast: int  # feature.breakout.percentile_window_fast
    percentile_window_slow: int  # feature.breakout.percentile_window_slow
    efficiency_window_fast: int  # feature.breakout.efficiency_window_fast
    efficiency_window_slow: int  # feature.breakout.efficiency_window_slow
    # Renaissance Primitives — return distribution + realized variance (Phase 142.5 Plan 03)
    ret_kurtosis_fast: int  # feature.ret_kurtosis.fast
    ret_kurtosis_slow: int  # feature.ret_kurtosis.slow
    ret_kurtosis_zscore_window: int  # feature.ret_kurtosis.zscore_window
    updown_ratio_fast: int  # feature.updown_ratio.fast
    updown_ratio_slow: int  # feature.updown_ratio.slow
    streak_window: int  # feature.streak.window
    realized_var_fast: int  # feature.realized_var.fast
    realized_var_slow: int  # feature.realized_var.slow
    vol_of_vol_window: int  # feature.vol_of_vol.window
    high_low_corr_window: int  # feature.high_low_corr.window
    variance_ratio_fast: int  # feature.variance_ratio.fast
    variance_ratio_slow: int  # feature.variance_ratio.slow
    vol_asymmetry_window: int  # feature.vol_asymmetry.window
    bb_pct_b_fast: int  # feature.bb_pct_b.fast
    bb_pct_b_slow: int  # feature.bb_pct_b.slow
    hv_fast: int  # feature.hv.fast
    hv_slow: int  # feature.hv.slow
    hv_ratio_window: int  # feature.hv.ratio_window
    # Renaissance Primitives — Alternative Volatility + Volatility Dynamics (Phase 142.5 Plan 04)
    parkinson_vol_window: int  # feature.parkinson_vol.window
    parkinson_vol_zscore_window: int  # feature.parkinson_vol.zscore_window
    garman_klass_vol_window: int  # feature.garman_klass_vol.window
    garman_klass_vol_zscore_window: int  # feature.garman_klass_vol.zscore_window
    yang_zhang_vol_window: int  # feature.yang_zhang_vol.window
    yang_zhang_vol_zscore_window: int  # feature.yang_zhang_vol.zscore_window
    vol_velocity_window: int  # feature.vol_velocity.window
    intraday_noise_window: int  # feature.intraday_noise.window
    # Renaissance Primitives — Price-Volume Interactions (Phase 142.5 Plan 05.5)
    price_vol_corr_fast: int  # feature.price_vol_corr.fast
    price_vol_corr_slow: int  # feature.price_vol_corr.slow
    # Velocity Primitives (Phase 151 Plan 01 Task 2, todo 123). Separate keys
    # per family (not a reuse of vol_velocity_window) per naming-system.md
    # section 7's gradient rule -- momentum-velocity and VWAP-velocity are
    # semantically distinct families.
    momentum_velocity_window: int  # feature.momentum_velocity.window
    vwap_velocity_window: int  # feature.vwap_velocity.window
    # Velocity Primitives Extension (todo 320). Same per-family separate-key
    # rule as the block immediately above -- rsi_velocity_window is shared
    # across all 3 RSI gradients (matching momentum_velocity_window's own
    # one-key-for-3-gradients precedent), ofi/cvd/volume each get their own
    # key since they're semantically distinct families. Non-defaulted,
    # matching momentum_velocity_window/vwap_velocity_window's own precedent.
    rsi_velocity_window: int  # feature.rsi_velocity.window
    ofi_velocity_window: int  # feature.ofi_velocity.window
    cvd_velocity_window: int  # feature.cvd_velocity.window
    volume_velocity_window: int  # feature.volume_velocity.window
    # Recency / Statistical Atomics (Phase 151 Plan 03, todo 180). The 2 event
    # thresholds behind bars_since_extreme_move_*/bars_since_vol_spike_*.
    # Non-defaulted (matching momentum_velocity_window/vwap_velocity_window's
    # own precedent immediately above) -- both real production entrypoints
    # AND every direct FeatureFactoryConfig(...) construction site are wired
    # in this same plan.
    extreme_move_sigma_threshold: float  # feature.bars_since_extreme_move.sigma_threshold
    vol_spike_threshold: float  # feature.bars_since_vol_spike.threshold
    # Cross-asset — Spread/Beta Atomics (Phase 151 Plan 04, todos 123/180).
    # Non-defaulted (matching extreme_move_sigma_threshold/vol_spike_threshold's
    # own precedent immediately above) -- both real production entrypoints AND
    # every direct FeatureFactoryConfig(...) construction site are wired in
    # this same plan. factor_beta (not bare "beta") per glossary's ban on the
    # unqualified term; one shared window pair serves both equity_beta_z and
    # rate_beta_z (same statistic, different factor series).
    tip_tlt_zscore_window: int  # feature.tip_tlt.zscore_window
    hyg_lqd_zscore_window: int  # feature.hyg_lqd.zscore_window
    sb_corr_window_fast: int  # feature.sb_corr.window_fast
    sb_corr_window_slow: int  # feature.sb_corr.window_slow
    sb_corr_zscore_window: int  # feature.sb_corr.zscore_window
    factor_beta_window: int  # feature.factor_beta.window
    factor_beta_zscore_window: int  # feature.factor_beta.zscore_window
    # Canary / Control Predictors (Phase 143.1 Plan 02, todo 068). Seed for
    # both noise canaries (Gaussian and Uniform draw independent sub-seeds
    # from this one base seed -- see _canary_sub_seed). Defaulted (unlike
    # every other field in this dataclass) so the ~6 pre-existing direct
    # FeatureFactoryConfig(...) construction sites across the test suite and
    # services/*.py don't all require updating in this plan; the 2 real
    # production entrypoints (backfill_feature_factory.py,
    # feature_vector_pipeline.py) explicitly wire this from ConfigService.
    canary_rng_seed: int = 90042  # alpha.ic.canary_rng_seed [initial_estimate]
    # Session Volume Profile (Phase 163 Plan 01, D-03/D-13). Defaulted for the
    # same reason as canary_rng_seed above (avoid updating every pre-existing
    # direct FeatureFactoryConfig(...) construction site); the 2 real production
    # entrypoints (backfill_feature_factory.py, feature_vector_pipeline.py)
    # explicitly wire these from ConfigService.
    session_vp_value_area_pct: float = 0.70  # feature.session_vp.value_area_pct
    session_vp_n_buckets: int = 50  # feature.session_vp.n_buckets
    session_vp_hvn_threshold: float = 0.80  # feature.session_vp.hvn_threshold
    session_vp_lvn_threshold: float = 0.20  # feature.session_vp.lvn_threshold
    session_vp_rolling_window: int = 480  # feature.session_vp.rolling_window
    # Support/Resistance (Phase 163 Plan 01, consumed by Plan 03). Same
    # defaulting rationale as above.
    sr_window: int = 10  # feature.sr.window
    sr_cluster_atr_mult: float = 0.5  # feature.sr.cluster_atr_mult
    sr_lookback_by_tf: dict = field(  # feature.sr.lookback_by_tf
        default_factory=lambda: {"1m": 60, "5m": 60, "15m": 80, "1h": 120, "4h": 90, "1d": 60}
    )
    # SMC Institutional Footprint (Phase 164 Plan 01, contract-only -- consumed by
    # Plans 02-04's compute logic). Same defaulting rationale as above (avoid
    # updating every pre-existing direct FeatureFactoryConfig(...) construction
    # site); the 2 real production entrypoints (backfill_feature_factory.py,
    # feature_vector_pipeline.py) explicitly wire these from ConfigService. All
    # values [conventional] -- copied verbatim from the archived smc_context
    # plugins' own hardcoded defaults (164-RESEARCH.md).
    smc_order_blocks_lookback: int = 100  # feature.smc.order_blocks.lookback
    smc_order_blocks_impulse_bars: int = 3  # feature.smc.order_blocks.impulse_bars
    smc_order_blocks_significant_move_pct: float = (
        0.003  # feature.smc.order_blocks.significant_move_pct
    )
    smc_order_blocks_opposing_candle_lookback: int = (
        10  # feature.smc.order_blocks.opposing_candle_lookback
    )
    smc_order_blocks_strength_fallback: float = 0.5  # feature.smc.order_blocks.strength_fallback
    smc_fvg_lookback: int = 100  # feature.smc.fvg.lookback
    smc_liquidity_sweeps_lookback: int = 120  # feature.smc.liquidity_sweeps.lookback
    smc_liquidity_sweeps_swing_neighbor: int = 5  # feature.smc.liquidity_sweeps.swing_neighbor
    smc_liquidity_sweeps_reclaim_bars: int = 3  # feature.smc.liquidity_sweeps.reclaim_bars
    smc_liquidity_sweeps_depth_ramp_max_pct: float = (
        2.0  # feature.smc.liquidity_sweeps.depth_ramp_max_pct
    )
    smc_liquidity_sweeps_reclaim_velocity_ramp_max: float = (
        0.5  # feature.smc.liquidity_sweeps.reclaim_velocity_ramp_max
    )
    smc_liquidity_pools_lookback: int = 150  # feature.smc.liquidity_pools.lookback
    smc_liquidity_pools_swing_neighbor: int = 5  # feature.smc.liquidity_pools.swing_neighbor
    smc_liquidity_pools_equal_level_tolerance_atr_mult: float = (
        0.75  # feature.smc.liquidity_pools.equal_level_tolerance_atr_mult
    )
    smc_liquidity_pools_session_bars: int = 390  # feature.smc.liquidity_pools.session_bars
    smc_liquidity_pools_significance_weights: dict = (
        field(  # feature.smc.liquidity_pools.significance_weights
            default_factory=lambda: {
                "eq_highs_3": 0.75,
                "eq_lows_3": 0.75,
                "eq_highs_2": 0.60,
                "eq_lows_2": 0.60,
                "session_high": 0.50,
                "session_low": 0.50,
            }
        )
    )
    smc_zones_lookback: int = 150  # feature.smc.zones.lookback
    smc_zones_impulse_atr_mult: float = 1.5  # feature.smc.zones.impulse_atr_mult
    smc_zones_base_body_ratio: float = 0.5  # feature.smc.zones.base_body_ratio
    smc_zones_base_atr_mult: float = 1.0  # feature.smc.zones.base_atr_mult
    smc_zones_max_base_bars: int = 5  # feature.smc.zones.max_base_bars
    smc_zones_zone_height_cap_atr_mult: float = 2.5  # feature.smc.zones.zone_height_cap_atr_mult
    smc_zones_impulse_overlap_atr_mult: float = 0.4  # feature.smc.zones.impulse_overlap_atr_mult
    smc_zones_freshness_decay_k: float = 0.5  # feature.smc.zones.freshness_decay_k
    smc_zones_strength_premium_align_mult: float = (
        1.20  # feature.smc.zones.strength_premium_align_mult
    )
    smc_zones_strength_fvg_align_mult: float = 1.15  # feature.smc.zones.strength_fvg_align_mult
    smc_zones_age_penalty_floor: float = 0.70  # feature.smc.zones.age_penalty_floor
    smc_zones_age_penalty_window_bars: int = 200  # feature.smc.zones.age_penalty_window_bars
    smc_zones_age_penalty_max_pct: float = 0.30  # feature.smc.zones.age_penalty_max_pct
    smc_zones_max_tracked_zones: int = 5  # feature.smc.zones.max_tracked_zones
    smc_bos_choch_lookback: int = 120  # feature.smc.bos_choch.lookback
    smc_bos_choch_swing_neighbor: int = 5  # feature.smc.bos_choch.swing_neighbor
    smc_amd_accum_start_utc_hour: int = 20  # feature.smc.amd.accum_start_utc_hour
    smc_amd_manip_end_utc_hour: int = 10  # feature.smc.amd.manip_end_utc_hour
    smc_amd_dist_end_utc_hour: int = 21  # feature.smc.amd.dist_end_utc_hour
    # Swing/Fib/Trend/Session Structure (Phase 165 Plan 01, contract-only --
    # consumed by Plans 02-04's compute logic). Same defaulting rationale as
    # above (avoid updating every pre-existing direct FeatureFactoryConfig(...)
    # construction site); the 2 real production entrypoints
    # (backfill_feature_factory.py, feature_vector_pipeline.py) explicitly
    # wire these from ConfigService. All values [conventional] -- copied
    # verbatim from the archived i3_structure plugins' own hardcoded defaults
    # (165-RESEARCH.md).
    swing_pivot_window: int = 5  # feature.swing.pivot_window
    swing_lookback_bars: int = 120  # feature.swing.lookback_bars
    trend_structure_atr_strength_divisor: float = (
        5.0  # feature.trend_structure.atr_strength_divisor
    )
    trend_structure_range_lookback_bars: int = 20  # feature.trend_structure.range_lookback_bars
    swing_momentum_confirm_n: int = 3  # feature.swing_momentum.confirm_n
    swing_momentum_max_extremes: int = 6  # feature.swing_momentum.max_extremes
    swing_momentum_lookback_bars: int = 60  # feature.swing_momentum.lookback_bars
    swing_momentum_reference_bars: int = 20  # feature.swing_momentum.reference_bars
    swing_momentum_speed_factor_min: float = 0.1  # feature.swing_momentum.speed_factor_min
    swing_momentum_speed_factor_max: float = 3.0  # feature.swing_momentum.speed_factor_max
    swing_momentum_energy_divisor: float = 3.0  # feature.swing_momentum.energy_divisor
    swing_momentum_intensity_ramp_lo: float = 1.0  # feature.swing_momentum.intensity_ramp_lo
    swing_momentum_intensity_ramp_hi: float = 2.0  # feature.swing_momentum.intensity_ramp_hi
    fib_cluster_atr_divisor: float = 2.0  # feature.fib.cluster_atr_divisor
    session_levels_asia_start_et_hour: int = 20  # feature.session_levels.asia_start_et_hour
    session_levels_asia_end_et_hour: int = 4  # feature.session_levels.asia_end_et_hour
    atr_normalization_min_pct: float = 0.0001  # feature.atr_normalization.min_atr_pct
    # CTF (cross-timeframe) higher-timeframe source mapping (todo 242, migration 305).
    # Single source of truth for both backfill_feature_factory.py's batch
    # _build_ctf_series() and feature_vector_pipeline.py's live per-HTF-bar update --
    # do not duplicate this dict. Formerly a hardcoded module constant
    # (feature_cache._CTF_HIGHER_TF); "1d" is self-referential (no timeframe above 1d
    # exists in this corpus) -- ctf_momentum degenerates into a same-tf RSI oscillator
    # there rather than genuine cross-timeframe signal (todo 189), kept for batch/live
    # parity, not because it's a good statistic.
    ctf_higher_tf_map: dict = field(  # feature.ctf.higher_tf_map
        default_factory=lambda: {"5m": "1h", "15m": "1h", "1h": "1d", "1d": "1d"}
    )
    # Earnings-Season Calendar Primitive (Phase 176 Plan 03, todo 353). Same
    # defaulting rationale as canary_rng_seed above (avoid updating every
    # pre-existing direct FeatureFactoryConfig(...) construction site); the 2
    # real production entrypoints (backfill_feature_factory.py,
    # feature_vector_pipeline.py) explicitly wire these from ConfigService.
    earnings_season_start_days: int = 14  # feature.earnings_season.start_days
    earnings_season_end_days: int = 42  # feature.earnings_season.end_days
    # Walk-forward HMM regime kernels (186-13; kernels/regime.py, math in kernels/_hmm.py). The
    # names, APR keys and casts are declared once, in kernels._hmm.HmmConfig, and there are no
    # defaults: every value changes stored regime labels and the live APR values differ from
    # any value a default could carry. None means "not wired": the regime kernels raise on it.
    # Every production entrypoint that runs them loads this with
    # `HmmConfig.from_values(config_service.get_sync)` (backfill_feature_factory.py,
    # feature_vector_pipeline.py). Changing any value invalidates every stored regime label.
    # `infra.hmm.rolling_block_rows` is not here: it changes no output, and the regime writer
    # and the rebuild pass it to the kernels as an argument.
    hmm: HmmConfig | None = None


def invert_ctf_higher_tf_map(higher_tf_map: dict[str, str]) -> dict[str, list[str]]:
    """Inverse of ctf_higher_tf_map: which LTF caches read ctf_momentum from a given
    HTF timeframe when a bar on that HTF arrives (todo 241). e.g. a "1h" bar updates
    both "5m" and "15m" caches; a "1d" bar updates "1h" (and its own, self-referential
    -- see ctf_higher_tf_map's docstring) cache.

    Single source of truth for this derivation (todo 242 /simplify pass) -- both
    services/feature_vector_pipeline.py's _prewarm_threshold_config() (production) and
    tests/unit/pipeline/pipeline_helpers.py's make_agent() (test harness, which bypasses
    _prewarm_threshold_config() via __new__()) call this instead of each carrying their
    own copy of the inversion logic.
    """
    return {
        htf: [ltf for ltf, mapped_htf in higher_tf_map.items() if mapped_htf == htf]
        for htf in set(higher_tf_map.values())
    }


# ---------------------------------------------------------------------------
# _PrecomputedSeries — bundled series arrays for a bar window
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class _PrecomputedSeries:
    """All series arrays precomputed from a bar window. Each has length == len(bars)
    except atr_raw which has length len(bars)-1 (ATR needs prev close)."""

    atr_raw: np.ndarray  # raw ATR series, length n-1
    atr_z: np.ndarray  # ATR z-score padded to length n
    gap_z: np.ndarray
    rel_volume: np.ndarray
    ofi_z: np.ndarray
    cvd_slope_z: np.ndarray
    volume_z: np.ndarray
    momentum_z_fast: np.ndarray
    momentum_z_mid: np.ndarray
    momentum_z_slow: np.ndarray
    momentum_reversal_z: np.ndarray
    vwap_dev_sigma: np.ndarray
    rsi_fast: np.ndarray
    rsi_mid: np.ndarray
    rsi_slow: np.ndarray
    amihud_illiq_z: np.ndarray
    high_52w_dist: np.ndarray
    ret_skew_z: np.ndarray
    ret_acf1_z: np.ndarray
    overnight_gap_z: np.ndarray  # Renaissance Primitives (Phase 142.5 Plan 01)
    # Renaissance Primitives — Volume Structure (Phase 142.5 Plan 02)
    vol_acceleration: np.ndarray
    dollar_vol_z: np.ndarray
    vol_range_ratio: np.ndarray
    vol_trend_ratio: np.ndarray
    up_vol_ratio_fast: np.ndarray
    up_vol_ratio_slow: np.ndarray
    vol_percentile: np.ndarray
    vol_persistence: np.ndarray
    vol_std_z: np.ndarray
    mfi_fast: np.ndarray
    mfi_slow: np.ndarray
    obv_z: np.ndarray
    # Renaissance Primitives — Breakout Distance (Phase 142.5 Plan 05)
    dist_from_high_fast: np.ndarray
    dist_from_high_slow: np.ndarray
    dist_from_low_fast: np.ndarray
    dist_from_low_slow: np.ndarray
    range_pct_fast: np.ndarray
    range_pct_slow: np.ndarray
    stoch_k_fast: np.ndarray
    stoch_k_slow: np.ndarray
    price_percentile_fast: np.ndarray
    price_percentile_slow: np.ndarray
    efficiency_ratio_fast: np.ndarray
    efficiency_ratio_slow: np.ndarray
    # Renaissance Primitives — Return Distribution (Phase 142.5 Plan 03)
    ret_kurtosis_z_fast: np.ndarray
    ret_kurtosis_z_slow: np.ndarray
    ret_autocorr_1: np.ndarray
    ret_autocorr_5: np.ndarray
    updown_ratio_fast: np.ndarray
    updown_ratio_slow: np.ndarray
    streak_z: np.ndarray
    # Renaissance Primitives — Realized Variance / Volatility (Phase 142.5 Plan 03)
    realized_var_ratio_fast: np.ndarray
    realized_var_ratio_slow: np.ndarray
    range_to_close: np.ndarray
    true_range_pct: np.ndarray
    vol_of_vol: np.ndarray
    high_low_corr: np.ndarray
    variance_ratio_fast: np.ndarray
    variance_ratio_slow: np.ndarray
    vol_asymmetry_z: np.ndarray
    bb_pct_b_fast: np.ndarray
    bb_pct_b_slow: np.ndarray
    hv_z_fast: np.ndarray
    hv_z_slow: np.ndarray
    hv_ratio: np.ndarray
    # Renaissance Primitives — Alternative Volatility / Volatility Dynamics (Phase 142.5 Plan 04)
    parkinson_vol_z: np.ndarray
    garman_klass_vol_z: np.ndarray
    yang_zhang_vol_z: np.ndarray
    vol_velocity_z: np.ndarray
    intraday_noise_ratio: np.ndarray
    # Renaissance Primitives — Price-Volume Interactions (Phase 142.5 Plan 05.5)
    price_vol_corr_fast: np.ndarray
    price_vol_corr_slow: np.ndarray
    # Velocity Primitives (Phase 151 Plan 01 Task 2)
    momentum_z_velocity_fast: np.ndarray
    momentum_z_velocity_mid: np.ndarray
    momentum_z_velocity_slow: np.ndarray
    vwap_dev_sigma_velocity: np.ndarray
    # Velocity Primitives Extension (todo 320)
    rsi_velocity_fast: np.ndarray
    rsi_velocity_mid: np.ndarray
    rsi_velocity_slow: np.ndarray
    ofi_z_velocity: np.ndarray
    cvd_slope_z_velocity: np.ndarray
    volume_z_velocity: np.ndarray
    # Recency / Statistical Atomics (Phase 151 Plan 03, todo 180)
    bars_since_high_fast: np.ndarray
    bars_since_high_slow: np.ndarray
    bars_since_low_fast: np.ndarray
    bars_since_low_slow: np.ndarray
    bars_since_52w_high: np.ndarray
    bars_since_52w_low: np.ndarray
    bars_since_extreme_move_fast: np.ndarray
    bars_since_extreme_move_slow: np.ndarray
    bars_since_vol_spike_fast: np.ndarray
    bars_since_vol_spike_slow: np.ndarray
    abs_ret_autocorr_1: np.ndarray


# Every _PrecomputedSeries field except atr_raw is a registry output of the same name; atr_raw is
# the padded ATR intermediate without its leading pad row.
_SERIES_FIELDS: tuple[str, ...] = tuple(
    f.name for f in dataclasses.fields(_PrecomputedSeries) if f.name != "atr_raw"
)
_SERIES_KERNEL_OUTPUTS: tuple[str, ...] = (*_SERIES_FIELDS, "_atr_raw_padded")


def _series_from_kernel_outputs(out: dict[str, np.ndarray]) -> _PrecomputedSeries:
    return _PrecomputedSeries(
        atr_raw=out["_atr_raw_padded"][1:], **{name: out[name] for name in _SERIES_FIELDS}
    )


def _precompute_series(
    opens: np.ndarray,
    highs: np.ndarray,
    lows: np.ndarray,
    closes: np.ndarray,
    volumes: np.ndarray,
    config: FeatureFactoryConfig,
) -> _PrecomputedSeries:
    """Bundle every series array for a bar window from the registry's kernels.

    compute() delegates here; compute_batch runs the same kernels in one call together with its
    scalar columns, so the series formulas have exactly one implementation.
    """
    out = compute_kernels(
        default_registry(),
        {"open": opens, "high": highs, "low": lows, "close": closes, "volume": volumes},
        config,
        outputs=list(_SERIES_KERNEL_OUTPUTS),
    )
    return _series_from_kernel_outputs(out)


# Columns compute_batch reads from registry kernels instead of calling helpers inline.
_DELEGATED_KERNEL_OUTPUTS: tuple[str, ...] = tuple(
    (
        "in_ny_session in_london_kz in_overlap power_hour opening_range session_time_pos "
        "dow_sin dow_cos month_position quarter_position days_to_month_end quarter_cycle_sin "
        "quarter_cycle_cos tdom_sin tdom_cos minute_of_hour_sin minute_of_hour_cos "
        "hour_of_day_sin hour_of_day_cos week_of_month_sin week_of_month_cos day_of_month_sin "
        "day_of_month_cos week_of_year_sin week_of_year_cos month_sin month_cos opex_flag "
        "quad_witching_flag earnings_season_flag days_since_quarter_end canary_noise_gaussian "
        "canary_noise_uniform canary_near_constant canary_constant canary_acausal_placebo "
        "bar_close_pos body_ratio upper_wick_ratio lower_wick_ratio close_vs_open_direction "
        "range_vs_atr overnight_gap range_efficiency open_ret intraday_ret open_vs_intraday "
        "ret_lag_1 ret_lag_2 ret_lag_3 ret_lag_fast ret_lag_mid ret_lag_slow range_position "
        "vol_ratio cci_fast cci_mid cci_slow aroon_fast aroon_slow ret_vol_ratio_fast "
        "parkinson_vol_velocity garman_klass_vol_velocity yang_zhang_vol_velocity "
        "momentum_vol_regime_product quarter_momentum_product variance_ratio_momentum_product "
        "informed_flow cmf ofi_div vol_body_product ret_vol_product_fast range_vol_product "
        "up_vol_body_diff vol_skew_product breakout_volume_product illiquidity_momentum_product "
        "efficiency_volume_product vix_z flight_quality yield_slope_z tip_tlt_ret_z hyg_lqd_ret_z "
        "sb_corr_fast sb_corr_slow sb_corr_z equity_beta_z rate_beta_z "
        "yield_slope_momentum_product vix_reversion_product"
    ).split()
)


# The cross-timeframe columns compute_batch reads from kernels: the three CTF pass-throughs and the
# three ret_div divergences.
_CROSS_TF_KERNEL_OUTPUTS: tuple[str, ...] = (
    "ctf_momentum",
    "ctf_vwap_align",
    "ctf_regime_align",
    "ret_div_5m_1h",
    "ret_div_1h_1d",
    "ret_div_1m_5m",
)
# The stateless structure columns compute_batch reads from kernels: the rolling POC, S/R, swing,
# trend and fib, and swing momentum columns, with the none-masks of the nullable ones. The
# cache-backed session VP, session levels and AMD kernels replay their own cache and are not run
# here (186-25 retires the cache-driven loop). Each group's outputs come from its one spec.
_STRUCTURE_KERNEL_OUTPUTS: tuple[str, ...] = (
    "_poc_price_rolling",
    *SR.outputs,
    *OB.outputs,
    *FVG.outputs,
    *SWEEP.outputs,
    *POOL.outputs,
    *ZONE.outputs,
    *BOS.outputs,
    *SWING_STRUCTURE.outputs,
    *SWING_MOMENTUM.outputs,
)


def _kernel_row(k: dict[str, np.ndarray], group: KeyGroup, i: int) -> dict[str, Any]:
    """Row i of a kernel-produced field group as the helper's dict (the group's public keys), None
    where the mask says so."""
    return {
        key: None if key in group.nullable and k[none_mask_name(key)][i] > 0.5 else float(k[key][i])
        for key in group.public_keys
    }


def _batch_kernel_inputs(
    row_ns: np.ndarray,
    opens: np.ndarray,
    highs: np.ndarray,
    lows: np.ndarray,
    closes: np.ndarray,
    volumes: np.ndarray,
    symbol: str,
    tf: str,
) -> dict[str, np.ndarray]:
    """Bar arrays plus the per-row `symbol` and `tf` external inputs for compute_kernels."""
    return {
        "ts": row_ns,
        "open": opens,
        "high": highs,
        "low": lows,
        "close": closes,
        "volume": volumes,
        "symbol": np.array([symbol] * len(row_ns), dtype=object),
        "tf": np.array([tf] * len(row_ns), dtype=object),
    }


def _none_if_nan(value: float) -> float | None:
    """A value that is NaN on the kernel grid is None in the FeatureVector."""
    return None if math.isnan(value) else float(value)


# The external-input alignments this module has a builder for: CONSTANT_PER_SERIES by
# `_batch_kernel_inputs` (the symbol), DAILY_ASOF_CLOSE by `_macro_kernel_inputs`,
# DAILY_REFERENCE_GRID by `kernels.macro.daily_reference_grid` (the daily-grid kernels run on it),
# HTF_ASOF_CLOSE and LTF_ASOF_BAR_START by `_cross_tf_kernel_inputs`. A kernel module
# declaring an external with any other Alignment is refused rather than fed an unaligned value.
_BUILT_ALIGNMENTS = frozenset(
    {
        Alignment.CONSTANT_PER_SERIES,
        Alignment.DAILY_ASOF_CLOSE,
        Alignment.DAILY_REFERENCE_GRID,
        Alignment.HTF_ASOF_CLOSE,
        Alignment.LTF_ASOF_BAR_START,
    }
)


def _require_buildable_externals() -> None:
    for external in default_registry().external_inputs:
        if external.alignment not in _BUILT_ALIGNMENTS:
            raise ValueError(
                f"external input {external.name!r} has alignment {external.alignment.name}, "
                "and feature_factory has no builder for it"
            )


# A row with no daily record available yet is missing data (no_fill): all-NaN, so the kernels
# emit NaN instead of a fabricated 0.0 z-score.
_MISSING_CROSS_ASSET = CrossAssetRecord(*([float("nan")] * len(CrossAssetRecord._fields)))


def _macro_kernel_inputs(
    row_ns: np.ndarray,
    symbol: str,
    tf: str,
    cache: FeatureCache,
    cross_asset_by_date: dict | None,
    beta_by_date: dict | None,
) -> dict[str, np.ndarray]:
    """The ten `ext_*` macro inputs on the row grid (None becomes NaN).

    Batch path: the daily records are aligned as-of the row's bar end with `daily_asof_indices`
    (a record dated d is available from the 16:00 ET close of d, so an intraday row on d reads
    d - 1; 1d rows read their own date). A row with no available record reads the default:
    NaN for the cross-asset fields, None (NaN) for the betas. Live path (cross_asset_by_date and
    beta_by_date None): the cache's values broadcast, with equity_beta_z None for SPY and
    rate_beta_z None for TLT (a self-regression is degenerate); the cache holds only
    already-closed daily values.
    """
    _require_buildable_externals()
    n = len(row_ns)
    out: dict[str, np.ndarray] = {}
    if cross_asset_by_date is not None:
        dates = sorted(cross_asset_by_date)
        index = daily_asof_indices(row_ns, tf, daily_close_availability(dates))
        records = [cross_asset_by_date[d] for d in dates]
        for name in RECORD_COLUMNS:
            # The default closes each column, so index -1 (no record available) reads it.
            column = [getattr(r, name) for r in records] + [getattr(_MISSING_CROSS_ASSET, name)]
            out[f"ext_{name}"] = np.array(column, dtype=np.float64)[index]
    else:
        for name in RECORD_COLUMNS:
            out[f"ext_{name}"] = np.full(n, getattr(cache, name), dtype=np.float64)
    if beta_by_date is not None:
        dates = sorted(beta_by_date)
        index = daily_asof_indices(row_ns, tf, daily_close_availability(dates))
        pairs = [beta_by_date[d] for d in dates] + [(None, None)]
        for position, name in enumerate(("ext_equity_beta_z", "ext_rate_beta_z")):
            column = [np.nan if p[position] is None else p[position] for p in pairs]
            out[name] = np.array(column, dtype=np.float64)[index]
    else:
        equity = None if symbol == "SPY" else cache.equity_beta_z
        rate = None if symbol == "TLT" else cache.rate_beta_z
        out["ext_equity_beta_z"] = np.full(n, np.nan if equity is None else equity)
        out["ext_rate_beta_z"] = np.full(n, np.nan if rate is None else rate)
    return out


def _cross_tf_kernel_inputs(
    row_ns: np.ndarray,
    tf: str,
    cache: FeatureCache,
    ctf_by_ts: CtfSeries | None,
    ltf_ret_by_ts: dict | None,
) -> dict[str, np.ndarray]:
    """The five cross-timeframe `ext_*` inputs on the row grid.

    Batch path (`ctf_by_ts` given): `ctf_row_inputs` looks each row up among the HTF values
    keyed by their bar's close. Live path: the cache's CTF values broadcast and the
    HTF return is NaN (the divergences have no live-path plumbing). `ext_ltf_last_log_ret` is the
    1m return taken at the row's bar start, NaN where the dict has none.
    """
    n = len(row_ns)
    if ctf_by_ts is not None:
        out = ctf_row_inputs(row_ns, ctf_by_ts)
    else:
        out = {
            "ext_ctf_momentum": np.full(n, cache.ctf_momentum, dtype=np.float64),
            "ext_ctf_vwap_align": np.full(n, cache.ctf_vwap_align, dtype=np.float64),
            "ext_ctf_regime_align": np.full(n, cache.ctf_regime_align, dtype=np.float64),
            "ext_htf_last_log_ret": np.full(n, np.nan),
        }
    # Same UTC-nanosecond convention as the CTF and macro paths: a naive timestamp is taken as UTC
    # on either side, so naive and aware inputs match identically.
    ltf = {bar_ts_ns(ts): value for ts, value in (ltf_ret_by_ts or {}).items()}
    out["ext_ltf_last_log_ret"] = np.array(
        [ltf.get(int(ns), np.nan) for ns in row_ns.tolist()], dtype=np.float64
    )
    return out


def _guard(v: float | None, fallback: float = 0.0) -> float | None:
    """Replace non-finite floats with fallback. Pass None through unchanged."""
    if v is None:
        return None
    return v if math.isfinite(v) else fallback


# Module-level substitution counter for the 10 Theory-Motivated Interaction
# compounds (Phase 151 Plan 06) ONLY -- not used by any of the ~190
# pre-existing fields, which stay on plain _guard(). Keyed by compound
# feature_name; incremented by _guard_counted() whenever that compound's
# product substitutes the 0.0 fallback for a non-finite value. Reset by
# _report_guard_counted_substitutions() after each report.
_GUARD_COUNTED_SUBSTITUTIONS: dict[str, int] = {}


def _guard_counted(v: float, name: str, inputs: Sequence[float] = ()) -> float:
    """Like _guard(v, fallback=0.0) but increments a named, observable counter.

    With `inputs` (the factors of the product), a non-finite product whose input is itself
    non-finite is missing data propagating (an early row with no cross-asset record yet), not
    a numerical anomaly: it is substituted the same 0.0 but not counted, so the tripwire
    counts only a product that is non-finite while every input is finite.

    Used exclusively by the 10 Theory-Motivated Interaction compounds (Phase
    151 Plan 06, todo -- see plan doc). Explicit range clipping was rejected
    at design time: a float64 product of two z-scores cannot reach ±inf short
    of roughly 1e154 per factor -- structurally unreachable for a real
    z-score -- so math.isfinite firing here is a tripwire against a genuine
    numerical anomaly, never a value-shaping clamp on an "extreme but valid"
    number. The counter exists so a firing tripwire is OBSERVABLE rather than
    a silent collapse (Codex code-review MEDIUM finding on the plain
    "substitute posinf/neginf with 0.0 via a bare numpy clamp call" idiom,
    which would substitute the same 0.0 with no trace at all) -- see
    _report_guard_counted_substitutions().
    """
    if math.isfinite(v):
        return v
    if not all(math.isfinite(x) for x in inputs):
        return 0.0
    _GUARD_COUNTED_SUBSTITUTIONS[name] = _GUARD_COUNTED_SUBSTITUTIONS.get(name, 0) + 1
    return 0.0


def _report_guard_counted_substitutions() -> None:
    """Emit ONE structured log line naming only non-zero-count compounds, then reset.

    Called exactly once per compute_batch() call (never per row -- CLAUDE.md's
    never-log-per-row-over-the-corpus rule; compute_batch() loops over up to
    36.7M rows in a full corpus pass). Emits nothing when every counter is
    zero, which is the expected case on real data given _guard_counted's
    near-unreachability. NOT called from compute() -- that function's own
    docstring purity contract is "zero IO"; compute() still calls
    _guard_counted() itself (a pure in-memory increment, not IO), but any
    live-path substitutions surface on the next compute_batch() report rather
    than logging per live bar.
    """
    fired = {name: count for name, count in _GUARD_COUNTED_SUBSTITUTIONS.items() if count > 0}
    if fired:
        _logger.warning("theory_interaction_guard_substitutions", substitutions=fired)
    _GUARD_COUNTED_SUBSTITUTIONS.clear()


def _series_last(arr: np.ndarray, fallback: float) -> float:
    """Safely extract the last element of a series array with fallback."""
    return float(arr[-1]) if len(arr) > 0 else fallback


def _build_feature_vector(
    *,
    momentum_z_fast: float,
    momentum_z_mid: float,
    range_position: float,
    bar_close_pos: float,
    gap_z: float,
    momentum_z_slow: float,
    momentum_reversal_z: float,
    informed_flow: float,
    volume_z: float,
    ofi_z: float,
    ofi_div: float,
    cvd_slope_z: float,
    cmf: float,
    rel_volume: float,
    vwap_dev_sigma: float,
    atr_z: float,
    vol_ratio: float,
    poc_dist_atr: float | None,
    va_position: float | None,
    sr_support_dist: float | None,
    sr_resist_dist: float | None,
    # Structural VP/SR (17, Phase 163 Plan 01). Defaulted to None (this is a
    # keyword-only function, `*,` above, so defaults can live anywhere in the
    # signature) -- same avoid-blast-radius-across-every-call-site rationale
    # as the canary defaults further below. Not computed by any caller yet;
    # Plan 02 wires real values in.
    nearest_hvn_above_dist_atr: float | None = None,
    nearest_hvn_below_dist_atr: float | None = None,
    nearest_lvn_above_dist_atr: float | None = None,
    nearest_lvn_below_dist_atr: float | None = None,
    price_in_value_area: float | None = None,
    in_lvn: float | None = None,
    va_width_atr: float | None = None,
    distance_to_vah_atr: float | None = None,
    distance_to_val_atr: float | None = None,
    nearest_hvn_dist_atr: float | None = None,
    poc_rolling_dist_atr: float | None = None,
    poc_session_rolling_divergence_atr: float | None = None,
    resistance_strength: float | None = None,
    support_strength: float | None = None,
    resistance_age_bars: float | None = None,
    support_age_bars: float | None = None,
    sr_level_count: float | None = None,
    hmm_regime_prob: float | None,
    hmm_entropy: float | None,
    hmm_duration: float | None,
    hurst: float,
    shannon: float,
    garch_ratio: float,
    hma_slope_z: float,
    adx: float,
    aroon_fast: float,
    aroon_slow: float,
    rsi_fast: float,
    rsi_mid: float,
    rsi_slow: float,
    cci_fast: float,
    cci_mid: float,
    cci_slow: float,
    vix_z: float,
    flight_quality: float,
    yield_slope_z: float,
    in_ny_session: float,
    in_london_kz: float,
    in_overlap: float,
    power_hour: float,
    opening_range: float,
    above_wk_vwap: float,
    dow_sin: float,
    dow_cos: float,
    month_position: float,
    quarter_position: float,
    days_to_month_end: float,
    quarter_cycle_sin: float,
    quarter_cycle_cos: float,
    tdom_sin: float,
    tdom_cos: float,
    minute_of_hour_sin: float,
    minute_of_hour_cos: float,
    ctf_momentum: float,
    ctf_vwap_align: float,
    ctf_regime_align: float,
    amihud_illiq_z: float,
    high_52w_dist: float,
    ret_skew_z: float,
    ret_acf1_z: float,
    body_ratio: float,
    upper_wick_ratio: float,
    lower_wick_ratio: float,
    range_vs_atr: float,
    close_vs_open_direction: float,
    overnight_gap: float,
    overnight_gap_z: float,
    range_efficiency: float,
    ret_lag_1: float,
    ret_lag_2: float,
    ret_lag_3: float,
    ret_lag_fast: float,
    ret_lag_mid: float,
    ret_lag_slow: float,
    open_ret: float,
    intraday_ret: float,
    open_vs_intraday: float,
    session_time_pos: float,
    hour_of_day_sin: float,
    hour_of_day_cos: float,
    week_of_month_sin: float,
    week_of_month_cos: float,
    day_of_month_sin: float,
    day_of_month_cos: float,
    week_of_year_sin: float,
    week_of_year_cos: float,
    month_sin: float,
    month_cos: float,
    vol_acceleration: float,
    dollar_vol_z: float,
    vol_range_ratio: float,
    vol_trend_ratio: float,
    up_vol_ratio_fast: float,
    up_vol_ratio_slow: float,
    vol_percentile: float,
    vol_persistence: float,
    vol_std_z: float,
    mfi_fast: float,
    mfi_slow: float,
    obv_z: float,
    dist_from_high_fast: float,
    dist_from_high_slow: float,
    dist_from_low_fast: float,
    dist_from_low_slow: float,
    range_pct_fast: float,
    range_pct_slow: float,
    stoch_k_fast: float,
    stoch_k_slow: float,
    price_percentile_fast: float,
    price_percentile_slow: float,
    efficiency_ratio_fast: float,
    efficiency_ratio_slow: float,
    ret_kurtosis_z_fast: float,
    ret_kurtosis_z_slow: float,
    ret_autocorr_1: float,
    ret_autocorr_5: float,
    updown_ratio_fast: float,
    updown_ratio_slow: float,
    streak_z: float,
    realized_var_ratio_fast: float,
    realized_var_ratio_slow: float,
    range_to_close: float,
    true_range_pct: float,
    vol_of_vol: float,
    high_low_corr: float,
    variance_ratio_fast: float,
    variance_ratio_slow: float,
    vol_asymmetry_z: float,
    bb_pct_b_fast: float,
    bb_pct_b_slow: float,
    hv_z_fast: float,
    hv_z_slow: float,
    hv_ratio: float,
    parkinson_vol_z: float,
    garman_klass_vol_z: float,
    yang_zhang_vol_z: float,
    parkinson_vol_velocity: float,
    garman_klass_vol_velocity: float,
    yang_zhang_vol_velocity: float,
    vol_velocity_z: float,
    intraday_noise_ratio: float,
    momentum_z_velocity_fast: float,
    momentum_z_velocity_mid: float,
    momentum_z_velocity_slow: float,
    vwap_dev_sigma_velocity: float,
    rsi_velocity_fast: float,
    rsi_velocity_mid: float,
    rsi_velocity_slow: float,
    ofi_z_velocity: float,
    cvd_slope_z_velocity: float,
    volume_z_velocity: float,
    bars_since_high_fast: float,
    bars_since_high_slow: float,
    bars_since_low_fast: float,
    bars_since_low_slow: float,
    bars_since_52w_high: float,
    bars_since_52w_low: float,
    bars_since_extreme_move_fast: float,
    bars_since_extreme_move_slow: float,
    bars_since_vol_spike_fast: float,
    bars_since_vol_spike_slow: float,
    abs_ret_autocorr_1: float,
    tip_tlt_ret_z: float,
    hyg_lqd_ret_z: float,
    sb_corr_fast: float,
    sb_corr_slow: float,
    sb_corr_z: float,
    equity_beta_z: float | None,
    rate_beta_z: float | None,
    ret_div_1m_5m: float | None,
    ret_div_5m_1h: float | None,
    ret_div_1h_1d: float | None,
    opex_flag: float,
    quad_witching_flag: float,
    earnings_season_flag: float,
    days_since_quarter_end: float,
    vol_body_product: float,
    ret_vol_product_fast: float,
    price_vol_corr_fast: float,
    price_vol_corr_slow: float,
    range_vol_product: float,
    up_vol_body_diff: float,
    ret_vol_ratio_fast: float,
    vol_skew_product: float,
    # Theory-Motivated Interactions (10, Phase 151 Plan 06). Raw (unguarded)
    # products -- _guard_counted() is applied once below, inside the
    # FeatureVector(...) construction, same single-application-point
    # discipline as every other field's plain _guard().
    momentum_vol_regime_product: float,
    momentum_trend_product: float,
    breakout_volume_product: float,
    reversion_hurst_product: float,
    quarter_momentum_product: float,
    variance_ratio_momentum_product: float,
    illiquidity_momentum_product: float,
    yield_slope_momentum_product: float,
    vix_reversion_product: float,
    efficiency_volume_product: float,
    # Swing/Fib/Trend/Session Structure (41, Phase 165 Plan 01). Defaulted to
    # None -- this is a keyword-only function (`*,` above) so defaults may
    # live anywhere in the signature. No caller supplies real values yet;
    # Plans 02-04 wire compute logic in and pass real values from both
    # compute() and compute_batch().
    swing_high_dist_atr: float | None = None,
    swing_low_dist_atr: float | None = None,
    swing_high_type: float | None = None,
    swing_low_type: float | None = None,
    swing_pattern: float | None = None,
    swing_high_age_bars: float | None = None,
    swing_low_age_bars: float | None = None,
    trend_direction: float | None = None,
    trend_strength: float | None = None,
    trend_leg_count: float | None = None,
    structure_integrity: float | None = None,
    price_position: float | None = None,
    trend_duration_bars: float | None = None,
    swing_amplitude_ratio: float | None = None,
    swing_amplitude_expanding: float | None = None,
    swing_amplitude_intensity: float | None = None,
    swing_velocity_bars: float | None = None,
    swing_velocity_bias: float | None = None,
    struct_energy: float | None = None,
    struct_accel_bias: float | None = None,
    swing_volume_confirmation: float | None = None,
    nearest_fib_ratio: float | None = None,
    nearest_fib_dist_atr: float | None = None,
    fib_cluster_strength: float | None = None,
    in_fib_discount_zone: float | None = None,
    prior_session_high_dist_atr: float | None = None,
    prior_session_low_dist_atr: float | None = None,
    prior_session_close_dist_atr: float | None = None,
    overnight_high_dist_atr: float | None = None,
    overnight_low_dist_atr: float | None = None,
    overnight_range_pct: float | None = None,
    opening_gap_pct: float | None = None,
    weekly_pivot_dist_atr: float | None = None,
    weekly_r1_dist_atr: float | None = None,
    weekly_r2_dist_atr: float | None = None,
    weekly_s1_dist_atr: float | None = None,
    weekly_s2_dist_atr: float | None = None,
    nearest_level_dist_atr: float | None = None,
    asian_session_high_dist_atr: float | None = None,
    asian_session_low_dist_atr: float | None = None,
    gap_filled: float | None = None,
    canary_noise_gaussian: float = 0.0,
    canary_noise_uniform: float = 0.0,
    canary_constant: float = _CANARY_CONSTANT_VALUE,
    canary_near_constant: float = _CANARY_CONSTANT_VALUE,
    canary_acausal_placebo: float = 0.0,
    # Smart Money Concepts (36, Phase 164 Plan 01). Defaulted to None -- this is
    # a keyword-only function (`*,` above) so defaults may live anywhere in the
    # signature. No caller supplies real values yet; Plan 02-04 wire compute
    # logic in and pass real values from both compute() and compute_batch().
    ob_bull_dist_atr: float | None = None,
    ob_bear_dist_atr: float | None = None,
    ob_strength: float | None = None,
    ob_mitigated_flag: float | None = None,
    breaker_dist_atr: float | None = None,
    breaker_block_active: float | None = None,
    ob_mitigation_pct: float | None = None,
    fvg_dist_atr: float | None = None,
    fvg_size_atr: float | None = None,
    fvg_open_count: float | None = None,
    sweep_detected: float | None = None,
    sweep_strength: float | None = None,
    reclaim_velocity: float | None = None,
    bars_since_last_sweep: float | None = None,
    bsl_dist_atr: float | None = None,
    ssl_dist_atr: float | None = None,
    bsl_touches: float | None = None,
    ssl_touches: float | None = None,
    pool_count: float | None = None,
    demand_dist_atr: float | None = None,
    supply_dist_atr: float | None = None,
    demand_freshness: float | None = None,
    supply_freshness: float | None = None,
    active_demand_zones: float | None = None,
    active_supply_zones: float | None = None,
    zone_friction_score: float | None = None,
    bos_strength: float | None = None,
    choch_strength: float | None = None,
    bos_direction: float | None = None,
    choch_direction: float | None = None,
    smc_trend_direction: float | None = None,
    bars_since_last_shift: float | None = None,
    amd_phase: float | None = None,
    amd_manipulation_detected: float | None = None,
    amd_distribution_direction: float | None = None,
    manip_strength: float | None = None,
) -> FeatureVector:
    return FeatureVector(
        momentum_z_fast=_guard(momentum_z_fast),
        momentum_z_mid=_guard(momentum_z_mid),
        range_position=_guard(range_position, 0.5),
        bar_close_pos=_guard(bar_close_pos, 0.5),
        gap_z=_guard(gap_z),
        momentum_z_slow=_guard(momentum_z_slow),
        momentum_reversal_z=_guard(momentum_reversal_z),
        informed_flow=_guard(informed_flow),
        volume_z=_guard(volume_z),
        ofi_z=_guard(ofi_z),
        ofi_div=_guard(ofi_div),
        cvd_slope_z=_guard(cvd_slope_z),
        cmf=_guard(cmf),
        rel_volume=_guard(rel_volume, 1.0),
        vwap_dev_sigma=_guard(vwap_dev_sigma),
        atr_z=_guard(atr_z),
        vol_ratio=_guard(vol_ratio, 1.0),
        poc_dist_atr=_guard(poc_dist_atr),
        va_position=_guard(va_position, 0.5),
        sr_support_dist=_guard(sr_support_dist),
        sr_resist_dist=_guard(sr_resist_dist),
        nearest_hvn_above_dist_atr=_guard(nearest_hvn_above_dist_atr),
        nearest_hvn_below_dist_atr=_guard(nearest_hvn_below_dist_atr),
        nearest_lvn_above_dist_atr=_guard(nearest_lvn_above_dist_atr),
        nearest_lvn_below_dist_atr=_guard(nearest_lvn_below_dist_atr),
        price_in_value_area=_guard(price_in_value_area),
        in_lvn=_guard(in_lvn),
        va_width_atr=_guard(va_width_atr),
        distance_to_vah_atr=_guard(distance_to_vah_atr),
        distance_to_val_atr=_guard(distance_to_val_atr),
        nearest_hvn_dist_atr=_guard(nearest_hvn_dist_atr),
        poc_rolling_dist_atr=_guard(poc_rolling_dist_atr),
        poc_session_rolling_divergence_atr=_guard(poc_session_rolling_divergence_atr),
        resistance_strength=_guard(resistance_strength),
        support_strength=_guard(support_strength),
        resistance_age_bars=_guard(resistance_age_bars),
        support_age_bars=_guard(support_age_bars),
        sr_level_count=_guard(sr_level_count),
        hmm_regime_prob=_guard(hmm_regime_prob),
        hmm_entropy=_guard(hmm_entropy),
        hmm_duration=_guard(hmm_duration),
        hurst=_guard(hurst, 0.5),
        shannon=_guard(shannon, 1.0),
        garch_ratio=_guard(garch_ratio, 1.0),
        hma_slope_z=_guard(hma_slope_z),
        adx=_guard(adx),
        aroon_fast=_guard(aroon_fast),
        aroon_slow=_guard(aroon_slow),
        rsi_fast=_guard(rsi_fast, 50.0),
        rsi_mid=_guard(rsi_mid, 50.0),
        rsi_slow=_guard(rsi_slow, 50.0),
        cci_fast=_guard(cci_fast),
        cci_mid=_guard(cci_mid),
        cci_slow=_guard(cci_slow),
        # Legacy no-fill gap (todo 463, plan 186-25): the kernels emit NaN for a row with no daily
        # record yet, and this guard turns it back into a fabricated 0.0 because FeatureVector
        # fields are non-nullable floats. 186-25 removes these guards on the rebuild path.
        vix_z=_guard(vix_z),
        flight_quality=_guard(flight_quality),
        yield_slope_z=_guard(yield_slope_z),
        in_ny_session=in_ny_session,
        in_london_kz=in_london_kz,
        in_overlap=in_overlap,
        power_hour=power_hour,
        opening_range=opening_range,
        above_wk_vwap=above_wk_vwap,
        dow_sin=dow_sin,
        dow_cos=dow_cos,
        month_position=month_position,
        quarter_position=_guard(quarter_position, 0.0),
        days_to_month_end=_guard(days_to_month_end, 0.0),
        quarter_cycle_sin=_guard(quarter_cycle_sin, 0.0),
        quarter_cycle_cos=_guard(quarter_cycle_cos, 1.0),
        tdom_sin=_guard(tdom_sin, 0.0),
        tdom_cos=_guard(tdom_cos, 1.0),
        minute_of_hour_sin=_guard(minute_of_hour_sin, 0.0),
        minute_of_hour_cos=_guard(minute_of_hour_cos, 1.0),
        ctf_momentum=_guard(ctf_momentum),
        ctf_vwap_align=_guard(ctf_vwap_align),
        ctf_regime_align=_guard(ctf_regime_align),
        amihud_illiq_z=_guard(amihud_illiq_z),
        high_52w_dist=_guard(high_52w_dist),
        ret_skew_z=_guard(ret_skew_z),
        ret_acf1_z=_guard(ret_acf1_z),
        body_ratio=_guard(body_ratio, 0.0),
        upper_wick_ratio=_guard(upper_wick_ratio, 0.5),
        lower_wick_ratio=_guard(lower_wick_ratio, 0.5),
        range_vs_atr=_guard(range_vs_atr, 0.0),
        close_vs_open_direction=close_vs_open_direction,
        overnight_gap=_guard(overnight_gap, 0.0),
        overnight_gap_z=_guard(overnight_gap_z, 0.0),
        range_efficiency=_guard(range_efficiency, 0.0),
        ret_lag_1=_guard(ret_lag_1, 0.0),
        ret_lag_2=_guard(ret_lag_2, 0.0),
        ret_lag_3=_guard(ret_lag_3, 0.0),
        ret_lag_fast=_guard(ret_lag_fast, 0.0),
        ret_lag_mid=_guard(ret_lag_mid, 0.0),
        ret_lag_slow=_guard(ret_lag_slow, 0.0),
        open_ret=_guard(open_ret, 0.0),
        intraday_ret=_guard(intraday_ret, 0.0),
        open_vs_intraday=_guard(open_vs_intraday, 0.0),
        session_time_pos=session_time_pos,
        hour_of_day_sin=hour_of_day_sin,
        hour_of_day_cos=hour_of_day_cos,
        week_of_month_sin=week_of_month_sin,
        week_of_month_cos=week_of_month_cos,
        day_of_month_sin=day_of_month_sin,
        day_of_month_cos=day_of_month_cos,
        week_of_year_sin=week_of_year_sin,
        week_of_year_cos=week_of_year_cos,
        month_sin=month_sin,
        month_cos=month_cos,
        vol_acceleration=_guard(vol_acceleration, 1.0),
        dollar_vol_z=_guard(dollar_vol_z, 0.0),
        vol_range_ratio=_guard(vol_range_ratio, 0.0),
        vol_trend_ratio=_guard(vol_trend_ratio, 1.0),
        up_vol_ratio_fast=_guard(up_vol_ratio_fast, 0.5),
        up_vol_ratio_slow=_guard(up_vol_ratio_slow, 0.5),
        vol_percentile=_guard(vol_percentile, 0.5),
        vol_persistence=_guard(vol_persistence, 0.0),
        vol_std_z=_guard(vol_std_z, 0.0),
        mfi_fast=_guard(mfi_fast, 50.0),
        mfi_slow=_guard(mfi_slow, 50.0),
        obv_z=_guard(obv_z, 0.0),
        dist_from_high_fast=_guard(dist_from_high_fast, 0.0),
        dist_from_high_slow=_guard(dist_from_high_slow, 0.0),
        dist_from_low_fast=_guard(dist_from_low_fast, 0.0),
        dist_from_low_slow=_guard(dist_from_low_slow, 0.0),
        range_pct_fast=_guard(range_pct_fast, 0.0),
        range_pct_slow=_guard(range_pct_slow, 0.0),
        stoch_k_fast=_guard(stoch_k_fast, 0.5),
        stoch_k_slow=_guard(stoch_k_slow, 0.5),
        price_percentile_fast=_guard(price_percentile_fast, 0.5),
        price_percentile_slow=_guard(price_percentile_slow, 0.5),
        efficiency_ratio_fast=_guard(efficiency_ratio_fast, 0.0),
        efficiency_ratio_slow=_guard(efficiency_ratio_slow, 0.0),
        ret_kurtosis_z_fast=_guard(ret_kurtosis_z_fast, 0.0),
        ret_kurtosis_z_slow=_guard(ret_kurtosis_z_slow, 0.0),
        ret_autocorr_1=_guard(ret_autocorr_1, 0.0),
        ret_autocorr_5=_guard(ret_autocorr_5, 0.0),
        updown_ratio_fast=_guard(updown_ratio_fast, 1.0),
        updown_ratio_slow=_guard(updown_ratio_slow, 1.0),
        streak_z=_guard(streak_z, 0.0),
        realized_var_ratio_fast=_guard(realized_var_ratio_fast, 1.0),
        realized_var_ratio_slow=_guard(realized_var_ratio_slow, 1.0),
        range_to_close=_guard(range_to_close, 0.0),
        true_range_pct=_guard(true_range_pct, 0.0),
        vol_of_vol=_guard(vol_of_vol, 0.0),
        high_low_corr=_guard(high_low_corr, 0.0),
        variance_ratio_fast=_guard(variance_ratio_fast, 1.0),
        variance_ratio_slow=_guard(variance_ratio_slow, 1.0),
        vol_asymmetry_z=_guard(vol_asymmetry_z, 0.0),
        bb_pct_b_fast=_guard(bb_pct_b_fast, 0.5),
        bb_pct_b_slow=_guard(bb_pct_b_slow, 0.5),
        hv_z_fast=_guard(hv_z_fast, 0.0),
        hv_z_slow=_guard(hv_z_slow, 0.0),
        hv_ratio=_guard(hv_ratio, 1.0),
        parkinson_vol_z=_guard(parkinson_vol_z, 0.0),
        garman_klass_vol_z=_guard(garman_klass_vol_z, 0.0),
        yang_zhang_vol_z=_guard(yang_zhang_vol_z, 0.0),
        parkinson_vol_velocity=_guard(parkinson_vol_velocity, 0.0),
        garman_klass_vol_velocity=_guard(garman_klass_vol_velocity, 0.0),
        yang_zhang_vol_velocity=_guard(yang_zhang_vol_velocity, 0.0),
        vol_velocity_z=_guard(vol_velocity_z, 0.0),
        intraday_noise_ratio=_guard(intraday_noise_ratio, 1.0),
        momentum_z_velocity_fast=_guard(momentum_z_velocity_fast, 0.0),
        momentum_z_velocity_mid=_guard(momentum_z_velocity_mid, 0.0),
        momentum_z_velocity_slow=_guard(momentum_z_velocity_slow, 0.0),
        vwap_dev_sigma_velocity=_guard(vwap_dev_sigma_velocity, 0.0),
        rsi_velocity_fast=_guard(rsi_velocity_fast, 0.0),
        rsi_velocity_mid=_guard(rsi_velocity_mid, 0.0),
        rsi_velocity_slow=_guard(rsi_velocity_slow, 0.0),
        ofi_z_velocity=_guard(ofi_z_velocity, 0.0),
        cvd_slope_z_velocity=_guard(cvd_slope_z_velocity, 0.0),
        volume_z_velocity=_guard(volume_z_velocity, 0.0),
        bars_since_high_fast=_guard(bars_since_high_fast, 0.0),
        bars_since_high_slow=_guard(bars_since_high_slow, 0.0),
        bars_since_low_fast=_guard(bars_since_low_fast, 0.0),
        bars_since_low_slow=_guard(bars_since_low_slow, 0.0),
        bars_since_52w_high=_guard(bars_since_52w_high, 0.0),
        bars_since_52w_low=_guard(bars_since_52w_low, 0.0),
        bars_since_extreme_move_fast=_guard(bars_since_extreme_move_fast, 0.0),
        bars_since_extreme_move_slow=_guard(bars_since_extreme_move_slow, 0.0),
        bars_since_vol_spike_fast=_guard(bars_since_vol_spike_fast, 0.0),
        bars_since_vol_spike_slow=_guard(bars_since_vol_spike_slow, 0.0),
        abs_ret_autocorr_1=_guard(abs_ret_autocorr_1, 0.0),
        # Same legacy no-fill gap as vix_z above (todo 463, plan 186-25): NaN becomes 0.0 here.
        tip_tlt_ret_z=_guard(tip_tlt_ret_z, 0.0),
        hyg_lqd_ret_z=_guard(hyg_lqd_ret_z, 0.0),
        sb_corr_fast=_guard(sb_corr_fast, 0.0),
        sb_corr_slow=_guard(sb_corr_slow, 0.0),
        sb_corr_z=_guard(sb_corr_z, 0.0),
        equity_beta_z=_guard(equity_beta_z),
        rate_beta_z=_guard(rate_beta_z),
        ret_div_1m_5m=_guard(ret_div_1m_5m),
        ret_div_5m_1h=_guard(ret_div_5m_1h),
        ret_div_1h_1d=_guard(ret_div_1h_1d),
        opex_flag=_guard(opex_flag, 0.0),
        quad_witching_flag=_guard(quad_witching_flag, 0.0),
        earnings_season_flag=_guard(earnings_season_flag, 0.0),
        days_since_quarter_end=_guard(days_since_quarter_end, 0.0),
        vol_body_product=_guard(vol_body_product, 0.0),
        ret_vol_product_fast=_guard(ret_vol_product_fast, 0.0),
        price_vol_corr_fast=_guard(price_vol_corr_fast, 0.0),
        price_vol_corr_slow=_guard(price_vol_corr_slow, 0.0),
        range_vol_product=_guard(range_vol_product, 0.0),
        up_vol_body_diff=_guard(up_vol_body_diff, 0.0),
        ret_vol_ratio_fast=_guard(ret_vol_ratio_fast, 0.0),
        vol_skew_product=_guard(vol_skew_product, 0.0),
        momentum_vol_regime_product=_guard_counted(
            momentum_vol_regime_product, "momentum_vol_regime_product"
        ),
        momentum_trend_product=_guard_counted(momentum_trend_product, "momentum_trend_product"),
        breakout_volume_product=_guard_counted(breakout_volume_product, "breakout_volume_product"),
        reversion_hurst_product=_guard_counted(reversion_hurst_product, "reversion_hurst_product"),
        quarter_momentum_product=_guard_counted(
            quarter_momentum_product, "quarter_momentum_product"
        ),
        variance_ratio_momentum_product=_guard_counted(
            variance_ratio_momentum_product, "variance_ratio_momentum_product"
        ),
        illiquidity_momentum_product=_guard_counted(
            illiquidity_momentum_product, "illiquidity_momentum_product"
        ),
        yield_slope_momentum_product=_guard_counted(
            yield_slope_momentum_product,
            "yield_slope_momentum_product",
            inputs=(yield_slope_z, momentum_z_fast),
        ),
        vix_reversion_product=_guard_counted(
            vix_reversion_product,
            "vix_reversion_product",
            inputs=(vix_z, momentum_reversal_z),
        ),
        efficiency_volume_product=_guard_counted(
            efficiency_volume_product, "efficiency_volume_product"
        ),
        swing_high_dist_atr=_guard(swing_high_dist_atr),
        swing_low_dist_atr=_guard(swing_low_dist_atr),
        swing_high_type=_guard(swing_high_type),
        swing_low_type=_guard(swing_low_type),
        swing_pattern=_guard(swing_pattern),
        swing_high_age_bars=_guard(swing_high_age_bars),
        swing_low_age_bars=_guard(swing_low_age_bars),
        trend_direction=_guard(trend_direction),
        trend_strength=_guard(trend_strength),
        trend_leg_count=_guard(trend_leg_count),
        structure_integrity=_guard(structure_integrity),
        price_position=_guard(price_position),
        trend_duration_bars=_guard(trend_duration_bars),
        swing_amplitude_ratio=_guard(swing_amplitude_ratio),
        swing_amplitude_expanding=_guard(swing_amplitude_expanding),
        swing_amplitude_intensity=_guard(swing_amplitude_intensity),
        swing_velocity_bars=_guard(swing_velocity_bars),
        swing_velocity_bias=_guard(swing_velocity_bias),
        struct_energy=_guard(struct_energy),
        struct_accel_bias=_guard(struct_accel_bias),
        swing_volume_confirmation=_guard(swing_volume_confirmation),
        nearest_fib_ratio=_guard(nearest_fib_ratio),
        nearest_fib_dist_atr=_guard(nearest_fib_dist_atr),
        fib_cluster_strength=_guard(fib_cluster_strength),
        in_fib_discount_zone=_guard(in_fib_discount_zone),
        prior_session_high_dist_atr=_guard(prior_session_high_dist_atr),
        prior_session_low_dist_atr=_guard(prior_session_low_dist_atr),
        prior_session_close_dist_atr=_guard(prior_session_close_dist_atr),
        overnight_high_dist_atr=_guard(overnight_high_dist_atr),
        overnight_low_dist_atr=_guard(overnight_low_dist_atr),
        overnight_range_pct=_guard(overnight_range_pct),
        opening_gap_pct=_guard(opening_gap_pct),
        weekly_pivot_dist_atr=_guard(weekly_pivot_dist_atr),
        weekly_r1_dist_atr=_guard(weekly_r1_dist_atr),
        weekly_r2_dist_atr=_guard(weekly_r2_dist_atr),
        weekly_s1_dist_atr=_guard(weekly_s1_dist_atr),
        weekly_s2_dist_atr=_guard(weekly_s2_dist_atr),
        nearest_level_dist_atr=_guard(nearest_level_dist_atr),
        asian_session_high_dist_atr=_guard(asian_session_high_dist_atr),
        asian_session_low_dist_atr=_guard(asian_session_low_dist_atr),
        gap_filled=_guard(gap_filled),
        canary_noise_gaussian=_guard(canary_noise_gaussian, 0.0),
        canary_noise_uniform=_guard(canary_noise_uniform, 0.0),
        canary_constant=_guard(canary_constant, _CANARY_CONSTANT_VALUE),
        canary_near_constant=_guard(canary_near_constant, _CANARY_CONSTANT_VALUE),
        canary_acausal_placebo=_guard(canary_acausal_placebo, 0.0),
        ob_bull_dist_atr=_guard(ob_bull_dist_atr),
        ob_bear_dist_atr=_guard(ob_bear_dist_atr),
        ob_strength=_guard(ob_strength),
        ob_mitigated_flag=_guard(ob_mitigated_flag),
        breaker_dist_atr=_guard(breaker_dist_atr),
        breaker_block_active=_guard(breaker_block_active),
        ob_mitigation_pct=_guard(ob_mitigation_pct),
        fvg_dist_atr=_guard(fvg_dist_atr),
        fvg_size_atr=_guard(fvg_size_atr),
        fvg_open_count=_guard(fvg_open_count),
        sweep_detected=_guard(sweep_detected),
        sweep_strength=_guard(sweep_strength),
        reclaim_velocity=_guard(reclaim_velocity),
        bars_since_last_sweep=_guard(bars_since_last_sweep),
        bsl_dist_atr=_guard(bsl_dist_atr),
        ssl_dist_atr=_guard(ssl_dist_atr),
        bsl_touches=_guard(bsl_touches),
        ssl_touches=_guard(ssl_touches),
        pool_count=_guard(pool_count),
        demand_dist_atr=_guard(demand_dist_atr),
        supply_dist_atr=_guard(supply_dist_atr),
        demand_freshness=_guard(demand_freshness),
        supply_freshness=_guard(supply_freshness),
        active_demand_zones=_guard(active_demand_zones),
        active_supply_zones=_guard(active_supply_zones),
        zone_friction_score=_guard(zone_friction_score),
        bos_strength=_guard(bos_strength),
        choch_strength=_guard(choch_strength),
        bos_direction=_guard(bos_direction),
        choch_direction=_guard(choch_direction),
        smc_trend_direction=_guard(smc_trend_direction),
        bars_since_last_shift=_guard(bars_since_last_shift),
        amd_phase=_guard(amd_phase),
        amd_manipulation_detected=_guard(amd_manipulation_detected),
        amd_distribution_direction=_guard(amd_distribution_direction),
        manip_strength=_guard(manip_strength),
        momentum_rank_z=None,
        volume_rank_z=None,
        volatility_rank_z=None,
    )


def _merge_structural_fields(
    vp_extra: dict[str, float | None],
    sr_fields: dict[str, float | None],
    swing_fields: dict[str, float | None | list[int] | int],
    trend_fields: dict[str, float | None],
    swing_momentum_fields: dict[str, float | None],
    fib_fields: dict[str, float | None],
    session_level_fields: dict[str, float | None],
    ob_fields: dict[str, float],
    fvg_fields: dict[str, float],
    sweep_fields: dict[str, float],
    pool_fields: dict[str, float],
    zone_fields: dict[str, float],
    bos_fields: dict[str, float],
    amd_fields: dict[str, float],
) -> dict[str, float | None]:
    """Merge the 14 Phase 163-165 structural/SMC field dicts into one.

    Both compute() and compute_batch() call each _compute_*/_derive_*
    helper above (identically -- they differ only in how input arrays are
    pre-sliced) and then need to relay every returned field into
    _build_feature_vector. Doing that merge here once, shared by both call
    sites, replaces what used to be a ~90-line unpack-into-named-locals-
    then-repack-as-kwargs block duplicated at each site -- the actual
    maintenance risk that duplication carried: a future field added to one
    of these dicts but not relayed at both sites would silently default to
    None in _build_feature_vector rather than error, since it is a
    keyword-only function with per-field None defaults.

    swing_fields/fvg_fields/pool_fields are filtered through their
    *_OUTPUT_KEYS allowlist first -- those three also carry in-memory-only
    intermediates (raw swing prices/indices, fvg_midpoint, price_in_premium)
    that must never reach _build_feature_vector.
    """
    return {
        **vp_extra,
        **sr_fields,
        **{k: swing_fields[k] for k in _SWING_STRUCTURE_OUTPUT_KEYS},
        **trend_fields,
        **swing_momentum_fields,
        **fib_fields,
        **session_level_fields,
        **ob_fields,
        **{k: fvg_fields[k] for k in _FVG_OUTPUT_KEYS},
        **sweep_fields,
        **{k: pool_fields[k] for k in _POOL_OUTPUT_KEYS},
        **zone_fields,
        **bos_fields,
        **amd_fields,
    }


# ---------------------------------------------------------------------------
# FeatureFactory — stateless pure-function class
# ---------------------------------------------------------------------------


class FeatureFactory:
    """Pure-function feature library. Stateless: no constructor, no stored config.

    The only public API is compute(). All bar-level rolling computations are
    performed directly from the `bars` array (the full history provided by the
    caller), making compute() deterministic for identical inputs with no
    external accumulator state. Regime/session/CTF state lives in FeatureCache.
    """

    @staticmethod
    def compute(
        bars: list[dict],
        symbol: str,
        tf: str,
        cache: FeatureCache,
        config: FeatureFactoryConfig,
    ) -> FeatureVector:
        """Compute all 300 FeatureVector primitives from bars + cache + config.

        PURE FUNCTION: no IO, no ConfigService.get(), no DB reads, no Kafka.
        All tunable numerics come from the config argument (SC-9).
        Cold-start (insufficient history) yields 0.0 for continuous features.
        Deterministic: identical (bars, symbol, tf, cache, config) -> identical output.

        Parameters
        ----------
        bars: Full bar history (list of OHLCV dicts with 'open','high','low',
              'close','volume','ts' keys). Must have at least 2 entries.
        symbol: Instrument symbol (e.g. 'SPY'). Used only for type annotation.
        tf: Timeframe string (e.g. '1m', '5m', '1d').
        cache: Mutable FeatureCache holding regime/session/CTF state.
        config: Frozen FeatureFactoryConfig with all APR-backed parameters.

        Returns
        -------
        FeatureVector with all 300 fields populated -- most set to finite
        floats, but 85 are `float | None` by design (41 Phase 165 Swing/Fib
        + 44 optional cross-sectional/canary/SMC placeholders); see the
        FeatureVector class docstring for the full breakdown.
        """
        if len(bars) < 2:
            # Phase 151 Plan 05: bar_ts, when available (len(bars) == 1), is
            # threaded through so opex_flag/quad_witching_flag compute real
            # values even at cold start -- both need only bar_ts, not history.
            # Phase 176 Plan 03: config is also threaded through so
            # earnings_season_flag can resolve its APR window even at cold
            # start.
            _cold_start_bar_ts = bars[-1]["ts"] if bars else None
            return _cold_start_vector(cache, tf, _cold_start_bar_ts, config)

        opens = np.array([b["open"] for b in bars], dtype=float)
        highs = np.array([b["high"] for b in bars], dtype=float)
        lows = np.array([b["low"] for b in bars], dtype=float)
        closes = np.array([b["close"] for b in bars], dtype=float)
        volumes = np.array([b["volume"] for b in bars], dtype=float)

        last = bars[-1]
        open_ = float(last["open"])
        high_ = float(last["high"])
        low_ = float(last["low"])
        close_ = float(last["close"])
        bar_ts = last["ts"]
        if isinstance(bar_ts, datetime) and bar_ts.tzinfo is None:
            bar_ts = bar_ts.replace(tzinfo=UTC)

        s = _precompute_series(opens, highs, lows, closes, volumes, config)

        atr_val = float(s.atr_raw[-1]) if len(s.atr_raw) > 0 else 0.0

        range_bars = min(config.momentum_window_mid, len(bars))
        range_position_val = _range_position(close_, highs[-range_bars:], lows[-range_bars:])

        if tf == "1d":
            vp_extra: dict[str, float | None] = dict(_NEUTRAL_VP_EXTRA)
        else:
            _roll_window = config.session_vp_rolling_window
            poc_price_rolling = _rolling_poc_price(
                highs[-_roll_window:],
                lows[-_roll_window:],
                closes[-_roll_window:],
                volumes[-_roll_window:],
                config,
            )
            vp_extra = _derive_session_vp(cache, close_, atr_val, poc_price_rolling, config)

        # S/R (Phase 163 Plan 03): stateless inline pivot-clustering, unlike VP,
        # is valid for tf=='1d' too (no single-daily-bar-has-no-distribution
        # constraint applies) -- always computed, using the tf-specific
        # lookback from config (D-19).
        _sr_fields = _compute_sr_dist_atr(highs, lows, close_, atr_val, volumes, tf, config)

        # Swing / Trend Structure (Phase 165 Plan 02): single shared
        # find_peaks/find_troughs pass (D-06) -- _swing_fields carries the
        # raw swing_high_indices/swing_low_indices/n_bars intermediates that
        # _compute_trend_structure reuses instead of re-detecting pivots.
        _swing_fields = _compute_swing_structure(highs, lows, close_, atr_val, config)
        _trend_fields = _compute_trend_structure(
            highs, lows, close_, atr_val, _swing_fields, config
        )

        # Swing Momentum / Fibonacci Zones (Phase 165 Plan 03): swing
        # momentum reads its own self-contained confirm-window extreme
        # detector (D-06 Finding B), not find_peaks/find_troughs; fibonacci
        # zones consumes _swing_fields' swing_high_price/swing_low_price
        # in-memory intermediates directly -- no cross-plugin fallback (D-05).
        _swing_momentum_fields = _compute_swing_momentum(highs, lows, volumes, config)
        _fib_fields = _compute_fib_zones(close_, atr_val, _swing_fields, config)

        # Session Levels (Phase 165 Plan 05): the last 16 Phase 165 fields,
        # derived from FeatureCache's raw session/overnight/Asian-block/
        # prior-completed-week state. The caller (e.g. feature_vector_pipeline
        # .py's _process_bar_compute) is required to call
        # cache.update_session_levels(...) before compute() runs -- this
        # function only reads the cache, never mutates it.
        _session_level_fields = _derive_session_levels(cache, close_, atr_val, tf, config)

        # Smart Money Concepts (Phase 164 Plan 02): Order Blocks + stateless
        # Breaker/Mitigation, single pure pass per RESEARCH.md's mandated
        # order_blocks -> breaker/mitigation sequencing. Plans 03-04 append
        # fair_value_gap/liquidity_sweeps/liquidity_pools/supply_demand_zones/
        # bos_choch/amd_cycle after this block, in that order.
        _ob_fields = _compute_order_blocks(
            opens, highs, lows, closes, volumes, close_, atr_val, config
        )

        # Smart Money Concepts (Phase 164 Plan 03): Fair Value Gaps, then
        # Liquidity Sweeps, then Liquidity Pools (single-tf descoped), per
        # RESEARCH.md's mandated sequencing. fvg_midpoint/price_in_premium
        # are staged as in-pass locals (not persisted) for Plan 04's
        # supply/demand-zones block.
        _fvg_fields = _compute_fvg(highs, lows, closes, close_, atr_val, config)
        _fvg_midpoint = _fvg_fields["fvg_midpoint"]  # Plan 04 zones local, not persisted

        _sweep_fields = _compute_liquidity_sweeps(highs, lows, closes, close_, atr_val, config)

        _pool_fields = _compute_liquidity_pools(highs, lows, closes, close_, atr_val, config)
        _price_in_premium = _pool_fields["price_in_premium"]  # Plan 04 zones local, not persisted

        # Smart Money Concepts (Phase 164 Plan 04): Supply/Demand Zones (soft-
        # consumes _fvg_midpoint/_price_in_premium from the FVG/pools block
        # above, per RESEARCH.md's mandated ordering), then BOS/CHoCH, then
        # AMD Cycle (reads FeatureCache's overnight-range state -- populated
        # by the caller's update_overnight_range(), never recomputed here).
        _zone_fields = _compute_supply_demand_zones(
            opens,
            highs,
            lows,
            closes,
            close_,
            atr_val,
            config,
            _fvg_midpoint,
            _price_in_premium,
        )

        _bos_fields = _compute_bos_choch(highs, lows, closes, close_, atr_val, config)
        _amd_fields = _derive_amd_cycle(cache, bar_ts, config)

        _structural_fields = _merge_structural_fields(
            vp_extra,
            _sr_fields,
            _swing_fields,
            _trend_fields,
            _swing_momentum_fields,
            _fib_fields,
            _session_level_fields,
            _ob_fields,
            _fvg_fields,
            _sweep_fields,
            _pool_fields,
            _zone_fields,
            _bos_fields,
            _amd_fields,
        )

        _dow = _dow_encoding(bar_ts)
        _qc = _quarter_cycle_encoding(bar_ts)
        _tdom = _tdom_encoding(bar_ts)
        _moh = _minute_of_hour_encoding(bar_ts)

        # Renaissance Primitives (Phase 142.5 Plan 01)
        prev_close_ = float(closes[-2])
        body_ratio_val = _body_ratio(open_, high_, low_, close_)
        upper_wick_ratio_val = _upper_wick_ratio(open_, high_, low_, close_)
        lower_wick_ratio_val = _lower_wick_ratio(open_, high_, low_, close_)
        range_vs_atr_val = _range_vs_atr(
            high_, low_, atr_val, close_, config.atr_normalization_min_pct
        )
        close_vs_open_direction_val = _close_vs_open_direction(open_, close_)
        overnight_gap_val = _overnight_gap(open_, prev_close_)
        overnight_gap_z_val = _overnight_gap_z(opens, closes, config.overnight_gap_window)
        range_efficiency_val = _range_efficiency(close_, prev_close_, high_, low_)
        ret_lag_1_val = _ret_lag_1(closes)
        ret_lag_2_val = _ret_lag_2(closes)
        ret_lag_3_val = _ret_lag_3(closes)
        ret_lag_fast_val = _ret_lag_fast(closes, config.ret_lag_fast)
        ret_lag_mid_val = _ret_lag_mid(closes, config.ret_lag_mid)
        ret_lag_slow_val = _ret_lag_slow(closes, config.ret_lag_slow)
        open_ret_val = _open_ret(open_, prev_close_)
        intraday_ret_val = _intraday_ret(close_, open_)
        open_vs_intraday_val = _open_vs_intraday(open_ret_val, intraday_ret_val)
        session_time_pos_val = _session_time_pos(bar_ts, config)

        # Renaissance Primitives (Phase 142.5 Plan 02) — temporal coordinates
        # are O(1) pure functions of bar_ts; volume structure reads the
        # precomputed series (s.*) built once above.
        hour_of_day_sin_val = _hour_of_day_sin(bar_ts)
        hour_of_day_cos_val = _hour_of_day_cos(bar_ts)
        week_of_month_sin_val = _week_of_month_sin(bar_ts)
        week_of_month_cos_val = _week_of_month_cos(bar_ts)
        day_of_month_sin_val = _day_of_month_sin(bar_ts)
        day_of_month_cos_val = _day_of_month_cos(bar_ts)
        week_of_year_sin_val = _week_of_year_sin(bar_ts)
        week_of_year_cos_val = _week_of_year_cos(bar_ts)
        month_sin_val = _month_sin(bar_ts)
        month_cos_val = _month_cos(bar_ts)

        # Renaissance Primitives (Phase 142.5 Plan 05.5) — price-volume
        # interactions. Baseline scalars (volume_z, atr_z, ret_skew_z,
        # up_vol_ratio_fast) captured into named locals so the 6 window-free
        # combinators can reuse them without recomputation; the 2 rolling
        # correlations read the precomputed series built above (s.*),
        # guaranteeing exact parity with compute_batch()'s indexing.
        volume_z_val = _series_last(s.volume_z, 0.0)
        atr_z_val = _series_last(s.atr_z, 0.0)
        ret_skew_z_val = _series_last(s.ret_skew_z, 0.0)
        up_vol_ratio_fast_val = _series_last(s.up_vol_ratio_fast, 0.5)
        vol_body_product_val = _product(body_ratio_val, volume_z_val)
        ret_vol_product_fast_val = _product(ret_lag_fast_val, volume_z_val)
        range_vol_product_val = _product(range_vs_atr_val, volume_z_val)
        up_vol_body_diff_val = _up_vol_body_diff(up_vol_ratio_fast_val, body_ratio_val)
        ret_vol_ratio_fast_val = _ret_vol_ratio(ret_lag_fast_val, atr_z_val)
        vol_skew_product_val = _product(ret_skew_z_val, volume_z_val)
        price_vol_corr_fast_val = _series_last(s.price_vol_corr_fast, 0.0)
        price_vol_corr_slow_val = _series_last(s.price_vol_corr_slow, 0.0)

        # Theory-Motivated Interactions (Phase 151 Plan 06). The 13 distinct
        # parent scalars are captured into named locals -- same rationale as
        # the block above (volume_z_val etc.) -- so both their ORIGINAL field
        # kwarg below and each compound reusing them here compute exactly
        # once, never twice. Mirrors compute_batch()'s already-bound _val
        # locals for the same 13 names.
        momentum_z_fast_val = _series_last(s.momentum_z_fast, 0.0)
        momentum_reversal_z_val = _series_last(s.momentum_reversal_z, 0.0)
        adx_val = cache.adx
        hurst_val = cache.hurst
        hv_ratio_val = _series_last(s.hv_ratio, 1.0)
        variance_ratio_fast_val = _series_last(s.variance_ratio_fast, 1.0)
        efficiency_ratio_fast_val = _series_last(s.efficiency_ratio_fast, 0.0)
        dist_from_high_fast_val = _series_last(s.dist_from_high_fast, 0.0)
        amihud_illiq_z_val = _series_last(s.amihud_illiq_z, 0.0)
        quarter_position_val = _quarter_position(bar_ts)
        vix_z_val = cache.vix_z
        yield_slope_z_val = cache.yield_slope_z

        momentum_vol_regime_product_val = momentum_z_fast_val * hv_ratio_val
        momentum_trend_product_val = momentum_z_fast_val * adx_val
        breakout_volume_product_val = dist_from_high_fast_val * volume_z_val
        reversion_hurst_product_val = momentum_reversal_z_val * hurst_val
        quarter_momentum_product_val = quarter_position_val * momentum_z_fast_val
        variance_ratio_momentum_product_val = variance_ratio_fast_val * momentum_z_fast_val
        illiquidity_momentum_product_val = amihud_illiq_z_val * momentum_z_fast_val
        yield_slope_momentum_product_val = yield_slope_z_val * momentum_z_fast_val
        vix_reversion_product_val = vix_z_val * momentum_reversal_z_val
        efficiency_volume_product_val = efficiency_ratio_fast_val * volume_z_val

        # Canary / Control Predictors (Phase 143.1 Plan 02). The acausal
        # placebo has no future data in this live single-bar path by
        # definition (closes only holds history up to and including the
        # current bar) -- _canary_acausal_placebo() naturally returns 0.0
        # here since i+2 is always out of bounds; the genuine forward-shifted
        # leak is only exercisable in compute_batch() (full-history backfill).
        canary_noise_gaussian_val = _canary_noise_gaussian(bar_ts, symbol, config.canary_rng_seed)
        canary_noise_uniform_val = _canary_noise_uniform(bar_ts, symbol, config.canary_rng_seed)
        canary_near_constant_val = _canary_near_constant(bar_ts, symbol, config.canary_rng_seed)
        canary_acausal_placebo_val = _canary_acausal_placebo(closes, len(closes) - 1)

        return _build_feature_vector(
            momentum_z_fast=momentum_z_fast_val,
            momentum_z_mid=_series_last(s.momentum_z_mid, 0.0),
            range_position=range_position_val,
            bar_close_pos=_bar_close_pos(high_, low_, close_),
            gap_z=_series_last(s.gap_z, 0.0),
            momentum_z_slow=_series_last(s.momentum_z_slow, 0.0),
            momentum_reversal_z=momentum_reversal_z_val,
            informed_flow=_informed_flow(open_, close_, atr_val, config.atr_normalization_min_pct),
            volume_z=volume_z_val,
            ofi_z=_series_last(s.ofi_z, 0.0),
            ofi_div=_series_last(s.ofi_z, 0.0) - _series_last(s.momentum_z_fast, 0.0),
            cvd_slope_z=_series_last(s.cvd_slope_z, 0.0),
            cmf=_cmf(highs, lows, closes, volumes, config.cmf_period),
            rel_volume=_series_last(s.rel_volume, 1.0),
            vwap_dev_sigma=_series_last(s.vwap_dev_sigma, 0.0),
            atr_z=atr_z_val,
            vol_ratio=_vol_ratio(closes, config.vol_short_bars, config.vol_long_bars),
            **_structural_fields,
            # regime_writer.py is the sole writer of these 3 columns (todo 207,
            # 2026-07-30) -- FeatureCache's inline K=3 forward-filter HMM
            # (cache.hmm_regime_prob/hmm_entropy/hmm_duration) has zero live
            # consumer of its own once this FeatureVector stops echoing it, so
            # persisting a value here only recreated the two-model column
            # collision regime_writer's fitted K=5 HMM already owns. None matches
            # how `regime` itself is already always None from every compute path.
            hmm_regime_prob=None,
            hmm_entropy=None,
            hmm_duration=None,
            hurst=hurst_val,
            shannon=cache.shannon,
            garch_ratio=cache.garch_ratio,
            hma_slope_z=cache.hma_slope_z,
            adx=adx_val,
            aroon_fast=_aroon_osc(highs, lows, config.aroon_fast_period),
            aroon_slow=_aroon_osc(highs, lows, config.aroon_slow_period),
            rsi_fast=_series_last(s.rsi_fast, 50.0),
            rsi_mid=_series_last(s.rsi_mid, 50.0),
            rsi_slow=_series_last(s.rsi_slow, 50.0),
            cci_fast=_cci(highs, lows, closes, config.cci_fast_period),
            cci_mid=_cci(highs, lows, closes, config.cci_mid_period),
            cci_slow=_cci(highs, lows, closes, config.cci_slow_period),
            vix_z=vix_z_val,
            flight_quality=cache.flight_quality,
            yield_slope_z=yield_slope_z_val,
            in_ny_session=_in_ny_session(bar_ts, config),
            in_london_kz=_in_london_kz(bar_ts, config),
            in_overlap=_in_overlap(bar_ts, config),
            power_hour=_power_hour(bar_ts, config),
            opening_range=_opening_range(bar_ts, config),
            above_wk_vwap=cache.above_wk_vwap,
            dow_sin=_dow[0],
            dow_cos=_dow[1],
            month_position=_month_position(bar_ts),
            quarter_position=quarter_position_val,
            days_to_month_end=_days_to_month_end_fraction(bar_ts),
            quarter_cycle_sin=_qc[0],
            quarter_cycle_cos=_qc[1],
            tdom_sin=_tdom[0],
            tdom_cos=_tdom[1],
            minute_of_hour_sin=_moh[0],
            minute_of_hour_cos=_moh[1],
            ctf_momentum=cache.ctf_momentum,
            ctf_vwap_align=cache.ctf_vwap_align,
            ctf_regime_align=cache.ctf_regime_align,
            amihud_illiq_z=amihud_illiq_z_val,
            high_52w_dist=_series_last(s.high_52w_dist, 0.0),
            ret_skew_z=ret_skew_z_val,
            ret_acf1_z=_series_last(s.ret_acf1_z, 0.0),
            body_ratio=body_ratio_val,
            upper_wick_ratio=upper_wick_ratio_val,
            lower_wick_ratio=lower_wick_ratio_val,
            range_vs_atr=range_vs_atr_val,
            close_vs_open_direction=close_vs_open_direction_val,
            overnight_gap=overnight_gap_val,
            overnight_gap_z=overnight_gap_z_val,
            range_efficiency=range_efficiency_val,
            ret_lag_1=ret_lag_1_val,
            ret_lag_2=ret_lag_2_val,
            ret_lag_3=ret_lag_3_val,
            ret_lag_fast=ret_lag_fast_val,
            ret_lag_mid=ret_lag_mid_val,
            ret_lag_slow=ret_lag_slow_val,
            open_ret=open_ret_val,
            intraday_ret=intraday_ret_val,
            open_vs_intraday=open_vs_intraday_val,
            session_time_pos=session_time_pos_val,
            hour_of_day_sin=hour_of_day_sin_val,
            hour_of_day_cos=hour_of_day_cos_val,
            week_of_month_sin=week_of_month_sin_val,
            week_of_month_cos=week_of_month_cos_val,
            day_of_month_sin=day_of_month_sin_val,
            day_of_month_cos=day_of_month_cos_val,
            week_of_year_sin=week_of_year_sin_val,
            week_of_year_cos=week_of_year_cos_val,
            month_sin=month_sin_val,
            month_cos=month_cos_val,
            vol_acceleration=_series_last(s.vol_acceleration, 1.0),
            dollar_vol_z=_series_last(s.dollar_vol_z, 0.0),
            vol_range_ratio=_series_last(s.vol_range_ratio, 0.0),
            vol_trend_ratio=_series_last(s.vol_trend_ratio, 1.0),
            up_vol_ratio_fast=up_vol_ratio_fast_val,
            up_vol_ratio_slow=_series_last(s.up_vol_ratio_slow, 0.5),
            vol_percentile=_series_last(s.vol_percentile, 0.5),
            vol_persistence=_series_last(s.vol_persistence, 0.0),
            vol_std_z=_series_last(s.vol_std_z, 0.0),
            mfi_fast=_series_last(s.mfi_fast, 50.0),
            mfi_slow=_series_last(s.mfi_slow, 50.0),
            obv_z=_series_last(s.obv_z, 0.0),
            dist_from_high_fast=dist_from_high_fast_val,
            dist_from_high_slow=_series_last(s.dist_from_high_slow, 0.0),
            dist_from_low_fast=_series_last(s.dist_from_low_fast, 0.0),
            dist_from_low_slow=_series_last(s.dist_from_low_slow, 0.0),
            range_pct_fast=_series_last(s.range_pct_fast, 0.0),
            range_pct_slow=_series_last(s.range_pct_slow, 0.0),
            stoch_k_fast=_series_last(s.stoch_k_fast, 0.5),
            stoch_k_slow=_series_last(s.stoch_k_slow, 0.5),
            price_percentile_fast=_series_last(s.price_percentile_fast, 0.5),
            price_percentile_slow=_series_last(s.price_percentile_slow, 0.5),
            efficiency_ratio_fast=efficiency_ratio_fast_val,
            efficiency_ratio_slow=_series_last(s.efficiency_ratio_slow, 0.0),
            ret_kurtosis_z_fast=_series_last(s.ret_kurtosis_z_fast, 0.0),
            ret_kurtosis_z_slow=_series_last(s.ret_kurtosis_z_slow, 0.0),
            ret_autocorr_1=_series_last(s.ret_autocorr_1, 0.0),
            ret_autocorr_5=_series_last(s.ret_autocorr_5, 0.0),
            updown_ratio_fast=_series_last(s.updown_ratio_fast, 1.0),
            updown_ratio_slow=_series_last(s.updown_ratio_slow, 1.0),
            streak_z=_series_last(s.streak_z, 0.0),
            realized_var_ratio_fast=_series_last(s.realized_var_ratio_fast, 1.0),
            realized_var_ratio_slow=_series_last(s.realized_var_ratio_slow, 1.0),
            range_to_close=_series_last(s.range_to_close, 0.0),
            true_range_pct=_series_last(s.true_range_pct, 0.0),
            vol_of_vol=_series_last(s.vol_of_vol, 0.0),
            high_low_corr=_series_last(s.high_low_corr, 0.0),
            variance_ratio_fast=variance_ratio_fast_val,
            variance_ratio_slow=_series_last(s.variance_ratio_slow, 1.0),
            vol_asymmetry_z=_series_last(s.vol_asymmetry_z, 0.0),
            bb_pct_b_fast=_series_last(s.bb_pct_b_fast, 0.5),
            bb_pct_b_slow=_series_last(s.bb_pct_b_slow, 0.5),
            hv_z_fast=_series_last(s.hv_z_fast, 0.0),
            hv_z_slow=_series_last(s.hv_z_slow, 0.0),
            hv_ratio=hv_ratio_val,
            # Renaissance Primitives (Phase 142.5 Plan 04) — alternative volatility
            # estimators + volatility dynamics. All read the precomputed series (s.*)
            # built once above; velocity primitives are the O(1) difference of the
            # current and prior-bar z-score elements (stateless, no cache dependency),
            # guaranteeing exact parity with compute_batch()'s indexing.
            parkinson_vol_z=_series_last(s.parkinson_vol_z, 0.0),
            garman_klass_vol_z=_series_last(s.garman_klass_vol_z, 0.0),
            yang_zhang_vol_z=_series_last(s.yang_zhang_vol_z, 0.0),
            parkinson_vol_velocity=(
                float(s.parkinson_vol_z[-1] - s.parkinson_vol_z[-2])
                if len(s.parkinson_vol_z) >= 2
                else 0.0
            ),
            garman_klass_vol_velocity=(
                float(s.garman_klass_vol_z[-1] - s.garman_klass_vol_z[-2])
                if len(s.garman_klass_vol_z) >= 2
                else 0.0
            ),
            yang_zhang_vol_velocity=(
                float(s.yang_zhang_vol_z[-1] - s.yang_zhang_vol_z[-2])
                if len(s.yang_zhang_vol_z) >= 2
                else 0.0
            ),
            vol_velocity_z=_series_last(s.vol_velocity_z, 0.0),
            intraday_noise_ratio=_series_last(s.intraday_noise_ratio, 1.0),
            # Velocity Primitives (Phase 151 Plan 01 Task 2) — read from the
            # precomputed series built once above, same pattern as vol_velocity_z.
            momentum_z_velocity_fast=_series_last(s.momentum_z_velocity_fast, 0.0),
            momentum_z_velocity_mid=_series_last(s.momentum_z_velocity_mid, 0.0),
            momentum_z_velocity_slow=_series_last(s.momentum_z_velocity_slow, 0.0),
            vwap_dev_sigma_velocity=_series_last(s.vwap_dev_sigma_velocity, 0.0),
            # Velocity Primitives Extension (todo 320) — read from the
            # precomputed series built once above, same pattern as
            # momentum_z_velocity_fast/vol_velocity_z.
            rsi_velocity_fast=_series_last(s.rsi_velocity_fast, 0.0),
            rsi_velocity_mid=_series_last(s.rsi_velocity_mid, 0.0),
            rsi_velocity_slow=_series_last(s.rsi_velocity_slow, 0.0),
            ofi_z_velocity=_series_last(s.ofi_z_velocity, 0.0),
            cvd_slope_z_velocity=_series_last(s.cvd_slope_z_velocity, 0.0),
            volume_z_velocity=_series_last(s.volume_z_velocity, 0.0),
            # Recency / Statistical Atomics (Phase 151 Plan 03, todo 180) —
            # read from the precomputed series built once above. Fallback is
            # the saturating value float(window-1) for each field's own
            # window, matching the no-event-in-window convention (never 0.0,
            # which would falsely assert "the extreme/event is the current
            # bar").
            bars_since_high_fast=_series_last(
                s.bars_since_high_fast, float(config.dist_window_fast - 1)
            ),
            bars_since_high_slow=_series_last(
                s.bars_since_high_slow, float(config.dist_window_slow - 1)
            ),
            bars_since_low_fast=_series_last(
                s.bars_since_low_fast, float(config.dist_window_fast - 1)
            ),
            bars_since_low_slow=_series_last(
                s.bars_since_low_slow, float(config.dist_window_slow - 1)
            ),
            bars_since_52w_high=_series_last(
                s.bars_since_52w_high, float(config.high_52w_window - 1)
            ),
            bars_since_52w_low=_series_last(
                s.bars_since_52w_low, float(config.high_52w_window - 1)
            ),
            bars_since_extreme_move_fast=_series_last(
                s.bars_since_extreme_move_fast, float(config.dist_window_fast - 1)
            ),
            bars_since_extreme_move_slow=_series_last(
                s.bars_since_extreme_move_slow, float(config.dist_window_slow - 1)
            ),
            bars_since_vol_spike_fast=_series_last(
                s.bars_since_vol_spike_fast, float(config.dist_window_fast - 1)
            ),
            bars_since_vol_spike_slow=_series_last(
                s.bars_since_vol_spike_slow, float(config.dist_window_slow - 1)
            ),
            abs_ret_autocorr_1=_series_last(s.abs_ret_autocorr_1, 0.0),
            # Cross-asset — Spread/Beta Atomics (Phase 151 Plan 04). Live path
            # reads cache-broadcast values, same as vix_z/flight_quality/
            # yield_slope_z above -- 0.0 at their FeatureCache dataclass
            # default until a live-path writer populates them (plan 151-09).
            # equity_beta_z/rate_beta_z apply the SPY/TLT self-regression
            # None special-case here (symbol is in scope; FeatureCache itself
            # stores an unconditional 0.0 default, per Task 1).
            tip_tlt_ret_z=cache.tip_tlt_ret_z,
            hyg_lqd_ret_z=cache.hyg_lqd_ret_z,
            sb_corr_fast=cache.sb_corr_fast,
            sb_corr_slow=cache.sb_corr_slow,
            sb_corr_z=cache.sb_corr_z,
            equity_beta_z=None if symbol == "SPY" else cache.equity_beta_z,
            rate_beta_z=None if symbol == "TLT" else cache.rate_beta_z,
            # Named Interaction Primitives (Phase 151 Plan 05). The 3 cross-TF
            # divergences have NO live-path plumbing today (batch is the
            # corpus/IC-measurement path; the LTF/HTF merge-walk builders live
            # only in backfill_feature_factory.py) -- always None here, same
            # asymmetry already documented for the Plan 04 cross-asset gap
            # (todo filed at that plan's Task 4). opex_flag/quad_witching_flag
            # need only bar_ts, which IS in scope on both paths, so they
            # compute real values here too.
            ret_div_1m_5m=None,
            ret_div_5m_1h=None,
            ret_div_1h_1d=None,
            opex_flag=_opex_flag(bar_ts),
            quad_witching_flag=_quad_witching_flag(bar_ts),
            earnings_season_flag=_earnings_season_flag(bar_ts, config),
            days_since_quarter_end=_days_since_quarter_end(bar_ts),
            # Renaissance Primitives (Phase 142.5 Plan 05.5) — price-volume
            # interactions. 6 window-free combinators computed inline above
            # from already-captured parent scalars; the 2 rolling
            # correlations read the precomputed series (s.*) built above.
            vol_body_product=vol_body_product_val,
            ret_vol_product_fast=ret_vol_product_fast_val,
            price_vol_corr_fast=price_vol_corr_fast_val,
            price_vol_corr_slow=price_vol_corr_slow_val,
            range_vol_product=range_vol_product_val,
            up_vol_body_diff=up_vol_body_diff_val,
            ret_vol_ratio_fast=ret_vol_ratio_fast_val,
            vol_skew_product=vol_skew_product_val,
            momentum_vol_regime_product=momentum_vol_regime_product_val,
            momentum_trend_product=momentum_trend_product_val,
            breakout_volume_product=breakout_volume_product_val,
            reversion_hurst_product=reversion_hurst_product_val,
            quarter_momentum_product=quarter_momentum_product_val,
            variance_ratio_momentum_product=variance_ratio_momentum_product_val,
            illiquidity_momentum_product=illiquidity_momentum_product_val,
            yield_slope_momentum_product=yield_slope_momentum_product_val,
            vix_reversion_product=vix_reversion_product_val,
            efficiency_volume_product=efficiency_volume_product_val,
            canary_noise_gaussian=canary_noise_gaussian_val,
            canary_noise_uniform=canary_noise_uniform_val,
            canary_constant=_CANARY_CONSTANT_VALUE,
            canary_near_constant=canary_near_constant_val,
            canary_acausal_placebo=canary_acausal_placebo_val,
        )

    @staticmethod
    def compute_batch(
        bars: list[dict],
        symbol: str,
        tf: str,
        cache: FeatureCache,
        config: FeatureFactoryConfig,
        warm_up_bars: int = 0,
        cross_asset_by_date: dict | None = None,
        ctf_by_ts: CtfSeries | None = None,
        beta_by_date: dict | None = None,
        ltf_ret_by_ts: dict | None = None,
    ) -> list[tuple[datetime, FeatureVector]]:
        """Compute FeatureVector for every bar in bars in O(n). Returns (bar_ts, fv) pairs.

        Precomputes all series_full functions once, then loops over bars indexing series[i].
        Non-series features (cmf, cci, aroon, vol_ratio, range_position, bar_close_pos, informed_flow)
        are computed per bar with bounded windows. Cache-backed features (hmm, hurst, etc.) are
        read from cache. Calendar features computed per bar from timestamps.

        When cross_asset_by_date is provided (batch path):
          - cross-asset (vix_z, flight_quality, yield_slope_z, tip_tlt_ret_z, hyg_lqd_ret_z,
            sb_corr_fast/slow/z -- Phase 151 Plan 04) read from a dict of CrossAssetRecord
            keyed by date
          - equity_beta_z/rate_beta_z (Phase 151 Plan 04, per-symbol) read from beta_by_date
            keyed by date, defaulting to (None, None) when the date is absent; None is also
            the permanent value when the caller IS the factor proxy for that beta (SPY for
            equity_beta_z, TLT for rate_beta_z) -- a self-regression is degenerate
          - CTF (ctf_momentum, ctf_vwap_align, ctf_regime_align) read from ctf_by_ts (a CtfSeries
            keyed by HTF bar close; a plain dict raises TypeError) via CtfSeries.asof
          - VP (poc_dist_atr, va_position, + 12 structural fields) computed from OHLCV via
            FeatureCache.update_session_vp(), called once per bar including warm-up --
            the identical mechanism the live path uses (D-05: no I3/tick-data dependency
            exists; the prior claim that this group was uncomputable in batch was a stale,
            never-verified assumption, now removed). S/R (sr_support_dist, sr_resist_dist,
            + 5 D-19 strength/age/count fields) computed stateless inline via
            the support_resistance kernel over a bounded per-tf lookback window built from
            OHLCV -- no cache/tick-data dependency, same mechanism in live and batch.
          - ret_div_5m_1h/ret_div_1h_1d (Phase 151 Plan 05) read ctf_by_ts's
            htf_last_log_ret field (same bisect lookup as CTF above), timeframe-
            pinned to tf=="5m"/"1h" respectively, None elsewhere. ret_div_1m_5m
            reads ltf_ret_by_ts (a separate causal merge-walk dict, tf=="5m"
            only), None wherever the key is absent (~99% of 5m bars -- 1m
            OHLCV coverage is far shorter than 5m's, a documented data
            limitation, not a defect).
        When cross_asset_by_date is None (live path):
          - cross-asset and CTF groups read from cache (unchanged behavior); VP and S/R
            use the same OHLCV-derived computation as the batch path. beta_by_date is
            ignored on this path -- equity_beta_z/rate_beta_z read from cache (0.0 live
            default until plan 151-09 wires a live-path writer), same SPY/TLT None
            special-case applied via the `symbol` argument. The 3 cross-TF divergences
            have no live-path plumbing today -- always None (Plan 05, same asymmetry
            documented for the Plan 04 cross-asset gap).
        """
        if len(bars) < 2:
            return []

        # Extract numpy arrays once
        opens = np.array([b["open"] for b in bars], dtype=float)
        highs = np.array([b["high"] for b in bars], dtype=float)
        lows = np.array([b["low"] for b in bars], dtype=float)
        closes = np.array([b["close"] for b in bars], dtype=float)
        volumes = np.array([b["volume"] for b in bars], dtype=float)

        # Registry kernels (D-25) compute every series and delegated column once for the whole
        # batch; the loop below reads row i. The registry is looked up here, never at import,
        # so kernel origins cannot create an import cycle with this module.
        row_ns = np.array([bar_ts_ns(b["ts"]) for b in bars], dtype=np.int64)
        k = compute_kernels(
            default_registry(),
            {
                **_batch_kernel_inputs(row_ns, opens, highs, lows, closes, volumes, symbol, tf),
                **_macro_kernel_inputs(
                    row_ns, symbol, tf, cache, cross_asset_by_date, beta_by_date
                ),
                **_cross_tf_kernel_inputs(row_ns, tf, cache, ctf_by_ts, ltf_ret_by_ts),
            },
            config,
            outputs=list(
                dict.fromkeys(
                    (
                        *_SERIES_KERNEL_OUTPUTS,
                        *_DELEGATED_KERNEL_OUTPUTS,
                        *_STRUCTURE_KERNEL_OUTPUTS,
                        *_CROSS_TF_KERNEL_OUTPUTS,
                    )
                )
            ),
        )
        s = _series_from_kernel_outputs(k)

        results: list[tuple[datetime, FeatureVector]] = []

        for i in range(1, len(bars)):
            # Periodically refresh regime — use hurst_window (APR: feature.hurst.window,
            # default 500) so HMM gets sufficient history. The bounded per-bar features (CCI,
            # Aroon, etc.) are registry kernels.
            if i % config.regime_cache_refresh_bars == 0:
                regime_window_start = max(0, i - config.hurst_window)
                cache.refresh_regime(bars[regime_window_start : i + 1], config)

            bar = bars[i]
            bar_ts = bar["ts"]
            if isinstance(bar_ts, datetime) and bar_ts.tzinfo is None:
                bar_ts = bar_ts.replace(tzinfo=UTC)
            open_ = float(bar["open"])
            high_ = float(bar["high"])
            low_ = float(bar["low"])
            close_ = float(bar["close"])
            vol_ = float(bar["volume"])

            # Session-VP accumulator (Phase 163 Plan 02): update on EVERY bar,
            # including warm-up, so FeatureCache._sess_bars (the session-
            # boundary-reset accumulator) stays current through warmup --
            # matches the live pipeline's per-bar update_session_vp() call site.
            cache.update_session_vp(bar_ts, high_, low_, close_, vol_, config)

            # AMD overnight-range accumulator (Phase 164 Plan 04): update on
            # EVERY bar, including warm-up, matching update_session_vp's
            # treatment immediately above -- otherwise the overnight
            # high/low state would cold-start mid-cycle whenever a batch run
            # starts inside the accumulation window. Same call-site
            # convention as the live per-bar handler and warm-up replay
            # block in services/feature_vector_pipeline.py.
            cache.update_overnight_range(bar_ts, high_, low_, config)

            # Session-levels accumulator (Phase 165 Plan 04): update on EVERY
            # bar, including warm-up, matching update_session_vp's/
            # update_overnight_range's treatment immediately above -- firing
            # through warm-up is what keeps the session/overnight/Asian/weekly
            # state from cold-starting mid-session. `open_` is read above
            # (moved up from its former post-warm-up-gate position) so it is
            # available here.
            cache.update_session_levels(bar_ts, open_, high_, low_, close_, config)

            # Skip warm-up
            if i < warm_up_bars:
                cache.advance_bar(bar_ts, high_, low_, close_, vol_)
                continue

            # Series-backed features (index into precomputed series)
            atr_val = float(s.atr_raw[i - 1]) if i - 1 < len(s.atr_raw) else 0.0
            atr_z_val = float(s.atr_z[i]) if i < len(s.atr_z) else 0.0
            gap_z_val = float(s.gap_z[i]) if i < len(s.gap_z) else 0.0
            rel_volume_val = float(s.rel_volume[i]) if i < len(s.rel_volume) else 1.0
            ofi_z_val = float(s.ofi_z[i]) if i < len(s.ofi_z) else 0.0
            cvd_slope_z_val = float(s.cvd_slope_z[i]) if i < len(s.cvd_slope_z) else 0.0
            volume_z_val = float(s.volume_z[i]) if i < len(s.volume_z) else 0.0
            momentum_z_fast_val = float(s.momentum_z_fast[i]) if i < len(s.momentum_z_fast) else 0.0
            momentum_z_mid_val = float(s.momentum_z_mid[i]) if i < len(s.momentum_z_mid) else 0.0
            momentum_z_slow_val = float(s.momentum_z_slow[i]) if i < len(s.momentum_z_slow) else 0.0
            momentum_reversal_z_val = (
                float(s.momentum_reversal_z[i]) if i < len(s.momentum_reversal_z) else 0.0
            )
            vwap_dev_sigma_val = float(s.vwap_dev_sigma[i]) if i < len(s.vwap_dev_sigma) else 0.0
            rsi_fast_val = float(s.rsi_fast[i]) if i < len(s.rsi_fast) else 50.0
            rsi_mid_val = float(s.rsi_mid[i]) if i < len(s.rsi_mid) else 50.0
            rsi_slow_val = float(s.rsi_slow[i]) if i < len(s.rsi_slow) else 50.0
            amihud_illiq_z_val = float(s.amihud_illiq_z[i]) if i < len(s.amihud_illiq_z) else 0.0
            high_52w_dist_val = float(s.high_52w_dist[i]) if i < len(s.high_52w_dist) else 0.0
            ret_skew_z_val = float(s.ret_skew_z[i]) if i < len(s.ret_skew_z) else 0.0
            ret_acf1_z_val = float(s.ret_acf1_z[i]) if i < len(s.ret_acf1_z) else 0.0

            # Non-series features (compute on bounded window)
            bar_close_pos_val = float(k["bar_close_pos"][i])
            range_position_val = float(k["range_position"][i])

            informed_flow_val = float(k["informed_flow"][i])
            vol_ratio_val = float(k["vol_ratio"][i])
            cmf_val = float(k["cmf"][i])

            # Session-level VP (Phase 163 Plan 02): tf=='1d' keeps neutral
            # defaults (a single daily bar has no intraday distribution); else
            # derive the 14 ATR-normalized/bounded VP fields from FeatureCache's
            # raw session levels (kept current above via update_session_vp(),
            # called for every bar including warm-up) + atr_val -- identical
            # mechanism in live and batch (D-05).
            if tf == "1d":
                vp_extra: dict[str, float | None] = dict(_NEUTRAL_VP_EXTRA)
            else:
                _poc = float(k["_poc_price_rolling"][i])
                poc_price_rolling = None if math.isnan(_poc) else _poc
                vp_extra = _derive_session_vp(cache, close_, atr_val, poc_price_rolling, config)

            # S/R, swing, trend, swing momentum and fib: registry kernels over the same causal
            # windows the loop used to slice (valid for tf=='1d' too, D-19).
            _sr_fields = _kernel_row(k, SR, i)

            _swing_fields = _kernel_row(k, SWING, i)
            _trend_fields = _kernel_row(k, TREND, i)
            _swing_momentum_fields = _kernel_row(k, SWING_MOMENTUM, i)
            _fib_fields = _kernel_row(k, FIB, i)

            # Session Levels (Phase 165 Plan 05): the last 16 Phase 165
            # fields, derived from FeatureCache's raw state --
            # cache.update_session_levels(...) was already called for this
            # bar in this loop's per-bar preamble above.
            _session_level_fields = _derive_session_levels(cache, close_, atr_val, tf, config)

            # Smart money concepts: registry kernels over the same causal windows the loop
            # used to slice, each reading the loop's atr_val.
            _ob_fields = _kernel_row(k, OB, i)
            _fvg_fields = _kernel_row(k, FVG, i)
            _sweep_fields = _kernel_row(k, SWEEP, i)
            _pool_fields = _kernel_row(k, POOL, i)
            _zone_fields = _kernel_row(k, ZONE, i)
            _bos_fields = _kernel_row(k, BOS, i)

            # AMD reads FeatureCache's overnight state, kept current by the
            # update_overnight_range() call earlier in this loop (cache-backed, like session VP).
            _amd_fields = _derive_amd_cycle(cache, bar_ts, config)

            _structural_fields = _merge_structural_fields(
                vp_extra,
                _sr_fields,
                _swing_fields,
                _trend_fields,
                _swing_momentum_fields,
                _fib_fields,
                _session_level_fields,
                _ob_fields,
                _fvg_fields,
                _sweep_fields,
                _pool_fields,
                _zone_fields,
                _bos_fields,
                _amd_fields,
            )

            # Regime-level primitives (all from cache). hmm_regime_prob/entropy/
            # duration are always None here -- regime_writer.py is the sole
            # writer of those 3 columns (todo 207, 2026-07-30); see the
            # matching comment at the compute() call site above for why.
            hmm_regime_prob_val = None
            hmm_entropy_val = None
            hmm_duration_val = None
            hurst_val = cache.hurst
            shannon_val = cache.shannon
            garch_ratio_val = cache.garch_ratio
            hma_slope_z_val = cache.hma_slope_z
            adx_val = cache.adx

            # Oscillators (non-series)
            cci_fast_val = float(k["cci_fast"][i])
            cci_mid_val = float(k["cci_mid"][i])
            cci_slow_val = float(k["cci_slow"][i])

            aroon_fast_val = float(k["aroon_fast"][i])
            aroon_slow_val = float(k["aroon_slow"][i])

            # OFI divergence
            ofi_div_val = float(k["ofi_div"][i])

            # Cross-asset: from pre-built causal dict (batch) or cache (live).
            # CrossAssetRecord is a NamedTuple (Phase 151 Plan 04) -- keyword
            # attribute access below, never positional unpack, so field order
            # can never silently matter as this payload grows.
            vix_z_val = float(k["vix_z"][i])
            flight_quality_val = float(k["flight_quality"][i])
            yield_slope_z_val = float(k["yield_slope_z"][i])
            tip_tlt_ret_z_val = float(k["tip_tlt_ret_z"][i])
            hyg_lqd_ret_z_val = float(k["hyg_lqd_ret_z"][i])
            sb_corr_fast_val = float(k["sb_corr_fast"][i])
            sb_corr_slow_val = float(k["sb_corr_slow"][i])
            sb_corr_z_val = float(k["sb_corr_z"][i])

            # Factor betas (Phase 151 Plan 04, per-symbol): from pre-built
            # beta_by_date dict (batch) or cache (live). Independent of the
            # cross_asset_by_date branch above -- beta_by_date is symbol-
            # specific, cross_asset_by_date is symbol-independent.
            equity_beta_z_val = _none_if_nan(k["equity_beta_z"][i])
            rate_beta_z_val = _none_if_nan(k["rate_beta_z"][i])

            # Calendar primitives
            in_ny_session_val = float(k["in_ny_session"][i])
            in_london_kz_val = float(k["in_london_kz"][i])
            in_overlap_val = float(k["in_overlap"][i])
            power_hour_val = float(k["power_hour"][i])
            opening_range_val = float(k["opening_range"][i])
            # Cache-backed: the registered above_wk_vwap kernel replays the same math, but
            # reading it here would change results for a caller passing a pre-warmed cache;
            # 186-25 retires the cache-driven batch loop.
            above_wk_vwap_val = cache.above_wk_vwap
            dow_sin_val, dow_cos_val = float(k["dow_sin"][i]), float(k["dow_cos"][i])
            month_position_val = float(k["month_position"][i])
            quarter_position_val = float(k["quarter_position"][i])
            days_to_month_end_val = float(k["days_to_month_end"][i])
            quarter_cycle_sin_val = float(k["quarter_cycle_sin"][i])
            quarter_cycle_cos_val = float(k["quarter_cycle_cos"][i])
            tdom_sin_val, tdom_cos_val = float(k["tdom_sin"][i]), float(k["tdom_cos"][i])
            minute_of_hour_sin_val = float(k["minute_of_hour_sin"][i])
            minute_of_hour_cos_val = float(k["minute_of_hour_cos"][i])

            # CTF and the cross-timeframe divergences: registry kernels over the HTF and LTF
            # externals (batch: aligned by bar close, live: the cache's values).
            ctf_momentum_val = float(k["ctf_momentum"][i])
            ctf_vwap_align_val = float(k["ctf_vwap_align"][i])
            ctf_regime_align_val = float(k["ctf_regime_align"][i])
            ret_div_1m_5m_val = _none_if_nan(k["ret_div_1m_5m"][i])
            ret_div_5m_1h_val = _none_if_nan(k["ret_div_5m_1h"][i])
            ret_div_1h_1d_val = _none_if_nan(k["ret_div_1h_1d"][i])

            # Renaissance Primitives (Phase 142.5 Plan 01). ret_lag_* index the full
            # `closes` array (view slice closes[:i+1], O(1)) rather than the bounded
            # w_closes window, since ret_lag_slow's APR window can exceed the bounded window.
            # overnight_gap_z reads the precomputed series (O(n) total, not O(n^2)).
            body_ratio_val = float(k["body_ratio"][i])
            upper_wick_ratio_val = float(k["upper_wick_ratio"][i])
            lower_wick_ratio_val = float(k["lower_wick_ratio"][i])
            range_vs_atr_val = float(k["range_vs_atr"][i])
            close_vs_open_direction_val = float(k["close_vs_open_direction"][i])
            overnight_gap_val = float(k["overnight_gap"][i])
            overnight_gap_z_val = float(s.overnight_gap_z[i]) if i < len(s.overnight_gap_z) else 0.0
            range_efficiency_val = float(k["range_efficiency"][i])
            ret_lag_1_val = float(k["ret_lag_1"][i])

            opex_flag_val = float(k["opex_flag"][i])
            quad_witching_flag_val = float(k["quad_witching_flag"][i])
            earnings_season_flag_val = float(k["earnings_season_flag"][i])
            days_since_quarter_end_val = float(k["days_since_quarter_end"][i])

            ret_lag_2_val = float(k["ret_lag_2"][i])
            ret_lag_3_val = float(k["ret_lag_3"][i])
            ret_lag_fast_val = float(k["ret_lag_fast"][i])
            ret_lag_mid_val = float(k["ret_lag_mid"][i])
            ret_lag_slow_val = float(k["ret_lag_slow"][i])
            open_ret_val = float(k["open_ret"][i])
            intraday_ret_val = float(k["intraday_ret"][i])
            open_vs_intraday_val = float(k["open_vs_intraday"][i])
            session_time_pos_val = float(k["session_time_pos"][i])

            # Renaissance Primitives (Phase 142.5 Plan 02). Temporal coordinates come from the
            # calendar kernels. Volume structure reads the precomputed series (O(n) total,
            # not per-bar O(n x window)).
            hour_of_day_sin_val = float(k["hour_of_day_sin"][i])
            hour_of_day_cos_val = float(k["hour_of_day_cos"][i])
            week_of_month_sin_val = float(k["week_of_month_sin"][i])
            week_of_month_cos_val = float(k["week_of_month_cos"][i])
            day_of_month_sin_val = float(k["day_of_month_sin"][i])
            day_of_month_cos_val = float(k["day_of_month_cos"][i])
            week_of_year_sin_val = float(k["week_of_year_sin"][i])
            week_of_year_cos_val = float(k["week_of_year_cos"][i])
            month_sin_val = float(k["month_sin"][i])
            month_cos_val = float(k["month_cos"][i])
            vol_acceleration_val = (
                float(s.vol_acceleration[i]) if i < len(s.vol_acceleration) else 1.0
            )
            dollar_vol_z_val = float(s.dollar_vol_z[i]) if i < len(s.dollar_vol_z) else 0.0
            vol_range_ratio_val = float(s.vol_range_ratio[i]) if i < len(s.vol_range_ratio) else 0.0
            vol_trend_ratio_val = float(s.vol_trend_ratio[i]) if i < len(s.vol_trend_ratio) else 1.0
            up_vol_ratio_fast_val = (
                float(s.up_vol_ratio_fast[i]) if i < len(s.up_vol_ratio_fast) else 0.5
            )
            up_vol_ratio_slow_val = (
                float(s.up_vol_ratio_slow[i]) if i < len(s.up_vol_ratio_slow) else 0.5
            )
            vol_percentile_val = float(s.vol_percentile[i]) if i < len(s.vol_percentile) else 0.5
            vol_persistence_val = float(s.vol_persistence[i]) if i < len(s.vol_persistence) else 0.0
            vol_std_z_val = float(s.vol_std_z[i]) if i < len(s.vol_std_z) else 0.0
            mfi_fast_val = float(s.mfi_fast[i]) if i < len(s.mfi_fast) else 50.0
            mfi_slow_val = float(s.mfi_slow[i]) if i < len(s.mfi_slow) else 50.0
            obv_z_val = float(s.obv_z[i]) if i < len(s.obv_z) else 0.0

            # Renaissance Primitives (Phase 142.5 Plan 05) — breakout distance.
            # All 14 fields read the precomputed series (O(n) total, not per-bar
            # O(n x window)); indexing here guarantees exact parity with compute().
            dist_from_high_fast_val = (
                float(s.dist_from_high_fast[i]) if i < len(s.dist_from_high_fast) else 0.0
            )
            dist_from_high_slow_val = (
                float(s.dist_from_high_slow[i]) if i < len(s.dist_from_high_slow) else 0.0
            )
            dist_from_low_fast_val = (
                float(s.dist_from_low_fast[i]) if i < len(s.dist_from_low_fast) else 0.0
            )
            dist_from_low_slow_val = (
                float(s.dist_from_low_slow[i]) if i < len(s.dist_from_low_slow) else 0.0
            )
            range_pct_fast_val = float(s.range_pct_fast[i]) if i < len(s.range_pct_fast) else 0.0
            range_pct_slow_val = float(s.range_pct_slow[i]) if i < len(s.range_pct_slow) else 0.0
            stoch_k_fast_val = float(s.stoch_k_fast[i]) if i < len(s.stoch_k_fast) else 0.5
            stoch_k_slow_val = float(s.stoch_k_slow[i]) if i < len(s.stoch_k_slow) else 0.5
            price_percentile_fast_val = (
                float(s.price_percentile_fast[i]) if i < len(s.price_percentile_fast) else 0.5
            )
            price_percentile_slow_val = (
                float(s.price_percentile_slow[i]) if i < len(s.price_percentile_slow) else 0.5
            )
            efficiency_ratio_fast_val = (
                float(s.efficiency_ratio_fast[i]) if i < len(s.efficiency_ratio_fast) else 0.0
            )
            efficiency_ratio_slow_val = (
                float(s.efficiency_ratio_slow[i]) if i < len(s.efficiency_ratio_slow) else 0.0
            )

            # Renaissance Primitives (Phase 142.5 Plan 03) — return distribution +
            # realized variance. All 21 fields read the precomputed series (O(n)
            # total, not per-bar O(n x window)); indexing here guarantees exact
            # parity with compute().
            ret_kurtosis_z_fast_val = (
                float(s.ret_kurtosis_z_fast[i]) if i < len(s.ret_kurtosis_z_fast) else 0.0
            )
            ret_kurtosis_z_slow_val = (
                float(s.ret_kurtosis_z_slow[i]) if i < len(s.ret_kurtosis_z_slow) else 0.0
            )
            ret_autocorr_1_val = float(s.ret_autocorr_1[i]) if i < len(s.ret_autocorr_1) else 0.0
            ret_autocorr_5_val = float(s.ret_autocorr_5[i]) if i < len(s.ret_autocorr_5) else 0.0
            updown_ratio_fast_val = (
                float(s.updown_ratio_fast[i]) if i < len(s.updown_ratio_fast) else 1.0
            )
            updown_ratio_slow_val = (
                float(s.updown_ratio_slow[i]) if i < len(s.updown_ratio_slow) else 1.0
            )
            streak_z_val = float(s.streak_z[i]) if i < len(s.streak_z) else 0.0
            realized_var_ratio_fast_val = (
                float(s.realized_var_ratio_fast[i]) if i < len(s.realized_var_ratio_fast) else 1.0
            )
            realized_var_ratio_slow_val = (
                float(s.realized_var_ratio_slow[i]) if i < len(s.realized_var_ratio_slow) else 1.0
            )
            range_to_close_val = float(s.range_to_close[i]) if i < len(s.range_to_close) else 0.0
            true_range_pct_val = float(s.true_range_pct[i]) if i < len(s.true_range_pct) else 0.0
            vol_of_vol_val = float(s.vol_of_vol[i]) if i < len(s.vol_of_vol) else 0.0
            high_low_corr_val = float(s.high_low_corr[i]) if i < len(s.high_low_corr) else 0.0
            variance_ratio_fast_val = (
                float(s.variance_ratio_fast[i]) if i < len(s.variance_ratio_fast) else 1.0
            )
            variance_ratio_slow_val = (
                float(s.variance_ratio_slow[i]) if i < len(s.variance_ratio_slow) else 1.0
            )
            vol_asymmetry_z_val = float(s.vol_asymmetry_z[i]) if i < len(s.vol_asymmetry_z) else 0.0
            bb_pct_b_fast_val = float(s.bb_pct_b_fast[i]) if i < len(s.bb_pct_b_fast) else 0.5
            bb_pct_b_slow_val = float(s.bb_pct_b_slow[i]) if i < len(s.bb_pct_b_slow) else 0.5
            hv_z_fast_val = float(s.hv_z_fast[i]) if i < len(s.hv_z_fast) else 0.0
            hv_z_slow_val = float(s.hv_z_slow[i]) if i < len(s.hv_z_slow) else 0.0
            hv_ratio_val = float(s.hv_ratio[i]) if i < len(s.hv_ratio) else 1.0

            # Renaissance Primitives (Phase 142.5 Plan 04) — alternative volatility
            # estimators + volatility dynamics. All 8 fields read the precomputed
            # series (O(n) total, not per-bar O(n x window)); velocity primitives
            # are the O(1) difference of consecutive precomputed z-score elements,
            # guaranteeing exact parity with compute().
            parkinson_vol_z_val = float(s.parkinson_vol_z[i]) if i < len(s.parkinson_vol_z) else 0.0
            garman_klass_vol_z_val = (
                float(s.garman_klass_vol_z[i]) if i < len(s.garman_klass_vol_z) else 0.0
            )
            yang_zhang_vol_z_val = (
                float(s.yang_zhang_vol_z[i]) if i < len(s.yang_zhang_vol_z) else 0.0
            )
            parkinson_vol_velocity_val = float(k["parkinson_vol_velocity"][i])
            garman_klass_vol_velocity_val = float(k["garman_klass_vol_velocity"][i])
            yang_zhang_vol_velocity_val = float(k["yang_zhang_vol_velocity"][i])
            vol_velocity_z_val = float(s.vol_velocity_z[i]) if i < len(s.vol_velocity_z) else 0.0
            intraday_noise_ratio_val = (
                float(s.intraday_noise_ratio[i]) if i < len(s.intraday_noise_ratio) else 1.0
            )
            # Velocity Primitives (Phase 151 Plan 01 Task 2) — same
            # precomputed-series indexing pattern as vol_velocity_z above.
            momentum_z_velocity_fast_val = (
                float(s.momentum_z_velocity_fast[i]) if i < len(s.momentum_z_velocity_fast) else 0.0
            )
            momentum_z_velocity_mid_val = (
                float(s.momentum_z_velocity_mid[i]) if i < len(s.momentum_z_velocity_mid) else 0.0
            )
            momentum_z_velocity_slow_val = (
                float(s.momentum_z_velocity_slow[i]) if i < len(s.momentum_z_velocity_slow) else 0.0
            )
            vwap_dev_sigma_velocity_val = (
                float(s.vwap_dev_sigma_velocity[i]) if i < len(s.vwap_dev_sigma_velocity) else 0.0
            )
            # Velocity Primitives Extension (todo 320) — same
            # precomputed-series indexing pattern as vol_velocity_z/
            # momentum_z_velocity_fast above.
            rsi_velocity_fast_val = (
                float(s.rsi_velocity_fast[i]) if i < len(s.rsi_velocity_fast) else 0.0
            )
            rsi_velocity_mid_val = (
                float(s.rsi_velocity_mid[i]) if i < len(s.rsi_velocity_mid) else 0.0
            )
            rsi_velocity_slow_val = (
                float(s.rsi_velocity_slow[i]) if i < len(s.rsi_velocity_slow) else 0.0
            )
            ofi_z_velocity_val = float(s.ofi_z_velocity[i]) if i < len(s.ofi_z_velocity) else 0.0
            cvd_slope_z_velocity_val = (
                float(s.cvd_slope_z_velocity[i]) if i < len(s.cvd_slope_z_velocity) else 0.0
            )
            volume_z_velocity_val = (
                float(s.volume_z_velocity[i]) if i < len(s.volume_z_velocity) else 0.0
            )

            # Recency / Statistical Atomics (Phase 151 Plan 03, todo 180) —
            # same precomputed-series indexing pattern as the velocity
            # primitives above. Fallback is the saturating value
            # float(window-1) for each field's own window, matching
            # compute()'s _series_last fallback convention exactly.
            bars_since_high_fast_val = (
                float(s.bars_since_high_fast[i])
                if i < len(s.bars_since_high_fast)
                else float(config.dist_window_fast - 1)
            )
            bars_since_high_slow_val = (
                float(s.bars_since_high_slow[i])
                if i < len(s.bars_since_high_slow)
                else float(config.dist_window_slow - 1)
            )
            bars_since_low_fast_val = (
                float(s.bars_since_low_fast[i])
                if i < len(s.bars_since_low_fast)
                else float(config.dist_window_fast - 1)
            )
            bars_since_low_slow_val = (
                float(s.bars_since_low_slow[i])
                if i < len(s.bars_since_low_slow)
                else float(config.dist_window_slow - 1)
            )
            bars_since_52w_high_val = (
                float(s.bars_since_52w_high[i])
                if i < len(s.bars_since_52w_high)
                else float(config.high_52w_window - 1)
            )
            bars_since_52w_low_val = (
                float(s.bars_since_52w_low[i])
                if i < len(s.bars_since_52w_low)
                else float(config.high_52w_window - 1)
            )
            bars_since_extreme_move_fast_val = (
                float(s.bars_since_extreme_move_fast[i])
                if i < len(s.bars_since_extreme_move_fast)
                else float(config.dist_window_fast - 1)
            )
            bars_since_extreme_move_slow_val = (
                float(s.bars_since_extreme_move_slow[i])
                if i < len(s.bars_since_extreme_move_slow)
                else float(config.dist_window_slow - 1)
            )
            bars_since_vol_spike_fast_val = (
                float(s.bars_since_vol_spike_fast[i])
                if i < len(s.bars_since_vol_spike_fast)
                else float(config.dist_window_fast - 1)
            )
            bars_since_vol_spike_slow_val = (
                float(s.bars_since_vol_spike_slow[i])
                if i < len(s.bars_since_vol_spike_slow)
                else float(config.dist_window_slow - 1)
            )
            abs_ret_autocorr_1_val = (
                float(s.abs_ret_autocorr_1[i]) if i < len(s.abs_ret_autocorr_1) else 0.0
            )

            # Renaissance Primitives (Phase 142.5 Plan 05.5) — price-volume
            # interactions. The 6 window-free combinators reuse already-
            # computed scalar locals (O(1) per bar); the 2 rolling
            # correlations read the precomputed series (O(n) total, not
            # per-bar O(n x window)), guaranteeing exact parity with compute().
            vol_body_product_val = float(k["vol_body_product"][i])
            ret_vol_product_fast_val = float(k["ret_vol_product_fast"][i])
            range_vol_product_val = float(k["range_vol_product"][i])
            up_vol_body_diff_val = float(k["up_vol_body_diff"][i])
            ret_vol_ratio_fast_val = float(k["ret_vol_ratio_fast"][i])
            vol_skew_product_val = float(k["vol_skew_product"][i])
            price_vol_corr_fast_val = (
                float(s.price_vol_corr_fast[i]) if i < len(s.price_vol_corr_fast) else 0.0
            )
            price_vol_corr_slow_val = (
                float(s.price_vol_corr_slow[i]) if i < len(s.price_vol_corr_slow) else 0.0
            )

            # Theory-Motivated Interactions (Phase 151 Plan 06) -- 10
            # single-operation products of two already-bound _val locals
            # (all 13 distinct parents bound earlier in this loop iteration),
            # same reuse-not-recompute discipline as the Price-Volume
            # Interactions block immediately above.
            momentum_vol_regime_product_val = float(k["momentum_vol_regime_product"][i])
            momentum_trend_product_val = momentum_z_fast_val * adx_val
            breakout_volume_product_val = float(k["breakout_volume_product"][i])
            reversion_hurst_product_val = momentum_reversal_z_val * hurst_val
            quarter_momentum_product_val = float(k["quarter_momentum_product"][i])
            variance_ratio_momentum_product_val = float(k["variance_ratio_momentum_product"][i])
            illiquidity_momentum_product_val = float(k["illiquidity_momentum_product"][i])
            yield_slope_momentum_product_val = float(k["yield_slope_momentum_product"][i])
            vix_reversion_product_val = float(k["vix_reversion_product"][i])
            efficiency_volume_product_val = float(k["efficiency_volume_product"][i])

            # Canary / Control Predictors (Phase 143.1 Plan 02). Unlike the
            # live compute() path, `closes` here is the full-history array
            # passed by the caller (backfill), so the acausal placebo can
            # genuinely reference bars i+1/i+2 -- the deliberate look-ahead
            # leak this canary exists to calibrate.
            canary_noise_gaussian_val = float(k["canary_noise_gaussian"][i])
            canary_noise_uniform_val = float(k["canary_noise_uniform"][i])
            canary_near_constant_val = float(k["canary_near_constant"][i])
            canary_acausal_placebo_val = float(k["canary_acausal_placebo"][i])

            # Build FeatureVector
            fv = _build_feature_vector(
                momentum_z_fast=momentum_z_fast_val,
                momentum_z_mid=momentum_z_mid_val,
                range_position=range_position_val,
                bar_close_pos=bar_close_pos_val,
                gap_z=gap_z_val,
                momentum_z_slow=momentum_z_slow_val,
                momentum_reversal_z=momentum_reversal_z_val,
                informed_flow=informed_flow_val,
                volume_z=volume_z_val,
                ofi_z=ofi_z_val,
                ofi_div=ofi_div_val,
                cvd_slope_z=cvd_slope_z_val,
                cmf=cmf_val,
                rel_volume=rel_volume_val,
                vwap_dev_sigma=vwap_dev_sigma_val,
                atr_z=atr_z_val,
                vol_ratio=vol_ratio_val,
                **_structural_fields,
                hmm_regime_prob=hmm_regime_prob_val,
                hmm_entropy=hmm_entropy_val,
                hmm_duration=hmm_duration_val,
                hurst=hurst_val,
                shannon=shannon_val,
                garch_ratio=garch_ratio_val,
                hma_slope_z=hma_slope_z_val,
                adx=adx_val,
                aroon_fast=aroon_fast_val,
                aroon_slow=aroon_slow_val,
                rsi_fast=rsi_fast_val,
                rsi_mid=rsi_mid_val,
                rsi_slow=rsi_slow_val,
                cci_fast=cci_fast_val,
                cci_mid=cci_mid_val,
                cci_slow=cci_slow_val,
                vix_z=vix_z_val,
                flight_quality=flight_quality_val,
                yield_slope_z=yield_slope_z_val,
                in_ny_session=in_ny_session_val,
                in_london_kz=in_london_kz_val,
                in_overlap=in_overlap_val,
                power_hour=power_hour_val,
                opening_range=opening_range_val,
                above_wk_vwap=above_wk_vwap_val,
                dow_sin=dow_sin_val,
                dow_cos=dow_cos_val,
                month_position=month_position_val,
                quarter_position=quarter_position_val,
                days_to_month_end=days_to_month_end_val,
                quarter_cycle_sin=quarter_cycle_sin_val,
                quarter_cycle_cos=quarter_cycle_cos_val,
                tdom_sin=tdom_sin_val,
                tdom_cos=tdom_cos_val,
                minute_of_hour_sin=minute_of_hour_sin_val,
                minute_of_hour_cos=minute_of_hour_cos_val,
                ctf_momentum=ctf_momentum_val,
                ctf_vwap_align=ctf_vwap_align_val,
                ctf_regime_align=ctf_regime_align_val,
                amihud_illiq_z=amihud_illiq_z_val,
                high_52w_dist=high_52w_dist_val,
                ret_skew_z=ret_skew_z_val,
                ret_acf1_z=ret_acf1_z_val,
                body_ratio=body_ratio_val,
                upper_wick_ratio=upper_wick_ratio_val,
                lower_wick_ratio=lower_wick_ratio_val,
                range_vs_atr=range_vs_atr_val,
                close_vs_open_direction=close_vs_open_direction_val,
                overnight_gap=overnight_gap_val,
                overnight_gap_z=overnight_gap_z_val,
                range_efficiency=range_efficiency_val,
                ret_lag_1=ret_lag_1_val,
                ret_lag_2=ret_lag_2_val,
                ret_lag_3=ret_lag_3_val,
                ret_lag_fast=ret_lag_fast_val,
                ret_lag_mid=ret_lag_mid_val,
                ret_lag_slow=ret_lag_slow_val,
                open_ret=open_ret_val,
                intraday_ret=intraday_ret_val,
                open_vs_intraday=open_vs_intraday_val,
                session_time_pos=session_time_pos_val,
                hour_of_day_sin=hour_of_day_sin_val,
                hour_of_day_cos=hour_of_day_cos_val,
                week_of_month_sin=week_of_month_sin_val,
                week_of_month_cos=week_of_month_cos_val,
                day_of_month_sin=day_of_month_sin_val,
                day_of_month_cos=day_of_month_cos_val,
                week_of_year_sin=week_of_year_sin_val,
                week_of_year_cos=week_of_year_cos_val,
                month_sin=month_sin_val,
                month_cos=month_cos_val,
                vol_acceleration=vol_acceleration_val,
                dollar_vol_z=dollar_vol_z_val,
                vol_range_ratio=vol_range_ratio_val,
                vol_trend_ratio=vol_trend_ratio_val,
                up_vol_ratio_fast=up_vol_ratio_fast_val,
                up_vol_ratio_slow=up_vol_ratio_slow_val,
                vol_percentile=vol_percentile_val,
                vol_persistence=vol_persistence_val,
                vol_std_z=vol_std_z_val,
                mfi_fast=mfi_fast_val,
                mfi_slow=mfi_slow_val,
                obv_z=obv_z_val,
                dist_from_high_fast=dist_from_high_fast_val,
                dist_from_high_slow=dist_from_high_slow_val,
                dist_from_low_fast=dist_from_low_fast_val,
                dist_from_low_slow=dist_from_low_slow_val,
                range_pct_fast=range_pct_fast_val,
                range_pct_slow=range_pct_slow_val,
                stoch_k_fast=stoch_k_fast_val,
                stoch_k_slow=stoch_k_slow_val,
                price_percentile_fast=price_percentile_fast_val,
                price_percentile_slow=price_percentile_slow_val,
                efficiency_ratio_fast=efficiency_ratio_fast_val,
                efficiency_ratio_slow=efficiency_ratio_slow_val,
                ret_kurtosis_z_fast=ret_kurtosis_z_fast_val,
                ret_kurtosis_z_slow=ret_kurtosis_z_slow_val,
                ret_autocorr_1=ret_autocorr_1_val,
                ret_autocorr_5=ret_autocorr_5_val,
                updown_ratio_fast=updown_ratio_fast_val,
                updown_ratio_slow=updown_ratio_slow_val,
                streak_z=streak_z_val,
                realized_var_ratio_fast=realized_var_ratio_fast_val,
                realized_var_ratio_slow=realized_var_ratio_slow_val,
                range_to_close=range_to_close_val,
                true_range_pct=true_range_pct_val,
                vol_of_vol=vol_of_vol_val,
                high_low_corr=high_low_corr_val,
                variance_ratio_fast=variance_ratio_fast_val,
                variance_ratio_slow=variance_ratio_slow_val,
                vol_asymmetry_z=vol_asymmetry_z_val,
                bb_pct_b_fast=bb_pct_b_fast_val,
                bb_pct_b_slow=bb_pct_b_slow_val,
                hv_z_fast=hv_z_fast_val,
                hv_z_slow=hv_z_slow_val,
                hv_ratio=hv_ratio_val,
                parkinson_vol_z=parkinson_vol_z_val,
                garman_klass_vol_z=garman_klass_vol_z_val,
                yang_zhang_vol_z=yang_zhang_vol_z_val,
                parkinson_vol_velocity=parkinson_vol_velocity_val,
                garman_klass_vol_velocity=garman_klass_vol_velocity_val,
                yang_zhang_vol_velocity=yang_zhang_vol_velocity_val,
                vol_velocity_z=vol_velocity_z_val,
                intraday_noise_ratio=intraday_noise_ratio_val,
                momentum_z_velocity_fast=momentum_z_velocity_fast_val,
                momentum_z_velocity_mid=momentum_z_velocity_mid_val,
                momentum_z_velocity_slow=momentum_z_velocity_slow_val,
                vwap_dev_sigma_velocity=vwap_dev_sigma_velocity_val,
                rsi_velocity_fast=rsi_velocity_fast_val,
                rsi_velocity_mid=rsi_velocity_mid_val,
                rsi_velocity_slow=rsi_velocity_slow_val,
                ofi_z_velocity=ofi_z_velocity_val,
                cvd_slope_z_velocity=cvd_slope_z_velocity_val,
                volume_z_velocity=volume_z_velocity_val,
                bars_since_high_fast=bars_since_high_fast_val,
                bars_since_high_slow=bars_since_high_slow_val,
                bars_since_low_fast=bars_since_low_fast_val,
                bars_since_low_slow=bars_since_low_slow_val,
                bars_since_52w_high=bars_since_52w_high_val,
                bars_since_52w_low=bars_since_52w_low_val,
                bars_since_extreme_move_fast=bars_since_extreme_move_fast_val,
                bars_since_extreme_move_slow=bars_since_extreme_move_slow_val,
                bars_since_vol_spike_fast=bars_since_vol_spike_fast_val,
                bars_since_vol_spike_slow=bars_since_vol_spike_slow_val,
                abs_ret_autocorr_1=abs_ret_autocorr_1_val,
                tip_tlt_ret_z=tip_tlt_ret_z_val,
                hyg_lqd_ret_z=hyg_lqd_ret_z_val,
                sb_corr_fast=sb_corr_fast_val,
                sb_corr_slow=sb_corr_slow_val,
                sb_corr_z=sb_corr_z_val,
                equity_beta_z=equity_beta_z_val,
                rate_beta_z=rate_beta_z_val,
                ret_div_1m_5m=ret_div_1m_5m_val,
                ret_div_5m_1h=ret_div_5m_1h_val,
                ret_div_1h_1d=ret_div_1h_1d_val,
                opex_flag=opex_flag_val,
                quad_witching_flag=quad_witching_flag_val,
                earnings_season_flag=earnings_season_flag_val,
                days_since_quarter_end=days_since_quarter_end_val,
                vol_body_product=vol_body_product_val,
                ret_vol_product_fast=ret_vol_product_fast_val,
                price_vol_corr_fast=price_vol_corr_fast_val,
                price_vol_corr_slow=price_vol_corr_slow_val,
                range_vol_product=range_vol_product_val,
                up_vol_body_diff=up_vol_body_diff_val,
                ret_vol_ratio_fast=ret_vol_ratio_fast_val,
                vol_skew_product=vol_skew_product_val,
                momentum_vol_regime_product=momentum_vol_regime_product_val,
                momentum_trend_product=momentum_trend_product_val,
                breakout_volume_product=breakout_volume_product_val,
                reversion_hurst_product=reversion_hurst_product_val,
                quarter_momentum_product=quarter_momentum_product_val,
                variance_ratio_momentum_product=variance_ratio_momentum_product_val,
                illiquidity_momentum_product=illiquidity_momentum_product_val,
                yield_slope_momentum_product=yield_slope_momentum_product_val,
                vix_reversion_product=vix_reversion_product_val,
                efficiency_volume_product=efficiency_volume_product_val,
                canary_noise_gaussian=canary_noise_gaussian_val,
                canary_noise_uniform=canary_noise_uniform_val,
                canary_constant=float(k["canary_constant"][i]),
                canary_near_constant=canary_near_constant_val,
                canary_acausal_placebo=canary_acausal_placebo_val,
            )

            results.append((bar_ts, fv))

            # Advance cache state
            cache.advance_bar(bar_ts, high_, low_, close_, vol_)

        # Theory-Motivated Interactions (Phase 151 Plan 06): emit the guard-
        # substitution tripwire report ONCE per compute_batch() call (never
        # per row -- CLAUDE.md's never-log-per-row-over-the-corpus rule).
        # Emits nothing when every counter is zero (the expected case).
        _report_guard_counted_substitutions()

        return results


def _cold_start_vector(
    cache: FeatureCache,
    tf: str,
    bar_ts: datetime | None = None,
    config: FeatureFactoryConfig | None = None,
) -> FeatureVector:
    """Return a valid FeatureVector with cold-start defaults (0.0 / neutral values).

    bar_ts (Phase 151 Plan 05): optional, supplied only when len(bars) == 1
    (the caller has exactly one bar, so a real timestamp exists even though
    there's no prior bar to derive a return from). opex_flag/quad_witching_flag
    use it to compute real values here rather than a neutral placeholder --
    both are pure functions of bar_ts alone, no history required.

    config (Phase 176 Plan 03, todo 353): optional, needed only by
    earnings_season_flag (its APR window boundaries live on config). When
    bar_ts is not None but config is None, earnings_season_flag falls back
    to the neutral 0.0 placeholder rather than raising -- days_since_quarter_end
    has no config dependency and computes a real value whenever bar_ts is
    available, same as opex_flag/quad_witching_flag.
    """
    if tf == "1d":
        poc_dist_atr = 0.0
        va_position = 0.5
        sr_support_dist = 0.0
        sr_resist_dist = 0.0
    else:
        poc_dist_atr = cache.poc_dist_atr
        va_position = cache.va_position
        sr_support_dist = cache.sr_support_dist
        sr_resist_dist = cache.sr_resist_dist

    return FeatureVector(
        momentum_z_fast=0.0,
        momentum_z_mid=0.0,
        range_position=0.5,
        bar_close_pos=0.5,
        gap_z=0.0,
        momentum_z_slow=0.0,
        momentum_reversal_z=0.0,
        informed_flow=0.0,
        volume_z=0.0,
        ofi_z=0.0,
        ofi_div=0.0,
        cvd_slope_z=0.0,
        cmf=0.0,
        rel_volume=1.0,
        vwap_dev_sigma=0.0,
        atr_z=0.0,
        vol_ratio=1.0,
        poc_dist_atr=poc_dist_atr,
        va_position=va_position,
        sr_support_dist=sr_support_dist,
        sr_resist_dist=sr_resist_dist,
        # Structural VP/SR (17, Phase 163 Plan 02): cold start (len(bars) < 2)
        # has no bar history, so no session has ever accumulated -- neutral
        # None for all 12 new fields is correct here, not a placeholder.
        nearest_hvn_above_dist_atr=None,
        nearest_hvn_below_dist_atr=None,
        nearest_lvn_above_dist_atr=None,
        nearest_lvn_below_dist_atr=None,
        price_in_value_area=None,
        in_lvn=None,
        va_width_atr=None,
        distance_to_vah_atr=None,
        distance_to_val_atr=None,
        nearest_hvn_dist_atr=None,
        poc_rolling_dist_atr=None,
        poc_session_rolling_divergence_atr=None,
        resistance_strength=None,
        support_strength=None,
        resistance_age_bars=None,
        support_age_bars=None,
        sr_level_count=None,
        # regime_writer.py is the sole writer of these 3 columns (todo 207,
        # 2026-07-30) -- see the matching comment at compute()'s call site.
        hmm_regime_prob=None,
        hmm_entropy=None,
        hmm_duration=None,
        hurst=cache.hurst,
        shannon=cache.shannon,
        garch_ratio=cache.garch_ratio,
        hma_slope_z=cache.hma_slope_z,
        adx=cache.adx,
        aroon_fast=0.0,
        aroon_slow=0.0,
        rsi_fast=50.0,
        rsi_mid=50.0,
        rsi_slow=50.0,
        cci_fast=0.0,
        cci_mid=0.0,
        cci_slow=0.0,
        vix_z=cache.vix_z,
        flight_quality=cache.flight_quality,
        yield_slope_z=cache.yield_slope_z,
        in_ny_session=0.0,
        in_london_kz=0.0,
        in_overlap=0.0,
        power_hour=0.0,
        opening_range=0.0,
        above_wk_vwap=cache.above_wk_vwap,
        dow_sin=0.0,
        dow_cos=1.0,
        month_position=1.0,
        quarter_position=0.0,
        days_to_month_end=0.0,
        # Phase 151 Plan 01: _cold_start_vector has no bar_ts (called only when
        # len(bars) < 2), so these follow the same neutral angle=0 convention
        # already used above for dow_sin/dow_cos and below for
        # hour_of_day_sin/cos etc -- sin=0.0, cos=1.0.
        quarter_cycle_sin=0.0,
        quarter_cycle_cos=1.0,
        tdom_sin=0.0,
        tdom_cos=1.0,
        minute_of_hour_sin=0.0,
        minute_of_hour_cos=1.0,
        ctf_momentum=cache.ctf_momentum,
        ctf_vwap_align=cache.ctf_vwap_align,
        ctf_regime_align=cache.ctf_regime_align,
        amihud_illiq_z=0.0,
        high_52w_dist=0.0,
        ret_skew_z=0.0,
        ret_acf1_z=0.0,
        body_ratio=0.0,
        upper_wick_ratio=0.5,
        lower_wick_ratio=0.5,
        range_vs_atr=0.0,
        close_vs_open_direction=0.0,
        overnight_gap=0.0,
        overnight_gap_z=0.0,
        range_efficiency=0.0,
        ret_lag_1=0.0,
        ret_lag_2=0.0,
        ret_lag_3=0.0,
        ret_lag_fast=0.0,
        ret_lag_mid=0.0,
        ret_lag_slow=0.0,
        open_ret=0.0,
        intraday_ret=0.0,
        open_vs_intraday=0.0,
        session_time_pos=0.0,
        hour_of_day_sin=0.0,
        hour_of_day_cos=1.0,
        week_of_month_sin=0.0,
        week_of_month_cos=1.0,
        day_of_month_sin=0.0,
        day_of_month_cos=1.0,
        week_of_year_sin=0.0,
        week_of_year_cos=1.0,
        month_sin=0.0,
        month_cos=1.0,
        vol_acceleration=1.0,
        dollar_vol_z=0.0,
        vol_range_ratio=0.0,
        vol_trend_ratio=0.0,
        up_vol_ratio_fast=0.5,
        up_vol_ratio_slow=0.5,
        vol_percentile=0.5,
        vol_persistence=0.0,
        vol_std_z=0.0,
        mfi_fast=50.0,
        mfi_slow=50.0,
        obv_z=0.0,
        dist_from_high_fast=0.0,
        dist_from_high_slow=0.0,
        dist_from_low_fast=0.0,
        dist_from_low_slow=0.0,
        range_pct_fast=0.0,
        range_pct_slow=0.0,
        stoch_k_fast=0.5,
        stoch_k_slow=0.5,
        price_percentile_fast=0.5,
        price_percentile_slow=0.5,
        efficiency_ratio_fast=0.0,
        efficiency_ratio_slow=0.0,
        ret_kurtosis_z_fast=0.0,
        ret_kurtosis_z_slow=0.0,
        ret_autocorr_1=0.0,
        ret_autocorr_5=0.0,
        updown_ratio_fast=1.0,
        updown_ratio_slow=1.0,
        streak_z=0.0,
        realized_var_ratio_fast=1.0,
        realized_var_ratio_slow=1.0,
        range_to_close=0.0,
        true_range_pct=0.0,
        vol_of_vol=0.0,
        high_low_corr=0.0,
        variance_ratio_fast=1.0,
        variance_ratio_slow=1.0,
        vol_asymmetry_z=0.0,
        bb_pct_b_fast=0.5,
        bb_pct_b_slow=0.5,
        hv_z_fast=0.0,
        hv_z_slow=0.0,
        hv_ratio=1.0,
        parkinson_vol_z=0.0,
        garman_klass_vol_z=0.0,
        yang_zhang_vol_z=0.0,
        parkinson_vol_velocity=0.0,
        garman_klass_vol_velocity=0.0,
        yang_zhang_vol_velocity=0.0,
        vol_velocity_z=0.0,
        intraday_noise_ratio=1.0,
        # Phase 151 Plan 01 Task 2: a velocity is undefined with fewer than 2
        # bars; 0.0 is the correct neutral, matching vol_velocity_z's own
        # cold-start default immediately above.
        momentum_z_velocity_fast=0.0,
        momentum_z_velocity_mid=0.0,
        momentum_z_velocity_slow=0.0,
        vwap_dev_sigma_velocity=0.0,
        # Velocity Primitives Extension (todo 320): a velocity is undefined
        # with fewer than 2 bars; 0.0 is the correct neutral, matching the
        # Phase 151 velocity fields' own cold-start default immediately above.
        rsi_velocity_fast=0.0,
        rsi_velocity_mid=0.0,
        rsi_velocity_slow=0.0,
        ofi_z_velocity=0.0,
        cvd_slope_z_velocity=0.0,
        volume_z_velocity=0.0,
        # Phase 151 Plan 03: _cold_start_vector's `config` parameter (added
        # Phase 176 Plan 03, todo 353, for earnings_season_flag) is Optional
        # and not threaded into the bars_since_* fields below, so the true
        # per-window saturating value (window minus one) still cannot be read
        # from live APR here. Uses each field's seeded APR default window
        # (dist windows fast/slow are 20/50, the 52-week high/low window is
        # 252) as a literal -- the same bare-literal convention every other
        # field in this function already follows for the identical reason.
        bars_since_high_fast=19.0,
        bars_since_high_slow=49.0,
        bars_since_low_fast=19.0,
        bars_since_low_slow=49.0,
        bars_since_52w_high=251.0,
        bars_since_52w_low=251.0,
        bars_since_extreme_move_fast=19.0,
        bars_since_extreme_move_slow=49.0,
        bars_since_vol_spike_fast=19.0,
        bars_since_vol_spike_slow=49.0,
        abs_ret_autocorr_1=0.0,
        # Phase 151 Plan 04: cold start (len(bars) < 2) has no bar history and
        # no symbol context (this function has no `symbol` parameter -- same
        # structural constraint documented at Plan 01/03's cold-start
        # deviations above), so the SPY/TLT self-regression None special-case
        # cannot be applied here. Betas are always None at cold start
        # regardless of symbol -- "not measured" is correct with zero bars,
        # matching the class-level docstring's None-means-not-measured
        # convention (never a fake numeric placeholder).
        tip_tlt_ret_z=0.0,
        hyg_lqd_ret_z=0.0,
        sb_corr_fast=0.0,
        sb_corr_slow=0.0,
        sb_corr_z=0.0,
        equity_beta_z=None,
        rate_beta_z=None,
        # Phase 151 Plan 05: cold start (len(bars) < 2) has no bar history, so
        # the 3 cross-TF divergences (which need a prior/HTF return) are
        # always None here -- "not measured" is correct with zero bars. The 2
        # calendar event flags need only bar_ts (no history), so they compute
        # real values when bar_ts is available (len(bars) == 1); with zero
        # bars there is no timestamp at all, so they fall back to 0.0 (the
        # same neutral convention already used above for dow_sin/cos etc).
        ret_div_1m_5m=None,
        ret_div_5m_1h=None,
        ret_div_1h_1d=None,
        opex_flag=_opex_flag(bar_ts) if bar_ts is not None else 0.0,
        quad_witching_flag=_quad_witching_flag(bar_ts) if bar_ts is not None else 0.0,
        # Earnings-Season Calendar Primitive (Phase 176 Plan 03, todo 353):
        # days_since_quarter_end needs only bar_ts, same as opex_flag/
        # quad_witching_flag above. earnings_season_flag additionally needs
        # config (its APR window lives there) -- falls back to the neutral
        # 0.0 placeholder when config is None, even if bar_ts is available.
        earnings_season_flag=(
            _earnings_season_flag(bar_ts, config)
            if bar_ts is not None and config is not None
            else 0.0
        ),
        days_since_quarter_end=(_days_since_quarter_end(bar_ts) if bar_ts is not None else 0.0),
        # Theory-Motivated Interactions (Phase 151 Plan 06): a product of two
        # cold-start-zero parents is 0.0 -- same convention as vol_body_product
        # etc. immediately below.
        momentum_vol_regime_product=0.0,
        momentum_trend_product=0.0,
        breakout_volume_product=0.0,
        reversion_hurst_product=0.0,
        quarter_momentum_product=0.0,
        variance_ratio_momentum_product=0.0,
        illiquidity_momentum_product=0.0,
        yield_slope_momentum_product=0.0,
        vix_reversion_product=0.0,
        efficiency_volume_product=0.0,
        vol_body_product=0.0,
        ret_vol_product_fast=0.0,
        price_vol_corr_fast=0.0,
        price_vol_corr_slow=0.0,
        range_vol_product=0.0,
        up_vol_body_diff=0.0,
        ret_vol_ratio_fast=0.0,
        vol_skew_product=0.0,
        canary_noise_gaussian=0.0,
        canary_noise_uniform=0.0,
        canary_constant=_CANARY_CONSTANT_VALUE,
        canary_near_constant=_CANARY_CONSTANT_VALUE,
        canary_acausal_placebo=0.0,
        # Smart Money Concepts (36, Phase 164 Plan 01): cold start (len(bars) <
        # 2) has no bar history, so no SMC structure has ever been detected --
        # neutral None for all 36 is correct here, not a placeholder.
        ob_bull_dist_atr=None,
        ob_bear_dist_atr=None,
        ob_strength=None,
        ob_mitigated_flag=None,
        breaker_dist_atr=None,
        breaker_block_active=None,
        ob_mitigation_pct=None,
        fvg_dist_atr=None,
        fvg_size_atr=None,
        fvg_open_count=None,
        sweep_detected=None,
        sweep_strength=None,
        reclaim_velocity=None,
        bars_since_last_sweep=None,
        bsl_dist_atr=None,
        ssl_dist_atr=None,
        bsl_touches=None,
        ssl_touches=None,
        pool_count=None,
        demand_dist_atr=None,
        supply_dist_atr=None,
        demand_freshness=None,
        supply_freshness=None,
        active_demand_zones=None,
        active_supply_zones=None,
        zone_friction_score=None,
        bos_strength=None,
        choch_strength=None,
        bos_direction=None,
        choch_direction=None,
        smc_trend_direction=None,
        bars_since_last_shift=None,
        amd_phase=None,
        amd_manipulation_detected=None,
        amd_distribution_direction=None,
        manip_strength=None,
        # Swing/Fib/Trend/Session Structure (41, Phase 165 Plan 01): cold start
        # (len(bars) < 2) has no bar history, so no swing/trend/fib/session
        # structure has ever been detected -- neutral None for all 41 is
        # correct here, not a placeholder.
        swing_high_dist_atr=None,
        swing_low_dist_atr=None,
        swing_high_type=None,
        swing_low_type=None,
        swing_pattern=None,
        swing_high_age_bars=None,
        swing_low_age_bars=None,
        trend_direction=None,
        trend_strength=None,
        trend_leg_count=None,
        structure_integrity=None,
        price_position=None,
        trend_duration_bars=None,
        swing_amplitude_ratio=None,
        swing_amplitude_expanding=None,
        swing_amplitude_intensity=None,
        swing_velocity_bars=None,
        swing_velocity_bias=None,
        struct_energy=None,
        struct_accel_bias=None,
        swing_volume_confirmation=None,
        nearest_fib_ratio=None,
        nearest_fib_dist_atr=None,
        fib_cluster_strength=None,
        in_fib_discount_zone=None,
        prior_session_high_dist_atr=None,
        prior_session_low_dist_atr=None,
        prior_session_close_dist_atr=None,
        overnight_high_dist_atr=None,
        overnight_low_dist_atr=None,
        overnight_range_pct=None,
        opening_gap_pct=None,
        weekly_pivot_dist_atr=None,
        weekly_r1_dist_atr=None,
        weekly_r2_dist_atr=None,
        weekly_s1_dist_atr=None,
        weekly_s2_dist_atr=None,
        nearest_level_dist_atr=None,
        asian_session_high_dist_atr=None,
        asian_session_low_dist_atr=None,
        gap_filled=None,
        momentum_rank_z=None,
        volume_rank_z=None,
        volatility_rank_z=None,
    )
