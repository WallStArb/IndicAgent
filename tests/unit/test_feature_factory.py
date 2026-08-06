"""Unit tests for FeatureFactory + FeatureCache (Phase 137 Plan 3).

TDD protocol: all tests written RED before implementation.
Tests cover the Phase 137 baseline FeatureVector primitives (36 at the time;
FeatureVector has grown to 249 since -- later additions are covered by
dedicated test files, e.g. test_feature_factory_p7.py), purity, forward-only
HMM, OHLCV-proxy flow, and cross-asset proxies.
"""

from __future__ import annotations

import math
import re
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pytest

from src.intelligence.feature_cache import CrossAssetState, FeatureCache

# These imports will fail RED until implementation exists.
from src.intelligence.feature_factory import (
    FeatureFactory,
    FeatureFactoryConfig,
    _dist_from_high_series_full,
    _dist_from_low_series_full,
    _informed_flow,
    _is_valid_atr,
    _is_valid_atr_series,
    _range_vs_atr,
    _rolling_zscore_series,
)
from src.intelligence.schemas import FeatureVector

# ---------------------------------------------------------------------------
# todo 086: structurally excludes the one deliberate, documented acausal
# reference (_canary_acausal_placebo(), a positive-control canary -- see
# feature_factory.py's own docstring on it) by stripping its function body,
# rather than a line-number allowlist that would rot as the file grows.
# ---------------------------------------------------------------------------

_CANARY_DEF_PATTERN = re.compile(r"\ndef _canary_acausal_placebo\(.*?(?=\ndef |\Z)", re.DOTALL)


