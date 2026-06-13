"""ATR null-guard wrapper for I7 trading plugins.

Per D-05/D-06: ATR is computed once in I1 (atr_14 field). I7 plugins consume
it — they do NOT recompute it from high/low. This module provides a single
guarded accessor so that null/zero/negative checks are centralised.

Per D-07: No numpy, no rolling computation. One source of truth.
"""

from __future__ import annotations

from typing import Any

from src.core.service_utils import get_tick_size


def get_atr(features: dict[str, Any]) -> float | None:
    """Return atr_14 from I1 features dict, or None if unavailable/invalid.

    Returns None when:
    - "atr_14" key is missing
    - value is None
    - value cannot be cast to float
    - value is <= 0 (zero or negative ATR is nonsensical)

    Args:
        features: The features dict from frames["features"] or similar.

    Returns:
        Positive float ATR value, or None.
    """
    return get_atr_with_period(features, period=14)


def get_atr_with_period(features: dict[str, Any], period: int = 14) -> float | None:
    """Return ATR for specific period (14 or 20) from I1 features.

    Returns None when:
    - Requested period field is missing
    - value is None
    - value cannot be cast to float
    - value is <= 0

    Args:
        features: I1 features dict (frames["i1"] or similar)
        period: ATR period to retrieve (must be 14 or 20)

    Returns:
        Positive float ATR value, or None.
    """
    if period not in (14, 20):
        raise ValueError(f"Unsupported ATR period: {period}. Must be 14 or 20.")

    field = f"atr_{period}"
    val = features.get(field)
    if val is None:
        return None
    try:
        f = float(val)
    except (TypeError, ValueError):
        return None
    return f if f > 0 else None


def get_atr_with_floor(features: dict[str, Any], symbol: str) -> float | None:
    """Return ATR floored to the instrument's minimum tick size.

    Returns None when ATR is None (same as get_atr) OR when ATR is below
    the instrument's minimum tick. A sub-tick ATR cannot produce a meaningful
    stop distance, so the calling plugin should return no_signal().

    This prevents silent emission-gate ValueError spam from quiet bars (near-zero
    ATR during off-hours) while keeping error counts meaningful for real failures.
    """
    atr = get_atr(features)
    if atr is None:
        return None
    min_tick = get_tick_size(symbol)
    return atr if atr >= min_tick else None


def get_atr_with_floor_from_frames(frames: dict[str, Any], period: int = 14) -> float | None:
    """Get tick-floored ATR for specific period from the plugin_input frames dict.

    Reads symbol from frames["symbol"] (set by executor) and ATR from
    frames["i1"]["atr_{period}"]. Call this in compute_full() instead of
    get_atr_with_floor() to correctly apply the instrument tick-size floor.

    Args:
        frames: plugin_input dict from compute_full()
        period: ATR period to retrieve (14 or 20)

    Returns None when ATR is None or below the instrument's minimum tick.
    """
    if period not in (14, 20):
        raise ValueError(f"Unsupported ATR period: {period}. Must be 14 or 20.")

    symbol = frames.get("symbol") or frames.get("__symbol__", "")
    i1 = frames.get("i1") or {}
    atr = get_atr_with_period(i1, period)
    if atr is None:
        return None

    min_tick = get_tick_size(symbol)
    return atr if atr >= min_tick else None


def get_atr_valid(features: dict[str, Any]) -> float:
    """Strict ATR accessor for I7 plugin use. Returns positive float ATR value.

    Raises ValueError when ATR is None, zero, or negative. Use ONLY in I7
    compute_full() where no_signal() is the correct failure contract. For I6,
    use the early-return pattern (if not atr: return {}) instead — I6 must
    gracefully degrade, not raise.
    """
    atr = get_atr(features)
    if not atr:
        raise ValueError(f"ATR unavailable or non-positive: {features.get('atr_14')!r}")
    return atr
