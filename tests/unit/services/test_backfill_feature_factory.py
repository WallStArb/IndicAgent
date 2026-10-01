"""Unit tests for BackfillFeatureFactory: the fetch stage's helpers, the rebuild unit design
(186-25, D-32a, D-26) and the feature_vectors_v2 rebuild writer (D-28, todo 339).

CI-clean: no live IBKR, no live DB. All DB interactions are faked; the rebuild-writer tests
run the stage's group flow over stub workers and spool files, never the real compute pool.
"""

from __future__ import annotations

import bisect
import dataclasses
import inspect
import math
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

# Ensure project root on sys.path for direct import
sys.path.insert(0, str(Path(__file__).parents[3]))

# Import only the pure-function helpers — no network, no DB
from services import backfill_feature_factory as module
from services.backfill_feature_factory import (
    _BARS_PER_DAY,
    _DEFAULT_CLIENT_ID,
    _TARGET_TIMEFRAMES_DEFAULT,
    _get_target_timeframes,
)
from src.config.config_service import ConfigService
from src.intelligence.feature_factory import FeatureFactory, FeatureFactoryConfig
from src.intelligence.features.contract.registry import compute_kernels, default_registry
from src.intelligence.features.feature_vector_persistence import (
    feature_vector_v2_row_values,
    feature_vectors_v2_numeric_columns,
    feature_vectors_v2_output_columns,
)
from src.intelligence.features.kernels._cache_state import FeatureCache
from src.intelligence.features.kernels.macro import (
    CROSS_ASSET_SYMBOLS,
    CrossAssetRecord,
    bar_ts_ns,
    build_cross_asset_series,
    build_symbol_beta_series,
)
from src.intelligence.schemas import FeatureVector
from tests.unit.intelligence import test_macro_alignment as tma
from tests.unit.intelligence.bar_builders import synthetic_daily_bars

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_config() -> FeatureFactoryConfig:
    """Minimal FeatureFactoryConfig with all fields for testing."""
    return FeatureFactoryConfig(
        momentum_window_fast=5,
        momentum_window_mid=20,
        momentum_window_slow=60,
        momentum_zscore_window=30,
        volume_zscore_window=20,
        ofi_zscore_window=20,
        cvd_slope_bars=5,
        cmf_period=20,
        vol_short_bars=5,
        vol_long_bars=20,
        hma_period=20,
        adx_period=14,
        hurst_window=64,
        garch_window=50,
        vix_zscore_window=30,
        yield_curve_zscore_window=30,
        regime_cache_refresh_bars=10,
        rsi_fast_period=7,
        rsi_mid_period=14,
        rsi_slow_period=28,
        cci_fast_period=10,
        cci_mid_period=20,
        cci_slow_period=40,
        aroon_fast_period=14,
        aroon_slow_period=25,
        amihud_zscore_window=30,
        ret_skew_window=20,
        ret_skew_zscore_window=30,
        ret_acf_window=20,
        ret_acf_zscore_window=30,
        high_52w_window=30,
        min_bars_warmup=16,
        cross_asset_rv_window=20,
        ny_session_start_utc_hour=13,
        ny_session_start_utc_minute=30,
        ny_session_end_utc_hour=20,
        overlap_start_utc_hour=12,
        overlap_end_utc_hour=15,
        london_kz_start_utc_hour=7,
        london_kz_end_utc_hour=10,
        power_hour_start_utc_hour=19,
        power_hour_end_utc_hour=21,
        opening_range_start_minute=810,
        opening_range_end_minute=900,
        ret_lag_fast=5,
        ret_lag_mid=20,
        ret_lag_slow=60,
        overnight_gap_window=20,
        dollar_vol_window=20,
        vol_range_ratio_window=20,
        vol_trend_fast=5,
        vol_trend_slow=20,
        up_vol_ratio_fast=5,
        up_vol_ratio_slow=20,
        vol_percentile_window=20,
        vol_persistence_window=20,
        vol_std_window=20,
        mfi_fast=7,
        mfi_slow=14,
        obv_window=20,
        dist_window_fast=20,
        dist_window_slow=50,
        range_window_fast=20,
        range_window_slow=50,
        stoch_window_fast=14,
        stoch_window_slow=50,
        percentile_window_fast=50,
        percentile_window_slow=200,
        efficiency_window_fast=10,
        efficiency_window_slow=50,
        ret_kurtosis_fast=10,
        ret_kurtosis_slow=40,
        ret_kurtosis_zscore_window=20,
        updown_ratio_fast=5,
        updown_ratio_slow=20,
        streak_window=20,
        realized_var_fast=5,
        realized_var_slow=20,
        vol_of_vol_window=20,
        high_low_corr_window=20,
        variance_ratio_fast=5,
        variance_ratio_slow=20,
        vol_asymmetry_window=20,
        bb_pct_b_fast=20,
        bb_pct_b_slow=50,
        hv_fast=10,
        hv_slow=30,
        hv_ratio_window=20,
        parkinson_vol_window=10,
        parkinson_vol_zscore_window=20,
        garman_klass_vol_window=10,
        garman_klass_vol_zscore_window=20,
        yang_zhang_vol_window=20,
        yang_zhang_vol_zscore_window=20,
        vol_velocity_window=20,
        intraday_noise_window=20,
        price_vol_corr_fast=10,
        price_vol_corr_slow=30,
        momentum_velocity_window=20,
        rsi_velocity_window=20,
        ofi_velocity_window=20,
        cvd_velocity_window=20,
        volume_velocity_window=20,
        vwap_velocity_window=20,
        extreme_move_sigma_threshold=2.0,
        vol_spike_threshold=2.0,
        tip_tlt_zscore_window=20,
        hyg_lqd_zscore_window=20,
        sb_corr_window_fast=10,
        sb_corr_window_slow=20,
        sb_corr_zscore_window=20,
        factor_beta_window=20,
        factor_beta_zscore_window=20,
    )


def _make_bars(n: int = 50) -> list[dict]:
    """Generate synthetic OHLCV bars with a UTC timestamp."""
    from datetime import timedelta

    base_ts = datetime(2025, 1, 2, 14, 30, 0, tzinfo=UTC)
    bars = []
    for i in range(n):
        ts = base_ts + timedelta(minutes=i * 5)
        bars.append(
            {
                "ts": ts,
                "open": 100.0 + i * 0.01,
                "high": 101.0 + i * 0.01,
                "low": 99.0 + i * 0.01,
                "close": 100.5 + i * 0.01,
                "volume": 1000.0 + i,
            }
        )
    return bars


