"""Flight-to-quality macro factor.

Computes flight-to-quality signal from TLT (20+ Year Treasury Bond ETF)
and SPY (S&P 500 ETF). Classic risk-off signal: TLT up + SPY down.

Future enhancement: Add VX (VIX futures) when data available.

Outputs:
    ftq_score: float [-1, +1]
        - Positive: Risk-on (SPY outperforming TLT)
        - Negative: Risk-off (TLT outperforming SPY, flight to quality)
        - Near 0: Neutral
    ftq_regime: str
        - risk_on: Bullish equities, bearish bonds
        - risk_off: Bearish equities, bullish bonds (flight to quality)
        - neutral: Balanced performance
"""

from __future__ import annotations

from collections import deque
from typing import Any

import numpy as np


def compute_flight_to_quality(
    bars: dict[str, deque],
    lookback: int = 10,
) -> dict[str, Any]:
    """Compute flight-to-quality signal from TLT+SPY.

    Args:
        bars: Dict mapping symbol → deque of recent bars (OHLCV dicts)
        lookback: Number of bars to average (default: 10)

    Returns:
        dict with ftq_score (float) and ftq_regime (str)

    Implementation:
        1. Extract close prices for TLT, SPY
        2. Compute relative performance: SPY_return - TLT_return
        3. Normalize via tanh for gradient in [-1, +1]
        4. Classify regime based on magnitude + direction

    Future enhancement: Add VX (VIX futures) for third dimension:
        - VX up + SPY down = strong risk-off
        - VX down + SPY up = strong risk-on
    """
    # Check if we have enough data
    # We need at least 2 bars to compute a return (current and previous)
    spy_len = len(bars.get("SPY", []))
    tlt_len = len(bars.get("TLT", []))

    if spy_len < 2 or tlt_len < 2:
        return {
            "ftq_score": 0.0,
            "ftq_regime": "neutral",
        }

    # Use the minimum of lookback and available bars (minus 1 for returns)
    min_required = min(lookback, spy_len, tlt_len)

    # Extract recent closes (average over lookback for stability)
    # We'll compute returns between consecutive bars
    spy_returns = []
    tlt_returns = []

    # Number of returns we can compute = min bars - 1
    num_returns = min(spy_len, tlt_len) - 1
    actual_lookback = min(lookback, num_returns)

    for i in range(1, actual_lookback + 1):  # Start at 1 to avoid -0 index issue
        try:
            spy_close = bars["SPY"][-i]["close"]
            tlt_close = bars["TLT"][-i]["close"]

            if None in (spy_close, tlt_close):
                continue

            # Previous close for return calculation
            spy_prev = bars["SPY"][-i-1]["close"]
            tlt_prev = bars["TLT"][-i-1]["close"]

            # Simple return
            spy_ret = (spy_close - spy_prev) / spy_prev if spy_prev != 0 else 0.0
            tlt_ret = (tlt_close - tlt_prev) / tlt_prev if tlt_prev != 0 else 0.0

            spy_returns.append(spy_ret)
            tlt_returns.append(tlt_ret)

        except (IndexError, KeyError, ZeroDivisionError, TypeError):
            continue

    if not spy_returns or not tlt_returns or len(spy_returns) < lookback // 2:
        return {
            "ftq_score": 0.0,
            "ftq_regime": "neutral",
        }

    # Average returns
    avg_spy_ret = np.mean(spy_returns)
    avg_tlt_ret = np.mean(tlt_returns)

    # Relative performance: SPY - TLT
    # Positive = SPY outperforming TLT (risk-on)
    # Negative = TLT outperforming SPY (risk-off)
    relative_perf = avg_spy_ret - avg_tlt_ret

    # Normalize via tanh: 0.01 = 1% relative return -> tanh(0.01 * 100) ≈ 0.76
    ftq_score = np.tanh(relative_perf * 100.0)  # [-1, +1]

    # Regime classification
    if relative_perf > 0.002:  # >0.2% risk-on
        regime = "risk_on"
    elif relative_perf < -0.002:  # >0.2% risk-off
        regime = "risk_off"
    else:
        regime = "neutral"

    return {
        "ftq_score": float(ftq_score),
        "ftq_regime": regime,
    }
