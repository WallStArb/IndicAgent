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


def build_features_from_tiers(frames: dict[str, Any]) -> dict[str, Any]:
    """Merge all I1-I6 tier sub-dicts and inject top-level metadata.

    Standard entry point for I7 plugins building their local features dict.
    Centralises the tier merge so plugins don't repeat the 7-tier spread and
    the timeframe/symbol injections.
    """
    features: dict[str, Any] = {
        **(frames.get("i1") or {}),
        **(frames.get("i2") or {}),
        **(frames.get("i3") or {}),
        **(frames.get("i4") or {}),
        **(frames.get("i5") or {}),
        **(frames.get("smc") or {}),
        **(frames.get("i6") or {}),
    }
    features["timeframe"] = frames.get("timeframe") or frames.get("__timeframe__", "")
    # Inject top-level symbol only when the tier merge didn't already provide one.
    if not features.get("symbol"):
        features["symbol"] = frames.get("symbol") or frames.get("__symbol__", "")
    return features


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


# Guards against zero-ATR bars (market close / zero-range candles) in stop-correction
# error messages — prevents ZeroDivisionError and ensures the reported number is a
# dimensionless ATR ratio, not a raw price distance.
_ATR_EPSILON = 1e-8


def validate_stop_against_zone(
    *,
    zone_low: float,
    zone_high: float,
    stop_loss: float,
    direction: int,
    atr: float | None = None,
    plugin_name: str = "unknown",
) -> float:
    """Validate that stop loss is OUTSIDE the entry zone.

    Renaissance invariant: Every signal must have a non-zero trading window.
    Stops inside zones cause "stopped_at_entry" outcomes — dead-on-arrival signals.

    Correction uses ATR_STOP_FALLBACK_MULTIPLIER (2.0) for consistency with frame_trade().
    This is more conservative than 1.25x ATR and provides a wider buffer against noise.

    Args:
        zone_low: Entry zone low bound.
        zone_high: Entry zone high bound.
        stop_loss: Proposed stop loss price.
        direction: +1 for long, -1 for short.
        atr: Optional ATR value for auto-correction (recommended).
        plugin_name: Plugin name for error messages.

    Returns:
        Validated stop loss price (may be auto-corrected if ATR provided).

    Raises:
        ValueError: If stop is inside zone AND no ATR provided for correction,
                    or if correction would exceed 3.0 ATR (extreme misconfiguration).

    Examples:
        >>> validate_stop_against_zone(zone_low=100.0, zone_high=100.5, stop_loss=99.9, direction=1, atr=1.0)
        99.9  # Valid - stop below zone for long
        >>> validate_stop_against_zone(zone_low=100.0, zone_high=100.5, stop_loss=100.05, direction=1, atr=1.0)
        98.0  # Auto-corrected - stop was inside zone, moved 2.0 ATR below zone_low
    """
    from structlog import get_logger

    # ATR_STOP_FALLBACK_MULTIPLIER migrated to APR (feature.trade_framer.stop_fallback_atr,
    # migration 145). Correction here uses the seed value literal (2.0) — this function
    # is a defensive zone-correction utility, not a tunable behavioral parameter.
    # EPSILON_TOLERANCE is intentionally not APR-backed (numerical stability constant).
    from .trade_framer import EPSILON_TOLERANCE

    _logger = get_logger()
    epsilon = EPSILON_TOLERANCE
    correction_multiplier = (
        2.0  # stop_fallback_atr seed value (APR: feature.trade_framer.stop_fallback_atr)
    )

    if direction == 1:  # Long
        if stop_loss < zone_low - epsilon:
            return stop_loss  # Valid: stop below zone

        # Stop is at or above zone_low - INSIDE zone
        if atr is None:
            raise ValueError(
                f"{plugin_name}: stop_loss {stop_loss} >= zone_low {zone_low} "
                f"(inside entry zone [{zone_low}, {zone_high}]). "
                f"Provide ATR for auto-correction or fix stop placement logic."
            )

        # Measure how far original stop is inside zone (Renaissance: detect plugin bugs)
        original_inside_distance = stop_loss - zone_low

        # Auto-correct: place stop 2.0 ATR below zone_low (Renaissance: conservative buffer)
        corrected_stop = zone_low - (atr * correction_multiplier)

        # Guard against extreme misconfig: if original stop is >3×ATR inside zone, reject
        if original_inside_distance > atr * 3.0:
            raise ValueError(
                f"{plugin_name}: stop correction too extreme (stop {stop_loss:.2f} is "
                f"{original_inside_distance / max(atr, _ATR_EPSILON):.2f} ATR inside zone [{zone_low}, {zone_high}]). "
                f"Review plugin stop calculation logic."
            )

        _logger.debug(
            "stop_inside_zone_corrected",
            setup_type=plugin_name,
            original_stop=stop_loss,
            corrected_stop=corrected_stop,
            zone_low=zone_low,
            zone_high=zone_high,
            correction_atr_multiplier=correction_multiplier,
        )
        return corrected_stop

    else:  # Short (direction == -1)
        if stop_loss > zone_high + epsilon:
            return stop_loss  # Valid: stop above zone

        # Stop is at or below zone_high - INSIDE zone
        if atr is None:
            raise ValueError(
                f"{plugin_name}: stop_loss {stop_loss} <= zone_high {zone_high} "
                f"(inside entry zone [{zone_low}, {zone_high}]). "
                f"Provide ATR for auto-correction or fix stop placement logic."
            )

        # Measure how far original stop is inside zone (Renaissance: detect plugin bugs)
        original_inside_distance = zone_high - stop_loss

        # Auto-correct: place stop 2.0 ATR above zone_high (Renaissance: conservative buffer)
        corrected_stop = zone_high + (atr * correction_multiplier)

        # Guard against extreme misconfig: if original stop is >3×ATR inside zone, reject
        if original_inside_distance > atr * 3.0:
            raise ValueError(
                f"{plugin_name}: stop correction too extreme (stop {stop_loss:.2f} is "
                f"{original_inside_distance / max(atr, _ATR_EPSILON):.2f} ATR inside zone [{zone_low}, {zone_high}]). "
                f"Review plugin stop calculation logic."
            )

        _logger.debug(
            "stop_inside_zone_corrected",
            setup_type=plugin_name,
            original_stop=stop_loss,
            corrected_stop=corrected_stop,
            zone_low=zone_low,
            zone_high=zone_high,
            correction_atr_multiplier=correction_multiplier,
        )
        return corrected_stop


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

    **Signal Generation Invariant:** This function requires a fully-formed TradeFrame
    (stops, targets, zones already computed). Trade framing happens at I7 plugin
    detection time via `frame_trade()`, not at the service boundary. There is no
    "raw signal" intermediate state per Renaissance data quality principles.

    Calls validate_signal() at construction and raises ValueError on failure
    — invalid signals never enter the pipeline.

    Writes features_snapshot only when trade_frame.features is non-empty.

    Args:
        trade_frame: Populated TradeFrame from trade_framer.py.
        confidence:  Signal confidence value (use compose_confidence()).
        entry_type:  Entry type string (use EntryType enum values from signal_outcome.py).
        stop_loss:   Absolute stop loss price.
        target_1:    First target price.
        target_2:    Optional second target price.
        **signal_fields: Additional required fields forwarded to make_signal_from_frame:
            symbol, timeframe, timestamp, signal_type, setup_plugin,
            direction, regime_context, confluence_score, supporting_factors,
            invalidation_conditions. Optional: ttl_bars.
            ECL fields (Phase 123): ctf_score, ctf_confirmed, zone_friction_score,
            factor_scores, context_features — passed through automatically via **signal_fields.

    Returns:
        Validated signal dict with type "signal.v1".

    Raises:
        ValueError: If validate_signal() fails or trade_frame.viable is False.
    """
    from src.intelligence.trading.signal_schema import (  # noqa: PLC0415
        make_signal_from_frame,
        validate_signal,
    )

    # Delegate to make_signal_from_frame for full framing + validation
    signal = make_signal_from_frame(
        trade_frame,
        confidence=confidence,
        **signal_fields,
    )

    # Hard validation gate — raises ValueError on failure
    if not validate_signal(signal):
        raise ValueError(
            f"emit_signal: produced invalid signal for plugin "
            f"{signal_fields.get('setup_plugin', '?')}: missing required fields or invalid values"
        )

    return signal
