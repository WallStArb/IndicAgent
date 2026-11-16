"""Per-row scalar references for the kernel equality tests (R2 item 5c).

These were the streaming path's scalar helpers in `kernels/price.py` and `kernels/control.py`.
Nothing in `src/` calls them since the streaming factory was deleted; the kernels compute the same
values block-vectorized. They stay here as independent oracles: a test that compares a kernel with
its per-row loop, or pins a canary sub-seed, needs a second implementation to compare against.
"""

from __future__ import annotations

from datetime import datetime

import numpy as np

from src.core.rng import hash_key_to_int
from src.intelligence.features.kernels._primitives import EPS
from src.intelligence.features.kernels.control import (
    _CANARY_CONSTANT_VALUE,
    _CANARY_NEAR_CONSTANT_EPSILON,
    _canary_seed,
)


def range_position(close: float, highs: np.ndarray, lows: np.ndarray, eps: float = EPS) -> float:
    """(close - min(low)) / (max(high) - min(low)); NaN on a degenerate range."""
    range_low = float(np.min(lows))
    range_high = float(np.max(highs))
    rng = range_high - range_low
    if rng < eps:
        return float("nan")
    return (close - range_low) / (rng + eps)


def vol_ratio(closes: np.ndarray, short_bars: int, long_bars: int) -> float:
    """std(short log returns) / std(long log returns); 1.0 on cold start or degenerate std."""
    if len(closes) < long_bars + 1:
        return 1.0
    long_returns = np.diff(np.log(np.maximum(closes[-(long_bars + 1) :], 1e-10)))
    short_returns = long_returns[-short_bars:]
    vol_short = float(np.std(short_returns))
    vol_long = float(np.std(long_returns))
    return vol_short / vol_long if vol_long > 1e-10 else 1.0


def cci(highs: np.ndarray, lows: np.ndarray, closes: np.ndarray, period: int) -> float:
    """(typical - SMA_typical) / (0.015 * MAD); NaN when MAD < 1e-10 or on a cold window."""
    if len(closes) < period:
        return float("nan")
    typical = (highs[-period:] + lows[-period:] + closes[-period:]) / 3.0
    sma = float(np.mean(typical))
    mad = float(np.mean(np.abs(typical - sma)))
    if mad < 1e-10:
        return float("nan")
    return float((float(typical[-1]) - sma) / (0.015 * mad))


def aroon_osc(highs: np.ndarray, lows: np.ndarray, period: int) -> float:
    """(aroon_up - aroon_down) / 100 in [-1, 1]; NaN below period + 1 bars."""
    if len(highs) < period + 1:
        return float("nan")
    window_h = highs[-(period + 1) :]
    window_l = lows[-(period + 1) :]
    aroon_up = int(np.argmax(window_h)) / period * 100.0
    aroon_down = int(np.argmin(window_l)) / period * 100.0
    return float(np.clip((aroon_up - aroon_down) / 100.0, -1.0, 1.0))


def canary_sub_seed(bar_ts: datetime, symbol: str, base_seed: int, offset: int) -> int:
    """Per-(symbol, bar) sub-seed: base seed, bar time, a per-canary offset and a stable MD5
    symbol hash (never Python's hash(), which varies across processes)."""
    return _canary_seed(int(bar_ts.timestamp() * 1000), hash_key_to_int(symbol), base_seed, offset)


def canary_noise_gaussian(bar_ts: datetime, symbol: str, base_seed: int) -> float:
    return float(
        np.random.default_rng(canary_sub_seed(bar_ts, symbol, base_seed, 0)).standard_normal()
    )


def canary_noise_uniform(bar_ts: datetime, symbol: str, base_seed: int) -> float:
    return float(
        np.random.default_rng(canary_sub_seed(bar_ts, symbol, base_seed, 1)).uniform(0.0, 1.0)
    )


def canary_near_constant(bar_ts: datetime, symbol: str, base_seed: int) -> float:
    rng = np.random.default_rng(canary_sub_seed(bar_ts, symbol, base_seed, 2))
    return _CANARY_CONSTANT_VALUE + _CANARY_NEAR_CONSTANT_EPSILON * float(rng.standard_normal())
