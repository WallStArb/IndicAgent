"""Canonical gradient transformation functions for all plugin tiers.

Replaces binary scoring shortcuts (hard thresholds, step functions, boolean
clamps) with continuous gradient outputs per the Renaissance principle:
"never drop data that could contain signal."

Every function takes scalar inputs and returns scalar float. Plugins vectorize
if needed. All functions are stateless with no side effects. Uses only the
math module (no numpy) since these are scalar primitives.

Typical usage in a plugin:
    from src.intelligence.utils.gradient_utils import linear_ramp, sigmoid_score

    # Instead of: score = 1.0 if rsi > 70 else 0.0
    score = linear_ramp(rsi, 30, 70)  # continuous 0-1 gradient
"""

from __future__ import annotations

import math

__all__ = [
    "linear_ramp",
    "threshold_decay",
    "sigmoid_score",
    "z_score_to_score",
    "session_progress",
    "hmm_regime_weight",
    "freshness_decay",
    "streak_score",
]


def linear_ramp(
    x: float,
    lo: float,
    hi: float,
    out_lo: float = 0.0,
    out_hi: float = 1.0,
) -> float:
    """Piecewise-linear map from [lo, hi] to [out_lo, out_hi], clamped at boundaries.

    The canonical "distance-from-threshold" gradient. Replaces patterns like
    ``score = 1.0 if x > threshold else 0.0`` with a continuous ramp.

    When lo == hi, returns out_hi if x >= lo, else out_lo.

    Parameters
    ----------
    x : float
        Input value.
    lo : float
        Lower bound of the input domain.
    hi : float
        Upper bound of the input domain.
    out_lo : float
        Output value at the lower bound (default 0.0).
    out_hi : float
        Output value at the upper bound (default 1.0).

    Returns
    -------
    float
        Value in [out_lo, out_hi] corresponding to x's position in [lo, hi].

    Examples
    --------
    >>> linear_ramp(50, 30, 70)
    0.5
    >>> linear_ramp(50, 30, 70, 0.3, 0.9)
    0.6
    """
    # NaN safety: return out_lo for non-finite inputs
    if not math.isfinite(x):
        return out_lo

    if lo >= hi:
        return out_hi if x >= lo else out_lo

    fraction = (x - lo) / (hi - lo)
    return max(out_lo, min(out_hi, out_lo + fraction * (out_hi - out_lo)))


def threshold_decay(
    x: float,
    center: float,
    width: float,
    peak: float = 1.0,
    floor: float = 0.0,
) -> float:
    """Score that peaks at center and linearly decays to floor over +/- width.

    Triangular/tent function: ``peak * max(0, 1 - abs(x - center) / width)``
    clamped to floor. Useful for proximity-to-level scoring where the signal
    should be strongest at a specific value and fade with distance.

    Replaces patterns like ``score = 1.0 if abs(x - level) < tolerance else 0.0``.

    Parameters
    ----------
    x : float
        Input value.
    center : float
        Value where the peak occurs.
    width : float
        Distance from center where the score reaches floor.
    peak : float
        Maximum score at center (default 1.0).
    floor : float
        Minimum score at edges (default 0.0).

    Returns
    -------
    float
        Score in [floor, peak].

    Examples
    --------
    >>> threshold_decay(50, 50, 10)
    1.0
    >>> threshold_decay(55, 50, 10)
    0.5
    """
    if width <= 0:
        return peak if x == center else floor
    distance_ratio = abs(x - center) / width
    raw = peak * max(0.0, 1.0 - distance_ratio)
    return max(floor, raw)


def sigmoid_score(x: float, center: float, steepness: float = 1.0) -> float:
    """Standard sigmoid: ``1 / (1 + exp(-steepness * (x - center)))``.

    For RSI extremes, z-score conversions, and any scenario where a smooth
    transition between 0 and 1 is needed. The center parameter shifts the
    inflection point; steepness controls how sharp the transition is.

    Replaces patterns like ``score = 1.0 if indicator > level else 0.0``.

    Parameters
    ----------
    x : float
        Input value.
    center : float
        Inflection point where output = 0.5.
    steepness : float
        Controls transition sharpness (default 1.0). Higher = sharper.

    Returns
    -------
    float
        Value in (0.0, 1.0) for finite inputs; exactly 0.5 at center.

    Examples
    --------
    >>> sigmoid_score(50, 50)
    0.5
    >>> round(sigmoid_score(51, 50), 4) > 0.5
    True
    """
    exponent = -steepness * (x - center)
    # Clamp exponent to avoid overflow in exp()
    exponent = max(-700.0, min(700.0, exponent))
    return 1.0 / (1.0 + math.exp(exponent))


