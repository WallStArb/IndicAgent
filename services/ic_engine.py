#!/usr/bin/env python3
"""IC Engine -- Spearman IC measurement substrate for v3.0 AlphaEngine.

Computes Information Coefficient (IC) per feature x symbol x TF x regime x lookahead,
with Fisher z-transform confidence intervals, BH-FDR multiple-testing correction,
60-bar-embargo walk-forward validation, IC Sharpe, and idempotent upsert into
feature_ic_scores.

CORRECTNESS INVARIANTS:
- CI uses Fisher z-transform (exact asymptotic, O(p)). Replaces circular block bootstrap
  which had a pre-ranking bug (resampling global ranks instead of re-ranking within sample)
  and was redundant at our sample sizes (n > 500 everywhere; CLT fully converged).
- Walk-forward has a 60-bar purge/embargo between training-fold end and test-fold start.
  60 bars = max(lookaheads) for the [1,5,20,60] set. Prevents overlapping forward-return
  labels from leaking across the fold boundary (lookahead bias).
- Degenerate features (std(X[:,j]) < 1e-8) are skipped before rankdata and tracked with
  IC_ENGINE_CELLS_SKIPPED_TOTAL{skip_reason=degenerate_feature}.
- Pooled rows have is_pooled=true, regime='_pooled' (sentinel; PK requires non-NULL).
- Regime-stratified rows have is_pooled=false, regime=<label>.
- ON CONFLICT uses column list + WHERE clause (partial index; not named CONSTRAINT).
- Idempotent: ON CONFLICT DO NOTHING. Re-run inserts 0 rows.
- Crash-loud: three startup gates raise RuntimeError with explicit messages.
- IC Sharpe gate: n_windows_possible >= sharpe_min_windows (checked on actual complete rows).

DAG invariant note: this oneshot is exempt from the "only writer subclasses touch DB"
rule exactly as backfill_feature_factory.py is -- it is a batch measurement tool,
not a real-time daemon. The ring 2 boundary still holds: no async pipeline, no Kafka.

vector_domain for all 54 features in Phase 138 is 'quant' (all features are quantitative
factor estimates).

Usage:
    python services/ic_engine.py
    python services/ic_engine.py --symbols VUG --tf 1h
    python services/ic_engine.py --symbols SPY TLT --tf 5m 15m
"""

from __future__ import annotations

import argparse
import dataclasses
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import psycopg2
import psycopg2.extras
import structlog
from opentelemetry import trace
from opentelemetry.trace import StatusCode
from scipy.cluster.hierarchy import fcluster, linkage
from scipy.spatial.distance import squareform
from scipy.stats import rankdata
from scipy.stats import t as t_dist
from statsmodels.stats.multitest import multipletests

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from services._batch_utils import load_config_service_sync as _load_config_service
from src.config.settings import Settings
from src.core.service_utils import setup_service_logging
from src.intelligence.feature_registry_service import FeatureRegistryService
from src.intelligence.schemas import FeatureVector
from src.observability.metrics import (
    EFFECTIVE_N_GAUGE,
    FEATURE_IC_PASSING_FDR_TOTAL,
    FEATURE_IC_PASSING_WALKFORWARD_TOTAL,
    FEATURES_SURVIVING_FDR_GAUGE,
    IC_ENGINE_CELLS_COMPLETED_TOTAL,
    IC_ENGINE_CELLS_SKIPPED_TOTAL,
    IC_ENGINE_RUN_LATENCY_SECONDS,
    IC_SCORE_GAUGE,
    IC_SHARPE_GAUGE,
    IC_SORTINO_GAUGE,
    IC_WIN_RATE_GAUGE,
    JOB_COMPLETED_TOTAL,
    flush_and_shutdown_metrics,
)
from src.observability.otel import OTelInitError, init_otel_providers

setup_service_logging("logs/ic_engine.log")

_logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_JOB = "ic-engine"

# Vector domain for all Phase 138 features -- quantitative factor estimates.
# Future expansions (micro-structure, macro) would use different domain labels.
_VECTOR_DOMAIN = "quant"

# Feature names derived from FeatureVector dataclass -- stays in sync automatically.
# Do NOT hardcode the 61 names; this list is the single source of truth.
_FEATURE_NAMES: list[str] = [f.name for f in dataclasses.fields(FeatureVector)]

# Gradient scale names for forward return horizons (matching forward_returns columns).
_SCALES: tuple[str, ...] = ("fast", "mid", "slow", "extended")

# Sentinel regime value for pooled (cross-regime) IC rows.
# The feature_ic_scores PK includes regime (NOT NULL), so we can't store NULL.
# is_pooled=true + regime='_pooled' is the canonical pooled-row identity.
_POOLED_REGIME_SENTINEL = "_pooled"

# Default TFs if not passed via --tf
_DEFAULT_TFS: list[str] = ["5m", "15m", "1h", "1d"]

# TF string to PostgreSQL interval string, used in DATE_TRUNC and JOIN on market_regimes.
TF_TO_INTERVAL: dict[str, str] = {
    "5m": "5 minutes",
    "15m": "15 minutes",
    "1h": "1 hour",
    "1d": "1 day",
}

# Cross-sectional symbol sentinel: used when symbol='POOLED' (all 58 equity ETFs pooled).
# feature_ic_scores.symbol is NOT NULL, so we use a string sentinel.
_CROSS_SECTIONAL_SYMBOL = "POOLED"

# vix_z, flight_quality, yield_slope_z are daily-cadence features stored in context_features.
# IC computation uses one observation per calendar day, not one per bar.
# Measuring IC from feature_vectors would inflate IC via artificial autocorrelation
# (same daily value duplicated ~78 times for 5m TF).
# DISTINCT ON (DATE(bar_ts)) picks the earliest intraday bar of each day as the IC observation.
# Phase 141 CORPUS-01 audit must scope its intraday-autocorrelation check to exclude these features.
CONTEXT_FEATURES: frozenset[str] = frozenset(["flight_quality", "vix_z", "yield_slope_z"])

# ---------------------------------------------------------------------------
# Module-level INSERT SQL (shared body; conflict clause differs by row type)
# ---------------------------------------------------------------------------

_INSERT_BODY = """
    INSERT INTO feature_ic_scores (
        feature_name, vector_domain, symbol, tf, regime, lookahead_bars,
        training_window_end, is_pooled, n_independent, reliable,
        ic_value, ic_sign, p_value, ic_ci_lower, ic_ci_upper, passes_ci_gate,
        bh_adjusted_p, passes_fdr, wf_fold_count, wf_pass_count, passes_walkforward,
        ic_sharpe, ic_sharpe_hac, ic_sharpe_n_windows, ic_sortino, ic_win_rate,
        regime_label_source, computed_at, cluster_id, feature_status_at_eval
    )
    VALUES (
        %(feature_name)s, %(vector_domain)s, %(symbol)s, %(tf)s, %(regime)s,
        %(lookahead_bars)s, %(training_window_end)s, %(is_pooled)s,
        %(n_independent)s, %(reliable)s, %(ic_value)s, %(ic_sign)s, %(p_value)s,
        %(ic_ci_lower)s, %(ic_ci_upper)s, %(passes_ci_gate)s, %(bh_adjusted_p)s,
        %(passes_fdr)s, %(wf_fold_count)s, %(wf_pass_count)s, %(passes_walkforward)s,
        %(ic_sharpe)s, %(ic_sharpe_hac)s, %(ic_sharpe_n_windows)s, %(ic_sortino)s, %(ic_win_rate)s,
        %(regime_label_source)s, %(computed_at)s, %(cluster_id)s,
        %(feature_status_at_eval)s
    )
"""
_POOLED_INSERT_SQL = (
    _INSERT_BODY
    + "    ON CONFLICT (feature_name, symbol, tf, lookahead_bars, training_window_end)\n"
    + "        WHERE is_pooled = true\n"
    + "    DO NOTHING\n"
)
_REGIME_INSERT_SQL = (
    _INSERT_BODY
    + "    ON CONFLICT (feature_name, symbol, tf, regime, lookahead_bars, training_window_end)\n"
    + "        WHERE is_pooled = false AND regime IS NOT NULL\n"
    + "    DO NOTHING\n"
)
# Cross-sectional INSERT uses the partial index from migration 174:
# (feature_name, symbol, tf, regime, lookahead_bars, training_window_end) WHERE is_pooled = true AND symbol = 'POOLED'
# The cross-sectional rows use regime = actual_regime_label (not '_pooled' sentinel).
_CROSS_SECTIONAL_INSERT_SQL = (
    _INSERT_BODY
    + "    ON CONFLICT (feature_name, symbol, tf, regime, lookahead_bars, training_window_end)\n"
    + "        WHERE is_pooled = true AND symbol = 'POOLED'\n"
    + "    DO NOTHING\n"
)


# ---------------------------------------------------------------------------
# Sync span helper -- matches observed_span semantics for sync psycopg2 services
# ---------------------------------------------------------------------------


@contextmanager
def _noop_span(name, **attrs):
    class _Noop:
        def set_attribute(self, k, v):
            pass

        def set_status(self, *a):
            pass

        def record_exception(self, *a):
            pass

    yield _Noop()


class _NoopTracer:
    """Subprocess-safe tracer stub — OTel spans must not be emitted from workers."""

    def start_as_current_span(self, name, attributes=None):
        return _noop_span(name)


@contextmanager
def _observed_span(name: str, tracer: Any, **attrs: Any):
    """Sync context manager wrapping an OTel span with ERROR auto-record."""
    with tracer.start_as_current_span(name, attributes=attrs) as span:
        try:
            yield span
        except Exception as error:
            span.set_status(StatusCode.ERROR, str(error))
            span.record_exception(error)
            raise


# ---------------------------------------------------------------------------
# DB connection
# ---------------------------------------------------------------------------


def _connect_db(settings: Settings) -> Any:
    """Open a psycopg2 connection to the TimescaleDB instance."""
    return _connect_db_from_url(settings.database_url)


def _connect_db_from_url(db_url: str) -> Any:
    """Open a psycopg2 connection from a raw DB URL."""
    conn = psycopg2.connect(db_url)
    conn.autocommit = False
    return conn


# ---------------------------------------------------------------------------
# APR loading
# ---------------------------------------------------------------------------


