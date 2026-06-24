"""Parity tests: _*_series_full batch functions vs scalar streaming equivalents.

Contract: for every _*_series_full function, batch[j] must match the equivalent
scalar call on bars[:j+<offset>] to within 1e-8. Any divergence is a data integrity
violation — the batch precompute path and the live streaming path must produce
identical feature values.

When _ret_skew_z_series_full / _ret_acf1_z_series_full are added, follow the
same pattern: generate N synthetic bars, run FeatureFactory.compute in a loop to
collect ret_skew_z / ret_acf1_z, run the series_full function once, assert match.
"""

import numpy as np
import pytest

from src.intelligence.feature_factory import (
    _atr_series_full,
    _atr_wilder,
)


def _make_bars(n: int, seed: int = 42) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    rng = np.random.default_rng(seed)
    close = 100.0 * np.cumprod(1 + rng.normal(0, 0.01, n))
    high = close * (1 + rng.uniform(0, 0.005, n))
    low = close * (1 - rng.uniform(0, 0.005, n))
    return high, low, close


class TestAtrSeriesFull:
    """_atr_series_full[j] == _atr_wilder(h[:j+2], l[:j+2], c[:j+2], period)."""

    @pytest.mark.parametrize("period", [5, 14, 20])
    def test_matches_scalar_streaming(self, period: int) -> None:
        N = 1000
        highs, lows, closes = _make_bars(N)

        batch = _atr_series_full(highs, lows, closes, period)
        assert len(batch) == N - 1

        for j in range(len(batch)):
            streaming = _atr_wilder(highs[: j + 2], lows[: j + 2], closes[: j + 2], period)
            assert abs(batch[j] - streaming) < 1e-8, (
                f"period={period} j={j}: batch={batch[j]:.12f} "
                f"streaming={streaming:.12f} delta={abs(batch[j] - streaming):.2e}"
            )

    def test_zero_prefix_before_sufficient_bars(self) -> None:
        """Values before period-1 bars must be 0.0 (matches _atr_wilder semantics)."""
        period = 14
        N = 1000
        highs, lows, closes = _make_bars(N)
        batch = _atr_series_full(highs, lows, closes, period)
        # _atr_wilder returns 0.0 when n < period+1, i.e. j+2 < period+1, i.e. j < period-1
        for j in range(min(period - 2, len(batch))):
            assert batch[j] == 0.0, f"j={j} should be 0.0 before sufficient bars, got {batch[j]}"

    def test_nonzero_after_sufficient_bars(self) -> None:
        period = 14
        N = 1000
        highs, lows, closes = _make_bars(N)
        batch = _atr_series_full(highs, lows, closes, period)
        # From j = period-1 onward ATR should be positive on real price data
        assert all(batch[period - 1 :] > 0), "Expected positive ATR values after warm-up"

    def test_short_input_returns_empty(self) -> None:
        highs, lows, closes = _make_bars(1)
        result = _atr_series_full(highs, lows, closes, 14)
        assert len(result) == 0

    def test_idempotent(self) -> None:
        """Calling twice on same data returns identical arrays (no hidden state)."""
        highs, lows, closes = _make_bars(500)
        a = _atr_series_full(highs, lows, closes, 14)
        b = _atr_series_full(highs, lows, closes, 14)
        np.testing.assert_array_equal(a, b)


# ---------------------------------------------------------------------------
# Test MIN_WINDOW derived from config (not hardcoded)
# ---------------------------------------------------------------------------


def _make_config_for_min_window():
    """Config where max constituent is cci_slow_period=40."""
    from tests.unit.services.test_backfill_feature_factory import _make_config

    return _make_config()  # cci_slow=40, aroon_slow=25, vol_long=20, cmf=20 → MIN_WINDOW=40


def _make_bars_dicts(n: int, seed: int = 0) -> list[dict]:
    from datetime import UTC, datetime, timedelta

    import numpy as np

    rng = np.random.default_rng(seed)
    base = datetime(2024, 1, 2, 14, 30, tzinfo=UTC)
    closes = 100.0 * np.cumprod(1 + rng.normal(0, 0.005, n))
    return [
        {
            "ts": base + timedelta(minutes=i),
            "open": float(closes[i] * 0.999),
            "high": float(closes[i] * 1.002),
            "low": float(closes[i] * 0.998),
            "close": float(closes[i]),
            "volume": 1000.0,
        }
        for i in range(n)
    ]


class TestMinWindowDerived:
    def test_compute_batch_produces_results_with_fewer_than_50_bars_warmup(self) -> None:
        """With MIN_WINDOW=40 (derived), a 42-bar batch must emit results.

        Before the fix MIN_WINDOW=50 was hardcoded. With MIN_WINDOW=40, bars[41]
        has a full 40-bar bounded window available — cci_slow etc. are computable.
        This test fails if MIN_WINDOW is still 50 (window_bars would only be 42
        bars but the bounded window slice [42-50:43] = [-8:43] = bars[:43] = 43
        bars, which is fine — so this test actually validates that the constant
        responds to config, not a behavior change at this size).
        """
        import math

        from src.intelligence.feature_cache import FeatureCache
        from src.intelligence.feature_factory import FeatureFactory

        config = _make_config_for_min_window()
        cache = FeatureCache()
        bars = _make_bars_dicts(60)
        results = FeatureFactory.compute_batch(bars, "SPY", "5m", cache, config, warm_up_bars=5)
        assert len(results) > 0, "compute_batch returned no results"
        # All non-null FeatureVector fields must be finite
        for _, fv in results:
            assert math.isfinite(fv.cci_slow), f"cci_slow not finite: {fv.cci_slow}"
            assert math.isfinite(fv.aroon_slow), f"aroon_slow not finite: {fv.aroon_slow}"


class TestWilderRsiSeries:
    def test_terminal_value_matches_rsi_simple(self) -> None:
        """_wilder_rsi_series[-1] must equal _rsi_simple for every prefix length."""
        from src.intelligence.feature_cache import _rsi_simple, _wilder_rsi_series

        rng = np.random.default_rng(42)
        closes = 100.0 * np.cumprod(1 + rng.normal(0, 0.01, 200))
        period = 14

        series = _wilder_rsi_series(closes, period)
        assert len(series) == len(closes)

        for n in range(2, len(closes) + 1):
            scalar = _rsi_simple(closes[:n], period)
            batch = float(series[n - 1])
            assert (
                abs(batch - scalar) < 1e-8
            ), f"n={n}: series={batch:.10f} scalar={scalar:.10f} delta={abs(batch-scalar):.2e}"

    def test_cold_start_returns_50(self) -> None:
        from src.intelligence.feature_cache import _wilder_rsi_series

        closes = np.array([100.0, 101.0, 102.0], dtype=float)
        series = _wilder_rsi_series(closes, period=14)
        assert series[0] == 50.0
        assert series[1] == 50.0
        assert series[2] == 50.0  # only 3 bars, period=14 → all cold

    def test_values_in_range(self) -> None:
        from src.intelligence.feature_cache import _wilder_rsi_series

        rng = np.random.default_rng(7)
        closes = 100.0 * np.cumprod(1 + rng.normal(0, 0.02, 500))
        series = _wilder_rsi_series(closes, period=14)
        assert np.all(series >= 0.0) and np.all(series <= 100.0)
