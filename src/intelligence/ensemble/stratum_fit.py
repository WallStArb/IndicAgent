"""Stratum weight fit: the compute half of EnsembleTrainer._process_stratum.

Pure functions, Ring 1 -- no DB, no clock, no logging. The trainer and the Phase 179
walk-forward harness (docs/plans/2026-09-24-phase179-sleeve-walk-forward-prereg.md)
call the same code, so a walk-forward refit is the production fit by construction.

Two steps, split where the caller has to fetch the stratum's feature matrix:
  select_stratum      IC rows -> the selected features and their per-feature arrays
  fit_stratum_weights selection + training-window feature matrix -> weights

The fit takes no reference date. It used to age quality weights by the wall clock and
fall back to 1/n past alpha.ensemble.weight_stale_max_days; the exponential decay was a
no-op (derive_weights renormalizes a uniformly scaled vector) and the fallback silently
turned the 2026-09-22 champion into 1/n in every 1d stratum (todo 408). Staleness is a
question for whoever consumes the weights, not for the fit.
"""

from __future__ import annotations

import bisect
import dataclasses
from datetime import datetime

import numpy as np

from src.intelligence.ensemble.covariance import (
    compute_shrinkage_covariance,
    covariance_to_correlation,
)
from src.intelligence.ensemble.feature_selector import select_features_per_stratum
from src.intelligence.ensemble.weights import (
    cluster_deflate_weights,
    derive_weights,
    effective_n,
    mean_variance_weights,
)

# alpha.ensemble.weight_method values (E2, D-08). 'ic_proportional' (default) preserves
# v1 behavior byte-for-byte: derive_weights -> cluster_deflate_weights (binary cluster
# cap). 'mean_variance' combines over the already-computed Ledoit-Wolf covariance via
# w ~ Sigma^-1.ic_shrunk (Grinold-Kahn signal combination), gated on covariance condition
# number -- an ill-conditioned Sigma falls back to the proven cluster_deflate_weights path
# rather than emitting extreme unstable weights (RESEARCH.md Pitfall 3).
_VALID_WEIGHT_METHODS = frozenset({"ic_proportional", "mean_variance"})


@dataclasses.dataclass(frozen=True)
class StratumWeightResult:
    """Output of resolve_stratum_weights(): the final weight vector plus which method
    actually produced it (for logging/diagnostics -- 'mean_variance_fallback' means the
    condition-number gate tripped and cluster_deflate_weights was used instead)."""

    raw_weights: np.ndarray
    weights: np.ndarray
    method_used: str
    condition_number: float | None


