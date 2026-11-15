"""FeatureFactoryConfig: the frozen APR-backed parameter container every feature kernel reads.

Built once by a production entrypoint (the rebuild writer `services/backfill_feature_factory.py`,
the streaming `services/feature_vector_pipeline.py`) from ConfigService through `from_values`
and `FEATURE_APR_FIELDS`, the one table of field, APR key, cast and default, and passed to every
kernel compute. It lives outside the streaming `feature_factory` so the rebuild code key hashes
the fields and defaults that shape a stored value without hashing the streaming path.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from src.intelligence.features.kernels._hmm import HmmConfig


@dataclass(frozen=True)
class FeatureFactoryConfig:
    """Frozen APR-backed parameter container for FeatureFactory.compute().

    Built once from ConfigService by a production entrypoint and passed to every kernel
    compute. APR keys (feature.* namespace) map directly to these fields.

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
        atr_normalization_min_pct: APR feature.atr_normalization.min_atr_pct
        ctf_higher_tf_map: APR feature.ctf.higher_tf_map
        ctf_vwap_window: APR feature.ctf.vwap_window
        market_residual_z_window: APR feature.market_residual.z_window
        idiosyncratic_volatility_window: APR feature.idiosyncratic_volatility.window
        market_residual_lag1_acf_window: APR feature.market_residual.lag1_acf_window
        residual_beta_stability_window: APR feature.residual_beta_stability.window
        max_daily_return_window: APR feature.max_daily_return.window
        max_drawdown_window: APR feature.max_drawdown.window
        downside_deviation_window: APR feature.downside_deviation.window
        size_proxy_window: APR feature.size_proxy.window
        dividend_yield_window: APR feature.dividend_yield.window
        high_low_spread_window: APR feature.high_low_spread.window
        roll_spread_window: APR feature.roll_spread.window
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
    # Rolling VWAP window, in HTF bars, behind ctf_vwap_align (todo 584 6b).
    ctf_vwap_window: int = 20  # feature.ctf.vwap_window
    # Item 8 add-list windows (todo 584 D2): the market-residual, return-distribution, size and
    # dividend-yield families. Defaulted like ctf_vwap_window; the two service entrypoints wire them.
    market_residual_z_window: int = 252  # feature.market_residual.z_window
    idiosyncratic_volatility_window: int = 21  # feature.idiosyncratic_volatility.window
    market_residual_lag1_acf_window: int = 63  # feature.market_residual.lag1_acf_window
    residual_beta_stability_window: int = 60  # feature.residual_beta_stability.window
    max_daily_return_window: int = 21  # feature.max_daily_return.window
    max_drawdown_window: int = 252  # feature.max_drawdown.window
    downside_deviation_window: int = 252  # feature.downside_deviation.window
    size_proxy_window: int = 63  # feature.size_proxy.window
    dividend_yield_window: int = 252  # feature.dividend_yield.window
    # Earnings-Season Calendar Primitive (Phase 176 Plan 03, todo 353). Same
    # defaulting rationale as canary_rng_seed above (avoid updating every
    # pre-existing direct FeatureFactoryConfig(...) construction site); the 2
    # real production entrypoints (backfill_feature_factory.py,
    # feature_vector_pipeline.py) explicitly wire these from ConfigService.
    earnings_season_start_days: int = 14  # feature.earnings_season.start_days
    earnings_season_end_days: int = 42  # feature.earnings_season.end_days
    # Spread estimators (todo 553, kernels/liquidity.py, migration 526). Same defaulting
    # rationale as earnings_season_* above; backfill_feature_factory.py and
    # feature_vector_pipeline.py wire both from ConfigService.
    high_low_spread_window: int = 21  # feature.high_low_spread.window
    roll_spread_window: int = 252  # feature.roll_spread.window
    # Amihud z-score (todo 555, migration 534): the share of the window that must hold a valid
    # observation; below it the output is NaN. Defaulted like the keys above; both production
    # entrypoints wire it from ConfigService.
    amihud_min_valid_fraction: float = 0.8  # feature.amihud.min_valid_fraction
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

    @classmethod
    def from_values(cls, get: Callable[[str, Any], Any]) -> FeatureFactoryConfig:
        """The config from APR: `get(key, default)` is `ConfigService.get_sync`. Every field in
        FEATURE_APR_FIELDS is read with its table default and cast; a JSON-object field takes a
        parsed dict or a JSON string (a value of another type falls back to the default). The
        HMM block is declared once in `HmmConfig` and has no defaults (it raises on a missing
        key)."""
        values: dict[str, Any] = {}
        for name, key, cast, default in FEATURE_APR_FIELDS:
            raw = get(key, default)
            values[name] = _json_object(raw, default) if cast is dict else cast(raw)
        return cls(**values, hmm=HmmConfig.from_values(get))

    @staticmethod
    def apr_keys() -> tuple[str, ...]:
        """Every APR key `from_values` reads, the HMM keys included."""
        return (*(key for _, key, _, _ in FEATURE_APR_FIELDS), *HmmConfig.apr_keys())


