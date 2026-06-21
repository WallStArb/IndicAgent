# tests/unit/test_double_top_bottom.py
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

# This import will FAIL until Task 2 creates the plugin — that's expected.
from src.intelligence.archive.i5_patterns.double_top_bottom import DoubleTBPlugin


def _make_frames(high: np.ndarray, low: np.ndarray, close: np.ndarray) -> dict:
    n = len(close)
    return {
        "main": pd.DataFrame(
            {
                "open": close,
                "high": high,
                "close": close,
                "low": low,
                "volume": np.ones(n) * 1000,
            }
        )
    }


def _base(n: int = 80) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Flat arrays at 5000. find_peaks finds no peaks (all equal, no strict inequality)."""
    close = np.full(n, 5000.0)
    high = close + 1.0  # 5001 everywhere
    low = close - 1.0  # 4999 everywhere
    return close.copy(), high.copy(), low.copy()


def _inject_peak(high: np.ndarray, bar: int, peak_price: float, shoulder: float = 5010.0) -> None:
    """Place a clean peak at `bar` with 4 lower neighbors on each side."""
    high[bar] = peak_price
    for i in [bar - 2, bar - 1, bar + 1, bar + 2]:
        if 0 <= i < len(high):
            high[i] = shoulder


def _inject_trough(
    low: np.ndarray,
    close: np.ndarray,
    high: np.ndarray,
    bar: int,
    trough_price: float,
    shoulder: float = 4985.0,
) -> None:
    """Place a clean trough at `bar`."""
    low[bar] = trough_price
    close[bar] = trough_price + 1.0
    high[bar] = trough_price + 2.0
    for i in [bar - 2, bar - 1, bar + 1, bar + 2]:
        if 0 <= i < len(low):
            low[i] = shoulder
            close[i] = shoulder + 1.0
            high[i] = shoulder + 2.0


class TestDoubleTBInsufficientData:
    def test_returns_empty_when_too_few_bars(self):
        plugin = DoubleTBPlugin()
        close, high, low = _base(50)  # min_lookback is 60
        result = plugin.compute_full(_make_frames(high, low, close))
        assert result == {}


class TestDoubleTBForming:
    def test_two_equal_peaks_above_neckline_is_forming(self):
        """Peaks at bars 20 and 55, neckline trough at bar 37, close above neckline → pattern=1."""
        plugin = DoubleTBPlugin()
        n = 80
        close, high, low = _base(n)

        _inject_peak(high, bar=20, peak_price=5015.0)
        _inject_trough(low, close, high, bar=37, trough_price=4980.0)
        _inject_peak(high, bar=55, peak_price=5015.0)  # same price → within 0.3% tolerance

        # Current close ABOVE neckline 4980
        close[-1] = 4992.0
        high[-1] = 4993.0
        low[-1] = 4991.0

        result = plugin.compute_full(_make_frames(high, low, close))
        assert result["dt_db_pattern"] == 1.0, f"Expected forming(1), got {result}"
        assert result["dt_db_neckline"] == pytest.approx(4980.0, abs=0.5)
        assert 0.0 <= result["dt_db_confidence"] <= 1.0


class TestDoubleTBConfirmed:
    def test_close_below_neckline_confirms_double_top(self):
        """Same setup but close BELOW neckline → pattern=2."""
        plugin = DoubleTBPlugin()
        n = 80
        close, high, low = _base(n)

        _inject_peak(high, bar=20, peak_price=5015.0)
        _inject_trough(low, close, high, bar=37, trough_price=4980.0)
        _inject_peak(high, bar=55, peak_price=5015.0)

        # Close BELOW neckline 4980
        close[-1] = 4970.0
        high[-1] = 4972.0
        low[-1] = 4969.0

        result = plugin.compute_full(_make_frames(high, low, close))
        assert result["dt_db_pattern"] == 2.0
        target = result["dt_db_target"]
        # Measured move: neckline - (peak - neckline) = 4980 - (5015 - 4980) = 4945
        assert target == pytest.approx(4945.0, abs=2.0)


class TestDoubleBottom:
    def test_two_equal_troughs_detected_as_double_bottom(self):
        """Two troughs at same price, neckline peak between them → pattern 3 or 4."""
        plugin = DoubleTBPlugin()
        n = 80
        close, high, low = _base(n)

        # Trough 1 at bar 20
        _inject_trough(low, close, high, bar=20, trough_price=4985.0)
        # Neckline peak at bar 37
        _inject_peak(high, bar=37, peak_price=5010.0)
        # Trough 2 at bar 55 (same price)
        _inject_trough(low, close, high, bar=55, trough_price=4985.0)

        result = plugin.compute_full(_make_frames(high, low, close))
        assert result["dt_db_pattern"] in (3.0, 4.0), f"Expected 3 or 4, got {result}"
        assert result["dt_db_neckline"] == pytest.approx(5010.0, abs=1.0)


class TestNoPattern:
    def test_flat_data_returns_zero_pattern(self):
        """Flat data → find_peaks finds nothing → pattern=0."""
        plugin = DoubleTBPlugin()
        close, high, low = _base(80)
        result = plugin.compute_full(_make_frames(high, low, close))
        # Returns default zeros dict (not empty — data is sufficient)
        assert result.get("dt_db_pattern", 0.0) == 0.0
