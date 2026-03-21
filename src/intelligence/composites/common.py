"""Re-export shim — DO NOT add new logic here.

All implementations live in src/intelligence/utils/common.py (D-23/D-24/D-25).
This file exists only for backward compatibility.  All I2 composites now import
directly from ..utils.common; this shim covers any external code that still
points here.
"""

from __future__ import annotations

from ..utils.common import (  # noqa: F401
    crossover_detect,
    is_num,
    threshold_cross,
    track_bars_ago,
)

__all__ = ["crossover_detect", "is_num", "threshold_cross", "track_bars_ago"]
