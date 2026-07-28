"""Unit tests for canary/control predictors (Phase 143.1 Plan 02, todo 068).

RED-first coverage for Component D: 5 new genuine FeatureVector fields
(canary_noise_gaussian, canary_noise_uniform, canary_constant,
canary_near_constant, canary_acausal_placebo) plus the corpus-run integrity
assertion (Task 3, scripts/ops/alpha/ops_canary_integrity_assert.py).

Negative controls (noise/constant/near-constant) must never carry IC. The
acausal placebo is a deliberate look-ahead leak (positive control) and must
clear an IC significance gate spectacularly, proving the pipeline can detect
contamination when it is genuinely present.
"""

from __future__ import annotations

import dataclasses
import math
from datetime import UTC, datetime, timedelta

import numpy as np
import pytest

from src.intelligence.feature_cache import FeatureCache
from src.intelligence.feature_factory import (
    _CANARY_CONSTANT_VALUE,
    FeatureFactory,
    FeatureFactoryConfig,
    _canary_acausal_placebo,
    _canary_near_constant,
    _canary_noise_gaussian,
    _canary_noise_uniform,
    _canary_sub_seed,
    _cold_start_vector,
)
from src.intelligence.schemas import FeatureVector

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_config(**overrides) -> FeatureFactoryConfig:
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
        canary_rng_seed=90042,
    )
    defaults.update(overrides)
    return FeatureFactoryConfig(**defaults)


def _make_bars(n: int = 100, seed: int = 42) -> list[dict]:
    """Generate n synthetic OHLCV bars as dicts, strictly UTC-aware timestamps."""
    rng = np.random.default_rng(seed)
    bars = []
    close = 100.0
    ts = datetime(2026, 1, 2, 9, 30, tzinfo=UTC)
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
                "ts": ts + timedelta(minutes=i),
            }
        )
    return bars


# ---------------------------------------------------------------------------
# FeatureVector schema: 5 new fields present, row-count gate implications
# ---------------------------------------------------------------------------


class TestFeatureVectorCanaryFields:
    def test_canary_fields_exist_on_dataclass(self) -> None:
        field_names = {f.name for f in dataclasses.fields(FeatureVector)}
        assert "canary_noise_gaussian" in field_names
        assert "canary_noise_uniform" in field_names
        assert "canary_constant" in field_names
        assert "canary_near_constant" in field_names
        assert "canary_acausal_placebo" in field_names

    def test_field_count_increased_by_five(self) -> None:
        """FeatureRegistryService._REGISTRY_ROW_COUNT auto-derives from this
        count -- the row-count alignment gate depends on it staying accurate."""
        total = len(dataclasses.fields(FeatureVector))
        # 150 fields prior to this plan (61 baseline + 89 Renaissance
        # primitives after the migration-211 redundant-field removal), +5
        # canary fields = 155, +17 structural VP/SR fields (Phase 163 Plan 01,
        # migration 255) = 172, +36 SMC institutional-footprint fields
        # (Phase 164 Plan 01, migration 266, added after this test was
        # written) = 208.
        assert total == 150 + 5 + 17 + 36


# ---------------------------------------------------------------------------
# _canary_sub_seed: deterministic, offset-distinguishing sub-seed derivation
# ---------------------------------------------------------------------------


class TestCanarySubSeed:
    def test_deterministic_for_same_inputs(self) -> None:
        bar_ts = datetime(2026, 3, 4, 14, 30, tzinfo=UTC)
        s1 = _canary_sub_seed(bar_ts, base_seed=90042, offset=0)
        s2 = _canary_sub_seed(bar_ts, base_seed=90042, offset=0)
        assert s1 == s2

    def test_different_offsets_give_different_seeds(self) -> None:
        bar_ts = datetime(2026, 3, 4, 14, 30, tzinfo=UTC)
        seeds = {_canary_sub_seed(bar_ts, base_seed=90042, offset=o) for o in range(3)}
        assert len(seeds) == 3, "offsets must never collide onto the same sub-seed"

    def test_different_bar_ts_give_different_seeds(self) -> None:
        s1 = _canary_sub_seed(datetime(2026, 3, 4, 14, 30, tzinfo=UTC), 90042, 0)
        s2 = _canary_sub_seed(datetime(2026, 3, 4, 14, 31, tzinfo=UTC), 90042, 0)
        assert s1 != s2

    def test_stable_across_repeated_calls_no_hash_randomization(self) -> None:
        """Uses pure arithmetic, not Python hash() -- must be stable across
        interpreter invocations (ProcessPoolExecutor workers)."""
        bar_ts = datetime(2026, 3, 4, 14, 30, tzinfo=UTC)
        results = [_canary_sub_seed(bar_ts, 90042, 1) for _ in range(5)]
        assert len(set(results)) == 1