def resolve_stratum_weights(
    weight_method: str,
    quality_weights: np.ndarray,
    cov_matrix: np.ndarray,
    corr_matrix: np.ndarray,
    ic_shrunk: np.ndarray,
    ic_signs: np.ndarray,
    max_feature_weight: float,
    max_cluster_corr: float,
    max_cluster_weight: float,
    mv_condition_max: float,
) -> StratumWeightResult:
    """Select and compute the per-stratum weight vector per alpha.ensemble.weight_method (E2, D-08).

    Pure function -- no DB/Kafka/logging -- so it is independently unit-testable without a
    live ensemble run. Callers (namely EnsembleTrainer._process_stratum) are responsible for
    emitting a structured log record when method_used == 'mean_variance_fallback' (T-142B1-04-03:
    a silent fallback that hides instability is a repudiation risk).

    Parameters
    ----------
    weight_method:
        'ic_proportional' (v1, default) or 'mean_variance' (E2). Any other value raises
        ValueError -- an unrecognized weight_method must fail loud, never silently default
        to the wrong path.
    quality_weights:
        IC-Sharpe-derived quality weights, the raw input to derive_weights()
        for the ic_proportional path (and the ic_proportional fallback path). Already
        positive-magnitude convention (Component E's sign-aware compute_quality_weight).
    cov_matrix, corr_matrix:
        The Ledoit-Wolf shrunk covariance and its derived correlation matrix, already computed
        by compute_shrinkage_covariance(X) every run regardless of weight_method.
    ic_shrunk:
        Per-feature IC vector already selected for this stratum (aliased consistently with
        E1's alpha.ensemble.ic_input resolution -- the same array select_features_per_stratum
        used as 'ic_sharpe'), fed to mean_variance_weights() UNCHANGED as its ic_shrunk
        argument -- never pre-multiplied by ic_signs (BLOCKER 3: the mathematically correct
        combination signs the OUTPUT of Sigma^-1.mu, not the input mu itself; see ic_signs).
    ic_signs:
        Per-feature full-sample IC sign (+1/-1), shape matching ic_shrunk. Applied to the
        OUTPUT of mean_variance_weights() (`ic_signs * mv_raw`) before derive_weights, converting
        the natural unconstrained-MV solution (which may carry negative entries for features
        that get combination-shorted, independent of their own sign) into the positive-magnitude
        convention derive_weights' `> 0` filter expects -- mirrors how quality_weights is
        already positive-convention for the ic_proportional path. NOT used by the ic_proportional
        branch (quality_weights is pre-signed via compute_quality_weight already).
    max_feature_weight, max_cluster_corr, max_cluster_weight, mv_condition_max:
        APR-backed thresholds (EnsembleConfig fields) passed through unchanged.

    Returns
    -------
    StratumWeightResult
        raw_weights: pre-cap/pre-deflation diagnostic weight vector (stored as the
            'raw_weight' column regardless of method). For the mean_variance success path
            this is the UNSIGNED mv_raw output (the pure Sigma^-1.ic_shrunk solve) -- the
            sign is applied only on the path into derive_weights, not stored back here.
        weights: final post-cap weight vector used for scoring.
        method_used: 'ic_proportional' | 'mean_variance' | 'mean_variance_fallback'.
        condition_number: the covariance condition number when the mean_variance path was
            attempted (success or fallback), else None.
    """
    if weight_method == "ic_proportional":
        raw_weights = derive_weights(quality_weights, max_feature_weight)
        weights = cluster_deflate_weights(
            raw_weights, corr_matrix, max_cluster_corr, max_cluster_weight
        )
        return StratumWeightResult(raw_weights, weights, "ic_proportional", None)

    if weight_method == "mean_variance":
        # ic_shrunk passed UNCHANGED (BLOCKER 3): Sigma^-1.(s.mu) != s.(Sigma^-1.mu) once a
        # contrarian is correlated with other selected features -- pre-signing the INPUT is
        # mathematically wrong. The mv_raw solve stays sign-naive; sign is applied to its
        # OUTPUT below, once, before derive_weights.
        mv_raw, cond = mean_variance_weights(cov_matrix, ic_shrunk, mv_condition_max)
        if mv_raw is not None:
            # Success path (D-08): reuse derive_weights' per-feature cap + filter logic
            # on the SIGNED MV output, unchanged in spirit from the ic_proportional path
            # (whose quality_weights input is already positive-convention). Cap/sign
            # are NOT folded into mean_variance_weights() itself -- they run here.
            # cluster_deflate_weights is deliberately SKIPPED: Sigma^-1.IC already
            # decorrelates continuously, so binary cluster capping would double-penalize.
            mv_raw_signed = ic_signs * mv_raw
            weights = derive_weights(mv_raw_signed, max_feature_weight)
            return StratumWeightResult(mv_raw, weights, "mean_variance", cond)
        # Ill-conditioned Sigma (Pitfall 3): fall back to the proven cluster-deflation
        # path rather than emitting extreme offsetting weights from an unreliable Sigma^-1
        # solve. Caller MUST log this -- never a silent skip (T-142B1-04-03).
        raw_weights = derive_weights(quality_weights, max_feature_weight)
        weights = cluster_deflate_weights(
            raw_weights, corr_matrix, max_cluster_corr, max_cluster_weight
        )
        return StratumWeightResult(raw_weights, weights, "mean_variance_fallback", cond)

    raise ValueError(
        f"Unknown alpha.ensemble.weight_method value: {weight_method!r}. "
        f"Valid values: {sorted(_VALID_WEIGHT_METHODS)}"
    )


