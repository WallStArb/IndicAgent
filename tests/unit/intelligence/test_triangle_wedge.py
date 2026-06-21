# tests/unit/test_triangle_wedge.py
from __future__ import annotations

import numpy as np
import pandas as pd

from src.intelligence.archive.i5_patterns.triangle_wedge import TriangleWedgePlugin


def _make_frames(high, low, close):
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


def _base(n: int = 80):
    close = np.full(n, 5000.0)
    high = close + 1.0
    low = close - 1.0
    return close.copy(), high.copy(), low.copy()


def _inject_peak(high, bar, peak_price, shoulder_price=None):
    high[bar] = peak_price
    sp = shoulder_price if shoulder_price is not None else peak_price - 5.0
    for i in [bar - 2, bar - 1, bar + 1, bar + 2]:
        if 0 <= i < len(high):
            high[i] = sp


def _inject_trough(low, bar, trough_price, shoulder_price=None):
    low[bar] = trough_price
    sp = shoulder_price if shoulder_price is not None else trough_price + 5.0
    for i in [bar - 2, bar - 1, bar + 1, bar + 2]:
        if 0 <= i < len(low):
            low[i] = sp


def _build_ascending_triangle(n=80):
    """
    Ascending triangle: flat top (all peaks ≈ 5020), rising bottom trough sequence.
    Peak bars: 12, 27, 42, 57  — all high=5020 (slope ≈ 0)
    Trough bars: 19, 34, 49, 64 — lows: 4980, 4984, 4988, 4992 (rising)
    """
    close, high, low = _base(n)

    peak_bars = [12, 27, 42, 57]
    for b in peak_bars:
        _inject_peak(high, b, peak_price=5020.0, shoulder_price=5014.0)

    trough_prices = [4980.0, 4984.0, 4988.0, 4992.0]
    trough_bars = [19, 34, 49, 64]
    for b, lp in zip(trough_bars, trough_prices, strict=False):
        _inject_trough(low, b, trough_price=lp, shoulder_price=lp + 4.0)

    return close, high, low


def _build_descending_triangle(n=80):
    """
    Descending triangle: falling top, flat bottom.
    Peak bars: 12, 27, 42, 57  — highs: 5040, 5034, 5028, 5022 (falling)
    Trough bars: 19, 34, 49, 64 — all low=4980 (slope ≈ 0)
    """
    close, high, low = _base(n)

    peak_prices = [5040.0, 5034.0, 5028.0, 5022.0]
    peak_bars = [12, 27, 42, 57]
    for b, hp in zip(peak_bars, peak_prices, strict=False):
        _inject_peak(high, b, peak_price=hp, shoulder_price=hp - 5.0)

    trough_bars = [19, 34, 49, 64]
    for b in trough_bars:
        _inject_trough(low, b, trough_price=4980.0, shoulder_price=4985.0)

    return close, high, low


def _build_rising_wedge(n=80):
    """
    Rising wedge: both trendlines slope up, lower line steeper.
    Peaks: 12→5020, 27→5025, 42→5030, 57→5035  (slope +1/bar)
    Troughs: 19→5000, 34→5008, 49→5016, 64→5024  (slope +8/15 ≈ steeper relative to channel)
    """
    close, high, low = _base(n)

    peak_prices = [5020.0, 5025.0, 5030.0, 5035.0]
    peak_bars = [12, 27, 42, 57]
    for b, hp in zip(peak_bars, peak_prices, strict=False):
        _inject_peak(high, b, peak_price=hp, shoulder_price=hp - 4.0)

    trough_prices = [5000.0, 5008.0, 5016.0, 5024.0]
    trough_bars = [19, 34, 49, 64]
    for b, lp in zip(trough_bars, trough_prices, strict=False):
        _inject_trough(low, b, trough_price=lp, shoulder_price=lp + 4.0)

    return close, high, low


class TestTriangleWedgeInsufficientData:
    def test_returns_empty_when_too_few_bars(self):
        plugin = TriangleWedgePlugin()
        close, high, low = _base(50)  # min_lookback is 60
        result = plugin.compute_full(_make_frames(high, low, close))
        assert result == {}


class TestAscendingTriangle:
    def test_ascending_triangle_detected(self):
        plugin = TriangleWedgePlugin()
        close, high, low = _build_ascending_triangle()
        result = plugin.compute_full(_make_frames(high, low, close))
        assert result["tri_pattern"] == 1.0, f"Expected ascending(1), got {result}"
        assert result["tri_breakout_bias"] == 1.0
        assert 0.0 <= result["tri_confidence"] <= 1.0

    def test_ascending_triangle_upper_slope_near_zero(self):
        plugin = TriangleWedgePlugin()
        close, high, low = _build_ascending_triangle()
        result = plugin.compute_full(_make_frames(high, low, close))
        if result.get("tri_pattern") == 1.0:
            assert abs(result["tri_upper_slope"]) <= plugin.slope_tolerance * 50


class TestDescendingTriangle:
    def test_descending_triangle_detected(self):
        plugin = TriangleWedgePlugin()
        close, high, low = _build_descending_triangle()
        result = plugin.compute_full(_make_frames(high, low, close))
        assert result["tri_pattern"] == 2.0, f"Expected descending(2), got {result}"
        assert result["tri_breakout_bias"] == -1.0


class TestRisingWedge:
    def test_rising_wedge_detected(self):
        plugin = TriangleWedgePlugin()
        close, high, low = _build_rising_wedge()
        result = plugin.compute_full(_make_frames(high, low, close))
        assert result["tri_pattern"] == 4.0, f"Expected rising_wedge(4), got {result}"
        assert result["tri_breakout_bias"] == -1.0


class TestConfidence:
    def test_confidence_always_in_valid_range(self):
        plugin = TriangleWedgePlugin()
        for builder in [_build_ascending_triangle, _build_descending_triangle, _build_rising_wedge]:
            close, high, low = builder()
            result = plugin.compute_full(_make_frames(high, low, close))
            assert 0.0 <= result.get("tri_confidence", 0.0) <= 1.0
