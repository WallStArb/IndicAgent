"""State tracking utilities for I7 trading plugins.

Shared consecutive state counter logic for plugins that need to track
how many bars a condition has held true.
"""

from __future__ import annotations

from typing import Any


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