def _make_zero_vector() -> FeatureVector:
    """Return an all-zero FeatureVector for testing."""
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
        poc_dist_atr=0.0,
        va_position=0.5,
        sr_support_dist=0.0,
        sr_resist_dist=0.0,
        # Structural VP/SR (Phase 163 Plan 01) — construction requires these
        # non-optional fields; nullable so None is valid.
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
        hmm_regime_prob=0.0,
        hmm_entropy=0.0,
        hmm_duration=0.0,
        hurst=0.5,
        shannon=1.0,
        garch_ratio=1.0,
        hma_slope_z=0.0,
        adx=0.0,
        aroon_fast=0.0,
        aroon_slow=0.0,
        rsi_fast=50.0,
        rsi_mid=50.0,
        rsi_slow=50.0,
        cci_fast=0.0,
        cci_mid=0.0,
        cci_slow=0.0,
        vix_z=0.0,
        flight_quality=0.0,
        yield_slope_z=0.0,
        in_ny_session=0.0,
        in_london_kz=0.0,
        in_overlap=0.0,
        power_hour=0.0,
        opening_range=0.0,
        above_wk_vwap=0.0,
        dow_sin=0.0,
        dow_cos=1.0,
        month_position=1.0,
        quarter_position=0.0,
        days_to_month_end=0.0,
        quarter_cycle_sin=0.0,
        quarter_cycle_cos=1.0,
        tdom_sin=0.0,
        tdom_cos=1.0,
        minute_of_hour_sin=0.0,
        minute_of_hour_cos=1.0,
        momentum_z_velocity_fast=0.0,
        momentum_z_velocity_mid=0.0,
        momentum_z_velocity_slow=0.0,
        vwap_dev_sigma_velocity=0.0,
        rsi_velocity_fast=0.0,
        rsi_velocity_mid=0.0,
        rsi_velocity_slow=0.0,
        ofi_z_velocity=0.0,
        cvd_slope_z_velocity=0.0,
        volume_z_velocity=0.0,
        earnings_season_flag=0.0,
        days_since_quarter_end=0.0,
        bars_since_high_fast=0.0,
        bars_since_high_slow=0.0,
        bars_since_low_fast=0.0,
        bars_since_low_slow=0.0,
        bars_since_52w_high=0.0,
        bars_since_52w_low=0.0,
        bars_since_extreme_move_fast=0.0,
        bars_since_extreme_move_slow=0.0,
        bars_since_vol_spike_fast=0.0,
        bars_since_vol_spike_slow=0.0,
        abs_ret_autocorr_1=0.0,
        tip_tlt_ret_z=0.0,
        hyg_lqd_ret_z=0.0,
        sb_corr_fast=0.0,
        sb_corr_slow=0.0,
        sb_corr_z=0.0,
        equity_beta_z=0.0,
        rate_beta_z=0.0,
        ret_div_1m_5m=None,
        ret_div_5m_1h=None,
        ret_div_1h_1d=None,
        opex_flag=0.0,
        quad_witching_flag=0.0,
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
        ctf_momentum=0.0,
        ctf_vwap_align=0.0,
        ctf_regime_align=0.0,
        amihud_illiq_z=0.0,
        high_52w_dist=0.0,
        ret_skew_z=0.0,
        ret_acf1_z=0.0,
        # Renaissance Primitives (Phase 142.5 Plan 01) — not yet in the persisted
        # tuple (migration 206 / writer wiring land in a later plan); construction
        # requires these non-optional fields.
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
        # Renaissance Primitives (Phase 142.5 Plan 02) — not yet in the persisted
        # tuple (migration 206 / writer wiring land in a later plan); construction
        # requires these non-optional fields.
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
        vol_trend_ratio=1.0,
        up_vol_ratio_fast=0.5,
        up_vol_ratio_slow=0.5,
        vol_percentile=0.5,
        vol_persistence=0.0,
        vol_std_z=0.0,
        mfi_fast=50.0,
        mfi_slow=50.0,
        obv_z=0.0,
        # Renaissance Primitives (Phase 142.5 Plan 05) — not yet in the persisted
        # tuple (migration 206 / writer wiring land in a later plan); construction
        # requires these non-optional fields.
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
        # Renaissance Primitives (Phase 142.5 Plan 03) — not yet in the persisted
        # tuple (migration 206 / writer wiring land in a later plan); construction
        # requires these non-optional fields.
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
        # Renaissance Primitives (Phase 142.5 Plan 04) — not yet in the persisted
        # tuple (migration 206 / writer wiring land in a later plan); construction
        # requires these non-optional fields.
        parkinson_vol_z=0.0,
        garman_klass_vol_z=0.0,
        yang_zhang_vol_z=0.0,
        parkinson_vol_velocity=0.0,
        garman_klass_vol_velocity=0.0,
        yang_zhang_vol_velocity=0.0,
        vol_velocity_z=0.0,
        intraday_noise_ratio=1.0,
        # Renaissance Primitives (Phase 142.5 Plan 05.5) — not yet in the
        # persisted tuple (migration 206 / writer wiring land in a later
        # plan); construction requires these non-optional fields.
        vol_body_product=0.0,
        ret_vol_product_fast=0.0,
        price_vol_corr_fast=0.0,
        price_vol_corr_slow=0.0,
        range_vol_product=0.0,
        up_vol_body_diff=0.0,
        ret_vol_ratio_fast=0.0,
        vol_skew_product=0.0,
        # Swing/Fib/Trend/Session Structure (Phase 165 Plan 01) — construction
        # requires these non-optional fields; nullable so None is valid.
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
    )


# Test 1: Default client-id is 40
# ---------------------------------------------------------------------------


def test_default_client_id_is_40() -> None:
    """IBKR client-id must default to 40 (T2 mitigation)."""
    assert _DEFAULT_CLIENT_ID == 40


def test_bars_per_day_values() -> None:
    """Verify _BARS_PER_DAY constants match objective specification."""
    assert _BARS_PER_DAY["5m"] == 78
    assert _BARS_PER_DAY["15m"] == 26
    assert _BARS_PER_DAY["1h"] == 6
    assert _BARS_PER_DAY["1d"] == 1


# ---------------------------------------------------------------------------
# Fetch resume: run_fetch_stage skips IBKR download for fetch_complete=true pairs
# ---------------------------------------------------------------------------


def test_fetch_resume_skips_fetch_complete_pairs() -> None:
    """run_fetch_stage must skip IBKR download for pairs with fetch_complete=true."""
    import asyncio

    settings = MagicMock()
    settings.ib_host = "127.0.0.1"
    settings.ib_port = 7497
    settings.database_url = "postgresql://fake"

    mock_instrument = MagicMock()
    mock_instrument.symbol = "SPY"
    mock_instrument.asset_class = "equity"

    mock_conn = MagicMock()
    mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=MagicMock())
    mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

    # All TFs fetch_complete=true
    status_map = {
        ("SPY", tf): {"fetch_complete": True, "status": "complete"}
        for tf in _TARGET_TIMEFRAMES_DEFAULT
    }

    async def _async_true() -> bool:
        return True

    async def _async_none() -> None:
        return None

    async def _async_instrument(_: object) -> bool:
        return True

    mock_provider = MagicMock()
    mock_provider.connect = MagicMock(side_effect=_async_true)
    mock_provider.disconnect = MagicMock(side_effect=_async_none)
    mock_provider.qualify_instrument = MagicMock(side_effect=_async_instrument)
    mock_provider.fetch_historical_bars = MagicMock(
        side_effect=AssertionError("fetch_historical_bars should NOT be called")
    )

    from services.backfill_feature_factory import run_fetch_stage

    with (
        patch(
            "services.backfill_feature_factory.get_active_contracts",
            return_value=[mock_instrument],
        ),
        patch(
            "services.backfill_feature_factory._load_config_service",
            return_value=MagicMock(),
        ),
        patch(
            "services.backfill_feature_factory._load_status_map",
            return_value=status_map,
        ),
        patch(
            "services.backfill_feature_factory.IBKRProvider",
            return_value=mock_provider,
        ),
    ):
        # Should complete without calling fetch_historical_bars
        asyncio.run(
            run_fetch_stage(
                settings=settings,
                client_id=_DEFAULT_CLIENT_ID,
                symbols=["SPY"],
                db_conn=mock_conn,
            )
        )

    # If we reached here without AssertionError, fetch was correctly skipped


# ---------------------------------------------------------------------------
# Test 7: target TFs are exactly 5m, 15m, 1h, 1d (no 1m)
# ---------------------------------------------------------------------------


def test_target_tfs_excludes_1m() -> None:
    """1m is NOT a backfill target — live pipeline owns 1m."""
    assert "1m" not in _TARGET_TIMEFRAMES_DEFAULT
    assert set(_TARGET_TIMEFRAMES_DEFAULT) == {"5m", "15m", "1h", "1d"}


def test_get_target_timeframes_defaults_when_apr_key_absent() -> None:
    """todo 199: feature.factory.target_timeframes must fall back to the exact prior
    hardcoded _TARGET_TIMEFRAMES value when the APR key is unset in config_state --
    a bare ConfigService with an empty cache (no DB load) reproduces that "key absent"
    condition, since ConfigService.get_sync() is a plain cache.get(key, default)."""
    cfg = ConfigService(database_url="")
    assert _get_target_timeframes(cfg) == ["5m", "15m", "1h", "1d"]
    assert _get_target_timeframes(cfg) == _TARGET_TIMEFRAMES_DEFAULT


def test_get_target_timeframes_honors_apr_override() -> None:
    """An explicit config_state value must win over the hardcoded default -- this is
    the entire point of the APR migration (todo 199): an operator can reconfigure
    which timeframes get processed without a code change."""
    cfg = ConfigService(database_url="")
    cfg._cache["feature.factory.target_timeframes"] = ["5m", "1h"]
    assert _get_target_timeframes(cfg) == ["5m", "1h"]


# ---------------------------------------------------------------------------
# Test 8: FeatureFactory.compute() integration with synthetic bars (no network/DB)
# ---------------------------------------------------------------------------


def test_feature_factory_compute_returns_valid_vector() -> None:
    """FeatureFactory.compute() with 50 synthetic bars returns a valid FeatureVector."""
    config = _make_config()
    cache = FeatureCache()
    bars = _make_bars(50)

    fv = FeatureFactory.compute(bars, "SPY", "5m", cache, config)

    # Check it's a FeatureVector
    assert isinstance(fv, FeatureVector)

    # All required fields are finite floats; Optional cross-sectional fields may be None.
    import dataclasses
    import math

    for field in dataclasses.fields(fv):
        val = getattr(fv, field.name)
        # Optional fields (momentum_rank_z, volume_rank_z, volatility_rank_z) are
        # None until batch cross-sectional enrichment; skip them.
        if val is None:
            continue
        assert isinstance(val, float), f"{field.name} should be float, got {type(val)}"
        assert math.isfinite(val), f"{field.name} should be finite, got {val}"


def test_feature_factory_cold_start_returns_vector() -> None:
    """FeatureFactory.compute() with only 1 bar returns cold-start defaults (no crash)."""
    config = _make_config()
    cache = FeatureCache()
    bars = _make_bars(1)

    fv = FeatureFactory.compute(bars, "SPY", "5m", cache, config)
    assert isinstance(fv, FeatureVector)


# ---------------------------------------------------------------------------
# Test 9: build_cross_asset_series — O(D) incremental parity
# ---------------------------------------------------------------------------


_make_daily_bars = synthetic_daily_bars


