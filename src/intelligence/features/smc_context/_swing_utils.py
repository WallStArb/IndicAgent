"""Shared swing detection for smart money plugins.

Re-exports from the central intelligence utils module to maintain
backward-compatible import paths for SMC plugins.
"""

from __future__ import annotations

from src.intelligence.utils import find_peaks as find_swing_highs
from src.intelligence.utils import find_troughs as find_swing_lows

__all__ = ["find_swing_highs", "find_swing_lows"]