def z_score_to_score(z: float, sigma_scale: float = 2.0) -> float:
    """Map absolute z-score to [0, 1] via linear_ramp.

    Delegates to ``linear_ramp(abs(z), 0, sigma_scale)``. For vol_spike
    intensity and other deviation-based scoring.

    Replaces patterns like ``int(abs(z) > 2)`` with a continuous gradient.

    Parameters
    ----------
    z : float
        Z-score value (positive or negative; absolute value is used).
    sigma_scale : float
        Z-score at which the output saturates at 1.0 (default 2.0).

    Returns
    -------
    float
        Value in [0.0, 1.0].

    Examples
    --------
    >>> z_score_to_score(0.0)
    0.0
    >>> z_score_to_score(4.0, sigma_scale=2.0)
    1.0
    """
    return linear_ramp(abs(z), 0.0, sigma_scale)


def session_progress(
    elapsed_frac: float,
    start_frac: float,
    end_frac: float,
) -> float:
    """Bell-shaped score: 1.0 at midpoint of [start, end], decays to 0 at edges.

    Tent function: position within [start, end] is computed, then a triangle
    peaks at the midpoint and decays linearly to 0 at both edges. Returns 0
    outside the window.

    Replaces patterns like ``int(start <= time <= end)`` with a gradient that
    captures how deep into the session window the current time is.

    Parameters
    ----------
    elapsed_frac : float
        Current position (e.g. fraction of session elapsed).
    start_frac : float
        Window start.
    end_frac : float
        Window end.

    Returns
    -------
    float
        Value in [0.0, 1.0]. 1.0 at midpoint, 0.0 at edges and outside.

    Examples
    --------
    >>> session_progress(0.5, 0.0, 1.0)
    1.0
    >>> session_progress(0.0, 0.0, 1.0)
    0.0
    """
    if end_frac <= start_frac:
        return 0.0
    # Outside window
    if elapsed_frac < start_frac or elapsed_frac > end_frac:
        return 0.0
    # Normalized position within [0, 1]
    position = (elapsed_frac - start_frac) / (end_frac - start_frac)
    # Tent function: peak at midpoint
    return max(0.0, 1.0 - abs(2.0 * position - 1.0))


def hmm_regime_weight(features: dict, regime_direction: str) -> float:
    """Extract continuous HMM regime probability as a weight.

    Maps direction strings to the corresponding HMM probability key:
    - "up" -> hmm_prob_trending_up
    - "down" -> hmm_prob_trending_down
    - "ranging" -> hmm_prob_ranging

    Falls back to 0.5 (neutral) if the key is missing. Clamps to [0, 1].

    Replaces patterns like ``weight = 1.0 if hmm_regime == 1 else 0.0``.

    Parameters
    ----------
    features : dict
        Feature dictionary containing HMM probability fields.
    regime_direction : str
        One of "up", "down", "ranging".

    Returns
    -------
    float
        Value in [0.0, 1.0]. 0.5 if feature key is missing.

    Examples
    --------
    >>> hmm_regime_weight({"hmm_prob_trending_up": 0.8}, "up")
    0.8
    >>> hmm_regime_weight({}, "up")
    0.5
    """
    key_map = {
        "up": "hmm_prob_trending_up",
        "down": "hmm_prob_trending_down",
        "ranging": "hmm_prob_ranging",
    }
    key = key_map.get(regime_direction)
    if key is None:
        return 0.5
    value = features.get(key)
    if value is None or not isinstance(value, (int, float)):
        return 0.5
    return max(0.0, min(1.0, float(value)))


def freshness_decay(touch_count: int, k: float = 0.5) -> float:
    """Exponential decay from 1.0 (fresh) toward 0.0 (stale).

    ``exp(-k * touch_count)``. For scoring how "fresh" a level or signal is
    based on how many times it has been tested/touched.

    Replaces patterns like ``fresh = 1.0 if touches == 0 else 0.0``.

    Parameters
    ----------
    touch_count : int
        Number of times the level/signal has been touched.
    k : float
        Decay rate (default 0.5). Higher k = faster decay.

    Returns
    -------
    float
        Value in (0.0, 1.0] for finite positive k and non-negative touch_count.

    Examples
    --------
    >>> freshness_decay(0)
    1.0
    >>> round(freshness_decay(1, k=0.5), 3)
    0.607
    """
    return math.exp(-k * max(0, touch_count))


def streak_score(streak_count: int, saturation: int = 5) -> float:
    """Linear ramp from 0 to 1 over [0, saturation].

    Delegates to ``linear_ramp(streak_count, 0, saturation)``. For scoring
    consecutive bar patterns where the signal strength grows with streak length.

    Replaces patterns like ``score = 1.0 if streak >= threshold else 0.0``.

    Parameters
    ----------
    streak_count : int
        Current streak length.
    saturation : int
        Streak length at which the score reaches 1.0 (default 5).

    Returns
    -------
    float
        Value in [0.0, 1.0].

    Examples
    --------
    >>> streak_score(0)
    0.0
    >>> streak_score(5, saturation=5)
    1.0
    >>> streak_score(3, saturation=5)
    0.6
    """
    return linear_ramp(float(streak_count), 0.0, float(saturation))
