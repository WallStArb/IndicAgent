#!/usr/bin/env python3
"""Ensemble Builder — oneshot that derives IC-weighted ensemble weights and scores ensemble alpha.

Reads feature_ic_scores (is_pooled=false, passes_walkforward=true), applies Ledoit-Wolf
cluster deflation, and writes:
  - ensemble_weights: one row per (symbol, tf, regime, weight_version, feature_name)
  - ensemble_alpha:   one row per (symbol, tf, bar_ts, weight_version) via vectorized matmul

CORRECTNESS INVARIANTS:
- Only non-pooled, walk-forward-passing rows feed the ensemble (no cross-regime leakage).
- feature_vectors query includes WHERE regime_label = stratum_regime — no cross-regime scoring.
- Scoring uses X @ signed_weights (matmul, no per-bar Python loop).
- LW cluster deflation (cluster_deflate_weights) runs after derive_weights.
- Zero-weight strata (all weights deflated to zero) are skipped — no silent empty writes.
- ensemble_weights INSERT is wrapped in a single transaction (atomic weight_version commit).
- ensemble_alpha rows use conn.executemany — bulk insert, not per-bar individual INSERTs.
- All numeric parameters loaded from APR via asyncpg-fetched config dict.

DAG invariant note: this oneshot is exempt from the "only writer subclasses touch DB" rule
exactly as backfill_feature_factory.py is — it is a batch compute tool, not a real-time daemon.

Usage:
    python services/ensemble_builder.py
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

from src.config.settings import Settings
from src.core.agent.base_batch import BaseBatch
from src.intelligence.ensemble import (
    cluster_deflate_weights,
    compute_shrinkage_covariance,
    derive_weights,
    effective_n,
    select_features_per_stratum,
)
from src.observability.metrics import (
    ENSEMBLE_EFFECTIVE_N_GAUGE,
    ENSEMBLE_FEATURE_WEIGHT_GAUGE,
    ENSEMBLE_FEATURES_ZERO_WEIGHT_GAUGE,
    ENSEMBLE_SHRINKAGE_INTENSITY_GAUGE,
)
from src.observability.otel import OTelInitError, init_otel_providers

_logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# APR config query — asyncpg (RESEARCH.md Pitfall 6: use asyncpg, not psycopg2)
# ---------------------------------------------------------------------------

_APR_QUERY = "SELECT config_key, config_value FROM config_state WHERE config_key LIKE 'alpha.%'"


async def _load_apr(conn: asyncpg.Connection) -> dict[str, Any]:
    """Load all alpha.* APR keys from config_state via asyncpg.

    Returns a plain dict {config_key: config_value} (values are text — cast to float/int
    at call site). No inline numeric fallbacks beyond the documented APR defaults.
    """
    rows = await conn.fetch(_APR_QUERY)
    return {r["config_key"]: r["config_value"] for r in rows}


def _cfg_float(cfg: dict[str, Any], key: str, default: float) -> float:
    val = cfg.get(key)
    return float(val) if val is not None else default


def _cfg_int(cfg: dict[str, Any], key: str, default: int) -> int:
    val = cfg.get(key)
    return int(val) if val is not None else default


def _cfg_str(cfg: dict[str, Any], key: str, default: str) -> str:
    val = cfg.get(key)
    return str(val) if val is not None else default


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


async def _assert_prerequisites(conn: asyncpg.Connection) -> None:
    """Two startup gates. Raise RuntimeError to prevent a silent empty run."""
    n_ic = await conn.fetchval(
        "SELECT count(*) FROM feature_ic_scores WHERE is_pooled = false AND passes_walkforward = true"
    )
    if not n_ic:
        raise RuntimeError(
            "EnsembleBuilder startup gate FAILED: no feature_ic_scores rows with "
            "is_pooled=false AND passes_walkforward=true. Run ic_engine.py first."
        )

    n_fv = await conn.fetchval("SELECT count(*) FROM feature_vectors")
    if not n_fv:
        raise RuntimeError(
            "EnsembleBuilder startup gate FAILED: feature_vectors is empty. "
            "Run backfill_feature_factory.py + regime_writer.py first."
        )


# ---------------------------------------------------------------------------
# EnsembleBuilder
# ---------------------------------------------------------------------------


class EnsembleBuilder(BaseBatch):
    """Batch compute service: feature_ic_scores → ensemble_weights + ensemble_alpha.

    Reads IC scores per (symbol, tf, regime), applies LW shrinkage covariance and
    cluster deflation, writes ensemble weights, then scores all feature_vectors bars
    via vectorized matmul.
    """

    job_name = "ensemble-builder"
    compute_version = "1.0.0"

    async def execute(self, pool: asyncpg.Pool) -> None:  # type: ignore[override]
        """Run the full ensemble weight derivation and alpha scoring pipeline."""
        async with pool.acquire() as conn:
            # --- Load APR config ---
            cfg = await _load_apr(conn)
            max_feature_weight = _cfg_float(cfg, "alpha.ensemble.max_feature_weight", 0.20)
            effective_n_gate = _cfg_float(cfg, "alpha.ensemble.effective_n_gate", 3.0)
            weight_version = _cfg_str(cfg, "alpha.ensemble.weight_version", "v1")
            min_passing_features = _cfg_int(cfg, "alpha.ensemble.min_passing_features", 5)
            max_cluster_corr = _cfg_float(cfg, "alpha.ensemble.max_cluster_correlation", 0.80)
            max_cluster_weight = _cfg_float(cfg, "alpha.ensemble.max_cluster_weight", 0.40)

            self.logger.info(
                "ensemble_builder.config_loaded",
                max_feature_weight=max_feature_weight,
                effective_n_gate=effective_n_gate,
                weight_version=weight_version,
                min_passing_features=min_passing_features,
                max_cluster_corr=max_cluster_corr,
                max_cluster_weight=max_cluster_weight,
            )

            # --- Startup gates ---
            await _assert_prerequisites(conn)

            # --- Discover feature columns ---
            feature_cols = await _get_feature_columns(conn)
            if not feature_cols:
                raise RuntimeError(
                    "EnsembleBuilder: no feature columns found in feature_vectors. "
                    "Check table schema."
                )

            # --- Enumerate strata ---
            strata_rows = await conn.fetch("""
                SELECT DISTINCT symbol, tf, regime
                FROM feature_ic_scores
                WHERE is_pooled = false AND passes_walkforward = true AND reliable = true
                  AND ic_sharpe IS NOT NULL AND regime IS NOT NULL
                ORDER BY symbol, tf, regime
                """)
            self.logger.info("ensemble_builder.strata_found", stratum_count=len(strata_rows))

            total_weights_written = 0
            total_alpha_written = 0

            for stratum in strata_rows:
                symbol = stratum["symbol"]
                tf = stratum["tf"]
                regime = stratum["regime"]

                await self._process_stratum(
                    conn=conn,
                    symbol=symbol,
                    tf=tf,
                    regime=regime,
                    feature_cols=feature_cols,
                    weight_version=weight_version,
                    max_feature_weight=max_feature_weight,
                    min_passing_features=min_passing_features,
                    max_cluster_corr=max_cluster_corr,
                    max_cluster_weight=max_cluster_weight,
                )
                total_weights_written += 1
                total_alpha_written += 1

        self.logger.info(
            "ensemble_builder.complete",
            strata_processed=len(strata_rows),
        )

    async def _process_stratum(
        self,
        conn: asyncpg.Connection,
        symbol: str,
        tf: str,
        regime: str,
        feature_cols: list[str],
        weight_version: str,
        max_feature_weight: float,
        min_passing_features: int,
        max_cluster_corr: float,
        max_cluster_weight: float,
    ) -> None:
        """Process one (symbol, tf, regime) stratum end-to-end."""
        log = self.logger.bind(symbol=symbol, tf=tf, regime=regime)

        # Step 1: Load IC scores for this stratum
        ic_rows = await conn.fetch(
            """
            SELECT feature_name, ic_sharpe, ic_ci_lower, ic_ci_upper, ic_sign, lookahead_bars
            FROM feature_ic_scores
            WHERE symbol = $1 AND tf = $2 AND regime = $3
              AND is_pooled = false AND passes_walkforward = true
              AND reliable = true AND ic_sharpe IS NOT NULL
            """,
            symbol,
            tf,
            regime,
        )
        if not ic_rows:
            log.debug("ensemble_builder.stratum_no_ic_rows")
            return

        # Step 2: Select best lookahead per feature
        selected = select_features_per_stratum([dict(r) for r in ic_rows])
        if len(selected) < min_passing_features:
            log.debug(
                "ensemble_builder.stratum_skipped_min_features",
                n_features=len(selected),
                min_required=min_passing_features,
            )
            return

        feature_names = [r["feature_name"] for r in selected]
        ic_sharpes = np.array([float(r["ic_sharpe"]) for r in selected])
        ic_signs = np.array([float(r["ic_sign"]) for r in selected])
        ic_ci_lower = np.array([float(r["ic_ci_lower"]) for r in selected])
        ic_ci_upper = np.array([float(r["ic_ci_upper"]) for r in selected])
        lookahead_bars = [int(r["lookahead_bars"]) for r in selected]

        # Step 3: Load feature matrix X from feature_vectors (regime filter — no cross-regime bias)
        # Build column list safely (names come from information_schema, not user input)
        col_subset = [c for c in feature_cols if c in feature_names]
        if len(col_subset) < min_passing_features:
            log.debug(
                "ensemble_builder.stratum_skipped_missing_cols",
                n_cols=len(col_subset),
                min_required=min_passing_features,
            )
            return

        # Map feature names to column indices
        col_idx = {name: i for i, name in enumerate(col_subset)}
        feature_name_to_col = {name: col_idx[name] for name in feature_names if name in col_idx}
        if len(feature_name_to_col) < min_passing_features:
            log.debug(
                "ensemble_builder.stratum_skipped_col_mismatch", n_mapped=len(feature_name_to_col)
            )
            return

        # Reorder selected features to match column order
        ordered_names = [n for n in feature_names if n in feature_name_to_col]
        ordered_idx = [feature_names.index(n) for n in ordered_names]
        ic_sharpes = ic_sharpes[ordered_idx]
        ic_signs = ic_signs[ordered_idx]
        ic_ci_lower = ic_ci_lower[ordered_idx]
        ic_ci_upper = ic_ci_upper[ordered_idx]
        lookahead_bars = [lookahead_bars[i] for i in ordered_idx]

        # Fetch feature matrix (regime-filtered) — col_subset sorted by ordinal
        # Safe: col_subset names come from information_schema, not user data
        col_list = ", ".join(f'"{c}"' for c in col_subset)
        fv_rows = await conn.fetch(
            f"""
            SELECT {col_list}, bar_ts
            FROM feature_vectors
            WHERE symbol = $1 AND tf = $2 AND regime = $3
            ORDER BY bar_ts
            """,
            symbol,
            tf,
            regime,
        )
        if len(fv_rows) < 2:
            log.debug("ensemble_builder.stratum_insufficient_bars", n_bars=len(fv_rows))
            return

        bar_ts_list = [r["bar_ts"] for r in fv_rows]
        X_raw = np.array(
            [[float(r[c]) if r[c] is not None else 0.0 for c in col_subset] for r in fv_rows],
            dtype=float,
        )  # shape [n_bars, n_features]

        # Map feature order in X to the IC-selected feature order
        ordered_col_indices = [col_subset.index(n) for n in ordered_names]
        X = X_raw[:, ordered_col_indices]  # [n_bars, n_selected_features]

        # Step 4: Compute LW covariance + cluster deflate weights
        raw_weights = derive_weights(ic_sharpes, max_feature_weight)

        cov_matrix, shrinkage = compute_shrinkage_covariance(X)

        # Convert to correlation matrix for cluster detection
        diag_var = np.diag(cov_matrix)
        with np.errstate(divide="ignore", invalid="ignore"):
            outer_std = np.sqrt(np.outer(diag_var, diag_var))
            corr_matrix = np.where(outer_std > 1e-10, cov_matrix / outer_std, 0.0)
            np.fill_diagonal(corr_matrix, 1.0)

        weights = cluster_deflate_weights(
            raw_weights, corr_matrix, max_cluster_corr, max_cluster_weight
        )

        # Zero-weight guard (Finding 2 blocker)
        if float(weights.sum()) < 1e-10:
            log.warning(
                "ensemble_builder.stratum_zero_weight_vector",
                reason="zero_weight_vector",
                symbol=symbol,
                tf=tf,
                regime=regime,
            )
            ENSEMBLE_FEATURES_ZERO_WEIGHT_GAUGE.set(
                len(ordered_names),
                {"symbol": symbol, "tf": tf, "weight_version": weight_version},
            )
            return

        eff_n = effective_n(weights)

        # Emit OTel gauges
        ENSEMBLE_SHRINKAGE_INTENSITY_GAUGE.set(
            shrinkage, {"symbol": symbol, "tf": tf, "weight_version": weight_version}
        )
        ENSEMBLE_EFFECTIVE_N_GAUGE.set(
            eff_n, {"symbol": symbol, "tf": tf, "weight_version": weight_version}
        )
        zero_weight_count = int(np.sum(weights < 1e-10))
        ENSEMBLE_FEATURES_ZERO_WEIGHT_GAUGE.set(
            zero_weight_count, {"symbol": symbol, "tf": tf, "weight_version": weight_version}
        )
        for fname, w in zip(ordered_names, weights.tolist()):
            ENSEMBLE_FEATURE_WEIGHT_GAUGE.set(
                w,
                {
                    "feature": fname,
                    "symbol": symbol,
                    "tf": tf,
                    "weight_version": weight_version,
                },
            )

        # Step 5: Write ensemble_weights atomically (all rows for this weight_version or none)
        now = datetime.now(UTC)
        weight_rows = [
            (
                symbol,
                tf,
                regime,
                weight_version,
                ordered_names[i],
                float(raw_weights[i]),
                float(weights[i]),
                float(ic_sharpes[i]),
                lookahead_bars[i],
                eff_n,
            )
            for i in range(len(ordered_names))
        ]

        async with conn.transaction():
            await conn.executemany(
                """
                INSERT INTO ensemble_weights
                    (symbol, tf, regime, weight_version, feature_name,
                     raw_weight, weight, ic_sharpe, lookahead_bars, effective_n, computed_at)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
                ON CONFLICT (symbol, tf, regime, weight_version, feature_name) DO NOTHING
                """,
                [(*row, now) for row in weight_rows],
            )

        log.info(
            "ensemble_builder.weights_written",
            n_features=len(weight_rows),
            effective_n=round(eff_n, 3),
            shrinkage=round(shrinkage, 4),
        )

        # Step 6: Score ensemble_alpha via vectorized matmul (no per-bar Python loop)
        signed_weights = weights * ic_signs  # [n_features]
        alpha_scores = X @ signed_weights  # [n_bars] — single matmul

        # Analytic CI: compute margin once per stratum (constant for all bars)
        ic_sigma = (ic_ci_upper - ic_ci_lower) / 3.92
        margin = 1.96 * float(np.sqrt(float(np.dot(weights**2, ic_sigma**2))))

        ci_lower_arr = alpha_scores - margin
        ci_upper_arr = alpha_scores + margin

        n_features_active = int(np.sum(weights > 1e-10))

        # Bulk insert all n_bars rows into ensemble_alpha
        alpha_rows = [
            (
                symbol,
                tf,
                bar_ts_list[i],
                weight_version,
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

        await conn.executemany(
            """
            INSERT INTO ensemble_alpha
                (symbol, tf, bar_ts, weight_version, regime,
                 alpha_score, alpha_ci_lower, alpha_ci_upper,
                 effective_n, n_features_active, computed_at)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
            ON CONFLICT (symbol, tf, bar_ts, weight_version) DO NOTHING
            """,
            alpha_rows,
        )

        log.info(
            "ensemble_builder.alpha_written",
            n_bars=len(alpha_rows),
            margin=round(margin, 4),
        )


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    try:
        init_otel_providers("indicagent-ensemble-builder")
    except OTelInitError as error:
        _logger.warning("ensemble_builder.otel_init_failed", error=str(error))

    settings = Settings()
    db_dsn = settings.database_url.replace("postgresql+asyncpg://", "postgresql://")
    asyncio.run(EnsembleBuilder(db_dsn=db_dsn).run())
