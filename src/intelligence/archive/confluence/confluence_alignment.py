"""Trend, structure, regime, and pattern scoring functions for cross-timeframe confluence."""

from __future__ import annotations

from typing import Any

from ..utils import clamp, is_num
from .confluence_weights import _sign, extract_trend_sign

# I2 event keys that indicate bullish momentum (+0.1 each)
_I2_BULLISH_EVENTS = frozenset(
    {
        "macd_cross_bullish",
        "rsi_crossed_30_up",
        "rsi_extreme_reversal",
        "stoch_cross_bullish",
        "stoch_oversold_reversal",
        "adx_trend_confirmed",
        "di_cross_bullish",
        "stoch_both_oversold",
    }
)

# I2 event keys that indicate bearish momentum (-0.1 each)
_I2_BEARISH_EVENTS = frozenset(
    {
        "macd_cross_bearish",
        "rsi_crossed_70_down",
        "stoch_cross_bearish",
        "stoch_overbought_reversal",
        "di_cross_bearish",
        "stoch_both_overbought",
    }
)


def score_trend_alignment(
    cur_trend: int,
    other_intel: dict[str, dict[str, Any]],
    weights: dict[str, float],
) -> float:
    """Recency-weighted fraction of other TFs agreeing with current direction."""
    if cur_trend == 0 or not other_intel:
        return 0.0

    total_weight = 0.0
    weighted_sum = 0.0
    for tf, intel in other_intel.items():
        w = weights.get(tf, 1.0)
        other_sign = extract_trend_sign(intel)
        total_weight += w
        if other_sign == cur_trend:
            weighted_sum += w
        elif other_sign == -cur_trend:
            weighted_sum -= w
        # other_sign == 0 → neutral, no contribution

    if total_weight == 0.0:
        return 0.0
    return cur_trend * (weighted_sum / total_weight)


def score_structure_alignment(
    features: dict[str, Any],
    other_intel: dict[str, dict[str, Any]],
    weights: dict[str, float],
) -> float:
    """Recency-weighted swing pattern agreement across timeframes."""
    cur_pattern = features.get("swing_pattern")
    if not is_num(cur_pattern) or cur_pattern == 0:
        return 0.0

    cur_sign = _sign(cur_pattern)
    total_weight = 0.0
    weighted_sum = 0.0
    for tf, intel in other_intel.items():
        other_pattern = intel.get("swing_pattern")
        if is_num(other_pattern) and other_pattern != 0:
            w = weights.get(tf, 1.0)
            total_weight += w
            if _sign(other_pattern) == cur_sign:
                weighted_sum += w

    if total_weight == 0.0:
        return 0.0
    return cur_sign * (weighted_sum / total_weight)


def score_regime_agreement(
    features: dict[str, Any],
    other_intel: dict[str, dict[str, Any]],
    weights: dict[str, float],
) -> float:
    """Recency-weighted volatility/momentum regime agreement."""
    scores: list[float] = []

    # Momentum bias comparison
    cur_mom = features.get("momentum_bias")
    if is_num(cur_mom) and cur_mom != 0:
        cur_sign = _sign(cur_mom)
        total_weight = 0.0
        weighted_sum = 0.0
        for tf, intel in other_intel.items():
            other_mom = intel.get("momentum_bias")
            if is_num(other_mom) and other_mom != 0:
                w = weights.get(tf, 1.0)
                total_weight += w
                if _sign(other_mom) == cur_sign:
                    weighted_sum += w
        if total_weight > 0.0:
            scores.append(cur_sign * (weighted_sum / total_weight))

    # Volatility regime comparison (expansion agreement)
    cur_vol_exp = features.get("vol_expansion")
    if is_num(cur_vol_exp):
        total_weight = 0.0
        weighted_sum = 0.0
        for tf, intel in other_intel.items():
            other_exp = intel.get("vol_expansion")
            if is_num(other_exp):
                w = weights.get(tf, 1.0)
                total_weight += w
                if (cur_vol_exp > 0) == (other_exp > 0):
                    weighted_sum += w
        if total_weight > 0.0 and scores:
            # Agreement is unsigned — only valid when a directional baseline exists
            scores.append(weighted_sum / total_weight)

    if not scores:
        return 0.0
    return sum(scores) / len(scores)


def score_pattern_confirmation(
    features: dict[str, Any], other_intel: dict[str, dict[str, Any]]
) -> float:
    """Check if current TF patterns are confirmed by higher TF context."""
    confirmations: list[float] = []

    # If current TF shows RSI divergence, check if higher TFs agree on direction
    for div_key, sign in [("rsi_div_bullish", 1), ("rsi_div_bearish", -1)]:
        v = features.get(div_key)
        if is_num(v) and v > 0:
            for intel in other_intel.values():
                other_trend = intel.get("trend_direction") or intel.get("trend_strength")
                if is_num(other_trend) and _sign(other_trend) == sign:
                    confirmations.append(float(sign))
                    break

    # BOS/CHoCH confirmation from higher TFs
    cur_bos = features.get("bos_direction")
    if is_num(cur_bos) and cur_bos != 0:
        bos_sign = _sign(cur_bos)
        for intel in other_intel.values():
            other_bos = intel.get("bos_direction")
            if is_num(other_bos) and _sign(other_bos) == bos_sign:
                confirmations.append(float(bos_sign))
                break

    if not confirmations:
        return 0.0
    return sum(confirmations) / len(confirmations)


def score_i2_events(features: dict[str, Any]) -> float:
    """Score I2 composite event signals on the current bar.

    Bullish events add +0.1, bearish events subtract 0.1.
    macd_negative_support_test adds +0.15 (bullish reversal confirmation).
    Result clamped to [-1.0, 1.0].
    """
    score = 0.0
    for key in _I2_BULLISH_EVENTS:
        v = features.get(key)
        if is_num(v) and v > 0:
            score += 0.1
    for key in _I2_BEARISH_EVENTS:
        v = features.get(key)
        if is_num(v) and v > 0:
            score -= 0.1
    v_neg = features.get("macd_negative_support_test")
    if is_num(v_neg) and v_neg > 0:
        score += 0.15
    return clamp(score)
