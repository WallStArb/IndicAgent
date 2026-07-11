#!/usr/bin/env python3
"""Ensemble Trainer — oneshot that derives IC-weighted ensemble weights and scores ensemble alpha.

Reads cross-sectional IC scores (symbol='POOLED', is_pooled=true, regime != '_pooled',
passes_fdr=true, reliable=true, passes_walkforward=true, plus a significance clause that
is flag-gated on alpha.ensemble.sign_symmetric -- Component E, todo 094: `ic_ci_lower > 0`
when the flag is off (long-only, byte-identical to the pre-Component-E champion), or
`(ic_sign=1 AND ic_ci_lower>0) OR (ic_sign=-1 AND ic_ci_upper<0)` when the flag is on --
see `_eligibility_where()`), applies Ledoit-Wolf cluster deflation, and writes:
  - ensemble_weights: one row per (tf, regime, weight_version, feature_name), symbol='UNIVERSE'
  - ensemble_alpha:   one row per (symbol, tf, bar_ts, weight_version) via vectorized matmul

Cross-sectional model rationale: per-symbol per-regime cells have ~1,500 bars at 5m,
structurally below the 60,000-bar gate (sharpe_min_windows=30 × window_size=2000).
Cross-sectional cells pool 58 symbols × regime, yielding ~126K bars → ~220 windows,
well above the gate. One universe-level model is also statistically superior to 58 noisy
per-symbol models.

CORRECTNESS INVARIANTS:
- Only cross-sectional, statistically significant, walk-forward-confirmed rows feed the ensemble
  (no cross-regime leakage). "Statistically significant" (CI+FDR) alone is not a sufficient bar —
  it does not distinguish real signal from the tail of expected false discoveries that BH-FDR
  budgets for; passes_walkforward=true requires the same effect to reproduce out-of-sample across
  independent time folds. Added 2026-07-09 after a fresh corpus measurement showed the top of the
  IC leaderboard concentrated in regime-conditional cells with wf_fold_count=0 (never evaluated
  out-of-sample) and IC magnitudes (0.15-0.42) implausible for real univariate equity signal.
- feature_vectors query includes WHERE regime = stratum_regime — no cross-regime scoring.
- Scoring uses X @ signed_weights (matmul, no per-bar Python loop).
- LW cluster deflation (cluster_deflate_weights) runs after derive_weights.
- Zero-weight strata (all weights deflated to zero) are skipped — no silent empty writes.
- ensemble_weights INSERT is wrapped in a single transaction (atomic weight_version commit).
- ensemble_alpha rows use conn.executemany — bulk insert, not per-bar individual INSERTs.
- All numeric parameters loaded from APR via asyncpg-fetched config dict.

DAG invariant note: this oneshot is exempt from the "only writer subclasses touch DB" rule
exactly as backfill_feature_factory.py is — it is a batch compute tool, not a real-time daemon.

Usage:
    python services/ensemble_trainer.py
"""

from __future__ import annotations

import asyncio
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import asyncpg
import numpy as np
import structlog

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

import dataclasses
import math

from services._batch_utils import cfg as _cfg
from services._batch_utils import load_apr_dict_async as _load_apr
from src.config.settings import Settings
from src.core.agent.base_batch import BaseBatch
from src.intelligence.ensemble import (
    cluster_deflate_weights,
    compute_shrinkage_covariance,
    derive_weights,
    effective_n,
    mean_variance_weights,
    select_features_per_stratum,
)
from src.intelligence.feature_registry_service import FeatureRegistryService
from src.intelligence.schemas import FeatureVector
from src.observability.corpus_manifest import CorpusManifest
from src.observability.metrics import (
    ENSEMBLE_EFFECTIVE_N_GAUGE,
    ENSEMBLE_FEATURE_WEIGHT_GAUGE,
    ENSEMBLE_FEATURES_ZERO_WEIGHT_GAUGE,
    ENSEMBLE_SHRINKAGE_INTENSITY_GAUGE,
)
from src.observability.otel import OTelInitError, init_otel_providers

_logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Ensemble eligibility criterion — single builder, four call sites below.
#
# Cross-sectional significance (ic_ci_lower/passes_fdr) is not a sufficient bar on
# its own: it does not distinguish real signal from the tail of expected false
# discoveries BH-FDR budgets for. passes_walkforward requires the same effect to
# reproduce out-of-sample across independent time folds. reliable/ic_sharpe_hac
# guard against low-N instability. All four conditions must hold together.
#
# alpha.ensemble.sign_symmetric (Component E, todo 094) is the champion/challenger
# behavior switch: when False, the significance clause is `ic_ci_lower > 0`
# (byte-identical to the pre-Component-E champion — this predicate can NEVER be
# satisfied by a negative-IC feature, since a negative point estimate's CI lower
# bound is always <= the point estimate). When True, a contrarian feature
# (ic_sign=-1) becomes eligible whenever its CI sits entirely below zero on its own
# side (ic_ci_upper < 0) — the sign-symmetric equivalent of "significant, not just
# not indistinguishable from noise."
# ---------------------------------------------------------------------------