def _load_apr(conn: Any, tf: str) -> dict[str, Any]:
    """Load all IC engine APR parameters via ConfigService.

    Returns a dict with all tunable parameters. No inline numeric fallbacks
    in compute logic -- all fall through to here.
    """
    cfg = _load_config_service(conn)
    return {
        "min_observations": int(cfg.get_sync("alpha.ic.min_observations", 500)),
        "fdr_alpha": float(cfg.get_sync("alpha.ic.fdr_alpha", 0.05)),
        "walk_forward_folds": int(cfg.get_sync("alpha.ic.walk_forward_folds", 3)),
        "sharpe_window_size": int(cfg.get_sync("alpha.ic.sharpe_window_size", 2000)),
        "sharpe_min_windows": int(cfg.get_sync("alpha.ic.sharpe_min_windows", 10)),
        "subsample_min_stride": int(cfg.get_sync("alpha.ic.subsample_min_stride", 5)),
        "min_reliable_n": int(cfg.get_sync("alpha.ic.min_reliable_n", 100)),
        "cluster_max_corr": float(cfg.get_sync("alpha.ic.cluster_max_corr", 0.70)),
        # Lookaheads per scale -- loaded from APR; column names are gradient-scale identifiers
        "lookaheads": {
            scale: int(cfg.get_sync(f"alpha.ic.lookahead.{scale}", fb))
            for scale, fb in [("fast", 1), ("mid", 5), ("slow", 20), ("extended", 60)]
        },
        # Cross-sectional equity regime model flag (migration 174)
        "equity_model_enabled": str(
            cfg.get_sync("alpha.regime.equity_model_enabled", "true")
        ).lower()
        == "true",
        # Daily-cadence features use min_obs_daily_features gate (APR: alpha.ic.min_obs_daily_features);
        # standard 20K intraday gate does not apply — calibrated for different observation frequency.
        "min_obs_daily": int(cfg.get_sync("alpha.ic.min_obs_daily_features", 1000)),
        # Newey-West HAC max lag for IC Sharpe autocorrelation correction (migration 177).
        # K=0 disables HAC (ic_sharpe_hac == ic_sharpe).
        "hac_max_lag": int(cfg.get_sync("alpha.ic.hac_max_lag", 3)),
    }


# ---------------------------------------------------------------------------
# Startup crash-loud gates
# ---------------------------------------------------------------------------


def _assert_prerequisites(
    conn: Any, tfs: list[str] | None = None, equity_model_enabled: bool = True
) -> None:
    """Crash-loud startup gates. Three (or four) explicit RuntimeError raises.

    A run that 'succeeds' with empty feature_ic_scores is a data-integrity
    failure. These gates prevent it by failing loud before any compute.

    When equity_model_enabled=True, also verifies market_regimes has rows for each TF.
    """
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM feature_vectors")
        n_fv = cur.fetchone()[0]
    if n_fv == 0:
        raise RuntimeError(
            "IC Engine startup gate FAILED: feature_vectors is empty. "
            "Run services/backfill_feature_factory.py first."
        )

    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM feature_vectors WHERE regime IS NOT NULL")
        n_regime = cur.fetchone()[0]
    if n_regime == 0:
        raise RuntimeError(
            "IC Engine startup gate FAILED: feature_vectors.regime is all-NULL. "
            "Run services/regime_writer.py first."
        )

    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM forward_returns")
        n_fr = cur.fetchone()[0]
    if n_fr == 0:
        raise RuntimeError(
            "IC Engine startup gate FAILED: forward_returns is empty. "
            "Run services/forward_return_writer.py first."
        )

    # market_regimes prerequisite: required when equity_model_enabled=True
    if equity_model_enabled and tfs:
        for tf in tfs:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT count(*) FROM market_regimes WHERE asset_class='equity' AND tf=%s",
                    (tf,),
                )
                n_mr = cur.fetchone()[0]
            if n_mr == 0:
                raise RuntimeError(
                    f"IC Engine startup gate FAILED: market_regimes empty for tf={tf}. "
                    "Run services/equity_regime_model.py first."
                )


# ---------------------------------------------------------------------------
# Fisher z-transform CI for IC vectors
# ---------------------------------------------------------------------------

_Z95 = 1.959963985  # norm.ppf(0.975) — 95% two-tailed critical value


def _fisher_z_ci(
    ic_vector: np.ndarray,
    n: int,
) -> tuple[np.ndarray, np.ndarray]:
    """95% CI for Spearman IC via Fisher z-transform.

    Exact asymptotic CI equivalent to the bootstrap limit as n → ∞.
    O(p) vs O(n_boot × n × p) for block bootstrap. No RNG, no memory pressure.

    The circular block bootstrap it replaces had a pre-ranking bug: it resampled
    globally pre-ranked values instead of resampling raw observations and re-ranking
    within each sample, producing CIs that were systematically too narrow.

    Returns NaN arrays when n < 4 (arctanh undefined); upstream min_reliable_n gate
    already excludes these, but defensive here.
    """
    if n < 4:
        nan = np.full_like(ic_vector, np.nan, dtype=float)
        return nan, nan.copy()
    z = np.arctanh(np.clip(ic_vector, -1 + 1e-10, 1 - 1e-10))
    se = 1.0 / np.sqrt(n - 3)
    return np.tanh(z - _Z95 * se), np.tanh(z + _Z95 * se)


# ---------------------------------------------------------------------------
# Vectorized IC computation
# ---------------------------------------------------------------------------


def _vectorized_ic(ranks_X: np.ndarray, ranks_Y: np.ndarray) -> np.ndarray:
    """Vectorized Spearman IC via Pearson on pre-ranked inputs.

    Args:
        ranks_X: Shape [n_obs, n_features] -- pre-ranked.
        ranks_Y: Shape [n_obs] -- pre-ranked.

    Returns:
        ic_vector: Shape [n_features].
    """
    n = ranks_X.shape[0]
    if n < 2:
        return np.zeros(ranks_X.shape[1])
    X_c = ranks_X - ranks_X.mean(axis=0)
    Y_c = ranks_Y - ranks_Y.mean()
    denom = np.sqrt((X_c**2).sum(axis=0) * (Y_c**2).sum())
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.where(denom > 1e-10, (X_c * Y_c[:, None]).sum(axis=0) / denom, 0.0)


def compute_ic_vectorized(X: np.ndarray, y: np.ndarray) -> np.ndarray:
    """Compute vectorized Spearman IC between each column of X and y.

    Public wrapper around _vectorized_ic that accepts raw (unranked) inputs
    and handles ranking internally. Equivalent to scipy.stats.spearmanr(X[:,j], y)
    for each feature j, but computed simultaneously across all features via
    vectorized Pearson-on-ranks.

    Args:
        X: Shape [n_obs, n_features] -- raw feature values (not pre-ranked).
        y: Shape [n_obs] -- raw return vector (not pre-ranked).

    Returns:
        ic_vector: Shape [n_features] -- Spearman IC per feature.
    """
    ranks_X = rankdata(X, axis=0)
    ranks_y = rankdata(y)
    return _vectorized_ic(ranks_X, ranks_y)


def _expand(nd_arr: np.ndarray, mask: np.ndarray, n: int) -> np.ndarray:
    """Scatter nd_arr (non-degenerate features) into a NaN-filled n-length float array."""
    out = np.full(n, np.nan)
    out[mask] = nd_arr
    return out


def _nan_to_none(v: float) -> float | None:
    return None if np.isnan(v) else float(v)


def _p_values_from_ic(ic_vector: np.ndarray, n: int) -> np.ndarray:
    """Two-tailed p-values from IC via t-approximation.

    t = ic * sqrt((n-2) / max(1 - ic^2, 1e-10)), df = n-2.
    """
    t_stat = ic_vector * np.sqrt((n - 2) / np.maximum(1 - ic_vector**2, 1e-10))
    return 2.0 * (1.0 - t_dist.cdf(np.abs(t_stat), df=n - 2))


# ---------------------------------------------------------------------------
# Collinearity clustering
# ---------------------------------------------------------------------------


def _cluster_features(X_nd: np.ndarray, cluster_max_corr: float) -> np.ndarray:
    """Distance-threshold dendrogram clustering of non-degenerate feature columns.

    Returns a 1-based int cluster label per column (len == X_nd.shape[1]).
    NOTE: this is a dendrogram distance cutoff, NOT a guarantee that all pairs
    within a cluster exceed cluster_max_corr (transitive linkage can merge features
    whose direct correlation is below the threshold).
    """
    n_nd = X_nd.shape[1]
    if n_nd < 2:
        return np.ones(n_nd, dtype=int)
    corr = np.corrcoef(X_nd.T)
    corr = np.nan_to_num(corr, nan=0.0)
    dist = np.sqrt(0.5 * (1.0 - np.clip(corr, -1.0, 1.0)))
    np.fill_diagonal(dist, 0.0)
    Z = linkage(squareform(dist, checks=False), method="average")
    dist_threshold = np.sqrt(0.5 * (1.0 - cluster_max_corr))
    return fcluster(Z, t=dist_threshold, criterion="distance")  # 1-based ints


# ---------------------------------------------------------------------------
# IC Sharpe computation
# ---------------------------------------------------------------------------


def _hac_sharpe_nd(
    window_ics: np.ndarray,
    max_lag: int,
    mean_ic: np.ndarray | None = None,
    var0: np.ndarray | None = None,
) -> np.ndarray:
    """Newey-West Bartlett-kernel HAC-corrected IC Sharpe.

    Args:
        window_ics: [n_windows, n_features] IC values per rolling window.
        max_lag: Bartlett-kernel max lag K. K=0 returns naive Sharpe.
        mean_ic: Pre-computed column means (optional; computed internally if absent).
        var0: Pre-computed population variance per feature (optional; avoids recomputation
              when the caller already holds mean_ic and std_ic).

    Returns:
        sharpe_hac: [n_features]. Equal to naive Sharpe when max_lag=0 or
        when the IC series has zero autocorrelation. Always <= naive Sharpe
        for positively autocorrelated IC series (inflation floored at 1).
    """
    n, p = window_ics.shape
    if mean_ic is None:
        mean_ic = window_ics.mean(axis=0)
    if var0 is None:
        var0 = ((window_ics - mean_ic) ** 2).mean(axis=0)

    if max_lag == 0 or n < max_lag + 2:
        hac_std = np.sqrt(var0)
        return np.where(hac_std > 1e-10, mean_ic / hac_std, 0.0)

    demeaned = window_ics - mean_ic
    inflation = np.ones(p)
    for k in range(1, max_lag + 1):
        gamma_k = (demeaned[k:] * demeaned[:-k]).mean(axis=0)
        rho_k = np.where(var0 > 1e-12, gamma_k / var0, 0.0)
        inflation += 2.0 * (1.0 - k / (max_lag + 1)) * rho_k

    inflation = np.maximum(inflation, 1.0)  # can't be more precise than i.i.d.
    hac_std = np.sqrt(var0 * inflation)
    return np.where(hac_std > 1e-10, mean_ic / hac_std, 0.0)


