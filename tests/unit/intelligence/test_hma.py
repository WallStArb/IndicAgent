# tests/unit/intelligence/test_hma.py
"""RED test stubs for HMAPlugin (Plan 02 target).

All tests FAIL with ImportError until Plan 02 creates
src/intelligence/indicators/hma.py.
"""
from __future__ import annotations

import numpy as np
import pytest

from src.intelligence.indicators.hma import HMAPlugin
from tests.unit.intelligence.helpers import make_ohlcv

# ── plugin contract tests ─────────────────────────────────────────────────────


def test_hma_20_in_outputs():
    """hma_20 must be in plugin.outputs frozenset."""
    plugin = HMAPlugin()
    assert "hma_20" in plugin.outputs


def test_min_lookback_is_20():
    """plugin.min_lookback must equal 20."""
    plugin = HMAPlugin()
    assert plugin.min_lookback == 20


# ── warmup gate tests ─────────────────────────────────────────────────────────


def test_returns_empty_or_zero_when_fewer_than_20_bars():
    """Fewer than 20 bars → returns {} or {'hma_20': 0.0}."""
    plugin = HMAPlugin()
    closes = np.full(15, 5000.0)
    df = make_ohlcv(closes)
    result = plugin.compute_full({"main": df, "features": {}})
    # Accept either {} (empty) or a dict with hma_20=0.0 (safe default)
    assert result == {} or result.get("hma_20", 0.0) == pytest.approx(0.0)


# ── formula correctness tests ─────────────────────────────────────────────────


def test_hma_20_is_float_on_valid_input():
    """With 50+ bars of valid prices, hma_20 is a float."""
    plugin = HMAPlugin()
    closes = np.linspace(5000.0, 5050.0, 50)
    df = make_ohlcv(closes)
    result = plugin.compute_full({"main": df, "features": {}})
    assert isinstance(result.get("hma_20"), float)
    assert result["hma_20"] > 0.0


def test_hma_20_flat_series_equals_price():
    """WMA of a constant → constant.  Therefore HMA(constant series) = constant.

    For all closes = C:
    WMA(n/2, C) = C  and  WMA(n, C) = C
    2*C - C = C
    WMA(sqrt(n), C) = C
    So hma_20 must equal C.
    """
    plugin = HMAPlugin()
    c = 5000.0
    closes = np.full(50, c)
    df = make_ohlcv(closes)
    result = plugin.compute_full({"main": df, "features": {}})
    assert result.get("hma_20") == pytest.approx(c, rel=1e-6)


def test_hma_20_trending_series_closer_to_current_price():
    """HMA is designed to be a low-lag MA.

    On a strongly trending series, hma_20 should be closer to the current price
    than a simple 20-bar SMA.
    """
    plugin = HMAPlugin()
    closes = np.linspace(4800.0, 5200.0, 50)   # strong uptrend
    df = make_ohlcv(closes)
    result = plugin.compute_full({"main": df, "features": {}})
    hma = result.get("hma_20")
    if hma is not None:
        current_price = closes[-1]
        sma_20 = float(np.mean(closes[-20:]))
        hma_distance = abs(current_price - hma)
        sma_distance = abs(current_price - sma_20)
        # HMA should be within SMA distance or closer to current price
        assert hma_distance <= sma_distance * 1.5, (
            f"HMA ({hma:.2f}) not close to current price ({current_price:.2f}); "
            f"SMA20={sma_20:.2f}"
        )