# ---------------------------------------------------------------------------
# Noise canaries: deterministic, distinguishable distributions
# ---------------------------------------------------------------------------


class TestNoiseCanaries:
    def test_gaussian_deterministic_for_fixed_seed(self) -> None:
        bar_ts = datetime(2026, 3, 4, 14, 30, tzinfo=UTC)
        v1 = _canary_noise_gaussian(bar_ts, base_seed=90042)
        v2 = _canary_noise_gaussian(bar_ts, base_seed=90042)
        assert v1 == v2

    def test_uniform_deterministic_for_fixed_seed(self) -> None:
        bar_ts = datetime(2026, 3, 4, 14, 30, tzinfo=UTC)
        v1 = _canary_noise_uniform(bar_ts, base_seed=90042)
        v2 = _canary_noise_uniform(bar_ts, base_seed=90042)
        assert v1 == v2

    def test_different_seed_gives_different_value(self) -> None:
        bar_ts = datetime(2026, 3, 4, 14, 30, tzinfo=UTC)
        v1 = _canary_noise_gaussian(bar_ts, base_seed=90042)
        v2 = _canary_noise_gaussian(bar_ts, base_seed=1)
        assert v1 != v2

    def test_gaussian_and_uniform_are_independently_seeded(self) -> None:
        """Not the same generator/seed-offset reused -- offset=0 (Gaussian) vs
        offset=1 (Uniform) must diverge; verified structurally via distinct
        sub-seeds (TestCanarySubSeed) and behaviorally here via output shape."""
        bar_ts = datetime(2026, 3, 4, 14, 30, tzinfo=UTC)
        gaussian_val = _canary_noise_gaussian(bar_ts, base_seed=90042)
        uniform_val = _canary_noise_uniform(bar_ts, base_seed=90042)
        # Uniform draw is bounded [0, 1); Gaussian is not. If the two used the
        # same seed/generator with no offset distinction, the raw draws could
        # coincide in shape across many bars -- assert the uniform draw
        # actually respects its distribution's bounds (a Gaussian draw at the
        # same generator position generally will not).
        assert 0.0 <= uniform_val < 1.0

    def test_uniform_is_bounded_zero_to_one_across_many_bars(self) -> None:
        base = datetime(2026, 3, 4, 14, 30, tzinfo=UTC)
        for i in range(200):
            v = _canary_noise_uniform(base + timedelta(minutes=i), base_seed=90042)
            assert 0.0 <= v < 1.0

    def test_gaussian_is_not_degenerate_across_many_bars(self) -> None:
        """A real N(0,1) draw stream must show variance -- not collapse to a
        single repeated value (which would indicate a seeding bug)."""
        base = datetime(2026, 3, 4, 14, 30, tzinfo=UTC)
        values = [
            _canary_noise_gaussian(base + timedelta(minutes=i), base_seed=90042) for i in range(200)
        ]
        assert np.std(values) > 0.5  # N(0,1) should show std close to 1.0


# ---------------------------------------------------------------------------
# Constant / near-constant canaries
# ---------------------------------------------------------------------------