def _reference_cross_asset_series(
    spy_bars, tlt_bars, shy_bars, tip_bars, hyg_bars, lqd_bars, config
) -> dict:
    """Original O(D×N) implementation — reference for parity testing.

    Only asserts on the 3 pre-existing macro fields (vix_z/flight_quality/
    yield_slope_z); tip/hyg/lqd bars are required by update_cross_asset()'s
    Phase 151 Plan 04 signature but not checked here (no regression on the
    3 legacy fields is this reference's entire purpose).
    """
    spy_dates = [b["ts"].date() for b in spy_bars]
    tlt_dates = [b["ts"].date() for b in tlt_bars]
    shy_dates = [b["ts"].date() for b in shy_bars]
    all_dates = sorted(set(spy_dates) | set(tlt_dates) | set(shy_dates))
    cache = FeatureCache()
    result = {}
    for d in all_dates:
        spy_end = bisect.bisect_right(spy_dates, d)
        tlt_end = bisect.bisect_right(tlt_dates, d)
        shy_end = bisect.bisect_right(shy_dates, d)
        if spy_end < 2 or tlt_end < 2 or shy_end < 2:
            continue
        cache.update_cross_asset(
            spy_bars[:spy_end],
            tlt_bars[:tlt_end],
            shy_bars[:shy_end],
            tip_bars,
            hyg_bars,
            lqd_bars,
            config,
        )
        result[d] = (cache.vix_z, cache.flight_quality, cache.yield_slope_z)
    return result


class TestBuildCrossAssetSeries:
    def test_parity_with_reference_implementation(self) -> None:
        """New incremental O(D) implementation must produce identical values to O(D×N)
        reference on the 3 pre-existing macro fields -- no regression from Phase 151
        Plan 04's 5-field extension. Also asserts the return type is CrossAssetRecord."""
        from src.intelligence.features.kernels.macro import build_cross_asset_series

        config = _make_config()
        spy = _make_daily_bars(300, seed=1, start_close=450.0)
        tlt = _make_daily_bars(300, seed=2, start_close=95.0)
        shy = _make_daily_bars(300, seed=3, start_close=86.0)
        tip = _make_daily_bars(300, seed=4, start_close=110.0)
        hyg = _make_daily_bars(300, seed=5, start_close=78.0)
        lqd = _make_daily_bars(300, seed=6, start_close=112.0)

        reference = _reference_cross_asset_series(spy, tlt, shy, tip, hyg, lqd, config)
        result = build_cross_asset_series(spy, tlt, shy, tip, hyg, lqd, config)

        assert set(result.keys()) == set(reference.keys()), "date keys differ"
        for d in reference:
            ref_vix, ref_fq, ref_ys = reference[d]
            res = result[d]
            assert isinstance(
                res, CrossAssetRecord
            ), f"{d}: result is {type(res)}, not CrossAssetRecord"
            assert abs(res.vix_z - ref_vix) < 1e-10, f"{d}: vix_z {res.vix_z} != {ref_vix}"
            assert (
                abs(res.flight_quality - ref_fq) < 1e-10
            ), f"{d}: flight_quality {res.flight_quality} != {ref_fq}"
            assert (
                abs(res.yield_slope_z - ref_ys) < 1e-10
            ), f"{d}: yield_slope_z {res.yield_slope_z} != {ref_ys}"

    def test_all_values_finite(self) -> None:
        from src.intelligence.features.kernels.macro import build_cross_asset_series

        config = _make_config()
        spy = _make_daily_bars(50, seed=10)
        tlt = _make_daily_bars(50, seed=11)
        shy = _make_daily_bars(50, seed=12)
        tip = _make_daily_bars(50, seed=13)
        hyg = _make_daily_bars(50, seed=14)
        lqd = _make_daily_bars(50, seed=15)
        result = build_cross_asset_series(spy, tlt, shy, tip, hyg, lqd, config)
        first = min(result)
        for d, values in result.items():
            for field_name in CrossAssetRecord._fields:
                v = getattr(values, field_name)
                if d == first and field_name in ("tip_tlt_ret_z", "hyg_lqd_ret_z"):
                    # no previous TIP/HYG/LQD close is tracked yet on the first record date
                    # (todo 464): missing, not a fabricated 0.0
                    assert math.isnan(v), f"{d}: {field_name} should be missing"
                    continue
                assert math.isfinite(v), f"{d}: {field_name} not finite"

    def test_tip_hyg_lqd_partial_coverage_emits_nan_not_zero_and_not_skip(self) -> None:
        """Dates with SPY/TLT/SHY coverage but no TIP/HYG/LQD coverage (pre-listing
        dates) must still emit vix_z/yield_slope_z -- TIP/HYG/LQD unavailability
        must NOT skip the whole date, and the affected spread fields are missing (NaN,
        no_fill), never a fabricated 0.0 z-score."""
        from src.intelligence.features.kernels.macro import build_cross_asset_series

        config = _make_config()
        spy = _make_daily_bars(60, seed=20)
        tlt = _make_daily_bars(60, seed=21)
        shy = _make_daily_bars(60, seed=22)
        # TIP/HYG/LQD only have bars for the LAST 20 days (simulating late listing).
        tip = _make_daily_bars(60, seed=23)[-20:]
        hyg = _make_daily_bars(60, seed=24)[-20:]
        lqd = _make_daily_bars(60, seed=25)[-20:]

        result = build_cross_asset_series(spy, tlt, shy, tip, hyg, lqd, config)
        early_dates = sorted(result.keys())[:10]
        assert early_dates, "expected early dates with SPY/TLT/SHY-only coverage"
        for d in early_dates:
            values = result[d]
            assert math.isnan(values.tip_tlt_ret_z)
            assert math.isnan(values.hyg_lqd_ret_z)
            # vix_z/yield_slope_z are NOT forced to 0.0 -- SPY/TLT/SHY coverage
            # is unaffected by TIP/HYG/LQD's absence.
            assert math.isfinite(values.vix_z)
            assert math.isfinite(values.yield_slope_z)


# ---------------------------------------------------------------------------
# Test 10: compute_batch external state injection
# ---------------------------------------------------------------------------


class TestComputeBatchExternalInjection:
    def test_cross_asset_from_dict_not_cache(self) -> None:
        """When cross_asset_by_date supplied, FeatureVector uses dict values not cache zeros.

        186-12: the record is aligned as-of the row's bar end (a daily record is available from the
        16:00 ET close of its date), so it is keyed on the day before the bars. Keyed on the bars'
        own date it would not reach any intraday row before that day's close (same-day lookahead
        fix).
        """
        config = _make_config()
        cache = FeatureCache()  # vix_z=0.0, flight_quality=0.0, yield_slope_z=0.0

        bars = _make_bars(60)
        record_date = bars[-1]["ts"].date() - timedelta(days=1)
        cross_asset = {
            record_date: CrossAssetRecord(vix_z=1.23, flight_quality=0.45, yield_slope_z=-0.67)
        }

        results = FeatureFactory.compute_batch(
            bars,
            "SPY",
            "5m",
            cache,
            config,
            warm_up_bars=5,
            cross_asset_by_date=cross_asset,
        )
        assert results, "no results returned"
        _, fv = results[-1]
        assert abs(fv.vix_z - 1.23) < 1e-10, f"vix_z={fv.vix_z}, expected 1.23"
        assert abs(fv.flight_quality - 0.45) < 1e-10
        assert abs(fv.yield_slope_z - -0.67) < 1e-10

    def test_vp_computed_from_ohlcv_in_batch_mode(self) -> None:
        """VP fields are computed from OHLCV in batch mode too (D-05 fix, Phase 163 Plan 02).

        Prior to Plan 02, cross_asset_by_date being provided (the batch-path signal)
        forced poc_dist_atr/va_position/sr_support_dist/sr_resist_dist to None under a
        stale, never-verified assumption that VP required tick-data injection. VP is
        now computed for real via FeatureCache.update_session_vp(), called once per
        bar inside compute_batch()'s loop -- identical mechanism to the live path.
        sr_support_dist/sr_resist_dist are computed inline via _compute_sr_dist_atr()
        (Phase 163 Plan 03) -- no longer a flat cache read, always finite.
        """
        config = _make_config()
        cache = FeatureCache()
        bars = _make_bars(60)
        cross_asset = {}  # empty — all dates fall back to (0,0,0), irrelevant to VP

        results = FeatureFactory.compute_batch(
            bars,
            "SPY",
            "5m",
            cache,
            config,
            warm_up_bars=5,
            cross_asset_by_date=cross_asset,
        )
        assert results
        poc_dist_atr_vals = [fv.poc_dist_atr for _, fv in results]
        assert any(v is not None for v in poc_dist_atr_vals), "VP still forced None in batch mode"
        va_position_vals = [fv.va_position for _, fv in results]
        assert all(v is not None and 0.0 <= v <= 1.0 for v in va_position_vals)
        for _, fv in results:
            assert math.isfinite(fv.sr_support_dist)
            assert math.isfinite(fv.sr_resist_dist)

    def test_live_path_unchanged_reads_from_cache(self) -> None:
        """When cross_asset_by_date=None (default), cache values flow into FeatureVector."""
        config = _make_config()
        cache = FeatureCache()
        cache.vix_z = 9.99
        cache.flight_quality = 8.88
        cache.yield_slope_z = 7.77

        bars = _make_bars(60)
        results = FeatureFactory.compute_batch(bars, "SPY", "5m", cache, config, warm_up_bars=5)
        assert results
        _, fv = results[-1]
        assert abs(fv.vix_z - 9.99) < 1e-10
        assert abs(fv.flight_quality - 8.88) < 1e-10
        assert abs(fv.yield_slope_z - 7.77) < 1e-10


