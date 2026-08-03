"""Unit tests: frame_gate_passes -- FRAME-04 day-clustered block-bootstrap exit gate
(review H4).

Frames opened on nearly every bar with hold horizons up to 60 bars share price paths almost
entirely within a (symbol, tf); i.i.d. per-frame resampling is anticonservative (a gate that
can pass on noise defeats the phase). These tests prove the day-clustered aggregation
actually bites (wider/stricter CI than naive per-frame resampling) and that the analytic-CLT
fallback engages above the BCa-feasible cluster count.
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np

_project_root = Path(__file__).parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from services.counterfactual_tracker import frame_gate_passes


def test_below_min_n_short_circuits():
    pnl = [0.5] * 10
    clusters = [f"day_{i}" for i in range(10)]
    passes, ci_lower, ci_upper = frame_gate_passes(
        pnl, clusters, min_n=30, bootstrap_max_n=5000, bootstrap_batch=1000
    )
    assert passes is False
    assert math.isnan(ci_lower)
    assert math.isnan(ci_upper)


def test_fewer_than_two_clusters_short_circuits():
    pnl = [0.5] * 40
    clusters = ["day_0"] * 40  # all frames land on a single calendar day
    passes, ci_lower, ci_upper = frame_gate_passes(
        pnl, clusters, min_n=30, bootstrap_max_n=5000, bootstrap_batch=1000
    )
    assert passes is False
    assert math.isnan(ci_lower)
    assert math.isnan(ci_upper)


def test_all_positive_many_days_passes():
    # Non-degenerate spread (BCa's jackknife is undefined on a zero-variance sample) but
    # comfortably, unambiguously positive.
    rng = np.random.default_rng(1)
    pnl = [float(0.5 + rng.normal(0, 0.05)) for _ in range(100)]
    clusters = [f"day_{i}" for i in range(100)]  # one frame per day -- no overlap
    passes, ci_lower, ci_upper = frame_gate_passes(
        pnl, clusters, min_n=30, bootstrap_max_n=5000, bootstrap_batch=1000
    )
    assert passes is True
    assert ci_lower > 0


def test_all_negative_fails():
    rng = np.random.default_rng(2)
    pnl = [float(-0.5 + rng.normal(0, 0.05)) for _ in range(100)]
    clusters = [f"day_{i}" for i in range(100)]
    passes, ci_lower, ci_upper = frame_gate_passes(
        pnl, clusters, min_n=30, bootstrap_max_n=5000, bootstrap_batch=1000
    )
    assert passes is False
    assert ci_lower < 0


def test_day_clustering_yields_wider_stricter_ci_than_naive_per_frame():
    """The overlap correction bites (review H4): resampling day-cluster MEANS (few
    effectively-independent blocks) produces a lower (stricter) ci_lower than naively
    resampling every individual frame as if it were independent, on the identical
    overlap-heavy sample (frames concentrated in a handful of days)."""
    rng = np.random.default_rng(42)
    day_means = [0.05, 0.10, 0.20, 0.25]
    pnl_values: list[float] = []
    day_cluster_ids: list[str] = []
    naive_cluster_ids: list[int] = []
    idx = 0
    for day_idx, day_mean in enumerate(day_means):
        for _ in range(50):
            pnl_values.append(float(day_mean + rng.normal(0, 0.001)))
            day_cluster_ids.append(f"day_{day_idx}")
            naive_cluster_ids.append(idx)  # unique id per frame -- degenerates to no clustering
            idx += 1

    _passes_clustered, ci_lower_clustered, _ = frame_gate_passes(
        pnl_values, day_cluster_ids, min_n=30, bootstrap_max_n=5000, bootstrap_batch=1000
    )
    _passes_naive, ci_lower_naive, _ = frame_gate_passes(
        pnl_values, naive_cluster_ids, min_n=30, bootstrap_max_n=5000, bootstrap_batch=1000
    )

    assert ci_lower_clustered < ci_lower_naive


def test_bootstrap_random_state_makes_ci_lower_reproducible():
    """Code-review WR-01: the frozen SHADOW-REVIEW.md 'no post-hoc gate renegotiation' verdict
    must be reproducible across identical re-runs. Two calls with the same seed on identical
    input (BCa path, a borderline-variance sample where entropy would otherwise matter) must
    return the exact same ci_lower."""
    rng = np.random.default_rng(99)
    pnl = [float(0.05 + rng.normal(0, 0.2)) for _ in range(60)]
    clusters = [f"day_{i}" for i in range(60)]

    _, ci_lower_a, _ = frame_gate_passes(
        pnl,
        clusters,
        min_n=30,
        bootstrap_max_n=5000,
        bootstrap_batch=1000,
        bootstrap_random_state=42,
    )
    _, ci_lower_b, _ = frame_gate_passes(
        pnl,
        clusters,
        min_n=30,
        bootstrap_max_n=5000,
        bootstrap_batch=1000,
        bootstrap_random_state=42,
    )

    assert ci_lower_a == ci_lower_b


def test_cluster_mean_array_order_independent_of_row_fetch_order():
    """Todo 172: cluster_means used to be built via dict insertion order
    (cluster_members.setdefault(...).append(...) over rows in fetch order), so a fixed-seed
    BCa resample on the SAME set of day-means at different array positions produced a
    different ci_lower -- non-reproducible run-to-run on unchanged data, since TimescaleDB
    doesn't guarantee stable row interleaving across parallel chunk scans for a plain
    ORDER BY bar_ts. Feeding the identical (pnl, cluster_id) pairs in two different row
    orders (simulating two different chunk-scan interleavings) must now return the exact
    same ci_lower/ci_upper, since cluster_means is sorted by cluster_id before resampling."""
    rng = np.random.default_rng(17)
    day_means = {f"day_{i}": float(rng.normal(0.05, 0.2)) for i in range(60)}
    pnl_a: list[float] = []
    clusters_a: list[str] = []
    for day, mean in day_means.items():
        for _ in range(5):
            pnl_a.append(float(mean + rng.normal(0, 0.01)))
            clusters_a.append(day)

    # Same (pnl, cluster_id) pairs, shuffled row order -- a different "chunk-scan
    # interleaving" of the identical underlying data.
    paired = list(zip(pnl_a, clusters_a))
    shuffle_rng = np.random.default_rng(99)
    shuffled = [paired[i] for i in shuffle_rng.permutation(len(paired))]
    pnl_b, clusters_b = (list(t) for t in zip(*shuffled))

    result_a = frame_gate_passes(
        pnl_a, clusters_a, min_n=30, bootstrap_max_n=5000, bootstrap_batch=1000
    )
    result_b = frame_gate_passes(
        pnl_b, clusters_b, min_n=30, bootstrap_max_n=5000, bootstrap_batch=1000
    )

    assert result_a == result_b


def test_analytic_clt_path_used_above_bootstrap_max_n():
    """When day-cluster count exceeds bootstrap_max_n, the analytic CLT lower bound is
    used instead of BCa (BCa's jackknife is infeasible at high cluster counts, review H4).
    Must return a finite ci_lower, not NaN/inf."""
    rng = np.random.default_rng(7)
    n_days = 20
    pnl_values: list[float] = []
    clusters: list[str] = []
    for day_idx in range(n_days):
        day_mean = 0.3  # comfortably positive so the analytic path clearly passes
        for _ in range(20):
            pnl_values.append(float(day_mean + rng.normal(0, 0.05)))
            clusters.append(f"day_{day_idx}")

    passes, ci_lower, ci_upper = frame_gate_passes(
        pnl_values, clusters, min_n=30, bootstrap_max_n=5, bootstrap_batch=1000
    )
    assert math.isfinite(ci_lower)
    assert ci_upper == float("inf")
    assert passes is True
