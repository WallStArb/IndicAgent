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
    _TARGET_TIMEFRAMES,
    _TRADING_DAYS_PER_YEAR,
    _log_coverage_report,
    _theoretical_max,
    _vector_to_params,
    run_compute_stage,
)
from src.intelligence.feature_cache import FeatureCache
from src.intelligence.feature_factory import FeatureFactory, FeatureFactoryConfig
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
        ctf_momentum=0.0,
        ctf_vwap_align=0.0,
        ctf_regime_align=0.0,
        amihud_illiq_z=0.0,
        high_52w_dist=0.0,
        ret_skew_z=0.0,
        ret_acf1_z=0.0,
    )


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
    """All FeatureVector fields must appear in the INSERT params tuple (70 total after migration 159)."""
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
    # 1 content-key + 7 structural + 54 feature floats + 8 new columns = 70 total
    assert len(params) == 70, f"Expected 70 params, got {len(params)}"


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
        ("SPY", tf): {"fetch_complete": True, "status": "complete"} for tf in _TARGET_TIMEFRAMES
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
    assert "1m" not in _TARGET_TIMEFRAMES
    assert set(_TARGET_TIMEFRAMES) == {"5m", "15m", "1h", "1d"}


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
# Test 9: _build_cross_asset_series — O(D) incremental parity
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


def _reference_cross_asset_series(spy_bars, tlt_bars, shy_bars, config) -> dict:
    """Original O(D×N) implementation — reference for parity testing."""
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
        cache.update_cross_asset(spy_bars[:spy_end], tlt_bars[:tlt_end], shy_bars[:shy_end], config)
        result[d] = (cache.vix_z, cache.flight_quality, cache.yield_slope_z)
    return result


class TestBuildCrossAssetSeries:
    def test_parity_with_reference_implementation(self) -> None:
        """New incremental O(D) implementation must produce identical values to O(D×N) reference."""
        from services.backfill_feature_factory import _build_cross_asset_series

        config = _make_config()
        spy = _make_daily_bars(300, seed=1, start_close=450.0)
        tlt = _make_daily_bars(300, seed=2, start_close=95.0)
        shy = _make_daily_bars(300, seed=3, start_close=86.0)

        reference = _reference_cross_asset_series(spy, tlt, shy, config)
        result = _build_cross_asset_series(spy, tlt, shy, config)

        assert set(result.keys()) == set(reference.keys()), "date keys differ"
        for d in reference:
            ref_vix, ref_fq, ref_ys = reference[d]
            res_vix, res_fq, res_ys = result[d]
            assert abs(res_vix - ref_vix) < 1e-10, f"{d}: vix_z {res_vix} != {ref_vix}"
            assert abs(res_fq - ref_fq) < 1e-10, f"{d}: flight_quality {res_fq} != {ref_fq}"
            assert abs(res_ys - ref_ys) < 1e-10, f"{d}: yield_slope_z {res_ys} != {ref_ys}"

    def test_all_values_finite(self) -> None:
        from services.backfill_feature_factory import _build_cross_asset_series

        config = _make_config()
        spy = _make_daily_bars(50, seed=10)
        tlt = _make_daily_bars(50, seed=11)
        shy = _make_daily_bars(50, seed=12)
        result = _build_cross_asset_series(spy, tlt, shy, config)
        for d, (vix, fq, ys) in result.items():
            assert math.isfinite(vix), f"{d}: vix_z not finite"
            assert math.isfinite(fq), f"{d}: flight_quality not finite"
            assert math.isfinite(ys), f"{d}: yield_slope_z not finite"