# ---------------------------------------------------------------------------
# Test 11: build_symbol_beta_series (Phase 151 Plan 04, todo 180)
# ---------------------------------------------------------------------------


class TestBuildSymbolBetaSeries:
    def test_spy_equity_beta_z_always_none(self) -> None:
        """symbol='SPY' must yield equity_beta_z=None at every date (self-regression
        against itself is degenerate -- beta identically 1)."""
        from src.intelligence.features.kernels.macro import build_symbol_beta_series

        config = _make_config()
        spy = _make_daily_bars(120, seed=1, start_close=450.0)
        tlt = _make_daily_bars(120, seed=2, start_close=95.0)

        result = build_symbol_beta_series(spy, spy, tlt, "SPY", config)
        assert result, "expected at least one date"
        for _d, (equity_beta_z, _rate_beta_z) in result.items():
            assert equity_beta_z is None

    def test_tlt_rate_beta_z_always_none(self) -> None:
        """symbol='TLT' must yield rate_beta_z=None at every date."""
        from src.intelligence.features.kernels.macro import build_symbol_beta_series

        config = _make_config()
        spy = _make_daily_bars(120, seed=1, start_close=450.0)
        tlt = _make_daily_bars(120, seed=2, start_close=95.0)

        result = build_symbol_beta_series(tlt, spy, tlt, "TLT", config)
        assert result, "expected at least one date"
        for _d, (_equity_beta_z, rate_beta_z) in result.items():
            assert rate_beta_z is None

    def test_non_proxy_symbol_yields_finite_betas(self) -> None:
        """A symbol that is neither SPY nor TLT gets finite (non-None) betas for
        both factors once enough history has accumulated."""
        from src.intelligence.features.kernels.macro import build_symbol_beta_series

        config = _make_config()
        sym = _make_daily_bars(120, seed=3, start_close=200.0)
        spy = _make_daily_bars(120, seed=1, start_close=450.0)
        tlt = _make_daily_bars(120, seed=2, start_close=95.0)

        result = build_symbol_beta_series(sym, spy, tlt, "XYZ", config)
        assert result, "expected at least one date"
        last_date = sorted(result.keys())[-1]
        equity_beta_z, rate_beta_z = result[last_date]
        assert equity_beta_z is not None and math.isfinite(equity_beta_z)
        assert rate_beta_z is not None and math.isfinite(rate_beta_z)


# ---------------------------------------------------------------------------
# Test 12: _build_ltf_return_series (Phase 151 Plan 05, todo 066)
# ---------------------------------------------------------------------------


class TestBuildLtfReturnSeries:
    def test_never_derives_from_a_1m_bar_strictly_after_target_ts(self) -> None:
        """Causality guard (T-151-10): no returned value may be derived from a
        1m bar whose own ts is strictly after the target 5m bar's ts."""
        from src.intelligence.features.kernels.cross_tf import _build_ltf_return_series

        base = datetime(2026, 1, 2, 14, 30, 0, tzinfo=UTC)
        ltf_bars = [
            {"ts": base + timedelta(minutes=i), "close": 100.0 + i * 0.1} for i in range(20)
        ]
        target_ts_list = [base + timedelta(minutes=i) for i in (2, 7, 12, 17, 25)]

        result = _build_ltf_return_series(ltf_bars, target_ts_list)

        assert result, "expected at least one entry"
        for target_ts in result:
            eligible = [b for b in ltf_bars if b["ts"] <= target_ts]
            assert eligible, f"no eligible 1m bar for {target_ts}, should not be in result"
            last_eligible_ts = eligible[-1]["ts"]
            assert last_eligible_ts <= target_ts, (
                f"selected 1m bar ts {last_eligible_ts} is after target {target_ts} "
                "-- lookahead bias"
            )

    def test_matches_manual_log_return_at_exact_bar_boundary(self) -> None:
        """When target_ts exactly matches a 1m bar's own ts, the returned value
        must be log(close[k] / close[k-1]) for that bar."""
        from src.intelligence.features.kernels.cross_tf import _build_ltf_return_series

        base = datetime(2026, 1, 2, 14, 30, 0, tzinfo=UTC)
        closes = [100.0, 101.0, 99.5, 102.0]
        ltf_bars = [{"ts": base + timedelta(minutes=i), "close": c} for i, c in enumerate(closes)]
        target_ts_list = [base + timedelta(minutes=3)]

        result = _build_ltf_return_series(ltf_bars, target_ts_list)
        expected = math.log(closes[3] / closes[2])
        assert result[target_ts_list[0]] == pytest.approx(expected, abs=1e-12)

    def test_no_entry_before_any_eligible_1m_bar(self) -> None:
        """A target_ts strictly before the first 1m bar's ts yields no entry."""
        from src.intelligence.features.kernels.cross_tf import _build_ltf_return_series

        base = datetime(2026, 1, 2, 14, 30, 0, tzinfo=UTC)
        ltf_bars = [{"ts": base + timedelta(minutes=i), "close": 100.0 + i} for i in range(5)]
        target_ts_list = [base - timedelta(minutes=1)]

        result = _build_ltf_return_series(ltf_bars, target_ts_list)
        assert target_ts_list[0] not in result

    def test_empty_inputs_return_empty_dict(self) -> None:
        from src.intelligence.features.kernels.cross_tf import _build_ltf_return_series

        assert _build_ltf_return_series([], [datetime(2026, 1, 1, tzinfo=UTC)]) == {}
        assert (
            _build_ltf_return_series([{"ts": datetime(2026, 1, 1, tzinfo=UTC), "close": 1.0}], [])
            == {}
        )


class TestRestrictTimeframes:
    """Todo 421: --tf narrows the APR timeframe set; an unknown tf is an error."""

    def test_none_keeps_the_configured_set(self):
        from services.backfill_feature_factory import _restrict_timeframes

        assert _restrict_timeframes(["5m", "15m", "1h", "1d"], None) == ["5m", "15m", "1h", "1d"]

    def test_narrows_in_configured_order(self):
        from services.backfill_feature_factory import _restrict_timeframes

        assert _restrict_timeframes(["5m", "15m", "1h", "1d"], ["1d", "5m"]) == ["5m", "1d"]

    def test_unknown_tf_raises(self):
        import pytest

        from services.backfill_feature_factory import _restrict_timeframes

        with pytest.raises(ValueError, match="1m"):
            _restrict_timeframes(["5m", "1d"], ["1m"])


# ---------------------------------------------------------------------------
# Rebuild unit design (186-25, D-32a, D-26)
# ---------------------------------------------------------------------------