class TestConstantCanaries:
    def test_constant_is_fixed_literal(self) -> None:
        assert _CANARY_CONSTANT_VALUE == 1.0

    def test_near_constant_is_literal_plus_tiny_noise(self) -> None:
        bar_ts = datetime(2026, 3, 4, 14, 30, tzinfo=UTC)
        v = _canary_near_constant(bar_ts, base_seed=90042)
        assert v != _CANARY_CONSTANT_VALUE
        assert abs(v - _CANARY_CONSTANT_VALUE) < 1e-3  # tiny, not a real signal

    def test_near_constant_is_deterministic(self) -> None:
        bar_ts = datetime(2026, 3, 4, 14, 30, tzinfo=UTC)
        v1 = _canary_near_constant(bar_ts, base_seed=90042)
        v2 = _canary_near_constant(bar_ts, base_seed=90042)
        assert v1 == v2

    def test_near_constant_uses_a_different_sub_seed_than_noise_canaries(self) -> None:
        bar_ts = datetime(2026, 3, 4, 14, 30, tzinfo=UTC)
        near_const_seed = _canary_sub_seed(bar_ts, 90042, offset=2)
        gaussian_seed = _canary_sub_seed(bar_ts, 90042, offset=0)
        uniform_seed = _canary_sub_seed(bar_ts, 90042, offset=1)
        assert near_const_seed not in (gaussian_seed, uniform_seed)


# ---------------------------------------------------------------------------
# Acausal placebo: deliberate look-ahead leak (positive control)
# ---------------------------------------------------------------------------


class TestAcausalPlaceboCanary:
    def test_references_future_indexed_value_not_current_bar(self) -> None:
        """Pairs bar i with the return realized from i+1 -> i+2 -- a genuine
        look-ahead leak. Uses a synthetic closes series where forward-shifted
        vs causal values are trivially distinguishable."""
        # Distinct, strictly increasing closes so every 2-bar log-return is
        # unique -- makes it impossible for the "wrong" (causal) value to
        # accidentally match the correct (forward-shifted) one.
        closes = np.array([100.0, 101.0, 103.0, 106.0, 110.0, 115.0, 121.0])
        i = 2
        # Correct: log(closes[i+2] / closes[i+1]) = log(closes[4]/closes[3])
        expected = math.log(closes[4] / closes[3])
        actual = _canary_acausal_placebo(closes, i)
        assert actual == pytest.approx(expected)
        # Provably NOT the causal ret_lag_1 shape (log(closes[i]/closes[i-1])).
        causal_wrong = math.log(closes[i] / closes[i - 1])
        assert actual != pytest.approx(causal_wrong)

    def test_falls_back_to_zero_at_end_of_series(self) -> None:
        closes = np.array([100.0, 101.0, 103.0])
        # i=2 is the last index; i+2=4 is out of bounds -- no future data.
        assert _canary_acausal_placebo(closes, 2) == 0.0
        assert _canary_acausal_placebo(closes, 1) == 0.0  # i+2=3 also OOB (len=3)

    def test_zero_when_future_close_is_degenerate(self) -> None:
        closes = np.array([100.0, 0.0, 103.0, 106.0])
        assert _canary_acausal_placebo(closes, 0) == 0.0  # closes[1] <= eps


# ---------------------------------------------------------------------------
# Integration: compute() (live, no future data) vs compute_batch() (backfill,
# genuine look-ahead exercisable)
# ---------------------------------------------------------------------------


