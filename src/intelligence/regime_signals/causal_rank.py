"""Causal expanding percentile rank -- shared by every regime signal module.

Extracted from breadth_vol.py's vix_pct rank logic (Phase 141 P0-T2 look-ahead fix, todo 092
breadth_frac fix 2026-07-24) so every signal module ranks its raw values the same, tested,
look-ahead-safe way instead of duplicating the bisect logic per module or -- worse -- cutting
a raw level/z-score against a guessed absolute threshold never checked against the real
distribution (todo 092's root cause, confirmed twice: equity's breadth_frac at 0.40/0.60, and
rates' curve_z/credit_z at +-0.5/0.0, both clean round-number guesses producing severe
population imbalance -- 12-17x for equity, up to 30.8x for rates).
"""

from __future__ import annotations

import bisect
import math

import pandas as pd


def causal_expanding_rank(series: pd.Series) -> pd.Series:
    """Causal bisect-based expanding percentile rank -- generic over any input series.

    Each position's rank is computed against all PRIOR valid values only -- never future
    ones. NaN guard: skip NaN values (do not insert into window -- preserves bisect sort
    invariant). Tie handling: average rank = (bisect_left + bisect_right) / 2 / n. Two equal
    values produce rank 0.5 (matches pandas 'average' tie behavior).
    """
    sorted_window: list[float] = []  # sorted; never contains NaN
    causal_ranks: list[float] = []

    for val in series:
        if math.isnan(val):
            # NaN input -> NaN output; do NOT insert into window
            causal_ranks.append(float("nan"))
            continue

        if not sorted_window:
            # First valid value: rank 1.0 (it's both min and max of a 1-element set)
            bisect.insort(sorted_window, val)
            causal_ranks.append(1.0)
            continue

        # Rank against PRIOR window (causal: insert AFTER computing)
        left = bisect.bisect_left(sorted_window, val)
        right = bisect.bisect_right(sorted_window, val)
        rank = (left + right) / 2 / len(sorted_window)
        bisect.insort(sorted_window, val)
        causal_ranks.append(rank)

    return pd.Series(causal_ranks, index=series.index, dtype=float)