class TestRebuildUnitDesign:
    def test_split_symbol_chunks_is_sorted_deterministic_and_covers_all(self) -> None:
        from services.backfill_feature_factory import split_symbol_chunks

        symbols = ["QQQ", "SPY", "AAPL", "TLT", "IWM", "SPY"]
        chunks = split_symbol_chunks(symbols, 2)
        assert chunks == [("AAPL", "IWM"), ("QQQ", "SPY"), ("TLT",)]
        assert split_symbol_chunks(list(reversed(symbols)), 2) == chunks
        assert [s for chunk in chunks for s in chunk] == sorted(set(symbols))
        with pytest.raises(ValueError, match="at least 1"):
            split_symbol_chunks(symbols, 0)

    def test_intraday_ranges_are_calendar_years_without_gaps_or_overlaps(self) -> None:
        from services.backfill_feature_factory import rebuild_unit_ranges

        first = datetime(2018, 6, 4, 13, 30, tzinfo=UTC)
        horizon = datetime(2021, 3, 1, tzinfo=UTC)
        ranges = rebuild_unit_ranges("5m", first, horizon)
        assert ranges == [
            (datetime(2018, 1, 1, tzinfo=UTC), datetime(2019, 1, 1, tzinfo=UTC)),
            (datetime(2019, 1, 1, tzinfo=UTC), datetime(2020, 1, 1, tzinfo=UTC)),
            (datetime(2020, 1, 1, tzinfo=UTC), datetime(2021, 1, 1, tzinfo=UTC)),
            (datetime(2021, 1, 1, tzinfo=UTC), horizon),
        ]
        for (_, end), (start, _) in zip(ranges, ranges[1:], strict=False):
            assert end == start
        assert all(s.tzinfo is not None and e.tzinfo is not None for s, e in ranges)

    def test_daily_is_one_range_per_chunk(self) -> None:
        from services.backfill_feature_factory import rebuild_unit_ranges

        first = datetime(2006, 6, 2, tzinfo=UTC)
        horizon = datetime(2026, 10, 1, tzinfo=UTC)
        assert rebuild_unit_ranges("1d", first, horizon) == [
            (datetime(2006, 1, 1, tzinfo=UTC), horizon)
        ]

    def test_ranges_empty_when_first_bar_is_at_or_after_the_horizon(self) -> None:
        from services.backfill_feature_factory import rebuild_unit_ranges

        ts = datetime(2026, 10, 1, tzinfo=UTC)
        assert rebuild_unit_ranges("5m", ts, ts) == []

    def test_ranges_refuse_naive_datetimes(self) -> None:
        from services.backfill_feature_factory import rebuild_unit_ranges

        with pytest.raises(ValueError, match="tz-aware"):
            rebuild_unit_ranges("5m", datetime(2020, 1, 1), datetime(2021, 1, 1, tzinfo=UTC))

    def test_fetch_window_is_never_shorter_than_the_bars_it_must_hold(self) -> None:
        from services.backfill_feature_factory import bars_to_fetch_window

        # 5m: 78 regular-session bars a day, so 780 bars is at least 10 trading days; a bare
        # 780 * 300 s would be 2.7 wall-clock hours and cover no more than one session.
        window = bars_to_fetch_window("5m", 780)
        assert window >= timedelta(days=14)
        assert bars_to_fetch_window("1d", 5) >= timedelta(days=7)
        assert bars_to_fetch_window("5m", 0) == timedelta(0)
        with pytest.raises(ValueError, match="bars-per-day"):
            bars_to_fetch_window("4h", 10)

    def test_fetch_start_uses_declared_memory_for_stateless_contributors(self) -> None:
        from services.backfill_feature_factory import bars_to_fetch_window, unit_fetch_start
        from src.intelligence.features.contract.registry import default_registry

        registry = default_registry()
        config = _make_config()
        series_start = datetime(2010, 1, 4, tzinfo=UTC)
        range_start = datetime(2015, 1, 1, tzinfo=UTC)
        # atr_z has a finite declared memory (no path-dependent upstream).
        memory = registry.effective_memory_bars(registry.by_output("atr_z").name, config)
        assert memory > 0
        got = unit_fetch_start(registry, ["atr_z"], "5m", range_start, series_start, config)
        assert got == range_start - bars_to_fetch_window("5m", memory)
        assert series_start < got < range_start
        # The deepest-memory column of a set wins.
        deeper = unit_fetch_start(
            registry, ["atr_z", "supply_dist_atr"], "5m", range_start, series_start, config
        )
        assert deeper < got

    def test_fetch_start_never_precedes_the_series_start(self) -> None:
        from services.backfill_feature_factory import unit_fetch_start
        from src.intelligence.features.contract.registry import default_registry

        series_start = datetime(2015, 1, 5, tzinfo=UTC)
        got = unit_fetch_start(
            default_registry(),
            ["supply_dist_atr"],
            "5m",
            datetime(2015, 1, 6, tzinfo=UTC),
            series_start,
            _make_config(),
        )
        assert got == series_start

    def test_fetch_start_is_the_series_start_for_a_path_dependent_contributor(self) -> None:
        from services.backfill_feature_factory import (
            path_dependent_contributors,
            unit_fetch_start,
        )
        from src.intelligence.features.contract.registry import default_registry

        registry = default_registry()
        series_start = datetime(2010, 1, 4, tzinfo=UTC)
        got = unit_fetch_start(
            registry,
            ["atr_z", "regime"],
            "5m",
            datetime(2020, 1, 1, tzinfo=UTC),
            series_start,
            _make_config(),
        )
        assert got == series_start
        assert path_dependent_contributors(registry, ["atr_z"]) == ()
        assert "hmm_trend_walk_forward" in path_dependent_contributors(registry, ["regime"])

    def test_every_externally_fed_kernel_declares_memory_in_the_consuming_tf(self) -> None:
        # D-26 denomination: a kernel reading a caller-supplied series (daily macro records, HTF
        # values) is a pass-through on the row grid, so its declared memory is in the consuming
        # tf's own bars (0, plus the lag chain it reads); the source-tf warmup lives in the
        # external builders, which the writer feeds from the full source history. A kernel that
        # computes from such a series is a daily-grid or HTF-source kernel and is not a v2 column
        # contributor, or it is path dependent. A new kernel breaking this fails here.
        from src.intelligence.features.contract.registry import default_registry

        registry = default_registry()
        config = _make_config()
        grid_only = {"cross_asset_daily", "factor_beta_daily", "ctf_source"}
        for kernel in registry.kernels:
            externals = [n for n in kernel.inputs if n.startswith(("ext_", "ref_"))]
            if not externals or kernel.name in grid_only:
                continue
            assert not kernel.path_dependent, kernel.name
            assert kernel.memory(config) <= 3, (kernel.name, kernel.memory(config))

    def test_unit_code_key_is_stable_hex_and_moves_with_a_contributing_kernel(
        self, monkeypatch
    ) -> None:
        import re

        from services import backfill_feature_factory as module
        from src.intelligence.features.contract.registry import default_registry

        registry = default_registry()
        columns = ["atr_z", "rsi_fast"]
        first = module.unit_code_key(registry, columns)
        assert re.fullmatch(r"[0-9a-f]{64}", first)
        assert module.unit_code_key(registry, columns) == first

        real = module._kernel_module_key
        target = registry.by_output("atr_z").module
        monkeypatch.setattr(
            module, "_kernel_module_key", lambda m: "changed" if m == target else real(m)
        )
        assert module.unit_code_key(registry, columns) != first
        # A kernel that does not contribute to the columns does not move the key.
        unrelated = "cmf"
        assert registry.by_output(unrelated).module != target
        monkeypatch.setattr(module, "_kernel_module_key", real)
        before = module.unit_code_key(registry, ["atr_z"])
        monkeypatch.setattr(
            module,
            "_kernel_module_key",
            lambda m: "changed" if m == registry.by_output(unrelated).module else real(m),
        )
        assert module.unit_code_key(registry, ["atr_z"]) == before

    def test_apr_reader_uses_the_fallbacks_and_refuses_nonsense(self) -> None:
        from services.backfill_feature_factory import load_rebuild_unit_apr

        class _Cfg:
            def __init__(self, values: dict[str, object]) -> None:
                self._values = values

            def get_sync(self, key: str, default: object = None) -> object:
                return self._values.get(key, default)

        assert load_rebuild_unit_apr(_Cfg({})) == (25, 1_000_000)  # type: ignore[arg-type]
        assert load_rebuild_unit_apr(
            _Cfg(  # type: ignore[arg-type]
                {
                    "infra.feature_factory.rebuild_symbols_per_chunk": 10,
                    "infra.feature_factory.max_unit_rows": 50_000,
                }
            )
        ) == (10, 50_000)
        with pytest.raises(ValueError, match="at least 1"):
            load_rebuild_unit_apr(
                _Cfg({"infra.feature_factory.rebuild_symbols_per_chunk": 0})  # type: ignore[arg-type]
            )


# ---------------------------------------------------------------------------
# The rebuild writer (186-25 Task 2): provenance-keyed units, spool IPC (todo 339),
# bulk_load-only writes, regime in the same pass. DB interactions are stubbed; the
# real compute pool never runs.
# ---------------------------------------------------------------------------


class _StubCfg:
    """get_sync over a dict, falling through to the caller's default (the APR fallbacks)."""

    def __init__(self, values: dict[str, object] | None = None):
        self._values = values or {}

    def get_sync(self, key: str, default: object = None) -> object:
        return self._values.get(key, default)


_NUMERIC_WIDTH = len(feature_vectors_v2_numeric_columns())


def _unit_spec(range_start, range_end, tf="1d", symbols=("AAA", "BBB")):
    from services._batch_utils import BulkLoadSpec

    return BulkLoadSpec(
        writer=module._JOB,
        target_table="feature_vectors_v2",
        time_column="bar_ts",
        tf=tf,
        range_start=range_start,
        range_end=range_end,
        symbols=list(symbols),
        code_key="a" * 64,
        apr_snapshot={"feature.momentum.window_fast": 5},
        input_digest="b" * 64,
    )


def _group_plan(tf, specs, chunk=("AAA", "BBB"), chunk_index=0, blind=()):
    return module._GroupPlan(
        chunk_index=chunk_index,
        chunk=tuple(chunk),
        tf=tf,
        units=[module.RebuildUnit(i, s) for i, s in enumerate(specs)],
        blind_symbols=set(blind),
    )


def _write_spool(path: Path, symbol: str, tf: str, times, regime=None) -> int:
    with open(path, "w") as handle:
        for ts in times:
            row = feature_vector_v2_row_values(symbol, tf, ts, regime, None, [0.0] * _NUMERIC_WIDTH)
            handle.write(module._spool_line(row))
    return len(times)


def _stub_worker(times_by_symbol: dict[str, dict[int, list]]):
    """A _rebuild_worker stand-in: writes each (symbol, unit) spool with the row times the
    test prescribes (order preserved, so a test can interleave deliberately)."""

    def worker(args: tuple) -> dict:
        symbol, tf, _dsn, _config, _horizon, unit_ranges, spool_dir, *_ = args
        planned = times_by_symbol.get(symbol, {})
        result: dict = {"symbol": symbol, "units": {}, "error": None}
        for index, (_start, _end) in unit_ranges:
            path = Path(spool_dir) / f"u{index:05d}-{symbol}.csv"
            times = planned.get(index, [])
            result["units"][index] = {
                "path": str(path),
                "rows": _write_spool(path, symbol, tf, times),
            }
        return result

    return worker


