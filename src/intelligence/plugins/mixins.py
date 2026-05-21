"""Shared utility functions for I1-I7 plugins.

Pure, module-level functions with no side effects. Any plugin can import and
use these directly without inheritance or registration.

NaN propagation contract
------------------------
Both ``wilders_update`` and ``update_ema`` propagate NaN: any NaN input
produces NaN output with no silent fallback. This matches the inline behavior
found in ATR, RSI, MFI, and MACD before extraction.

get_main_df contract
--------------------
Returns ``None`` (never raises) when data is insufficient. Callers MUST check
the return value and handle ``None`` appropriately -- typically ``return {}``
for plugins.
"""

from __future__ import annotations

import math
from typing import Any

import pandas as pd

__all__ = ["wilders_update", "update_ema", "get_main_df"]


def wilders_update(prev: float, new_val: float, period: int) -> float:
    """Apply one step of Wilder's smoothing.

    Formula: ``(prev * (period - 1) + new_val) / period``

    NaN rule: NaN in -> NaN out. If either ``prev`` or ``new_val`` is NaN,
    the function returns ``float("nan")`` immediately with no computation.
    This matches the inline guard found in ATR's Wilder's smoothing loop
    (``pd.notna`` check before using the result).

    Usage example (ATR incremental update)::

        new_atr = wilders_update(s["prev_atr"], tr, period)

    Args:
        prev:    Previous smoothed value (e.g. previous ATR or avg_gain).
        new_val: Current raw value to smooth in (e.g. current True Range).
        period:  Wilder smoothing period. Must be >= 1.

    Returns:
        Updated smoothed value, or ``float("nan")`` if either input is NaN.

    Raises:
        ValueError: If ``period < 1``.
    """
    if period < 1:
        raise ValueError(f"period must be >= 1, got {period}")
    if math.isnan(prev):
        return float("nan")
    if math.isnan(new_val):
        return float("nan")
    return (prev * (period - 1) + new_val) / period


def update_ema(current: float, prev_ema: float, span: int) -> float:
    """Apply one step of exponential moving average (EMA) smoothing.

    Formula: ``alpha * current + (1 - alpha) * prev_ema``
    where ``alpha = 2 / (span + 1)``.

    NaN rule: NaN in either arg -> NaN out. If ``current`` or ``prev_ema``
    is NaN, the function returns ``float("nan")`` immediately. This matches
    the inline EMA update chains in MACD (fast, slow, and signal EMAs are
    always seeded from valid full-computation values, so a NaN here indicates
    a real error -- no silent fallback is appropriate).

    Usage example (MACD fast EMA update)::

        s["ema_fast"] = update_ema(new_close, s["ema_fast"], fast)

    Args:
        current:  Current bar value (e.g. close price).
        prev_ema: Previous EMA value. Must be a valid float (not NaN) for
                  correct operation; NaN propagates as an error indicator.
        span:     EMA span (number of periods). Must be >= 1.
                  ``alpha = 2 / (span + 1)``; span=1 gives alpha=1.0 (no
                  smoothing -- output equals ``current``).

    Returns:
        Updated EMA value, or ``float("nan")`` if either input is NaN.

    Raises:
        ValueError: If ``span < 1``.
    """
    if span < 1:
        raise ValueError(f"span must be >= 1, got {span}")
    if math.isnan(current):
        return float("nan")
    if math.isnan(prev_ema):
        return float("nan")
    alpha = 2.0 / (span + 1)
    return alpha * current + (1.0 - alpha) * prev_ema


def get_main_df(frames: dict[str, Any] | None, min_bars: int) -> pd.DataFrame | None:
    """Extract the primary OHLCV DataFrame from a plugin ``frames`` dict.

    Returns ``None`` when data is insufficient. Callers MUST check for
    ``None`` and handle appropriately. The typical plugin pattern is::

        df = get_main_df(frames, self.min_lookback)
        if df is None:
            return {}

    Returns ``None`` when:
    - ``frames`` is ``None`` or not a dict
    - ``frames["main"]`` is missing or not a DataFrame
    - ``len(frames["main"]) < min_bars``

    This function never raises. It is a pure guard -- no data is modified.

    Args:
        frames:   Plugin frames dict (typically passed directly from
                  ``compute_full``/``compute_next``). May be ``None``.
        min_bars: Minimum number of rows required in ``frames["main"]``.
                  Use the plugin's ``min_lookback`` value here.

    Returns:
        The ``frames["main"]`` DataFrame if it satisfies the length guard.
        Returns None when ``frames`` is missing, not a dict, ``frames["main"]``
        is absent or not a DataFrame, or ``len(frames["main"]) < min_bars``.
    """
    if not isinstance(frames, dict):
        return None
    df = frames.get("main")
    if df is None or not isinstance(df, pd.DataFrame):
        return None
    if len(df) < min_bars:
        return None
    return df
