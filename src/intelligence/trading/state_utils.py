"""State tracking utilities for I7 trading plugins."""

from __future__ import annotations

from typing import Any

# Minimum active-condition bars between fires of the same event_id.
# Prevents re-fire on the same persistent upstream event while allowing
# re-fire when a genuinely new occurrence of the same structural event appears.
_DEDUP_MIN_BARS: int = 20

_config_service: Any | None = None


def set_config_service(config: Any) -> None:
    global _config_service
    _config_service = config


def get_dedup_min_bars() -> int:
    if _config_service is not None:
        return int(_config_service.get_sync("feature.state.dedup_min_bars", _DEDUP_MIN_BARS))
    return _DEDUP_MIN_BARS


def track_consecutive_state(
    frames: dict[str, Any],
    state: dict[str, Any],
    state_key: str,
    current_value: int,
    value_field_name: str = "value",
) -> tuple[int, int]:
    """Track consecutive occurrences of a state value.

    Increments counter if value matches previous, resets to 1 if changed.
    Returns the (current_value, count) tuple.

    Args:
        frames: Frame dict (currently unused, kept for API consistency with reset_consecutive_state)
        state: Plugin's internal state dict (e.g., self._state)
        state_key: Unique key for this (symbol, timeframe) combo
        current_value: Current value to track (e.g., direction sign)
        value_field_name: Field name in state dict (default "value")

    Returns:
        Tuple of (current_value, count) where count is consecutive bars

    Example:
        # In plugin compute_full():
        symbol = frames.get("__symbol__", "_")
        tf = frames.get("__timeframe__", "_")
        state_key = f"{symbol}_{tf}"
        direction = 1 if condition else -1

        direction, count = track_consecutive_state(
            frames, self._state, state_key, direction, "dir"
        )

        if count < MIN_BARS:
            return no_signal()

    Common patterns:
    - Divergence tracking: value_field_name="div_sign"
    - Direction tracking: value_field_name="dir"
    - Sign tracking: value_field_name="sign"
    """
    # Retrieve or initialize state entry
    existing = state.get(state_key, {value_field_name: 0, "count": 0})

    # Check if value matches previous
    if existing[value_field_name] == current_value:
        count = existing["count"] + 1
    else:
        # Value changed: reset counter
        count = 1

    # Update and store state
    state_entry = {value_field_name: current_value, "count": count}
    state[state_key] = state_entry

    return current_value, count


def onset_guard(state: dict, state_key: str, condition_active: bool) -> bool:
    """Return True only on a False→True transition of condition_active.

    Rearmed automatically when condition_active goes False.

    PLACEMENT: call AFTER all downstream gates (ATR, frame_trade, confidence).
    This ensures state is committed only when a signal will actually be emitted —
    a transient infrastructure failure (ATR=None, frame not viable) cannot silently
    consume the onset without producing a signal.
    """
    entry = state.setdefault(state_key, {})
    was_active = entry.get("onset_active", False)
    entry["onset_active"] = condition_active
    return condition_active and not was_active


def deduplicate_event(
    state: dict,
    state_key: str,
    event_id: Any,
    *,
    min_bars_between_fires: int | None = None,
) -> bool:
    """Return True only when event_id differs from last fired, or min_bars have elapsed.

    Counts active-condition calls (not total bars). A new event_id always fires immediately.
    The same event_id re-fires after min_bars_between_fires active-condition calls, allowing
    re-occurrence of the same structural event (e.g., price sweeping the same level twice).

    PLACEMENT: call AFTER all downstream gates, immediately before make_signal_from_frame.
    """
    if min_bars_between_fires is None:
        min_bars_between_fires = get_dedup_min_bars()
    entry = state.setdefault(state_key, {})
    entry["call_count"] = entry.get("call_count", 0) + 1
    call_count = entry["call_count"]

    last_id = entry.get("last_event_id")
    last_fire = entry.get("last_fire_call", call_count - min_bars_between_fires - 1)

    if event_id == last_id and (call_count - last_fire) < min_bars_between_fires:
        return False

    entry["last_event_id"] = event_id
    entry["last_fire_call"] = call_count
    return True


def reset_consecutive_state(
    frames: dict[str, Any],
    state: dict[str, Any],
    state_key: str | None = None,
) -> None:
    """Reset consecutive state counter for a key.

    Called when a condition invalidates the accumulated state
    (e.g., disagreement between signals, zero value).

    Args:
        frames: Frame dict - used ONLY when state_key is None to derive f"{symbol}_{tf}"
        state: Plugin's internal state dict (e.g., self._state)
        state_key: Specific key to reset, or None to derive from frames using symbol/timeframe
    """
    if state_key is None:
        symbol = frames.get("__symbol__", "_")
        tf = frames.get("__timeframe__", "_")
        state_key = f"{symbol}_{tf}"

    state.pop(state_key, None)
