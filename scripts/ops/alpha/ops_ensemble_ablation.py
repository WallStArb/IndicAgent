#!/usr/bin/env python3
"""
ops_ensemble_ablation.py -- todo 084: pre-committed leave-one-family-out ablation
protocol for ensemble degradation (G-2, fable-2026-07-07-renaissance-layer-refinements
section 11).

When ensemble OOS IC degrades between epochs, this script is the mechanical first
pass that replaces ad-hoc EIC-05-style forensics: for every concept_registry
(domain='feature') group_name family (11 live values as of 2026-07-13: calendar, control, cross_tf,
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

import asyncio
import dataclasses
import functools
from typing import Any

import asyncpg
import numpy as np

from services._batch_utils import ACTIVE_SCALES_FALLBACKS_BY_TF
from services._batch_utils import canonicalize_active_scales as _canonicalize_active_scales
from services._batch_utils import cfg as _cfg
from services._batch_utils import load_apr_dict_async as _load_apr
from services._batch_utils import lookahead_by_scale_from_apr as _lookahead_by_scale_from_apr
from services._batch_utils import lookaheads_for_tf as _lookaheads_for_tf
from services.ensemble_ic_engine import _SCALE_RETURN_COLUMNS
from src.config.settings import Settings
from src.intelligence.statistics.ic_math import (
    _fisher_z_ci,
    _nan_to_none,
    apply_bh_fdr,
    compute_ic_vectorized,
    fisher_z_difference_p,
)
from src.observability.corpus_manifest import CorpusManifest

# Sentinel arm name for the all-families baseline. Dunder-wrapped so it can never
# collide with a real concept_registry.group_name (snake_case identifiers).
_BASELINE_ARM = "__baseline__"

# The canary family (concept_registry.is_control rows share this group_name).
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


def _family_mask(group_names: list[str], family: str) -> np.ndarray:
    """Boolean membership mask: which weight-vector entries belong to `family`.
    Single shared home for the group_names == family comparison so
    zero_family/weight_mass_fraction/compute_stratum_attribution's family-loop
    setup cannot silently drift into three different mask idioms.
    """
    return np.asarray(group_names) == family


def zero_family(signed_weights: np.ndarray, group_names: list[str], family: str) -> np.ndarray:
    """Return a COPY of signed_weights with every entry belonging to `family`
    zeroed -- the leave-one-family-out arm. Copy semantics are load-bearing: arms
    must never mutate the shared baseline vector.
    """
    out = signed_weights.copy()
    out[_family_mask(group_names, family)] = 0.0
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
    return float(abs_w[_family_mask(group_names, family)].sum()) / total


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
    min_reliable_n gate -> compute_ic_vectorized -> _fisher_z_ci (which itself
    bounds the CI to the point estimate, raising loudly on a non-noise-scale
    violation rather than silently masking it -- ic_math.py's _clamp_ci_to_ic,
    todo 109).

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


# ---------------------------------------------------------------------------
# SQL + config binding + panel preparation
# ---------------------------------------------------------------------------

# Strata = the trainer's own output grain: (tf, regime) per weight_version, all
# rows symbol='UNIVERSE' (universe-level weights; 100% of live rows carry this).
_STRATA_SQL = """
    SELECT DISTINCT tf, regime
    FROM ensemble_weights
    WHERE weight_version = $1 AND symbol = 'UNIVERSE'
    ORDER BY tf, regime
"""

# Per-stratum weight vector joined to concept_registry (domain='feature') for the
# family label. The trainer's alignment gate guarantees every feature_name has
# exactly one concept_registry(domain='feature') row, so this join can never drop
# a weighted feature.
_WEIGHTS_SQL = """
    SELECT ew.feature_name, ew.weight, ew.ic_sharpe, freg.group_name
    FROM ensemble_weights ew
    JOIN concept_registry freg ON freg.name = ew.feature_name AND freg.domain = 'feature'
    WHERE ew.weight_version = $1 AND ew.symbol = 'UNIVERSE'
      AND ew.tf = $2 AND ew.regime = $3
    ORDER BY ew.feature_name
