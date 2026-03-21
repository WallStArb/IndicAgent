"""ATR null-guard wrapper for I7 trading plugins.

Per D-05/D-06: ATR is computed once in I1 (atr_14 field). I7 plugins consume
it — they do NOT recompute it from high/low. This module provides a single
guarded accessor so that null/zero/negative checks are centralised.

Per D-07: No numpy, no rolling computation. One source of truth.
"""

from __future__ import annotations

from typing import Any


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
    val = features.get("atr_14")
    if val is None:
        return None
    try:
        f = float(val)
    except (TypeError, ValueError):
        return None
    return f if f > 0 else None
