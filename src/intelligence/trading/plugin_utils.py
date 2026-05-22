"""Shared utility functions for I7 trading plugins.

Per D-01/D-02: module-level functions, NOT a BaseI7Plugin class.
Plugins import what they need; no inheritance required.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import numpy as np

if TYPE_CHECKING:
    from src.intelligence.trading.trade_framer import TradeFrame


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


def _fval(features: dict[str, Any], key: str, default: float = 0.0) -> float:
    """Null-safe float extraction from a features dict."""
    v = features.get(key)
    if v is None:
        return default
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def emit_signal(
    trade_frame: TradeFrame,
    *,
    confidence: float,
    entry_type: str,
    stop_loss: float,
    target_1: float,
    target_2: float | None = None,
    **signal_fields: Any,
) -> dict[str, Any]:
    """Build and validate a signal dict from a TradeFrame.

    Calls validate_signal() at construction and raises ValueError on failure
    — invalid signals never enter the pipeline.

    Writes features_snapshot only when trade_frame.features is non-empty.

    Args:
        trade_frame: Populated TradeFrame from trade_framer.py.
        confidence:  Signal confidence value (use compose_confidence()).
        entry_type:  Entry type string ("at_close", "at_pullback", etc.).
        stop_loss:   Absolute stop loss price.
        target_1:    First target price.
        target_2:    Optional second target price.
        **signal_fields: Additional required fields forwarded to make_signal_from_frame:
            symbol, timeframe, timestamp, signal_type, setup_plugin,
            direction, regime_context, confluence_score, supporting_factors,
            invalidation_conditions. Optional: ttl_bars.

    Returns:
        Validated signal dict with type "signal.v1".

    Raises:
        ValueError: If validate_signal() fails or trade_frame.viable is False.
    """
    from src.intelligence.trading.signal_schema import (  # noqa: PLC0415
        make_signal_from_frame,
        validate_signal,
    )

    # features_snapshot: only capture when non-empty (avoid polluting signal with empty dicts)
    raw_features = getattr(trade_frame, "features", {}) or {}
    features_snapshot = raw_features if raw_features else None

    # Delegate to make_signal_from_frame for full framing + validation
    signal = make_signal_from_frame(
        trade_frame,
        confidence=confidence,
        features_snapshot=features_snapshot,
        **signal_fields,
    )

    # Hard validation gate — raises ValueError on failure
    if not validate_signal(signal):
        raise ValueError(
            f"emit_signal: produced invalid signal for plugin "
            f"{signal_fields.get('setup_plugin', '?')}: missing required fields or invalid values"
        )

    return signal
