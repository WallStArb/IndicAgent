"""Yield curve slope macro factor.

Computes yield curve slope from rate futures prices (ZT, ZN, ZB, ZF).
Rate futures trade inverse to yields: price up = yield down.

Outputs:
    yield_curve_slope: float [-1, +1]
        - Positive: Curve steepening (short rates down more than long)
        - Negative: Curve flattening (short rates up more than long)
        - Near 0: Curve stable
    yield_curve_regime: str
        - steepening: Bullish steepening
        - flattening: Bearish flattening
        - inverted: Yield curve inverted
        - normal: Normal yield curve
"""

from __future__ import annotations

from collections import deque
from typing import Any

import numpy as np


def compute_yield_curve_slope(
    bars: dict[str, deque],
    lookback: int = 10,
) -> dict[str, Any]:
    """Compute yield curve slope from rate futures.

    Args:
        bars: Dict mapping symbol → deque of recent bars (OHLCV dicts)
        lookback: Number of bars to average (default: 10)

    Returns:
        dict with yield_curve_slope (float) and yield_curve_regime (str)

    Implementation:
        1. Extract close prices for ZT, ZN, ZB, ZF
        2. Compute yield proxy: yield = -log(price / 100)  # Price down = yield up
        3. Compute slope: ZT_yield - ZB_yield (short - long)
        4. Normalize slope via tanh for gradient in [-1, +1]
        5. Classify regime based on slope magnitude + ZT-ZB relationship
    """
    # Check if we have enough data
    min_required = min(lookback, len(bars.get("ZT", [])), len(bars.get("ZN", [])), len(bars.get("ZB", [])))
    
    if min_required < lookback:
        return {
            "yield_curve_slope": 0.0,
            "yield_curve_regime": "normal",
        }

    # Extract recent closes (average over lookback for stability)
    slopes = []
    for i in range(min_required):
        try:
            zt_close = bars["ZT"][-i]["close"]
            zn_close = bars["ZN"][-i]["close"]
            zb_close = bars["ZB"][-i]["close"]

            # Yield proxy: price down = yield up
            # Use -log(price / 100) to convert to yield basis points
            zt_yield = -np.log(zt_close / 100.0)
            zb_yield = -np.log(zb_close / 100.0)

            # Slope: short-term yield minus long-term yield
            slope = zt_yield - zb_yield
            slopes.append(slope)
        except (IndexError, KeyError, TypeError):
            continue

    if not slopes or len(slopes) < lookback // 2:  # Need at least half the lookback
        return {
            "yield_curve_slope": 0.0,
            "yield_curve_regime": "normal",
        }

    # Average slope
    avg_slope = np.mean(slopes)

    # Normalize via tanh: 0.01 = 1% steepening -> tanh(0.01 * 100) ≈ 0.76
    slope_normalized = np.tanh(avg_slope * 100.0)  # [-1, +1]

    # Compute current yields for regime classification
    try:
        zt_close_latest = bars["ZT"][0]["close"]
        zb_close_latest = bars["ZB"][0]["close"]
        zt_yield_latest = -np.log(zt_close_latest / 100.0)
        zb_yield_latest = -np.log(zb_close_latest / 100.0)
    except (IndexError, KeyError, TypeError):
        zt_yield_latest = 0.0
        zb_yield_latest = 0.0

    # Regime classification
    if zb_yield_latest > zt_yield_latest:  # Inverted (long yield > short yield)
        regime = "inverted"
    elif avg_slope > 0.005:  # >0.5% steepening
        regime = "steepening"
    elif avg_slope < -0.005:  # >0.5% flattening
        regime = "flattening"
    else:
        regime = "normal"

    return {
        "yield_curve_slope": float(slope_normalized),
        "yield_curve_regime": regime,
    }
