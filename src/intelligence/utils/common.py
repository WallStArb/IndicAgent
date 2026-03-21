"""Tier-agnostic numeric utilities for intelligence plugins.

Promoted from composites/common.py for tier-agnostic access (D-23/D-24/D-25).
These functions are usable by I2, I7, or any other tier that needs basic numeric
helpers without importing from a composites-specific module.

Note on is_num:
    The is_num here is isinstance-based (int or float).
    See src/intelligence/utils.py for the stricter math.isfinite version.
    Do NOT merge them — they have different semantics. The isinstance version
    allows NaN and Inf; the isfinite version does not. I2 composites rely on
    the isinstance version's behaviour.
"""

from __future__ import annotations

from typing import Any


def is_num(x: Any) -> bool:
    """Check if x is a numeric type (int or float)."""
    return isinstance(x, int | float)


def crossover_detect(prev_a: Any, now_a: Any, prev_b: Any, now_b: Any) -> tuple[int, int]:
    """Detect bullish/bearish crossover between two series.

    Returns:
        (bullish_cross, bearish_cross) where each is 0 or 1
    """
    if not all(is_num(v) for v in [prev_a, now_a, prev_b, now_b]):
        return 0, 0
    bullish = 1 if prev_a <= prev_b and now_a > now_b else 0
    bearish = 1 if prev_a >= prev_b and now_a < now_b else 0
    return bullish, bearish


def threshold_cross(prev: Any, now: Any, threshold: float, direction: str) -> int:
    """Detect threshold crossing: prev < threshold <= now (up) or prev > threshold >= now (down).

    Args:
        prev: Previous value
        now: Current value
        threshold: Threshold value to cross
        direction: "up" or "down"

    Returns:
        1 if crossed in direction, 0 otherwise
    """
    if not is_num(prev) or not is_num(now):
        return 0
    if direction == "up":
        return 1 if prev < threshold <= now else 0
    else:
        return 1 if prev > threshold >= now else 0


def track_bars_ago(state: dict, key: str, event_occurred: bool, max_bars: int = 999) -> float:
    """Track bars since last event occurrence. Updates state in-place.

    Args:
        state: Plugin state dictionary
        key: State key to track
        event_occurred: Whether event occurred this bar
        max_bars: Maximum bars to count (default 999)

    Returns:
        Current bars ago value (0 if event just occurred)
    """
    if event_occurred:
        state[key] = 0.0
    else:
        state[key] = min(state.get(key, max_bars) + 1, max_bars)
    return state[key]