def _eligibility_where(sign_symmetric: bool) -> tuple[str, str]:
    """Build (base, full) eligibility WHERE clauses for feature_ic_scores.

    sign_symmetric=False reproduces the exact pre-Component-E predicate string
    (equivalence property, tested). sign_symmetric=True adds the sign-aware
    contrarian branch without changing the positive-side clause at all.
    """
    if sign_symmetric:
        significance_clause = (
            "((ic_sign = 1 AND ic_ci_lower > 0) OR (ic_sign = -1 AND ic_ci_upper < 0))"
        )
    else:
        significance_clause = "ic_ci_lower > 0"
    base_where = (
        "symbol = 'POOLED' AND is_pooled = true AND regime != '_pooled'"
        f" AND {significance_clause}"
        " AND reliable = true AND ic_sharpe_hac IS NOT NULL"
        " AND passes_walkforward = true"
    )
    return base_where, base_where + " AND passes_fdr = true"


# ---------------------------------------------------------------------------
# APR compile-time binding
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class EnsembleConfig:
    """Frozen config snapshot bound once at startup from APR.

    All values are immutable for the entire ensemble run — no mid-run drift if
    config_state is updated externally.
    """

    max_feature_weight: float
    effective_n_gate: float
    weight_version: str
    min_passing_features: int
    max_cluster_corr: float
    max_cluster_weight: float
    meta_fdr_min_fraction: float
    meta_fdr_min_cells: int
    sharpe_floor: float
    weight_half_life_days: float
    weight_stale_max_days: int
    ic_input: str
    weight_method: str
    mv_condition_max: float
    sign_symmetric: bool

    @classmethod
    def from_apr(cls, cfg: dict[str, Any]) -> EnsembleConfig:
        """Load all ensemble APR parameters from the raw config dict in one pass."""
        return cls(
            max_feature_weight=_cfg(cfg, "alpha.ensemble.max_feature_weight", 0.20),
            effective_n_gate=_cfg(cfg, "alpha.ensemble.effective_n_gate", 3.0),
            weight_version=_cfg(cfg, "alpha.ensemble.weight_version", "v1"),
            min_passing_features=_cfg(cfg, "alpha.ensemble.min_passing_features", 5),
            max_cluster_corr=_cfg(cfg, "alpha.ensemble.max_cluster_correlation", 0.80),
            max_cluster_weight=_cfg(cfg, "alpha.ensemble.max_cluster_weight", 0.40),
            meta_fdr_min_fraction=_cfg(cfg, "alpha.ensemble.meta_fdr_min_fraction", 0.50),
            meta_fdr_min_cells=_cfg(cfg, "alpha.ensemble.meta_fdr_min_cells", 3),
            sharpe_floor=_cfg(cfg, "alpha.ensemble.sharpe_floor", 0.05),
            weight_half_life_days=_cfg(cfg, "alpha.ensemble.weight_half_life_days", 30.0),
            weight_stale_max_days=_cfg(cfg, "alpha.ensemble.weight_stale_max_days", 90),
            ic_input=_cfg(cfg, "alpha.ensemble.ic_input", "ic_sharpe_hac"),
            weight_method=_cfg(cfg, "alpha.ensemble.weight_method", "ic_proportional"),
            mv_condition_max=_cfg(cfg, "alpha.ensemble.mv_condition_max", 1000.0),
            sign_symmetric=bool(_cfg(cfg, "alpha.ensemble.sign_symmetric", False)),
        )


# feature_ic_scores column each alpha.ensemble.ic_input value reads from (E1, D-05).
# 'ic_sharpe_hac' (default) preserves v1 behavior byte-for-byte; 'ic_shrunk' is only
# trustworthy once ops_ic_shrinkage.py's out-of-fold gate has PASSED and flipped the
# APR value -- ensemble_trainer.py never checks the gate itself, it just reads
# whatever alpha.ensemble.ic_input currently says (the gate script is the sole writer
# of that flip, and only inside its PASS branch).
_IC_INPUT_COLUMNS: dict[str, str] = {
    "ic_sharpe_hac": "ic_sharpe_hac",
    "ic_shrunk": "ic_shrunk",
}


def _resolve_ic_input_column(ic_input: str) -> str:
    """Resolve alpha.ensemble.ic_input to its source feature_ic_scores column.

    Fails loud on an unknown value rather than silently falling back to the wrong
    column -- a mis-set APR value must not silently keep training on stale/wrong IC
    estimates.
    """
    try:
        return _IC_INPUT_COLUMNS[ic_input]
    except KeyError:
        raise ValueError(
            f"Unknown alpha.ensemble.ic_input value: {ic_input!r}. "
            f"Valid values: {sorted(_IC_INPUT_COLUMNS)}"
        ) from None


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
    aged_quality_weights: np.ndarray,
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
    aged_quality_weights:
        Staleness-decayed IC-Sharpe-derived quality weights, the raw input to derive_weights()
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
        convention derive_weights' `> 0` filter expects -- mirrors how aged_quality_weights is
        already positive-convention for the ic_proportional path. NOT used by the ic_proportional
        branch (aged_quality_weights is pre-signed via compute_quality_weight already).
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
        raw_weights = derive_weights(aged_quality_weights, max_feature_weight)
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
            # (whose aged_quality_weights input is already positive-convention). Cap/sign
            # are NOT folded into mean_variance_weights() itself -- they run here.
            # cluster_deflate_weights is deliberately SKIPPED: Sigma^-1.IC already
            # decorrelates continuously, so binary cluster capping would double-penalize.
            mv_raw_signed = ic_signs * mv_raw
            weights = derive_weights(mv_raw_signed, max_feature_weight)
            return StratumWeightResult(mv_raw, weights, "mean_variance", cond)
        # Ill-conditioned Sigma (Pitfall 3): fall back to the proven cluster-deflation
        # path rather than emitting extreme offsetting weights from an unreliable Sigma^-1
        # solve. Caller MUST log this -- never a silent skip (T-142B1-04-03).
        raw_weights = derive_weights(aged_quality_weights, max_feature_weight)
        weights = cluster_deflate_weights(
            raw_weights, corr_matrix, max_cluster_corr, max_cluster_weight
        )
        return StratumWeightResult(raw_weights, weights, "mean_variance_fallback", cond)

    raise ValueError(
        f"Unknown alpha.ensemble.weight_method value: {weight_method!r}. "
        f"Valid values: {sorted(_VALID_WEIGHT_METHODS)}"
    )


