#!/usr/bin/env python3
"""
ops_ensemble_ablation.py -- todo 084: pre-committed leave-one-family-out ablation
protocol for ensemble degradation (G-2, fable-2026-07-07-renaissance-layer-refinements
section 11).

When ensemble OOS IC degrades between epochs, this script is the mechanical first
pass that replaces ad-hoc EIC-05-style forensics: for every feature_registry
group_name family (11 live values as of 2026-07-13: calendar, control, cross_tf,
macro, momentum, oscillator, regime, session, structure, volatility, volume), zero
that family's ensemble_weights, recompute the composite alpha score on the OOS
window through the IDENTICAL code path as the baseline, and re-measure IC per
(tf, regime, scale) stratum. Output: a marginal-attribution markdown table on
stdout plus a CorpusManifest("ensemble_ablation") run record scoped by
weight_version. Answers "what died" in one batch run before any human hypothesis
enters the room.

METHODOLOGY INVARIANTS (statistical correctness, non-negotiable):
- Baseline and ablated arms share one code path: X (float32, NULL -> 0.0, the
  ensemble_trainer.py convention) @ signed_weights, then cross-symbol per-bar mean
  pooling (the alpha_ensemble_ic POOLED convention, equivalence-tested against
  ensemble_ic_engine._aggregate_pooled_series), then per-scale stride subsampling,
  then ic_math measurement. The ONLY difference between arms is which weight
  entries are zeroed. The stored ensemble_alpha.alpha_score is used exclusively as
  a replication cross-check on the recomputed baseline (normalized max abs diff
  vs --reconstruction-tol), never as the baseline itself -- so a baseline/ablated
  methodology mismatch is structurally impossible, and a REPLICATION MISMATCH flag
  means the weights/regime labels drifted since ensemble_trainer ran (or this
  script has a bug); either way the stratum's attribution is untrustworthy and
  says so loudly.
- Executable returns only (CLAUDE.md Invariant 1): forward_returns is always read
  WHERE return_type = 'executable_open_to_open'.
- OOS only: fv.bar_ts >= alpha.validation.oos_start. The >= operator matches
  ops_oos_holdout_eval._oos_mask and partitions exactly against the training
  side's bar_ts < oos_start (ensemble_ic_engine) -- no gap, no overlap. A missing
  oos_start aborts loudly; it never silently measures the full corpus.
- Completeness gate: a return participates only when complete_<scale> AND
  isfinite(return_<scale>) (ic_engine.py convention), applied per symbol-row
  BEFORE pooling so censored returns never leak into a pooled mean.
- Sign convention: ensemble_weights has no ic_sign column; sign(ic_sharpe) is used
  (the stored ic_sharpe is the exact sign-carrying ic_input-resolved value the
  trainer held at scoring time, line 924). Verified empirically by the
  reconstruction check rather than assumed.
- IC math is reused from src/intelligence/statistics/ic_math.py (Spearman via
  compute_ic_vectorized, Fisher-z CI, fisher_z_difference_p for the between-arm
  delta -- conservative under the positive dependence of two arms measured on the
  same bars -- and one corpus-wide apply_bh_fdr pass over all delta p-values).
  Fisher-z (not the block bootstrap) is deliberate: this script must stay
  CI-comparable with alpha_ensemble_ic's pooled rows, which stay on Fisher-z this
  phase (143.1-CONTEXT resolved item 3). Upgrade both together.
- 'control' (canary) family stays in the sweep by design: it should be absent from
  ensemble_weights entirely (feature_status_at_eval='active' excludes canaries);
  if present, the report and manifest flag a governance breach, and a material IC
  delta from zeroing it indicts the ablation mechanism itself, not the model.

This report is diagnostic; remediation decisions are human/operator. Exit code is
always 0 (ops_ensemble_ic_diagnosis.py convention).

Usage:
    python scripts/ops/alpha/ops_ensemble_ablation.py
    python scripts/ops/alpha/ops_ensemble_ablation.py --weight-version run_2025122405150000
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

import dataclasses

import numpy as np

from src.intelligence.statistics.ic_math import (
    _fisher_z_ci,
    _nan_to_none,
    compute_ic_vectorized,
)

# Sentinel arm name for the all-families baseline. Dunder-wrapped so it can never
# collide with a real feature_registry.group_name (snake_case identifiers).
_BASELINE_ARM = "__baseline__"

# The canary family (feature_registry.is_control rows share this group_name).
_CONTROL_FAMILY = "control"

# Std threshold below which an arm's pooled score series is degenerate (near
# constant): Spearman IC is undefined on a constant series, so the arm is reported
# as DEGENERATE rather than as a fake IC of 0.0. [conventional] numerical-zero
# guard, same magnitude as ic_math's internal 1e-10/1e-12 denominators -- a
# statistical concept definition, not a tunable (APR-exempt).
_DEGENERATE_STD = 1e-12

# Default for --reconstruction-tol: max |recomputed - stored| / std(stored) allowed
# before flagging REPLICATION MISMATCH. ensemble_trainer.py's own float32
# validation (its lines 810-822 comment) measured worst-case ~0.2% relative
# divergence at the mv_condition_max gate boundary; 1% gives headroom for the
# float32 X reconstruction while still catching any sign/ordering/NaN-handling bug
# (which produce O(100%) distortions, not O(1%)). CLI-overridable; scripts/ sit
# outside the APR src/services mandate (EIC-05 fallback-constant precedent).
_DEFAULT_RECONSTRUCTION_TOL = 0.01

# Tolerance for the CI-bracket boundary check in _clamp_ci_to_ic: how far
# _fisher_z_ci's raw output may fall outside [ci_lower, ci_upper] <=> ic before
# it is treated as float64 tanh/arctanh saturation noise (observed magnitude
# ~8e-11 at IC=+-1.0) rather than a genuine bug in _fisher_z_ci. 1e-6 sits many
# orders above that observed noise floor and many orders below any real
# statistical discrepancy -- a numerical-noise guard, not a tunable (APR-exempt,
# same reasoning as _DEGENERATE_STD above).
_CI_BOUNDARY_TOL = 1e-6


# ---------------------------------------------------------------------------
# Weight-vector kernels (pure)
# ---------------------------------------------------------------------------


def signed_weights_from_rows(weights: np.ndarray, ic_sharpes: np.ndarray) -> np.ndarray:
    """Replicate ensemble_trainer.py's `signed_weights = weights * ic_signs`
    (line 962) from stored ensemble_weights columns.

    ensemble_weights has no ic_sign column; sign is inferred from the stored
    ic_sharpe (the exact ic_input-resolved sign-carrying value the trainer wrote,
    line 924). ic_sharpe >= 0 -> +1 (never 0: a zero sign would silently zero the
    weight, and the champion's ic_ci_lower > 0 eligibility makes exact-zero
    ic_sharpe impossible for a weighted feature anyway). The reconstruction check
    against stored ensemble_alpha verifies this empirically per stratum.
    """
    signs = np.where(np.asarray(ic_sharpes, dtype=np.float64) < 0.0, -1.0, 1.0)
    return np.asarray(weights, dtype=np.float64) * signs


def zero_family(signed_weights: np.ndarray, group_names: list[str], family: str) -> np.ndarray:
    """Return a COPY of signed_weights with every entry belonging to `family`
    zeroed -- the leave-one-family-out arm. Copy semantics are load-bearing: arms
    must never mutate the shared baseline vector.
    """
    out = signed_weights.copy()
    mask = np.array([g == family for g in group_names], dtype=bool)
    out[mask] = 0.0
    return out


def weight_mass_fraction(signed_weights: np.ndarray, group_names: list[str], family: str) -> float:
    """Fraction of total ABSOLUTE weight mass carried by `family` (context column
    for the attribution table). Absolute, not signed: a contrarian feature's share
    must not net against longs. Returns 0.0 for an all-zero vector.
    """
    abs_w = np.abs(np.asarray(signed_weights, dtype=np.float64))
    total = float(abs_w.sum())
    if total < 1e-12:
        return 0.0
    mask = np.array([g == family for g in group_names], dtype=bool)
    return float(abs_w[mask].sum()) / total


# ---------------------------------------------------------------------------
# Cross-symbol pooling (pure) -- alpha_ensemble_ic POOLED convention
# ---------------------------------------------------------------------------


def apply_complete_gate(returns: np.ndarray, complete: np.ndarray) -> np.ndarray:
    """Censor incomplete forward returns BEFORE pooling: a return participates only
    when complete_<scale> is true AND the value is finite (services/ic_engine.py
    lines 1848-1850). Returns a copy with NaN at censored positions; NaN is then
    skipped by pool_means_by_bar, so a censored per-symbol return can never leak
    into a pooled cross-symbol mean.
    """
    out = np.asarray(returns, dtype=np.float64).copy()
    out[~np.asarray(complete, dtype=bool)] = np.nan
    return out


def pool_means_by_bar(bar_idx: np.ndarray, n_bars: int, values: np.ndarray) -> np.ndarray:
    """Cross-symbol mean per bar: the alpha_ensemble_ic POOLED aggregation grain
    (group by bar_ts within a fixed (tf, regime) stratum, average across symbols
    BEFORE any IC math -- ensemble_ic_engine._aggregate_pooled_series / RESEARCH
    Pitfall 5). Vectorized via bincount instead of reusing _aggregate_pooled_series
    directly because each stratum pools 12 arms over the same bar grouping and the
    dict-per-row oracle would rebuild row dicts per arm; equivalence with the
    oracle is pinned by test_pool_means_by_bar_matches_aggregate_pooled_series so
    the two implementations cannot silently diverge.

    Args:
        bar_idx: [n_rows] int array mapping each (symbol, bar) row to its bar's
            index in time-sorted unique-bar order (np.unique(..., return_inverse)).
        n_bars: number of distinct bars (len of np.unique's first output).
        values: [n_rows] float array; NaN entries are skipped (missing member,
            not a zero observation).

    Returns:
        [n_bars] float64 array of per-bar means; NaN where a bar has zero finite
        members (unmeasurable, never a silent 0.0).
    """
    values = np.asarray(values, dtype=np.float64)
    finite = np.isfinite(values)
    sums = np.bincount(bar_idx[finite], weights=values[finite], minlength=n_bars)
    counts = np.bincount(bar_idx[finite], minlength=n_bars)
    out = np.full(n_bars, np.nan)
    has_members = counts > 0
    out[has_members] = sums[has_members] / counts[has_members]
    return out


# ---------------------------------------------------------------------------
# Arm IC measurement + reconstruction check (pure)
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class ArmIC:
    """One arm's measured IC on one (stratum, scale) cell."""

    ic: float
    ci_lower: float | None
    ci_upper: float | None
    n: int


def _clamp_ci_to_ic(
    ci_lower: float, ci_upper: float, ic: float, tol: float = _CI_BOUNDARY_TOL
) -> tuple[float, float]:
    """Clamp a Fisher-z CI bracket so it encompasses the point estimate, but only
    when the pre-clamp violation is genuine float64 boundary noise.

    _fisher_z_ci's tanh/arctanh round-trip can land ci_upper a few 1e-11 below (or
    ci_lower a few 1e-11 above) the point estimate at the +-1.0 saturation
    boundary -- expected numerical noise, not a statistical error. This function
    absorbs only that: if ci_lower exceeds ic, or ic exceeds ci_upper, by more
    than `tol`, it raises loudly instead of silently swallowing the discrepancy,
    because a violation that large means _fisher_z_ci produced an invalid bracket
    (e.g. a sign error) -- a real bug that must not be masked as a "numerical
    precision safeguard" ("silent wrong answers are worse than loud crashes").

    Raises:
        ValueError: if either bound is violated by more than `tol`.
    """
    lower_violation = ci_lower - ic
    upper_violation = ic - ci_upper
    if lower_violation > tol:
        raise ValueError(
            f"_fisher_z_ci produced ci_lower={ci_lower!r} > ic={ic!r} by "
            f"{lower_violation!r}, exceeding tolerance {tol!r} -- this is larger "
            "than float64 boundary noise and indicates a real bug upstream, not "
            "a numerical-precision artifact."
        )
    if upper_violation > tol:
        raise ValueError(
            f"_fisher_z_ci produced ci_upper={ci_upper!r} < ic={ic!r} by "
            f"{upper_violation!r}, exceeding tolerance {tol!r} -- this is larger "
            "than float64 boundary noise and indicates a real bug upstream, not "
            "a numerical-precision artifact."
        )
    return float(np.clip(ci_lower, -1.0, ic)), float(np.clip(ci_upper, ic, 1.0))


def compute_arm_ic(
    pooled_alpha: np.ndarray,
    pooled_returns: np.ndarray,
    stride: int,
    min_reliable_n: int,
) -> ArmIC | None:
    """Measure one arm's Spearman IC with Fisher-z CI on a pooled per-bar series.

    THE shared measurement path: baseline and every ablated arm go through this
    exact function with the exact same pooled_returns/stride/min_reliable_n, so
    the only between-arm difference is the alpha series itself (identical-code-path
    invariant). Mirrors ensemble_ic_engine's per-cell sequence: stride subsample
    (independence of overlapping forward returns) -> finite-pair mask ->
    min_reliable_n gate -> compute_ic_vectorized -> _fisher_z_ci -> _clamp_ci_to_ic
    (bounds the CI to the point estimate, raising loudly on a non-noise-scale
    violation rather than silently masking it).

    Returns None when the cell is unmeasurable: fewer than min_reliable_n valid
    pairs after subsampling, or a degenerate (near-constant) alpha series --
    Spearman is undefined on a constant, and reporting 0.0 would be a silent wrong
    answer (e.g. zeroing the only weighted family must read DEGENERATE, not
    "exactly neutral").
    """
    sub_idx = np.arange(0, len(pooled_alpha), stride)
    alpha_sub = np.asarray(pooled_alpha, dtype=np.float64)[sub_idx]
    returns_sub = np.asarray(pooled_returns, dtype=np.float64)[sub_idx]
    valid = np.isfinite(alpha_sub) & np.isfinite(returns_sub)
    n_valid = int(valid.sum())
    if n_valid < min_reliable_n:
        return None
    alpha_valid = alpha_sub[valid]
    returns_valid = returns_sub[valid]
    if float(np.std(alpha_valid)) < _DEGENERATE_STD:
        return None
    ic_vector = compute_ic_vectorized(alpha_valid.reshape(-1, 1), returns_valid)
    ci_lower_arr, ci_upper_arr = _fisher_z_ci(ic_vector, n_valid)
    ic_val = float(ic_vector[0])
    ci_lower_val = float(ci_lower_arr[0])
    ci_upper_val = float(ci_upper_arr[0])
    ci_lower_val, ci_upper_val = _clamp_ci_to_ic(ci_lower_val, ci_upper_val, ic_val)
    return ArmIC(
        ic=ic_val,
        ci_lower=_nan_to_none(ci_lower_val),
        ci_upper=_nan_to_none(ci_upper_val),
        n=n_valid,
    )


def reconstruction_check(
    recomputed: np.ndarray, stored: np.ndarray, tol: float
) -> tuple[int, float | None, bool]:
    """Verify the recomputed baseline against stored ensemble_alpha.alpha_score.

    Compares only bars where a stored score exists (stored is NaN where the LEFT
    JOIN found no row). Normalization: max |recomputed - stored| / std(stored) --
    scale-free, robust to near-zero individual scores where a relative tolerance
    would explode. Zero overlap returns (0, None, True): SKIPPED, not a failure
    (the trainer may simply predate those OOS bars).

    A False here means the trainer's inputs drifted since it ran (re-run
    ensemble_trainer before trusting attribution) or this script's replication of
    the scoring formula is wrong -- either way the stratum's deltas are
    untrustworthy and the report must say so loudly.
    """
    mask = np.isfinite(np.asarray(stored, dtype=np.float64))
    n_compared = int(mask.sum())
    if n_compared == 0:
        return 0, None, True
    stored_masked = np.asarray(stored, dtype=np.float64)[mask]
    recomputed_masked = np.asarray(recomputed, dtype=np.float64)[mask]
    max_abs_diff = float(np.max(np.abs(recomputed_masked - stored_masked)))
    denom = max(float(np.std(stored_masked)), 1e-12)
    norm_max_diff = max_abs_diff / denom
    return n_compared, norm_max_diff, norm_max_diff <= tol
