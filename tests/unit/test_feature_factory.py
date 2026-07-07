"""Unit tests for FeatureFactory + FeatureCache (Phase 137 Plan 3).

TDD protocol: all tests written RED before implementation.
Tests cover all 36 FeatureVector primitives, purity, forward-only HMM,
OHLCV-proxy flow, and cross-asset proxies.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime

import numpy as np

from src.intelligence.feature_cache import FeatureCache

# These imports will fail RED until implementation exists.
from src.intelligence.feature_factory import (
    FeatureFactory,
    FeatureFactoryConfig,
    _rolling_zscore_series,
)
from src.intelligence.schemas import FeatureVector

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_config(**overrides: int) -> FeatureFactoryConfig:
    """Return a minimal FeatureFactoryConfig for testing. All numeric params explicit."""
    defaults = dict(
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
        amihud_zscore_window=20,
        ret_skew_window=10,
        ret_skew_zscore_window=20,
        ret_acf_window=5,
        ret_acf_zscore_window=20,
        high_52w_window=20,
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
    )
    defaults.update(overrides)
    return FeatureFactoryConfig(**defaults)


def _make_bars(n: int = 100, seed: int = 42) -> list[dict]:
    """Generate n synthetic OHLCV bars as dicts."""
    rng = np.random.default_rng(seed)
    bars = []
    close = 100.0
    ts = datetime(2026, 1, 2, 9, 30, tzinfo=UTC)
    import datetime as dt

    for i in range(n):
        r = rng.normal(0.0, 0.01)
        close = close * (1 + r)
        open_ = close * (1 + rng.normal(0.0, 0.002))
        high = max(close, open_) * (1 + abs(rng.normal(0.0, 0.003)))
        low = min(close, open_) * (1 - abs(rng.normal(0.0, 0.003)))
        vol = float(rng.integers(10_000, 100_000))
        bars.append(
            {
                "open": open_,
                "high": high,
                "low": low,
                "close": close,
                "volume": vol,
                "ts": ts + dt.timedelta(minutes=i),
            }
        )
    return bars


def _make_cache(**overrides: float) -> FeatureCache:
    """Return a default FeatureCache."""
    cache = FeatureCache()
    for k, v in overrides.items():
        object.__setattr__(cache, k, v) if False else setattr(cache, k, v)
    return cache


# ---------------------------------------------------------------------------
# Task 1: bar-level and calendar primitives
# ---------------------------------------------------------------------------


class TestRollingZscore:
    def test_returns_zero_when_insufficient_history(self) -> None:
        arr = np.array([5.0])
        z = _rolling_zscore_series(arr, window=30)[-1]
        assert z == 0.0

    def test_returns_nonzero_when_sufficient_history(self) -> None:
        arr = np.array([float(v) for v in range(30)] + [100.0])
        z = _rolling_zscore_series(arr, window=30)[-1]
        assert z != 0.0

    def test_near_zero_std_returns_zero(self) -> None:
        arr = np.full(30, 5.0)
        z = _rolling_zscore_series(arr, window=30)[-1]
        assert z == 0.0


class TestBarLevelPrimitives:
    """Tests for bar-level primitives — deterministic given exact input values."""

    def test_bar_close_pos_midpoint(self) -> None:
        """(close - low) / (high - low) = 0.5 when close is mid."""
        bars = _make_bars(50)
        # Override last bar
        bars[-1]["high"] = 10.0
        bars[-1]["low"] = 8.0
        bars[-1]["close"] = 9.0
        bars[-1]["open"] = 9.0
        config = _make_config()
        cache = _make_cache()
        fv = FeatureFactory.compute(bars, "SPY", "1m", cache, config)
        assert math.isclose(fv.bar_close_pos, 0.5, abs_tol=1e-9)

    def test_bar_close_pos_high_equals_low_returns_half(self) -> None:
        """When high == low, epsilon guard must prevent ZeroDivisionError and return 0.5."""
        bars = _make_bars(50)
        bars[-1]["high"] = 10.0
        bars[-1]["low"] = 10.0
        bars[-1]["close"] = 10.0
        bars[-1]["open"] = 10.0
        config = _make_config()
        cache = _make_cache()
        fv = FeatureFactory.compute(bars, "SPY", "1m", cache, config)
        assert math.isfinite(fv.bar_close_pos)
        assert fv.bar_close_pos == 0.5

    def test_ofi_z_is_ohlcv_proxy_not_tick_path(self) -> None:
        """ofi_z must be computed without tick_buffer (OHLCV proxy only)."""
        import subprocess

        result = subprocess.run(
            ["grep", "-n", "tick_buffer", "src/intelligence/feature_factory.py"],
            capture_output=True,
            text=True,
            cwd="/home/bg/dev/indicagent",
        )
        assert (
            result.returncode != 0 or result.stdout.strip() == ""
        ), "tick_buffer reference found in feature_factory.py — OHLCV proxy path required"

    def test_rel_volume_positive(self) -> None:
        bars = _make_bars(50)
        config = _make_config()
        cache = _make_cache()
        fv = FeatureFactory.compute(bars, "SPY", "1m", cache, config)
        assert math.isfinite(fv.rel_volume)
        assert fv.rel_volume >= 0.0

    def test_volume_z_finite(self) -> None:
        bars = _make_bars(60)
        config = _make_config()
        cache = _make_cache()
        fv = FeatureFactory.compute(bars, "SPY", "1m", cache, config)
        assert math.isfinite(fv.volume_z)

    def test_informed_flow_finite(self) -> None:
        bars = _make_bars(50)
        config = _make_config()
        cache = _make_cache()
        fv = FeatureFactory.compute(bars, "SPY", "1m", cache, config)
        assert math.isfinite(fv.informed_flow)

    def test_momentum_z_fast_finite(self) -> None:
        bars = _make_bars(60)
        config = _make_config()
        cache = _make_cache()
        fv = FeatureFactory.compute(bars, "SPY", "1m", cache, config)
        assert math.isfinite(fv.momentum_z_fast)

    def test_momentum_z_mid_finite(self) -> None:
        bars = _make_bars(60)
        config = _make_config()
        cache = _make_cache()
        fv = FeatureFactory.compute(bars, "SPY", "1m", cache, config)
        assert math.isfinite(fv.momentum_z_mid)

    def test_atr_z_finite(self) -> None:
        bars = _make_bars(60)
        config = _make_config()
        cache = _make_cache()
        fv = FeatureFactory.compute(bars, "SPY", "1m", cache, config)
        assert math.isfinite(fv.atr_z)

    def test_cmf_bounded(self) -> None:
        """CMF must be in [-1, 1]."""
        bars = _make_bars(60)
        config = _make_config()
        cache = _make_cache()
        fv = FeatureFactory.compute(bars, "SPY", "1m", cache, config)
        assert -1.0 <= fv.cmf <= 1.0

    def test_vol_ratio_positive(self) -> None:
        bars = _make_bars(60)
        config = _make_config(vol_short_bars=5, vol_long_bars=20)
        cache = _make_cache()
        fv = FeatureFactory.compute(bars, "SPY", "1m", cache, config)
        assert math.isfinite(fv.vol_ratio)
        assert fv.vol_ratio >= 0.0

    def test_no_self_config_in_feature_factory(self) -> None:
        """Confirm FeatureFactory has no self._config attribute — config is an arg."""
        import subprocess

        result = subprocess.run(
            ["grep", "-n", "self._config", "src/intelligence/feature_factory.py"],
            capture_output=True,
            text=True,
            cwd="/home/bg/dev/indicagent",
        )
        assert (
            result.returncode != 0 or result.stdout.strip() == ""
        ), "self._config found in feature_factory.py — config must be a compute() argument"


class TestCalendarPrimitives:
    def test_in_ny_session_rth_hour(self) -> None:
        """Bar at 10:00 ET (14:00 UTC) should be in NY session."""

        bars = _make_bars(50)
        # Use 14:00 UTC = 10:00 ET (within 13:30-20:00 UTC for RTH)
        ny_time = datetime(2026, 6, 4, 14, 0, tzinfo=UTC)  # Wednesday
        bars[-1]["ts"] = ny_time
        config = _make_config()
        cache = _make_cache()
        fv = FeatureFactory.compute(bars, "SPY", "1m", cache, config)
        assert fv.in_ny_session == 1.0

    def test_in_ny_session_outside(self) -> None:
        """Bar at 02:00 UTC is outside NY session."""

        bars = _make_bars(50)
        bars[-1]["ts"] = datetime(2026, 6, 4, 2, 0, tzinfo=UTC)
        config = _make_config()
        cache = _make_cache()
        fv = FeatureFactory.compute(bars, "SPY", "1m", cache, config)
        assert fv.in_ny_session == 0.0

    def test_dow_sin_cos_range(self) -> None:
        """dow_sin and dow_cos must be in [-1, 1]."""
        bars = _make_bars(50)
        config = _make_config()
        cache = _make_cache()
        fv = FeatureFactory.compute(bars, "SPY", "1m", cache, config)
        assert -1.0 <= fv.dow_sin <= 1.0
        assert -1.0 <= fv.dow_cos <= 1.0

    def test_month_position_range(self) -> None:
        """month_position must be in (0, 1]."""
        bars = _make_bars(50)
        config = _make_config()
        cache = _make_cache()
        fv = FeatureFactory.compute(bars, "SPY", "1m", cache, config)
        assert 0.0 < fv.month_position <= 1.0

    def test_in_overlap_london_ny(self) -> None:
        """Bar at 09:00 UTC is in London-NY overlap (08:00-11:00 ET = 12:00-15:00 UTC)."""
        bars = _make_bars(50)
        # 13:00 UTC = 09:00 ET - in overlap
        bars[-1]["ts"] = datetime(2026, 6, 4, 13, 0, tzinfo=UTC)
        config = _make_config()
        cache = _make_cache()
        fv = FeatureFactory.compute(bars, "SPY", "1m", cache, config)
        assert fv.in_overlap == 1.0


# ---------------------------------------------------------------------------
# Task 2: regime, session, structural, and CTF primitives
# ---------------------------------------------------------------------------


class TestRegimePrimitives:
    def test_hmm_regime_prob_from_cache(self) -> None:
        """hmm_regime_prob must come from FeatureCache, not recomputed per bar."""
        bars = _make_bars(60)
        config = _make_config()
        cache = _make_cache()
        cache.hmm_regime_prob = 0.77
        fv = FeatureFactory.compute(bars, "SPY", "1m", cache, config)
        assert math.isclose(fv.hmm_regime_prob, 0.77, abs_tol=1e-9)

    def test_hmm_entropy_from_cache(self) -> None:
        bars = _make_bars(60)
        config = _make_config()
        cache = _make_cache()
        cache.hmm_entropy = 0.33
        fv = FeatureFactory.compute(bars, "SPY", "1m", cache, config)
        assert math.isclose(fv.hmm_entropy, 0.33, abs_tol=1e-9)

    def test_hurst_from_cache(self) -> None:
        bars = _make_bars(60)
        config = _make_config()
        cache = _make_cache()
        cache.hurst = 0.62
        fv = FeatureFactory.compute(bars, "SPY", "1m", cache, config)
        assert math.isclose(fv.hurst, 0.62, abs_tol=1e-9)

    def test_shannon_from_cache(self) -> None:
        bars = _make_bars(60)
        config = _make_config()
        cache = _make_cache()
        cache.shannon = 0.88
        fv = FeatureFactory.compute(bars, "SPY", "1m", cache, config)
        assert math.isclose(fv.shannon, 0.88, abs_tol=1e-9)

    def test_garch_ratio_from_cache(self) -> None:
        bars = _make_bars(60)
        config = _make_config()
        cache = _make_cache()
        cache.garch_ratio = 1.25
        fv = FeatureFactory.compute(bars, "SPY", "1m", cache, config)
        assert math.isclose(fv.garch_ratio, 1.25, abs_tol=1e-9)

    def test_adx_from_cache(self) -> None:
        bars = _make_bars(60)
        config = _make_config()
        cache = _make_cache()
        cache.adx = 28.5
        fv = FeatureFactory.compute(bars, "SPY", "1m", cache, config)
        assert math.isclose(fv.adx, 28.5, abs_tol=1e-9)

    def test_hma_slope_z_from_cache(self) -> None:
        bars = _make_bars(60)
        config = _make_config()
        cache = _make_cache()
        cache.hma_slope_z = 1.5
        fv = FeatureFactory.compute(bars, "SPY", "1m", cache, config)
        assert math.isclose(fv.hma_slope_z, 1.5, abs_tol=1e-9)

    def test_no_smooth_or_backward_in_factory(self) -> None:
        """No backward smoother reference in feature_factory.py regime path."""
        import subprocess

        result = subprocess.run(
            ["grep", "-nE", "_smooth|smoothed|backward", "src/intelligence/feature_factory.py"],
            capture_output=True,
            text=True,
            cwd="/home/bg/dev/indicagent",
        )
        assert (
            result.returncode != 0 or result.stdout.strip() == ""
        ), "Backward smoother reference found in feature_factory.py — forward only permitted"

    def test_refresh_regime_updates_cache(self) -> None:
        """FeatureCache.refresh_regime updates regime fields in cache."""
        bars = _make_bars(100)
        config = _make_config()
        cache = FeatureCache()
        # Initially default values
        assert cache.hmm_regime_prob == 0.0
        cache.refresh_regime(bars, config)
        # After refresh, hmm_regime_prob should be set (0.0 is valid on cold start)
        assert math.isfinite(cache.hmm_regime_prob)
        # bars_since_regime_refresh should be reset to 0
        assert cache.bars_since_regime_refresh == 0


class TestSessionPrimitives:
    def test_session_poc_dist_from_cache(self) -> None:
        """Session poc_dist_atr comes from FeatureCache."""
        bars = _make_bars(60)
        config = _make_config()
        cache = _make_cache()
        cache.poc_dist_atr = 0.42
        fv = FeatureFactory.compute(bars, "SPY", "1m", cache, config)
        assert math.isclose(fv.poc_dist_atr, 0.42, abs_tol=1e-9)

    def test_session_va_position_from_cache(self) -> None:
        bars = _make_bars(60)
        config = _make_config()
        cache = _make_cache()
        cache.va_position = 0.73
        fv = FeatureFactory.compute(bars, "SPY", "1m", cache, config)
        assert math.isclose(fv.va_position, 0.73, abs_tol=1e-9)

    def test_session_sr_support_from_cache(self) -> None:
        bars = _make_bars(60)
        config = _make_config()
        cache = _make_cache()
        cache.sr_support_dist = 1.2
        fv = FeatureFactory.compute(bars, "SPY", "1m", cache, config)
        assert math.isclose(fv.sr_support_dist, 1.2, abs_tol=1e-9)

    def test_1d_tf_session_features_are_defaults(self) -> None:
        """For tf='1d', session-level features must be zero/0.5 (intraday concepts)."""
        bars = _make_bars(60)
        config = _make_config()
        cache = _make_cache()
        # Set cache values to non-default to confirm 1d override
        cache.poc_dist_atr = 2.0
        cache.va_position = 0.8
        cache.sr_support_dist = 3.0
        cache.sr_resist_dist = 4.0
        fv = FeatureFactory.compute(bars, "SPY", "1d", cache, config)
        assert fv.poc_dist_atr == 0.0
        assert fv.va_position == 0.5
        assert fv.sr_support_dist == 0.0
        assert fv.sr_resist_dist == 0.0

    def test_vwap_dev_sigma_finite(self) -> None:
        bars = _make_bars(60)
        config = _make_config()
        cache = _make_cache()
        fv = FeatureFactory.compute(bars, "SPY", "1m", cache, config)
        assert math.isfinite(fv.vwap_dev_sigma)


class TestCTFPrimitives:
    def test_ctf_momentum_from_cache(self) -> None:
        """ctf_momentum comes from FeatureCache, not computed in compute()."""
        bars = _make_bars(60)
        config = _make_config()
        cache = _make_cache()
        cache.ctf_momentum = 0.55
        fv = FeatureFactory.compute(bars, "SPY", "1m", cache, config)
        assert math.isclose(fv.ctf_momentum, 0.55, abs_tol=1e-9)

    def test_ctf_vwap_align_from_cache(self) -> None:
        bars = _make_bars(60)
        config = _make_config()
        cache = _make_cache()
        cache.ctf_vwap_align = -0.25
        fv = FeatureFactory.compute(bars, "SPY", "1m", cache, config)
        assert math.isclose(fv.ctf_vwap_align, -0.25, abs_tol=1e-9)

    def test_ctf_regime_align_from_cache(self) -> None:
        bars = _make_bars(60)
        config = _make_config()
        cache = _make_cache()
        cache.ctf_regime_align = 0.9
        fv = FeatureFactory.compute(bars, "SPY", "1m", cache, config)
        assert math.isclose(fv.ctf_regime_align, 0.9, abs_tol=1e-9)


# ---------------------------------------------------------------------------
# Task 3: Assemble compute(), cross-asset proxies, purity + completeness
# ---------------------------------------------------------------------------


class TestComputePurity:
    def test_compute_returns_feature_vector(self) -> None:
        """compute() must return a FeatureVector instance."""
        bars = _make_bars(60)
        config = _make_config()
        cache = FeatureCache()
        result = FeatureFactory.compute(bars, "SPY", "1m", cache, config)
        assert isinstance(result, FeatureVector)

    def test_all_fields_are_finite_floats(self) -> None:
        """All FeatureVector fields must be finite floats (no NaN, no inf).

        61 baseline (v3.0) + 18 Plan 01 + 22 Plan 02 + 14 Plan 05 + 21 Plan 03
        Renaissance primitives = 136. (Plan 05 merged before Plans 03/04 per
        the actual dependency-DAG-valid merge order — see 142.5-05-SUMMARY.md
        Deviations; this plan's own base was 115, not the phase outline's
        assumed 101. Plan 06 reconciles the final count to 152 once every
        plan has landed, regardless of merge order.)
        """
        import dataclasses

        bars = _make_bars(100)
        config = _make_config()
        cache = FeatureCache()
        fv = FeatureFactory.compute(bars, "SPY", "1m", cache, config)
        fields = dataclasses.fields(fv)
        assert len(fields) == 136, f"Expected 136 fields, got {len(fields)}"
        for f in fields:
            val = getattr(fv, f.name)
            # Optional cross-sectional fields (momentum_rank_z, volume_rank_z,
            # volatility_rank_z) are None until batch enrichment; skip them.
            if val is None:
                continue
            assert math.isfinite(val), f"Field {f.name} is not finite: {val}"

    def test_determinism(self) -> None:
        """Same inputs must produce identical output."""
        bars = _make_bars(60)
        config = _make_config()
        cache1 = FeatureCache()
        cache2 = FeatureCache()
        fv1 = FeatureFactory.compute(bars, "SPY", "1m", cache1, config)
        fv2 = FeatureFactory.compute(bars, "SPY", "1m", cache2, config)
        import dataclasses

        for f in dataclasses.fields(fv1):
            v1 = getattr(fv1, f.name)
            v2 = getattr(fv2, f.name)
            assert v1 == v2, f"Field {f.name}: {v1} != {v2}"

    def test_purity_no_io(self) -> None:
        """compute() with a fully-built config/cache must work without live services.

        This test runs in isolation — no ConfigService, no DB, no Kafka.
        If compute() calls ConfigService.get() internally it will raise
        because no config_service is injected.
        """
        bars = _make_bars(60)
        # Build config/cache manually — no ConfigService involved
        config = _make_config()
        cache = FeatureCache()
        # Must not raise even with no DB/ConfigService/Kafka
        fv = FeatureFactory.compute(bars, "SPY", "1m", cache, config)
        assert isinstance(fv, FeatureVector)

    def test_no_async_in_feature_factory(self) -> None:
        """feature_factory.py must not use async def or await."""
        import subprocess

        result = subprocess.run(
            ["grep", "-nE", "^(async def|    await )", "src/intelligence/feature_factory.py"],
            capture_output=True,
            text=True,
            cwd="/home/bg/dev/indicagent",
        )
        assert (
            result.returncode != 0 or result.stdout.strip() == ""
        ), "async def or await found in feature_factory.py — must be sync"

    def test_no_inline_magic_numbers(self) -> None:
        """No inline period=N, window=N, or / 252 in compute paths."""
        import subprocess

        result = subprocess.run(
            [
                "grep",
                "-nE",
                r"window=[0-9]|period=[0-9]|/ 252[^0-9]|/ 20[^0-9]",
                "src/intelligence/feature_factory.py",
            ],
            capture_output=True,
            text=True,
            cwd="/home/bg/dev/indicagent",
        )
        # Allow zero matches
        lines = [
            ln
            for ln in (result.stdout.strip().split("\n") if result.stdout.strip() else [])
            if ln.strip() and "# APR:" not in ln  # Allow comment annotations
        ]
        assert not lines, "Inline magic numbers found:\n" + "\n".join(lines)


class TestCrossAssetProxies:
    def test_update_cross_asset_populates_vix_z(self) -> None:
        """FeatureCache.update_cross_asset must compute vix_z from SPY bars."""
        spy_bars = _make_bars(60, seed=1)
        tlt_bars = _make_bars(60, seed=2)
        shy_bars = _make_bars(60, seed=3)
        config = _make_config()
        cache = FeatureCache()
        cache.update_cross_asset(spy_bars, tlt_bars, shy_bars, config)
        assert math.isfinite(cache.vix_z)

    def test_update_cross_asset_populates_flight_quality(self) -> None:
        """flight_quality = TLT/SPY relative-return divergence."""
        spy_bars = _make_bars(60, seed=1)
        tlt_bars = _make_bars(60, seed=2)
        shy_bars = _make_bars(60, seed=3)
        config = _make_config()
        cache = FeatureCache()
        cache.update_cross_asset(spy_bars, tlt_bars, shy_bars, config)
        assert math.isfinite(cache.flight_quality)

    def test_update_cross_asset_populates_yield_slope_z(self) -> None:
        """yield_slope_z = z-score of TLT/SHY return ratio."""
        spy_bars = _make_bars(60, seed=1)
        tlt_bars = _make_bars(60, seed=2)
        shy_bars = _make_bars(60, seed=3)
        config = _make_config()
        cache = FeatureCache()
        cache.update_cross_asset(spy_bars, tlt_bars, shy_bars, config)
        assert math.isfinite(cache.yield_slope_z)

    def test_cross_asset_values_appear_in_compute_output(self) -> None:
        """compute() must surface vix_z/flight_quality/yield_slope_z from cache."""
        bars = _make_bars(60)
        config = _make_config()
        cache = FeatureCache()
        cache.vix_z = 1.23
        cache.flight_quality = -0.45
        cache.yield_slope_z = 0.67
        fv = FeatureFactory.compute(bars, "SPY", "1m", cache, config)
        assert math.isclose(fv.vix_z, 1.23, abs_tol=1e-9)
        assert math.isclose(fv.flight_quality, -0.45, abs_tol=1e-9)
        assert math.isclose(fv.yield_slope_z, 0.67, abs_tol=1e-9)


# ---------------------------------------------------------------------------
# Phase 142.5 (Renaissance Primitives) — Wave 0 RED tests
#
# 91 new primitives across 11 categories (61 baseline + 91 = 152 total
# FeatureVector fields at end of phase). DO NOT implement primitives here —
# these tests must fail RED (AttributeError: FeatureVector has no field X)
# until Plans 01/02/03/04/05/05.5 add the fields. See:
#   .planning/phases/142.5-renaissance-primitives/142.5-PLAN-OUTLINE.md
#   docs/ideas/signal-renaissance-primitives-ohlcv.md
# ---------------------------------------------------------------------------

# Canonical list of all 91 new field names, grouped by category in plan order.
# Used by test_compute_batch_parity to guard against per-bar/vectorized
# divergence (M1) once these fields exist.
RENAISSANCE_PRIMITIVE_FIELDS: tuple[str, ...] = (
    # Bar Anatomy (8)
    "body_ratio",
    "upper_wick_ratio",
    "lower_wick_ratio",
    "range_vs_atr",
    "close_vs_open_direction",
    "overnight_gap",
    "overnight_gap_z",
    "range_efficiency",
    # Lagged Returns (6)
    "ret_lag_1",
    "ret_lag_2",
    "ret_lag_3",
    "ret_lag_fast",
    "ret_lag_mid",
    "ret_lag_slow",
    # Open-to-Close Split (4)
    "open_ret",
    "intraday_ret",
    "open_vs_intraday",
    "session_time_pos",
    # Temporal Coordinates: new pairs + month_sin/cos (10)
    "hour_of_day_sin",
    "hour_of_day_cos",
    "week_of_month_sin",
    "week_of_month_cos",
    "day_of_month_sin",
    "day_of_month_cos",
    "week_of_year_sin",
    "week_of_year_cos",
    "month_sin",
    "month_cos",
    # Volume Structure (12)
    "vol_acceleration",
    "dollar_vol_z",
    "vol_range_ratio",
    "vol_trend_ratio",
    "up_vol_ratio_fast",
    "up_vol_ratio_slow",
    "vol_percentile",
    "vol_persistence",
    "vol_std_z",
    "mfi_fast",
    "mfi_slow",
    "obv_z",
    # Return Distribution (7)
    "ret_kurtosis_z_fast",
    "ret_kurtosis_z_slow",
    "ret_autocorr_1",
    "ret_autocorr_5",
    "updown_ratio_fast",
    "updown_ratio_slow",
    "streak_z",
    # Realized Variance (14)
    "realized_var_ratio_fast",
    "realized_var_ratio_slow",
    "range_to_close",
    "true_range_pct",
    "vol_of_vol",
    "high_low_corr",
    "variance_ratio_fast",
    "variance_ratio_slow",
    "vol_asymmetry_z",
    "bb_pct_b_fast",
    "bb_pct_b_slow",
    "hv_z_fast",
    "hv_z_slow",
    "hv_ratio",
    # Alternative Volatility (3)
    "parkinson_vol_z",
    "garman_klass_vol_z",
    "yang_zhang_vol_z",
    # Volatility Dynamics (5)
    "parkinson_vol_velocity",
    "garman_klass_vol_velocity",
    "yang_zhang_vol_velocity",
    "vol_velocity_z",
    "intraday_noise_ratio",
    # Breakout Distance (14)
    "dist_from_high_fast",
    "dist_from_high_slow",
    "dist_from_low_fast",
    "dist_from_low_slow",
    "range_pct_fast",
    "range_pct_slow",
    "new_high_flag",
    "new_low_flag",
    "stoch_k_fast",
    "stoch_k_slow",
    "price_percentile_fast",
    "price_percentile_slow",
    "efficiency_ratio_fast",
    "efficiency_ratio_slow",
    # Price-Volume Interactions (8)
    "vol_body_product",
    "ret_vol_product_fast",
    "price_vol_corr_fast",
    "price_vol_corr_slow",
    "range_vol_product",
    "up_vol_body_diff",
    "ret_vol_ratio_fast",
    "vol_skew_product",
)

assert (
    len(RENAISSANCE_PRIMITIVE_FIELDS) == 91
), f"Expected 91 Renaissance primitive field names, got {len(RENAISSANCE_PRIMITIVE_FIELDS)}"


def test_bar_anatomy_primitives() -> None:
    """8 bar-anatomy ratios: body_ratio, upper/lower_wick_ratio, range_vs_atr,
    close_vs_open_direction, overnight_gap(+z), range_efficiency.
    """
    bars = _make_bars(60)
    config = _make_config()
    cache = _make_cache()
    fv = FeatureFactory.compute(bars, "SPY", "1m", cache, config)

    # body_ratio = (C - O) / (H - L), bounded [-1, 1]
    assert -1.0 <= fv.body_ratio <= 1.0
    # upper/lower wick ratios bounded [0, 1]
    assert 0.0 <= fv.upper_wick_ratio <= 1.0
    assert 0.0 <= fv.lower_wick_ratio <= 1.0
    # range_vs_atr: (H - L) / ATR_N, unbounded positive
    assert fv.range_vs_atr >= 0.0
    # close_vs_open_direction: sign(C - O), categorical {-1, 0, 1}
    assert fv.close_vs_open_direction in (-1.0, 0.0, 1.0)
    # overnight_gap / overnight_gap_z: unbounded, finite
    assert math.isfinite(fv.overnight_gap)
    assert math.isfinite(fv.overnight_gap_z)
    # range_efficiency: abs(C - prev_C) / (H - L), bounded [0, 1]
    assert 0.0 <= fv.range_efficiency <= 1.0

    # Edge case: degenerate bar (high == low) must not raise; epsilon guard applies.
    bars_degenerate = _make_bars(60)
    bars_degenerate[-1]["high"] = 10.0
    bars_degenerate[-1]["low"] = 10.0
    bars_degenerate[-1]["close"] = 10.0
    bars_degenerate[-1]["open"] = 10.0
    fv_deg = FeatureFactory.compute(bars_degenerate, "SPY", "1m", cache, config)
    assert math.isfinite(fv_deg.body_ratio)
    assert math.isfinite(fv_deg.upper_wick_ratio)
    assert math.isfinite(fv_deg.lower_wick_ratio)
    assert math.isfinite(fv_deg.range_efficiency)


def test_lagged_returns() -> None:
    """6 lagged log-return primitives: ret_lag_1/2/3 (definitional) +
    ret_lag_fast/mid/slow (APR-backed gradient windows).
    """
    bars = _make_bars(80)
    config = _make_config()
    cache = _make_cache()
    fv = FeatureFactory.compute(bars, "SPY", "1m", cache, config)

    for field_name in (
        "ret_lag_1",
        "ret_lag_2",
        "ret_lag_3",
        "ret_lag_fast",
        "ret_lag_mid",
        "ret_lag_slow",
    ):
        val = getattr(fv, field_name)
        assert math.isfinite(val), f"{field_name} must be finite, got {val}"

    # Edge case: insufficient history (fewer bars than the longest lag) must
    # not raise — cold-start neutral value (0.0) expected.
    bars_short = _make_bars(2)
    fv_short = FeatureFactory.compute(bars_short, "SPY", "1m", cache, config)
    assert math.isfinite(fv_short.ret_lag_3)
    assert math.isfinite(fv_short.ret_lag_slow)


def test_open_to_close_split() -> None:
    """4 primitives decomposing total return into overnight/intraday components."""
    bars = _make_bars(60)
    config = _make_config()
    cache = _make_cache()
    fv = FeatureFactory.compute(bars, "SPY", "1m", cache, config)

    # open_ret = log(O_t / C_{t-1}); intraday_ret = log(C_t / O_t); both unbounded finite.
    assert math.isfinite(fv.open_ret)
    assert math.isfinite(fv.intraday_ret)
    # open_vs_intraday = open_ret - intraday_ret, unbounded finite.
    assert math.isclose(fv.open_vs_intraday, fv.open_ret - fv.intraday_ret, abs_tol=1e-9)
    # session_time_pos = bar_index_in_session / total_session_bars, bounded [0, 1].
    assert 0.0 <= fv.session_time_pos <= 1.0


def test_temporal_coordinates() -> None:
    """10 sin/cos temporal coordinates: hour_of_day, week_of_month, day_of_month,
    week_of_year (all NEW) + month_sin/cos (NEW pair; only month_position existed
    before). All bounded [-1, 1] — circular calendar arithmetic, no state.
    """
    bars = _make_bars(50)
    config = _make_config()
    cache = _make_cache()
    bars[-1]["ts"] = datetime(2026, 6, 19, 14, 30, tzinfo=UTC)  # 3rd Friday-ish
    fv = FeatureFactory.compute(bars, "SPY", "1m", cache, config)

    for field_name in (
        "hour_of_day_sin",
        "hour_of_day_cos",
        "week_of_month_sin",
        "week_of_month_cos",
        "day_of_month_sin",
        "day_of_month_cos",
        "week_of_year_sin",
        "week_of_year_cos",
        "month_sin",
        "month_cos",
    ):
        val = getattr(fv, field_name)
        assert -1.0 <= val <= 1.0, f"{field_name} must be in [-1, 1], got {val}"


def test_volume_structure() -> None:
    """12 volume-structure primitives beyond simple z-scores of volume level."""
    bars = _make_bars(80)
    config = _make_config()
    cache = _make_cache()
    fv = FeatureFactory.compute(bars, "SPY", "1m", cache, config)

    # vol_acceleration = V_t / V_{t-1}, unbounded positive.
    assert fv.vol_acceleration >= 0.0
    # z-scored primitives, finite, centered at 0.
    for field_name in ("dollar_vol_z", "vol_std_z", "obv_z"):
        assert math.isfinite(getattr(fv, field_name))
    # unbounded positive ratios.
    assert fv.vol_range_ratio >= 0.0
    assert fv.vol_trend_ratio >= 0.0
    # up_vol_ratio_fast/slow bounded [0, 1] (fraction of volume on up bars).
    assert 0.0 <= fv.up_vol_ratio_fast <= 1.0
    assert 0.0 <= fv.up_vol_ratio_slow <= 1.0
    # vol_percentile bounded [0, 1] (rolling percentile rank).
    assert 0.0 <= fv.vol_percentile <= 1.0
    # vol_persistence bounded [-1, 1] (lag-1 autocorrelation of volume).
    assert -1.0 <= fv.vol_persistence <= 1.0
    # mfi_fast/slow bounded [0, 100] (Money Flow Index, RSI-like).
    assert 0.0 <= fv.mfi_fast <= 100.0
    assert 0.0 <= fv.mfi_slow <= 100.0

    # Edge case: zero volume on prior bar must not raise ZeroDivisionError
    # (epsilon guard on vol_acceleration = V_t / V_{t-1}).
    bars_zero_vol = _make_bars(80)
    bars_zero_vol[-2]["volume"] = 0.0
    fv_zero = FeatureFactory.compute(bars_zero_vol, "SPY", "1m", cache, config)
    assert math.isfinite(fv_zero.vol_acceleration)


def test_return_distribution() -> None:
    """7 return-distribution primitives: kurtosis, autocorrelation, win-rate, streak."""
    bars = _make_bars(80)
    config = _make_config()
    cache = _make_cache()
    fv = FeatureFactory.compute(bars, "SPY", "1m", cache, config)

    assert math.isfinite(fv.ret_kurtosis_z_fast)
    assert math.isfinite(fv.ret_kurtosis_z_slow)
    # ret_autocorr_1/5: mathematically bounded [-1, 1].
    assert -1.0 <= fv.ret_autocorr_1 <= 1.0
    assert -1.0 <= fv.ret_autocorr_5 <= 1.0
    # updown_ratio_fast/slow: count(up) / count(down), unbounded non-negative.
    assert fv.updown_ratio_fast >= 0.0
    assert fv.updown_ratio_slow >= 0.0
    # streak_z: z-scored signed directional streak length.
    assert math.isfinite(fv.streak_z)


def test_realized_variance() -> None:
    """14 realized-variance / volatility-structure primitives."""
    bars = _make_bars(80)
    config = _make_config()
    cache = _make_cache()
    fv = FeatureFactory.compute(bars, "SPY", "1m", cache, config)

    # unbounded positive ratios, centered near 1.0 under random walk.
    assert fv.realized_var_ratio_fast >= 0.0
    assert fv.realized_var_ratio_slow >= 0.0
    assert fv.variance_ratio_fast >= 0.0
    assert fv.variance_ratio_slow >= 0.0
    assert fv.hv_ratio >= 0.0
    # unbounded positive (price-normalized range).
    assert fv.range_to_close >= 0.0
    assert fv.true_range_pct >= 0.0
    # z-scored, finite.
    for field_name in ("vol_of_vol", "vol_asymmetry_z", "hv_z_fast", "hv_z_slow"):
        assert math.isfinite(getattr(fv, field_name))
    # high_low_corr bounded [-1, 1] (correlation of H and L over N bars).
    assert -1.0 <= fv.high_low_corr <= 1.0
    # bb_pct_b_fast/slow: nominally [0, 1] but unbounded in practice (price can
    # exit its own bands) — only assert finiteness.
    assert math.isfinite(fv.bb_pct_b_fast)
    assert math.isfinite(fv.bb_pct_b_slow)

    # Edge case: insufficient history (fewer bars than longest window) must
    # not raise — cold-start neutral fallback expected.
    bars_short = _make_bars(3)
    fv_short = FeatureFactory.compute(bars_short, "SPY", "1m", cache, config)
    assert math.isfinite(fv_short.variance_ratio_slow)
    assert math.isfinite(fv_short.hv_z_slow)


def test_alt_volatility() -> None:
    """3 alternative OHLC-based volatility estimators: Parkinson, Garman-Klass, Yang-Zhang."""
    bars = _make_bars(80)
    config = _make_config()
    cache = _make_cache()
    fv = FeatureFactory.compute(bars, "SPY", "1m", cache, config)

    # All z-scored, centered at 0, finite.
    assert math.isfinite(fv.parkinson_vol_z)
    assert math.isfinite(fv.garman_klass_vol_z)
    assert math.isfinite(fv.yang_zhang_vol_z)


def test_volatility_dynamics() -> None:
    """5 volatility-dynamics primitives: first derivatives of the 3 estimators
    above + normalized velocity + intraday noise ratio.
    """
    bars = _make_bars(80)
    config = _make_config()
    cache = _make_cache()
    fv = FeatureFactory.compute(bars, "SPY", "1m", cache, config)

    # *_vol_velocity: first derivative of z-scored vol, unbounded, finite.
    assert math.isfinite(fv.parkinson_vol_velocity)
    assert math.isfinite(fv.garman_klass_vol_velocity)
    assert math.isfinite(fv.yang_zhang_vol_velocity)
    # vol_velocity_z: z-scored, finite.
    assert math.isfinite(fv.vol_velocity_z)
    # intraday_noise_ratio: unbounded positive [1, inf) per spec; require > 0.
    assert fv.intraday_noise_ratio > 0.0


def test_breakout_distance() -> None:
    """14 breakout-distance primitives: raw distance from recent extremes,
    range position, and trend-purity measures — no S/R zone theory.
    """
    bars = _make_bars(100)
    config = _make_config()
    cache = _make_cache()
    fv = FeatureFactory.compute(bars, "SPY", "1m", cache, config)

    # dist_from_high/low_*: (rolling_extreme - C) / ATR, unbounded non-negative.
    assert fv.dist_from_high_fast >= 0.0
    assert fv.dist_from_high_slow >= 0.0
    assert fv.dist_from_low_fast >= 0.0
    assert fv.dist_from_low_slow >= 0.0
    # range_pct_fast/slow: (rolling_high - rolling_low) / C, unbounded non-negative.
    assert fv.range_pct_fast >= 0.0
    assert fv.range_pct_slow >= 0.0
    # new_high_flag / new_low_flag: binary {0, 1}.
    assert fv.new_high_flag in (0.0, 1.0)
    assert fv.new_low_flag in (0.0, 1.0)
    # stoch_k_fast/slow: (C - L_N) / (H_N - L_N), bounded [0, 1].
    assert 0.0 <= fv.stoch_k_fast <= 1.0
    assert 0.0 <= fv.stoch_k_slow <= 1.0
    # price_percentile_fast/slow: rolling percentile rank, bounded [0, 1].
    assert 0.0 <= fv.price_percentile_fast <= 1.0
    assert 0.0 <= fv.price_percentile_slow <= 1.0
    # efficiency_ratio_fast/slow: Kaufman ER, bounded [0, 1] (0=chop, 1=trend).
    assert 0.0 <= fv.efficiency_ratio_fast <= 1.0
    assert 0.0 <= fv.efficiency_ratio_slow <= 1.0

    # Edge case: bar closing exactly at the rolling high must set new_high_flag.
    bars_new_high = _make_bars(100)
    rolling_high = max(b["high"] for b in bars_new_high[-21:-1])
    bars_new_high[-1]["high"] = rolling_high + 1.0
    bars_new_high[-1]["close"] = rolling_high + 1.0
    fv_high = FeatureFactory.compute(bars_new_high, "SPY", "1m", cache, config)
    assert fv_high.new_high_flag == 1.0


def test_price_volume_interactions() -> None:
    """8 price x volume interaction primitives — deterministic combinations of
    two atomic features (product, ratio, or rolling correlation). No theory.
    """
    bars = _make_bars(80)
    config = _make_config()
    cache = _make_cache()
    fv = FeatureFactory.compute(bars, "SPY", "1m", cache, config)

    # Products/ratios: unbounded, symmetric around 0, finite.
    for field_name in (
        "vol_body_product",
        "ret_vol_product_fast",
        "range_vol_product",
        "ret_vol_ratio_fast",
        "vol_skew_product",
    ):
        assert math.isfinite(getattr(fv, field_name)), f"{field_name} must be finite"
    # price_vol_corr_fast/slow: rolling Pearson correlation, bounded [-1, 1].
    assert -1.0 <= fv.price_vol_corr_fast <= 1.0
    assert -1.0 <= fv.price_vol_corr_slow <= 1.0
    # up_vol_body_diff: difference of two ~bounded [0,1]/[−1,1] parents, approx [-1, 1].
    assert -1.5 <= fv.up_vol_body_diff <= 1.5


def test_compute_batch_parity() -> None:
    """General regression guard (Round 2 review M1/M4): compute() (per-bar live
    path) and compute_batch() (vectorized backfill path) must return identical
    values for every Renaissance primitive on the same synthetic bar series.

    RED now: fields don't exist yet (AttributeError on first getattr). Stays
    green once Plans 01-05.5 add matching `_*_series_full` precompute helpers
    — catching any per-bar/vectorized divergence (e.g. an off-by-one window
    boundary) that unit tests of either path alone would miss.
    """
    bars = _make_bars(120)
    config = _make_config()
    cache_live = FeatureCache()
    cache_batch = FeatureCache()

    live_fv = FeatureFactory.compute(bars, "SPY", "5m", cache_live, config)
    batch_results = FeatureFactory.compute_batch(bars, "SPY", "5m", cache_batch, config)
    assert batch_results, "compute_batch() returned no rows"
    _, batch_fv = batch_results[-1]

    for field_name in RENAISSANCE_PRIMITIVE_FIELDS:
        live_val = getattr(live_fv, field_name)
        batch_val = getattr(batch_fv, field_name)
        if live_val is None or batch_val is None:
            continue
        assert math.isclose(
            live_val, batch_val, abs_tol=1e-6
        ), f"Parity mismatch for {field_name}: compute()={live_val} vs compute_batch()={batch_val}"