def _source_without_acausal_canary(source: str) -> tuple[str, int]:
    """Strip _canary_acausal_placebo's definition; returns (stripped, n_stripped)."""
    return _CANARY_DEF_PATTERN.subn("\n", source, count=1)


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
        # Plan 04 added 8 more: parkinson_vol_window/zscore_window,
        # garman_klass_vol_window/zscore_window, yang_zhang_vol_window/
        # zscore_window, vol_velocity_window, intraday_noise_window.
        parkinson_vol_window=10,
        parkinson_vol_zscore_window=20,
        garman_klass_vol_window=10,
        garman_klass_vol_zscore_window=20,
        yang_zhang_vol_window=20,
        yang_zhang_vol_zscore_window=20,
        vol_velocity_window=20,
        intraday_noise_window=20,
        # Plan 05.5 added 2 more: price_vol_corr_fast/slow.
        price_vol_corr_fast=10,
        price_vol_corr_slow=30,
        momentum_velocity_window=20,
        vwap_velocity_window=20,
        extreme_move_sigma_threshold=2.0,
        vol_spike_threshold=2.0,
        # Plan 04 (Phase 151) added 7 more: cross-asset spread/beta atomics.
        tip_tlt_zscore_window=20,
        hyg_lqd_zscore_window=20,
        sb_corr_window_fast=10,
        sb_corr_window_slow=20,
        sb_corr_zscore_window=20,
        factor_beta_window=20,
        factor_beta_zscore_window=20,
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
    def test_hmm_regime_prob_never_leaks_cache_value(self) -> None:
        """FeatureVector.hmm_regime_prob must always be None from FeatureFactory,
        regardless of what FeatureCache's inline K=3 forward-filter HMM computed.

        regime_writer.py's fitted, BIC-selected K=5 HMM is the sole writer of
        this column (todo 205/207, 2026-07-30) -- FeatureCache's K=3 model was
        never validated and, before this fix, its value silently leaked into
        the same column name regime_writer owns, corrupting a live ML feature
        with mixed-provenance rows (confirmed: 11% same-model-invariant
        violation on SPY/1d). This test replaces
        test_hmm_regime_prob_from_cache, which asserted the leak itself as
        correct behavior.
        """
        bars = _make_bars(60)
        config = _make_config()
        cache = _make_cache()
        cache.hmm_regime_prob = 0.77  # even a confident K=3 value must not leak
        fv = FeatureFactory.compute(bars, "SPY", "1m", cache, config)
        assert fv.hmm_regime_prob is None

    def test_hmm_entropy_never_leaks_cache_value(self) -> None:
        """FeatureVector.hmm_entropy must always be None -- see
        test_hmm_regime_prob_never_leaks_cache_value for full rationale.
        Replaces test_hmm_entropy_from_cache."""
        bars = _make_bars(60)
        config = _make_config()
        cache = _make_cache()
        cache.hmm_entropy = 0.33
        fv = FeatureFactory.compute(bars, "SPY", "1m", cache, config)
        assert fv.hmm_entropy is None

    def test_hmm_duration_never_leaks_cache_value(self) -> None:
        """FeatureVector.hmm_duration must always be None -- see
        test_hmm_regime_prob_never_leaks_cache_value for full rationale.
        No prior test covered hmm_duration specifically; added for parity."""
        bars = _make_bars(60)
        config = _make_config()
        cache = _make_cache()
        cache.hmm_duration = 12.0
        fv = FeatureFactory.compute(bars, "SPY", "1m", cache, config)
        assert fv.hmm_duration is None

    def test_hmm_fields_never_leak_cache_value_on_cold_start(self) -> None:
        """compute()'s cold-start path (<2 bars, _cold_start_vector) is a
        separate code path from the main body above -- must not leak either.
        """
        config = _make_config()
        cache = _make_cache()
        cache.hmm_regime_prob = 0.91
        cache.hmm_entropy = 0.05
        cache.hmm_duration = 30.0
        fv = FeatureFactory.compute([_make_bars(1)[0]], "SPY", "1m", cache, config)
        assert fv.hmm_regime_prob is None
        assert fv.hmm_entropy is None
        assert fv.hmm_duration is None

    def test_hmm_fields_never_leak_cache_value_in_compute_batch(self) -> None:
        """compute_batch()'s per-bar loop is a third, independently-wired code
        path from compute()'s main body and cold-start branch -- must not leak
        either. Uses test_compute_batch_parity's pattern (fresh FeatureCache,
        real bar series) rather than a hand-set cache value, since
        compute_batch() manages its own cache.refresh_regime() lifecycle
        internally instead of accepting a pre-seeded cache field."""
        bars = _make_bars(120)
        config = _make_config()
        cache = _make_cache()
        batch_results = FeatureFactory.compute_batch(bars, "SPY", "5m", cache, config)
        assert batch_results, "compute_batch() returned no rows"
        for _, fv in batch_results:
            assert fv.hmm_regime_prob is None
            assert fv.hmm_entropy is None
            assert fv.hmm_duration is None

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
        """No accidental look-ahead in feature_factory.py (todo 086).

        The original check grepped for the literal words "smooth"/"smoothed",
        which false-positives on legitimately causal code: Phase 142.5's
        Parkinson/Garman-Klass volatility estimators use a trailing rolling
        mean (_rolling_mean_series) and call it "smoothed" in their own
        docstrings without being acausal in any way (backward-looking in
        *value* terms, i.e. noise-reduced via past-only averaging, is not the
        same thing as *look-ahead*). Checking for "backward" alone is a
        stronger signal -- production code has no legitimate reason to
        describe itself as backward/look-ahead -- with one deliberate,
        documented exception: _canary_acausal_placebo(), a positive-control
        canary whose entire purpose is to prove the IC significance gate
        detects real contamination when genuinely present (see its own
        docstring). That function's body is stripped structurally before
        scanning, not carved out by line number, so this stays correct as
        the file grows around it.
        """
        factory_path = Path("/home/bg/dev/indicagent/src/intelligence/feature_factory.py")
        source = factory_path.read_text()

        source_without_canary, n_stripped = _source_without_acausal_canary(source)
        assert n_stripped == 1, (
            "_canary_acausal_placebo() not found where expected -- this test's "
            "structural exclusion depends on it existing; update the test if the "
            "canary was renamed or removed."
        )

        assert "backward" not in source_without_canary.lower(), (
            "Backward/look-ahead reference found in feature_factory.py outside "
            "the documented _canary_acausal_placebo() positive control — forward "
            "only permitted"
        )


