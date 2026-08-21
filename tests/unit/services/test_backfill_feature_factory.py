"""Unit tests for BackfillFeatureFactory — two-stage checkpoint/resume, coverage accounting.

CI-clean: no live IBKR, no live DB. All DB interactions mocked.
Tests cover:
- compute resume skips status='complete' pairs
- fetch resume skips IBKR download for fetch_complete=true pairs
- theoretical_max formula per TF/depth
- coverage gate flags pairs below 80% of theoretical_max
- feature_vectors params builder sets regime_label_source='filtered'
"""

from __future__ import annotations

import bisect
import math
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

# Ensure project root on sys.path for direct import
sys.path.insert(0, str(Path(__file__).parents[3]))

# Import only the pure-function helpers — no network, no DB
from services.backfill_feature_factory import (
    _BARS_PER_DAY,
    _DEFAULT_CLIENT_ID,
    _INSERT_FEATURE_VECTORS_SQL,
    _MARK_COMPUTE_COMPLETE_SQL,
    _MARK_COMPUTE_FAILED_SQL,
    _TARGET_TIMEFRAMES_DEFAULT,
    _TRADING_DAYS_PER_YEAR,
    _UPSERT_FEATURE_VECTORS_SQL,
    _batch_insert,
    _get_target_timeframes,
    _log_coverage_report,
    _theoretical_max,
    _vector_to_params,
    run_compute_stage,
)
from src.config.config_service import ConfigService
from src.intelligence.feature_cache import FeatureCache
from src.intelligence.feature_factory import FeatureFactory, FeatureFactoryConfig
from src.intelligence.features.cross_asset_series import CrossAssetRecord
from src.intelligence.schemas import FeatureVector

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


def _mock_worker_result(symbol: str) -> dict:
    """Build one _run_compute_worker-shaped pool.map() result for `symbol` across the
    default target timeframes.

    Shared by the run_compute_stage tests below (/simplify pass, todo 318/300 session)
    -- this exact literal was repeated identically across 4 tests; any future change to
    the worker-result shape (already happened once this session, the rows_written/pct ->
    rows-only change) previously had to be hand-applied to all 4 copies.

    No tfs/theoretical_max params: an earlier version of this helper had both, but no
    caller ever passed either (/simplify altitude-angle finding, same session) -- YAGNI,
    re-add if a real test ever needs a different set.
    """
    return {
        "symbol": symbol,
        "error": None,
        "results": [
            {"tf": tf, "rows": [(f"row-{tf}",)], "theoretical_max": 1200}
            for tf in _TARGET_TIMEFRAMES_DEFAULT
        ],
    }


# ---------------------------------------------------------------------------
# Test 1: Default client-id is 40
# ---------------------------------------------------------------------------


def test_default_client_id_is_40() -> None:
    """IBKR client-id must default to 40 (T2 mitigation)."""
    assert _DEFAULT_CLIENT_ID == 40


# ---------------------------------------------------------------------------
# Test 2: theoretical_max formula
# ---------------------------------------------------------------------------


def test_theoretical_max_5m_5y() -> None:
    """5m over 5y: (5 * 252 * 78) - warm_up = 98280 - warm_up."""
    warm_up = 252
    expected = 5 * 252 * 78 - warm_up
    result = _theoretical_max("5m", 5, warm_up)
    assert result == expected, f"Expected {expected}, got {result}"


def test_theoretical_max_1d_20y() -> None:
    """1d over 20y: (20 * 252 * 1) - warm_up = 5040 - warm_up."""
    warm_up = 252
    expected = 20 * 252 * 1 - warm_up
    result = _theoretical_max("1d", 20, warm_up)
    assert result == expected, f"Expected {expected}, got {result}"


def test_theoretical_max_15m_10y() -> None:
    """15m over 10y: (10 * 252 * 26) - warm_up."""
    warm_up = 100
    expected = 10 * 252 * 26 - warm_up
    result = _theoretical_max("15m", 10, warm_up)
    assert result == expected


def test_theoretical_max_1h_15y() -> None:
    """1h over 15y: (15 * 252 * 6) - warm_up."""
    warm_up = 252
    expected = 15 * 252 * 6 - warm_up
    result = _theoretical_max("1h", 15, warm_up)
    assert result == expected


def test_theoretical_max_no_negative() -> None:
    """theoretical_max floors at 0 if warm_up exceeds raw bars."""
    warm_up = 99999
    result = _theoretical_max("1d", 1, warm_up)
    assert result == 0


