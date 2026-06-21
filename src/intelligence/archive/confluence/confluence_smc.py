"""SMC-specific scoring — BOS, FVG, and Order Block alignment for cross-timeframe confluence."""

from __future__ import annotations

from typing import Any

from src.intelligence.trading.atr_utils import get_atr

from ..utils import clamp, is_num
from .confluence_weights import _TF_MINUTES, _proximity_decay, _sign, extract_trend_sign


def score_smc_bos_alignment(
    features: dict[str, Any],
    other_intel: dict[str, dict[str, Any]],
    weights: dict[str, float],
) -> float:
    """BOS direction on current TF vs higher TF trend direction (recency-weighted)."""
    cur_bos = features.get("bos_direction")
    if not is_num(cur_bos) or cur_bos == 0:
        return 0.0

    bos_sign = _sign(cur_bos)
    total_weight = 0.0
    weighted_sum = 0.0
    for tf, intel in other_intel.items():
        other_sign = extract_trend_sign(intel)
        if other_sign != 0:
            w = weights.get(tf, 1.0)
            total_weight += w
            if other_sign == bos_sign:
                weighted_sum += w
            else:
                weighted_sum -= w

    if total_weight == 0.0:
        return 0.0
    return clamp(bos_sign * (weighted_sum / total_weight))


def score_fvg_alignment(
    features: dict[str, Any],
    other_intel: dict[str, dict[str, Any]],
    current_tf: str,
    cur_trend: int,
) -> tuple[float, dict[str, float]]:
    """Direction-weighted FVG proximity score across higher TFs.

    Only higher TFs are used (lower TFs are too ephemeral).
    TF authority weight = _TF_MINUTES value, normalized across contributing TFs.
    Returns (aggregate_score, per_tf_contributions) for full auditability.
    """
    cur_price = features.get("close") or 0.0
    atr = get_atr(features)
    if not atr:
        return 0.0, {}
    if cur_trend == 0:
        return 0.0, {}

    cur_tf_min = _TF_MINUTES.get(current_tf, 0)
    total_weight = 0.0
    weighted_sum = 0.0
    contributions: dict[str, float] = {}

    for tf, intel in other_intel.items():
        tf_min = _TF_MINUTES.get(tf, 0)
        if tf_min <= cur_tf_min:
            continue  # Only higher TFs
        fvg_type = intel.get("fvg_type") or 0.0
        fvg_top = intel.get("fvg_top") or 0.0
        fvg_bottom = intel.get("fvg_bottom") or 0.0
        if not is_num(fvg_type) or fvg_type == 0.0 or fvg_top <= 0 or fvg_bottom <= 0:
            continue
        direction_match = 1.0 if int(fvg_type) == cur_trend else -1.0
        decay = _proximity_decay(cur_price, fvg_top, fvg_bottom, atr)
        if decay <= 0:
            continue
        w = float(tf_min)
        total_weight += w
        contrib = direction_match * decay
        weighted_sum += w * contrib
        contributions[tf] = round(contrib, 4)

    if total_weight == 0.0:
        return 0.0, {}
    return round(clamp(weighted_sum / total_weight), 4), contributions


def score_ob_alignment(
    features: dict[str, Any],
    other_intel: dict[str, dict[str, Any]],
    current_tf: str,
    cur_trend: int,
) -> tuple[float, dict[str, float]]:
    """Direction-weighted Order Block proximity score across higher TFs.

    OBs are already filtered to unmitigated-only by order_blocks.py.
    Same formula as FVG — Phase 46 calibration may diverge weights if data supports it.
    Returns (aggregate_score, per_tf_contributions) for full auditability.
    """
    cur_price = features.get("close") or 0.0
    atr = get_atr(features)
    if not atr:
        return 0.0, {}
    if cur_trend == 0:
        return 0.0, {}

    cur_tf_min = _TF_MINUTES.get(current_tf, 0)
    total_weight = 0.0
    weighted_sum = 0.0
    contributions: dict[str, float] = {}

    for tf, intel in other_intel.items():
        tf_min = _TF_MINUTES.get(tf, 0)
        if tf_min <= cur_tf_min:
            continue  # Only higher TFs
        ob_type = intel.get("ob_type") or 0.0
        ob_top = intel.get("ob_top") or 0.0
        ob_bottom = intel.get("ob_bottom") or 0.0
        if not is_num(ob_type) or ob_type == 0.0 or ob_top <= 0 or ob_bottom <= 0:
            continue
        direction_match = 1.0 if int(ob_type) == cur_trend else -1.0
        decay = _proximity_decay(cur_price, ob_top, ob_bottom, atr)
        if decay <= 0:
            continue
        w = float(tf_min)
        total_weight += w
        contrib = direction_match * decay
        weighted_sum += w * contrib
        contributions[tf] = round(contrib, 4)

    if total_weight == 0.0:
        return 0.0, {}
    return round(clamp(weighted_sum / total_weight), 4), contributions