def _effective_weight_version(cli_weight_version: str | None, apr_default: str) -> str:
    """Resolve the per-run weight epoch: CLI override takes precedence over the APR default.

    A per-run epoch (e.g. 'run_20260624') lets a re-run after IC scores change write fresh
    weight/alpha rows instead of colliding with (and silently keeping) the prior run's static
    'v1' key. When no CLI override is given, falls back to the APR default (backward compatible).
    """
    return cli_weight_version if cli_weight_version else apr_default


def _effective_sign_symmetric(cli_sign_symmetric: bool | None, apr_default: bool) -> bool:
    """Resolve the champion/challenger behavior switch: CLI override takes precedence
    over the APR default (mirrors `_effective_weight_version`).

    `None` means "no CLI override given" (argparse.BooleanOptionalAction default) —
    distinct from an explicit `False`, which must still override the APR default.
    """
    return cli_sign_symmetric if cli_sign_symmetric is not None else apr_default


def _meta_eligible(
    fdr_pass_rows: list[dict], min_fraction: float, min_cells: int
) -> dict[str, set[str]]:
    """Return, per timeframe, feature names whose BH-FDR pass-rate across that
    timeframe's eligible cells meets the threshold.

    Scoped per-tf rather than pooled globally: timeframes are not exchangeable draws of
    the same experiment (different bars/day, different noise floor, different horizon),
    so pooling BH-FDR outcomes across all 4 timeframes into one fraction conflates
    cross-timeframe power differences with feature quality — a feature genuinely strong
    at 1d can get vetoed everywhere by a weak showing in 5m noise. Each row must carry
    'feature_name', 'tf', 'fdr_pass_rate', 'n_cells'.

    min_cells excludes (feature, tf) pairs with too little evidence to make the
    fraction meaningful — a single-cell 100% pass rate is a tautology, not replication.

    Denominator (fdr_pass_rate) is restricted to cross-sectional cells that pass all
    ensemble eligibility filters (symbol='POOLED', is_pooled=true, regime != '_pooled',
    reliable=true, ic_sharpe_hac IS NOT NULL, passes_walkforward=true, plus the
    flag-gated significance clause -- see `_eligibility_where()`) — the same population
    consumed by _process_stratum.
    """
    result: dict[str, set[str]] = {}
    for r in fdr_pass_rows:
        if r["n_cells"] < min_cells:
            continue
        if r["fdr_pass_rate"] >= min_fraction:
            result.setdefault(r["tf"], set()).add(r["feature_name"])
    return result


# ---------------------------------------------------------------------------
# FeatureVector column names — matches FeatureVector dataclass field ordering.
# We select only the numeric feature columns from feature_vectors.
# ---------------------------------------------------------------------------

_KNOWN_FEATURE_COLS: list[str] | None = None


async def _get_feature_columns(conn: asyncpg.Connection) -> list[str]:
    """Retrieve numeric feature column names from feature_vectors (excluding metadata cols)."""
    _META_COLS = frozenset(
        {
            "id",
            "symbol",
            "tf",
            "bar_ts",
            "bar_close_ts",
            "feature_factory_version",
            "feature_vector_id",
            "pipeline_version",
            "regime",
            "regime_label_source",
            "created_at",
        }
    )
    rows = await conn.fetch("""
        SELECT column_name
        FROM information_schema.columns
        WHERE table_name = 'feature_vectors'
          AND table_schema = 'public'
        ORDER BY ordinal_position
        """)
    cols = [r["column_name"] for r in rows if r["column_name"] not in _META_COLS]
    return cols


# ---------------------------------------------------------------------------
# Startup crash-loud gates
# ---------------------------------------------------------------------------


async def _assert_prerequisites(
    conn: asyncpg.Connection,
    sign_symmetric: bool,
    manifest_dir: Path = CorpusManifest.DEFAULT_MANIFEST_DIR,
) -> None:
    """Two startup gates plus a manifest check. Raise RuntimeError to prevent a
    silent empty OR silently-partial run."""
    _, eligibility_where = _eligibility_where(sign_symmetric)
    n_ic = await conn.fetchval(f"SELECT count(*) FROM feature_ic_scores WHERE {eligibility_where}")
    if not n_ic:
        significance_desc = (
            "(ic_sign=1 AND ic_ci_lower>0) OR (ic_sign=-1 AND ic_ci_upper<0)"
            if sign_symmetric
            else "ic_ci_lower > 0"
        )
        raise RuntimeError(
            "EnsembleTrainer startup gate FAILED: no cross-sectional feature_ic_scores rows "
            f"(symbol='POOLED', is_pooled=true, regime != '_pooled', {significance_desc}, "
            "passes_fdr=true, reliable=true, passes_walkforward=true). "
            "Run ic_engine.py first."
        )

    # A nonzero row count above does not mean the ic_engine.py run that wrote them
    # finished -- ic_engine.py is the sole writer of feature_ic_scores, and this is
    # the identical "nonzero rows isn't proof the run finished" gap already closed
    # one hop downstream (ensemble_ic_engine.py / alpha_publisher.py reading
    # ensemble_trainer's output). ic_engine.py has no weight_version-style scoping
    # axis (one canonical corpus-wide run, not coexisting variants), so no
    # scope_suffix is needed here.
    CorpusManifest.ensure_success_for(manifest_dir, "ic_engine")

    n_fv = await conn.fetchval("SELECT count(*) FROM feature_vectors")
    if not n_fv:
        raise RuntimeError(
            "EnsembleTrainer startup gate FAILED: feature_vectors is empty. "
            "Run backfill_feature_factory.py + regime_writer.py first."
        )


