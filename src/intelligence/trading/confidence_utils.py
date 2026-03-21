"""System-wide confidence contract for I7 trading plugins.

Per D-12/D-13/D-14: All I7 plugins route their final confidence value through
compose_confidence(). Zero inline min()/max() clamping in plugin bodies.

The contract: [CONF_FLOOR, CONF_CEIL] = [0.10, 0.95].
Rounding: 4 decimal places for consistent ML feature representation.
"""

from __future__ import annotations

CONF_FLOOR: float = 0.10
"""Minimum allowed confidence for any I7 signal."""

CONF_CEIL: float = 0.95
"""Maximum allowed confidence for any I7 signal."""


def compose_confidence(raw: float) -> float:
    """Clamp raw confidence to the system contract [CONF_FLOOR, CONF_CEIL].

    All I7 plugins must route through this function before emitting a signal.
    This eliminates inline clamping patterns (min(0.95, max(0.10, x))) and
    ensures the system-wide contract is enforced at a single point.

    Args:
        raw: Raw confidence value (any float, including out-of-range).

    Returns:
        Float in [CONF_FLOOR, CONF_CEIL] rounded to 4 decimal places.
    """
    return round(max(CONF_FLOOR, min(CONF_CEIL, raw)), 4)