def test_bars_per_day_values() -> None:
    """Verify _BARS_PER_DAY constants match objective specification."""
    assert _BARS_PER_DAY["5m"] == 78
    assert _BARS_PER_DAY["15m"] == 26
    assert _BARS_PER_DAY["1h"] == 6
    assert _BARS_PER_DAY["1d"] == 1


def test_trading_days_per_year() -> None:
    """Standard 252 trading days."""
    assert _TRADING_DAYS_PER_YEAR == 252


# ---------------------------------------------------------------------------
# Test 3: params builder sets regime_label_source='filtered'
# ---------------------------------------------------------------------------


def test_vector_to_params_regime_label_source() -> None:
    """Every feature_vectors INSERT must set regime_label_source='filtered' (SC-5/D-07)."""
    fv = _make_zero_vector()
    ts = datetime(2025, 1, 2, 14, 30, 0, tzinfo=UTC)
    params = _vector_to_params(
        symbol="SPY",
        tf="5m",
        bar_ts=ts,
        pipeline_version="3.0.0",
        regime=None,
        fv=fv,
    )
    # params[7] is regime_label_source in the INSERT column order (post migration 159).
    # Column layout: [0]=feature_vector_id, [1]=symbol, [2]=tf, [3]=bar_ts,
    #   [4]=pipeline_version, [5]=feature_factory_version, [6]=regime, [7]=regime_label_source
    assert params[7] == "filtered", f"Expected 'filtered', got {params[7]!r}"


def test_vector_to_params_all_features_present() -> None:
    """All FeatureVector fields must appear in the INSERT params tuple (159 total
    after migration 211, 2026-07-09 -- 161 after migration 206's 2026-07-08
    persistence-wiring fix, then -2 for the redundant new_high_flag/new_low_flag
    removal, 164 after migration 223's 5 canary columns, 181 after migration
    255's 17 structural VP/SR columns (Phase 163 Plan 01), 217 after migration
    266's 36 SMC institutional-footprint columns (Phase 164 Plan 01), 258
    after migration 267's 41 swing/fib/trend/session structure columns
    (Phase 165 Plan 01), 268 after migration 293's 10 calendar cycle/TDOM/
    minute + velocity columns (Phase 151 Plan 01), 279 after migration 288's
    11 recency/statistical atomics columns (Phase 151 Plan 03), 286 after
    migration 289's 7 cross-asset spread/beta atomics columns (Phase 151
    Plan 04), 291 after migration 290's 5 Named Interaction Primitives
    columns (Phase 151 Plan 05), 301 after migration 291's 10
    Theory-Motivated Interaction columns (Phase 151 Plan 06), 307 after
    migration 316's 6 Velocity Primitives Extension columns (todo 320)."""
    fv = _make_zero_vector()
    ts = datetime(2025, 1, 2, 14, 30, 0, tzinfo=UTC)
    params = _vector_to_params(
        symbol="SPY",
        tf="5m",
        bar_ts=ts,
        pipeline_version="3.0.0",
        regime=None,
        fv=fv,
    )
    # 1 content-key + 8 structural + 298 feature floats = 307 total
    assert len(params) == 307, f"Expected 307 params, got {len(params)}"


def test_vector_to_params_symbol_tf_ts() -> None:
    """First three params are symbol, tf, bar_ts."""
    fv = _make_zero_vector()
    ts = datetime(2025, 6, 1, 13, 30, 0, tzinfo=UTC)
    params = _vector_to_params(
        symbol="TLT",
        tf="1h",
        bar_ts=ts,
        pipeline_version="3.0.0",
        regime=None,
        fv=fv,
    )
    assert params[1] == "TLT"
    assert params[2] == "1h"
    assert params[3] == ts


# ---------------------------------------------------------------------------
# Test 4: coverage gate flags pairs below 80%
# ---------------------------------------------------------------------------


def test_coverage_gate_below_80pct_flagged(caplog: pytest.LogCaptureFixture) -> None:
    """Pairs with rows_written < 80% theoretical_max must be flagged as warnings."""
    import logging

    coverage = {
        ("SPY", "5m"): {
            "rows_written": 500,
            "theoretical_max": 1000,
            "pct": 0.5,  # 50% — below gate
        },
        ("TLT", "1d"): {
            "rows_written": 900,
            "theoretical_max": 1000,
            "pct": 0.9,  # 90% — above gate
        },
    }

    with caplog.at_level(logging.WARNING):
        _log_coverage_report(coverage, 0.80)

    # The below-gate pair should appear in warning output
    assert any(
        "SPY" in record.message or "below" in record.message.lower()
        for record in caplog.records
        if record.levelno >= logging.WARNING
    ), "Expected a warning for SPY/5m below 80% gate"