"""

# Sweep families from the registry at runtime (11 live values as of 2026-07-13),
# never a hardcoded list -- includes 'control' by design (see module docstring).
# group_name IS NOT NULL is NEW and necessary: concept_registry.group_name is
# nullable because domain='ensemble_strategy' rows (and migration 284's 2
# gate-less tombstone domain='feature' rows) have none; without the guard a NULL
# family would enter the ablation sweep as a spurious "family."
_FAMILIES_SQL = (
    "SELECT DISTINCT group_name FROM concept_registry "
    "WHERE domain = 'feature' AND group_name IS NOT NULL ORDER BY group_name"
)


def build_stratum_fetch_sql(feature_names: list[str], scales: tuple[str, ...]) -> str:
    """OOS panel fetch for one (tf, regime) stratum.

    Placeholders: $1=tf, $2=regime_label, $3=weight_version, $4=oos_start.
    - feature_vectors JOIN market_regimes: the trainer's exact stratum join
      (ensemble_trainer.py lines 792-799) -- feature_vectors.regime holds
      per-symbol HMM labels; the cross-sectional stratum label lives in
      market_regimes (regime_group='equity', tf, ts=bar_ts).
    - JOIN forward_returns with the executable filter (Invariant 1) plus this tf's
      ACTIVE return_* AND complete_* columns (todo 211 -- not all 4 unconditionally;
      matches what ic_engine.py actually measures for this tf) for pre-pooling
      completeness gating. return_* is NULL-masked in SQL when its own
      return_{scale}_suspect flag is set (todo 148 price-sanity guard) -- same
      CASE-in-SQL pattern as ensemble_ic_engine.py's
      _WORKER_FETCH_SQL/_POOLED_WORKER_FETCH_SQL, required to keep this harness's
      pool_means_by_bar an honest replica of production's _aggregate_pooled_series
      (pinned by test_pool_means_by_bar_matches_aggregate_pooled_series) now that the
      production function excludes suspect values from its cross-symbol mean.
    - LEFT JOIN ensemble_alpha scoped to this weight_version: stored baseline for
      the replication check only (LEFT: missing stored rows are a skipped check,
      not lost measurement bars).
    - fv.bar_ts >= $4: the OOS boundary, >= per ops_oos_holdout_eval._oos_mask,
      exactly complementary to the training side's bar_ts < oos_start.
    - ORDER BY fv.bar_ts, fv.symbol: the trainer's scoring order.
    feature_names come from ensemble_weights/information-schema-governed registry
    rows, not user input (same trust argument as the trainer's col_list f-string).
    """
    col_list = ", ".join(f'fv."{c}"' for c in feature_names)
    return_cols = ", ".join(
        f"CASE WHEN fr.{_SCALE_RETURN_COLUMNS[s]}_suspect THEN NULL "
        f"ELSE fr.{_SCALE_RETURN_COLUMNS[s]} END AS {_SCALE_RETURN_COLUMNS[s]}"
        for s in scales
    )
    complete_cols = ", ".join(f"fr.complete_{s}" for s in scales)
    return f"""
        SELECT fv.symbol, fv.bar_ts, {col_list}, {return_cols}, {complete_cols},
               ea.alpha_score AS stored_alpha
        FROM feature_vectors fv
        JOIN market_regimes mr
          ON mr.regime_group = 'equity' AND mr.tf = fv.tf AND mr.ts = fv.bar_ts
        JOIN forward_returns fr
          ON fr.symbol = fv.symbol AND fr.tf = fv.tf AND fr.bar_ts = fv.bar_ts
          AND fr.return_type = 'executable_open_to_open'
        LEFT JOIN ensemble_alpha ea
          ON ea.symbol = fv.symbol AND ea.tf = fv.tf AND ea.bar_ts = fv.bar_ts
          AND ea.weight_version = $3
        WHERE fv.tf = $1 AND mr.regime_label = $2 AND fv.bar_ts >= $4
        ORDER BY fv.bar_ts, fv.symbol
    """


@dataclasses.dataclass(frozen=True)
class AblationConfig:
    """Frozen APR snapshot bound once at startup (compile-time binding, the
    EnsembleICConfig pattern). Fallback defaults are byte-identical to
    EnsembleICConfig.from_apr's for the shared keys -- a divergent fallback would
    silently measure with different gates on a DB missing a key. No new APR keys:
    every threshold here already exists under alpha.ic.*.

    lookahead_{scale}/active_scales are per-tf dicts, matching ICEngineConfig's
    exact shape -- todo 211 (2026-07-30): this previously read the pre-todo-146
    flat global alpha.ic.lookahead.{scale} keys (no {tf} component), silently
    computing every non-matching tf's stride against the wrong bar count. Fixed
    by mirroring ICEngineConfig.from_apr()'s per-tf resolution exactly, via the
    same shared services._batch_utils helpers.
    """

    subsample_min_stride: int
    min_reliable_n: int
    fdr_alpha: float
    lookahead_fast: dict[str, int]
    lookahead_mid: dict[str, int]
    lookahead_slow: dict[str, int]
    lookahead_extended: dict[str, int]
    active_scales: dict[str, tuple[str, ...]]

    def lookaheads_for(self, tf: str) -> dict[str, int]:
        return _lookaheads_for_tf(
            self.lookahead_fast,
            self.lookahead_mid,
            self.lookahead_slow,
            self.lookahead_extended,
            tf,
        )

    def active_scales_for(self, tf: str) -> tuple[str, ...]:
        return self.active_scales[tf]

    @classmethod
    def from_apr(cls, cfg: dict[str, Any]) -> AblationConfig:
        lookahead_by_scale = _lookahead_by_scale_from_apr(functools.partial(_cfg, cfg))
        active_scales = {
            tf: _canonicalize_active_scales(_cfg(cfg, f"alpha.ic.active_scales.{tf}", list(fb)))
            for tf, fb in ACTIVE_SCALES_FALLBACKS_BY_TF.items()
        }
        return cls(
            subsample_min_stride=_cfg(cfg, "alpha.ic.subsample_min_stride", 5),
            min_reliable_n=_cfg(cfg, "alpha.ic.min_reliable_n", 100),
            fdr_alpha=_cfg(cfg, "alpha.ic.fdr_alpha", 0.05),
            lookahead_fast=lookahead_by_scale["fast"],
            lookahead_mid=lookahead_by_scale["mid"],
            lookahead_slow=lookahead_by_scale["slow"],
            lookahead_extended=lookahead_by_scale["extended"],
            active_scales=active_scales,
        )


def prepare_stratum_arrays(
    fv_rows: list[Any], feature_names: list[str], scales: tuple[str, ...]
) -> tuple[np.ndarray, np.ndarray, dict[str, np.ndarray], np.ndarray]:
    """Convert fetched panel rows (asyncpg Records or dicts) into scoring arrays.

    X replicates ensemble_trainer.py lines 823-826 exactly: NULL -> 0.0, float32
    (the reconstruction check depends on matching the trainer's dtype path).
    Returns are complete-gated per row via apply_complete_gate. stored_alpha is
    NaN where the LEFT JOIN found no ensemble_alpha row.

    scales: this tf's active scale set (todo 211) -- only these columns exist in
    fv_rows (build_stratum_fetch_sql fetched exactly this set).

    Returns:
        (bar_ts_arr [n_rows] object, X [n_rows, n_features] float32,
         gated_returns_by_scale {scale: [n_rows] float64}, stored_alpha [n_rows]).
    """
    bar_ts_arr = np.array([r["bar_ts"] for r in fv_rows], dtype=object)
    X = np.array(
        [[float(r[c]) if r[c] is not None else 0.0 for c in feature_names] for r in fv_rows],
        dtype=np.float32,
    )
    gated_returns_by_scale: dict[str, np.ndarray] = {}
    for scale in scales:
        return_col = _SCALE_RETURN_COLUMNS[scale]
        raw = np.array(
            [float(r[return_col]) if r[return_col] is not None else np.nan for r in fv_rows]
        )
        complete = np.array([bool(r[f"complete_{scale}"]) for r in fv_rows])
        gated_returns_by_scale[scale] = apply_complete_gate(raw, complete)
    stored_alpha = np.array(
        [float(r["stored_alpha"]) if r["stored_alpha"] is not None else np.nan for r in fv_rows]
    )
    return bar_ts_arr, X, gated_returns_by_scale, stored_alpha


# ---------------------------------------------------------------------------
# Attribution assembly (pure)
# ---------------------------------------------------------------------------

_FLAG_ABSENT = "family absent from this stratum"
_FLAG_DEGENERATE = (
    "DEGENERATE (ablated composite near-constant; family was effectively the whole model)"
)
_FLAG_BASELINE_UNMEASURABLE = (
    "BASELINE UNMEASURABLE (insufficient N after stride/completeness gates)"
)
_FLAG_CONTROL_BREACH = (
    "CONTROL FAMILY CARRIES WEIGHT (governance breach: canaries must never be " "ensemble-eligible)"
)


@dataclasses.dataclass(frozen=True, kw_only=True)
class AttributionRow:
    """One line of the marginal-attribution table: one (stratum, scale, arm).

    family == _BASELINE_ARM rows describe the all-families baseline (ic_ablated/
    delta_ic/diff_p are None there). delta_ic = ic_baseline - ic_ablated: positive
    means removing the family REDUCED OOS IC, i.e. the family was contributing.
    ci_lower/ci_upper describe the arm this row measures (baseline row -> baseline
    CI; family row -> ablated-arm CI). Every field beyond the four identity fields
    (tf/regime/scale/family) defaults to its "unset" value so each construction
    site states only what it actually knows -- the baseline-unmeasurable/absent/
    degenerate branches never had those fields populated in the first place.
    """

    tf: str
    regime: str
    scale: str
    family: str
    n_features_zeroed: int = 0
    weight_mass_zeroed: float = 0.0
    n_obs: int = 0
    ic_baseline: float | None = None
    ci_lower: float | None = None
    ci_upper: float | None = None
    ic_ablated: float | None = None
    delta_ic: float | None = None
    diff_p: float | None = None
    bh_adjusted_p: float | None = None
    delta_passes_fdr: bool | None = None
    flag: str = ""


def compute_stratum_attribution(
    tf: str,
    regime: str,
    families: list[str],
    group_names: list[str],
    signed_weights: np.ndarray,
    X: np.ndarray,
    bar_idx: np.ndarray,
    n_bars: int,
    pooled_returns_by_scale: dict[str, np.ndarray],
    config: AblationConfig,
    baseline_scores: np.ndarray | None = None,
) -> list[AttributionRow]:
    """Leave-one-family-out attribution for one (tf, regime) stratum.

    Every arm -- the baseline and each family's zeroed variant -- goes through the
    identical sequence: X @ arm_weights (the trainer's scoring matmul, line 963),
    pool_means_by_bar (cross-symbol mean per bar), compute_arm_ic (stride
    subsample, gates, Spearman IC, Fisher-z CI). Pooled arm scores are computed
    ONCE per arm (pooling is scale-independent); the per-scale loop only re-runs
    the subsample + measurement step against that scale's gated returns.

    baseline_scores: precomputed X @ signed_weights, when the caller already has
    it (main() computes this for the reconstruction check and passes it here to
    avoid a redundant matmul over the full OOS panel); computed internally when
    omitted, e.g. by unit tests that don't exercise the reconstruction check.

    A family with zero weighted features in this stratum yields a _FLAG_ABSENT
    row per scale (delta None) -- 'control' landing here on every stratum is the
    EXPECTED outcome and doubles as the eligibility-filter check. A control family
    that DOES carry weight is measured normally but flagged _FLAG_CONTROL_BREACH
    (the single source of truth render_report/record_manifest read, rather than
    each re-deriving "family == control and weighted" independently).
    diff_p uses fisher_z_difference_p, which is conservative (over-estimates p)
    under the positive dependence of two arms measured on the same bars -- the
    safe direction for a postmortem attribution.
    """
    rows: list[AttributionRow] = []
    if baseline_scores is None:
        baseline_scores = X @ signed_weights

    pooled_by_arm: dict[str, np.ndarray] = {
        _BASELINE_ARM: pool_means_by_bar(bar_idx, n_bars, baseline_scores)
    }
    abs_weights = np.abs(signed_weights)
    total_mass = float(abs_weights.sum())
    family_n_features: dict[str, int] = {}
    family_mass: dict[str, float] = {}
    for family in families:
        mask = _family_mask(group_names, family)
        n_features = int(mask.sum())
        family_n_features[family] = n_features
        if n_features > 0:
            family_mass[family] = (
                float(abs_weights[mask].sum()) / total_mass if total_mass >= 1e-12 else 0.0
            )
            ablated_weights = zero_family(signed_weights, group_names, family)
            pooled_by_arm[family] = pool_means_by_bar(bar_idx, n_bars, X @ ablated_weights)

    tf_lookaheads = config.lookaheads_for(tf)
    for scale in config.active_scales_for(tf):
        stride = max(config.subsample_min_stride, tf_lookaheads[scale])
        pooled_returns = pooled_returns_by_scale[scale]
        baseline = compute_arm_ic(
            pooled_by_arm[_BASELINE_ARM], pooled_returns, stride, config.min_reliable_n
        )
        if baseline is None:
            rows.append(
                AttributionRow(
                    tf=tf,
                    regime=regime,
                    scale=scale,
                    family=_BASELINE_ARM,
                    flag=_FLAG_BASELINE_UNMEASURABLE,
                )
            )
            continue

        rows.append(
            AttributionRow(
                tf=tf,
                regime=regime,
                scale=scale,
                family=_BASELINE_ARM,
                n_obs=baseline.n,
                ic_baseline=baseline.ic,
                ci_lower=baseline.ci_lower,
                ci_upper=baseline.ci_upper,
            )
        )

        for family in families:
            n_features = family_n_features[family]
            is_control_breach = family == _CONTROL_FAMILY and n_features > 0
            if n_features == 0:
                rows.append(
                    AttributionRow(
                        tf=tf,
                        regime=regime,
                        scale=scale,
                        family=family,
                        n_obs=baseline.n,
                        ic_baseline=baseline.ic,
                        flag=_FLAG_ABSENT,
                    )
                )
                continue

            ablated = compute_arm_ic(
                pooled_by_arm[family], pooled_returns, stride, config.min_reliable_n
            )
            if ablated is None:
                rows.append(
                    AttributionRow(
                        tf=tf,
                        regime=regime,
                        scale=scale,
                        family=family,
                        n_features_zeroed=n_features,
                        weight_mass_zeroed=family_mass[family],
                        n_obs=baseline.n,
                        ic_baseline=baseline.ic,
                        flag=_FLAG_DEGENERATE,
                    )
                )
                continue

            delta_ic = baseline.ic - ablated.ic
            diff_p = fisher_z_difference_p(baseline.ic, baseline.n, ablated.ic, ablated.n)
            rows.append(
                AttributionRow(
                    tf=tf,
                    regime=regime,
                    scale=scale,
                    family=family,
                    n_features_zeroed=n_features,
                    weight_mass_zeroed=family_mass[family],
                    n_obs=ablated.n,
                    ic_baseline=baseline.ic,
                    ci_lower=ablated.ci_lower,
                    ci_upper=ablated.ci_upper,
                    ic_ablated=ablated.ic,
                    delta_ic=delta_ic,
                    diff_p=None if np.isnan(diff_p) else float(diff_p),
                    flag=_FLAG_CONTROL_BREACH if is_control_breach else "",
                )
            )
    return rows


def apply_delta_fdr(rows: list[AttributionRow], fdr_alpha: float) -> list[AttributionRow]:
    """One corpus-wide BH-FDR pass across every delta p-value (the project's
    one-multipletests-call-per-family convention, via ic_math.apply_bh_fdr).
    Informational, not a gate: the report prints bh_adjusted_p/delta_passes_fdr so
    an operator can distinguish real family deaths from multiplicity noise across
    ~strata x scales x families comparisons. Rows without a diff_p (baseline,
    absent, degenerate) pass through unchanged.
    """
    indexed_p = [(i, r.diff_p) for i, r in enumerate(rows) if r.diff_p is not None]
    if not indexed_p:
        return list(rows)
    reject, p_corrected = apply_bh_fdr([p for _, p in indexed_p], fdr_alpha)
    out = list(rows)
    for flat_idx, (row_idx, _) in enumerate(indexed_p):
        out[row_idx] = dataclasses.replace(
            out[row_idx],
            bh_adjusted_p=float(p_corrected[flat_idx]),
            delta_passes_fdr=bool(reject[flat_idx]),
        )
    return out


# ---------------------------------------------------------------------------
# Report rendering + manifest recording
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class ReplicationRecord:
    """Per-stratum baseline reconstruction check result (see reconstruction_check)."""

    tf: str
    regime: str
    n_bars: int
    n_compared: int
    norm_max_diff: float | None
    ok: bool


def _fmt(value: Any, digits: int = 4) -> str:
    """Uniform markdown cell formatting: '-' for None, fixed digits for floats."""
    if value is None:
        return "-"
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, float):
        return f"{value:.{digits}f}"
    return str(value)


def render_report(
    weight_version: str,
    oos_start: Any,
    families: list[str],
    rows: list[AttributionRow],
    replication: list[ReplicationRecord],
    config: AblationConfig,
    reconstruction_tol: float,
) -> list[str]:
    """Render the full markdown report as a list of lines (caller prints).

    Sections: header/config, replication check, per-(tf, regime, scale)
    attribution tables (families sorted by delta_ic descending -- biggest marginal
    contributors first), per-family cross-strata summary, control-family verdict.
    This report is diagnostic; remediation decisions are human/operator (EIC-05
    convention).
    """
    lines: list[str] = []
    lines.append("## Ensemble Ablation Report (todo 084, leave-one-family-out)")
    lines.append("")
    lines.append(f"- weight_version: `{weight_version}`")
    lines.append(f"- OOS window: `bar_ts >= {oos_start}` (alpha.validation.oos_start)")
    lines.append(f"- families swept: {', '.join(families)}")
    lines.append(
        f"- gates: min_reliable_n={config.min_reliable_n}, "
        f"subsample_min_stride={config.subsample_min_stride}, "
        f"fdr_alpha={config.fdr_alpha}, reconstruction_tol={reconstruction_tol}"
    )
    lines.append(
        "- delta_ic = ic_baseline - ic_ablated: positive means removing the family "
        "REDUCED OOS IC (the family was contributing). diff_p is conservative under "
        "the arms' positive dependence; bh_p is one corpus-wide BH-FDR pass."
    )
    # --- Section 1: replication check ---------------------------------------
    lines.append("")
    lines.append("### Section 1: Baseline replication check (recomputed vs stored ensemble_alpha)")
    lines.append("")
    mismatches = [r for r in replication if not r.ok]
    if mismatches:
        lines.append(
            "> **REPLICATION MISMATCH** in "
            f"{len(mismatches)}/{len(replication)} strata: the recomputed baseline "
            "does not match stored ensemble_alpha.alpha_score. Weights/regime labels "
            "have likely drifted since ensemble_trainer ran (or the ablation's "
            "replication is buggy). Attribution for flagged strata is UNTRUSTWORTHY; "
            "re-run ensemble_trainer for this weight_version, then re-run this report."
        )
        lines.append("")
    lines.append("| tf | regime | n_bars | n_compared | norm_max_diff | verdict |")
    lines.append("|---|---|---|---|---|---|")
    for r in replication:
        verdict = "ok" if r.ok else "REPLICATION MISMATCH"
        if r.n_compared == 0:
            verdict = "skipped (no stored overlap)"
        lines.append(
            f"| {r.tf} | {r.regime} | {r.n_bars} | {r.n_compared} | "
            f"{_fmt(r.norm_max_diff, 6)} | {verdict} |"
        )

    # --- Section 2: per-stratum attribution ---------------------------------
    lines.append("")
    lines.append("### Section 2: Marginal attribution per (tf, regime, scale)")
    untrusted = {(r.tf, r.regime) for r in mismatches}
    strata = sorted({(r.tf, r.regime, r.scale) for r in rows})
    for tf, regime, scale in strata:
        cell_rows = [r for r in rows if (r.tf, r.regime, r.scale) == (tf, regime, scale)]
        baseline_rows = [r for r in cell_rows if r.family == _BASELINE_ARM]
        header_suffix = " [UNTRUSTED: replication mismatch]" if (tf, regime) in untrusted else ""
        lines.append("")
        lines.append(f"#### {tf} / {regime} / {scale}{header_suffix}")
        lines.append("")
        if baseline_rows and baseline_rows[0].flag == _FLAG_BASELINE_UNMEASURABLE:
            lines.append(f"> {_FLAG_BASELINE_UNMEASURABLE}")
            continue
        family_rows = sorted(
            (r for r in cell_rows if r.family != _BASELINE_ARM),
            key=lambda r: (r.delta_ic is None, -(r.delta_ic or 0.0)),
        )
        b = baseline_rows[0]
        lines.append(
            f"baseline: ic={_fmt(b.ic_baseline)} "
            f"[{_fmt(b.ci_lower)}, {_fmt(b.ci_upper)}], n={b.n_obs}"
        )
        lines.append("")
        lines.append(
            "| family | n_feat | weight_mass | ic_ablated | delta_ic | diff_p | bh_p "
            "| sig | flag |"
        )
        lines.append("|---|---|---|---|---|---|---|---|---|")
        for r in family_rows:
            lines.append(
                f"| {r.family} | {r.n_features_zeroed} | {_fmt(r.weight_mass_zeroed)} "
                f"| {_fmt(r.ic_ablated)} | {_fmt(r.delta_ic)} | {_fmt(r.diff_p, 6)} "
                f"| {_fmt(r.bh_adjusted_p, 6)} | {_fmt(r.delta_passes_fdr)} | {r.flag} |"
            )

    # --- Section 3: per-family cross-strata summary --------------------------
    lines.append("")
    lines.append("### Section 3: Per-family summary across all measurable strata")
    lines.append("")
    lines.append(
        "| family | strata present | mean delta_ic | max delta_ic | fdr-significant cells |"
    )
    lines.append("|---|---|---|---|---|")
    for family in families:
        f_rows = [r for r in rows if r.family == family and r.delta_ic is not None]
        n_sig = sum(1 for r in f_rows if r.delta_passes_fdr)
        mean_d = float(np.mean([r.delta_ic for r in f_rows])) if f_rows else None
        max_d = float(np.max([r.delta_ic for r in f_rows])) if f_rows else None
        lines.append(f"| {family} | {len(f_rows)} | {_fmt(mean_d)} | {_fmt(max_d)} | {n_sig} |")

    # --- Section 4: control-family verdict -----------------------------------
    lines.append("")
    lines.append("### Section 4: Control (canary) family verdict")
    lines.append("")
    control_weighted = [r for r in rows if r.flag == _FLAG_CONTROL_BREACH]
    if not control_weighted:
        lines.append(
            "control family absent from all strata (expected: "
            "feature_status_at_eval='active' excludes canaries from eligibility). "
            "The absent-family no-op doubles as the ablation-mechanism sanity check."
        )
    else:
        lines.append(
            f"> **GOVERNANCE BREACH**: control family carries weight in "
            f"{len(control_weighted)} (stratum, scale) cells -- canaries must never "
            "be ensemble-eligible. Investigate ensemble_trainer eligibility before "
            "trusting any other row of this report."
        )
        sig_control = [r for r in control_weighted if r.delta_passes_fdr]
        if sig_control:
            lines.append(
                f"> **ABLATION MECHANISM SUSPECT**: zeroing control moved IC with "
                f"FDR significance in {len(sig_control)} cells -- a canary family "
                "cannot carry real marginal IC; suspect the ablation code, not the model."
            )

    lines.append("")
    lines.append("---")
    lines.append("This report is diagnostic; remediation decisions are human/operator.")
    return lines


def record_manifest(
    manifest_dir: Path,
    weight_version: str,
    oos_start: Any,
    families: list[str],
    rows: list[AttributionRow],
    replication: list[ReplicationRecord],
    error: str | None = None,
) -> Path:
    """Write the CorpusManifest run record -- the todo's 'results go in the run
    manifest' target. step_name 'ensemble_ablation', scope_suffix=weight_version
    (the ensemble_trainer pattern: champion + challenger runs coexist and must not
    stomp each other's manifest file). Replication mismatches and control-family
    breaches become manifest warnings (status 'partial'); a hard failure becomes a
    manifest error (status 'failed'). Nothing downstream gates on this manifest
    today; it is the durable, machine-readable record a future epoch-over-epoch
    comparison can diff.
    """
    manifest = CorpusManifest("ensemble_ablation", manifest_dir)
    manifest.scope_suffix = weight_version
    manifest.set_inputs(
        weight_version=weight_version,
        oos_start=str(oos_start),
        families=families,
        n_strata=len({(r.tf, r.regime) for r in rows}),
    )
    if rows:
        rows_by_tf: dict[str, int] = {}
        for r in rows:
            rows_by_tf[r.tf] = rows_by_tf.get(r.tf, 0) + 1
        manifest.add_output(
            table_name="ensemble_ablation_attribution",
            rows_total=len(rows),
            rows_by_tf=rows_by_tf,
        )
    for r in replication:
        if not r.ok:
            manifest.add_warning(
                f"REPLICATION MISMATCH {r.tf}/{r.regime}: norm_max_diff="
                f"{r.norm_max_diff} over {r.n_compared} bars"
            )
    n_control_weighted = len({(r.tf, r.regime) for r in rows if r.flag == _FLAG_CONTROL_BREACH})
    if n_control_weighted:
        manifest.add_warning(
            f"GOVERNANCE BREACH: control family carries weight in {n_control_weighted} strata"
        )
    if error is not None:
        manifest.add_error(error)
    else:
        manifest.mark_success()
    return manifest.write()


# ---------------------------------------------------------------------------
# Entrypoint (all DB I/O lives here; kernels above are pure)
# ---------------------------------------------------------------------------


def _abort(message: str, manifest_dir: Path, weight_version: str, oos_start: Any) -> int:
    """Loud diagnostic abort: print a FAILED header, record a failed manifest,
    return 0 (exit code always 0 -- EIC-05 convention; the FAILURE signal is the
    printed banner + manifest status, not the exit code)."""
    print(f"## Ensemble Ablation Report\n\nFAILED: {message}")
    try:
        record_manifest(
            manifest_dir=manifest_dir,
            weight_version=weight_version,
            oos_start=oos_start,
            families=[],
            rows=[],
            replication=[],
            error=message,
        )
    except Exception as error:
        print(f"(manifest write also failed: {error})")
    return 0


async def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description="Leave-one-family-out ensemble ablation report (todo 084)"
    )
    parser.add_argument(
        "--weight-version",
        default=None,
        help=(
            "Weight variant to ablate; defaults to the champion "
            "(alpha.ensemble.weight_version APR value)"
        ),
    )
    parser.add_argument(
        "--reconstruction-tol",
        type=float,
        default=_DEFAULT_RECONSTRUCTION_TOL,
        help=(
            "Max |recomputed - stored| / std(stored) before flagging REPLICATION "
            f"MISMATCH (default {_DEFAULT_RECONSTRUCTION_TOL}; see module constant "
            "comment for provenance)"
        ),
    )
    parser.add_argument(
        "--manifest-dir",
        type=Path,
        default=CorpusManifest.DEFAULT_MANIFEST_DIR,
        help="Corpus manifest directory (default: the pipeline-shared location)",
    )
    args = parser.parse_args()

    settings = Settings()
    dsn = settings.database_url.replace("postgresql+asyncpg://", "postgresql://")
    pool = await asyncpg.create_pool(dsn=dsn)
    try:
        async with pool.acquire() as conn:
            apr_cfg = await _load_apr(conn)
            config = AblationConfig.from_apr(apr_cfg)
            weight_version = (
                args.weight_version
                if args.weight_version
                else _cfg(apr_cfg, "alpha.ensemble.weight_version", "v1")
            )

            # OOS boundary: crash-loud read (ensemble_ic_engine CR-01 pattern) --
            # a missing oos_start must never silently measure the full corpus.
            try:
                oos_start = await conn.fetchval(
                    "SELECT config_value::timestamptz FROM config_state "
                    "WHERE config_key = 'alpha.validation.oos_start'"
                )
            except (asyncpg.DataError, asyncpg.InvalidTextRepresentationError) as error:
                return _abort(
                    f"alpha.validation.oos_start is not a valid timestamp: {error}",
                    args.manifest_dir,
                    weight_version,
                    None,
                )
            if oos_start is None:
                return _abort(
                    "alpha.validation.oos_start is not set in config_state; an OOS "
                    "ablation without a boundary would silently include training data.",
                    args.manifest_dir,
                    weight_version,
                    None,
                )

            # Trust gate on the weight source: nonzero ensemble_weights rows are
            # not evidence the trainer run that wrote them finished
            # (CorpusManifest.ensure_success_for closes exactly this gap).
            try:
                CorpusManifest.ensure_success_for(
                    args.manifest_dir,
                    "ensemble_trainer",
                    scope_suffix=weight_version,
                    weight_version=weight_version,
                )
            except RuntimeError as error:
                return _abort(
                    f"ensemble_trainer prerequisite not satisfied: {error}",
                    args.manifest_dir,
                    weight_version,
                    oos_start,
                )

            family_rows = await conn.fetch(_FAMILIES_SQL)
            families = [r["group_name"] for r in family_rows]
            strata = await conn.fetch(_STRATA_SQL, weight_version)
            if not strata:
                return _abort(
                    f"no ensemble_weights strata for weight_version={weight_version!r}",
                    args.manifest_dir,
                    weight_version,
                    oos_start,
                )

            all_rows: list[AttributionRow] = []
            replication: list[ReplicationRecord] = []
            for stratum in strata:
                tf, regime = stratum["tf"], stratum["regime"]
                weight_recs = await conn.fetch(_WEIGHTS_SQL, weight_version, tf, regime)
                if not weight_recs:
                    continue
                feature_names = [r["feature_name"] for r in weight_recs]
                group_names = [r["group_name"] for r in weight_recs]
                signed_weights = signed_weights_from_rows(
                    np.array([float(r["weight"]) for r in weight_recs]),
                    np.array([float(r["ic_sharpe"]) for r in weight_recs]),
                )

                scales = config.active_scales_for(tf)
                fv_rows = await conn.fetch(
                    build_stratum_fetch_sql(feature_names, scales),
                    tf,
                    regime,
                    weight_version,
                    oos_start,
                )
                if len(fv_rows) < 2:
                    replication.append(
                        ReplicationRecord(
                            tf=tf,
                            regime=regime,
                            n_bars=len(fv_rows),
                            n_compared=0,
                            norm_max_diff=None,
                            ok=True,
                        )
                    )
                    continue

                bar_ts_arr, X, gated_returns, stored_alpha = prepare_stratum_arrays(
                    fv_rows, feature_names, scales
                )
                unique_ts, bar_idx = np.unique(bar_ts_arr, return_inverse=True)
                n_bars = len(unique_ts)

                baseline_scores = X @ signed_weights
                n_compared, norm_max_diff, ok = reconstruction_check(
                    baseline_scores, stored_alpha, args.reconstruction_tol
                )
                replication.append(
                    ReplicationRecord(
                        tf=tf,
                        regime=regime,
                        n_bars=len(fv_rows),
                        n_compared=n_compared,
                        norm_max_diff=norm_max_diff,
                        ok=ok,
                    )
                )

                pooled_returns_by_scale = {
                    scale: pool_means_by_bar(bar_idx, n_bars, gated_returns[scale])
                    for scale in scales
                }
                all_rows.extend(
                    compute_stratum_attribution(
                        tf=tf,
                        regime=regime,
                        families=families,
                        group_names=group_names,
                        signed_weights=signed_weights,
                        X=X,
                        bar_idx=bar_idx,
                        n_bars=n_bars,
                        pooled_returns_by_scale=pooled_returns_by_scale,
                        config=config,
                        baseline_scores=baseline_scores,
                    )
                )

        all_rows = apply_delta_fdr(all_rows, config.fdr_alpha)
        report_lines = render_report(
            weight_version=weight_version,
            oos_start=oos_start,
            families=families,
            rows=all_rows,
            replication=replication,
            config=config,
            reconstruction_tol=args.reconstruction_tol,
        )
        print("\n".join(report_lines))
        manifest_path = record_manifest(
            manifest_dir=args.manifest_dir,
            weight_version=weight_version,
            oos_start=oos_start,
            families=families,
            rows=all_rows,
            replication=replication,
        )
        print(f"\nmanifest: {manifest_path}")
        return 0
    finally:
        await pool.close()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
