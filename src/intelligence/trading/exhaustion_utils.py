"""Shared exhaustion-awareness helpers for I7 trading plugins.

Two patterns wired into I7 setups during Phase 24:
  - Exhaustion boost: confirms sweep/reclaim setups when momentum is exhausted
    in the signal direction (decelerating move validates the stop-run thesis).
  - Exhaustion guard: penalises trend-chasing setups when momentum is exhausted
    and has persisted for multiple bars (avoid entering a tired move).
"""
from __future__ import annotations

from typing import Any


def apply_exhaustion_boost(
    features: dict[str, Any],
    direction: int,
    confidence: float,
    supporting: list[str],
) -> tuple[float, list[str]]:
    """Apply +0.10 boost when sweep-aligned exhaustion is detected.

    Parameters
    ----------
    features:   frames["features"] dict
    direction:  +1 long, -1 short
    confidence: current confidence score (mutated copy returned)
    supporting: supporting factors list (mutated copy returned)
    """
    exhaustion_score = float(features.get("exhaustion_score", 0.0))
    exhaustion_side = features.get("exhaustion_side", "none")
    if exhaustion_score > 0.6 and (
        (direction == 1 and exhaustion_side == "bull")
        or (direction == -1 and exhaustion_side == "bear")
    ):
        confidence += 0.10
        supporting.append("exhaustion_sweep_boost")
    return confidence, supporting


def apply_exhaustion_guard(
    features: dict[str, Any],
    confidence: float,
    supporting: list[str],
) -> tuple[float, list[str]]:
    """Apply -0.15 penalty when chasing a sustained exhausted move.

    Parameters
    ----------
    features:   frames["features"] dict
    confidence: current confidence score (mutated copy returned)
    supporting: supporting factors list (mutated copy returned)
    """
    exhaustion_score = float(features.get("exhaustion_score", 0.0))
    exhaustion_bars = float(features.get("exhaustion_bars", 0.0))
    if exhaustion_score > 0.7 and exhaustion_bars >= 3:
        confidence -= 0.15
        supporting.append("exhaustion_guard_penalty")
    return confidence, supporting