class _InlinePool:
    """submit() runs the stub worker in-process and records the dispatch order."""

    def __init__(self, worker):
        self._worker = worker
        self.dispatched: list[str] = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def shutdown(self, wait=True):
        pass

    def submit(self, _fn, args):
        self.dispatched.append(args[0])
        return SimpleNamespace(result=lambda: self._worker(args))


class _BulkLoadRecorder:
    """A bulk_load stand-in: consumes the rows iterator (asserting time order), records them
    per batch key, and can fail or miscount on chosen keys."""

    def __init__(self, fail_keys=(), wrong_counts=None):
        self.rows_by_key: dict[str, list[tuple]] = {}
        self.load_order: list[str] = []
        self.preclamped_by_key: dict[str, bool] = {}
        self._fail_keys = set(fail_keys)
        self._wrong_counts = dict(wrong_counts or {})

    def __call__(self, conn, spec, columns, rows, preclamped_real=False):
        rows = list(rows)
        for prev, curr in zip(rows, rows[1:]):
            assert prev[2] <= curr[2], f"rows out of time order in {spec.batch_key[:12]}"
        self.load_order.append(spec.batch_key)
        self.preclamped_by_key[spec.batch_key] = preclamped_real
        if spec.batch_key in self._fail_keys:
            raise RuntimeError("simulated COPY failure")
        self.rows_by_key[spec.batch_key] = rows
        return SimpleNamespace(
            batch_key=spec.batch_key,
            status="loaded",
            row_count=self._wrong_counts.get(spec.batch_key, len(rows)),
            chunks_compressed=0,
        )


class _FakeWriteConn:
    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True


def _run_rebuild_stage(
    monkeypatch,
    tmp_path,
    plans: dict,
    *,
    completed=(),
    worker=None,
    bulk_load=None,
    symbols=("AAA", "BBB"),
    timeframes=("1d",),
    cfg_values=None,
):
    """Run run_rebuild_stage over canned group plans, a stub worker pool and a recording
    bulk_load. Returns (summary, pool, recorder, compress_calls)."""
    completed = set(completed)
    worker = worker if worker is not None else _stub_worker({})
    recorder = bulk_load if bulk_load is not None else _BulkLoadRecorder()
    pool = _InlinePool(worker)
    compress_calls: list = []

    monkeypatch.setattr(module, "_load_config_service", lambda conn: _StubCfg(cfg_values))
    monkeypatch.setattr(module, "_build_feature_factory_config", lambda cfg: tma.CONFIG)
    monkeypatch.setattr(
        module,
        "get_active_contracts",
        lambda settings, dimension=None: [SimpleNamespace(symbol=s) for s in ("AAA", "BBB", "CCC")],
    )
    monkeypatch.setattr(module, "_filter_etf_contracts", lambda contracts, symbols: contracts)
    monkeypatch.setattr(module, "_fetch_bars_from_db", lambda *a, **k: [])
    monkeypatch.setattr(module, "build_cross_asset_series", lambda *a, **k: {})
    monkeypatch.setattr(
        module,
        "_plan_group",
        lambda conn, chunk_index, chunk, tf, horizon, code_key, apr: plans.get((chunk_index, tf)),
    )
    monkeypatch.setattr(
        module,
        "_completed_provenance_batch",
        lambda conn, spec: {"status": "completed"} if spec.batch_key in completed else None,
    )
    monkeypatch.setattr(module, "_make_worker_pool", lambda n, blas, **kw: pool)
    monkeypatch.setattr(module, "_bulk_load", recorder)
    monkeypatch.setattr(module, "psycopg", SimpleNamespace(connect=lambda url: _FakeWriteConn()))
    monkeypatch.setattr(
        module,
        "_compress_completed_chunks",
        lambda conn, table, before: compress_calls.append((table, before)) or 0,
    )
    summary = module.run_rebuild_stage(
        settings=SimpleNamespace(database_url="postgresql://fake"),
        symbols=list(symbols) if symbols is not None else None,
        db_conn=object(),
        n_workers=1,
        timeframes=list(timeframes) if timeframes is not None else None,
        horizon=datetime(2026, 10, 1, tzinfo=UTC),
        spool_root=tmp_path / "spool",
    )
    return summary, pool, recorder, compress_calls


_YEAR_2020 = (datetime(2020, 1, 1, tzinfo=UTC), datetime(2021, 1, 1, tzinfo=UTC))
_YEAR_2021 = (datetime(2021, 1, 1, tzinfo=UTC), datetime(2022, 1, 1, tzinfo=UTC))
# Distinct units are distinct years: two units of one group never share an identity.
_YEAR = _YEAR_2020


def test_resume_loads_only_the_incomplete_units(monkeypatch, tmp_path):
    """u1 completed in provenance_batch: the group still dispatches (u2 is pending), but only
    u2 is spooled and loaded."""
    u1, u2 = _unit_spec(*_YEAR_2020), _unit_spec(*_YEAR_2021)
    plan = _group_plan("1d", [u1, u2])
    summary, pool, recorder, _ = _run_rebuild_stage(
        monkeypatch, tmp_path, {(0, "1d"): plan}, completed={u1.batch_key}
    )
    assert len(pool.dispatched) == 3  # one worker per symbol of the single chunk
    assert recorder.load_order == [u2.batch_key]
    # The writer clamps whole columns upstream; bulk_load is told and skips its per-row clamp.
    assert recorder.preclamped_by_key[u2.batch_key] is True
    assert summary["units_total"] == 2
    assert summary["units_skipped"] == 1
    assert summary["units_loaded"] == 1
    assert summary["rows_loaded"] == len(recorder.rows_by_key[u2.batch_key])


def test_a_fully_completed_group_dispatches_no_worker_and_issues_no_copy(monkeypatch, tmp_path):
    u1 = _unit_spec(*_YEAR)
    plan = _group_plan("1d", [u1])
    summary, pool, recorder, compress_calls = _run_rebuild_stage(
        monkeypatch, tmp_path, {(0, "1d"): plan}, completed={u1.batch_key}
    )
    assert pool.dispatched == []
    assert recorder.load_order == []
    assert summary["units_skipped"] == 1
    assert summary["units_loaded"] == 0
    assert compress_calls == []


def test_unit_row_bound_refuses_before_any_write(monkeypatch, tmp_path):
    """A unit whose spooled rows exceed infra.feature_factory.max_unit_rows raises, naming the
    unit and the counts, before any bulk_load (todo 339's guard)."""
    u1 = _unit_spec(*_YEAR)
    plan = _group_plan("1d", [u1])
    worker = _stub_worker({"AAA": {0: [datetime(2020, 3, 1, tzinfo=UTC)] * 11}})
    with pytest.raises(ValueError, match="above"):
        _run_rebuild_stage(
            monkeypatch,
            tmp_path,
            {(0, "1d"): plan},
            worker=worker,
            cfg_values={"infra.feature_factory.max_unit_rows": 10},
        )


def test_multi_symbol_unit_merges_interleaved_spools_in_time_order(monkeypatch, tmp_path):
    """The per-symbol spools are deliberately out of order across symbols; heapq.merge must
    hand bulk_load one non-decreasing stream (the recorder asserts it too)."""
    u1 = _unit_spec(*_YEAR)
    plan = _group_plan("1d", [u1])
    worker = _stub_worker(
        {
            "AAA": {0: [datetime(2020, 3, 2, tzinfo=UTC), datetime(2020, 3, 4, tzinfo=UTC)]},
            "BBB": {0: [datetime(2020, 3, 1, tzinfo=UTC), datetime(2020, 3, 3, tzinfo=UTC)]},
        }
    )
    _summary, _pool, recorder, _ = _run_rebuild_stage(
        monkeypatch, tmp_path, {(0, "1d"): plan}, worker=worker
    )
    rows = recorder.rows_by_key[u1.batch_key]
    times = [r[2] for r in rows]
    assert times == sorted(times)
    assert len(rows) == 4


def test_one_failed_unit_does_not_block_its_group(monkeypatch, tmp_path):
    """Unit 1's COPY fails: its provenance row is left failed by bulk_load, unit 2 still
    loads, and the summary counts one failed unit."""
    u1, u2 = _unit_spec(*_YEAR_2020), _unit_spec(*_YEAR_2021)
    plan = _group_plan("1d", [u1, u2])
    summary, _pool, recorder, _ = _run_rebuild_stage(
        monkeypatch,
        tmp_path,
        {(0, "1d"): plan},
        bulk_load=_BulkLoadRecorder(fail_keys={u1.batch_key}),
    )
    assert recorder.load_order == [u1.batch_key, u2.batch_key]
    assert summary["units_failed"] == 1
    assert summary["units_loaded"] == 1
    assert summary["failed_units"][0]["batch_key"] == u1.batch_key