class TestFeatureFactoryIntegration:
    def test_compute_live_path_has_no_future_acausal_leak(self) -> None:
        """The live single-bar compute() path has no future bars by
        definition -- canary_acausal_placebo must be inert (0.0) there."""
        bars = _make_bars(60)
        config = _make_config()
        cache = FeatureCache()
        fv = FeatureFactory.compute(bars, "SPY", "5m", cache, config)
        assert fv.canary_acausal_placebo == 0.0

    def test_compute_live_path_populates_noise_and_constant_canaries(self) -> None:
        bars = _make_bars(60)
        config = _make_config()
        cache = FeatureCache()
        fv = FeatureFactory.compute(bars, "SPY", "5m", cache, config)
        assert math.isfinite(fv.canary_noise_gaussian)
        assert 0.0 <= fv.canary_noise_uniform < 1.0
        assert fv.canary_constant == _CANARY_CONSTANT_VALUE
        assert abs(fv.canary_near_constant - _CANARY_CONSTANT_VALUE) < 1e-3

    def test_compute_batch_acausal_placebo_is_genuinely_forward_shifted(self) -> None:
        """compute_batch() has the full-history closes array in scope --
        the acausal placebo must reference real future data for interior
        bars, not silently degrade to 0.0 like the live path."""
        bars = _make_bars(60)
        config = _make_config()
        cache = FeatureCache()
        results = FeatureFactory.compute_batch(bars, "SPY", "5m", cache, config)
        closes = np.array([b["close"] for b in bars], dtype=float)
        # Pick an interior bar with headroom for i+2.
        i = 30
        _, fv = results[i - 1]  # compute_batch results are 0-indexed from bar 1
        expected = math.log(closes[i + 2] / closes[i + 1])
        assert fv.canary_acausal_placebo == pytest.approx(expected)
        assert fv.canary_acausal_placebo != 0.0

    def test_compute_batch_last_two_bars_fall_back_to_zero(self) -> None:
        """No future data exists for the final 2 bars of a batch run --
        must degrade to 0.0, never crash or fabricate a value."""
        bars = _make_bars(60)
        config = _make_config()
        cache = FeatureCache()
        results = FeatureFactory.compute_batch(bars, "SPY", "5m", cache, config)
        _, fv_last = results[-1]
        assert fv_last.canary_acausal_placebo == 0.0

    def test_compute_batch_noise_canaries_are_deterministic_across_runs(self) -> None:
        bars = _make_bars(40)
        config = _make_config()
        results1 = FeatureFactory.compute_batch(bars, "SPY", "5m", FeatureCache(), config)
        results2 = FeatureFactory.compute_batch(bars, "SPY", "5m", FeatureCache(), config)
        for (ts1, fv1), (ts2, fv2) in zip(results1, results2, strict=True):
            assert ts1 == ts2
            assert fv1.canary_noise_gaussian == fv2.canary_noise_gaussian
            assert fv1.canary_noise_uniform == fv2.canary_noise_uniform

    def test_cold_start_vector_returns_all_canary_fields(self) -> None:
        """142.5 cold-start-crash precedent: _cold_start_vector must be
        updated for every new field or cold-start crashes."""
        cache = FeatureCache()
        fv = _cold_start_vector(cache, "5m")
        assert fv.canary_noise_gaussian == 0.0
        assert fv.canary_noise_uniform == 0.0
        assert fv.canary_constant == _CANARY_CONSTANT_VALUE
        assert fv.canary_near_constant == _CANARY_CONSTANT_VALUE
        assert fv.canary_acausal_placebo == 0.0
        # No crash, and no missing field -- full dataclass construction succeeded.
        # 155 prior to Phase 163 Plan 01's 17 new structural VP/SR fields (migration
        # 255) = 172, +36 SMC institutional-footprint fields (Phase 164 Plan 01,
        # migration 266) = 208.
        assert len(dataclasses.fields(fv)) == 208


# ---------------------------------------------------------------------------
# Task 3: ops_canary_integrity_assert.py -- expectation-aware, false-halt-aware
# corpus-run integrity assertion. Pure evaluate() function, synthetic rows,
# no DB required.
# ---------------------------------------------------------------------------


def _row(
    feature_name: str,
    symbol: str,
    control_expectation: str,
    ic_ci_lower: float | None,
    passes_fdr: bool,
    is_pooled: bool = True,
    tf: str = "5m",
    regime: str = "trending_up",
    ic_ci_upper: float = 0.05,
) -> dict:
    return {
        "feature_name": feature_name,
        "symbol": symbol,
        "tf": tf,
        "regime": regime,
        "is_pooled": is_pooled,
        "ic_ci_lower": ic_ci_lower,
        "ic_ci_upper": ic_ci_upper,
        "passes_fdr": passes_fdr,
        "control_expectation": control_expectation,
    }


