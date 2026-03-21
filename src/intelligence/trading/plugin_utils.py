"""Shared utility functions for I7 trading plugins.

Per D-01/D-02: module-level functions, NOT a BaseI7Plugin class.
Plugins import what they need; no inheritance required.
"""

from __future__ import annotations

from typing import Any

import numpy as np


def no_signal() -> dict[str, Any]:
    """Return the canonical no-signal dict.

    All I7 plugins must return this when their gate conditions are not met.
    Returns a new dict on every call — callers may safely mutate the result.
    """
    return {"signal_type": "none", "direction": 0, "confidence": 0.0}


def extract_ohlcv(
    frames: dict[str, Any],
    min_bars: int,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray] | None:
    """Extract (open, high, low, close) arrays from frames["main"].

    Returns None when:
    - frames["main"] is missing or None
    - len(df) < min_bars

    Returns:
        4-tuple of float64 ndarrays (open, high, low, close) or None.
    """
    df = frames.get("main")
    if df is None or len(df) < min_bars:
        return None
    return (
        df["open"].to_numpy(dtype=float),
        df["high"].to_numpy(dtype=float),
        df["low"].to_numpy(dtype=float),
        df["close"].to_numpy(dtype=float),
    )


def default_compute_next(plugin: Any, windows: dict[str, Any]) -> dict[str, Any]:
    """Default compute_next delegation — calls plugin.compute_full(windows).

    Used when a plugin's compute_next is identical to compute_full (no
    incremental optimisation needed).
    """
    return plugin.compute_full(windows)


def signal_type_for_direction(prefix: str, direction: int) -> str:
    """Return '{prefix}_long' or '{prefix}_short' based on direction.

    Args:
        prefix:    Setup name prefix (e.g. "trend", "fvg_fill").
        direction: +1 for long, -1 for short.
    """
    return f"{prefix}_long" if direction == 1 else f"{prefix}_short"
