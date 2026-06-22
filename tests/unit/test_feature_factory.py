"""Unit tests for FeatureFactory + FeatureCache (Phase 137 Plan 3).

TDD protocol: all tests written RED before implementation.
Tests cover all 36 FeatureVector primitives, purity, forward-only HMM,
OHLCV-proxy flow, and cross-asset proxies.
"""

from __future__ import annotations

import math
from collections import deque
from datetime import UTC, datetime

import numpy as np

from src.intelligence.feature_cache import FeatureCache

# These imports will fail RED until implementation exists.
from src.intelligence.feature_factory import (
    FeatureFactory,
    FeatureFactoryConfig,
    _rolling_zscore,
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
        h: deque = deque(maxlen=30)
        z = _rolling_zscore(5.0, h, window=30)
        assert z == 0.0

    def test_returns_nonzero_when_sufficient_history(self) -> None:
        h: deque = deque(maxlen=30)
        for v in range(30):
            _rolling_zscore(float(v), h, window=30)
        z = _rolling_zscore(100.0, h, window=30)
        assert z != 0.0

    def test_near_zero_std_returns_zero(self) -> None:
        h: deque = deque(maxlen=30)
        for _ in range(30):
            _rolling_zscore(5.0, h, window=30)
        z = _rolling_zscore(5.0, h, window=30)
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
        """All 36 FeatureVector fields must be finite floats (no NaN, no inf)."""
        import dataclasses

        bars = _make_bars(100)
        config = _make_config()
        cache = FeatureCache()
        fv = FeatureFactory.compute(bars, "SPY", "1m", cache, config)
        fields = dataclasses.fields(fv)
        assert len(fields) == 61, f"Expected 61 fields, got {len(fields)}"
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