def test_spool_row_count_mismatch_raises_loudly(monkeypatch, tmp_path):
    u1 = _unit_spec(*_YEAR)
    plan = _group_plan("1d", [u1])
    recorder = _BulkLoadRecorder(wrong_counts={u1.batch_key: 999})
    with pytest.raises(RuntimeError, match="declared"):
        _run_rebuild_stage(monkeypatch, tmp_path, {(0, "1d"): plan}, bulk_load=recorder)


def test_compression_defers_to_a_clean_full_scope_run(monkeypatch, tmp_path):
    """A hypertable chunk spans every symbol chunk and tf of its year, so nothing compresses
    mid-run: a full-scope run with every unit completed compresses once at the end; a failed
    unit or a partial scope defers (resume traffic must never meet a compressed chunk)."""
    u1, u2 = _unit_spec(*_YEAR_2020), _unit_spec(*_YEAR_2021)
    plan = _group_plan("1d", [u1, u2])

    clean, _pool, _rec, calls = _run_rebuild_stage(
        monkeypatch, tmp_path, {(0, "1d"): plan}, symbols=None, timeframes=None
    )
    assert len(calls) == 1 and calls[0][0] == "feature_vectors_v2"
    assert clean["compression"] == "done"

    failed, _pool, _rec, calls = _run_rebuild_stage(
        monkeypatch,
        tmp_path,
        {(0, "1d"): plan},
        symbols=None,
        timeframes=None,
        bulk_load=_BulkLoadRecorder(fail_keys={u1.batch_key}),
    )
    assert calls == []
    assert failed["compression"].startswith("deferred")

    partial, _pool, _rec, calls = _run_rebuild_stage(
        monkeypatch, tmp_path, {(0, "1d"): plan}, symbols=("AAA",), timeframes=("1d",)
    )
    assert calls == []
    assert partial["compression"].startswith("deferred")


def test_no_write_targets_the_old_feature_vectors_table():
    """D-28/D-24: the module holds no INSERT/UPDATE/COPY against the old table (source grep)."""
    import re

    source = Path(module.__file__).read_text()
    pattern = re.compile(r"(INSERT INTO|UPDATE|COPY)\s+feature_vectors([^_]|$)")
    hits = [
        line
        for line in source.splitlines()
        if pattern.search(line) and not line.lstrip().startswith("#")
    ]
    assert hits == []


def test_regime_comes_from_the_registry_in_the_same_pass():
    """R-10: the stage never imports regime_writer and never issues an UPDATE; the regime
    columns come out of the one compute_kernels call."""
    source = Path(module.__file__).read_text()
    assert "regime_writer" not in source
    assert "compute_kernels(" in source
    # The regime columns are outputs of the same compute_kernels call as the numerics: the
    # worker builds every column of a series from the one call (see _compute_series_columns).
    outputs = list(feature_vectors_v2_output_columns())
    assert "regime" in outputs and "regime_volatility" in outputs
    worker_source = inspect.getsource(module._compute_series_columns)
    assert worker_source.count("compute_kernels(") == 1


def test_no_legacy_row_builder_or_validator_on_the_rebuild_path():
    """The legacy row builders raise on NaN, so an early-history row would abort a unit; the
    v2 row builder is the only row constructor here."""
    source = Path(module.__file__).read_text()
    for forbidden in ("validate_feature_vector", "build_feature_vector_row"):
        assert forbidden not in source, forbidden


def test_refresh_flag_is_gone():
    """The old compute stage's recompute flag has no meaning on an append-only rebuild."""
    source = Path(module.__file__).read_text()
    assert "--refresh" not in source
    assert "--pipeline-version" not in source


# ---------------------------------------------------------------------------
# The rebuild worker over real synthetic compute (no database): bounded payload,
# cache-independence, early-history macro NULL.
# ---------------------------------------------------------------------------


class _ServerCursor:
    """The named server cursor _fetch_bar_arrays reads through."""

    def __init__(self, rows):
        self._rows = list(rows)
        self.itersize = 1

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params):
        pass

    def fetchmany(self, n):
        out, self._rows = self._rows[:n], self._rows[n:]
        return out


class _ListCursor:
    def __init__(self, rows):
        self._rows = list(rows)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params):
        pass

    def fetchall(self):
        return self._rows


class _WorkerConn:
    """Serves the worker's two read shapes: the named server cursor over the tf's bars, and
    the plain cursor's fetchall over the 1d/htf/1m fetches, in call order."""

    def __init__(self, tf_rows, list_fetches):
        self._tf_rows = tf_rows
        self._list_fetches = list(list_fetches)

    def cursor(self, name=None):
        if name is not None:
            return _ServerCursor(self._tf_rows)
        assert self._list_fetches, "unexpected plain-cursor fetch"
        return _ListCursor(self._list_fetches.pop(0))

    def close(self):
        pass


def _bar_tuples(bars: list[dict]) -> list[tuple]:
    return [(b["ts"], b["open"], b["high"], b["low"], b["close"], b["volume"]) for b in bars]


def _bar_arrays(bars: list[dict]):
    times = [b["ts"] for b in bars]
    arrays = {
        "ts": np.array([bar_ts_ns(t) for t in times], dtype=np.int64),
        **{
            name: np.array([float(b[name]) for b in bars])
            for name in ("open", "high", "low", "close", "volume")
        },
    }
    return arrays, times


def _rebuild_config():
    """tma.CONFIG with the regime kernels' HMM loaded (the stage builds it through
    _build_feature_factory_config, which merges HmmConfig.from_values in production)."""
    from src.intelligence.features.kernels._hmm import HmmConfig
    from tests.unit.intelligence.regime_kernel_fixtures import SMALL_HMM_APR

    return dataclasses.replace(tma.CONFIG, hmm=HmmConfig.from_values(SMALL_HMM_APR.get))


_CACHE_BACKED_COLUMNS = (
    "hurst",
    "shannon",
    "garch_ratio",
    "hma_slope_z",
    "adx",
    "above_wk_vwap",
    "momentum_trend_product",
    "reversion_hurst_product",
)


def _macro_column_indices() -> dict[str, int]:
    names = feature_vectors_v2_numeric_columns()
    return {
        name: names.index(name)
        for name in (
            "vix_z",
            "flight_quality",
            "yield_slope_z",
            "tip_tlt_ret_z",
            "hyg_lqd_ret_z",
            "equity_beta_z",
            "rate_beta_z",
        )
    }


def test_rebuild_reads_cache_backed_columns_from_the_registry(monkeypatch, tmp_path):
    """The eight cache-backed columns come out of the one compute_kernels call from the series
    start: a deliberately pre-warmed FeatureCache (sentinel values) is never consulted -- the
    worker takes no cache argument, and a pre-warmed cache cannot change a row."""
    bars = tma._intraday()
    daily = tma._daily_bars()
    late = {s: series[tma.TARGET_SESSION :] for s, series in daily.items()}
    cross = build_cross_asset_series(*(late[s] for s in CROSS_ASSET_SYMBOLS), _rebuild_config())
    beta = build_symbol_beta_series(
        late[tma.SYMBOL], late["SPY"], late["TLT"], tma.SYMBOL, _rebuild_config()
    )

    prewarmed = FeatureCache()
    prewarmed.hurst = 9.99
    prewarmed.shannon = 9.99
    prewarmed.adx = 9.99
    prewarmed.above_wk_vwap = 1.0
    assert prewarmed.hurst == 9.99  # the sentinel cache exists and is never passed on

    arrays, times = _bar_arrays(bars)
    horizon = times[-1] + timedelta(days=2)
    conn = _WorkerConn(
        _bar_tuples(bars),
        [_bar_tuples(late[tma.SYMBOL]), [], []],  # symbol 1d, htf 1h, ltf 1m
    )
    monkeypatch.setattr(module.psycopg, "connect", lambda url: conn)
    unit_ranges = [(0, (times[0], horizon))]
    module._rebuild_worker_init(cross, late["SPY"], late["TLT"])
    payload = module._rebuild_worker(
        (
            tma.SYMBOL,
            "5m",
            "postgresql://fake",
            _rebuild_config(),
            horizon,
            unit_ranges,
            str(tmp_path),
            100,
        )
    )
    assert payload["error"] is None, payload["error"]
    assert payload["symbol"] == tma.SYMBOL
    # Bounded payload (todo 339): paths and counts only, no row tuples -- and its size does
    # not grow with the series even though one block is a tenth of the series.
    assert set(payload) == {"symbol", "units", "error"}
    unit_payload = payload["units"][0]
    assert set(unit_payload) == {"path", "rows"}
    assert unit_payload["rows"] > 100  # several blocks were spooled
    assert len(str(payload)) < 4096
    spool_path = Path(unit_payload["path"])
    assert spool_path.exists()

    # Expected values: the same externals through one compute_kernels call from series start.
    inputs = module._series_kernel_inputs(
        tma.SYMBOL, "5m", arrays, _rebuild_config(), cross, beta, [], None
    )
    out = compute_kernels(
        default_registry(),
        inputs,
        _rebuild_config(),
        outputs=list(feature_vectors_v2_output_columns()),
    )
    names = feature_vectors_v2_numeric_columns()
    spooled: dict[str, list[tuple[int, float]]] = {c: [] for c in _CACHE_BACKED_COLUMNS}
    for row in module.read_spool_rows(spool_path):
        bar_index = int(np.searchsorted(arrays["ts"], bar_ts_ns(row[2])))
        assert arrays["ts"][bar_index] == bar_ts_ns(row[2])
        for c in _CACHE_BACKED_COLUMNS:
            v = row[5 + names.index(c)]
            if v is not None:
                spooled[c].append((bar_index, v))
    for c in _CACHE_BACKED_COLUMNS:
        pairs = spooled[c]
        assert pairs, f"{c} spooled no values"
        for bar_index, v in pairs:
            expected = np.float32(out[c][bar_index])
            assert v == pytest.approx(float(expected), rel=1e-6, abs=1e-9), (
                c,
                bar_index,
                v,
                expected,
            )