def test_coverage_gate_above_80pct_no_warning(caplog: pytest.LogCaptureFixture) -> None:
    """Pairs with rows_written >= 80% theoretical_max should not trigger a D-06 gate warning."""
    import logging

    coverage = {
        ("SPY", "1d"): {
            "rows_written": 850,
            "theoretical_max": 1000,
            "pct": 0.85,  # 85% — above gate
        },
    }

    with caplog.at_level(logging.WARNING):
        _log_coverage_report(coverage, 0.80)

    # No D-06 gate warning expected
    gate_warnings = [
        r for r in caplog.records if r.levelno >= logging.WARNING and "gate" in r.message.lower()
    ]
    assert not gate_warnings, f"Unexpected D-06 gate warnings: {gate_warnings}"


# ---------------------------------------------------------------------------
# Test 5: compute resume skips status='complete' pairs
# ---------------------------------------------------------------------------


def test_compute_resume_skips_complete_pairs() -> None:
    """run_compute_stage must skip (symbol, tf) pairs where status='complete'."""
    # Mock Settings
    settings = MagicMock()
    settings.database_url = "postgresql://fake"

    # Mock DB connection
    mock_conn = MagicMock()

    # Stub get_active_contracts to return a single ETF
    mock_instrument = MagicMock()
    mock_instrument.symbol = "SPY"
    mock_instrument.asset_class = "equity"

    # Status: SPY/5m already complete
    with (
        patch(
            "services.backfill_feature_factory.get_active_contracts",
            return_value=[mock_instrument],
        ),
        patch(
            "services.backfill_feature_factory._load_config_service",
        ) as mock_cfg_load,
        patch(
            "services.backfill_feature_factory._build_feature_factory_config",
        ) as mock_cfg_build,
        patch(
            "services.backfill_feature_factory._load_status_map",
            return_value={
                ("SPY", "5m"): {
                    "status": "complete",
                    "fetch_complete": True,
                    "rows_written": 1000,
                    "theoretical_max": 1200,
                },
                ("SPY", "15m"): {
                    "status": "complete",
                    "fetch_complete": True,
                    "rows_written": 800,
                    "theoretical_max": 900,
                },
                ("SPY", "1h"): {
                    "status": "complete",
                    "fetch_complete": True,
                    "rows_written": 200,
                    "theoretical_max": 250,
                },
                ("SPY", "1d"): {
                    "status": "complete",
                    "fetch_complete": True,
                    "rows_written": 50,
                    "theoretical_max": 60,
                },
            },
        ),
        # todo 316: checkpoint only trusted when feature_vectors actually holds the
        # rows (at or above coverage_threshold of rows_written) -- this test's
        # scenario is the correctly-synced case, unlike
        # test_compute_resume_recomputes_when_status_complete_but_no_fv_rows.
        patch(
            "services.backfill_feature_factory._load_fv_row_counts",
            return_value={
                ("SPY", "5m"): 1000,
                ("SPY", "15m"): 800,
                ("SPY", "1h"): 200,
                ("SPY", "1d"): 50,
            },
        ),
        patch("services.backfill_feature_factory._compute_symbol_tf") as mock_compute,
    ):
        mock_cfg_load.return_value = MagicMock()
        mock_cfg_build.return_value = _make_config()

        coverage, _ = run_compute_stage(
            settings=settings,
            symbols=None,
            db_conn=mock_conn,
        )

    # _compute_symbol_tf must never be called when all pairs are complete
    mock_compute.assert_not_called()

    # All 4 TFs returned in coverage
    assert ("SPY", "5m") in coverage
    assert ("SPY", "1d") in coverage


