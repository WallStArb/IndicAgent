#!/usr/bin/env python3
"""CounterfactualTracker — oneshot that fills alpha_frames geometry and closes each frame
via a direction-aware four-trigger state machine (FRAME-02/03), then evaluates the FRAME-04
day-clustered block-bootstrap exit gate.

Phase 142B, Plan 02. Depends on Plan 01's alpha_frames schema (migration 214) and
AlphaFrameWriter's compute_frame_geometry (imported here, never duplicated).

CORRECTNESS INVARIANTS:
- determine_exit is DIRECTION-AWARE (review H3, the single most important fix in this plan):
  for direction='short' the stop sits ABOVE entry (bar.high >= stop -> closed_stop) and the
  target sits BELOW (bar.low <= target -> closed_target), and pnl_r's sign flips. A long-only
  comparison would close every short frame as an instant false stop, silently corrupting
  ~half the corpus and the FRAME-04 verdict built on it.
- Fills are executable, not theoretical (review L2): a gap-through-stop fills at the worse of
  (bar.open, stop_price); mirrored for shorts. The same executable-returns discipline as
  Invariant 1, applied to frame exits.
- A frame with zero observed bars stays open -- never writes a NULL pnl (review L3b).
- Each open frame closes via exactly one of closed_stop / closed_target / closed_max_hold /
  closed_ic_decay, in strict priority order (stop checked before target on a same-bar
  both-hit).
- The bar-path scan and the ATR/geometry fill happen in ONE streaming named-cursor sweep per
  (symbol, tf) cell (review H2/M2/M4) -- no per-frame round-trip, no feature_vectors ATR read
  (that column doesn't exist; ATR is computed from market_data_ohlcv, review H2).
- ProcessPoolExecutor workers return list[dict] only; the serial write happens in the main
  process, flushed per-symbol as each worker result arrives (never one aggregate write over
  all symbols -- anti-OOM, DAG invariant #3).
- FRAME-04's exit gate is a DAY-CLUSTERED BLOCK BOOTSTRAP (review H4): frames are aggregated
  to per-calendar-day means before resampling (overlap-aware -- hold horizons up to 60 bars
  mean adjacent frames share most of their price path) -- BCa when the day-cluster count is
  small enough for a feasible jackknife, an analytic CLT lower bound above that (BCa's
  jackknife is infeasible at 10^6-row cells). Evaluated on GROSS counterfactual_pnl_r (D-01).
- The alpha_ensemble_ic row age consumed for the IC-decay trigger is instrumented (D-10); the
  read is never blocked on freshness (D-08). A recurring ensemble_ic_engine cadence is
  explicitly out of scope for this phase (D-09, follow-on todo 089).

Usage:
    python services/counterfactual_tracker.py [--backfill]
    python services/counterfactual_tracker.py --evaluate-gate
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, NamedTuple

import numpy as np
from scipy.stats import bootstrap


class Bar(NamedTuple):
    """One OHLC bar. `open` is required for executable gap-through fills (review L2)."""

    open: float
    high: float
    low: float
    close: float


@dataclass(frozen=True)
class ExitResult:
    """Result of determine_exit: which trigger fired, how many bars it took, and the
    executable exit price."""

    status: str
    bars: int
    exit_price: float | None


def determine_exit(
    direction: str,
    bars_since_entry: Sequence[Bar],
    stop_price: float,
    target_price: float,
    hold_max_bars: int,
    ic_ci_lower: float | None,
) -> ExitResult | None:
    """FRAME-02/03 direction-aware four-trigger exit state machine.

    Priority per bar (stop checked before target -- conservative on a same-bar both-hit):
      direction='long':  (1) bar.low <= stop_price -> closed_stop, exit = min(bar.open, stop)
                          (2) bar.high >= target_price -> closed_target, exit = target
      direction='short': (1) bar.high >= stop_price -> closed_stop, exit = max(bar.open, stop)
                          (2) bar.low <= target_price -> closed_target, exit = target
      both directions:   (3) i >= hold_max_bars -> closed_max_hold, exit = bar.close

    After the bar loop with no per-bar exit: (4) ic_ci_lower is not None and < 0 ->
    closed_ic_decay, exit = last bar.close; otherwise the frame stays open (returns None).
    The ic_ci_lower value is used as given regardless of the underlying row's age (D-08) --
    this function takes the value already fetched, it does not gate on freshness itself.

    An empty bar list returns None immediately -- the frame stays open, never a fabricated
    close with a NULL pnl (review L3b). `bars` on the returned ExitResult is 1-indexed from
    entry (the number of bars observed before/at the exit trigger).
    """
    if direction not in ("long", "short"):
        raise ValueError(f"determine_exit: unknown direction {direction!r}")
    if not bars_since_entry:
        return None

    for i, bar in enumerate(bars_since_entry, start=1):
        if direction == "long":
            if bar.low <= stop_price:
                return ExitResult("closed_stop", i, min(bar.open, stop_price))
            if bar.high >= target_price:
                return ExitResult("closed_target", i, target_price)
        else:  # direction == "short"
            if bar.high >= stop_price:
                return ExitResult("closed_stop", i, max(bar.open, stop_price))
            if bar.low <= target_price:
                return ExitResult("closed_target", i, target_price)
        if i >= hold_max_bars:
            return ExitResult("closed_max_hold", i, bar.close)

    if ic_ci_lower is not None and ic_ci_lower < 0:
        return ExitResult("closed_ic_decay", len(bars_since_entry), bars_since_entry[-1].close)
    return None


def compute_frame_pnl_r(
    direction: str, entry_price: float, stop_price: float, exit_price: float
) -> float:
    """Direction-aware realized P&L in R (risk multiples).

    risk = abs(entry_price - stop_price) -- the stop distance, always positive.
    long -> (exit_price - entry_price) / risk ; short -> (entry_price - exit_price) / risk.
    A stop-out is ~ -1.0 R in both directions; a target hit is ~ +target_r_multiple R.
    """
    if direction not in ("long", "short"):
        raise ValueError(f"compute_frame_pnl_r: unknown direction {direction!r}")
    risk = abs(entry_price - stop_price)
    if direction == "long":
        return (exit_price - entry_price) / risk
    return (entry_price - exit_price) / risk


def frame_gate_passes(
    pnl_r_values: Sequence[float],
    cluster_ids: Sequence[Any],
    min_n: int,
    bootstrap_max_n: int,
    bootstrap_batch: int,
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
    """
    if len(pnl_r_values) < min_n:
        return False, float("nan"), float("nan")

    cluster_members: dict[Any, list[float]] = {}
    for pnl, cluster_id in zip(pnl_r_values, cluster_ids):
        cluster_members.setdefault(cluster_id, []).append(pnl)
    cluster_means = np.array(
        [float(np.mean(values)) for values in cluster_members.values()], dtype=float
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