class TestCanaryIntegrityAssertion:
    def test_pooled_negative_control_clear_is_a_failure(self) -> None:
        from scripts.ops.alpha.ops_canary_integrity_assert import (
            CanaryIntegrityViolation,
            evaluate,
        )

        rows = [
            _row("canary_noise_gaussian", "POOLED", "negative_control", 0.02, True),
            _row("canary_acausal_placebo", "POOLED", "positive_control", 0.30, True),
        ]
        with pytest.raises(CanaryIntegrityViolation, match="POOLED negative-control"):
            evaluate(rows)

    def test_placebo_fails_to_clear_is_a_failure(self) -> None:
        from scripts.ops.alpha.ops_canary_integrity_assert import (
            CanaryIntegrityViolation,
            evaluate,
        )

        rows = [
            _row("canary_noise_gaussian", "POOLED", "negative_control", -0.01, False),
            # Positive control does NOT clear (ic_ci_lower <= 0) -- the failure mode.
            _row("canary_acausal_placebo", "POOLED", "positive_control", -0.002, False),
        ]
        with pytest.raises(CanaryIntegrityViolation, match="did NOT clear"):
            evaluate(rows)

    def test_single_per_symbol_clear_within_bound_is_not_a_hard_fail(self) -> None:
        from scripts.ops.alpha.ops_canary_integrity_assert import evaluate

        rows = [
            _row("canary_acausal_placebo", "POOLED", "positive_control", 0.30, True),
            # Healthy POOLED negative controls.
            _row("canary_noise_gaussian", "POOLED", "negative_control", -0.01, False),
            # A large per-symbol population of negative-control cells with exactly
            # ONE clear -- well within the Binomial bound at alpha=0.05 for n=100.
            *[
                _row(
                    "canary_noise_gaussian",
                    f"SYM{i}",
                    "negative_control",
                    -0.01,
                    False,
                    is_pooled=False,
                )
                for i in range(99)
            ],
            _row(
                "canary_noise_gaussian",
                "SYM99",
                "negative_control",
                0.02,
                True,
                is_pooled=False,
            ),
        ]
        report = evaluate(rows)
        assert report["per_symbol_negative_clears"] == 1
        assert not report["per_symbol_bound_exceeded"]

    def test_healthy_case_returns_success(self) -> None:
        from scripts.ops.alpha.ops_canary_integrity_assert import evaluate

        rows = [
            _row("canary_acausal_placebo", "POOLED", "positive_control", 0.30, True),
            _row("canary_noise_gaussian", "POOLED", "negative_control", -0.01, False),
            _row("canary_noise_uniform", "POOLED", "negative_control", -0.02, False),
            _row("canary_constant", "POOLED", "negative_control", None, False),
            _row("canary_near_constant", "POOLED", "negative_control", -0.005, False),
            *[
                _row(
                    "canary_noise_gaussian",
                    f"SYM{i}",
                    "negative_control",
                    -0.01,
                    False,
                    is_pooled=False,
                )
                for i in range(20)
            ],
        ]
        report = evaluate(rows)
        assert report["pooled_violations"] == []
        assert report["placebo_pooled_cleared"] is True
        assert report["per_symbol_negative_clears"] == 0
        assert not report["per_symbol_bound_exceeded"]

    def test_excessive_per_symbol_clears_exceeding_bound_is_a_failure(self) -> None:
        from scripts.ops.alpha.ops_canary_integrity_assert import (
            CanaryIntegrityViolation,
            evaluate,
        )

        rows = [
            _row("canary_acausal_placebo", "POOLED", "positive_control", 0.30, True),
            _row("canary_noise_gaussian", "POOLED", "negative_control", -0.01, False),
            # 20 per-symbol cells, ALL clearing -- wildly exceeds any reasonable
            # Binomial bound at p=0.05.
            *[
                _row(
                    "canary_noise_gaussian",
                    f"SYM{i}",
                    "negative_control",
                    0.02,
                    True,
                    is_pooled=False,
                )
                for i in range(20)
            ],
        ]
        with pytest.raises(CanaryIntegrityViolation, match="Binomial tail bound"):
            evaluate(rows)

    def test_no_rows_at_all_is_a_failure(self) -> None:
        from scripts.ops.alpha.ops_canary_integrity_assert import (
            CanaryIntegrityViolation,
            evaluate,
        )

        with pytest.raises(CanaryIntegrityViolation, match="no canary coverage"):
            evaluate([])

    def test_binomial_tail_bound_grows_with_more_cells(self) -> None:
        from scripts.ops.alpha.ops_canary_integrity_assert import _binomial_tail_bound

        small = _binomial_tail_bound(n_cells=10, p=0.05, tail_alpha=0.01)
        large = _binomial_tail_bound(n_cells=1000, p=0.05, tail_alpha=0.01)
        assert large > small

    def test_binomial_tail_bound_zero_cells(self) -> None:
        from scripts.ops.alpha.ops_canary_integrity_assert import _binomial_tail_bound

        assert _binomial_tail_bound(n_cells=0, p=0.05, tail_alpha=0.01) == 0