def test_compute_resume_recomputes_when_status_complete_but_no_fv_rows() -> None:
    """todo 316: a (symbol, tf) marked status='complete' in backfill_status but with
    ZERO rows actually present in feature_vectors must NOT be skipped -- the checkpoint
    desynced from reality (confirmed live: 80 active ETF symbols, computed successfully
    per backfill_status in 2026-07, completely absent from feature_vectors as of
    2026-08-14 with no error ever raised). Recompute, don't trust a stale flag blindly."""
    settings = MagicMock()
    settings.database_url = "postgresql://fake"
    mock_conn = MagicMock()

    mock_instrument = MagicMock()
    mock_instrument.symbol = "SPY"
    mock_instrument.asset_class = "equity"

    with (
        patch(
            "services.backfill_feature_factory.get_active_contracts",
            return_value=[mock_instrument],
        ),
        patch("services.backfill_feature_factory._load_config_service") as mock_cfg_load,
        patch("services.backfill_feature_factory._build_feature_factory_config") as mock_cfg_build,
        patch(
            "services.backfill_feature_factory._load_status_map",
            return_value={
                ("SPY", tf): {
                    "status": "complete",
                    "fetch_complete": True,
                    "rows_written": 1000,
                    "theoretical_max": 1200,
                }
                for tf in _TARGET_TIMEFRAMES_DEFAULT
            },
        ),
        # feature_vectors has ZERO rows for SPY on any tf -- the desync
        patch(
            "services.backfill_feature_factory._load_fv_row_counts",
            return_value={},
        ),
        patch("services.backfill_feature_factory._make_worker_pool") as mock_pool_cls,
        patch("services.backfill_feature_factory._write_session"),
    ):
        mock_cfg_load.return_value = MagicMock()
        mock_cfg_build.return_value = _make_config()
        mock_pool = MagicMock()
        mock_pool.map.return_value = [_mock_worker_result("SPY")]
        mock_pool_cls.return_value.__enter__.return_value = mock_pool

        run_compute_stage(
            settings=settings,
            symbols=None,
            db_conn=mock_conn,
        )

        # The stale 'complete' flag must NOT short-circuit compute when feature_vectors
        # actually holds nothing for this pair -- a pool must still be spawned.
        mock_pool.map.assert_called_once()


def test_compute_resume_recomputes_on_partial_row_loss() -> None:
    """Code review finding (todo 316, same session): a pure existence check missed
    PARTIAL data loss -- a pair that lost most but not all of its rows still read as
    'present' and got skipped forever, reproducing the exact silent-gap failure mode
    this fix exists to close, just below 100% instead of at 0%. A count well under
    coverage_threshold (default 0.80) of rows_written must also trigger recompute."""
    settings = MagicMock()
    settings.database_url = "postgresql://fake"
    mock_conn = MagicMock()

    mock_instrument = MagicMock()
    mock_instrument.symbol = "SPY"
    mock_instrument.asset_class = "equity"

    with (
        patch(
            "services.backfill_feature_factory.get_active_contracts",
            return_value=[mock_instrument],
        ),
        patch("services.backfill_feature_factory._load_config_service") as mock_cfg_load,
        patch("services.backfill_feature_factory._build_feature_factory_config") as mock_cfg_build,
        patch(
            "services.backfill_feature_factory._load_status_map",
            return_value={
                ("SPY", tf): {
                    "status": "complete",
                    "fetch_complete": True,
                    "rows_written": 1000,
                    "theoretical_max": 1200,
                }
                for tf in _TARGET_TIMEFRAMES_DEFAULT
            },
        ),
        # feature_vectors holds only 50/1000 rows for SPY on every tf -- well under
        # the 80% default coverage_threshold, i.e. a real partial-loss desync.
        patch(
            "services.backfill_feature_factory._load_fv_row_counts",
            return_value={("SPY", tf): 50 for tf in _TARGET_TIMEFRAMES_DEFAULT},
        ),
        patch("services.backfill_feature_factory._make_worker_pool") as mock_pool_cls,
        patch("services.backfill_feature_factory._write_session"),
    ):
        mock_cfg_load.return_value = MagicMock()
        mock_cfg_build.return_value = _make_config()
        mock_pool = MagicMock()
        mock_pool.map.return_value = [_mock_worker_result("SPY")]
        mock_pool_cls.return_value.__enter__.return_value = mock_pool

        run_compute_stage(
            settings=settings,
            symbols=None,
            db_conn=mock_conn,
        )

        mock_pool.map.assert_called_once()


