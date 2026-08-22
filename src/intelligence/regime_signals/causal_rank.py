"""Causal expanding percentile rank -- shared by every regime signal module.

Extracted from breadth_vol.py's vix_pct rank logic (Phase 141 P0-T2 look-ahead fix, todo 092
breadth_frac fix 2026-07-24) so every signal module ranks its raw values the same, tested,
look-ahead-safe way instead of duplicating the bisect logic per module or -- worse -- cutting
a raw level/z-score against a guessed absolute threshold never checked against the real
distribution (todo 092's root cause, confirmed twice: equity's breadth_frac at 0.40/0.60, and
rates' curve_z/credit_z at +-0.5/0.0, both clean round-number guesses producing severe
population imbalance -- 12-17x for equity, up to 30.8x for rates).

Complexity: O(n log n) via a Fenwick tree (order-statistics BIT) over a coordinate-compressed
value domain -- rewritten 2026-08-21 from an O(n^2) list+bisect.insort implementation.
Production's own usage (daily-cadence macro series, corpus-wide `cross_sectional_regime_model.py`
batch step) never had enough rows to expose the old complexity (~150s total, corpus-wide), but
reuse against an intraday series (5m, ~392K rows/symbol) in a regime-candidate falsification
script turned an 8-hour run into a genuine operational problem -- see
tests/unit/test_regime_signals_causal_rank.py's test_scales_near_linearithmic_not_quadratic
for the empirical baseline this rewrite is measured against (a scaling-ratio test, not an
absolute wall-clock threshold -- kept environment-independent on purpose, see that test's own
docstring). Validated bit-for-bit equivalent to
the retired implementation via an independent scipy.stats.rankdata-based oracle (same test file),
not just "looks right" -- this function's output feeds live market_regimes labels, so behavioral
drift here has the same blast-radius class as an HMM_RANDOM_STATE change. Tested up to n=500,000;
if a future caller needs materially more than that, re-benchmark before assuming this still holds.

Note: the vectorized numpy preprocessing below (np.unique/np.searchsorted) has a fixed per-call
overhead that makes this implementation ~2x SLOWER than a plain bisect scan for a tiny series
(n<~30) -- confirmed by benchmark, not currently a live problem since every call site (below)
ranks a full history series once, never a small rolling window in a tight loop. If a future
caller reuses this per-window at small n, a size-gated bisect fallback would be the fix; not
added speculatively (YAGNI) since no such caller exists today.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


class _FenwickTree:
    """1-indexed Binary Indexed Tree over a fixed-size compressed value domain.

    Supports point-update (`add`) and prefix-sum (`prefix_sum`) in O(log size) each --
    the operation causal_expanding_rank needs to track "how many prior values fall at or
    below compressed index i" without ever rescanning the full window.
    """

    __slots__ = ("_size", "_tree")

    def __init__(self, size: int) -> None:
        self._size = size
        self._tree = [0] * (size + 1)

    def add(self, index: int, delta: int = 1) -> None:
        i = index + 1  # internal 1-indexing
        size = self._size
        tree = self._tree
        while i <= size:
            tree[i] += delta
            i += i & (-i)

    def prefix_sum(self, index: int) -> int:
        """Sum of counts for compressed indices [0, index] inclusive. index=-1 -> 0."""
        if index < 0:
            return 0
        i = index + 1
        tree = self._tree
        total = 0
        while i > 0:
            total += tree[i]
            i -= i & (-i)
        return total


def causal_expanding_rank(series: pd.Series) -> pd.Series:
    """Causal expanding percentile rank -- generic over any input series.

    Each position's rank is computed against all PRIOR valid values only -- never future
    ones. NaN guard: skip NaN values (do not insert into window). Tie handling: average
    rank = (left + right) / 2 / n, where left/right are the counts of prior valid values
    strictly-less-than / less-or-equal-to the current value -- two equal values produce
    rank 0.5 (matches pandas 'average' tie behavior). First valid value in the series always
    ranks 1.0 (compared against an empty window). Handles an all-NaN or empty input series
    without special-casing: the loop below simply never executes.
    """
    values = series.to_numpy(dtype=float)
    causal_ranks: list[float] = [float("nan")] * values.shape[0]

    valid_mask = ~np.isnan(values)
    valid_positions = np.flatnonzero(valid_mask)
    valid_values = values[valid_mask]

    # Coordinate-compress the value domain once (static value SET, not future time-ordering
    # information -- causality is preserved because the Fenwick tree below still only ever
    # contains values inserted strictly before the current position in the original series).
    unique_sorted = np.unique(valid_values)
    compressed = np.searchsorted(unique_sorted, valid_values)

    tree = _FenwickTree(unique_sorted.shape[0])
    # exact_counts[idx] tracks how many prior occurrences of compressed value `idx` have
    # been inserted -- lets `right` (count of prior values <= current) be derived from
    # `left` (count of prior values < current) in O(1) instead of a second O(log D) BIT
    # walk. Read before this iteration's insert, so it reflects PRIOR occurrences only.
    exact_counts = [0] * unique_sorted.shape[0]

    for n_seen, (pos, idx) in enumerate(
        zip(valid_positions.tolist(), compressed.tolist(), strict=True)
    ):
        if n_seen == 0:
            causal_ranks[pos] = 1.0
        else:
            left = tree.prefix_sum(idx - 1)
            right = left + exact_counts[idx]
            causal_ranks[pos] = (left + right) / 2 / n_seen
        tree.add(idx)
        exact_counts[idx] += 1

    return pd.Series(causal_ranks, index=series.index, dtype=float)
