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

from services.cross_sectional_regime_model import _bucket  # noqa: E402

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


def _neighbors_across_axis(
    value: float, tiers: list[tuple[str, float]], window: float
) -> list[str]:
    """Tier names reachable by crossing a boundary within `window` of `value`.

    Loops every boundary (not just the two flanking value's own tier) so a narrow middle
    tier with a wide window correctly reports both neighbors, not just one.
    """
    boundaries = [upper for _, upper in tiers[:-1]]
    names = [name for name, _ in tiers]
    neighbors: list[str] = []
    for i, boundary in enumerate(boundaries):
        if abs(value - boundary) <= window:
            other_name = names[i + 1] if value < boundary else names[i]
            neighbors.append(other_name)
    return neighbors


def classify_timestamp_adjacency(
    sig1: float,
    sig2: float,
    tiers1: list[tuple[str, float]],
    tiers2: list[tuple[str, float]],
    window1: float,
    window2: float,
) -> BoundaryAdjacency:
    """Classify one (regime_group, tf, ts) timestamp's boundary adjacency.

    market_regimes is keyed (regime_group, tf, ts) with no symbol dimension -- this
    classifies the timestamp itself, shared by every symbol's row at that ts. Uses the
    production _bucket() function for the actual label so this can never silently drift
    from what cross_sectional_regime_model.py assigns in production.
    """
    label1 = str(_bucket(np.array([sig1]), tiers1)[0])
    label2 = str(_bucket(np.array([sig2]), tiers2)[0])
    actual_label = f"{label1}_{label2}"

    axis1_neighbors = _neighbors_across_axis(sig1, tiers1, window1)
    axis2_neighbors = _neighbors_across_axis(sig2, tiers2, window2)

    neighbor_labels: list[str] = []
    for n1 in axis1_neighbors:
        neighbor_labels.append(f"{n1}_{label2}")
    for n2 in axis2_neighbors:
        neighbor_labels.append(f"{label1}_{n2}")
    for n1 in axis1_neighbors:
        for n2 in axis2_neighbors:
            neighbor_labels.append(f"{n1}_{n2}")

    return BoundaryAdjacency(
        axis1_adjacent=bool(axis1_neighbors),
        axis2_adjacent=bool(axis2_neighbors),
        actual_label=actual_label,
        neighbor_labels=tuple(dict.fromkeys(neighbor_labels)),
    )


def align_weight_vectors(
    signed_weights_a: dict[str, float], signed_weights_b: dict[str, float]
) -> AlignedWeights:
    """Zero-pad both weight dicts onto the union of their feature names.

    Different regimes' ensemble_weights may cover different selected feature sets --
    a feature present in one but absent in the other must contribute correctly rather
    than being silently dropped or misaligned.
    """
    feature_names = tuple(sorted(set(signed_weights_a) | set(signed_weights_b)))
    a = np.array([signed_weights_a.get(f, 0.0) for f in feature_names], dtype=float)
    b = np.array([signed_weights_b.get(f, 0.0) for f in feature_names], dtype=float)
    return AlignedWeights(feature_names=feature_names, signed_weights_a=a, signed_weights_b=b)


def score_bar(
    feature_values: dict[str, float],
    feature_names: tuple[str, ...],
    signed_weights: np.ndarray,
) -> float:
    """alpha_score = X[bar] @ signed_weights -- the exact ensemble_trainer.py Step 6 pattern.

    signed_weights must already be weight * ic_sign (see the fetch layer, Task 6). Missing
    or non-finite feature values are treated as 0, matching alpha_score.py's convention.
    """
    x = np.array(
        [v if np.isfinite(v) else 0.0 for v in (feature_values.get(f, 0.0) for f in feature_names)],
        dtype=float,
    )
    return float(np.dot(x, signed_weights))