def test_refresh_skips_fv_row_count_check_entirely() -> None:
    """Code review finding (todo 316, same session): under refresh=True the skip
    branch is already unconditionally bypassed, so computing the desync check's
    result is pure waste (a real query against a 70M-row hypertable) plus misleading
    'desynced' warnings for what's actually just an operator-requested recompute.
    _load_fv_row_counts must not even be called when refresh=True."""
    settings = MagicMock()
    settings.database_url = "postgresql://fake"
    mock_conn = MagicMock()

    mock_instrument = MagicMock()
    mock_instrument.symbol = "SPY"
    mock_instrument.asset_class = "equity"

    with (
        patch(
            "services.backfill_feature_factory.get_active_contracts",
            return_value=[mock_instrument],
        ),
        patch("services.backfill_feature_factory._load_config_service") as mock_cfg_load,
        patch("services.backfill_feature_factory._build_feature_factory_config") as mock_cfg_build,
        patch(
            "services.backfill_feature_factory._load_status_map",
            return_value={
                ("SPY", tf): {
                    "status": "complete",
                    "fetch_complete": True,
                    "rows_written": 1000,
                    "theoretical_max": 1200,
                }
                for tf in _TARGET_TIMEFRAMES_DEFAULT
            },
        ),
        patch("services.backfill_feature_factory._load_fv_row_counts") as mock_fv_counts,
        patch("services.backfill_feature_factory._make_worker_pool") as mock_pool_cls,
        patch("services.backfill_feature_factory._write_session"),
    ):
        mock_cfg_load.return_value = MagicMock()
        mock_cfg_build.return_value = _make_config()
        mock_pool = MagicMock()
        mock_pool.map.return_value = [_mock_worker_result("SPY")]
        mock_pool_cls.return_value.__enter__.return_value = mock_pool

        run_compute_stage(
            settings=settings,
            symbols=None,
            db_conn=mock_conn,
            refresh=True,
        )

        mock_fv_counts.assert_not_called()


def test_refresh_reprocesses_complete_pairs() -> None:
    """todo 176: refresh=True must bypass the status='complete' checkpoint skip --
    otherwise a recompute run would never even reach the pairs it exists to fix."""
    settings = MagicMock()
    settings.database_url = "postgresql://fake"
    mock_conn = MagicMock()

    mock_instrument = MagicMock()
    mock_instrument.symbol = "SPY"
    mock_instrument.asset_class = "equity"

    with (
        patch(
            "services.backfill_feature_factory.get_active_contracts",
            return_value=[mock_instrument],
        ),
        patch("services.backfill_feature_factory._load_config_service") as mock_cfg_load,
        patch("services.backfill_feature_factory._build_feature_factory_config") as mock_cfg_build,
        patch(
            "services.backfill_feature_factory._load_status_map",
            return_value={
                ("SPY", tf): {
                    "status": "complete",
                    "fetch_complete": True,
                    "rows_written": 1000,
                    "theoretical_max": 1200,
                }
                for tf in _TARGET_TIMEFRAMES_DEFAULT
            },
        ),
        patch("services.backfill_feature_factory._make_worker_pool") as mock_pool_cls,
        patch("services.backfill_feature_factory._write_session"),
    ):
        mock_cfg_load.return_value = MagicMock()
        mock_cfg_build.return_value = _make_config()
        mock_pool = MagicMock()
        mock_pool.map.return_value = [_mock_worker_result("SPY")]
        mock_pool_cls.return_value.__enter__.return_value = mock_pool

        run_compute_stage(
            settings=settings,
            symbols=None,
            db_conn=mock_conn,
            refresh=True,
        )

        # A pool was actually spawned -- the complete-pair checkpoint did not short-circuit
        mock_pool.map.assert_called_once()
        worker_args = list(mock_pool.map.call_args[0][1])
        assert len(worker_args) == 1
        # Unpack by name (matches _run_compute_worker's documented args: order) rather
        # than a magic tuple index -- stays correct if the tuple grows again.
        (
            _symbol,
            _tfs,
            _dsn,
            _config,
            _pipeline_version,
            _warm_up_bars,
            _cross_asset_by_date,
            _spy_1d_bars,
            _tlt_1d_bars,
            refresh,
        ) = worker_args[0]
        assert refresh is True


