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
