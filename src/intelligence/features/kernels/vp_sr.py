"""Volume profile and structure kernels: session VP, rolling POC, S/R, swing, trend, swing
momentum, Fibonacci zones and session levels (D-25).

The helpers are the ones `feature_factory` used to hold, moved unchanged. A stateless kernel
slices the same causal window the batch loop sliced, `[max(0, i - lookback + 1) : i + 1]`, and
reads the loop's `atr_val` (the ATR padded series at row i). The two cache-backed kernels replay a
fresh `FeatureCache` with the loop's update calls from row 1, so they are path dependent.

A helper that returns None for a key emits NaN in that key's column and 1.0 in its
`_<key>_is_none` column, so a caller can tell None from a non-finite float (`_guard` maps the two
differently).
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Any

import numpy as np

from src.intelligence.features.contract.registry import Kernel
from src.intelligence.features.kernels._cache_state import (
    FeatureCache,
    _compute_session_value_area,
    _compute_session_vp_profile,
)
from src.intelligence.features.kernels._primitives import (
    ATR_RAW_PADDED,
    KeyGroup,
    _is_valid_atr,
    constant_tf,
    window_start,
)
from src.intelligence.utils import clamp, find_peaks, find_troughs
from src.intelligence.utils.gradient_utils import linear_ramp

if TYPE_CHECKING:
    from src.intelligence.feature_factory import FeatureFactoryConfig


# ---------------------------------------------------------------------------
# Session Volume Profile — ATR-normalized output derivation (Phase 163 Plan 02)
# ---------------------------------------------------------------------------

# tf == '1d' neutral defaults for the 14 VP FeatureVector fields: a single
# daily bar has no intraday distribution, so session-anchored VP is not
# meaningful. poc_dist_atr/va_position keep the pre-existing 0.0/0.5 neutral
# convention (matches the original 2-field tf=='1d' branch); the 12 new
# fields have no legacy default to preserve, so they fall back to None except
# the two already-0/1 flags (price_in_value_area, in_lvn).
_NEUTRAL_VP_EXTRA: dict[str, float | None] = {
    "poc_dist_atr": 0.0,
    "va_position": 0.5,
    "nearest_hvn_above_dist_atr": None,
    "nearest_hvn_below_dist_atr": None,
    "nearest_lvn_above_dist_atr": None,
    "nearest_lvn_below_dist_atr": None,
    "price_in_value_area": 0.0,
    "in_lvn": 0.0,
    "va_width_atr": None,
    "distance_to_vah_atr": None,
    "distance_to_val_atr": None,
    "nearest_hvn_dist_atr": None,
    "poc_rolling_dist_atr": None,
    "poc_session_rolling_divergence_atr": None,
}


def _rolling_poc_price(
    highs: np.ndarray,
    lows: np.ndarray,
    closes: np.ndarray,
    volumes: np.ndarray,
    config: FeatureFactoryConfig,
) -> float | None:
    """Stateless rolling-window POC (D-18), computed over the given bar slice.

    The caller passes the last config.session_vp_rolling_window bars (inclusive
    of the current bar). Intermediate value only -- never persisted as a raw
    column (D-16); Plan 02's compute()/compute_batch() call sites use it solely
    to derive poc_rolling_dist_atr/poc_session_rolling_divergence_atr. Reuses
    the same profile/value-area helpers as the session-anchored track
    (FeatureCache.update_session_vp) for identical bucket/tie-break semantics.
    Returns None on degenerate input (zero price range or zero volume).

    CR-02 (163-REVIEW.md): this function trusts the caller to actually supply
    session_vp_rolling_window bars. In backfill that's true (unbounded history).
    In the live pipeline the caller's bars array is bounded by
    FeatureVectorPipeline's BarHistory(maxlen=200), so live poc_rolling_dist_atr/
    poc_session_rolling_divergence_atr are computed over at most 200 bars
    regardless of this key's configured value -- a real train/serve skew, not a
    bug in this function itself. See migration 256's corrected APR description.
    """
    if len(highs) == 0:
        return None
    profile = _compute_session_vp_profile(highs, lows, closes, volumes, config.session_vp_n_buckets)
    if profile is None:
        return None
    vol_hist, bucket_prices, _bucket_size, _price_min = profile
    if float(vol_hist.sum()) == 0:
        return None
    poc_price, _vah, _val = _compute_session_value_area(
        vol_hist, bucket_prices, config.session_vp_value_area_pct
    )
    return poc_price


def _derive_session_vp(
    cache: FeatureCache,
    close_: float,
    atr_val: float,
    poc_price_rolling: float | None,
    config: FeatureFactoryConfig,
) -> dict[str, float | None]:
    """Derive the 14 ATR-normalized/bounded VP FeatureVector fields.

    Reads FeatureCache's raw session levels (set by update_session_vp(), called
    once per bar by the caller before compute()/inside compute_batch()'s loop)
    plus the compute-path atr_val -- no raw price level is ever returned or
    persisted (D-16). poc_dist_atr/va_position fall back to the legacy neutral
    defaults (0.0/0.5) when session state or atr_val is unavailable (cold
    start / degenerate histogram / atr_val invalid per _is_valid_atr, i.e.
    <= 0 or below config.atr_normalization_min_pct of close_ -- todo 237),
    matching the pre-existing tf=='1d' convention. The 12 new fields fall
    back to None in the same conditions -- they are brand-new columns with
    no legacy default to preserve. price_in_value_area/in_lvn are already-bounded 0/1 flags on the
    cache and need no ATR normalization.
    """
    atr_valid = _is_valid_atr(atr_val, close_, config.atr_normalization_min_pct)

    poc = cache._sess_poc
    vah = cache._sess_vah
    val = cache._sess_val

    poc_dist_atr = 0.0 if poc is None or not atr_valid else (close_ - poc) / atr_val

    if val is None or vah is None or (vah - val) == 0:
        va_position = 0.5
    else:
        va_position = float(np.clip((close_ - val) / (vah - val), 0.0, 1.0))

    def _above(level: float | None) -> float | None:
        return None if level is None or not atr_valid else (level - close_) / atr_val

    def _below(level: float | None) -> float | None:
        return None if level is None or not atr_valid else (close_ - level) / atr_val

    nearest_hvn_above_dist_atr = _above(cache._sess_hvn_above)
    nearest_hvn_below_dist_atr = _below(cache._sess_hvn_below)
    nearest_lvn_above_dist_atr = _above(cache._sess_lvn_above)
    nearest_lvn_below_dist_atr = _below(cache._sess_lvn_below)

    nearest_hvn_dist_atr = (
        None
        if cache._sess_hvn_nearest is None or not atr_valid
        else abs(close_ - cache._sess_hvn_nearest) / atr_val
    )

    # D-17: va_width_atr == distance_to_vah_atr + distance_to_val_atr exactly
    # -- documented collinearity kept deliberately (both are directly
    # interpretable structural distances in their own right).
    va_width_atr = None if vah is None or val is None or not atr_valid else (vah - val) / atr_val
    distance_to_vah_atr = _above(vah)
    distance_to_val_atr = _below(val)

    price_in_value_area = cache._sess_price_in_va
    in_lvn = cache._sess_in_lvn

    if poc_price_rolling is None or not atr_valid:
        poc_rolling_dist_atr: float | None = None
        poc_session_rolling_divergence_atr: float | None = None
    else:
        poc_rolling_dist_atr = (close_ - poc_price_rolling) / atr_val
        # D-18: poc_session_rolling_divergence_atr == poc_rolling_dist_atr -
        # poc_dist_atr exactly -- documented collinearity kept deliberately.
        poc_session_rolling_divergence_atr = (
            None if poc is None else (poc - poc_price_rolling) / atr_val
        )

    return {
        "poc_dist_atr": poc_dist_atr,
        "va_position": va_position,
        "nearest_hvn_above_dist_atr": nearest_hvn_above_dist_atr,
        "nearest_hvn_below_dist_atr": nearest_hvn_below_dist_atr,
        "nearest_lvn_above_dist_atr": nearest_lvn_above_dist_atr,
        "nearest_lvn_below_dist_atr": nearest_lvn_below_dist_atr,
        "nearest_hvn_dist_atr": nearest_hvn_dist_atr,
        "va_width_atr": va_width_atr,
        "distance_to_vah_atr": distance_to_vah_atr,
        "distance_to_val_atr": distance_to_val_atr,
        "price_in_value_area": price_in_value_area,
        "in_lvn": in_lvn,
        "poc_rolling_dist_atr": poc_rolling_dist_atr,
        "poc_session_rolling_divergence_atr": poc_session_rolling_divergence_atr,
    }


# ---------------------------------------------------------------------------
# Support/Resistance — stateless pivot-clustering (Phase 163 Plan 03)
# ---------------------------------------------------------------------------

_SR_FALLBACK: dict[str, float] = {
    "sr_support_dist": 0.0,
    "sr_resist_dist": 0.0,
    "resistance_strength": 0.0,
    "support_strength": 0.0,
    "resistance_age_bars": 0.0,
    "support_age_bars": 0.0,
    "sr_level_count": 0.0,
}


def _finalize_cluster(
    members: list[tuple[float, int]],
    volume: np.ndarray,
    mean_volume: float,
) -> dict[str, Any]:
    """Collapse a group of nearby pivots into one level with strength/recency.

    Ported verbatim from support_resistance.py's SupportResistancePlugin
    (D-02/D-04/D-19): level is the simple mean of member prices, strength is
    the volume-weighted (capped at 2x mean, uncapped in aggregate) sum across
    members, latest_idx is the most recent bar index among members (used to
    derive age_bars = n_bars - 1 - latest_idx by the caller).
    """
    avg_level = sum(p for p, _ in members) / len(members)
    latest_idx = max(idx for _, idx in members)
    vol_sum = sum(
        min(2.0, (float(volume[idx]) / mean_volume if mean_volume > 0 else 1.0))
        for _, idx in members
    )
    return {"level": avg_level, "strength": float(vol_sum), "latest_idx": latest_idx}


def _cluster_levels(
    pivots: list[tuple[float, int]],
    cluster_radius: float,
    volume: np.ndarray,
    mean_volume: float,
) -> list[dict[str, Any]]:
    """Cluster nearby pivot prices within `cluster_radius`, ported from
    support_resistance.py's SupportResistancePlugin._cluster_levels (D-02/D-04).
    """
    if not pivots:
        return []

    sorted_pivots = sorted(pivots, key=lambda p: p[0])
    clusters: list[dict[str, Any]] = []
    current_cluster: list[tuple[float, int]] = [sorted_pivots[0]]

    for price, idx in sorted_pivots[1:]:
        if abs(price - current_cluster[-1][0]) <= cluster_radius:
            current_cluster.append((price, idx))
        else:
            clusters.append(_finalize_cluster(current_cluster, volume, mean_volume))
            current_cluster = [(price, idx)]

    clusters.append(_finalize_cluster(current_cluster, volume, mean_volume))
    return clusters


def _compute_sr_dist_atr(
    highs: np.ndarray,
    lows: np.ndarray,
    close_: float,
    atr_val: float,
    volume: np.ndarray,
    tf: str,
    config: FeatureFactoryConfig,
) -> dict[str, float]:
    """Stateless inline support/resistance (D-02/D-04), ATR-normalized (D-19).

    Ports i3_structure/support_resistance.py's pivot-clustering approach
    directly: find_peaks/find_troughs over a bounded per-tf lookback window,
    cluster pivots within (atr_val * config.sr_cluster_atr_mult), take the
    nearest resistance cluster above close_ and nearest support cluster below
    close_. Distances are converted to ATR units (the archived plugin reports
    percent distance instead -- D-02). resistance_strength/support_strength/
    resistance_age_bars/support_age_bars/sr_level_count come from the SAME
    cluster objects, at effectively zero extra cost (D-19).

    Falls back to all-zero for any side/field when atr_val is invalid per
    _is_valid_atr (<= 0 or below config.atr_normalization_min_pct of close_
    -- todo 237), the window has insufficient bars for find_peaks/
    find_troughs, or no qualifying pivot cluster exists on that side --
    never raises.
    """
    atr_valid = _is_valid_atr(atr_val, close_, config.atr_normalization_min_pct)
    if not atr_valid:
        return dict(_SR_FALLBACK)

    lookback = _sr_lookback(config, tf)
    h = highs[-lookback:]
    lo = lows[-lookback:]
    v = volume[-lookback:]
    n_bars = len(h)
    if n_bars < 2 * config.sr_window + 1:
        return dict(_SR_FALLBACK)

    peak_indices = find_peaks(h, n=config.sr_window)
    trough_indices = find_troughs(lo, n=config.sr_window)

    pivot_highs = [(float(h[i]), i) for i in peak_indices]
    pivot_lows = [(float(lo[i]), i) for i in trough_indices]

    mean_volume = float(v.mean()) if v.size else 0.0
    cluster_radius = atr_val * config.sr_cluster_atr_mult

    resistance_clusters = _cluster_levels(pivot_highs, cluster_radius, v, mean_volume)
    support_clusters = _cluster_levels(pivot_lows, cluster_radius, v, mean_volume)

    resistances_above = [c for c in resistance_clusters if c["level"] > close_]
    supports_below = [c for c in support_clusters if c["level"] < close_]

    nearest_r = min(resistances_above, key=lambda c: c["level"]) if resistances_above else None
    nearest_s = max(supports_below, key=lambda c: c["level"]) if supports_below else None

    sr_level_count = float(len(resistance_clusters) + len(support_clusters))

    if nearest_r is not None:
        sr_resist_dist = (nearest_r["level"] - close_) / atr_val
        resistance_strength = float(nearest_r["strength"])
        resistance_age_bars = float(n_bars - 1 - nearest_r["latest_idx"])
    else:
        sr_resist_dist = 0.0
        resistance_strength = 0.0
        resistance_age_bars = 0.0

    if nearest_s is not None:
        sr_support_dist = (close_ - nearest_s["level"]) / atr_val
        support_strength = float(nearest_s["strength"])
        support_age_bars = float(n_bars - 1 - nearest_s["latest_idx"])
    else:
        sr_support_dist = 0.0
        support_strength = 0.0
        support_age_bars = 0.0

    return {
        "sr_support_dist": sr_support_dist,
        "sr_resist_dist": sr_resist_dist,
        "resistance_strength": resistance_strength,
        "support_strength": support_strength,
        "resistance_age_bars": resistance_age_bars,
        "support_age_bars": support_age_bars,
        "sr_level_count": sr_level_count,
    }


# ---------------------------------------------------------------------------
# Swing / Trend Structure — stateless pivot geometry (Phase 165 Plan 02)
# ---------------------------------------------------------------------------

# Deliberately NOT modelled on _SR_FALLBACK's all-zero dict: 0.0 is a
# legitimate "no level found" value for S/R distances, but a numeric
# placeholder for a swing classification or trend position is a fake
# measurement (D-01, the todo-153 failure shape). Every field here is None.
_SWING_FALLBACK: dict[str, float | None] = {
    "swing_high_dist_atr": None,
    "swing_low_dist_atr": None,
    "swing_high_type": None,
    "swing_low_type": None,
    "swing_pattern": None,
    "swing_high_age_bars": None,
    "swing_low_age_bars": None,
}

# The persisted subset of _compute_swing_structure()'s return dict -- the
# other 5 keys (swing_high_price/swing_low_price/swing_high_indices/
# swing_low_indices/n_bars) are in-memory-only intermediates for
# _compute_trend_structure/_compute_fib_zones and must never reach
# _build_feature_vector (see _compute_swing_structure's docstring). Both
# compute() and compute_batch() filter through this set instead of hand-
# listing the 7 names a second (and third) time.
_SWING_STRUCTURE_OUTPUT_KEYS = frozenset(_SWING_FALLBACK)

# Same D-01 rationale as _SWING_FALLBACK -- the archived plugin's
# trend_direction=0.0/price_position=0.5 early-return reads as a real
# measurement ("no trend" / "exactly mid-range") instead of "couldn't
# measure". Every field here is None.
_TREND_STRUCTURE_FALLBACK: dict[str, float | None] = {
    "trend_direction": None,
    "trend_strength": None,
    "trend_leg_count": None,
    "structure_integrity": None,
    "price_position": None,
    "trend_duration_bars": None,
}


def _compute_swing_structure(
    highs: np.ndarray,
    lows: np.ndarray,
    close_: float,
    atr_val: float,
    config: FeatureFactoryConfig,
) -> dict[str, float | None | list[int] | int]:
    """Stateless swing-high/low detection (D-01/D-02/D-06), ATR-normalized.

    Ports i3_structure/swing_detector.py's find_peaks/find_troughs pivot
    detection over a bounded causal window (config.swing_lookback_bars).
    This is the SHARED pivot-detection pass (D-06): callers must invoke this
    once per bar and pass the returned swing_high_indices/swing_low_indices/
    n_bars into _compute_trend_structure rather than re-running find_peaks/
    find_troughs a second time.

    Unlike swing_detector.py's archived per-field defaults (0.0 for a
    missing type/pattern classification, float(n_bars) for a missing age),
    every insufficient-data branch here returns None per field (D-01) -- a
    fake-but-numeric placeholder is a silent-wrong-answer bug, not a
    measurement.

    Also returns the raw swing_high_price/swing_low_price/swing_high_indices/
    swing_low_indices/n_bars intermediates for Plan 03's fibonacci port
    (D-05). These extra keys are in-memory only -- they must NEVER be
    threaded into _build_feature_vector (D-02/D-16: a raw price and a raw
    bar index are equally invalid as persisted columns).

    Falls back to _SWING_FALLBACK (all-None) for the 7 FeatureVector fields
    (with empty indices/zero n_bars) when atr_val is invalid or the window
    is too short for find_peaks/find_troughs -- never raises.
    """
    atr_valid = _is_valid_atr(atr_val, close_, config.atr_normalization_min_pct)
    if not atr_valid:
        result: dict[str, float | None | list[int] | int] = dict(_SWING_FALLBACK)
        result["swing_high_price"] = None
        result["swing_low_price"] = None
        result["swing_high_indices"] = []
        result["swing_low_indices"] = []
        result["n_bars"] = 0
        return result

    h = highs[-config.swing_lookback_bars :]
    lo = lows[-config.swing_lookback_bars :]
    n_bars = len(h)
    if n_bars < 2 * config.swing_pivot_window + 1:
        result = dict(_SWING_FALLBACK)
        result["swing_high_price"] = None
        result["swing_low_price"] = None
        result["swing_high_indices"] = []
        result["swing_low_indices"] = []
        result["n_bars"] = n_bars
        return result

    peaks = find_peaks(h, n=config.swing_pivot_window)
    troughs = find_troughs(lo, n=config.swing_pivot_window)

    swing_high_price: float | None = float(h[peaks[-1]]) if peaks else None
    swing_low_price: float | None = float(lo[troughs[-1]]) if troughs else None

    swing_high_dist_atr = (
        (swing_high_price - close_) / atr_val if swing_high_price is not None else None
    )
    swing_low_dist_atr = (
        (close_ - swing_low_price) / atr_val if swing_low_price is not None else None
    )
    swing_high_age_bars = float(n_bars - 1 - peaks[-1]) if peaks else None
    swing_low_age_bars = float(n_bars - 1 - troughs[-1]) if troughs else None

    swing_high_type: float | None = None
    if len(peaks) >= 2:
        swing_high_type = 1.0 if h[peaks[-1]] > h[peaks[-2]] else -1.0

    swing_low_type: float | None = None
    if len(troughs) >= 2:
        swing_low_type = 1.0 if lo[troughs[-1]] > lo[troughs[-2]] else -1.0

    swing_pattern: float | None = None
    if swing_high_type is not None and swing_low_type is not None:
        if swing_high_type > 0.0 and swing_low_type > 0.0:
            swing_pattern = 1.0
        elif swing_high_type < 0.0 and swing_low_type < 0.0:
            swing_pattern = -1.0
        else:
            swing_pattern = 0.0

    return {
        "swing_high_dist_atr": swing_high_dist_atr,
        "swing_low_dist_atr": swing_low_dist_atr,
        "swing_high_type": swing_high_type,
        "swing_low_type": swing_low_type,
        "swing_pattern": swing_pattern,
        "swing_high_age_bars": swing_high_age_bars,
        "swing_low_age_bars": swing_low_age_bars,
        "swing_high_price": swing_high_price,
        "swing_low_price": swing_low_price,
        "swing_high_indices": peaks,
        "swing_low_indices": troughs,
        "n_bars": n_bars,
    }


def _trend_duration_bars(
    direction: float,
    swing_highs: list[int],
    swing_lows: list[int],
    high: np.ndarray,
    low: np.ndarray,
    n_bars: int,
) -> float:
    """Bars since the start of the current directional swing streak.

    Ported verbatim from trend_structure.py's
    TrendStructurePlugin._compute_trend_duration static method.
    """
    if direction > 0.0 and len(swing_highs) >= 2:
        streak_start = swing_highs[-1]
        for i in range(len(swing_highs) - 1, 0, -1):
            if high[swing_highs[i]] > high[swing_highs[i - 1]]:
                streak_start = swing_highs[i - 1]
            else:
                break
        return float(n_bars - 1 - streak_start)
    if direction < 0.0 and len(swing_lows) >= 2:
        streak_start = swing_lows[-1]
        for i in range(len(swing_lows) - 1, 0, -1):
            if low[swing_lows[i]] < low[swing_lows[i - 1]]:
                streak_start = swing_lows[i - 1]
            else:
                break
        return float(n_bars - 1 - streak_start)
    return 0.0


def _compute_trend_structure(
    highs: np.ndarray,
    lows: np.ndarray,
    close_: float,
    atr_val: float,
    swing_fields: dict[str, Any],
    config: FeatureFactoryConfig,
) -> dict[str, float | None]:
    """Stateless trend-regime classification from the shared swing pass (D-01/D-06).

    Ports i3_structure/trend_structure.py's leg-scoring/strength/integrity/
    price-position/duration geometry, consuming the SAME swing_high_indices/
    swing_low_indices/n_bars produced by _compute_swing_structure for this
    bar -- find_peaks/find_troughs is never called a second time here (D-06).

    D-01 fix: the archived plugin's early return
    ({"trend_direction": 0.0, ..., "price_position": 0.5, ...}) when fewer
    than 2 confirmed swing highs/lows exist is a fake-but-numeric "no
    signal" -- replaced here with _TREND_STRUCTURE_FALLBACK (all-None).
    atr_val<=0 also returns the all-None fallback: the archived plugin
    silently skipped ATR normalization and returned a half-normalized
    strength instead, which is not comparable across symbols/tf and is
    removed rather than carried forward.

    price_range/atr_strength_divisor are APR-backed
    (config.trend_structure_range_lookback_bars /
    config.trend_structure_atr_strength_divisor) -- no hardcoded 20-bar
    slice or 5.0 divisor survives the port.

    Never raises.
    """
    atr_valid = _is_valid_atr(atr_val, close_, config.atr_normalization_min_pct)
    if not atr_valid:
        return dict(_TREND_STRUCTURE_FALLBACK)

    swing_highs: list[int] = swing_fields.get("swing_high_indices") or []
    swing_lows: list[int] = swing_fields.get("swing_low_indices") or []
    n_bars: int = swing_fields.get("n_bars") or 0
    if len(swing_highs) < 2 or len(swing_lows) < 2:
        return dict(_TREND_STRUCTURE_FALLBACK)

    h = highs[-config.swing_lookback_bars :]
    lo = lows[-config.swing_lookback_bars :]

    bullish_legs = 0
    bearish_legs = 0
    for i in range(1, len(swing_highs)):
        if h[swing_highs[i]] > h[swing_highs[i - 1]]:
            bullish_legs += 1
        elif h[swing_highs[i]] < h[swing_highs[i - 1]]:
            bearish_legs += 1
    for i in range(1, len(swing_lows)):
        if lo[swing_lows[i]] > lo[swing_lows[i - 1]]:
            bullish_legs += 1
        elif lo[swing_lows[i]] < lo[swing_lows[i - 1]]:
            bearish_legs += 1

    total_legs = bullish_legs + bearish_legs
    if total_legs == 0:
        direction = 0.0
        leg_count = 0.0
    elif bullish_legs > bearish_legs:
        direction = 1.0
        leg_count = float(bullish_legs)
    elif bearish_legs > bullish_legs:
        direction = -1.0
        leg_count = float(bearish_legs)
    else:
        direction = 0.0
        leg_count = 0.0

    strength = max(bullish_legs, bearish_legs) / total_legs if total_legs > 0 else 0.0
    range_lookback = config.trend_structure_range_lookback_bars
    price_range = float(np.max(h[-range_lookback:]) - np.min(lo[-range_lookback:]))
    strength = min(
        1.0,
        strength * (price_range / atr_val) / config.trend_structure_atr_strength_divisor,
    )

    overlap_count = 0
    all_swings = sorted(
        [(idx, "H", float(h[idx])) for idx in swing_highs]
        + [(idx, "L", float(lo[idx])) for idx in swing_lows],
        key=lambda x: x[0],
    )
    for i in range(1, len(all_swings)):
        prev_type, prev_val = all_swings[i - 1][1], all_swings[i - 1][2]
        curr_type, curr_val = all_swings[i][1], all_swings[i][2]
        if prev_type == "H" and curr_type == "L" and curr_val > prev_val:
            overlap_count += 1
        elif prev_type == "L" and curr_type == "H" and curr_val < prev_val:
            overlap_count += 1
    max_overlaps = max(len(all_swings) - 1, 1)
    integrity = 1.0 - overlap_count / max_overlaps

    recent_high = float(np.max(h[swing_highs[-1] :]))
    recent_low = float(np.min(lo[swing_lows[-1] :]))
    swing_range = recent_high - recent_low
    position: float | None
    if swing_range > 0:
        position = (close_ - recent_low) / swing_range
        position = max(0.0, min(1.0, position))
    else:
        # D-01: no fake midpoint placeholder -- an undefined swing range
        # means "unknown position", not "exactly at the midpoint".
        position = None

    trend_duration = _trend_duration_bars(direction, swing_highs, swing_lows, h, lo, n_bars)

    return {
        "trend_direction": direction,
        "trend_strength": round(strength, 4),
        "trend_leg_count": leg_count,
        "structure_integrity": round(integrity, 4),
        "price_position": round(position, 4) if position is not None else None,
        "trend_duration_bars": trend_duration,
    }


# ---------------------------------------------------------------------------
# Swing Momentum / Fibonacci Zones — stateless swing geometry (Phase 165 Plan 03)
# ---------------------------------------------------------------------------

# D-01: the archived plugin already returns {} (empty dict, "not computed")
# on insufficient data -- unlike _SWING_FALLBACK/_TREND_STRUCTURE_FALLBACK,
# there is no fake-numeric-default bug to fix here. Still all-None, matching
# the FeatureVector float | None convention every other fallback in this
# module follows.
_SWING_MOMENTUM_FALLBACK: dict[str, float | None] = {
    "swing_amplitude_ratio": None,
    "swing_amplitude_expanding": None,
    "swing_amplitude_intensity": None,
    "swing_velocity_bars": None,
    "swing_velocity_bias": None,
    "struct_energy": None,
    "struct_accel_bias": None,
    "swing_volume_confirmation": None,
}


def _dedup_swing_extremes(
    extremes: list[tuple[float, int, str]],
) -> list[tuple[float, int, str]]:
    """Drop consecutive same-type extremes, keeping the dominant one.

    Ported verbatim from the archived module-level swing_momentum.py
    ``_dedup_extremes`` (lines 233-255), renamed to avoid colliding with a
    future SMC-tier helper of the same generic name in this module. When
    two consecutive highs appear without an intervening low, keep the
    higher one; when two consecutive lows appear, keep the lower one --
    this is what guarantees the alternating high/low pattern swing-leg
    amplitude/velocity analysis requires.
    """
    if not extremes:
        return extremes

    result: list[tuple[float, int, str]] = [extremes[0]]
    for current in extremes[1:]:
        prev = result[-1]
        if current[2] == prev[2]:
            if current[2] == "high" and current[0] >= prev[0]:
                result[-1] = current
            elif current[2] == "low" and current[0] <= prev[0]:
                result[-1] = current
        else:
            result.append(current)

    return result


def _detect_swing_extremes(
    highs: np.ndarray,
    lows: np.ndarray,
    confirm_n: int,
    max_extremes: int,
) -> list[tuple[float, int, str]]:
    """Self-contained confirm-window swing extreme detector (D-06 Finding B).

    Deliberately does NOT call find_peaks/find_troughs -- swing momentum
    uses its own independent confirmation algorithm (a bar is a confirmed
    peak/trough when it equals the max/min over its own inclusive window on
    both sides), a different, self-contained calculation from the shared
    pivot pass _compute_swing_structure/_compute_trend_structure use.
    Unifying the two would change swing momentum's output.

    The >= max / <= min comparison means a flat run of equal highs (or
    lows) confirms EVERY bar in that run as its own extreme -- that is why
    _dedup_swing_extremes exists, to collapse consecutive same-type
    duplicates down to one dominant extreme per swing leg.

    Indices in the returned tuples are positions within the highs/lows
    ARRAYS PASSED IN (the caller's own pre-sliced window), not any larger
    series.

    Returns at most the trailing max_extremes confirmed, deduplicated
    extremes; never raises (a too-short input yields an empty list).

    Vectorized via the same shifted-array neighbor-comparison technique as
    find_peaks/find_troughs (src/intelligence/utils/core.py) instead of a
    per-bar Python loop with an np.max/np.min call over each bar's window --
    this runs once per bar in both compute() and compute_batch(), so an
    O(n_bars) Python loop here is O(n_bars) extra numpy dispatch overhead
    per bar across the whole corpus. Not a call to find_peaks/find_troughs
    itself (see module docstring above): the >=/<= comparison here has no
    "at least one strict" requirement, so it is computed directly rather
    than reused.
    """
    n_bars = len(highs)
    count = n_bars - 2 * confirm_n
    if count <= 0:
        return []

    center_h = highs[confirm_n : confirm_n + count]
    center_l = lows[confirm_n : confirm_n + count]
    is_peak = np.ones(count, dtype=bool)
    is_trough = np.ones(count, dtype=bool)
    for j in range(1, confirm_n + 1):
        left_h = highs[confirm_n - j : confirm_n - j + count]
        right_h = highs[confirm_n + j : confirm_n + j + count]
        is_peak &= (center_h >= left_h) & (center_h >= right_h)
        left_l = lows[confirm_n - j : confirm_n - j + count]
        right_l = lows[confirm_n + j : confirm_n + j + count]
        is_trough &= (center_l <= left_l) & (center_l <= right_l)

    # elif semantics: a bar satisfying both is recorded as a peak only,
    # matching the original loop's `if is_peak: ... elif is_trough: ...`.
    peak_idx = np.where(is_peak)[0] + confirm_n
    trough_idx = np.where(is_trough & ~is_peak)[0] + confirm_n

    extremes: list[tuple[float, int, str]] = sorted(
        [(float(highs[i]), int(i), "high") for i in peak_idx]
        + [(float(lows[i]), int(i), "low") for i in trough_idx],
        key=lambda x: x[1],
    )

    extremes = _dedup_swing_extremes(extremes)
    return extremes[-max_extremes:]


def _compute_swing_momentum(
    highs: np.ndarray,
    lows: np.ndarray,
    volumes: np.ndarray,
    config: FeatureFactoryConfig,
) -> dict[str, float | None]:
    """Stateless swing-momentum amplitude/velocity/energy (D-01/D-06/D-15).

    NOTE the signature carries no atr_val/close_ parameter -- deliberate.
    Every one of the 8 outputs below is derived from amplitudes only
    through the ratio of the last amplitude to the mean of the last three,
    a ratio in which a common positive divisor cancels out exactly. The
    archived plugin normalized each amplitude by ATR first (falling back to
    a divisor of 1.0 when ATR was unavailable) and added a small additive
    epsilon to the denominator so the divide could never blow up -- that
    epsilon is the only reason the ATR divisor was not already a no-op, and
    it made the result silently depend on the absolute price scale. Both
    are deleted here; the epsilon's job is replaced by an explicit
    amp_mean <= 0 guard below, which returns the all-None fallback instead
    of a scale-dependent number. This makes the function EXACTLY
    ATR-invariant. test_swing_momentum_atr_invariance is the proof
    obligation for this claim -- if it ever fails, this deletion was wrong
    and must be reverted, not the test weakened.

    Ports i3_structure/swing_momentum.py's compute_full() over its own
    self-contained _detect_swing_extremes() confirm-window pass.

    Fixes two archived implementation-vs-docstring bugs rather than porting
    them: the mean amplitude used as the ratio's denominator only covers
    the LAST three amplitudes, not the full history, and the "expanding"
    classification checks whether the LAST three amplitudes are increasing,
    not the first three -- both match the archived plugin's own docstring
    and migration 267's binding COMMENT; neither matches what the archived
    plugin's code actually did.

    Falls back to _SWING_MOMENTUM_FALLBACK (all-None) when the lookback
    window is too short, fewer than config.swing_momentum_max_extremes
    confirmed extremes exist, or the recent mean amplitude is not positive
    (flat prices) -- never raises.
    """
    h = highs[-config.swing_momentum_lookback_bars :]
    lo = lows[-config.swing_momentum_lookback_bars :]
    v = volumes[-config.swing_momentum_lookback_bars :]
    if len(h) < 2 * config.swing_momentum_confirm_n + 1:
        return dict(_SWING_MOMENTUM_FALLBACK)

    extremes = _detect_swing_extremes(
        h, lo, config.swing_momentum_confirm_n, config.swing_momentum_max_extremes
    )
    if len(extremes) < config.swing_momentum_max_extremes:
        return dict(_SWING_MOMENTUM_FALLBACK)

    amps = [abs(extremes[k][0] - extremes[k + 1][0]) for k in range(len(extremes) - 1)]
    vels = [
        max(float(abs(extremes[k + 1][1] - extremes[k][1])), 1.0) for k in range(len(extremes) - 1)
    ]
    if not amps or not vels:
        return dict(_SWING_MOMENTUM_FALLBACK)

    amp_recent = amps[-3:]
    amp_mean = float(np.mean(amp_recent))
    if amp_mean <= 0:
        return dict(_SWING_MOMENTUM_FALLBACK)

    swing_amplitude_ratio = amps[-1] / amp_mean
    _is_expanding = len(amps) >= 3 and amps[-3] < amps[-2] < amps[-1]
    swing_amplitude_expanding = 1.0 if _is_expanding else 0.0  # gradient-exempt
    swing_amplitude_intensity = (
        linear_ramp(
            swing_amplitude_ratio,
            config.swing_momentum_intensity_ramp_lo,
            config.swing_momentum_intensity_ramp_hi,
        )
        if swing_amplitude_expanding == 1.0  # gradient-exempt: categorical flag, not a score
        else 0.0
    )

    swing_velocity_bars = float(vels[-1])
    swing_velocity_bias: float | None
    if len(vels) >= 2:
        if vels[-1] < vels[-2]:
            swing_velocity_bias = 1.0
        elif vels[-1] > vels[-2]:
            swing_velocity_bias = -1.0
        else:
            swing_velocity_bias = 0.0
    else:
        swing_velocity_bias = None

    speed_factor = clamp(
        config.swing_momentum_reference_bars / max(swing_velocity_bars, 1.0),
        config.swing_momentum_speed_factor_min,
        config.swing_momentum_speed_factor_max,
    )
    struct_energy = clamp(
        swing_amplitude_ratio * speed_factor / config.swing_momentum_energy_divisor,
        0.0,
        1.0,
    )

    # struct_accel_bias: ported verbatim from the archived
    # _compute_accel_bias -- collect the retained highs/lows in bar order,
    # compare the last 2 of each side.
    ext_highs = [(p, idx) for p, idx, t in extremes if t == "high"]
    ext_lows = [(p, idx) for p, idx, t in extremes if t == "low"]
    if len(ext_highs) < 2 or len(ext_lows) < 2:
        struct_accel_bias = 0.0
    else:
        h1, h2 = ext_highs[-2][0], ext_highs[-1][0]
        l1, l2 = ext_lows[-2][0], ext_lows[-1][0]
        if h2 > h1 and l2 > l1:
            struct_accel_bias = 1.0
        elif h2 < h1 and l2 < l1:
            struct_accel_bias = -1.0
        else:
            struct_accel_bias = 0.0

    # swing_volume_confirmation (D-15): mean volume over the bar-index span
    # of the most recent confirmed swing leg, divided by mean volume over
    # the whole bounded window -- a free column off computation already
    # happening, no new state.
    window_mean_volume = float(v.mean()) if len(v) > 0 else 0.0
    swing_volume_confirmation: float | None
    if window_mean_volume > 0:
        i0 = min(extremes[-2][1], extremes[-1][1])
        i1 = max(extremes[-2][1], extremes[-1][1])
        leg_mean_volume = float(v[i0 : i1 + 1].mean())
        swing_volume_confirmation = leg_mean_volume / window_mean_volume
    else:
        swing_volume_confirmation = None

    return {
        "swing_amplitude_ratio": float(swing_amplitude_ratio),
        "swing_amplitude_expanding": swing_amplitude_expanding,
        "swing_amplitude_intensity": float(swing_amplitude_intensity),
        "swing_velocity_bars": swing_velocity_bars,
        "swing_velocity_bias": swing_velocity_bias,
        "struct_energy": float(struct_energy),
        "struct_accel_bias": struct_accel_bias,
        "swing_volume_confirmation": swing_volume_confirmation,
    }


# APR-EXEMPT: definitional Fibonacci retracement ratios, the same exemption
# class as "the 5 in momentum_z_5" per CLAUDE.md's APR-exempt list -- not a
# tunable to migrate. Migration 267's SQL COMMENT carries the same note;
# keep the two consistent.
_FIB_RATIOS: tuple[float, ...] = (0.236, 0.382, 0.500, 0.618, 0.786)
# ICT discount-zone bounds, referenced by value (not position) so a future
# reorder/extension of _FIB_RATIOS can't silently redefine the zone. Indices
# resolved once at import time (not per bar in _compute_fib_zones, which
# runs once per bar across the whole historical corpus in compute_batch()).
_FIB_DISCOUNT_ZONE_LO = 0.500
_FIB_DISCOUNT_ZONE_HI = 0.786
_FIB_DISCOUNT_LO_IDX = _FIB_RATIOS.index(_FIB_DISCOUNT_ZONE_LO)
_FIB_DISCOUNT_HI_IDX = _FIB_RATIOS.index(_FIB_DISCOUNT_ZONE_HI)

_FIB_FALLBACK: dict[str, float | None] = {
    "nearest_fib_ratio": None,
    "nearest_fib_dist_atr": None,
    "fib_cluster_strength": None,
    "in_fib_discount_zone": None,
}


def _compute_fib_zones(
    close_: float,
    atr_val: float,
    swing_fields: dict[str, Any],
    config: FeatureFactoryConfig,
) -> dict[str, float | None]:
    """Fibonacci retracement zones off the SAME bar's shared swing pass (D-05).

    Consumes swing_fields["swing_high_price"]/["swing_low_price"] -- the
    in-memory intermediates _compute_swing_structure already produced for
    this bar. This IS D-05's fix: the archived plugin's cross-plugin read
    plus its rolling-high/low fallback existed only because the old
    wave-based pipeline could not guarantee the swing-detector plugin ran
    first in the same pass; v3's compute()/compute_batch() calls this
    function AFTER the shared swing pass on the same bar, so the swing
    prices are simply already available as local values. No fallback
    branch is reimplemented here -- no rolling-high/low substitute over the
    raw OHLCV arrays.

    Returns _FIB_FALLBACK (all-None) when either swing price is missing or
    non-finite, when the swing range is non-positive, or when atr_val is
    missing/non-finite/non-positive -- matching migration 267's COMMENT.
    Never raises.
    """
    swing_high_price = swing_fields.get("swing_high_price")
    swing_low_price = swing_fields.get("swing_low_price")
    if (
        swing_high_price is None
        or swing_low_price is None
        or not math.isfinite(swing_high_price)
        or not math.isfinite(swing_low_price)
    ):
        return dict(_FIB_FALLBACK)

    swing_range = swing_high_price - swing_low_price
    if swing_range <= 0:
        return dict(_FIB_FALLBACK)

    atr_valid = _is_valid_atr(atr_val, close_, config.atr_normalization_min_pct)
    if not atr_valid:
        return dict(_FIB_FALLBACK)

    levels = [swing_low_price + ratio * swing_range for ratio in _FIB_RATIOS]
    nearest_idx = min(range(len(levels)), key=lambda k: abs(levels[k] - close_))
    nearest_fib_ratio = float(_FIB_RATIOS[nearest_idx])
    nearest_fib_dist_atr = abs(close_ - levels[nearest_idx]) / atr_val
    discount_lo = levels[_FIB_DISCOUNT_LO_IDX]
    discount_hi = levels[_FIB_DISCOUNT_HI_IDX]
    # gradient-exempt: zone-membership flag, not a score
    in_fib_discount_zone = 1.0 if discount_lo <= close_ <= discount_hi else 0.0  # gradient-exempt

    threshold = atr_val / config.fib_cluster_atr_divisor
    cluster_count = sum(
        1
        for i in range(len(levels))
        for j in range(i + 1, len(levels))
        if abs(levels[i] - levels[j]) < threshold
    )
    max_pairs = len(levels) * (len(levels) - 1) / 2
    fib_cluster_strength = cluster_count / max_pairs if max_pairs > 0 else 0.0

    return {
        "nearest_fib_ratio": nearest_fib_ratio,
        "nearest_fib_dist_atr": nearest_fib_dist_atr,
        "fib_cluster_strength": fib_cluster_strength,
        "in_fib_discount_zone": in_fib_discount_zone,
    }


# ---------------------------------------------------------------------------
# Session Levels — FeatureCache-derived price geometry (Phase 165 Plan 05)
# ---------------------------------------------------------------------------

# D-01: every one of these 16 columns is None on cold/degenerate state, unlike
# _NEUTRAL_VP_EXTRA (which preserves two legacy 0.0/0.5 neutral defaults for
# pre-existing consumers). None of these sixteen columns has a legacy default
# to preserve -- they are brand-new Phase 165 columns -- so every one falls
# back to None, matching migration 267's COMMENT ON COLUMN NULL conditions.
_SESSION_LEVELS_FALLBACK: dict[str, float | None] = {
    "prior_session_high_dist_atr": None,
    "prior_session_low_dist_atr": None,
    "prior_session_close_dist_atr": None,
    "overnight_high_dist_atr": None,
    "overnight_low_dist_atr": None,
    "overnight_range_pct": None,
    "opening_gap_pct": None,
    "weekly_pivot_dist_atr": None,
    "weekly_r1_dist_atr": None,
    "weekly_r2_dist_atr": None,
    "weekly_s1_dist_atr": None,
    "weekly_s2_dist_atr": None,
    "nearest_level_dist_atr": None,
    "asian_session_high_dist_atr": None,
    "asian_session_low_dist_atr": None,
    "gap_filled": None,
}

# The five intraday-only fields, suppressed to None on tf=='1d'. A daily bar
# is a whole session -- it has no observable non-RTH sub-block and no Asian
# sub-block. On tf=='1d', update_session_levels() would classify the single
# daily bar itself as the overnight block, making overnight_high_dist_atr a
# near-duplicate of prior_session_high_dist_atr rather than an independent
# measurement -- same class of reasoning as _NEUTRAL_VP_EXTRA's tf=='1d'
# branch. The other eleven fields (prior-session trio, opening gap, weekly
# five, nearest level, gap_filled) ARE meaningful on daily bars and are not
# suppressed here.
_SESSION_LEVELS_DAILY_SUPPRESSED: tuple[str, ...] = (
    "overnight_high_dist_atr",
    "overnight_low_dist_atr",
    "overnight_range_pct",
    "asian_session_high_dist_atr",
    "asian_session_low_dist_atr",
)


def _derive_session_levels(
    cache: FeatureCache,
    close_: float,
    atr_val: float | None,
    tf: str,
    config: FeatureFactoryConfig,
) -> dict[str, float | None]:
    """Derive the 16 ATR-normalized/bounded/flag session-levels FeatureVector fields.

    Reads FeatureCache's raw session, overnight, Asian-block and prior-completed-
    week levels (set by the session-levels mutator / update_wk_vwap(), both
    called once per bar by the caller BEFORE compute()) plus the compute-path
    atr_val -- never recomputes them, and never returns a raw price level
    (D-16). Structured
    exactly like _derive_session_vp(): an atr_valid guard at the top returning the
    full fallback, local _above()/_below() closures with the same sign convention
    (a level ABOVE close yields a positive distance via (level - close_); a level
    BELOW close yields a positive distance via (close_ - level)), never raises.

    The atr_valid guard also suppresses the three ATR-independent fields
    (opening_gap_pct, overnight_range_pct, gap_filled): migration 267's COMMENT
    binds all sixteen columns to NULL on ATR <= 0, and letting behaviour diverge
    from the column documentation is exactly the drift this phase's discipline
    exists to prevent.

    Weekly pivot/R1/R2/S1/S2 anchor on the PRIOR COMPLETED ISO week's
    high/low/close (cache._prior_wk_high/_low/_close) only -- never the week in
    progress, which would make the pivot partially self-referential (its close
    component would be the current bar). All five weekly fields are None
    together whenever any of the three prior-week values is None; the archived
    session_levels.py plugin's prior-session-substituted-for-prior-week
    fallback (a prior SESSION silently labelled a weekly level) is a fake
    measurement of a different thing and is deliberately NOT ported.

    tf=='1d' suppression is applied at the END, inside this helper (not at the
    call sites), so live and batch cannot diverge on the gating -- a deliberate
    departure from _derive_session_vp's call-site branch, which exists because
    VP additionally skips the expensive rolling-POC computation on daily bars,
    an optimization with no analogue here.

    Never raises: a cold cache (no session/week has ever completed) reads back
    its dataclass defaults (all None), which this function propagates as the
    correct "no data yet" reading, not an error state.
    """
    atr_valid = _is_valid_atr(atr_val, close_, config.atr_normalization_min_pct)
    if not atr_valid:
        return dict(_SESSION_LEVELS_FALLBACK)

    def _above(level: float | None) -> float | None:
        return None if level is None else (level - close_) / atr_val

    def _below(level: float | None) -> float | None:
        return None if level is None else (close_ - level) / atr_val

    psh = cache._sl_prior_session_high
    psl = cache._sl_prior_session_low
    psc = cache._sl_prior_session_close
    on_high = cache._sl_overnight_high
    on_low = cache._sl_overnight_low
    asia_high = cache._sl_asia_high
    asia_low = cache._sl_asia_low
    session_open = cache._sl_session_open

    prior_session_high_dist_atr = _above(psh)
    prior_session_low_dist_atr = _below(psl)
    prior_session_close_dist_atr = _below(psc)
    overnight_high_dist_atr = _above(on_high)
    overnight_low_dist_atr = _below(on_low)

    overnight_range_pct = (
        None if on_high is None or on_low is None or on_low <= 0 else (on_high - on_low) / on_low
    )
    opening_gap_pct = (
        None if session_open is None or psc is None or psc <= 0 else (session_open - psc) / psc
    )

    asian_session_high_dist_atr = _above(asia_high)
    asian_session_low_dist_atr = _below(asia_low)

    gap_filled = float(cache._sl_gap_filled)

    ph = cache._prior_wk_high
    pl = cache._prior_wk_low
    pc = cache._prior_wk_close
    if ph is None or pl is None or pc is None:
        weekly_pivot_dist_atr: float | None = None
        weekly_r1_dist_atr: float | None = None
        weekly_r2_dist_atr: float | None = None
        weekly_s1_dist_atr: float | None = None
        weekly_s2_dist_atr: float | None = None
        wp = r1 = r2 = s1 = s2 = None
    else:
        wp = (ph + pl + pc) / 3.0
        wr = ph - pl
        r1 = 2.0 * wp - pl
        r2 = wp + wr
        s1 = 2.0 * wp - ph
        s2 = wp - wr
        weekly_pivot_dist_atr = _below(wp)
        weekly_r1_dist_atr = _above(r1)
        weekly_r2_dist_atr = _above(r2)
        weekly_s1_dist_atr = _below(s1)
        weekly_s2_dist_atr = _below(s2)

    # Nearest level -- the same 7 raw levels the archived plugin's `levels`
    # list used (matching migration 267's COMMENT): prior-session high/low
    # plus the 5 weekly pivot levels. Raw values stay in-function locals --
    # never returned (D-16).
    _candidates = [lvl for lvl in (psh, psl, wp, r1, r2, s1, s2) if lvl is not None]
    nearest_level_dist_atr = (
        None
        if not _candidates
        else abs(close_ - min(_candidates, key=lambda x: abs(x - close_))) / atr_val
    )

    result: dict[str, float | None] = {
        "prior_session_high_dist_atr": prior_session_high_dist_atr,
        "prior_session_low_dist_atr": prior_session_low_dist_atr,
        "prior_session_close_dist_atr": prior_session_close_dist_atr,
        "overnight_high_dist_atr": overnight_high_dist_atr,
        "overnight_low_dist_atr": overnight_low_dist_atr,
        "overnight_range_pct": overnight_range_pct,
        "opening_gap_pct": opening_gap_pct,
        "weekly_pivot_dist_atr": weekly_pivot_dist_atr,
        "weekly_r1_dist_atr": weekly_r1_dist_atr,
        "weekly_r2_dist_atr": weekly_r2_dist_atr,
        "weekly_s1_dist_atr": weekly_s1_dist_atr,
        "weekly_s2_dist_atr": weekly_s2_dist_atr,
        "nearest_level_dist_atr": nearest_level_dist_atr,
        "asian_session_high_dist_atr": asian_session_high_dist_atr,
        "asian_session_low_dist_atr": asian_session_low_dist_atr,
        "gap_filled": gap_filled,
    }

    if tf == "1d":
        for name in _SESSION_LEVELS_DAILY_SUPPRESSED:
            result[name] = None

    return result


# ---------------------------------------------------------------------------
# Kernels
# ---------------------------------------------------------------------------


# One (keys, nullable) spec per key group: the Kernel's outputs and the row reader both derive
# from it. A key is nullable where its helper's fallback dict holds None.
VP = KeyGroup.from_fallback(_NEUTRAL_VP_EXTRA)
SR = KeyGroup.from_fallback(_SR_FALLBACK)
SWING = KeyGroup.from_fallback(_SWING_FALLBACK)
TREND = KeyGroup.from_fallback(_TREND_STRUCTURE_FALLBACK)
SWING_MOMENTUM = KeyGroup.from_fallback(_SWING_MOMENTUM_FALLBACK)
FIB = KeyGroup.from_fallback(_FIB_FALLBACK)
SESSION_LEVEL = KeyGroup.from_fallback(_SESSION_LEVELS_FALLBACK)
# The swing, trend and fib columns come from one kernel because the trend and fib helpers
# reuse the swing pass's pivots (D-06, one find_peaks pass per bar).
SWING_STRUCTURE = KeyGroup.concat(SWING, TREND, FIB)

_POC = "_poc_price_rolling"
_OHLCV = ("open", "high", "low", "close", "volume")

# The S/R lookback when a timeframe has no entry in `sr_lookback_by_tf`. The compute reads the
# per-tf value and the kernel's memory bounds every tf through the same two accessors, so a change
# here moves both together (a kernel's memory function sees config, not tf).
_SR_DEFAULT_LOOKBACK = 120


def _sr_lookback(config, tf: str) -> int:
    return int(config.sr_lookback_by_tf.get(tf, _SR_DEFAULT_LOOKBACK))


def _sr_max_lookback(config) -> int:
    return max(
        max(config.sr_lookback_by_tf.values(), default=_SR_DEFAULT_LOOKBACK), _SR_DEFAULT_LOOKBACK
    )


def _compute_rolling_poc(x, config):
    n = len(x["close"])
    out = np.full(n, np.nan)
    if constant_tf(x["tf"]) == "1d":
        return {_POC: out}
    highs, lows, closes, volumes = x["high"], x["low"], x["close"], x["volume"]
    for i in range(1, n):
        start = window_start(i, config.session_vp_rolling_window)
        price = _rolling_poc_price(
            highs[start : i + 1],
            lows[start : i + 1],
            closes[start : i + 1],
            volumes[start : i + 1],
            config,
        )
        if price is not None:
            out[i] = price
    return {_POC: out}


def _replay_cache(x, config, update):
    """Yield (i, cache, bar_ts) over rows 1.. with a fresh cache updated as the batch loop does."""
    cache = FeatureCache()
    highs, lows, closes, volumes = (x[f] for f in ("high", "low", "close", "volume"))
    opens = x.get("open", closes)  # only update_session_levels reads the open
    ts = x["ts_dt"]
    for i in range(1, len(closes)):
        bar_ts = ts[i]
        update(
            cache,
            bar_ts,
            float(opens[i]),
            float(highs[i]),
            float(lows[i]),
            float(closes[i]),
            float(volumes[i]),
            config,
        )
        yield i, cache, bar_ts
        cache.advance_bar(
            bar_ts, float(highs[i]), float(lows[i]), float(closes[i]), float(volumes[i])
        )


def _compute_session_vp_columns(x, config):
    n = len(x["close"])
    tf = constant_tf(x["tf"])
    closes, atr, poc = x["close"], x[ATR_RAW_PADDED], x[_POC]
    rows: dict[int, dict[str, float | None]] = {}

    def update(cache, bar_ts, open_, high_, low_, close_, vol_, cfg):
        cache.update_session_vp(bar_ts, high_, low_, close_, vol_, cfg)

    for i, cache, _bar_ts in _replay_cache(x, config, update):
        if tf == "1d":
            rows[i] = dict(_NEUTRAL_VP_EXTRA)
        else:
            rolling = None if math.isnan(poc[i]) else float(poc[i])
            rows[i] = _derive_session_vp(cache, float(closes[i]), float(atr[i]), rolling, config)
    return VP.columns(n, rows.__getitem__)


def _compute_support_resistance(x, config):
    tf = constant_tf(x["tf"])
    highs, lows, closes, volumes, atr = (
        x["high"],
        x["low"],
        x["close"],
        x["volume"],
        x[ATR_RAW_PADDED],
    )
    lookback = _sr_lookback(config, tf)

    def row(i):
        start = window_start(i, lookback)
        return _compute_sr_dist_atr(
            highs[start : i + 1],
            lows[start : i + 1],
            float(closes[i]),
            float(atr[i]),
            volumes[start : i + 1],
            tf,
            config,
        )

    return SR.columns(len(closes), row)


def _compute_swing_structure_columns(x, config):
    highs, lows, closes, atr = x["high"], x["low"], x["close"], x[ATR_RAW_PADDED]

    def row(i):
        start = window_start(i, config.swing_lookback_bars)
        h, lo, close_, atr_val = (
            highs[start : i + 1],
            lows[start : i + 1],
            float(closes[i]),
            float(atr[i]),
        )
        swing = _compute_swing_structure(h, lo, close_, atr_val, config)
        trend = _compute_trend_structure(h, lo, close_, atr_val, swing, config)
        fib = _compute_fib_zones(close_, atr_val, swing, config)
        return {**swing, **trend, **fib}

    return SWING_STRUCTURE.columns(len(closes), row)


def _compute_swing_momentum_columns(x, config):
    highs, lows, volumes = x["high"], x["low"], x["volume"]

    def row(i):
        start = window_start(i, config.swing_momentum_lookback_bars)
        return _compute_swing_momentum(
            highs[start : i + 1], lows[start : i + 1], volumes[start : i + 1], config
        )

    return SWING_MOMENTUM.columns(len(highs), row)


def _compute_session_levels_columns(x, config):
    n = len(x["close"])
    tf = constant_tf(x["tf"])
    closes, atr = x["close"], x[ATR_RAW_PADDED]
    rows: dict[int, dict[str, float | None]] = {}

    def update(cache, bar_ts, open_, high_, low_, close_, vol_, cfg):
        cache.update_session_levels(bar_ts, open_, high_, low_, close_, cfg)

    for i, cache, _bar_ts in _replay_cache(x, config, update):
        rows[i] = _derive_session_levels(cache, float(closes[i]), float(atr[i]), tf, config)
    return SESSION_LEVEL.columns(n, rows.__getitem__)


_PATH_SESSION_ACCUMULATOR = (
    "the session accumulator state, its session-boundary resets and the exclusion of row 0 depend "
    "on where the series starts"
)

KERNELS = (
    Kernel(
        name="rolling_poc",
        outputs=(_POC,),
        inputs=("high", "low", "close", "volume", "tf"),
        memory=lambda config: config.session_vp_rolling_window - 1,
        compute=_compute_rolling_poc,
    ),
    Kernel(
        name="session_vp",
        outputs=VP.outputs,
        inputs=("ts_dt", *_OHLCV[1:], _POC, ATR_RAW_PADDED, "tf"),
        memory=lambda config: 0,
        compute=_compute_session_vp_columns,
        path_dependent=True,
        path_dependent_reason=_PATH_SESSION_ACCUMULATOR,
    ),
    Kernel(
        name="support_resistance",
        outputs=SR.outputs,
        inputs=("high", "low", "close", "volume", ATR_RAW_PADDED, "tf"),
        memory=lambda config: _sr_max_lookback(config) - 1,
        compute=_compute_support_resistance,
    ),
    Kernel(
        name="swing_structure",
        outputs=SWING_STRUCTURE.outputs,
        inputs=("high", "low", "close", ATR_RAW_PADDED),
        memory=lambda config: config.swing_lookback_bars - 1,
        compute=_compute_swing_structure_columns,
    ),
    Kernel(
        name="swing_momentum",
        outputs=SWING_MOMENTUM.outputs,
        inputs=("high", "low", "volume"),
        memory=lambda config: config.swing_momentum_lookback_bars - 1,
        compute=_compute_swing_momentum_columns,
    ),
    Kernel(
        name="session_levels",
        outputs=SESSION_LEVEL.outputs,
        inputs=("ts_dt", *_OHLCV, ATR_RAW_PADDED, "tf"),
        memory=lambda config: 0,
        compute=_compute_session_levels_columns,
        path_dependent=True,
        path_dependent_reason=_PATH_SESSION_ACCUMULATOR,
    ),
)