def test_compute_cell_write_failure_does_not_abort_remaining_cells() -> None:
    """Code review finding (todo 318 Bug 2, /simplify pass): the main process now
    does every worker's write serially in one pool.map loop -- a write failure for
    one (symbol, tf) cell must not abort the whole run and discard every other
    pending symbol's already-computed rows, mirroring regime_writer.py's per-cell
    isolation. Verified by making _batch_insert raise for AAPL's cell only; MSFT's
    cell (returned in the same pool.map iterable) must still get written and
    recorded in coverage."""
    settings = MagicMock()
    settings.database_url = "postgresql://fake"
    mock_conn = MagicMock()

    mock_instruments = []
    for sym in ("AAPL", "MSFT"):
        inst = MagicMock()
        inst.symbol = sym
        inst.asset_class = "equity"
        mock_instruments.append(inst)

    with (
        patch(
            "services.backfill_feature_factory.get_active_contracts",
            return_value=mock_instruments,
        ),
        patch("services.backfill_feature_factory._load_config_service") as mock_cfg_load,
        patch("services.backfill_feature_factory._build_feature_factory_config") as mock_cfg_build,
        patch(
            "services.backfill_feature_factory._load_status_map",
            return_value={
                (sym, tf): {
                    "status": "complete",
                    "fetch_complete": True,
                    "rows_written": 1000,
                    "theoretical_max": 1200,
                }
                for sym in ("AAPL", "MSFT")
                for tf in _TARGET_TIMEFRAMES_DEFAULT
            },
        ),
        # Empty feature_vectors -- todo 316's checkpoint-desync check forces both
        # symbols into pending_symbols despite status='complete' above.
        patch("services.backfill_feature_factory._load_fv_row_counts", return_value={}),
        patch("services.backfill_feature_factory._make_worker_pool") as mock_pool_cls,
        patch("services.backfill_feature_factory._write_session"),
        patch("services.backfill_feature_factory._batch_insert") as mock_batch_insert,
    ):
        mock_cfg_load.return_value = MagicMock()
        mock_cfg_build.return_value = _make_config()

        def _raise_for_aapl(conn, rows, refresh=False):
            if rows and rows[0][0] == "AAPL-row":
                raise RuntimeError("simulated write failure")

        mock_batch_insert.side_effect = _raise_for_aapl

        mock_pool = MagicMock()
        mock_pool.map.return_value = [
            {
                "symbol": "AAPL",
                "error": None,
                "results": [
                    {"tf": "5m", "rows": [("AAPL-row",)], "theoretical_max": 1200},
                ],
            },
            {
                "symbol": "MSFT",
                "error": None,
                "results": [
                    {"tf": "5m", "rows": [("MSFT-row",)], "theoretical_max": 1200},
                ],
            },
        ]
        mock_pool_cls.return_value.__enter__.return_value = mock_pool

        # Must not raise -- that's the whole point of the fix.
        coverage, _ = run_compute_stage(
            settings=settings,
            symbols=None,
            db_conn=mock_conn,
        )

    # MSFT's cell was written despite AAPL's failing earlier in the same loop.
    assert coverage[("MSFT", "5m")]["rows_written"] == 1
    # AAPL's failed cell is recorded as zero, not silently dropped or left absent.
    assert coverage[("AAPL", "5m")]["rows_written"] == 0


def test_compute_cell_mid_chunk_failure_does_not_leave_partial_commit() -> None:
    """/simplify altitude-angle finding, todo 318/300 session: every existing test
    before this one only ever exercised a single-chunk cell (one row -> one
    _batch_insert call), because int(MagicMock()) defaults to 1 for the mocked
    insert_batch_size AND every mocked cell only ever had 1 row -- so
    range(0, 1, N) never iterated more than once regardless of N. This test gives
    one cell 3 rows so the chunk loop genuinely iterates 3 times (insert_batch_size
    defaults to 1 via the same MagicMock behavior), and fails on the SECOND chunk --
    the exact scenario _batch_insert's dropped internal commit() exists to fix.
    Must not commit anything for this cell: _MARK_COMPUTE_COMPLETE_SQL must never
    run, only _MARK_COMPUTE_FAILED_SQL, and the cell's coverage must read zero --
    not a partial count reflecting the one chunk that succeeded before the failure."""
    settings = MagicMock()
    settings.database_url = "postgresql://fake"
    mock_conn = MagicMock()

    mock_instrument = MagicMock()
    mock_instrument.symbol = "TSLA"
    mock_instrument.asset_class = "equity"

    with (
        patch(
            "services.backfill_feature_factory.get_active_contracts",
            return_value=[mock_instrument],
        ),
        patch("services.backfill_feature_factory._load_config_service") as mock_cfg_load,
        patch("services.backfill_feature_factory._build_feature_factory_config") as mock_cfg_build,
        patch(
            "services.backfill_feature_factory._load_status_map",
            return_value={
                ("TSLA", "5m"): {
                    "status": "complete",
                    "fetch_complete": True,
                    "rows_written": 1000,
                    "theoretical_max": 1200,
                }
            },
        ),
        patch("services.backfill_feature_factory._load_fv_row_counts", return_value={}),
        patch("services.backfill_feature_factory._make_worker_pool") as mock_pool_cls,
        patch("services.backfill_feature_factory._write_session"),
        patch("services.backfill_feature_factory._batch_insert") as mock_batch_insert,
    ):
        mock_cfg_load.return_value = MagicMock()
        mock_cfg_build.return_value = _make_config()

        # Chunk 1 succeeds, chunk 2 raises -- chunk 3 is never reached.
        call_count = {"n": 0}

        def _raise_on_second_chunk(conn, rows, refresh=False):
            call_count["n"] += 1
            if call_count["n"] == 2:
                raise RuntimeError("simulated mid-chunk failure")

        mock_batch_insert.side_effect = _raise_on_second_chunk

        mock_pool = MagicMock()
        mock_pool.map.return_value = [
            {
                "symbol": "TSLA",
                "error": None,
                "results": [
                    {
                        "tf": "5m",
                        "rows": [("TSLA-row-1",), ("TSLA-row-2",), ("TSLA-row-3",)],
                        "theoretical_max": 1200,
                    },
                ],
            },
        ]
        mock_pool_cls.return_value.__enter__.return_value = mock_pool

        coverage, _ = run_compute_stage(
            settings=settings,
            symbols=None,
            db_conn=mock_conn,
        )

    # The chunk loop actually iterated more than once -- confirms this test
    # exercises the multi-chunk path, not a trivially-single-iteration one.
    assert call_count["n"] >= 2

    # Whole cell recorded as failed -- not a partial count from the one chunk
    # that succeeded before the second chunk raised.
    assert coverage[("TSLA", "5m")]["rows_written"] == 0

    # The success-path SQL must never have run for this cell.
    executed_sql = [c.args[0] for c in mock_conn.cursor().__enter__().execute.call_args_list]
    assert _MARK_COMPUTE_COMPLETE_SQL not in executed_sql
    assert _MARK_COMPUTE_FAILED_SQL in executed_sql