def _compute_ic_rolling_metrics(
    X_sub: np.ndarray,
    returns_sub: np.ndarray,
    scale_idx: int,
    complete_mask: np.ndarray,
    apr: dict[str, Any],
    non_degenerate_mask: np.ndarray,
    n_total_features: int,
    stride: int,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, int]:
    """Compute IC Sharpe, HAC Sharpe, Sortino, and win rate via rolling non-overlapping windows.

    Gate: n_windows_possible >= sharpe_min_windows.
    Returns NaN arrays when gate not met.

    IC Sharpe     = mean(window_ICs) / std(window_ICs)                       [symmetric]
    IC Sharpe HAC = mean(window_ICs) / (std(window_ICs) * sqrt(NW_inflation)) [autocorr-adjusted]
    IC Sortino    = mean(window_ICs) / semi_dev(neg windows)                  [downside only]
                    NaN when no windows have IC < 0 (ratio undefined)
    IC win rate   = fraction of windows where IC > 0                          [stability]

    Args:
        stride: Subsampling stride used to create X_sub/returns_sub. sharpe_window_size
                from APR is in RAW bars, so we divide by stride to get subsampled bars.

    Returns: (sharpe_arr, sharpe_hac_arr, sortino_arr, win_rate_arr, n_windows)
    """
    # sharpe_window_size is in RAW bars; convert to SUBSAMPLED bars via floor division.
    # Precision loss: e.g., 1999 raw bars with stride=10 → 199 subsampled bars (10% loss from 200).
    # Floor division ensures we never exceed available subsampled data.
    sharpe_window_size_raw = apr["sharpe_window_size"]
    sharpe_window_size = max(1, sharpe_window_size_raw // stride)
    sharpe_min_windows = apr["sharpe_min_windows"]

    nan_result = np.full(n_total_features, np.nan)
    n_windows = 0

    if complete_mask.sum() < 2:
        return nan_result, nan_result, nan_result, nan_result, n_windows

    X_aligned = X_sub[complete_mask]
    Y_aligned = returns_sub[complete_mask, scale_idx]

    n = len(X_aligned)
    n_windows_possible = n // sharpe_window_size
    if n_windows_possible < sharpe_min_windows:
        return nan_result, nan_result, nan_result, nan_result, n_windows

    window_ics_list = []
    for w in range(n_windows_possible):
        start = w * sharpe_window_size
        end = start + sharpe_window_size
        wx = X_aligned[start:end][:, non_degenerate_mask]
        wy = Y_aligned[start:end]
        if len(wx) < 2:
            continue
        rx = rankdata(wx, axis=0)
        ry = rankdata(wy)
        window_ics_list.append(_vectorized_ic(rx, ry))

    n_windows = len(window_ics_list)
    if n_windows < sharpe_min_windows:
        return nan_result, nan_result, nan_result, nan_result, n_windows

    window_ics = np.array(window_ics_list)  # [n_windows, n_non_degenerate]
    mean_ic = window_ics.mean(axis=0)
    var0 = ((window_ics - mean_ic) ** 2).mean(axis=0)
    std_ic = np.sqrt(var0)

    sharpe_nd = np.where(std_ic > 1e-10, mean_ic / std_ic, 0.0)
    sharpe_hac_nd = _hac_sharpe_nd(window_ics, apr["hac_max_lag"], mean_ic=mean_ic, var0=var0)

    # Sortino: penalise only negative-IC windows (target = 0)
    # NaN per feature when that feature has no negative windows (ratio undefined)
    neg_mask = window_ics < 0  # [n_windows, n_non_degenerate]
    sum_neg = neg_mask.sum(axis=0)  # reused for both gate and denominator
    semi_dev = np.where(
        sum_neg > 0,
        np.sqrt(np.where(neg_mask, window_ics**2, 0.0).sum(axis=0) / sum_neg),
        np.nan,
    )
    sortino_nd = np.where(semi_dev > 1e-10, mean_ic / semi_dev, np.nan)

    win_rate_nd = (window_ics > 0).mean(axis=0)

    n = n_total_features
    return (
        _expand(sharpe_nd, non_degenerate_mask, n),
        _expand(sharpe_hac_nd, non_degenerate_mask, n),
        _expand(sortino_nd, non_degenerate_mask, n),
        _expand(win_rate_nd, non_degenerate_mask, n),
        n_windows,
    )


# ---------------------------------------------------------------------------
# Main compute loop for a single (symbol, tf)
# ---------------------------------------------------------------------------


def _compute_symbol_tf(
    conn: Any,
    symbol: str,
    tf: str,
    training_window_end: Any,
    existing_keys: set[tuple] | frozenset[tuple],
    apr: dict[str, Any],
    tracer: Any,
    run_ts: datetime,
    feature_status_map: dict[str, str] | None = None,
    mr_dict: dict | None = None,
) -> dict[str, Any]:
    """Compute IC for all (regime, lookahead) cells for one (symbol, tf).

    feature_status_map: dict mapping feature_name → status from feature_registry.
    If provided, each IC score row receives feature_status_at_eval from this map.
    Defaults to 'unknown' for any feature not found in the map.

    mr_dict: optional dict {ts -> regime_label} from market_regimes for this TF.
    When provided (equity_model_enabled=True), regime labels come from market_regimes
    instead of feature_vectors.regime, enabling cross-symbol IC stratification.
    When None (equity_model_enabled=False), falls back to feature_vectors.regime.

    Returns summary statistics for logging.
    """
    lookaheads = apr["lookaheads"]
    subsample_min_stride = apr["subsample_min_stride"]
    min_reliable_n = apr["min_reliable_n"]
    fdr_alpha = apr["fdr_alpha"]
    walk_forward_folds = apr["walk_forward_folds"]
    cluster_max_corr = apr["cluster_max_corr"]
    n_features = len(_FEATURE_NAMES)

    with _observed_span("ic_engine.compute_symbol_tf", tracer, symbol=symbol, tf=tf):
        # ------------------------------------------------------------------
        # Load feature matrix
        # ------------------------------------------------------------------
        feature_cols = ", ".join(f'"{f}"' for f in _FEATURE_NAMES)
        fv_sql = f"""
            SELECT bar_ts, regime, {feature_cols}
            FROM feature_vectors
            WHERE symbol = %s AND tf = %s AND bar_ts <= %s
            ORDER BY bar_ts
        """
        # Stream rows from cursor to avoid materialising all 469K psycopg2 tuples at once.
        # fetchall() on a 469K × 63-column result = ~1.1 GB Python heap per worker; with
        # 12 parallel workers that peaks at ~24 GB and OOM-kills the pool.
        # psycopg2 cursor iteration batches via fetchmany(itersize) under the hood, keeping
        # only ~2000 live tuples at a time while we build native Python lists per column.
        bar_ts_list: list = []
        regime_list: list = []
        X_list: list = []
        with conn.cursor() as cur:
            cur.execute(fv_sql, (symbol, tf, training_window_end))
            for r in cur:
                bar_ts_list.append(r[0])
                regime_list.append(r[1])
                X_list.append(r[2:])

        if not bar_ts_list:
            _logger.info("ic_engine.no_feature_vectors", symbol=symbol, tf=tf)
            return {"n_committed": 0, "n_skipped": 0}

        n_raw_bars = len(bar_ts_list)
        bar_ts_arr = np.array(bar_ts_list)
        del bar_ts_list
        regime_arr = np.array(regime_list)
        del regime_list
        X_raw = np.array(X_list, dtype=float)
        del X_list

        # ------------------------------------------------------------------
        # Load forward returns aligned by bar_ts
        # ------------------------------------------------------------------
        return_cols = ", ".join(f"return_{s}" for s in _SCALES)
        complete_cols = ", ".join(f"complete_{s}" for s in _SCALES)
        fr_sql = f"""
            SELECT bar_ts, {return_cols}, {complete_cols}
            FROM forward_returns
            WHERE symbol = %s AND tf = %s AND bar_ts <= %s
            ORDER BY bar_ts
        """
        with conn.cursor() as cur:
            cur.execute(fr_sql, (symbol, tf, training_window_end))
            fr_rows = cur.fetchall()

        if not fr_rows:
            _logger.info("ic_engine.no_forward_returns", symbol=symbol, tf=tf)
            return {"n_committed": 0, "n_skipped": 0}

        fr_ts = {r[0]: r for r in fr_rows}
        del fr_rows  # dict lookup is sufficient; raw tuples no longer needed

        # Align feature matrix to forward_returns rows (exact bar_ts match)
        aligned_idx = [i for i, ts in enumerate(bar_ts_arr) if ts in fr_ts]
        if not aligned_idx:
            _logger.info("ic_engine.no_alignment", symbol=symbol, tf=tf)
            return {"n_committed": 0, "n_skipped": 0}

        aligned_idx_arr = np.array(aligned_idx)
        X_aligned = X_raw[aligned_idx_arr]
        del X_raw  # fancy index produces a copy; original no longer needed
        regime_aligned = regime_arr[aligned_idx_arr]
        del regime_arr
        bar_ts_aligned = bar_ts_arr[aligned_idx_arr]
        del bar_ts_arr

        n_scales = len(_SCALES)
        # returns_mat: [n_aligned, n_scales]; complete_mat: [n_aligned, n_scales]
        returns_mat = np.full((len(aligned_idx), n_scales), np.nan)
        complete_mat = np.zeros((len(aligned_idx), n_scales), dtype=bool)
        for i, ts in enumerate(bar_ts_aligned):
            row = fr_ts[ts]
            for j in range(n_scales):
                returns_mat[i, j] = row[1 + j] if row[1 + j] is not None else np.nan
                complete_mat[i, j] = bool(row[1 + n_scales + j])
        del fr_ts  # returns_mat/complete_mat are sufficient; dict no longer needed

        # Regime source: market_regimes (cross-sectional) or feature_vectors.regime (per-symbol).
        # When mr_dict is provided, map each aligned bar_ts to its cross-sectional regime.
        # Bars without a market_regimes entry get None (excluded from regime-stratified IC).
        if mr_dict is not None:
            # equity_model_enabled=True: use cross-sectional labels from market_regimes
            regime_aligned_market = np.array([mr_dict.get(ts) for ts in bar_ts_aligned])
            distinct_regimes = [r for r in set(regime_aligned_market) if r is not None]
        else:
            # equity_model_enabled=False: fallback to feature_vectors.regime (per-symbol)
            regime_aligned_market = regime_aligned
            distinct_regimes = [r for r in set(regime_aligned) if r is not None]

        # Process: each distinct regime + one pooled pass
        regime_passes = list(distinct_regimes) + [_POOLED_REGIME_SENTINEL]

        # Collect all result dicts + parallel p-value list for BH-FDR per (symbol,tf)
        all_results: list[dict] = []
        pvals_flat: list[float] = []
        pval_result_idxs: list[int] = []

        n_committed = 0
        n_skipped = 0

        for regime_label in regime_passes:
            is_pooled = regime_label == _POOLED_REGIME_SENTINEL
            # Mask rows for this regime.
            # When equity_model_enabled=True (mr_dict provided): regime_aligned_market is the
            # cross-sectional label array. When False: regime_aligned_market == regime_aligned.
            if is_pooled:
                mask = np.ones(len(aligned_idx), dtype=bool)
            else:
                mask = regime_aligned_market == regime_label

            X_regime = X_aligned[mask]
            returns_regime = returns_mat[mask]
            complete_regime = complete_mat[mask]
            n_regime_raw = X_regime.shape[0]

            # ------------------------------------------------------------------
            # Degenerate feature detection on FULL regime data (std < 1e-8 = constant column).
            # Using X_regime (not a subsample) ensures the mask is stable across all scales
            # regardless of stride. A feature constant in the full regime is constant in any
            # subsample — but the converse may not hold for large strides.
            # ------------------------------------------------------------------
            feature_stds = np.std(X_regime, axis=0)
            degenerate_mask = feature_stds < 1e-8
            non_degenerate_mask = ~degenerate_mask
            n_degenerate = degenerate_mask.sum()
            if n_degenerate > 0:
                for _ in range(n_degenerate):
                    IC_ENGINE_CELLS_SKIPPED_TOTAL.add(
                        1,
                        {"symbol": symbol, "tf": tf, "skip_reason": "degenerate_feature"},
                    )
                n_skipped += n_degenerate

            # Non-degenerate slice of full regime matrix — shared across scales.
            X_regime_nd = X_regime[:, non_degenerate_mask]
            if X_regime_nd.shape[1] == 0:
                continue

            # embargo_bars for walk-forward: max lookahead across all scales.
            # Set once per regime so all scales share the same embargo boundary.
            embargo_bars = max(lookaheads.values())

            # ------------------------------------------------------------------
            # Distance-threshold dendrogram clustering per (symbol, tf, regime)
            # NOTE: dendrogram distance cutoff -- transitive linkage can merge
            # features whose direct pairwise correlation is below cluster_max_corr.
            # ------------------------------------------------------------------
            cluster_ids_nd = _cluster_features(X_regime_nd, cluster_max_corr)
            # Expand to full feature space: None for degenerate, cluster_id for non-degenerate
            cluster_id_full: list[int | None] = [None] * n_features
            nd_positions = np.where(non_degenerate_mask)[0]
            for _i, _pos in enumerate(nd_positions):
                cluster_id_full[_pos] = int(cluster_ids_nd[_i])

            _logger.info(
                "ic_engine.clustering",
                symbol=symbol,
                tf=tf,
                regime=regime_label,
                n_clusters=int(cluster_ids_nd.max()) if len(cluster_ids_nd) > 0 else 0,
                n_features=len(cluster_ids_nd),
            )

            for scale_idx, scale in enumerate(_SCALES):
                lookahead_bars = lookaheads[scale]

                # Per-scale subsampling: stride = max(min_stride, lookahead_bars).
                # Fast scale (lookahead=1) uses stride=min_stride, giving ~N/5 obs per regime.
                # Extended scale (lookahead=60) uses stride=60, giving ~N/60 obs per regime.
                # Previously all scales used stride=60, starving fast scale by 60x.
                scale_stride = max(subsample_min_stride, lookahead_bars)
                sub_idx = np.arange(0, n_regime_raw, scale_stride)
                X_sub_scale = X_regime[sub_idx]  # full features for _compute_ic_rolling_metrics
                X_sub_nd = X_regime_nd[sub_idx]  # non-degen columns for rankdata
                returns_sub = returns_regime[sub_idx]
                complete_sub = complete_regime[sub_idx]
                n_independent = len(sub_idx)

                if n_independent < min_reliable_n:
                    IC_ENGINE_CELLS_SKIPPED_TOTAL.add(
                        len(_FEATURE_NAMES),
                        {"symbol": symbol, "tf": tf, "skip_reason": "insufficient_n"},
                    )
                    n_skipped += len(_FEATURE_NAMES)
                    continue

                # Filter to complete rows for this lookahead
                scale_complete = complete_sub[:, scale_idx]
                returns_scale = returns_sub[:, scale_idx]
                valid_mask = scale_complete & np.isfinite(returns_scale)
                n_valid = valid_mask.sum()

                if n_valid < min_reliable_n:
                    IC_ENGINE_CELLS_SKIPPED_TOTAL.add(
                        len(_FEATURE_NAMES),
                        {"symbol": symbol, "tf": tf, "skip_reason": "insufficient_n"},
                    )
                    n_skipped += len(_FEATURE_NAMES)
                    continue

                ranks_X_scale = rankdata(X_sub_nd, axis=0)[valid_mask]
                Y_scale = returns_scale[valid_mask]
                ranks_Y = rankdata(Y_scale)

                # -------------------------------------------------------
                # IC point estimate + p-values
                # -------------------------------------------------------
                ic_vector_nd = _vectorized_ic(ranks_X_scale, ranks_Y)
                p_vector_nd = _p_values_from_ic(ic_vector_nd, n_valid)

                # Expand back to full feature space (NaN for degenerate)
                ic_full = _expand(ic_vector_nd, non_degenerate_mask, n_features)
                p_full = _expand(p_vector_nd, non_degenerate_mask, n_features)

                # -------------------------------------------------------
                # Fisher z-transform CI
                # -------------------------------------------------------
                ci_lower_nd, ci_upper_nd = _fisher_z_ci(ic_vector_nd, n_valid)

                ci_lower_full = _expand(ci_lower_nd, non_degenerate_mask, n_features)
                ci_upper_full = _expand(ci_upper_nd, non_degenerate_mask, n_features)
                passes_ci_full = np.where(non_degenerate_mask, ci_lower_full > 0.0, False)

                # -------------------------------------------------------
                # Walk-forward with 60-bar embargo
                # -------------------------------------------------------
                # embargo_bars = max(lookaheads) = 60 bars (set once per regime above).
                # This equals the maximum forward-return window in the [1,5,20,60]
                # set. Derived from APR-backed lookaheads, not a magic number.

                fold_ics_list: list[np.ndarray] = []
                for k in range(walk_forward_folds):
                    train_end = int(n_valid * (k + 1) / (walk_forward_folds + 1))
                    test_start = train_end + embargo_bars
                    test_end = int(n_valid * (k + 2) / (walk_forward_folds + 1))
                    if test_start >= test_end or (test_end - test_start) < min_reliable_n:
                        continue
                    X_test = ranks_X_scale[test_start:test_end]
                    Y_test = ranks_Y[test_start:test_end]
                    if len(X_test) < 2:
                        continue
                    rX_test = rankdata(X_test, axis=0)
                    rY_test = rankdata(Y_test)
                    fold_ics_list.append(_vectorized_ic(rX_test, rY_test))

                wf_fold_count = len(fold_ics_list)
                if wf_fold_count > 0:
                    fold_ic_arr = np.array(fold_ics_list)  # [n_folds, n_nd]
                    wf_pass_count_nd = (fold_ic_arr > 0).sum(axis=0)
                    passes_wf_nd = wf_pass_count_nd == walk_forward_folds
                else:
                    wf_pass_count_nd = np.zeros(len(ic_vector_nd), dtype=int)
                    passes_wf_nd = np.zeros(len(ic_vector_nd), dtype=bool)

                wf_pass_full = np.zeros(n_features, dtype=int)
                passes_wf_full = np.zeros(n_features, dtype=bool)
                wf_pass_full[non_degenerate_mask] = wf_pass_count_nd
                passes_wf_full[non_degenerate_mask] = passes_wf_nd

                # -------------------------------------------------------
                # IC Sharpe / Sortino / win rate (rolling windows)
                # -------------------------------------------------------
                (
                    ic_sharpe_arr,
                    ic_sharpe_hac_arr,
                    ic_sortino_arr,
                    ic_win_rate_arr,
                    n_sharpe_windows,
                ) = _compute_ic_rolling_metrics(
                    X_sub_scale,  # full feature matrix; _compute_ic_rolling_metrics applies non_degenerate_mask internally
                    returns_sub,
                    scale_idx,
                    complete_sub[:, scale_idx],
                    apr,
                    non_degenerate_mask,
                    n_features,
                    scale_stride,  # per-scale stride for raw→subsampled window conversion
                )

                # -------------------------------------------------------
                # Collect results -- BH-FDR is applied after all regimes/scales
                # using representative-only selection per cluster.
                # -------------------------------------------------------
                for feat_idx, feat_name in enumerate(_FEATURE_NAMES):
                    cell_key = (feat_name, symbol, tf, regime_label, lookahead_bars, is_pooled)
                    if cell_key in existing_keys:
                        IC_ENGINE_CELLS_SKIPPED_TOTAL.add(
                            1,
                            {"symbol": symbol, "tf": tf, "skip_reason": "already_present"},
                        )
                        n_skipped += 1
                        continue

                    ic_val = ic_full[feat_idx]
                    p_val = p_full[feat_idx]
                    all_results.append(
                        {
                            "feature_name": feat_name,
                            "vector_domain": _VECTOR_DOMAIN,
                            "symbol": symbol,
                            "tf": tf,
                            "regime": regime_label,
                            "lookahead_bars": lookahead_bars,
                            "training_window_end": training_window_end,
                            "is_pooled": is_pooled,
                            "n_independent": int(n_valid),
                            "reliable": bool(n_valid >= min_reliable_n),
                            "ic_value": _nan_to_none(ic_val),
                            "ic_sign": (None if np.isnan(ic_val) else (1 if ic_val > 0 else -1)),
                            "p_value": _nan_to_none(p_val),
                            "ic_ci_lower": _nan_to_none(ci_lower_full[feat_idx]),
                            "ic_ci_upper": _nan_to_none(ci_upper_full[feat_idx]),
                            "passes_ci_gate": bool(passes_ci_full[feat_idx]),
                            "bh_adjusted_p": None,  # filled after BH-FDR pass
                            "passes_fdr": None,  # filled after BH-FDR pass
                            "wf_fold_count": wf_fold_count,
                            "wf_pass_count": int(wf_pass_full[feat_idx]),
                            "passes_walkforward": bool(passes_wf_full[feat_idx]),
                            "ic_sharpe": _nan_to_none(ic_sharpe_arr[feat_idx]),
                            "ic_sharpe_hac": _nan_to_none(ic_sharpe_hac_arr[feat_idx]),
                            "ic_sharpe_n_windows": int(n_sharpe_windows),
                            "ic_sortino": _nan_to_none(ic_sortino_arr[feat_idx]),
                            "ic_win_rate": _nan_to_none(ic_win_rate_arr[feat_idx]),
                            "regime_label_source": "forward_filter",
                            "computed_at": run_ts,
                            "cluster_id": cluster_id_full[feat_idx],
                            "feature_status_at_eval": (
                                feature_status_map.get(feat_name, "unknown")
                                if feature_status_map is not None
                                else "unknown"
                            ),
                        }
                    )

        # ------------------------------------------------------------------
        # Context features: daily-cadence features in context_features table.
        # vix_z, flight_quality, yield_slope_z are daily-cadence features stored in context_features.
        # IC computation uses one observation per calendar day, not one per bar.
        # Measuring IC from feature_vectors would inflate IC via artificial autocorrelation
        # (same daily value duplicated ~78 times for 5m TF).
        # DISTINCT ON (DATE(bar_ts)) picks the earliest intraday bar of each day as the IC observation.
        #
        # Daily-cadence features use min_obs_daily_features gate (APR: alpha.ic.min_obs_daily_features);
        # standard 20K intraday gate does not apply — calibrated for different observation frequency.
        # ------------------------------------------------------------------
        min_obs_daily = apr["min_obs_daily"]
        cf_embargo_bars = max(lookaheads.values())
        n_scales = len(_SCALES)

        return_cols_cf = ", ".join(f"fr.return_{s}" for s in _SCALES)
        complete_cols_cf = ", ".join(f"fr.complete_{s}" for s in _SCALES)
        cf_sql_tmpl = f"""
            SELECT DISTINCT ON (DATE(fv.bar_ts))
                DATE(fv.bar_ts)    AS obs_date,
                cf.value           AS feature_value,
                {return_cols_cf},
                {complete_cols_cf}
            FROM feature_vectors fv
            INNER JOIN context_features cf
                ON DATE(fv.bar_ts) = cf.feature_date
                AND cf.feature_name = %(feature_name)s
                AND cf.symbol = ''
            INNER JOIN forward_returns fr
                ON fv.symbol = fr.symbol AND fv.tf = fr.tf AND fv.bar_ts = fr.bar_ts
            WHERE fv.symbol = %(symbol)s
              AND fv.tf = %(tf)s
              AND fv.bar_ts <= %(training_window_end)s
            ORDER BY DATE(fv.bar_ts), fv.bar_ts ASC
        """

        for cf_idx, cf_name in enumerate(sorted(CONTEXT_FEATURES)):  # deterministic order
            with conn.cursor() as cur:
                cur.execute(
                    cf_sql_tmpl,
                    {
                        "feature_name": cf_name,
                        "symbol": symbol,
                        "tf": tf,
                        "training_window_end": training_window_end,
                    },
                )
                cf_rows = cur.fetchall()

            n_cf_days = len(cf_rows)
            # Daily-cadence features use min_obs_daily_features gate (APR: alpha.ic.min_obs_daily_features);
            # standard 20K intraday gate does not apply — calibrated for different observation frequency.
            if n_cf_days < min_obs_daily:
                IC_ENGINE_CELLS_SKIPPED_TOTAL.add(
                    n_scales,
                    {"symbol": symbol, "tf": tf, "skip_reason": "insufficient_daily_n"},
                )
                continue

            cf_vals = np.array([r[1] for r in cf_rows], dtype=float)
            cf_returns_mat = np.array(
                [
                    [r[2 + j] if r[2 + j] is not None else np.nan for j in range(n_scales)]
                    for r in cf_rows
                ],
                dtype=float,
            )
            cf_complete_mat = np.array(
                [[bool(r[2 + n_scales + j]) for j in range(n_scales)] for r in cf_rows],
                dtype=bool,
            )

            # Assign unique cluster ID for BH-FDR participation — each context feature is
            # its own cluster. Start at 10000 to avoid collision with per-symbol clustering
            # (scipy fcluster returns integers starting from 1; max ~61 for 61 features).
            cf_cluster_id = 10000 + cf_idx

            for scale_idx, scale in enumerate(_SCALES):
                lookahead_bars = lookaheads[scale]

                cell_key = (cf_name, symbol, tf, _POOLED_REGIME_SENTINEL, lookahead_bars, True)
                if cell_key in existing_keys:
                    IC_ENGINE_CELLS_SKIPPED_TOTAL.add(
                        1, {"symbol": symbol, "tf": tf, "skip_reason": "already_present"}
                    )
                    n_skipped += 1
                    continue

                scale_complete = cf_complete_mat[:, scale_idx]
                returns_scale = cf_returns_mat[:, scale_idx]
                valid_mask = scale_complete & np.isfinite(returns_scale) & np.isfinite(cf_vals)
                n_valid = int(valid_mask.sum())

                if n_valid < min_obs_daily:
                    IC_ENGINE_CELLS_SKIPPED_TOTAL.add(
                        1, {"symbol": symbol, "tf": tf, "skip_reason": "insufficient_daily_n"}
                    )
                    continue

                x_daily = cf_vals[valid_mask].reshape(-1, 1)  # [n_valid, 1] for vectorized IC
                y_daily = returns_scale[valid_mask]

                ranks_x_daily = rankdata(x_daily, axis=0)
                ranks_y_daily = rankdata(y_daily)

                ic_vec = _vectorized_ic(ranks_x_daily, ranks_y_daily)
                ic_val = _nan_to_none(float(ic_vec[0]))
                p_val = float(_p_values_from_ic(ic_vec, n_valid)[0])

                ci_lower_arr, ci_upper_arr = _fisher_z_ci(ic_vec, n_valid)
                ci_lower = float(ci_lower_arr[0])
                ci_upper = float(ci_upper_arr[0])
                passes_ci = ci_lower > 0.0

                # Walk-forward with cf_embargo_bars embargo
                wf_fold_count = 0
                wf_pass_count = 0
                passes_wf = False
                folds_counted = 0
                folds_passed = 0
                if n_valid >= walk_forward_folds * 2 + cf_embargo_bars:
                    for k in range(walk_forward_folds):
                        train_end = int(n_valid * (k + 1) / (walk_forward_folds + 1))
                        test_start = train_end + cf_embargo_bars
                        test_end = int(n_valid * (k + 2) / (walk_forward_folds + 1))
                        if test_start >= test_end or (test_end - test_start) < min_reliable_n:
                            continue
                        fold_len = test_end - test_start
                        if fold_len < 2:
                            continue
                        rx_fold = rankdata(x_daily[test_start:test_end], axis=0)
                        ry_fold = rankdata(y_daily[test_start:test_end])
                        fold_ic = float(_vectorized_ic(rx_fold, ry_fold)[0])
                        folds_counted += 1
                        if fold_ic > 0:
                            folds_passed += 1
                wf_fold_count = folds_counted
                wf_pass_count = folds_passed
                passes_wf = folds_counted > 0 and folds_passed == folds_counted

                # IC Sharpe — expected NaN for daily data.
                # sharpe_window_size (APR default 2000) is calibrated for intraday bars.
                # With ~1000-2995 daily observations, n // sharpe_window_size < sharpe_min_windows
                # and _compute_ic_rolling_metrics returns NaN. This is documented expected behavior:
                # daily-cadence features do not have enough history to fill the intraday Sharpe window.
                ic_sharpe_val = None
                ic_sharpe_hac_val = None
                ic_sortino_val = None
                ic_win_rate_val = None
                ic_sharpe_n_windows = 0

                all_results.append(
                    {
                        "feature_name": cf_name,
                        "vector_domain": _VECTOR_DOMAIN,
                        "symbol": symbol,
                        "tf": tf,
                        "regime": _POOLED_REGIME_SENTINEL,
                        "lookahead_bars": lookahead_bars,
                        "training_window_end": training_window_end,
                        "is_pooled": True,
                        "n_independent": n_valid,
                        "reliable": bool(n_valid >= min_reliable_n),
                        "ic_value": ic_val,
                        "ic_sign": (None if ic_val is None else (1 if ic_val > 0 else -1)),
                        "p_value": p_val,
                        "ic_ci_lower": ci_lower,
                        "ic_ci_upper": ci_upper,
                        "passes_ci_gate": passes_ci,
                        "bh_adjusted_p": None,
                        "passes_fdr": None,
                        "wf_fold_count": wf_fold_count,
                        "wf_pass_count": wf_pass_count,
                        "passes_walkforward": passes_wf,
                        "ic_sharpe": ic_sharpe_val,
                        "ic_sharpe_hac": ic_sharpe_hac_val,
                        "ic_sharpe_n_windows": ic_sharpe_n_windows,
                        "ic_sortino": ic_sortino_val,
                        "ic_win_rate": ic_win_rate_val,
                        "regime_label_source": "context_features",
                        "computed_at": run_ts,
                        "cluster_id": cf_cluster_id,
                        "feature_status_at_eval": (
                            feature_status_map.get(cf_name, "unknown")
                            if feature_status_map is not None
                            else "unknown"
                        ),
                    }
                )

        # ------------------------------------------------------------------
        # BH-FDR correction -- representative-only per (regime, lookahead, cluster)
        #
        # Within each (regime_label, lookahead_bars, cluster_id) group only the
        # feature with max(abs(ic_value)) enters multipletests. Non-representatives
        # receive passes_fdr=False and bh_adjusted_p=None directly. Degenerate
        # features (cluster_id is None) are also excluded from BH-FDR.
        # ------------------------------------------------------------------

        # Group results by (regime, lookahead, cluster_id) in a single pass.
        # Degenerate features (cluster_id is None, which implies p_value is None) are
        # excluded from BH-FDR and marked immediately.
        # Key: (regime_label, lookahead_bars, cluster_id) -> list of (abs_ic, result_idx)
        cluster_groups: dict[tuple, list[tuple[float, int]]] = {}
        for result_idx, r in enumerate(all_results):
            cid = r["cluster_id"]
            if cid is None:
                # Degenerate: no variance in regime data -> no p-value.
                r["bh_adjusted_p"] = None
                r["passes_fdr"] = False
                continue
            group_key = (r["regime"], r["lookahead_bars"], cid)
            ic_val = r["ic_value"]
            abs_ic = abs(ic_val) if ic_val is not None else 0.0
            cluster_groups.setdefault(group_key, []).append((abs_ic, result_idx))

        # Within each group pick the representative (max abs IC); the rest are non-reps.
        for group_key, candidates in cluster_groups.items():
            rep_result_idx = max(candidates, key=lambda x: x[0])[1]
            pvals_flat.append(float(all_results[rep_result_idx]["p_value"]))
            pval_result_idxs.append(rep_result_idx)
            # Non-representatives: FDR excluded.
            for _, non_rep_idx in candidates[1:]:
                all_results[non_rep_idx]["bh_adjusted_p"] = None
                all_results[non_rep_idx]["passes_fdr"] = False

        if pvals_flat:
            reject, p_corrected, _, _ = multipletests(pvals_flat, alpha=fdr_alpha, method="fdr_bh")
            for flat_idx, result_idx in enumerate(pval_result_idxs):
                all_results[result_idx]["bh_adjusted_p"] = float(p_corrected[flat_idx])
                all_results[result_idx]["passes_fdr"] = bool(reject[flat_idx])

        # ------------------------------------------------------------------
        # Batch INSERT into feature_ic_scores (SQL defined at module level)
        # ------------------------------------------------------------------
        pooled_rows = [r for r in all_results if r["is_pooled"]]
        regime_rows = [r for r in all_results if not r["is_pooled"]]

        if pooled_rows:
            with conn.cursor() as cur:
                psycopg2.extras.execute_batch(cur, _POOLED_INSERT_SQL, pooled_rows)
        if regime_rows:
            with conn.cursor() as cur:
                psycopg2.extras.execute_batch(cur, _REGIME_INSERT_SQL, regime_rows)
        conn.commit()

        n_committed = len(all_results)

        # ------------------------------------------------------------------
        # Per-cell OTel metrics
        # ------------------------------------------------------------------
        for regime_label in regime_passes:
            is_pooled = regime_label == _POOLED_REGIME_SENTINEL
            regime_results = [
                r
                for r in all_results
                if r["regime"] == regime_label and r["is_pooled"] == is_pooled
            ]
            if not regime_results:
                continue
            attrs = {"symbol": symbol, "tf": tf, "regime": regime_label}
            IC_ENGINE_CELLS_COMPLETED_TOTAL.add(len(regime_results), attrs)

        n_passing_fdr = sum(1 for r in all_results if r.get("passes_fdr"))
        n_passing_wf = sum(1 for r in all_results if r.get("passes_walkforward"))
        FEATURE_IC_PASSING_FDR_TOTAL.set(n_passing_fdr, {"symbol": symbol, "tf": tf})
        FEATURE_IC_PASSING_WALKFORWARD_TOTAL.set(n_passing_wf, {"symbol": symbol, "tf": tf})

        return {
            "n_committed": n_committed,
            "n_skipped": n_skipped,
            "n_passing_fdr": n_passing_fdr,
            "n_passing_wf": n_passing_wf,
            "all_results": all_results,
        }


# ---------------------------------------------------------------------------
# Cross-sectional IC computation (equity_model_enabled=True)
# ---------------------------------------------------------------------------


def _compute_cross_sectional_tf(
    conn: Any,
    tf: str,
    regime_label: str,
    training_window_end: Any,
    existing_keys: frozenset[tuple],
    apr: dict[str, Any],
    tracer: Any,
    run_ts: datetime,
    feature_status_map: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Compute cross-sectional IC for one (tf, regime_label) cell.

    Fetches feature_vectors JOIN market_regimes JOIN forward_returns for ALL 58 equity
    ETFs pooled into a single observation set. Computes Spearman IC across all symbols
    simultaneously — each (bar_ts, symbol) pair is an independent observation.

    The result is stored with symbol=_CROSS_SECTIONAL_SYMBOL ('POOLED'), is_pooled=True,
    regime=regime_label (actual label, not '_pooled' sentinel).

    Returns dict with n_committed, n_skipped, all_results.
    """
    lookaheads = apr["lookaheads"]
    subsample_min_stride = apr["subsample_min_stride"]
    min_reliable_n = apr["min_reliable_n"]
    fdr_alpha = apr["fdr_alpha"]
    walk_forward_folds = apr["walk_forward_folds"]
    cluster_max_corr = apr["cluster_max_corr"]
    n_features = len(_FEATURE_NAMES)

    tf_interval = TF_TO_INTERVAL.get(tf, "5 minutes")

    feature_cols = ", ".join(f'"fv"."{f}"' for f in _FEATURE_NAMES)
    return_cols = ", ".join(f'"fr".return_{s}' for s in _SCALES)
    complete_cols = ", ".join(f'"fr".complete_{s}' for s in _SCALES)

    cs_sql = f"""
        SELECT fv.bar_ts, {feature_cols}, {return_cols}, {complete_cols}
        FROM feature_vectors fv
        INNER JOIN market_regimes mr
            ON mr.asset_class = 'equity'
            AND mr.tf = %(tf)s
            AND mr.ts = DATE_TRUNC(%(tf_interval)s, fv.bar_ts)
            AND mr.regime_label = %(regime_label)s
        INNER JOIN forward_returns fr
            ON fr.symbol = fv.symbol
            AND fr.tf = fv.tf
            AND fr.bar_ts = fv.bar_ts
        WHERE fv.tf = %(tf)s
          AND fv.bar_ts <= %(training_window_end)s
        ORDER BY fv.bar_ts
    """

    with conn.cursor() as cur:
        cur.execute(
            cs_sql,
            {
                "tf": tf,
                "tf_interval": tf_interval,
                "regime_label": regime_label,
                "training_window_end": training_window_end,
            },
        )
        cs_rows = cur.fetchall()

    if not cs_rows:
        _logger.info(
            "ic_engine.cross_sectional_no_data",
            tf=tf,
            regime=regime_label,
        )
        return {"n_committed": 0, "n_skipped": 0, "all_results": []}

    n_raw = len(cs_rows)
    n_scales = len(_SCALES)

    # Build feature matrix [n_raw, n_features] and returns/complete [n_raw, n_scales]
    X_raw = np.array([[r[i + 1] for i in range(n_features)] for r in cs_rows], dtype=float)
    returns_mat = np.full((n_raw, n_scales), np.nan)
    complete_mat = np.zeros((n_raw, n_scales), dtype=bool)
    for i, row in enumerate(cs_rows):
        for j in range(n_scales):
            returns_mat[i, j] = (
                row[1 + n_features + j] if row[1 + n_features + j] is not None else np.nan
            )
            complete_mat[i, j] = bool(row[1 + n_features + n_scales + j])

    # Degenerate feature detection
    feature_stds = np.std(X_raw, axis=0)
    degenerate_mask = feature_stds < 1e-8
    non_degenerate_mask = ~degenerate_mask
    X_nd = X_raw[:, non_degenerate_mask]

    n_skipped = int(degenerate_mask.sum())
    if X_nd.shape[1] == 0:
        return {"n_committed": 0, "n_skipped": n_skipped, "all_results": []}

    embargo_bars = max(lookaheads.values())
    cluster_ids_nd = _cluster_features(X_nd, cluster_max_corr)
    cluster_id_full: list[int | None] = [None] * n_features
    nd_positions = np.where(non_degenerate_mask)[0]
    for _i, _pos in enumerate(nd_positions):
        cluster_id_full[_pos] = int(cluster_ids_nd[_i])

    all_results: list[dict] = []
    pvals_flat: list[float] = []
    pval_result_idxs: list[int] = []
    n_committed = 0

    for scale_idx, scale in enumerate(_SCALES):
        lookahead_bars = lookaheads[scale]
        scale_stride = max(subsample_min_stride, lookahead_bars)
        sub_idx = np.arange(0, n_raw, scale_stride)
        X_sub = X_raw[sub_idx]
        X_sub_nd = X_nd[sub_idx]
        returns_sub = returns_mat[sub_idx]
        complete_sub = complete_mat[sub_idx]
        n_independent = len(sub_idx)

        if n_independent < min_reliable_n:
            n_skipped += len(_FEATURE_NAMES)
            continue

        scale_complete = complete_sub[:, scale_idx]
        returns_scale = returns_sub[:, scale_idx]
        valid_mask = scale_complete & np.isfinite(returns_scale)
        n_valid = valid_mask.sum()

        if n_valid < min_reliable_n:
            n_skipped += len(_FEATURE_NAMES)
            continue

        ranks_X_scale = rankdata(X_sub_nd, axis=0)[valid_mask]
        Y_scale = returns_scale[valid_mask]
        ranks_Y = rankdata(Y_scale)

        ic_vector_nd = _vectorized_ic(ranks_X_scale, ranks_Y)
        p_vector_nd = _p_values_from_ic(ic_vector_nd, n_valid)

        ic_full = _expand(ic_vector_nd, non_degenerate_mask, n_features)
        p_full = _expand(p_vector_nd, non_degenerate_mask, n_features)

        ci_lower_nd, ci_upper_nd = _fisher_z_ci(ic_vector_nd, n_valid)
        ci_lower_full = _expand(ci_lower_nd, non_degenerate_mask, n_features)
        ci_upper_full = _expand(ci_upper_nd, non_degenerate_mask, n_features)
        passes_ci_full = np.where(non_degenerate_mask, ci_lower_full > 0.0, False)

        fold_ics_list: list[np.ndarray] = []
        for k in range(walk_forward_folds):
            train_end = int(n_valid * (k + 1) / (walk_forward_folds + 1))
            test_start = train_end + embargo_bars
            test_end = int(n_valid * (k + 2) / (walk_forward_folds + 1))
            if test_start >= test_end or (test_end - test_start) < min_reliable_n:
                continue
            X_test = ranks_X_scale[test_start:test_end]
            Y_test = ranks_Y[test_start:test_end]
            if len(X_test) < 2:
                continue
            fold_ics_list.append(_vectorized_ic(rankdata(X_test, axis=0), rankdata(Y_test)))

        wf_fold_count = len(fold_ics_list)
        if wf_fold_count > 0:
            fold_ic_arr = np.array(fold_ics_list)
            wf_pass_count_nd = (fold_ic_arr > 0).sum(axis=0)
            passes_wf_nd = wf_pass_count_nd == walk_forward_folds
        else:
            wf_pass_count_nd = np.zeros(len(ic_vector_nd), dtype=int)
            passes_wf_nd = np.zeros(len(ic_vector_nd), dtype=bool)

        wf_pass_full = np.zeros(n_features, dtype=int)
        passes_wf_full = np.zeros(n_features, dtype=bool)
        wf_pass_full[non_degenerate_mask] = wf_pass_count_nd
        passes_wf_full[non_degenerate_mask] = passes_wf_nd

        ic_sharpe_arr, ic_sharpe_hac_arr, ic_sortino_arr, ic_win_rate_arr, n_sharpe_windows = (
            _compute_ic_rolling_metrics(
                X_sub,
                returns_sub,
                scale_idx,
                complete_sub[:, scale_idx],
                apr,
                non_degenerate_mask,
                n_features,
                scale_stride,
            )
        )

        for feat_idx, feat_name in enumerate(_FEATURE_NAMES):
            cell_key = (feat_name, _CROSS_SECTIONAL_SYMBOL, tf, regime_label, lookahead_bars, True)
            if cell_key in existing_keys:
                n_skipped += 1
                continue

            ic_val = ic_full[feat_idx]
            p_val = p_full[feat_idx]
            all_results.append(
                {
                    "feature_name": feat_name,
                    "vector_domain": _VECTOR_DOMAIN,
                    "symbol": _CROSS_SECTIONAL_SYMBOL,
                    "tf": tf,
                    "regime": regime_label,
                    "lookahead_bars": lookahead_bars,
                    "training_window_end": training_window_end,
                    "is_pooled": True,
                    "n_independent": int(n_valid),
                    "reliable": bool(n_valid >= min_reliable_n),
                    "ic_value": _nan_to_none(ic_val),
                    "ic_sign": (None if np.isnan(ic_val) else (1 if ic_val > 0 else -1)),
                    "p_value": _nan_to_none(p_val),
                    "ic_ci_lower": _nan_to_none(ci_lower_full[feat_idx]),
                    "ic_ci_upper": _nan_to_none(ci_upper_full[feat_idx]),
                    "passes_ci_gate": bool(passes_ci_full[feat_idx]),
                    "bh_adjusted_p": None,
                    "passes_fdr": None,
                    "wf_fold_count": wf_fold_count,
                    "wf_pass_count": int(wf_pass_full[feat_idx]),
                    "passes_walkforward": bool(passes_wf_full[feat_idx]),
                    "ic_sharpe": _nan_to_none(ic_sharpe_arr[feat_idx]),
                    "ic_sharpe_hac": _nan_to_none(ic_sharpe_hac_arr[feat_idx]),
                    "ic_sharpe_n_windows": int(n_sharpe_windows),
                    "ic_sortino": _nan_to_none(ic_sortino_arr[feat_idx]),
                    "ic_win_rate": _nan_to_none(ic_win_rate_arr[feat_idx]),
                    "regime_label_source": "market_regimes",
                    "computed_at": run_ts,
                    "cluster_id": cluster_id_full[feat_idx],
                    "feature_status_at_eval": (
                        feature_status_map.get(feat_name, "unknown")
                        if feature_status_map is not None
                        else "unknown"
                    ),
                }
            )

    # BH-FDR pass (same logic as _compute_symbol_tf)
    cluster_groups: dict[tuple, list[tuple[float, int]]] = {}
    for result_idx, r in enumerate(all_results):
        cid = r["cluster_id"]
        if cid is None:
            r["bh_adjusted_p"] = None
            r["passes_fdr"] = False
            continue
        group_key = (r["regime"], r["lookahead_bars"], cid)
        ic_val = r["ic_value"]
        abs_ic = abs(ic_val) if ic_val is not None else 0.0
        cluster_groups.setdefault(group_key, []).append((abs_ic, result_idx))

    for group_key, candidates in cluster_groups.items():
        rep_result_idx = max(candidates, key=lambda x: x[0])[1]
        pvals_flat.append(float(all_results[rep_result_idx]["p_value"]))
        pval_result_idxs.append(rep_result_idx)
        for _, non_rep_idx in candidates[1:]:
            all_results[non_rep_idx]["bh_adjusted_p"] = None
            all_results[non_rep_idx]["passes_fdr"] = False

    if pvals_flat:
        reject, p_corrected, _, _ = multipletests(pvals_flat, alpha=fdr_alpha, method="fdr_bh")
        for flat_idx, result_idx in enumerate(pval_result_idxs):
            all_results[result_idx]["bh_adjusted_p"] = float(p_corrected[flat_idx])
            all_results[result_idx]["passes_fdr"] = bool(reject[flat_idx])

    if all_results:
        with conn.cursor() as cur:
            psycopg2.extras.execute_batch(cur, _CROSS_SECTIONAL_INSERT_SQL, all_results)
        conn.commit()

    n_committed = len(all_results)
    return {"n_committed": n_committed, "n_skipped": n_skipped, "all_results": all_results}


# ---------------------------------------------------------------------------
# IC health gauge emission
# ---------------------------------------------------------------------------

# Optional per-cell gauges: (result_dict_key, gauge). Extend here to add ic_skew etc.
_OPTIONAL_IC_GAUGES = [
    ("ic_sharpe", IC_SHARPE_GAUGE),
    ("ic_sortino", IC_SORTINO_GAUGE),
    ("ic_win_rate", IC_WIN_RATE_GAUGE),
]


def _emit_health_gauges(symbol: str, tf: str, results: list[dict]) -> None:
    """Emit IC health OTel gauges after computing a (symbol, tf) cell."""
    for r in results:
        if r.get("ic_value") is None:
            continue
        base_attrs = {
            "feature_name": r["feature_name"],
            "tf": r["tf"],
            "regime": r["regime"],
            "lookahead": str(r["lookahead_bars"]),
        }
        IC_SCORE_GAUGE.set(r["ic_value"], base_attrs)
        for _key, _gauge in _OPTIONAL_IC_GAUGES:
            if r[_key] is not None:
                _gauge.set(r[_key], base_attrs)

    # Effective N and features surviving FDR per (tf, regime)
    by_regime: dict[str, list[dict]] = {}
    for r in results:
        key = r["regime"]
        by_regime.setdefault(key, []).append(r)

    for regime_label, regime_results in by_regime.items():
        attrs = {"tf": tf, "regime": regime_label}
        n_eff = max((r["n_independent"] for r in regime_results), default=0)
        EFFECTIVE_N_GAUGE.set(n_eff, attrs)
        n_surviving = sum(1 for r in regime_results if r.get("passes_fdr"))
        FEATURES_SURVIVING_FDR_GAUGE.set(n_surviving, attrs)


# ---------------------------------------------------------------------------
# ProcessPoolExecutor worker support
# ---------------------------------------------------------------------------


def _run_ic_worker(args: tuple) -> dict:
    """Worker function for ProcessPoolExecutor -- runs in subprocess.

    Each worker processes one symbol x all TFs with its own DB connection.
    No OTel tracer -- workers log only.

    Args:
        args: (symbol, tfs, dsn, training_window_end, existing_keys_frozen,
               apr_cache, run_ts, feature_status_map, mr_dict_by_tf)

    Returns:
        dict with keys: symbol, all_results (list), n_committed (int),
        n_skipped (int), error (str|None)
    """
    (
        symbol,
        tfs,
        dsn,
        training_window_end,
        existing_keys_frozen,
        apr_cache,
        run_ts,
        feature_status_map,
        mr_dict_by_tf,
    ) = args

    from src.core.service_utils import setup_service_logging

    setup_service_logging("logs/ic_engine.log")
    worker_log = structlog.get_logger(__name__)

    noop_tracer = _NoopTracer()

    # frozenset supports O(1) `in` lookups identically to set; no conversion needed.
    existing_keys = existing_keys_frozen

    conn = None
    all_results = []
    total_committed = 0
    total_skipped = 0
    error_msg = None

    try:
        # Use the DSN passed from the main process rather than re-instantiating Settings(),
        # which re-reads env vars and would diverge if the subprocess environment differs.
        conn = _connect_db_from_url(dsn)
        for tf in tfs:
            apr = apr_cache[tf]
            try:
                stats = _compute_symbol_tf(
                    conn=conn,
                    symbol=symbol,
                    tf=tf,
                    training_window_end=training_window_end,
                    existing_keys=existing_keys,
                    apr=apr,
                    tracer=noop_tracer,
                    run_ts=run_ts,
                    feature_status_map=feature_status_map,
                    mr_dict=mr_dict_by_tf.get(tf) if mr_dict_by_tf else None,
                )
                total_committed += stats.get("n_committed", 0)
                total_skipped += stats.get("n_skipped", 0)
                all_results.extend(stats.get("all_results", []))
            except Exception as error:
                worker_log.error(
                    "ic_engine.worker_cell_failed",
                    symbol=symbol,
                    tf=tf,
                    error=str(error),
                )
                # Rollback the aborted transaction so subsequent TFs can proceed.
                # psycopg2 leaves connections in aborted state after any exception;
                # without rollback all remaining TFs silently fail with InFailedSqlTransaction.
                try:
                    conn.rollback()
                except Exception:
                    pass
    except Exception as error:
        error_msg = str(error)
        worker_log.error("ic_engine.worker_failed", symbol=symbol, error=error_msg)
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass

    return {
        "symbol": symbol,
        "all_results": all_results,
        "n_committed": total_committed,
        "n_skipped": total_skipped,
        "error": error_msg,
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="IC Engine -- Spearman IC measurement for v3.0 AlphaEngine"
    )
    parser.add_argument(
        "--symbols",
        nargs="*",
        default=None,
        help="Symbols to process (default: all distinct symbols in feature_vectors)",
    )
    parser.add_argument(
        "--tf",
        nargs="*",
        default=_DEFAULT_TFS,
        help="Timeframes to process (default: 5m 15m 1h 1d)",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=None,
        help="Number of parallel workers (default: APR infra.ic_engine.workers, fallback 1)",
    )
    parser.add_argument(
        "--training-window-end",
        default=None,
        help="Explicit training window end (ISO 8601, timezone-aware/UTC). "
        "Default: MAX(bar_ts) FROM feature_vectors with a warning. "
        "Set explicitly to keep PKs stable across multi-run corpus builds.",
    )
    args = parser.parse_args()

    try:
        init_otel_providers(service_name=_JOB)
    except OTelInitError as error:
        _logger.warning("ic_engine.otel_init_failed", error=str(error))

    tracer = trace.get_tracer("indicagent")
    t0 = time.monotonic()
    status = "success"
    exit_code = 0

    settings = Settings()
    conn = None
    conn = _connect_db(settings)

    try:
        with _observed_span("ic_engine.run", tracer):
            # ----------------------------------------------------------
            # Load equity_model_enabled flag from APR (needed before prerequisites)
            # ----------------------------------------------------------
            _pre_cfg = _load_config_service(conn)
            equity_model_enabled: bool = (
                str(_pre_cfg.get_sync("alpha.regime.equity_model_enabled", "true")).lower()
                == "true"
            )
            _logger.info("ic_engine.equity_model_enabled", value=equity_model_enabled)

            # ----------------------------------------------------------
            # Startup crash-loud gates (market_regimes gate included when enabled)
            # ----------------------------------------------------------
            _assert_prerequisites(conn, tfs=args.tf, equity_model_enabled=equity_model_enabled)

            # ----------------------------------------------------------
            # Feature registry alignment gate
            # Crash-loud: registry must match FeatureVector dataclass fields exactly.
            # Use get_all_features() — NOT get_active_features() — so the gate
            # passes even when features have been deprecated. The alignment gate
            # checks schema completeness, not lifecycle state.
            # ----------------------------------------------------------
            registry_svc = FeatureRegistryService()
            registry_svc.load_sync(conn)
            all_registry_names = {r["feature_name"] for r in registry_svc.get_all_features()}
            dataclass_names = {f.name for f in dataclasses.fields(FeatureVector)}
            if all_registry_names != dataclass_names:
                raise RuntimeError(
                    f"feature_registry drift: {all_registry_names ^ dataclass_names}. "
                    "Run migration to sync registry with FeatureVector."
                )
            # Build status map for workers: plain dict is picklable; FeatureRegistryService is not.
            feature_status_map: dict[str, str] = {
                r["feature_name"]: (r["status"] or "unknown")
                for r in registry_svc.get_all_features()
            }

            # ----------------------------------------------------------
            # Run constants (locked at start)
            # ----------------------------------------------------------
            run_ts = datetime.now(UTC)

            if args.training_window_end:
                training_window_end = datetime.fromisoformat(args.training_window_end)
                if training_window_end.tzinfo is None:
                    raise ValueError(
                        "--training-window-end must be timezone-aware ISO 8601 (UTC). "
                        "Naive datetimes are rejected to preserve the UTC-only invariant."
                    )
                training_window_end = training_window_end.astimezone(UTC)
                _logger.info(
                    "ic_engine.training_window_end_explicit", value=str(training_window_end)
                )
            else:
                with conn.cursor() as cur:
                    cur.execute("SELECT MAX(bar_ts) FROM feature_vectors")
                    training_window_end = cur.fetchone()[0]
                _logger.warning(
                    "ic_engine.training_window_end_from_max",
                    value=str(training_window_end),
                    note="Pass --training-window-end to stabilize PKs across runs",
                )

            _logger.info(
                "ic_engine.run_constants",
                training_window_end=str(training_window_end),
                run_ts=str(run_ts),
            )

            # ----------------------------------------------------------
            # Discover symbols
            # ----------------------------------------------------------
            if args.symbols:
                symbols = args.symbols
            else:
                with conn.cursor() as cur:
                    cur.execute("SELECT DISTINCT symbol FROM feature_vectors ORDER BY symbol")
                    symbols = [r[0] for r in cur.fetchall()]

            tfs = args.tf
            _logger.info(
                "ic_engine.starting",
                n_symbols=len(symbols),
                tfs=tfs,
                training_window_end=str(training_window_end),
            )

            # ----------------------------------------------------------
            # Idempotency: load existing (feature, symbol, tf, regime, lookahead, is_pooled)
            # for this training_window_end
            # ----------------------------------------------------------
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT feature_name, symbol, tf, regime, lookahead_bars, is_pooled
                    FROM feature_ic_scores
                    WHERE training_window_end = %s
                    """,
                    (training_window_end,),
                )
                existing_keys: set[tuple] = {
                    (r[0], r[1], r[2], r[3], r[4], r[5]) for r in cur.fetchall()
                }
            _logger.info("ic_engine.existing_keys", count=len(existing_keys))

            # APR is TF-specific (lookahead.* varies by TF); load once per TF
            # rather than once per (symbol, tf) to avoid 58x redundant DB round-trips.
            apr_cache = {tf: _load_apr(conn, tf) for tf in tfs}

            # Load n_workers from APR (infra namespace) before closing conn
            _full_cfg = _load_config_service(conn)
            n_workers = args.workers
            if n_workers is None:
                n_workers = int(_full_cfg.get_sync("infra.ic_engine.workers", 1))

            # ----------------------------------------------------------
            # Load market_regimes {ts -> regime_label} per TF (for equity model)
            # Pre-materialized here so workers receive a plain dict (picklable).
            # ----------------------------------------------------------
            mr_dict_by_tf: dict[str, dict] = {}
            if equity_model_enabled:
                for tf in tfs:
                    with conn.cursor() as cur:
                        cur.execute(
                            "SELECT ts, regime_label FROM market_regimes WHERE asset_class='equity' AND tf=%s",
                            (tf,),
                        )
                        mr_dict_by_tf[tf] = {r[0]: r[1] for r in cur.fetchall()}
                    _logger.info(
                        "ic_engine.mr_loaded",
                        tf=tf,
                        n_rows=len(mr_dict_by_tf[tf]),
                    )

            # ----------------------------------------------------------
            # Build worker args then close main conn -- workers open their own
            # ----------------------------------------------------------
            existing_keys_frozen = frozenset(existing_keys)
            worker_args = [
                (
                    symbol,
                    tfs,
                    settings.database_url,
                    training_window_end,
                    existing_keys_frozen,
                    apr_cache,
                    run_ts,
                    feature_status_map,
                    mr_dict_by_tf if equity_model_enabled else None,
                )
                for symbol in symbols
            ]

            _logger.info(
                "ic_engine.starting_parallel",
                n_symbols=len(symbols),
                n_workers=n_workers,
            )
            conn.close()
            conn = None  # prevent double-close in finally

            # ----------------------------------------------------------
            # Main compute loop (ProcessPoolExecutor)
            # ----------------------------------------------------------
            total_committed = 0
            total_skipped = 0

            with ProcessPoolExecutor(max_workers=n_workers) as pool:
                for result in pool.map(_run_ic_worker, worker_args, chunksize=1):
                    symbol = result["symbol"]
                    if result["error"]:
                        _logger.error(
                            "ic_engine.symbol_failed",
                            symbol=symbol,
                            error=result["error"],
                        )
                        status = "failure"
                        exit_code = 1
                    total_committed += result["n_committed"]
                    total_skipped += result["n_skipped"]
                    if result["all_results"]:
                        for tf in tfs:
                            tf_results = [r for r in result["all_results"] if r.get("tf") == tf]
                            if tf_results:
                                _emit_health_gauges(symbol, tf, tf_results)
                    _logger.info(
                        "ic_engine.symbol_done",
                        symbol=symbol,
                        n_committed=result["n_committed"],
                        n_skipped=result["n_skipped"],
                    )

            # ----------------------------------------------------------
            # Cross-sectional IC pass (equity_model_enabled=True only)
            # Runs in main process after per-symbol workers complete.
            # Each cell: all 58 equity ETFs pooled per (tf, regime_label).
            # Max 4 TFs * 9 regime labels = 36 compute cells (in practice fewer).
            # ----------------------------------------------------------
            if equity_model_enabled:
                _logger.info("ic_engine.starting_cross_sectional_pass")
                cs_conn = _connect_db(settings)
                try:
                    with cs_conn.cursor() as cur:
                        cur.execute(
                            "SELECT DISTINCT regime_label FROM market_regimes "
                            "WHERE asset_class='equity' AND tf=%s ORDER BY regime_label",
                            (tfs[0],),
                        )
                        cs_regimes = [r[0] for r in cur.fetchall()]

                    for tf in tfs:
                        apr = apr_cache[tf]
                        for regime_label in cs_regimes:
                            cs_result = _compute_cross_sectional_tf(
                                conn=cs_conn,
                                tf=tf,
                                regime_label=regime_label,
                                training_window_end=training_window_end,
                                existing_keys=existing_keys_frozen,
                                apr=apr,
                                tracer=tracer,
                                run_ts=run_ts,
                                feature_status_map=feature_status_map,
                            )
                            total_committed += cs_result.get("n_committed", 0)
                            total_skipped += cs_result.get("n_skipped", 0)
                            _logger.info(
                                "ic_engine.cross_sectional_done",
                                tf=tf,
                                regime=regime_label,
                                n_committed=cs_result.get("n_committed", 0),
                            )
                finally:
                    cs_conn.close()

            elapsed = time.monotonic() - t0
            IC_ENGINE_RUN_LATENCY_SECONDS.record(elapsed)

            _logger.info(
                "ic_engine.run_complete",
                total_committed=total_committed,
                total_skipped=total_skipped,
                elapsed_s=round(elapsed, 2),
                status=status,
            )

    except Exception as error:
        _logger.error("ic_engine.run_failed", error=str(error))
        status = "failure"
        exit_code = 1
    finally:
        if conn is not None:
            conn.close()
        JOB_COMPLETED_TOTAL.add(1, {"job": _JOB, "status": status})
        flush_and_shutdown_metrics()

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