@dataclasses.dataclass(frozen=True)
class StratumSelectionResult:
    """The features one stratum trains on, in IC-selection order, with their per-feature
    IC arrays aligned to feature_names, and the IC window they were all measured on."""

    feature_names: list[str]
    quality_weights: np.ndarray
    ic_sharpes: np.ndarray
    ic_signs: np.ndarray
    ic_ci_lower: np.ndarray
    ic_ci_upper: np.ndarray
    lookahead_bars: list[int]
    training_window_end: datetime


@dataclasses.dataclass(frozen=True)
class StratumFitResult:
    """Output of fit_stratum_weights()."""

    result: StratumWeightResult
    shrinkage: float
    effective_n: float
    n_fit_rows: int


def select_stratum(
    ic_rows: list[dict],
    *,
    ic_input_column: str,
    sharpe_floor: float,
    feature_cols: list[str],
    min_passing_features: int,
) -> tuple[StratumSelectionResult | None, str | None, int]:
    """Pick the stratum's features from its eligible IC rows.

    Returns (selection, None, n) on success, or (None, reason, n) when the stratum can't be
    trained: 'min_features' when only n features survive selection, 'missing_cols' when only
    n of them have a feature_vectors column. Raises ValueError when the selected rows come
    from more than one IC window: the fit then has no single causal bound (todo 405).
    """
    selected = select_features_per_stratum(
        [{**dict(r), "ic_sharpe": r[ic_input_column]} for r in ic_rows],
        sharpe_floor=sharpe_floor,
    )
    if len(selected) < min_passing_features:
        return None, "min_features", len(selected)
    columns = set(feature_cols)
    kept = [r for r in selected if r["feature_name"] in columns]
    if len(kept) < min_passing_features:
        return None, "missing_cols", len(kept)
    windows = {r["training_window_end"] for r in kept}
    if len(windows) != 1:
        raise ValueError(
            f"stratum selection spans {len(windows)} training_window_end values "
            f"({sorted(windows)}); pin the IC read to one window (todo 405)"
        )
    return (
        StratumSelectionResult(
            feature_names=[r["feature_name"] for r in kept],
            quality_weights=np.array([float(r["quality_weight"]) for r in kept]),
            ic_sharpes=np.array([float(r["ic_sharpe"]) for r in kept]),
            ic_signs=np.array([float(r["ic_sign"]) for r in kept]),
            ic_ci_lower=np.array([float(r["ic_ci_lower"]) for r in kept]),
            ic_ci_upper=np.array([float(r["ic_ci_upper"]) for r in kept]),
            lookahead_bars=[int(r["lookahead_bars"]) for r in kept],
            training_window_end=windows.pop(),
        ),
        None,
        len(kept),
    )


def fit_stratum_weights(
    selection: StratumSelectionResult,
    X: np.ndarray,
    bar_ts: list[datetime],
    *,
    weight_method: str,
    max_feature_weight: float,
    max_cluster_corr: float,
    max_cluster_weight: float,
    mv_condition_max: float,
) -> StratumFitResult:
    """Fit the stratum's weights on the IC training window.

    X is [n_rows, n_features] in selection.feature_names order, with bar_ts aligned to its
    rows and sorted ascending. Only rows with bar_ts <= selection.training_window_end (the
    same inclusive bound ic_engine measures IC on) enter the covariance behind cluster
    deflation or the mean-variance solve; later rows would leak into the weights (todo 409).
    """
    n_fit_rows = bisect.bisect_right(bar_ts, selection.training_window_end)
    cov_matrix, shrinkage = compute_shrinkage_covariance(X[:n_fit_rows])
    result = resolve_stratum_weights(
        weight_method,
        selection.quality_weights,
        cov_matrix,
        covariance_to_correlation(cov_matrix),
        selection.ic_sharpes,
        selection.ic_signs,
        max_feature_weight,
        max_cluster_corr,
        max_cluster_weight,
        mv_condition_max,
    )
    return StratumFitResult(
        result=result,
        shrinkage=float(shrinkage),
        effective_n=effective_n(result.weights),
        n_fit_rows=n_fit_rows,
    )