def test_batch_insert_does_not_commit() -> None:
    """/simplify altitude-angle finding, todo 318/300 session: pins the "does not
    commit" contract _batch_insert's docstring documents but no test previously
    verified -- a future change that reintroduces conn.commit() here would silently
    reopen the mid-chunk-failure partial-commit bug this function's docstring exists
    to prevent, with nothing in the suite catching it."""
    mock_conn = MagicMock()
    _batch_insert(mock_conn, [("row",)], refresh=False)
    mock_conn.commit.assert_not_called()


def test_batch_insert_default_uses_insert_sql() -> None:
    """Default (refresh=False) must use the DO NOTHING statement -- never touches
    an existing row, matching the live write path's idempotent-skip semantics."""
    mock_conn = MagicMock()
    mock_cur = mock_conn.cursor.return_value.__enter__.return_value
    _batch_insert(mock_conn, [("row",)], refresh=False)
    mock_cur.executemany.assert_called_once()
    assert mock_cur.executemany.call_args[0][0] == _INSERT_FEATURE_VECTORS_SQL


def test_batch_insert_refresh_uses_upsert_sql() -> None:
    """refresh=True (todo 176) must use the DO UPDATE statement so existing rows
    actually get overwritten with freshly computed values, including new columns."""
    mock_conn = MagicMock()
    mock_cur = mock_conn.cursor.return_value.__enter__.return_value
    _batch_insert(mock_conn, [("row",)], refresh=True)
    mock_cur.executemany.assert_called_once()
    assert mock_cur.executemany.call_args[0][0] == _UPSERT_FEATURE_VECTORS_SQL


# ---------------------------------------------------------------------------
# Test 6: fetch resume skips IBKR download for fetch_complete=true pairs
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


