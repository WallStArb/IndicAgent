"""Shared utilities for intelligence plugins."""

from __future__ import annotations

import math
from datetime import UTC, datetime
from typing import Any

import numpy as np

# Timeframe constants for TF guards
INTRADAY_ONLY_TFS = ("1m", "5m", "15m")


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


def guard_intraday_only(frames: dict[str, Any]) -> bool:
    """Return False if timeframe is not intraday-only (1h+ bars blocked).

    This prevents intraday-only setups from firing on hourly or higher timeframes
    where the session-based logic doesn't apply. Empty string (not yet injected)
    passes through for backward compatibility with tests.

    Parameters
    ----------
    frames : dict[str, Any]
        Frame dict containing optional "timeframe" key

    Returns
    -------
    bool
        True if timeframe is intraday-only or unset, False if 1h/4h/1d/etc.
    """
    tf = frames.get("timeframe", "")
    return not tf or tf in INTRADAY_ONLY_TFS


def safe_corr(x: np.ndarray, y: np.ndarray) -> float:
    """Pearson correlation coefficient between two equal-length arrays.

    Returns 0.0 for degenerate input (fewer than 2 samples or zero variance
    in either series) rather than NaN. Canonical implementation -- previously
    duplicated as feature_factory.py's `_correlation()` and feature_cache.py's
    `_safe_corr()` (byte-identical formulas, different names, in different
    modules that couldn't import from each other directly without a cycle);
    consolidated here (code review IN-01, Phase 151 post-execution review).
    """
    if len(x) < 2 or len(y) < 2:
        return 0.0
    xm = x - x.mean()
    ym = y - y.mean()
    denom = float(np.sqrt(np.dot(xm, xm) * np.dot(ym, ym)))
    if denom < 1e-10:
        return 0.0
    return float(np.dot(xm, ym) / denom)
