"""Shared utilities for intelligence plugins."""

from __future__ import annotations

import math
from datetime import UTC, datetime
from typing import Any

import numpy as np


def find_peaks(data: np.ndarray, n: int) -> list[int]:
    """Find local maxima using N-neighbor comparison.

    Uses >= so that a bar tying its neighbor still qualifies (common in
    futures tick data where highs cluster at round numbers).  Requires at
    least one strict inequality to avoid firing on every bar in a flat line.

    Vectorized: ~50-100x faster than the Python-loop version for typical
    n=5, len=120 inputs.
    """
    length = len(data)
    if length < 2 * n + 1:
        return []
    count = length - 2 * n
    result = np.ones(count, dtype=bool)
    strict = np.zeros(count, dtype=bool)
    center = data[n : n + count]
    for j in range(1, n + 1):
        left = data[n - j : n - j + count]
        right = data[n + j : n + j + count]
        result &= (center >= left) & (center >= right)
        strict |= (center > left) | (center > right)
    indices = np.where(result & strict)[0] + n
    return indices.tolist()


def find_troughs(data: np.ndarray, n: int) -> list[int]:
    """Find local minima using N-neighbor comparison.

    Uses <= with at least one strict inequality to handle ties without
    producing false positives on flat data.

    Vectorized: ~50-100x faster than the Python-loop version.
    """
    length = len(data)
    if length < 2 * n + 1:
        return []
    count = length - 2 * n
    result = np.ones(count, dtype=bool)
    strict = np.zeros(count, dtype=bool)
    center = data[n : n + count]
    for j in range(1, n + 1):
        left = data[n - j : n - j + count]
        right = data[n + j : n + j + count]
        result &= (center <= left) & (center <= right)
        strict |= (center < left) | (center < right)
    indices = np.where(result & strict)[0] + n
    return indices.tolist()


def is_num(x: Any) -> bool:
    """Check if value is a valid finite numeric type (rejects NaN and Inf)."""
    return isinstance(x, int | float) and math.isfinite(x)


def clamp(value: float, min_val: float = -1.0, max_val: float = 1.0) -> float:
    """Clamp a value to be within [min_val, max_val] inclusive.

    Commonly used to normalize scores to [-1.0, 1.0] range.

    Parameters
    ----------
    value: float
        Value to clamp
    min_val: float
        Minimum allowed value (default: -1.0)
    max_val: float
        Maximum allowed value (default: 1.0)

    Returns
    -------
    float
        Clamped value within [min_val, max_val]
    """
    return max(min_val, min(max_val, value))


def linreg_slope(y: np.ndarray) -> float:
    """Simple linear regression slope: Σ((x - x̄)(y - ȳ)) / Σ((x - x̄)²).

    Returns 0.0 for arrays with fewer than 2 elements or zero denominator.
    Used by divergence plugins (VolumeDivergence, MACDDivergence, CMFDivergence).
    """
    n = len(y)
    if n < 2:
        return 0.0
    x = np.arange(n, dtype=float)
    x_mean = (n - 1) / 2.0
    y_mean = float(np.mean(y))
    num = float(np.sum((x - x_mean) * (y - y_mean)))
    den = float(np.sum((x - x_mean) ** 2))
    return num / den if den != 0 else 0.0


def utc_datetime_from_df(df: Any) -> datetime | None:
    """Extract a timezone-aware UTC datetime from the last bar's timestamp column.

    Handles both native ``datetime`` objects and pandas ``Timestamp`` values.
    Returns ``None`` if the column is absent or parsing fails.
    """
    if "timestamp" not in df.columns or df.empty:
        return None
    raw = df.iloc[-1]["timestamp"]
    if isinstance(raw, datetime):
        return raw.astimezone(UTC) if raw.tzinfo else raw.replace(tzinfo=UTC)
    try:
        import pandas as pd

        ts = pd.Timestamp(raw).to_pydatetime()
        return ts.replace(tzinfo=UTC) if ts.tzinfo is None else ts.astimezone(UTC)
    except Exception:
        return None