def _make_daily_bars(n: int, seed: int, start_close: float = 100.0) -> list[dict]:
    rng = np.random.default_rng(seed)
    closes = start_close * np.cumprod(1 + rng.normal(0, 0.01, n))
    base = datetime(2020, 1, 2, 21, 0, tzinfo=UTC)
    return [
        {
            "ts": base + timedelta(days=i),
            "open": float(closes[i] * 0.999),
            "high": float(closes[i] * 1.001),
            "low": float(closes[i] * 0.999),
            "close": float(closes[i]),
            "volume": 1_000_000.0,
        }
        for i in range(n)
    ]


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
        from src.intelligence.features.cross_asset_series import build_cross_asset_series

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
        from src.intelligence.features.cross_asset_series import build_cross_asset_series

        config = _make_config()
        spy = _make_daily_bars(50, seed=10)
        tlt = _make_daily_bars(50, seed=11)
        shy = _make_daily_bars(50, seed=12)
        tip = _make_daily_bars(50, seed=13)
        hyg = _make_daily_bars(50, seed=14)
        lqd = _make_daily_bars(50, seed=15)
        result = build_cross_asset_series(spy, tlt, shy, tip, hyg, lqd, config)
        for d, values in result.items():
            for field_name in CrossAssetRecord._fields:
                v = getattr(values, field_name)
                assert math.isfinite(v), f"{d}: {field_name} not finite"

    def test_tip_hyg_lqd_partial_coverage_emits_zero_not_skip(self) -> None:
        """Dates with SPY/TLT/SHY coverage but no TIP/HYG/LQD coverage (pre-listing
        dates) must still emit vix_z/yield_slope_z -- TIP/HYG/LQD unavailability
        must NOT skip the whole date, only zero the affected spread fields."""
        from src.intelligence.features.cross_asset_series import build_cross_asset_series

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
            assert values.tip_tlt_ret_z == 0.0
            assert values.hyg_lqd_ret_z == 0.0
            # vix_z/yield_slope_z are NOT forced to 0.0 -- SPY/TLT/SHY coverage
            # is unaffected by TIP/HYG/LQD's absence.
            assert math.isfinite(values.vix_z)
            assert math.isfinite(values.yield_slope_z)


# ---------------------------------------------------------------------------
# Test 10: compute_batch external state injection
# ---------------------------------------------------------------------------


class TestComputeBatchExternalInjection:
    def test_cross_asset_from_dict_not_cache(self) -> None:
        """When cross_asset_by_date supplied, FeatureVector uses dict values not cache zeros."""
        config = _make_config()
        cache = FeatureCache()  # vix_z=0.0, flight_quality=0.0, yield_slope_z=0.0

        bars = _make_bars(60)
        bar_date = bars[-1]["ts"].date()
        cross_asset = {
            bar_date: CrossAssetRecord(vix_z=1.23, flight_quality=0.45, yield_slope_z=-0.67)
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
        from src.intelligence.features.cross_asset_series import build_symbol_beta_series

        config = _make_config()
        spy = _make_daily_bars(120, seed=1, start_close=450.0)
        tlt = _make_daily_bars(120, seed=2, start_close=95.0)

        result = build_symbol_beta_series(spy, spy, tlt, "SPY", config)
        assert result, "expected at least one date"
        for _d, (equity_beta_z, _rate_beta_z) in result.items():
            assert equity_beta_z is None

    def test_tlt_rate_beta_z_always_none(self) -> None:
        """symbol='TLT' must yield rate_beta_z=None at every date."""
        from src.intelligence.features.cross_asset_series import build_symbol_beta_series

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
        from src.intelligence.features.cross_asset_series import build_symbol_beta_series

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
        from services.backfill_feature_factory import _build_ltf_return_series

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
        from services.backfill_feature_factory import _build_ltf_return_series

        base = datetime(2026, 1, 2, 14, 30, 0, tzinfo=UTC)
        closes = [100.0, 101.0, 99.5, 102.0]
        ltf_bars = [{"ts": base + timedelta(minutes=i), "close": c} for i, c in enumerate(closes)]
        target_ts_list = [base + timedelta(minutes=3)]

        result = _build_ltf_return_series(ltf_bars, target_ts_list)
        expected = math.log(closes[3] / closes[2])
        assert result[target_ts_list[0]] == pytest.approx(expected, abs=1e-12)

    def test_no_entry_before_any_eligible_1m_bar(self) -> None:
        """A target_ts strictly before the first 1m bar's ts yields no entry."""
        from services.backfill_feature_factory import _build_ltf_return_series

        base = datetime(2026, 1, 2, 14, 30, 0, tzinfo=UTC)
        ltf_bars = [{"ts": base + timedelta(minutes=i), "close": 100.0 + i} for i in range(5)]
        target_ts_list = [base - timedelta(minutes=1)]

        result = _build_ltf_return_series(ltf_bars, target_ts_list)
        assert target_ts_list[0] not in result

    def test_empty_inputs_return_empty_dict(self) -> None:
        from services.backfill_feature_factory import _build_ltf_return_series

        assert _build_ltf_return_series([], [datetime(2026, 1, 1, tzinfo=UTC)]) == {}
        assert (
            _build_ltf_return_series([{"ts": datetime(2026, 1, 1, tzinfo=UTC), "close": 1.0}], [])
            == {}
        )