def test_early_macro_nan_is_spooled_as_null_and_does_not_raise(monkeypatch, tmp_path):
    """Rows before the first daily record carry NaN macro columns; the spool writes them as
    empty fields (NULL after COPY), never the text NaN, and nothing raises."""
    bars = tma._intraday()
    daily = tma._daily_bars()
    late = {s: series[tma.TARGET_SESSION :] for s, series in daily.items()}
    cross = build_cross_asset_series(*(late[s] for s in CROSS_ASSET_SYMBOLS), _rebuild_config())
    beta = build_symbol_beta_series(
        late[tma.SYMBOL], late["SPY"], late["TLT"], tma.SYMBOL, _rebuild_config()
    )
    arrays, times = _bar_arrays(bars)
    inputs = module._series_kernel_inputs(
        tma.SYMBOL, "5m", arrays, _rebuild_config(), cross, beta, [], None
    )
    series = module._compute_series_columns(inputs, _rebuild_config())

    path = tmp_path / "unit0-QQQ.csv"
    written = module._write_unit_spool(
        path,
        tma.SYMBOL,
        "5m",
        arrays["ts"],
        times,
        series,
        times[0],
        times[-1] + timedelta(minutes=5),
        0,  # include the warmup rows: this test is about them
        100,
    )
    assert written > 0
    lines = path.read_text().splitlines()
    assert not any("NaN" in line or "nan" in line for line in lines)
    n_early = tma.BARS_PER_SESSION * (tma.TARGET_SESSION - tma.INTRADAY_SESSIONS.start)
    names = feature_vectors_v2_numeric_columns()
    macro_at = _macro_column_indices()
    early = [line.split(",") for line in lines[:n_early]]
    for cells in early:
        for name, j in macro_at.items():
            assert cells[5 + j] == "", (name, cells[2])
    # The spool row builder is the only row constructor on this path (the legacy validator
    # would have raised on the first NaN above).
    assert Path(module.__file__).read_text().count("validate_feature_vector") == 0


def test_rebuilt_early_history_macro_columns_are_null_not_zero_in_feature_vectors_v2(
    monkeypatch, tmp_path
):
    """End to end through the write loop: early rows' macro columns load as None (NULL), none
    is 0.0, and late rows keep their kernel values."""
    bars = tma._intraday()
    daily = tma._daily_bars()
    late = {s: series[tma.TARGET_SESSION :] for s, series in daily.items()}
    cross = build_cross_asset_series(*(late[s] for s in CROSS_ASSET_SYMBOLS), _rebuild_config())
    beta = build_symbol_beta_series(
        late[tma.SYMBOL], late["SPY"], late["TLT"], tma.SYMBOL, _rebuild_config()
    )
    arrays, times = _bar_arrays(bars)
    horizon = times[-1] + timedelta(minutes=5)

    conn = _WorkerConn(
        _bar_tuples(bars),
        [_bar_tuples(late[tma.SYMBOL]), [], []],
    )
    monkeypatch.setattr(module.psycopg, "connect", lambda url: conn)
    spool_dir = tmp_path / "spool-group"
    spool_dir.mkdir()
    module._rebuild_worker_init(cross, late["SPY"], late["TLT"])
    payload = module._rebuild_worker(
        (
            tma.SYMBOL,
            "5m",
            "postgresql://fake",
            _rebuild_config(),
            horizon,
            [(0, (times[0], horizon))],
            str(spool_dir),
            100,
        )
    )
    assert payload["error"] is None

    plan = _group_plan("5m", [_unit_spec(times[0], horizon, tf="5m", symbols=(tma.SYMBOL,))])
    recorder = _BulkLoadRecorder()
    real_bulk_load = module._bulk_load
    module._bulk_load = recorder  # the write loop's only write path; restored below
    try:
        summary: dict = {
            "units_failed": 0,
            "failed_units": [],
            "units_loaded": 0,
            "rows_loaded": 0,
        }
        prepared = module._PreparedGroup(
            plan, plan.units, [SimpleNamespace(result=lambda: payload)], spool_dir
        )
        module._write_group(prepared, _FakeWriteConn(), 10**9, summary, set())
    finally:
        module._bulk_load = real_bulk_load
    assert summary["units_loaded"] == 1 and summary["units_failed"] == 0
    rows = recorder.rows_by_key[plan.units[0].spec.batch_key]

    # Early rows (bar_ts before the first daily record's date) load NULL macro columns.
    names = feature_vectors_v2_numeric_columns()
    macro_at = _macro_column_indices()
    first_record_ts = late[tma.SYMBOL][0]["ts"]
    by_ts = {r[2]: r for r in rows}
    early = [r for r in rows if r[2] < first_record_ts]
    assert early, "expected early rows without a daily record"
    for row in early:
        for j in macro_at.values():
            assert row[5 + j] is None
            assert row[5 + j] != 0.0
    # A late row keeps its value: vix_z equals the kernel output at that bar.
    inputs = module._series_kernel_inputs(
        tma.SYMBOL, "5m", arrays, _rebuild_config(), cross, beta, [], None
    )
    out = compute_kernels(
        default_registry(),
        inputs,
        _rebuild_config(),
        outputs=list(feature_vectors_v2_output_columns()),
    )
    last_ts = times[-1]
    last = by_ts[last_ts]
    bar_index = int(np.searchsorted(arrays["ts"], bar_ts_ns(last_ts)))
    vix_j = 5 + macro_at["vix_z"]
    expected = np.float32(out["vix_z"][bar_index])
    assert last[vix_j] is not None
    assert last[vix_j] == pytest.approx(float(expected), rel=1e-6)


def test_full_column_set_fetch_start_is_the_series_start():
    """D-26: the contributing set of the whole v2 column set includes path-dependent kernels
    (the regime walk-forward, hurst, ...), so the unit fetch starts at the series start; the
    worker's single compute pass therefore covers the full series."""
    from services.backfill_feature_factory import path_dependent_contributors, unit_fetch_start

    registry = default_registry()
    outputs = list(feature_vectors_v2_output_columns())
    series_start = datetime(2010, 1, 4, tzinfo=UTC)
    got = unit_fetch_start(
        registry, outputs, "5m", datetime(2020, 1, 1, tzinfo=UTC), series_start, tma.CONFIG
    )
    assert got == series_start
    assert path_dependent_contributors(registry, outputs)


def test_plan_group_builds_units_from_bar_stats_and_month_digests(tmp_path):
    """The digest pass plans each unit from per-symbol bar statistics plus the month-composed
    content digest, without fetching a bar or running a kernel; a symbol with no digest row at
    all is flagged digest-blind, never silently skipped."""
    from services._batch_utils import BAR_DIGEST_ABSENT_SYMBOL
    from tests.unit._compressed_hypertable_write_session_fakes import ScriptedConn

    stats = [
        ("AAA", 2020, 100, datetime(2020, 1, 2, tzinfo=UTC), datetime(2020, 12, 31, tzinfo=UTC)),
        ("BBB", 2020, 50, datetime(2020, 1, 2, tzinfo=UTC), datetime(2020, 12, 31, tzinfo=UTC)),
    ]
    digest_rows = [("AAA", datetime(2020, 1, 1, tzinfo=UTC), "d1")]
    conn = ScriptedConn([{"fetchall": stats}, {"fetchall": digest_rows}])
    horizon = datetime(2021, 1, 1, tzinfo=UTC)
    plan = module._plan_group(conn, 0, ("AAA", "BBB"), "1d", horizon, "c" * 64, {"k": 1})
    assert plan is not None
    assert [(u.spec.range_start, u.spec.range_end) for u in plan.units] == [
        (datetime(2020, 1, 1, tzinfo=UTC), horizon)
    ]
    assert plan.blind_symbols == {"BBB"}
    unit = plan.units[0]
    assert unit.spec.target_table == "feature_vectors_v2"
    assert len(unit.spec.input_digest) == 64
    assert unit.index == 0

    # A chunk with no bars before the horizon plans nothing.
    empty = ScriptedConn([{"fetchall": []}])
    assert module._plan_group(empty, 0, ("AAA",), "1d", horizon, "c" * 64, {"k": 1}) is None
    assert BAR_DIGEST_ABSENT_SYMBOL == "absent"