# ---------------------------------------------------------------------------
# EnsembleTrainer
# ---------------------------------------------------------------------------


class EnsembleTrainer(BaseBatch):
    """Batch compute service: feature_ic_scores → ensemble_weights + ensemble_alpha.

    Reads cross-sectional IC scores per (tf, regime) from symbol='POOLED' rows,
    applies LW shrinkage covariance and cluster deflation, writes universe-level
    ensemble weights (symbol='UNIVERSE'), then scores all feature_vectors bars
    for every symbol via vectorized matmul.
    """

    job_name = "ensemble-trainer"
    compute_version = "1.0.0"

    def __init__(
        self,
        db_dsn: str,
        weight_version_override: str | None = None,
        sign_symmetric_override: bool | None = None,
    ) -> None:
        super().__init__(db_dsn=db_dsn)
        self._weight_version_override = weight_version_override
        self._sign_symmetric_override = sign_symmetric_override

    async def execute(self, pool: asyncpg.Pool) -> None:  # type: ignore[override]
        """Run the full ensemble weight derivation and alpha scoring pipeline."""
        manifest = CorpusManifest("ensemble_trainer", CorpusManifest.DEFAULT_MANIFEST_DIR)
        try:
            await self._execute_inner(pool, manifest)
        except Exception as error:
            manifest.add_error(str(error))
            try:
                manifest.write()
            except Exception:
                pass
            raise

    async def _execute_inner(self, pool: asyncpg.Pool, manifest: CorpusManifest) -> None:
        async with pool.acquire() as conn:
            # --- Bind all APR parameters once at startup (compile-time binding) ---
            cfg = await _load_apr(conn)
            config = EnsembleConfig.from_apr(cfg)
            # Per-run weight epoch: CLI --weight-version overrides the static APR default so a
            # re-run after IC scores change writes fresh keys instead of colliding with (and
            # silently keeping) the prior run's weights.
            config = dataclasses.replace(
                config,
                weight_version=_effective_weight_version(
                    self._weight_version_override, config.weight_version
                ),
                sign_symmetric=_effective_sign_symmetric(
                    self._sign_symmetric_override, config.sign_symmetric
                ),
            )

            self.logger.info(
                "ensemble_trainer.config_loaded",
                max_feature_weight=config.max_feature_weight,
                effective_n_gate=config.effective_n_gate,
                weight_version=config.weight_version,
                min_passing_features=config.min_passing_features,
                max_cluster_corr=config.max_cluster_corr,
                max_cluster_weight=config.max_cluster_weight,
                meta_fdr_min_fraction=config.meta_fdr_min_fraction,
                sharpe_floor=config.sharpe_floor,
                sign_symmetric=config.sign_symmetric,
            )
            manifest.set_inputs(weight_version=config.weight_version)
            # Scope the manifest FILE by weight_version too, not just its recorded
            # inputs: champion + challenger weight_version runs coexist by design
            # (migration 196 Section 3) and must not share one manifest file, or a
            # crashed challenger run would overwrite the record a healthy champion
            # run's readers (ensemble_ic_engine.py, alpha_publisher.py) depend on.
            manifest.scope_suffix = config.weight_version

            # Eligibility WHERE clauses, built once per run from the effective
            # sign_symmetric flag (Component E, todo 094) -- reused by the startup
            # gate, the meta-FDR denominator, the strata enumeration, and the
            # per-stratum IC fetch below.
            eligibility_base_where, eligibility_where = _eligibility_where(config.sign_symmetric)

            # --- Startup gates ---
            await _assert_prerequisites(conn, config.sign_symmetric)

            # --- Feature registry alignment gate ---
            # Use get_all_features() — NOT get_active_features() — for alignment gate.
            # Lifecycle state (active/deprecated) is enforced separately via WHERE clause.
            # The alignment gate checks schema completeness regardless of status.
            registry_svc = FeatureRegistryService()
            await registry_svc.load(pool)
            all_registry_names = {r["feature_name"] for r in registry_svc.get_all_features()}
            dataclass_names = {f.name for f in dataclasses.fields(FeatureVector)}
            if all_registry_names != dataclass_names:
                raise RuntimeError(
                    f"feature_registry drift: {all_registry_names ^ dataclass_names}"
                )

            self.logger.info(
                "ensemble_trainer.registry_loaded",
                n_features=len(all_registry_names),
                weight_half_life_days=config.weight_half_life_days,
            )

            # --- Full replace, scoped to this weight_version ---
            # A re-run under the same weight_version must produce a fully self-consistent
            # row-set, not an incremental upsert on top of a prior run's output.
            # _process_stratum silently early-returns (debug-level log only) when a
            # stratum's meta-eligible feature count drops below min_passing_features --
            # e.g. after a gate tightens (as the per-timeframe meta-FDR fix did for 1h).
            # Without this delete, a stratum that qualified under an OLDER run's logic
            # keeps its stale rows forever under a weight_version that is supposed to be
            # a deterministic snapshot of "this run's logic + this run's data." Scoped
            # strictly to config.weight_version -- never touches other versions (the
            # champion 'v1' or other challenger runs) sharing the same tables. Placed
            # after all startup/registry gates so a gate failure never touches existing
            # data -- only a run that's actually going to complete triggers the delete.
            #
            # NEVER add RETURNING here: ensemble_alpha holds one row per (symbol, tf,
            # bar_ts) and can exceed 30M rows for an active weight_version. RETURNING
            # forces Postgres to materialize the full deleted-row result set before a
            # count can be taken -- against this table's size that OOM-killed the
            # Postgres backend and crashed the entire TimescaleDB instance (2026-07-08,
            # required WAL recovery on restart). conn.execute()'s command tag
            # ("DELETE <n>") gives the row count without materializing any result rows.
            weights_tag = await conn.execute(
                "DELETE FROM ensemble_weights WHERE weight_version = $1",
                config.weight_version,
            )
            alpha_tag = await conn.execute(
                "DELETE FROM ensemble_alpha WHERE weight_version = $1",
                config.weight_version,
            )
            self.logger.info(
                "ensemble_trainer.prior_weight_version_cleared",
                weight_version=config.weight_version,
                weights_tag=weights_tag,
                alpha_tag=alpha_tag,
            )

            # --- Meta-FDR gate: feature must pass BH-FDR in >=meta_fdr_min_fraction of cells,
            # scoped per timeframe (GROUP BY includes tf) — timeframes are not exchangeable
            # draws of the same experiment (different bars/day, noise floor, horizon), so
            # pooling pass rates across all 4 timeframes would silently veto features that
            # are genuinely strong at one horizon but weak at another. See _meta_eligible
            # docstring. Denominator mirrors _process_stratum's WHERE clause exactly — cells
            # that fail the significance gate, have NULL ic_sharpe_hac, or never had
            # out-of-sample walk-forward confirmation are never consumed by the ensemble, so
            # including them would artificially deflate every feature's pass-rate.
            fdr_pass_rows = await conn.fetch(f"""
                SELECT feature_name, tf,
                       SUM(CASE WHEN passes_fdr THEN 1 ELSE 0 END)::float / COUNT(*) AS fdr_pass_rate,
                       COUNT(*) AS n_cells
                FROM feature_ic_scores
                WHERE {eligibility_base_where}
                GROUP BY feature_name, tf
                """)
            meta_eligible_by_tf = _meta_eligible(
                fdr_pass_rows, config.meta_fdr_min_fraction, config.meta_fdr_min_cells
            )
            n_total_cells = sum(r["n_cells"] for r in fdr_pass_rows)
            self.logger.info(
                "ensemble_trainer.meta_fdr_gate",
                n_eligible_by_tf={tf: len(feats) for tf, feats in meta_eligible_by_tf.items()},
                n_total_features=len({r["feature_name"] for r in fdr_pass_rows}),
                min_fraction=config.meta_fdr_min_fraction,
                min_cells=config.meta_fdr_min_cells,
                n_total_cells_evaluated=n_total_cells,
            )
            if fdr_pass_rows:
                cells = [r["n_cells"] for r in fdr_pass_rows]
                min_cells, max_cells = min(cells), max(cells)
                if min_cells < 0.10 * max_cells:
                    self.logger.warning(
                        "ensemble_trainer.meta_fdr_low_coverage",
                        min_cells=min_cells,
                        max_cells=max_cells,
                    )

            # --- Discover feature columns ---
            feature_cols = await _get_feature_columns(conn)
            if not feature_cols:
                raise RuntimeError(
                    "EnsembleTrainer: no feature columns found in feature_vectors. "
                    "Check table schema."
                )

            # --- Enumerate strata ---
            strata_rows = await conn.fetch(f"""
                SELECT DISTINCT tf, regime
                FROM feature_ic_scores
                WHERE {eligibility_where}
                  AND regime IS NOT NULL
                ORDER BY tf, regime
                """)
            self.logger.info("ensemble_trainer.strata_found", stratum_count=len(strata_rows))

            for stratum in strata_rows:
                tf = stratum["tf"]
                regime = stratum["regime"]

                await self._process_stratum(
                    conn=conn,
                    tf=tf,
                    regime=regime,
                    feature_cols=feature_cols,
                    config=config,
                    meta_eligible_features=meta_eligible_by_tf.get(tf, set()),
                )

        self.logger.info(
            "ensemble_trainer.complete",
            strata_processed=len(strata_rows),
        )

        # Record output counts and mark manifest success
        async with pool.acquire() as conn:
            weight_rows = await conn.fetch(
                "SELECT tf, COUNT(*) as n FROM ensemble_weights WHERE weight_version = $1 GROUP BY tf",
                config.weight_version,
            )
            rows_by_tf = {r["tf"]: r["n"] for r in weight_rows}
            manifest.add_output(
                table_name="ensemble_weights",
                rows_total=sum(rows_by_tf.values()),
                rows_by_tf=rows_by_tf,
            )
        manifest.mark_success()
        manifest_path = manifest.write()
        self.logger.info("ensemble_trainer.manifest_written", path=str(manifest_path))

    async def _process_stratum(
        self,
        conn: asyncpg.Connection,
        tf: str,
        regime: str,
        feature_cols: list[str],
        config: EnsembleConfig,
        meta_eligible_features: set[str],
    ) -> None:
        """Process one (tf, regime) stratum end-to-end using cross-sectional IC."""
        log = self.logger.bind(tf=tf, regime=regime)

        # E1 (D-05): alpha.ensemble.ic_input selects which column feeds quality_weight.
        # Default 'ic_sharpe_hac' preserves v1 behavior byte-for-byte; 'ic_shrunk' is
        # only live once ops_ic_shrinkage.py's out-of-fold gate has PASSED.
        ic_input_column = _resolve_ic_input_column(config.ic_input)
        ic_shrunk_not_null_clause = (
            "AND ic_shrunk IS NOT NULL" if ic_input_column == "ic_shrunk" else ""
        )
        _, eligibility_where = _eligibility_where(config.sign_symmetric)

        # Step 1: Load cross-sectional IC scores for this stratum (symbol='POOLED')
        # feature_status_at_eval = 'active' ensures we only train on IC scores from
        # periods when the feature was actively governed — excludes candidate and
        # shadow_only periods where IC data was gathered but feature not yet promoted.
        ic_rows = await conn.fetch(
            f"""
            SELECT feature_name, ic_sharpe_hac, ic_shrunk, shrinkage_weight,
                   ic_ci_lower, ic_ci_upper, ic_sign, lookahead_bars, training_window_end
            FROM feature_ic_scores
            WHERE {eligibility_where}
              AND tf = $1 AND regime = $2
              AND feature_status_at_eval = 'active'
              {ic_shrunk_not_null_clause}
            """,
            tf,
            regime,
        )
        # Meta-FDR gate: keep only features that pass BH-FDR in >=min_fraction of eligible cells
        ic_rows = [r for r in ic_rows if r["feature_name"] in meta_eligible_features]
        if not ic_rows:
            log.debug("ensemble_trainer.stratum_no_ic_rows")
            return

        # Step 2: Select best lookahead per feature using quality_weight.
        # select_features_per_stratum expects key "ic_sharpe"; the underlying column is
        # whichever alpha.ensemble.ic_input currently resolves to (ic_sharpe_hac by
        # default, or ic_shrunk once E1's out-of-fold gate has passed).
        # quality_weight = ic_ci_lower * max(sharpe_floor, ic_sharpe) is computed inside
        # select_features_per_stratum and returned on each selected row.
        selected = select_features_per_stratum(
            [{**dict(r), "ic_sharpe": r[ic_input_column]} for r in ic_rows],
            sharpe_floor=config.sharpe_floor,
        )
        if len(selected) < config.min_passing_features:
            log.debug(
                "ensemble_trainer.stratum_skipped_min_features",
                n_features=len(selected),
                min_required=config.min_passing_features,
            )
            return

        feature_names = [r["feature_name"] for r in selected]
        # quality_weights are the raw weight inputs to derive_weights (A5c).
        # Ledoit-Wolf deflation and weight caps operate on whatever raw weight is passed in.
        quality_weights = np.array([float(r["quality_weight"]) for r in selected])
        # Reads the "ic_sharpe" alias set by the remap above (Step 2) -- resolves to
        # whichever column alpha.ensemble.ic_input currently selects, not a hardcoded
        # ic_sharpe_hac literal.
        ic_sharpes = np.array([float(r["ic_sharpe"]) for r in selected])
        ic_signs = np.array([float(r["ic_sign"]) for r in selected])
        ic_ci_lower = np.array([float(r["ic_ci_lower"]) for r in selected])
        ic_ci_upper = np.array([float(r["ic_ci_upper"]) for r in selected])
        lookahead_bars = [int(r["lookahead_bars"]) for r in selected]

        # Step 3: Load feature matrix X from feature_vectors for all symbols in this (tf, regime)
        col_subset = [c for c in feature_cols if c in feature_names]
        if len(col_subset) < config.min_passing_features:
            log.debug(
                "ensemble_trainer.stratum_skipped_missing_cols",
                n_cols=len(col_subset),
                min_required=config.min_passing_features,
            )
            return

        # Restrict to features that have a column, preserving IC-selection order.
        # col_subset already passed the min_passing_features gate, and ordered_names has the
        # same membership (both are feature_names ∩ feature_cols), so no second count check.
        ordered_names = [n for n in feature_names if n in col_subset]
        ordered_idx = [feature_names.index(n) for n in ordered_names]
        quality_weights = quality_weights[ordered_idx]
        ic_sharpes = ic_sharpes[ordered_idx]
        ic_signs = ic_signs[ordered_idx]
        ic_ci_lower = ic_ci_lower[ordered_idx]
        ic_ci_upper = ic_ci_upper[ordered_idx]
        lookahead_bars = [lookahead_bars[i] for i in ordered_idx]

        # Fetch feature matrix for all symbols in this cross-sectional regime.
        # feature_vectors.regime holds per-symbol HMM labels; cross-sectional regime labels
        # live in market_regimes. JOIN on (asset_class, tf, ts=bar_ts) to filter by regime.
        # Safe: col_subset names come from information_schema, not user data
        col_list = ", ".join(f'fv."{c}"' for c in col_subset)
        fv_rows = await conn.fetch(
            f"""
            SELECT fv.symbol, {col_list}, fv.bar_ts
            FROM feature_vectors fv
            JOIN market_regimes mr
              ON mr.asset_class = 'equity' AND mr.tf = fv.tf AND mr.ts = fv.bar_ts
            WHERE fv.tf = $1 AND mr.regime_label = $2
            ORDER BY fv.bar_ts, fv.symbol
            """,
            tf,
            regime,
        )
        if len(fv_rows) < 2:
            log.debug("ensemble_trainer.stratum_insufficient_bars", n_bars=len(fv_rows))
            return

        symbol_list = [r["symbol"] for r in fv_rows]
        bar_ts_list = [r["bar_ts"] for r in fv_rows]
        # float32, not float64: same wide-matrix-from-DB-fetch shape that OOM'd
        # ic_engine.py's cross-sectional pass twice in one week (fixed there via the
        # same dtype change, commit 95a57806). Empirically validated safe end-to-end
        # for this file's specific downstream math (2026-07-08, todo 171 -- deleted
        # after this fix landed): compute_shrinkage_covariance's LedoitWolf preserves
        # input dtype rather than upcasting; mean_variance_weights' np.linalg.solve on
        # a float32 covariance showed max relative weight diff ~0.006% on a
        # well-conditioned matrix and ~0.2% right at the alpha.ensemble.mv_condition_max
        # gate boundary (n_obs=200_000, n_features=60, both far below any threshold
        # that could flip a trading decision); the final `X @ signed_weights` scoring
        # matmul (line ~853) auto-promotes to float64 via numpy's mixed-dtype rules
        # since signed_weights stays float64, so no further precision loss compounds
        # there.
        X_raw = np.array(
            [[float(r[c]) if r[c] is not None else 0.0 for c in col_subset] for r in fv_rows],
            dtype=np.float32,
        )  # shape [n_bars, n_features]

        # Map feature order in X to the IC-selected feature order
        ordered_col_indices = [col_subset.index(n) for n in ordered_names]
        X = X_raw[:, ordered_col_indices]  # [n_bars, n_selected_features]

        # Step 4: Compute LW covariance + cluster deflate weights
        # Weight aging: decay IC-derived weights exponentially with staleness.
        # Uses the latest training_window_end across all selected features as the
        # reference point. Reverts to equal-weight beyond config.weight_stale_max_days
        # (alpha.ensemble.weight_stale_max_days APR key, todo 043).
        max_training_window_end = max(
            (r["training_window_end"] for r in selected if r["training_window_end"] is not None),
            default=None,
        )
        if max_training_window_end is not None:
            days_since = max(0, (datetime.now(UTC) - max_training_window_end).days)
        else:
            days_since = 0
        if days_since > config.weight_stale_max_days:
            # Equal-weight fallback: IC scores are too stale to trust the weight ordering.
            aged_quality_weights = np.full(len(quality_weights), 1.0 / max(1, len(quality_weights)))
        else:
            aged_quality_weights = quality_weights * math.exp(
                -days_since / config.weight_half_life_days
            )

        cov_matrix, shrinkage = compute_shrinkage_covariance(X)

        # Convert to correlation matrix for cluster detection
        diag_var = np.diag(cov_matrix)
        with np.errstate(divide="ignore", invalid="ignore"):
            outer_std = np.sqrt(np.outer(diag_var, diag_var))
            corr_matrix = np.where(outer_std > 1e-10, cov_matrix / outer_std, 0.0)
            np.fill_diagonal(corr_matrix, 1.0)

        # E2 (D-08): alpha.ensemble.weight_method selects ic_proportional (v1,
        # derive_weights -> cluster_deflate_weights) vs. mean_variance
        # (Sigma^-1.ic_shrunk, condition-number gated, cluster deflation skipped on
        # success). ic_sharpes is the ic_input-resolved per-feature IC vector already
        # selected for this stratum (E1, D-05) -- the same array select_features_per_stratum
        # used as "ic_sharpe". ic_signs is threaded through for the E2 output-sign fix
        # (BLOCKER 3, Component E) -- the mean_variance branch signs mv_raw's OUTPUT,
        # never ic_sharpes/ic_shrunk's input.
        weight_result = resolve_stratum_weights(
            config.weight_method,
            aged_quality_weights,
            cov_matrix,
            corr_matrix,
            ic_sharpes,
            ic_signs,
            config.max_feature_weight,
            config.max_cluster_corr,
            config.max_cluster_weight,
            config.mv_condition_max,
        )
        raw_weights = weight_result.raw_weights
        weights = weight_result.weights
        if weight_result.method_used == "mean_variance_fallback":
            # Never a silent skip (T-142B1-04-03): ill-conditioned Sigma triggered the
            # condition-number gate, so this stratum fell back to cluster_deflate_weights.
            log.warning(
                "ensemble_trainer.weight_method_fallback",
                weight_method=config.weight_method,
                condition_number=weight_result.condition_number,
                mv_condition_max=config.mv_condition_max,
                fallback_to="cluster_deflate_weights",
            )

        gauge_attrs = {"symbol": "UNIVERSE", "tf": tf, "weight_version": config.weight_version}

        # Zero-weight guard
        if float(weights.sum()) < 1e-10:
            log.warning("ensemble_trainer.stratum_zero_weight_vector", reason="zero_weight_vector")
            ENSEMBLE_FEATURES_ZERO_WEIGHT_GAUGE.set(len(ordered_names), gauge_attrs)
            return

        eff_n = effective_n(weights)

        ENSEMBLE_SHRINKAGE_INTENSITY_GAUGE.set(shrinkage, gauge_attrs)
        ENSEMBLE_EFFECTIVE_N_GAUGE.set(eff_n, gauge_attrs)
        zero_weight_count = int(np.sum(weights < 1e-10))
        ENSEMBLE_FEATURES_ZERO_WEIGHT_GAUGE.set(zero_weight_count, gauge_attrs)
        for fname, w in zip(ordered_names, weights.tolist()):
            ENSEMBLE_FEATURE_WEIGHT_GAUGE.set(w, {"feature": fname, **gauge_attrs})

        # Step 5: Write ensemble_weights atomically (all rows for this weight_version or none)
        # symbol='UNIVERSE' — universe-level weights, not per-symbol
        now = datetime.now(UTC)
        weight_rows = [
            (
                "UNIVERSE",
                tf,
                regime,
                config.weight_version,
                ordered_names[i],
                float(raw_weights[i]),
                float(weights[i]),
                float(ic_sharpes[i]),
                lookahead_bars[i],
                eff_n,
            )
            for i in range(len(ordered_names))
        ]

        # DO UPDATE, never silently no-op: a re-run after IC scores change overwrites with
        # recomputed values instead of silently keeping stale weights (bottom-up audit §5.6).
        # Combined with the per-run weight epoch, a fresh run writes fresh keys; a
        # same-epoch resume is idempotent.
        async with conn.transaction():
            await conn.executemany(
                """
                INSERT INTO ensemble_weights
                    (symbol, tf, regime, weight_version, feature_name,
                     raw_weight, weight, ic_sharpe, lookahead_bars, effective_n, computed_at)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
                ON CONFLICT (symbol, tf, regime, weight_version, feature_name) DO UPDATE SET
                    raw_weight = EXCLUDED.raw_weight,
                    weight = EXCLUDED.weight,
                    ic_sharpe = EXCLUDED.ic_sharpe,
                    lookahead_bars = EXCLUDED.lookahead_bars,
                    effective_n = EXCLUDED.effective_n,
                    computed_at = EXCLUDED.computed_at
                """,
                [(*row, now) for row in weight_rows],
            )

        log.info(
            "ensemble_trainer.weights_written",
            n_features=len(weight_rows),
            effective_n=round(eff_n, 3),
            shrinkage=round(shrinkage, 4),
        )

        # Step 6: Score ensemble_alpha via vectorized matmul (no per-bar Python loop)
        # Universe weights applied to every symbol's bars in this (tf, regime).
        signed_weights = weights * ic_signs  # [n_features]
        alpha_scores = X @ signed_weights  # [n_bars] — single matmul

        # Analytic CI: compute margin once per stratum (constant for all bars)
        ic_sigma = (ic_ci_upper - ic_ci_lower) / 3.92
        margin = 1.96 * float(np.sqrt(float(np.dot(weights**2, ic_sigma**2))))

        ci_lower_arr = alpha_scores - margin
        ci_upper_arr = alpha_scores + margin

        n_features_active = int(np.sum(weights > 1e-10))

        # Bulk insert all n_bars rows into ensemble_alpha (per-symbol, using universe weights)
        alpha_rows = [
            (
                symbol_list[i],
                tf,
                bar_ts_list[i],
                config.weight_version,
                regime,
                float(alpha_scores[i]),
                float(ci_lower_arr[i]),
                float(ci_upper_arr[i]),
                eff_n,
                n_features_active,
                now,
            )
            for i in range(len(bar_ts_list))
        ]

        # DO UPDATE, never silently no-op: a re-run after IC scores change overwrites with
        # recomputed values instead of silently keeping stale weights (bottom-up audit §5.6).
        # Combined with the per-run weight epoch, a fresh run writes fresh keys; a
        # same-epoch resume is idempotent.
        await conn.executemany(
            """
            INSERT INTO ensemble_alpha
                (symbol, tf, bar_ts, weight_version, regime,
                 alpha_score, alpha_ci_lower, alpha_ci_upper,
                 effective_n, n_features_active, computed_at)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
            ON CONFLICT (symbol, tf, bar_ts, weight_version) DO UPDATE SET
                regime = EXCLUDED.regime,
                alpha_score = EXCLUDED.alpha_score,
                alpha_ci_lower = EXCLUDED.alpha_ci_lower,
                alpha_ci_upper = EXCLUDED.alpha_ci_upper,
                effective_n = EXCLUDED.effective_n,
                n_features_active = EXCLUDED.n_features_active,
                computed_at = EXCLUDED.computed_at
            """,
            alpha_rows,
        )

        log.info(
            "ensemble_trainer.alpha_written",
            n_bars=len(alpha_rows),
            margin=round(margin, 4),
        )


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="EnsembleTrainer oneshot")
    parser.add_argument(
        "--weight-version",
        default=None,
        help=(
            "Per-run weight epoch; overrides alpha.ensemble.weight_version so a re-run "
            "after IC changes produces fresh weights instead of silently keeping stale ones"
        ),
    )
    parser.add_argument(
        "--sign-symmetric",
        action=argparse.BooleanOptionalAction,
        default=None,
        help=(
            "Champion/challenger behavior switch (Component E, todo 094); overrides "
            "alpha.ensemble.sign_symmetric. Omit to use the APR default (false = "
            "pre-Component-E long-only-eligible champion); pass --sign-symmetric or "
            "--no-sign-symmetric to force either behavior for this run"
        ),
    )
    args = parser.parse_args()

    try:
        init_otel_providers("indicagent-ensemble-trainer")
    except OTelInitError as error:
        _logger.warning("ensemble_trainer.otel_init_failed", error=str(error))

    settings = Settings()
    db_dsn = settings.database_url.replace("postgresql+asyncpg://", "postgresql://")
    asyncio.run(
        EnsembleTrainer(
            db_dsn=db_dsn,
            weight_version_override=args.weight_version,
            sign_symmetric_override=args.sign_symmetric,
        ).run()
    )
