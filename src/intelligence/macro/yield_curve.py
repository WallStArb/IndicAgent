"""Yield curve slope macro factor.

Computes yield curve slope from rate futures prices (ZT, ZB).
Rate futures trade inverse to yields: price up = yield down.

Proxy formula: yield = -log(price / 100). Slope = ZT_proxy - ZB_proxy.

Sign convention (proxy-based, not true yield spread):
    Positive slope: ZB has more price appreciation than ZT (long rates fell more).
    Negative slope: ZT has more price appreciation than ZB (short rates fell more or
                    long rates rose).

Regime labels reflect the proxy formula behaviour. For precise inversion detection,
use DV01-adjusted actual yields.

Outputs:
    yield_curve_slope: float [-1, +1]
        - Positive: ZB price appreciation > ZT (long rates falling faster)
        - Negative: ZT price appreciation > ZB (short rates falling faster)
        - Near 0: Rates moving together
    yield_curve_regime: str
        - steepening: slope > 0.10 (long rates diverging down from short)
        - flattening: slope < -0.10 (short rates diverging down from long)
        - inverted: ZB proxy > ZT proxy (ZB less above par than ZT — spread compression)
        - normal: Stable typical spread
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
    # ZN excluded from min_required — not used in slope computation (only ZT and ZB)
    min_required = min(lookback, len(bars.get("ZT", [])), len(bars.get("ZB", [])))

    if min_required < lookback:
        return {
            "yield_curve_slope": 0.0,
            "yield_curve_regime": "normal",
        }

    # range(1, ...) avoids -0 == 0 trap: deque[-0] returns the OLDEST element, not newest
    slopes = []
    for i in range(1, min_required + 1):
        try:
            zt_close = bars["ZT"][-i]["close"]
            zb_close = bars["ZB"][-i]["close"]

            zt_yield = -np.log(zt_close / 100.0)
            zb_yield = -np.log(zb_close / 100.0)

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

    # Multiplier 10 preserves gradient for typical proxy spreads (0.05–0.20 range)
    # At 100 the output saturates to ±1 for all realistic rate future prices
    slope_normalized = np.tanh(avg_slope * 10.0)  # [-1, +1]

    # Use [-1] (most recent) — [0] on a deque is the OLDEST element
    try:
        zt_yield_latest = -np.log(bars["ZT"][-1]["close"] / 100.0)
        zb_yield_latest = -np.log(bars["ZB"][-1]["close"] / 100.0)
    except (IndexError, KeyError, TypeError):
        zt_yield_latest = 0.0
        zb_yield_latest = 0.0

    # Regime classification
    # "inverted" fires when ZB proxy > ZT proxy (ZB less above par — spread compression)
    if zb_yield_latest > zt_yield_latest:
        regime = "inverted"
    elif avg_slope > 0.10:
        regime = "steepening"
    elif avg_slope < -0.10:
        regime = "flattening"
    else:
        regime = "normal"

    return {
        "yield_curve_slope": float(slope_normalized),
        "yield_curve_regime": regime,
    }
