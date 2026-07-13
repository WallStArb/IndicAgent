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

import numpy as np

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
