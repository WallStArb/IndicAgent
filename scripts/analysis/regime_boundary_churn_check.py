"""Regime boundary-churn materiality diagnostic (todo 080 / L5-1 Phase 0).

Read-only. Measures whether hard-argmax cross-sectional regime-label boundary crossings
are a materially destructive source of alpha_score discontinuity, per a pre-committed
decision gate, BEFORE any soft-blending scoring mechanism is designed. See
docs/plans/2026-07-15-regime-boundary-churn-diagnostic-design.md for full rationale.

Decision gate, per (regime_group, tf) -- both required:
  1. Boundary-adjacent timestamps are >= BOUNDARY_ADJACENT_FRACTION_GATE of all timestamps.
  2. Median boundary-crossing effect size >= EFFECT_SIZE_MULTIPLIER_GATE x the clean
     (same-regime-only) bar-to-bar alpha_score noise floor.

V1 scope: regime_group='equity' only -- matches ensemble_trainer.py's current hardcoded
scope (not yet regime_group-aware). 'rates' has no trained ensemble_weights; cells with no
trained weights report via the untrained-neighbor path (Task 8), not a separate code path.

Results reflect whichever ensemble_weights/ensemble_alpha are live when this runs --
preliminary, cheap to re-run after any corpus refresh, not a permanent verdict.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

# Sample size target across all timeframes combined (~50k rows gives ample power for a
# median-based effect-size comparison without pulling the full corpus).
SAMPLE_SIZE_TARGET = 50_000
# Hard cap per tf so one large timeframe (5m) can't starve smaller ones (1d) of
# representation in the proportional allocation.
HARD_CAP_PER_TF = 20_000
# Boundary window = this many multiples of the signal's own median bar-to-bar step size.
# Self-calibrating: generalizes across bounded [0,1] signals (vix_pct, breadth_frac) and
# unbounded z-scores (curve_z, credit_z) without group-specific window logic.
WINDOW_STEP_MULTIPLIER = 2.0
# Decision gate criterion 1: boundary-adjacent timestamps must be at least this fraction of
# all timestamps in a (regime_group, tf) cell for the churn effect to be aggregately material.
BOUNDARY_ADJACENT_FRACTION_GATE = 0.05
# Decision gate criterion 2: median boundary-crossing effect size must exceed this multiple
# of the clean noise floor to be distinguishable from ordinary feature-driven movement.
EFFECT_SIZE_MULTIPLIER_GATE = 1.5

TFS: tuple[str, ...] = ("5m", "15m", "1h", "1d")
REGIME_GROUP = "equity"


@dataclass(frozen=True)
class BoundaryAdjacency:
    axis1_adjacent: bool
    axis2_adjacent: bool
    actual_label: str
    neighbor_labels: tuple[str, ...]


@dataclass(frozen=True)
class AlignedWeights:
    feature_names: tuple[str, ...]
    signed_weights_a: np.ndarray
    signed_weights_b: np.ndarray


@dataclass(frozen=True)
class CellVerdict:
    regime_group: str
    tf: str
    boundary_adjacent_fraction: float
    n_boundary_adjacent_timestamps: int
    n_total_timestamps: int
    median_effect_size: float
    clean_noise_floor: float
    n_untrained_neighbor_bars: int
    n_scored_bars: int
    criterion_1_pass: bool
    criterion_2_pass: bool
    overall_pass: bool


def derive_boundary_window(
    step_series: np.ndarray, multiplier: float = WINDOW_STEP_MULTIPLIER
) -> float:
    """Median absolute bar-to-bar step size of a regime signal, scaled by multiplier.

    Self-calibrating boundary window: derived from the signal's own typical movement
    rather than an externally imposed percentage, so it generalizes to both bounded [0,1]
    signals and unbounded z-scores without group-specific logic.
    """
    if len(step_series) < 2:
        return 0.0
    steps = np.abs(np.diff(step_series))
    return float(np.median(steps)) * multiplier