def _json_object(raw: Any, default: dict) -> dict:
    """A JSON-object APR value: already a dict, or a JSON string (a test or fallback path;
    `load_config_service_sync` parses json-typed keys at load time)."""
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        parsed: dict = json.loads(raw)
        return parsed
    return default


# The one table of the config's APR keys: (field, key, cast, default), in field order. A field
# with a dataclass default carries the same value there (tests build configs directly); a test
# holds the two equal. Changing a default here moves the rebuild code key; changing a live value
# is an APR write and moves the apr_hash instead.
FEATURE_APR_FIELDS: tuple[tuple[str, str, type, Any], ...] = (
    ("momentum_window_fast", "feature.momentum.window_fast", int, 5),
    ("momentum_window_mid", "feature.momentum.window_mid", int, 20),
    ("momentum_window_slow", "feature.momentum.window_slow", int, 60),
    ("momentum_zscore_window", "feature.momentum.zscore_window", int, 252),
    ("volume_zscore_window", "feature.volume.zscore_window", int, 20),
    ("ofi_zscore_window", "feature.ofi.zscore_window", int, 20),
    ("cvd_slope_bars", "feature.cvd.slope_bars", int, 5),
    ("cmf_period", "feature.cmf.period", int, 20),
    ("vol_short_bars", "feature.vol.short_bars", int, 5),
    ("vol_long_bars", "feature.vol.long_bars", int, 20),
    ("hma_period", "feature.hma.period", int, 20),
    ("adx_period", "feature.adx.period", int, 14),
    ("hurst_window", "feature.hurst.window", int, 252),
    ("garch_window", "feature.garch.window", int, 100),
    ("vix_zscore_window", "feature.vix.zscore_window", int, 252),
    ("yield_curve_zscore_window", "feature.yield_curve.zscore_window", int, 252),
    ("regime_cache_refresh_bars", "feature.regime.cache_refresh_bars", int, 30),
    ("rsi_fast_period", "feature.period.rsi.fast", int, 7),
    ("rsi_mid_period", "feature.period.rsi.mid", int, 14),
    ("rsi_slow_period", "feature.period.rsi.slow", int, 28),
    ("cci_fast_period", "feature.period.cci.fast", int, 10),
    ("cci_mid_period", "feature.period.cci.mid", int, 20),
    ("cci_slow_period", "feature.period.cci.slow", int, 40),
    ("aroon_fast_period", "feature.period.aroon.fast", int, 14),
    ("aroon_slow_period", "feature.period.aroon.slow", int, 25),
    ("amihud_zscore_window", "feature.amihud.zscore_window", int, 252),
    ("ret_skew_window", "feature.ret_skew.window", int, 60),
    ("ret_skew_zscore_window", "feature.ret_skew.zscore_window", int, 252),
    ("ret_acf_window", "feature.ret_acf.window", int, 30),
    ("ret_acf_zscore_window", "feature.ret_acf.zscore_window", int, 252),
    ("high_52w_window", "feature.high_52w.window", int, 252),
    ("min_bars_warmup", "feature.cache.min_bars_warmup", int, 16),
    ("cross_asset_rv_window", "feature.cross_asset.rv_window", int, 20),
    ("ny_session_start_utc_hour", "feature.session.ny_start_utc_hour", int, 13),
    ("ny_session_start_utc_minute", "feature.session.ny_start_utc_minute", int, 30),
    ("ny_session_end_utc_hour", "feature.session.ny_end_utc_hour", int, 20),
    ("overlap_start_utc_hour", "feature.session.overlap_start_utc_hour", int, 12),
    ("overlap_end_utc_hour", "feature.session.overlap_end_utc_hour", int, 15),
    ("power_hour_start_utc_hour", "feature.session.power_hour_start_utc_hour", int, 19),
    ("power_hour_end_utc_hour", "feature.session.power_hour_end_utc_hour", int, 21),
    ("opening_range_start_minute", "feature.session.opening_range_start_minute", int, 810),
    ("opening_range_end_minute", "feature.session.opening_range_end_minute", int, 900),
    ("ret_lag_fast", "feature.ret_lag.fast", int, 5),
    ("ret_lag_mid", "feature.ret_lag.mid", int, 20),
    ("ret_lag_slow", "feature.ret_lag.slow", int, 60),
    ("overnight_gap_window", "feature.overnight_gap.window", int, 20),
    ("dollar_vol_window", "feature.dollar_vol.window", int, 20),
    ("vol_range_ratio_window", "feature.vol_range_ratio.window", int, 20),
    ("vol_trend_fast", "feature.vol_trend.fast", int, 5),
    ("vol_trend_slow", "feature.vol_trend.slow", int, 20),
    ("up_vol_ratio_fast", "feature.up_vol_ratio.fast", int, 5),
    ("up_vol_ratio_slow", "feature.up_vol_ratio.slow", int, 20),
    ("vol_percentile_window", "feature.vol_percentile.window", int, 20),
    ("vol_persistence_window", "feature.vol_persistence.window", int, 20),
    ("vol_std_window", "feature.vol_std.window", int, 20),
    ("mfi_fast", "feature.mfi.fast", int, 7),
    ("mfi_slow", "feature.mfi.slow", int, 14),
    ("obv_window", "feature.obv.window", int, 20),
    ("dist_window_fast", "feature.breakout.dist_window_fast", int, 20),
    ("dist_window_slow", "feature.breakout.dist_window_slow", int, 50),
    ("range_window_fast", "feature.breakout.range_window_fast", int, 20),
    ("range_window_slow", "feature.breakout.range_window_slow", int, 50),
    ("stoch_window_fast", "feature.breakout.stoch_window_fast", int, 14),
    ("stoch_window_slow", "feature.breakout.stoch_window_slow", int, 50),
    ("percentile_window_fast", "feature.breakout.percentile_window_fast", int, 50),
    ("percentile_window_slow", "feature.breakout.percentile_window_slow", int, 200),
    ("efficiency_window_fast", "feature.breakout.efficiency_window_fast", int, 10),
    ("efficiency_window_slow", "feature.breakout.efficiency_window_slow", int, 50),
    ("ret_kurtosis_fast", "feature.ret_kurtosis.fast", int, 10),
    ("ret_kurtosis_slow", "feature.ret_kurtosis.slow", int, 40),
    ("ret_kurtosis_zscore_window", "feature.ret_kurtosis.zscore_window", int, 20),
    ("updown_ratio_fast", "feature.updown_ratio.fast", int, 5),
    ("updown_ratio_slow", "feature.updown_ratio.slow", int, 20),
    ("streak_window", "feature.streak.window", int, 20),
    ("realized_var_fast", "feature.realized_var.fast", int, 5),
    ("realized_var_slow", "feature.realized_var.slow", int, 20),
    ("vol_of_vol_window", "feature.vol_of_vol.window", int, 20),
    ("high_low_corr_window", "feature.high_low_corr.window", int, 20),
    ("variance_ratio_fast", "feature.variance_ratio.fast", int, 5),
    ("variance_ratio_slow", "feature.variance_ratio.slow", int, 20),
    ("vol_asymmetry_window", "feature.vol_asymmetry.window", int, 20),
    ("bb_pct_b_fast", "feature.bb_pct_b.fast", int, 20),
    ("bb_pct_b_slow", "feature.bb_pct_b.slow", int, 50),
    ("hv_fast", "feature.hv.fast", int, 10),
    ("hv_slow", "feature.hv.slow", int, 30),
    ("hv_ratio_window", "feature.hv.ratio_window", int, 20),
    ("parkinson_vol_window", "feature.parkinson_vol.window", int, 10),
    ("parkinson_vol_zscore_window", "feature.parkinson_vol.zscore_window", int, 20),
    ("garman_klass_vol_window", "feature.garman_klass_vol.window", int, 10),
    ("garman_klass_vol_zscore_window", "feature.garman_klass_vol.zscore_window", int, 20),
    ("yang_zhang_vol_window", "feature.yang_zhang_vol.window", int, 20),
    ("yang_zhang_vol_zscore_window", "feature.yang_zhang_vol.zscore_window", int, 20),
    ("vol_velocity_window", "feature.vol_velocity.window", int, 20),
    ("intraday_noise_window", "feature.intraday_noise.window", int, 20),
    ("price_vol_corr_fast", "feature.price_vol_corr.fast", int, 10),
    ("price_vol_corr_slow", "feature.price_vol_corr.slow", int, 30),
    ("momentum_velocity_window", "feature.momentum_velocity.window", int, 14),
    ("vwap_velocity_window", "feature.vwap_velocity.window", int, 14),
    ("rsi_velocity_window", "feature.rsi_velocity.window", int, 14),
    ("ofi_velocity_window", "feature.ofi_velocity.window", int, 14),
    ("cvd_velocity_window", "feature.cvd_velocity.window", int, 14),
    ("volume_velocity_window", "feature.volume_velocity.window", int, 14),
    ("extreme_move_sigma_threshold", "feature.bars_since_extreme_move.sigma_threshold", float, 2.0),
    ("vol_spike_threshold", "feature.bars_since_vol_spike.threshold", float, 2.0),
    ("tip_tlt_zscore_window", "feature.tip_tlt.zscore_window", int, 252),
    ("hyg_lqd_zscore_window", "feature.hyg_lqd.zscore_window", int, 252),
    ("sb_corr_window_fast", "feature.sb_corr.window_fast", int, 30),
    ("sb_corr_window_slow", "feature.sb_corr.window_slow", int, 60),
    ("sb_corr_zscore_window", "feature.sb_corr.zscore_window", int, 252),
    ("factor_beta_window", "feature.factor_beta.window", int, 60),
    ("factor_beta_zscore_window", "feature.factor_beta.zscore_window", int, 252),
    ("canary_rng_seed", "alpha.ic.canary_rng_seed", int, 90042),
    ("session_vp_value_area_pct", "feature.session_vp.value_area_pct", float, 0.7),
    ("session_vp_n_buckets", "feature.session_vp.n_buckets", int, 50),
    ("session_vp_hvn_threshold", "feature.session_vp.hvn_threshold", float, 0.8),
    ("session_vp_lvn_threshold", "feature.session_vp.lvn_threshold", float, 0.2),
    ("session_vp_rolling_window", "feature.session_vp.rolling_window", int, 480),
    ("sr_window", "feature.sr.window", int, 10),
    ("sr_cluster_atr_mult", "feature.sr.cluster_atr_mult", float, 0.5),
    (
        "sr_lookback_by_tf",
        "feature.sr.lookback_by_tf",
        dict,
        {"1m": 60, "5m": 60, "15m": 80, "1h": 120, "4h": 90, "1d": 60},
    ),
    ("smc_order_blocks_lookback", "feature.smc.order_blocks.lookback", int, 100),
    ("smc_order_blocks_impulse_bars", "feature.smc.order_blocks.impulse_bars", int, 3),
    (
        "smc_order_blocks_significant_move_pct",
        "feature.smc.order_blocks.significant_move_pct",
        float,
        0.003,
    ),
    (
        "smc_order_blocks_opposing_candle_lookback",
        "feature.smc.order_blocks.opposing_candle_lookback",
        int,
        10,
    ),
    (
        "smc_order_blocks_strength_fallback",
        "feature.smc.order_blocks.strength_fallback",
        float,
        0.5,
    ),
    ("smc_fvg_lookback", "feature.smc.fvg.lookback", int, 100),
    ("smc_liquidity_sweeps_lookback", "feature.smc.liquidity_sweeps.lookback", int, 120),
    ("smc_liquidity_sweeps_swing_neighbor", "feature.smc.liquidity_sweeps.swing_neighbor", int, 5),
    ("smc_liquidity_sweeps_reclaim_bars", "feature.smc.liquidity_sweeps.reclaim_bars", int, 3),
    (
        "smc_liquidity_sweeps_depth_ramp_max_pct",
        "feature.smc.liquidity_sweeps.depth_ramp_max_pct",
        float,
        2.0,
    ),
    (
        "smc_liquidity_sweeps_reclaim_velocity_ramp_max",
        "feature.smc.liquidity_sweeps.reclaim_velocity_ramp_max",
        float,
        0.5,
    ),
    ("smc_liquidity_pools_lookback", "feature.smc.liquidity_pools.lookback", int, 150),
    ("smc_liquidity_pools_swing_neighbor", "feature.smc.liquidity_pools.swing_neighbor", int, 5),
    (
        "smc_liquidity_pools_equal_level_tolerance_atr_mult",
        "feature.smc.liquidity_pools.equal_level_tolerance_atr_mult",
        float,
        0.75,
    ),
    ("smc_liquidity_pools_session_bars", "feature.smc.liquidity_pools.session_bars", int, 390),
    (
        "smc_liquidity_pools_significance_weights",
        "feature.smc.liquidity_pools.significance_weights",
        dict,
        {
            "eq_highs_3": 0.75,
            "eq_lows_3": 0.75,
            "eq_highs_2": 0.6,
            "eq_lows_2": 0.6,
            "session_high": 0.5,
            "session_low": 0.5,
        },
    ),
    ("smc_zones_lookback", "feature.smc.zones.lookback", int, 150),
    ("smc_zones_impulse_atr_mult", "feature.smc.zones.impulse_atr_mult", float, 1.5),
    ("smc_zones_base_body_ratio", "feature.smc.zones.base_body_ratio", float, 0.5),
    ("smc_zones_base_atr_mult", "feature.smc.zones.base_atr_mult", float, 1.0),
    ("smc_zones_max_base_bars", "feature.smc.zones.max_base_bars", int, 5),
    (
        "smc_zones_zone_height_cap_atr_mult",
        "feature.smc.zones.zone_height_cap_atr_mult",
        float,
        2.5,
    ),
    (
        "smc_zones_impulse_overlap_atr_mult",
        "feature.smc.zones.impulse_overlap_atr_mult",
        float,
        0.4,
    ),
    ("smc_zones_freshness_decay_k", "feature.smc.zones.freshness_decay_k", float, 0.5),
    (
        "smc_zones_strength_premium_align_mult",
        "feature.smc.zones.strength_premium_align_mult",
        float,
        1.2,
    ),
    ("smc_zones_strength_fvg_align_mult", "feature.smc.zones.strength_fvg_align_mult", float, 1.15),
    ("smc_zones_age_penalty_floor", "feature.smc.zones.age_penalty_floor", float, 0.7),
    ("smc_zones_age_penalty_window_bars", "feature.smc.zones.age_penalty_window_bars", int, 200),
    ("smc_zones_age_penalty_max_pct", "feature.smc.zones.age_penalty_max_pct", float, 0.3),
    ("smc_zones_max_tracked_zones", "feature.smc.zones.max_tracked_zones", int, 5),
    ("smc_bos_choch_lookback", "feature.smc.bos_choch.lookback", int, 120),
    ("smc_bos_choch_swing_neighbor", "feature.smc.bos_choch.swing_neighbor", int, 5),
    ("swing_pivot_window", "feature.swing.pivot_window", int, 5),
    ("swing_lookback_bars", "feature.swing.lookback_bars", int, 120),
    (
        "trend_structure_atr_strength_divisor",
        "feature.trend_structure.atr_strength_divisor",
        float,
        5.0,
    ),
    ("trend_structure_range_lookback_bars", "feature.trend_structure.range_lookback_bars", int, 20),
    ("swing_momentum_confirm_n", "feature.swing_momentum.confirm_n", int, 3),
    ("swing_momentum_max_extremes", "feature.swing_momentum.max_extremes", int, 6),
    ("swing_momentum_lookback_bars", "feature.swing_momentum.lookback_bars", int, 60),
    ("swing_momentum_reference_bars", "feature.swing_momentum.reference_bars", int, 20),
    ("swing_momentum_speed_factor_min", "feature.swing_momentum.speed_factor_min", float, 0.1),
    ("swing_momentum_speed_factor_max", "feature.swing_momentum.speed_factor_max", float, 3.0),
    ("swing_momentum_energy_divisor", "feature.swing_momentum.energy_divisor", float, 3.0),
    ("swing_momentum_intensity_ramp_lo", "feature.swing_momentum.intensity_ramp_lo", float, 1.0),
    ("swing_momentum_intensity_ramp_hi", "feature.swing_momentum.intensity_ramp_hi", float, 2.0),
    ("fib_cluster_atr_divisor", "feature.fib.cluster_atr_divisor", float, 2.0),
    ("atr_normalization_min_pct", "feature.atr_normalization.min_atr_pct", float, 0.0001),
    (
        "ctf_higher_tf_map",
        "feature.ctf.higher_tf_map",
        dict,
        {"5m": "1h", "15m": "1h", "1h": "1d", "1d": "1d"},
    ),
    ("ctf_vwap_window", "feature.ctf.vwap_window", int, 20),
    ("market_residual_z_window", "feature.market_residual.z_window", int, 252),
    ("idiosyncratic_volatility_window", "feature.idiosyncratic_volatility.window", int, 21),
    ("market_residual_lag1_acf_window", "feature.market_residual.lag1_acf_window", int, 63),
    ("residual_beta_stability_window", "feature.residual_beta_stability.window", int, 60),
    ("max_daily_return_window", "feature.max_daily_return.window", int, 21),
    ("max_drawdown_window", "feature.max_drawdown.window", int, 252),
    ("downside_deviation_window", "feature.downside_deviation.window", int, 252),
    ("size_proxy_window", "feature.size_proxy.window", int, 63),
    ("dividend_yield_window", "feature.dividend_yield.window", int, 252),
    ("earnings_season_start_days", "feature.earnings_season.start_days", int, 14),
    ("earnings_season_end_days", "feature.earnings_season.end_days", int, 42),
    ("high_low_spread_window", "feature.high_low_spread.window", int, 21),
    ("roll_spread_window", "feature.roll_spread.window", int, 252),
    ("amihud_min_valid_fraction", "feature.amihud.min_valid_fraction", float, 0.8),
)