class TestAcausalCanaryExclusionCheck:
    """todo 086: the exclusion logic backing test_no_smooth_or_backward_in_factory
    must both stay silent on the documented canary AND still catch a real
    violation -- otherwise "tightening the check" could silently regress into a
    vacuous check that never fails. No live FeatureFactory computation here,
    pure string-processing coverage of the check's own logic.
    """

    def test_causal_smoothing_docstring_does_not_trip_the_word_check(self) -> None:
        source = (
            "def _parkinson_vol_z_series_full(...):\n"
            '    """z-score of the rolling-averaged Parkinson variance proxy.\n'
            "    `window` smooths the per-bar term via a rolling mean;\n"
            '    normalizes the smoothed series against its own trailing history."""\n'
            "    smoothed = _rolling_mean_series(terms, window)\n"
            "    return smoothed\n"
        )
        stripped, _ = _source_without_acausal_canary(source)
        assert "backward" not in stripped.lower()

    def test_canary_own_backward_reference_is_excluded(self) -> None:
        source = (
            "\ndef _canary_acausal_placebo(closes, i, eps=1e-10):\n"
            '    """Deliberate look-ahead leak (positive control): pairs bar i\n'
            "    with the return realized 2 bars in the future, forward-shifted\n"
            '    instead of backward-shifted."""\n'
            "    return closes[i + 2]\n"
            "\n\ndef _next_real_function(x):\n"
            "    return x\n"
        )
        stripped, n_stripped = _source_without_acausal_canary(source)
        assert n_stripped == 1
        assert "backward" not in stripped.lower()
        assert "_next_real_function" in stripped, "must not over-strip past the canary's own body"

    def test_a_genuine_new_violation_elsewhere_is_still_caught(self) -> None:
        """The actual regression this check exists to prevent: a NEW function,
        unrelated to the documented canary, that describes itself as
        backward-looking. Must NOT be silently excluded."""
        source = (
            "\ndef _canary_acausal_placebo(closes, i):\n"
            '    """forward-shifted instead of backward-shifted."""\n'
            "    return closes[i + 2]\n"
            "\n\ndef _new_totally_unrelated_feature(closes, i):\n"
            '    """Oops -- this one actually reads a backward-shifted future bar."""\n'
            "    return closes[i + 1]\n"
        )
        stripped, n_stripped = _source_without_acausal_canary(source)
        assert n_stripped == 1
        assert "backward" in stripped.lower(), (
            "a genuine new acausal reference outside the canary must still be "
            "detectable -- the exclusion must not over-strip"
        )

    def test_refresh_regime_updates_cache(self) -> None:
        """FeatureCache.refresh_regime updates its still-live regime fields
        (hurst/shannon/garch_ratio/hma_slope_z/adx) in cache.

        hmm_regime_prob/hmm_entropy/hmm_duration are deliberately excluded
        from this assertion -- removed from refresh_regime() 2026-07-30
        (todo 207) as dead compute (zero live consumer once FeatureFactory
        stopped echoing them into FeatureVector; regime_writer.py's fitted
        K=5 HMM is the sole writer of those 3 columns). They now stay
        permanently at their dataclass defaults; see refresh_regime()'s
        comment for the full removal rationale.
        """
        bars = _make_bars(100)
        config = _make_config()
        cache = FeatureCache()
        # Initially default values
        assert cache.hurst == 0.5
        assert cache.hmm_regime_prob == 0.0
        cache.refresh_regime(bars, config)
        # hurst/shannon/garch_ratio/hma_slope_z/adx should be set (finite)
        assert math.isfinite(cache.hurst)
        assert math.isfinite(cache.shannon)
        assert math.isfinite(cache.garch_ratio)
        assert math.isfinite(cache.hma_slope_z)
        assert math.isfinite(cache.adx)
        # hmm_regime_prob must NOT be touched by refresh_regime() anymore --
        # stays at its dataclass default.
        assert cache.hmm_regime_prob == 0.0
        # bars_since_regime_refresh should be reset to 0
        assert cache.bars_since_regime_refresh == 0


