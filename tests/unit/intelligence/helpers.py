"""Shared test helpers for intelligence plugin tests."""
from __future__ import annotations

import numpy as np
import pandas as pd


def make_ohlcv(close: np.ndarray, volume: np.ndarray | None = None) -> pd.DataFrame:
    """Build OHLCV DataFrame from close array with synthetic high/low/open."""
    n = len(close)
    spread = np.abs(close) * 0.002
    high = close + spread
    low = close - spread
    open_ = close + np.random.default_rng(0).normal(0, 0.001, n) * close
    high = np.maximum(high, np.maximum(open_, close))
    low = np.minimum(low, np.minimum(open_, close))
    if volume is None:
        volume = np.full(n, 1000.0)
    return pd.DataFrame({"open": open_, "high": high, "low": low, "close": close, "volume": volume})


def make_ohlcv_from_hl(
    high: np.ndarray, low: np.ndarray, volume: np.ndarray | None = None
) -> pd.DataFrame:
    """Build OHLCV from explicit high/low arrays (close = midpoint)."""
    close = (high + low) / 2
    open_ = close + np.random.default_rng(0).normal(0, 0.001, len(close)) * close
    high = np.maximum(high, np.maximum(open_, close))
    low = np.minimum(low, np.minimum(open_, close))
    if volume is None:
        volume = np.full(len(close), 1000.0)
    return pd.DataFrame({"open": open_, "high": high, "low": low, "close": close, "volume": volume})
