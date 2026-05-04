"""Shared utilities for AI agent prompt builders.

Single source of truth for formatting helpers, label maps, and constants
used across all prompt modules (skeptic, narrative, future risk).
"""

from __future__ import annotations

from typing import Any

DIRECTION_LABELS: dict[int, str] = {1: "LONG", -1: "SHORT", 0: "FLAT"}
REGIME_LABELS: dict[int, str] = {0: "Ranging", 1: "Trending Up", 2: "Trending Down"}


def fmt(val: Any, spec: str) -> str:
    """Format a numeric value with the given format spec, or return N/A."""
    if isinstance(val, (int, float)):
        return format(val, spec)
    return "N/A"
