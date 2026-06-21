# tests/unit/test_head_shoulders.py
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.intelligence.archive.i5_patterns.head_shoulders import HeadShouldersPlugin


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


def _base(n: int = 100):
    close = np.full(n, 5000.0)
    high = close + 1.0
    low = close - 1.0
    return close.copy(), high.copy(), low.copy()


def _inject_peak(high, bar, peak_price, shoulder=5010.0):
    high[bar] = peak_price
    for i in [bar - 2, bar - 1, bar + 1, bar + 2]:
        if 0 <= i < len(high):
            high[i] = shoulder


def _inject_trough(low, close, high, bar, trough_price, shoulder=4990.0):
    low[bar] = trough_price
    close[bar] = trough_price + 1.0
    high[bar] = trough_price + 2.0
    for i in [bar - 2, bar - 1, bar + 1, bar + 2]:
        if 0 <= i < len(low):
            low[i] = shoulder
            close[i] = shoulder + 1.0
            high[i] = shoulder + 2.0


def _build_hs_data(n=100, confirmed=False):
    """
    Structure:
      Left shoulder peak: bar 15, high=5015
      Left trough:        bar 28, low=4985   ← neckline point 1
      Head peak:          bar 45, high=5190  (> ls * 1.03 = 5165)
      Right trough:       bar 60, low=4987   ← neckline point 2
      Right shoulder:     bar 75, high=5016  (within 5% of 5015)
      Final bar 99: above or below sloped neckline
    """
    close, high, low = _base(n)

    _inject_peak(high, bar=15, peak_price=5015.0)
    _inject_trough(low, close, high, bar=28, trough_price=4985.0)
    _inject_peak(high, bar=45, peak_price=5190.0, shoulder=5160.0)
    _inject_trough(low, close, high, bar=60, trough_price=4987.0)
    _inject_peak(high, bar=75, peak_price=5016.0)

    # Sloped neckline: from (28, 4985) to (60, 4987)
    # slope = (4987 - 4985) / (60 - 28) = 0.0625 per bar
    # neckline at bar 99 = 4985 + 0.0625 * (99 - 28) = 4985 + 4.44 = 4989.44
    if confirmed:
        close[-1] = 4983.0  # well below 4989.44
        low[-1] = 4982.0
        high[-1] = 4984.0
    else:
        close[-1] = 4995.0  # above neckline
        low[-1] = 4994.0
        high[-1] = 4996.0

    return close, high, low


class TestHSInsufficientData:
    def test_returns_empty_when_too_few_bars(self):
        plugin = HeadShouldersPlugin()
        close, high, low = _base(70)  # min_lookback is 80
        result = plugin.compute_full(_make_frames(high, low, close))
        assert result == {}


class TestHSForming:
    def test_valid_hs_above_neckline_is_forming(self):
        plugin = HeadShouldersPlugin()
        close, high, low = _build_hs_data(confirmed=False)
        result = plugin.compute_full(_make_frames(high, low, close))
        assert result["hs_pattern"] == 1.0, f"Expected hs_forming(1), got {result}"
        assert 0.0 <= result["hs_confidence"] <= 1.0
        # Neckline at bar 99 ≈ 4989.44
        assert result["hs_neckline"] == pytest.approx(4989.44, abs=1.0)


class TestHSConfirmed:
    def test_close_below_sloped_neckline_confirms(self):
        plugin = HeadShouldersPlugin()
        close, high, low = _build_hs_data(confirmed=True)
        result = plugin.compute_full(_make_frames(high, low, close))
        assert result["hs_pattern"] == 2.0, f"Expected hs_confirmed(2), got {result}"
        # neckline_distance should be positive (close below neckline)
        assert result["hs_neckline_distance"] > 0.0

    def test_target_is_below_neckline(self):
        plugin = HeadShouldersPlugin()
        close, high, low = _build_hs_data(confirmed=True)
        result = plugin.compute_full(_make_frames(high, low, close))
        if result["hs_pattern"] == 2.0:
            # Target should be well below the neckline (measured move down)
            assert result["hs_target"] < result["hs_neckline"]


class TestInverseHS:
    def test_inverse_hs_detected(self):
        """Mirror: three troughs with lowest in middle → ihs_forming (3) or ihs_confirmed (4)."""
        plugin = HeadShouldersPlugin()
        n = 100
        close, high, low = _base(n)

        # Left shoulder trough at bar 15 (low=4985)
        _inject_trough(low, close, high, bar=15, trough_price=4985.0)
        # Left peak (neckline point 1) at bar 28
        _inject_peak(high, bar=28, peak_price=5015.0)
        # Head trough at bar 45 (must be < 4985 * (1 - 0.03) = 4815.55 → use 4810)
        _inject_trough(low, close, high, bar=45, trough_price=4810.0, shoulder=4850.0)
        # Right peak (neckline point 2) at bar 60
        _inject_peak(high, bar=60, peak_price=5016.0)
        # Right shoulder trough at bar 75 (≈ left shoulder, within 5%)
        _inject_trough(low, close, high, bar=75, trough_price=4986.0)

        result = plugin.compute_full(_make_frames(high, low, close))
        assert result["hs_pattern"] in (3.0, 4.0), f"Expected IHS, got {result}"


class TestNoPattern:
    def test_flat_data_returns_zero_pattern(self):
        plugin = HeadShouldersPlugin()
        close, high, low = _base(100)
        result = plugin.compute_full(_make_frames(high, low, close))
        assert result.get("hs_pattern", 0.0) == 0.0
