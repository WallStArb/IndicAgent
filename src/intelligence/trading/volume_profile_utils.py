"""Volume profile utility functions for I7 trading plugins.

Shared rejection detection logic for POC and HVN signals.
Preserves signal identity (Renaissance principle) while eliminating duplication.
"""

from __future__ import annotations

from typing import Any


# Minimum divergence confidence to count as reversal
_DIV_THRESHOLD = 0.3

# Stochastic thresholds
_STOCH_OVERSOLD = 30.0
_STOCH_OVERBOUGHT = 70.0


def check_reversal_gate(
    features: dict[str, Any],
    direction: int,
) -> tuple[bool, float]:
    """Check momentum reversal gate for volume profile rejection signals.

    Evaluates whether RSI divergence or stochastic extremes confirm a reversal
    in the specified direction.

    Args:
        features: Feature dict from frame
        direction: 1 for long (below VP level), -1 for short (above VP level)

    Returns:
        Tuple of (reversal_ok, reversal_strength)
        - reversal_ok: True if reversal conditions met
        - reversal_strength: Float 0-1 indicating reversal conviction

    Long reversal (direction=1):
        - rsi_div_bullish > 0.3 OR stoch_k < 30
        - Strength = max(rsi_div_bullish, (30 - stoch_k) / 30)

    Short reversal (direction=-1):
        - rsi_div_bearish > 0.3 OR stoch_k > 70
        - Strength = max(rsi_div_bearish, (stoch_k - 70) / 30)
    """
    rsi_div_bullish = float(features.get("rsi_div_bullish", 0.0))
    rsi_div_bearish = float(features.get("rsi_div_bearish", 0.0))
    stoch_k = float(features.get("stoch_k_14_3", 50.0))

    if direction == 1:
        rsi_div_ok = rsi_div_bullish > _DIV_THRESHOLD
        stoch_ok = stoch_k < _STOCH_OVERSOLD
        reversal_ok = rsi_div_ok or stoch_ok
        reversal_strength = max(
            rsi_div_bullish,
            (30.0 - stoch_k) / 30.0 if stoch_k < _STOCH_OVERSOLD else 0.0,
        )
    else:  # direction == -1
        rsi_div_ok = rsi_div_bearish > _DIV_THRESHOLD
        stoch_ok = stoch_k > _STOCH_OVERBOUGHT
        reversal_ok = rsi_div_ok or stoch_ok
        reversal_strength = max(
            rsi_div_bearish,
            (stoch_k - 70.0) / 30.0 if stoch_k > _STOCH_OVERBOUGHT else 0.0,
        )

    return reversal_ok, min(1.0, max(0.0, reversal_strength))


def format_reversal_supporting_factors(
    features: dict[str, Any],
    direction: int,
    rsi_div_ok: bool,
    stoch_ok: bool,
) -> list[str]:
    """Format supporting factors for reversal conditions.

    Args:
        features: Feature dict from frame
        direction: 1 for long, -1 for short
        rsi_div_ok: Whether RSI divergence confirmed
        stoch_ok: Whether stochastic extreme confirmed

    Returns:
        List of supporting factor strings
    """
    stoch_k = float(features.get("stoch_k_14_3", 50.0))
    factors: list[str] = []

    if rsi_div_ok:
        div_label = "rsi_div_bullish" if direction == 1 else "rsi_div_bearish"
        factors.append(div_label)

    if stoch_ok:
        factors.append(f"stoch_extreme={stoch_k:.1f}")

    return factors