class TestSessionPrimitives:
    def test_session_poc_dist_from_cache(self) -> None:
        """Session poc_dist_atr is derived from FeatureCache's raw _sess_poc + atr_val.

        Phase 163 Plan 02: poc_dist_atr is no longer a flat FeatureCache attribute
        set externally -- it's derived inside compute() as
        (close - cache._sess_poc) / atr_val (see _derive_session_vp). Setting
        _sess_poc == the last bar's close makes the expected result exactly 0.0
        regardless of atr_val, avoiding the need to reproduce the internal ATR
        computation in this test.
        """
        bars = _make_bars(60)
        config = _make_config()
        cache = _make_cache()
        cache._sess_poc = bars[-1]["close"]
        fv = FeatureFactory.compute(bars, "SPY", "1m", cache, config)
        assert math.isclose(fv.poc_dist_atr, 0.0, abs_tol=1e-9)

    def test_session_va_position_from_cache(self) -> None:
        """va_position is derived from FeatureCache's raw _sess_val/_sess_vah (no ATR).

        Phase 163 Plan 02: va_position = clamp((close - _sess_val) / (_sess_vah -
        _sess_val), 0, 1) -- independent of atr_val, so the expected value can be
        computed exactly from the raw session levels and the last bar's close.
        """
        bars = _make_bars(60)
        config = _make_config()
        cache = _make_cache()
        close = bars[-1]["close"]
        cache._sess_val = close - 2.0
        cache._sess_vah = close + 6.0
        fv = FeatureFactory.compute(bars, "SPY", "1m", cache, config)
        expected = (close - cache._sess_val) / (cache._sess_vah - cache._sess_val)
        assert math.isclose(fv.va_position, expected, abs_tol=1e-9)

    def test_sr_computed_from_ohlcv_not_cache(self) -> None:
        """S/R (Phase 163 Plan 03) is computed inline from OHLCV pivot-clustering,
        not read from a flat FeatureCache attribute set externally. Setting
        cache.sr_support_dist/sr_resist_dist to stub values must have NO effect
        on the result -- compute() must produce identical output regardless.
        """
        bars = _make_bars(60)
        config = _make_config()

        cache_stub = _make_cache()
        cache_stub.sr_support_dist = 1.2
        cache_stub.sr_resist_dist = 9.9
        fv_with_stub = FeatureFactory.compute(bars, "SPY", "1m", cache_stub, config)

        cache_clean = _make_cache()
        fv_clean = FeatureFactory.compute(bars, "SPY", "1m", cache_clean, config)

        assert math.isfinite(fv_with_stub.sr_support_dist)
        assert math.isfinite(fv_with_stub.sr_resist_dist)
        assert math.isclose(fv_with_stub.sr_support_dist, fv_clean.sr_support_dist, abs_tol=1e-9)
        assert math.isclose(fv_with_stub.sr_resist_dist, fv_clean.sr_resist_dist, abs_tol=1e-9)

    def test_1d_tf_vp_features_are_defaults(self) -> None:
        """For tf='1d', VP session-level features must be zero/0.5 (a single
        daily bar has no intraday distribution). S/R is NOT forced to neutral
        for tf='1d' (Phase 163 Plan 03) -- pivot-clustering over daily bars is
        valid, so it is exercised by the S/R regression suite instead.
        """
        bars = _make_bars(60)
        config = _make_config()
        cache = _make_cache()
        # Set cache values to non-default to confirm 1d override
        cache.poc_dist_atr = 2.0
        cache.va_position = 0.8
        fv = FeatureFactory.compute(bars, "SPY", "1d", cache, config)
        assert fv.poc_dist_atr == 0.0
        assert fv.va_position == 0.5

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
        + 8 Plan 04 + 8 Plan 05.5 Renaissance primitives = 150 (2 of the
        original 91 later removed as redundant, migration 211) + 5 canary/
        control predictors (Phase 143.1 Plan 02, todo 068) = 155, + 17
        structural VP/SR fields (Phase 163 Plan 01, migration 255) = 172,
        + 36 SMC institutional-footprint fields (Phase 164 Plan 01,
        migration 266) = 208, + 41 swing/fib/trend/session structure fields
        (Phase 165 Plan 01, migration 267) = 249 (final total). See
        142.5-05-SUMMARY.md / 142.5-03-SUMMARY.md / 142.5-04-SUMMARY.md
        Deviations for the actual dependency-DAG-valid merge order vs. the
        phase outline's originally assumed counts.
        """
        import dataclasses

        bars = _make_bars(100)
        config = _make_config()
        cache = FeatureCache()
        fv = FeatureFactory.compute(bars, "SPY", "1m", cache, config)
        fields = dataclasses.fields(fv)
        assert len(fields) == 292, f"Expected 292 fields, got {len(fields)}"
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
        tip_bars = _make_bars(60, seed=4)
        hyg_bars = _make_bars(60, seed=5)
        lqd_bars = _make_bars(60, seed=6)
        config = _make_config()
        cache = FeatureCache()
        cache.update_cross_asset(spy_bars, tlt_bars, shy_bars, tip_bars, hyg_bars, lqd_bars, config)
        assert math.isfinite(cache.vix_z)

    def test_update_cross_asset_populates_flight_quality(self) -> None:
        """flight_quality = TLT/SPY relative-return divergence."""
        spy_bars = _make_bars(60, seed=1)
        tlt_bars = _make_bars(60, seed=2)
        shy_bars = _make_bars(60, seed=3)
        tip_bars = _make_bars(60, seed=4)
        hyg_bars = _make_bars(60, seed=5)
        lqd_bars = _make_bars(60, seed=6)
        config = _make_config()
        cache = FeatureCache()
        cache.update_cross_asset(spy_bars, tlt_bars, shy_bars, tip_bars, hyg_bars, lqd_bars, config)
        assert math.isfinite(cache.flight_quality)

    def test_update_cross_asset_populates_yield_slope_z(self) -> None:
        """yield_slope_z = z-score of TLT/SHY return ratio."""
        spy_bars = _make_bars(60, seed=1)
        tlt_bars = _make_bars(60, seed=2)
        shy_bars = _make_bars(60, seed=3)
        tip_bars = _make_bars(60, seed=4)
        hyg_bars = _make_bars(60, seed=5)
        lqd_bars = _make_bars(60, seed=6)
        config = _make_config()
        cache = FeatureCache()
        cache.update_cross_asset(spy_bars, tlt_bars, shy_bars, tip_bars, hyg_bars, lqd_bars, config)
        assert math.isfinite(cache.yield_slope_z)

    def test_update_cross_asset_populates_tip_tlt_and_hyg_lqd(self) -> None:
        """Phase 151 Plan 04: tip_tlt_ret_z/hyg_lqd_ret_z must be finite once enough
        bars have accumulated, and 0.0 with fewer than 2 bars (cold start)."""
        spy_bars = _make_bars(60, seed=1)
        tlt_bars = _make_bars(60, seed=2)
        shy_bars = _make_bars(60, seed=3)
        tip_bars = _make_bars(60, seed=4)
        hyg_bars = _make_bars(60, seed=5)
        lqd_bars = _make_bars(60, seed=6)
        config = _make_config()
        cache = FeatureCache()
        cache.update_cross_asset(
            spy_bars[:1],
            tlt_bars[:1],
            shy_bars[:1],
            tip_bars[:1],
            hyg_bars[:1],
            lqd_bars[:1],
            config,
        )
        assert cache.tip_tlt_ret_z == 0.0
        assert cache.hyg_lqd_ret_z == 0.0

        cache.update_cross_asset(spy_bars, tlt_bars, shy_bars, tip_bars, hyg_bars, lqd_bars, config)
        assert math.isfinite(cache.tip_tlt_ret_z)
        assert math.isfinite(cache.hyg_lqd_ret_z)

    def test_sb_corr_fast_bounded_and_extremes(self) -> None:
        """sb_corr_fast must be within [-1, 1], and hit +1.0/-1.0 for perfectly
        co-moving / perfectly opposed synthetic SPY/TLT series.

        update_cross_asset() appends only the LAST bar's return per call (matching
        the live incremental-append semantics of vix_z/yield_slope_z above) -- a
        rolling window needs sb_corr_window_fast INCREMENTAL calls to populate the
        deque, not one call over the full bar list. Mirrors
        TestBuildCrossAssetSeries's incremental-slice pattern below.
        """
        config = _make_config()

        spy_bars = _make_bars(60, seed=1)
        # Perfectly co-moving: TLT close = k * SPY close (pure scalar multiple) ->
        # log returns are IDENTICAL (log(k*a/k*b) == log(a/b)), so correlation is
        # exactly 1.0 -- an additive/affine shift would NOT give exact log-return
        # correlation (log is not linear under addition).
        co_moving_tlt_bars = [{**b, "close": 0.5 * b["close"]} for b in spy_bars]
        shy_bars = _make_bars(60, seed=3)
        tip_bars = _make_bars(60, seed=4)
        hyg_bars = _make_bars(60, seed=5)
        lqd_bars = _make_bars(60, seed=6)

        cache = FeatureCache()
        for i in range(2, len(spy_bars) + 1):
            cache.update_cross_asset(
                spy_bars[:i],
                co_moving_tlt_bars[:i],
                shy_bars[:i],
                tip_bars[:i],
                hyg_bars[:i],
                lqd_bars[:i],
                config,
            )
        assert -1.0 <= cache.sb_corr_fast <= 1.0
        assert cache.sb_corr_fast == pytest.approx(1.0, abs=1e-6)

        # Perfectly opposed: TLT close = C / SPY close (pure inverse) -> log
        # returns are exact negatives (log(C/a / (C/b)) == -log(a/b)), so
        # correlation is exactly -1.0.
        opposed_tlt_bars = [{**b, "close": 10000.0 / b["close"]} for b in spy_bars]
        cache2 = FeatureCache()
        for i in range(2, len(spy_bars) + 1):
            cache2.update_cross_asset(
                spy_bars[:i],
                opposed_tlt_bars[:i],
                shy_bars[:i],
                tip_bars[:i],
                hyg_bars[:i],
                lqd_bars[:i],
                config,
            )
        assert cache2.sb_corr_fast == pytest.approx(-1.0, abs=1e-6)

    def test_cross_asset_state_matches_feature_cache(self) -> None:
        """CrossAssetState.update_cross_asset() (todo 222) must produce byte-identical
        vix_z/flight_quality/yield_slope_z to FeatureCache.update_cross_asset() given the
        same inputs -- both delegate to the same _compute_cross_asset(), so this is the
        regression guard against that shared implementation ever diverging again.

        CrossAssetState is deliberately NOT extended with Plan 04's 5 new fields (see
        that class's docstring) -- its own update_cross_asset() keeps the original
        3-bar-list signature, only FeatureCache's signature grew to 6 bar lists.
        """
        spy_bars = _make_bars(60, seed=1)
        tlt_bars = _make_bars(60, seed=2)
        shy_bars = _make_bars(60, seed=3)
        tip_bars = _make_bars(60, seed=4)
        hyg_bars = _make_bars(60, seed=5)
        lqd_bars = _make_bars(60, seed=6)
        config = _make_config()

        cache = FeatureCache()
        cache.update_cross_asset(spy_bars, tlt_bars, shy_bars, tip_bars, hyg_bars, lqd_bars, config)

        state = CrossAssetState()
        state.update_cross_asset(spy_bars, tlt_bars, shy_bars, config)

        assert state.vix_z == cache.vix_z
        assert state.flight_quality == cache.flight_quality
        assert state.yield_slope_z == cache.yield_slope_z

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
# FeatureVector fields at end of phase; reduced to 89/150 2026-07-09 after
# new_high_flag/new_low_flag were found redundant with dist_from_high/
# dist_from_low and removed, migration 211). DO NOT implement primitives
# here — these tests must fail RED (AttributeError: FeatureVector has no
# field X) until Plans 01/02/03/04/05/05.5 add the fields. See:
#   .planning/phases/142.5-renaissance-primitives/142.5-PLAN-OUTLINE.md
#   docs/research/signal-renaissance-primitives-ohlcv.md
# ---------------------------------------------------------------------------

# Canonical list of all 89 new field names, grouped by category in plan order.
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
    # Breakout Distance (12)
    "dist_from_high_fast",
    "dist_from_high_slow",
    "dist_from_low_fast",
    "dist_from_low_slow",
    "range_pct_fast",
    "range_pct_slow",
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
    len(RENAISSANCE_PRIMITIVE_FIELDS) == 89
), f"Expected 89 Renaissance primitive field names, got {len(RENAISSANCE_PRIMITIVE_FIELDS)}"


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
    # stoch_k_fast/slow: (C - L_N) / (H_N - L_N), bounded [0, 1].
    assert 0.0 <= fv.stoch_k_fast <= 1.0
    assert 0.0 <= fv.stoch_k_slow <= 1.0
    # price_percentile_fast/slow: rolling percentile rank, bounded [0, 1].
    assert 0.0 <= fv.price_percentile_fast <= 1.0
    assert 0.0 <= fv.price_percentile_slow <= 1.0
    # efficiency_ratio_fast/slow: Kaufman ER, bounded [0, 1] (0=chop, 1=trend).
    assert 0.0 <= fv.efficiency_ratio_fast <= 1.0
    assert 0.0 <= fv.efficiency_ratio_slow <= 1.0

    # Edge case: bar closing exactly at the rolling high must zero out
    # dist_from_high (close is at, not below, the rolling high).
    bars_new_high = _make_bars(100)
    rolling_high = max(b["high"] for b in bars_new_high[-21:-1])
    bars_new_high[-1]["high"] = rolling_high + 1.0
    bars_new_high[-1]["close"] = rolling_high + 1.0
    fv_high = FeatureFactory.compute(bars_new_high, "SPY", "1m", cache, config)
    assert fv_high.dist_from_high_fast == pytest.approx(0.0, abs=1e-9)


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


def test_price_volume_interaction_helpers_direct() -> None:
    """Direct unit coverage of the price-volume-interaction helper functions
    (exact products/ratios + epsilon-guard edge cases), independent of the
    FeatureFactory.compute() integration test above.
    """
    from src.intelligence.feature_factory import (
        _price_vol_corr_series_full,
        _product,
        _ret_vol_ratio,
        _up_vol_body_diff,
    )

    # Test 1-3, 6: _product returns a * b (pure product) -- shared by
    # vol_body_product, ret_vol_product_fast, range_vol_product, vol_skew_product.
    assert _product(0.4, 2.0) == pytest.approx(0.8)
    assert _product(0.02, -1.5) == pytest.approx(-0.03)
    assert _product(1.2, 0.5) == pytest.approx(0.6)
    assert _product(-0.3, 1.1) == pytest.approx(-0.33)
    # Test 4: _up_vol_body_diff returns up_vol_ratio - body_ratio, bounded ~[-1, 1].
    assert _up_vol_body_diff(0.7, 0.4) == pytest.approx(0.3)
    assert _up_vol_body_diff(0.0, 1.0) == pytest.approx(-1.0)
    # Test 5: _ret_vol_ratio returns ret_lag / atr_z; 0.0 when abs(atr_z) < eps.
    assert _ret_vol_ratio(0.04, 2.0) == pytest.approx(0.02)
    assert _ret_vol_ratio(0.04, 0.0) == 0.0
    assert _ret_vol_ratio(0.04, 1e-12) == 0.0

    # Test 7/8: _price_vol_corr_series_full's last element — bounded [-1, 1]
    # on warm input; 0.0 on insufficient history and on degenerate (constant
    # volume / constant returns) input. (No standalone scalar wrapper exists
    # for this primitive — compute()/compute_batch() both read this same
    # vectorized series directly, so testing its last element IS testing the
    # production code path, not a parallel reimplementation of it.)
    rng = np.random.default_rng(7)
    closes = np.cumprod(1.0 + rng.normal(0, 0.01, 60)) * 100.0
    volumes = rng.uniform(1e5, 1e6, 60)
    corr = _price_vol_corr_series_full(closes, volumes, window=20)[-1]
    assert -1.0 <= corr <= 1.0
    # Insufficient history: fewer bars than window.
    assert _price_vol_corr_series_full(closes[:10], volumes[:10], window=20)[-1] == 0.0
    # Degenerate: constant volume (zero variance).
    const_volumes = np.full(60, 5e5)
    assert _price_vol_corr_series_full(closes, const_volumes, window=20)[-1] == 0.0
    # Degenerate: constant price (zero return variance).
    const_closes = np.full(60, 100.0)
    assert _price_vol_corr_series_full(const_closes, volumes, window=20)[-1] == 0.0


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


class TestIsValidAtr:
    """todo 237: _is_valid_atr is the shared guard for every ATR-normalized distance
    feature in this module (session VP, S/R, swing/trend structure, fibonacci zones,
    session levels, and all 6 SMC compute functions). A bare `atr_val > 0` check lets a
    legitimately-positive but numerically-tiny ATR through, and `(level - close_) /
    atr_val` then explodes -- confirmed live: weekly_r1_dist_atr up to 96,512 during a
    genuinely flat BIL period. min_atr_pct floors atr_val as a fraction of close_."""

    def test_none_is_invalid(self) -> None:
        assert _is_valid_atr(None, 100.0, 0.0001) is False

    def test_non_finite_is_invalid(self) -> None:
        assert _is_valid_atr(float("nan"), 100.0, 0.0001) is False
        assert _is_valid_atr(float("inf"), 100.0, 0.0001) is False

    def test_zero_or_negative_is_invalid(self) -> None:
        assert _is_valid_atr(0.0, 100.0, 0.0001) is False
        assert _is_valid_atr(-1.0, 100.0, 0.0001) is False

    def test_ordinary_atr_is_valid(self) -> None:
        """A typical ATR (well above the floor relative to close_) passes."""
        assert _is_valid_atr(1.0, 100.0, 0.0001) is True

    def test_tiny_but_positive_atr_below_floor_is_now_invalid(self) -> None:
        """The BIL-style regression case: atr_val > 0 but far below min_atr_pct of
        close_ -- the exact case a bare `atr_val > 0` check let through pre-fix."""
        close_ = 91.70
        atr_val = 0.0001  # ~0.0001% of close_, far below the 0.01% (1bp) default floor
        assert _is_valid_atr(atr_val, close_, 0.0001) is False

    def test_boundary_at_exactly_the_floor_is_valid(self) -> None:
        close_ = 100.0
        min_atr_pct = 0.0001
        atr_val = min_atr_pct * close_  # exactly at the floor
        assert _is_valid_atr(atr_val, close_, min_atr_pct) is True

    def test_just_below_the_floor_is_invalid(self) -> None:
        close_ = 100.0
        min_atr_pct = 0.0001
        atr_val = min_atr_pct * close_ - 1e-9
        assert _is_valid_atr(atr_val, close_, min_atr_pct) is False

    def test_floor_disabled_via_config_zero_matches_pre_fix_behavior(self) -> None:
        """min_atr_pct=0.0 recovers the old bare `atr_val > 0` behavior exactly --
        proves the floor is additive, not a change to the pre-existing >0 gate."""
        assert _is_valid_atr(1e-12, 91.70, 0.0) is True

    def test_default_config_min_atr_pct_matches_migration_294_seed(self) -> None:
        assert FeatureFactoryConfig.__dataclass_fields__[
            "atr_normalization_min_pct"
        ].default == pytest.approx(0.0001)


class TestInformedFlowRangeVsAtrFloor:
    """todo 266: _informed_flow/_range_vs_atr routed through the same _is_valid_atr
    relative floor todo 237 applied to the other 12 ATR-ratio features -- replaces
    their own inline `atr > 1e-10` absolute epsilon, which let a BIL-style
    tiny-but-positive ATR through uncaught when it was still far below
    min_atr_pct of close_."""

    def test_informed_flow_ordinary_atr_computes_ratio(self) -> None:
        assert _informed_flow(99.0, 100.0, 2.0, 0.0001) == pytest.approx(0.5)

    def test_informed_flow_tiny_atr_below_floor_returns_zero(self) -> None:
        """The BIL-style regression case: atr_val > 1e-10 (old gate would have
        passed it) but far below min_atr_pct of close_."""
        close_ = 91.70
        atr_val = 0.0001  # ~0.0001% of close_, far below the 0.01% default floor
        assert _informed_flow(90.0, close_, atr_val, 0.0001) == 0.0

    def test_informed_flow_floor_disabled_allows_sub_eps_atr(self) -> None:
        """min_atr_pct=0.0 relaxes the gate to a bare atr_val > 0 check, same
        additive-floor semantics as _is_valid_atr's own floor-disabled test."""
        assert _informed_flow(90.0, 91.70, 1e-12, 0.0) != 0.0

    def test_range_vs_atr_ordinary_atr_computes_ratio(self) -> None:
        assert _range_vs_atr(102.0, 98.0, 2.0, 100.0, 0.0001) == pytest.approx(2.0)

    def test_range_vs_atr_tiny_atr_below_floor_returns_zero(self) -> None:
        close_ = 91.70
        atr_val = 0.0001
        assert _range_vs_atr(92.0, 91.0, atr_val, close_, 0.0001) == 0.0

    def test_range_vs_atr_floor_disabled_allows_sub_eps_atr(self) -> None:
        assert _range_vs_atr(92.0, 91.0, 1e-12, 91.70, 0.0) != 0.0


