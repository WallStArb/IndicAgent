"""Day-clustered block-bootstrap gate math — shared statistical core for any
construction that needs to ask "does this stratum's realized pnl clear a rigorous,
non-circular expectancy bar?"

Extracted from services/counterfactual_tracker.py (todo 249, 2026-08-04):
services/cross_sectional_spread_tracker.py was already importing these same
functions directly from counterfactual_tracker.py -- a Ring 2 service reaching into
another Ring 2 service's internals for what is actually generic statistics with zero
DB/Kafka/daemon dependency of its own. Moving the math here (Ring 1, matching
src/intelligence/statistics/ic_math.py's own precedent for exactly this situation)
gives every consumer a stable import target that doesn't depend on
counterfactual_tracker.py's own service lifecycle.

Pure functions only -- no DB, no config loading, no module-global mutable state
besides _DEFAULT_BOOTSTRAP_RANDOM_STATE.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from typing import Any

import numpy as np
from scipy.stats import bootstrap

_DEFAULT_BOOTSTRAP_RANDOM_STATE = 42


def frame_gate_passes(
    pnl_r_values: Sequence[float],
    cluster_ids: Sequence[Any],
    min_n: int,
    bootstrap_max_n: int,
    bootstrap_batch: int,
    bootstrap_random_state: int = _DEFAULT_BOOTSTRAP_RANDOM_STATE,
) -> tuple[bool, float, float]:
    """FRAME-04 day-clustered block-bootstrap exit gate (review H4).

    Aggregates pnl to per-cluster (calendar-day) means BEFORE resampling -- overlapping hold
    horizons make per-frame i.i.d. resampling anticonservative (a gate that can pass on noise
    defeats the phase's purpose). Below bootstrap_max_n day-clusters, uses
    scipy.stats.bootstrap (method='BCa', one-sided alternative='greater', batch=
    bootstrap_batch to cap peak resample-matrix memory). Above bootstrap_max_n clusters,
    BCa's jackknife (N leave-one-out evaluations) is computationally infeasible and its
    bias-correction negligible at that cluster count, so an analytic one-sided 95% CLT lower
    bound is used instead: mean - 1.645 * std(ddof=1) / sqrt(n_clusters).

    Returns (passes, ci_lower, ci_upper). passes iff ci_lower > 0.
    Returns (False, nan, nan) when len(pnl_r_values) < min_n (the alpha.scoring.
    min_strategy_n frame-count sufficiency floor) or when fewer than 2 day-clusters exist
    (a bootstrap CI cannot be formed from <2 blocks).

    bootstrap_random_state seeds scipy's BCa resampling (alpha.scoring.bootstrap_random_state
    APR key, default 42) so the frozen SHADOW-REVIEW.md "no post-hoc gate renegotiation" verdict
    is reproducible across identical re-runs (code-review WR-01) -- changing this key invalidates
    any prior gate verdict for cells that used the BCa path (len(cluster_means) <= bootstrap_max_n).
    """
    if len(pnl_r_values) < min_n:
        return False, float("nan"), float("nan")

    cluster_members: dict[Any, list[float]] = {}
    for pnl, cluster_id in zip(pnl_r_values, cluster_ids):
        cluster_members.setdefault(cluster_id, []).append(pnl)
    # Sorted at two levels (todo 172), not raw dict/list insertion order: cluster_id is a
    # calendar date (bar_ts::date), so sorting clusters also gives chronological order for
    # free. BCa resampling below is seeded with a FIXED bootstrap_random_state -- a fixed
    # seed draws specific index positions from cluster_means, so an array whose element
    # order depended on row-fetch order (TimescaleDB doesn't guarantee stable interleaving
    # across parallel chunk scans for a plain ORDER BY bar_ts) made the resulting CI
    # silently non-reproducible run-to-run on unchanged data. Sorting each cluster's own
    # pnl values before averaging additionally makes np.mean's summation order
    # deterministic -- floating-point addition is not associative, so leaving within-
    # cluster order to row-fetch order would still leave ULP-level noise in cluster_means
    # even after the (larger) inter-cluster ordering bug above is fixed.
    cluster_means = np.array(
        [float(np.mean(sorted(cluster_members[cid]))) for cid in sorted(cluster_members)],
        dtype=float,
    )

    if len(cluster_means) < 2:
        return False, float("nan"), float("nan")

    if len(cluster_means) <= bootstrap_max_n:
        result = bootstrap(
            (cluster_means,),
            np.mean,
            confidence_level=0.95,
            alternative="greater",
            method="BCa",
            batch=bootstrap_batch,
            random_state=np.random.default_rng(bootstrap_random_state),
        )
        ci_lower = float(result.confidence_interval.low)
        ci_upper = float(result.confidence_interval.high)
    else:
        # Analytic one-sided 95% CLT lower bound -- BCa's jackknife is infeasible at this
        # cluster count and its bias correction negligible here (review H4).
        n_clusters = len(cluster_means)
        mean = float(np.mean(cluster_means))
        std = float(np.std(cluster_means, ddof=1))
        ci_lower = mean - 1.645 * std / np.sqrt(n_clusters)
        ci_upper = float("inf")

    return bool(ci_lower > 0), ci_lower, ci_upper


def evaluate_frame_gate(
    rows: Iterable[dict[str, Any]],
    min_n: int,
    bootstrap_max_n: int,
    bootstrap_batch: int,
    bootstrap_random_state: int = _DEFAULT_BOOTSTRAP_RANDOM_STATE,
    group_key: Callable[[dict[str, Any]], tuple[Any, Any]] | None = None,
    min_clusters: int | None = None,
) -> list[dict[str, Any]]:
    """Pure grouping/aggregation core for day-clustered bootstrap gate evaluation.

    Takes an in-memory iterable of dicts with keys tf, regime, cluster_id, pnl_r -- pnl_r is
    the GROSS realized counterfactual_pnl_r (D-01); this function applies no adjustment to
    it whatsoever. Groups rows by group_key (default: (tf, regime), the FRAME-04 in-sample
    exit gate's original grouping -- omitting group_key preserves that behavior byte-for-byte).
    A second caller (the OOS regime-stratified promotion gate, todo 165) reuses this same
    core with group_key=lambda row: (row["direction"], row["regime"]) rather than
    duplicating the day-clustered bootstrap machinery.

    Passes each cell's per-frame calendar-date cluster_id straight into frame_gate_passes
    unmodified (day-clustered, review H4), and respects the min_n frame-count sufficiency
    floor via that same call.

    min_clusters (optional): a day-cluster coverage floor distinct from min_n's frame-count
    floor -- a cell can clear min_n on frame count alone while resting on too few
    independent day-observations for the bootstrap CI to mean anything (todo 165). When set,
    a cell with n_clusters < min_clusters is marked coverage="insufficient" and its "passes"
    field is forced to None (neither pass nor fail) regardless of frame_gate_passes' own
    verdict -- never silently counted as a failure. Cells at/above the floor (or when
    min_clusters is None, preserving current callers' behavior) get coverage="evaluated".

    Returns one verdict dict per group_key cell: tf, regime, n_frames, n_clusters, ci_lower,
    ci_upper, passes, coverage. (tf/regime keys are populated from the group_key tuple's two
    elements regardless of what group_key actually groups by, so existing callers that group
    by (tf, regime) see unchanged field names.)
    """
    if group_key is None:
        group_key = lambda row: (row["tf"], row["regime"])  # noqa: E731

    groups: dict[tuple[Any, Any], dict[str, list[Any]]] = {}
    for row in rows:
        key = group_key(row)
        bucket = groups.setdefault(key, {"pnl_r": [], "cluster_id": []})
        bucket["pnl_r"].append(row["pnl_r"])
        bucket["cluster_id"].append(row["cluster_id"])

    verdicts: list[dict[str, Any]] = []
    for (dim_a, dim_b), bucket in groups.items():
        passes, ci_lower, ci_upper = frame_gate_passes(
            bucket["pnl_r"],
            bucket["cluster_id"],
            min_n,
            bootstrap_max_n,
            bootstrap_batch,
            bootstrap_random_state,
        )
        n_clusters = len(set(bucket["cluster_id"]))
        coverage = "evaluated"
        if min_clusters is not None and n_clusters < min_clusters:
            coverage = "insufficient"
            passes = None
        verdicts.append(
            {
                "tf": dim_a,
                "regime": dim_b,
                "n_frames": len(bucket["pnl_r"]),
                "n_clusters": n_clusters,
                "ci_lower": ci_lower,
                "ci_upper": ci_upper,
                "passes": passes,
                "coverage": coverage,
            }
        )
    return verdicts
