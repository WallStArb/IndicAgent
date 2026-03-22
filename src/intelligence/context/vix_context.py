"""VIX context computation -- pure-function module.

No Kafka, no DB, no side effects. All I/O lives in the service layer.
Computes VIX level and z-score from bar history for I6 confluence expansion.
"""

from __future__ import annotations

import statistics
from collections import deque
from typing import Any

from src.core.schemas.bar_message import BarMessage

# Threshold below which rolling std is treated as near-zero (same as cross_asset_features.py)
_LOW_VOL_THRESHOLD: float = 1e-8


def compute_vix_context(vix_bars: deque[BarMessage], z_window: int = 20) -> dict[str, Any]:
    """Compute VIX level and z-score from a deque of bar data.

    Args:
        vix_bars: Deque of BarMessage objects for the VIX instrument (any TF).
        z_window: Number of bars used for rolling mean and stddev (default 20).

    Returns:
        {"ready": False} when fewer than z_window bars are available.
        {"ready": True, "level": float, "z_score": float} when sufficient data exists.

    Notes:
        - ``level`` is the close price of the most recent bar.
        - ``z_score`` = (level − mean) / stddev over the last ``z_window`` bars.
        - When stddev < ``_LOW_VOL_THRESHOLD`` (near-zero), ``z_score`` is 0.0
          to prevent NaN / Inf output.
        - All returned floats are rounded to 4 decimal places.
    """
    if len(vix_bars) < z_window:
        return {"ready": False}

    # Extract close prices from the last z_window bars
    closes: list[float] = [bar.close for bar in list(vix_bars)[-z_window:]]

    level: float = closes[-1]
    mean: float = sum(closes) / z_window

    # Use population stddev via manual sqrt to stay dependency-free
    # statistics.stdev uses sample (n-1) — which matches the manual formula
    # described in the plan and the test fixture.  Use it directly.
    std: float = statistics.stdev(closes)

    if std < _LOW_VOL_THRESHOLD:
        z_score: float = 0.0
    else:
        z_score = (level - mean) / std

    return {
        "level": round(float(level), 4),
        "z_score": round(float(z_score), 4),
        "ready": True,
    }