class TestIsValidAtrSeries:
    """todo 268: vectorized form of _is_valid_atr for the _series_full batch
    functions, which operate on a full atr_padded array rather than a per-bar
    scalar."""

    def test_matches_scalar_is_valid_atr_elementwise(self) -> None:
        atr_padded = np.array([0.0, 1.0, 0.0001, np.nan, -1.0, 0.05])
        closes = np.array([100.0, 100.0, 91.70, 100.0, 100.0, 100.0])
        min_atr_pct = 0.0001
        expected = np.array(
            [
                _is_valid_atr(float(a), float(c), min_atr_pct)
                for a, c in zip(atr_padded, closes, strict=True)
            ]
        )
        result = _is_valid_atr_series(atr_padded, closes, min_atr_pct)
        np.testing.assert_array_equal(result, expected)


class TestDistFromHighLowFloor:
    """todo 268: _dist_from_high_series_full/_dist_from_low_series_full routed
    through the vectorized ATR floor -- same BIL-style gap todo 266 fixed for
    _informed_flow/_range_vs_atr, but on the vectorized batch path that backs
    dist_from_high_fast/slow and dist_from_low_fast/slow."""

    def test_dist_from_high_tiny_atr_below_floor_returns_zero(self) -> None:
        closes = np.array([91.0, 91.5, 91.70])
        highs = np.array([91.2, 91.8, 92.0])
        atr_padded = np.array([1.0, 1.0, 0.0001])  # last bar far below floor
        atr_valid = _is_valid_atr_series(atr_padded, closes, 0.0001)
        result = _dist_from_high_series_full(closes, highs, atr_padded, atr_valid, window=3)
        assert result[-1] == 0.0

    def test_dist_from_high_ordinary_atr_computes_ratio(self) -> None:
        closes = np.array([91.0, 91.5, 98.0])
        highs = np.array([91.2, 91.8, 100.0])
        atr_padded = np.array([1.0, 1.0, 2.0])
        atr_valid = _is_valid_atr_series(atr_padded, closes, 0.0001)
        result = _dist_from_high_series_full(closes, highs, atr_padded, atr_valid, window=3)
        assert result[-1] == pytest.approx((100.0 - 98.0) / 2.0)

    def test_dist_from_low_tiny_atr_below_floor_returns_zero(self) -> None:
        closes = np.array([91.0, 91.5, 91.70])
        lows = np.array([90.8, 91.2, 91.0])
        atr_padded = np.array([1.0, 1.0, 0.0001])
        atr_valid = _is_valid_atr_series(atr_padded, closes, 0.0001)
        result = _dist_from_low_series_full(closes, lows, atr_padded, atr_valid, window=3)
        assert result[-1] == 0.0

    def test_dist_from_low_ordinary_atr_computes_ratio(self) -> None:
        closes = np.array([91.0, 91.5, 98.0])
        lows = np.array([90.8, 91.2, 90.0])
        atr_padded = np.array([1.0, 1.0, 2.0])
        atr_valid = _is_valid_atr_series(atr_padded, closes, 0.0001)
        result = _dist_from_low_series_full(closes, lows, atr_padded, atr_valid, window=3)
        assert result[-1] == pytest.approx((98.0 - 90.0) / 2.0)
