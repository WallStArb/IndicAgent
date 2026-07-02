#!/usr/bin/env python3
"""EnsembleICEngine -- measures IC(alpha_score, forward_return_*) per (symbol, tf, regime,
lookahead) for the v3.0 ensemble output (Phase 142A, EIC-01).

Proves the ensemble OUTPUT has IC before any execution rules are tested. Composes the
SAME corrected IC methodology as ic_engine.py (Fisher z-transform CI, NOT circular block
bootstrap; corpus-level BH-FDR; expanding-window walk-forward with scale-specific embargo)
onto a single composite predictor (alpha_score), reading alpha_events joined to
forward_returns and market_regimes.

CORRECTNESS INVARIANTS:
- Executable returns only (Invariant 1): every forward_returns query filters
  WHERE return_type = 'executable_open_to_open'.
- ProcessPoolExecutor workers are compute-only: all data fetching happens in the main
  process via asyncpg BEFORE worker dispatch; workers receive numpy arrays (not a DSN,
  not a connection) and return list[dict] rows for a single serial write after corpus-level
  BH-FDR. No worker ever opens a DB connection or calls commit() (CLAUDE.md invariant).
- alpha_score is ONE predictor -- collinearity clustering is skipped (feature-level
  concern only); every cell IS representative for the single corpus-level BH-FDR call.
- scored_at is pinned to a single run_ts (UTC "now" at start) computed ONCE per
  _execute_inner and reused for every row (D-142A-R2): a failed-and-retried run upserts
  in place via ON CONFLICT (event_row_id, scored_at) DO UPDATE; separate invocations
  accumulate distinct vintages (mirrors ic_engine.computed_at).
- walk_forward_stable (EIC-03) is the fold IC-MAGNITUDE max/min ratio, NOT a fold
  IC-Sharpe ratio (D-142A-R1: reasoned v1 relaxation -- see compute_walk_forward_stable).
- Crashes loud at startup when alpha_events, forward_returns, OR market_regimes is empty.
- In-sample filter: all queries restrict bar_ts < alpha.validation.oos_start (OOS half
  reserved for Phase 144).

DAG invariant note: this oneshot is exempt from the "only writer subclasses touch DB"
rule exactly as ic_engine.py / ensemble_trainer.py are -- it is a batch measurement tool,
not a real-time daemon.

Usage:
    python services/ensemble_ic_engine.py
"""

from __future__ import annotations

import asyncio
import dataclasses
import sys
from concurrent.futures import ProcessPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import asyncpg
import numpy as np
import structlog
from scipy.stats import rankdata
from statsmodels.stats.multitest import multipletests

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# Composition, not subclassing/forking -- import the private pure IC math functions.
# See CLAUDE.md + 142A-CONTEXT.md: methodology parity is structural, not re-derived.
from services.ic_engine import (
    ICEngineConfig,  # noqa: F401 -- documents the shared-key contract this config mirrors
    _compute_ic_rolling_metrics,
    _fisher_z_ci,
    _nan_to_none,
    _p_values_from_ic,
    _vectorized_ic,
)
from src.config.config_service import ConfigService  # EIC-02: alpha.frame.hold_max_bars writes
from src.config.settings import Settings
from src.core.agent.base_batch import BaseBatch
from src.observability.corpus_manifest import CorpusManifest
from src.observability.otel import OTelInitError, init_otel_providers

_logger = structlog.get_logger(__name__)

_JOB = "ensemble-ic-engine"

# Gradient scale names for forward return horizons (matches forward_returns columns).
_SCALES: tuple[str, ...] = ("fast", "mid", "slow", "extended")

# Cross-sectional pooled-row sentinel (research OQ-2: 'POOLED', not '_pooled' -- alpha_events
# and alpha_ensemble_ic both use the literal string 'POOLED' for symbol, per migration 195's
# CHECK constraint (symbol = 'POOLED') = is_pooled).
_POOLED_SYMBOL = "POOLED"


# ---------------------------------------------------------------------------
# APR compile-time binding
# ---------------------------------------------------------------------------

_APR_QUERY = (
    "SELECT config_key, config_value FROM config_state "
    "WHERE config_key LIKE 'alpha.%' OR config_key LIKE 'infra.ensemble_ic_engine.%'"
)


async def _load_apr(conn: asyncpg.Connection) -> dict[str, Any]:
    """Load all alpha.* and infra.ensemble_ic_engine.* APR keys via asyncpg."""
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


@dataclasses.dataclass(frozen=True)
class EnsembleICConfig:
    """Frozen config snapshot bound once at startup from APR.

    Reuses the shared ICEngineConfig-style keys (fdr_alpha, walk_forward_folds,
    sharpe_window_size, sharpe_min_windows, subsample_min_stride, min_reliable_n,
    hac_max_lag, lookahead_fast/mid/slow/extended, n_workers) plus the
    EnsembleIC-specific keys seeded by migration 195. Frozen + picklable so workers
    receive it directly via ProcessPoolExecutor without re-loading from DB.
    """

    # Shared IC-engine-style keys
    fdr_alpha: float
    walk_forward_folds: int
    sharpe_window_size: int
    sharpe_min_windows: int
    subsample_min_stride: int
    min_reliable_n: int
    hac_max_lag: int
    lookahead_fast: int
    lookahead_mid: int
    lookahead_slow: int
    lookahead_extended: int
    n_workers: int
    # EnsembleIC-specific keys (migration 195)
    decay_threshold: float
    min_qualifying_fraction: float
    wf_stability_ratio: float
    gate_lookahead: str
    wf_stability_metric: str
    min_obs_per_regime: int

    @property
    def lookaheads(self) -> dict[str, int]:
        """Gradient-scale lookahead mapping -- built once; frozen after construction."""
        return {
            "fast": self.lookahead_fast,
            "mid": self.lookahead_mid,
            "slow": self.lookahead_slow,
            "extended": self.lookahead_extended,
        }

    @classmethod
    def from_apr(cls, cfg: dict[str, Any]) -> EnsembleICConfig:
        """Load all EnsembleIC APR parameters from the raw config dict in one pass."""
        return cls(
            fdr_alpha=_cfg_float(cfg, "alpha.ic.fdr_alpha", 0.05),
            walk_forward_folds=_cfg_int(cfg, "alpha.ic.walk_forward_folds", 3),
            sharpe_window_size=_cfg_int(cfg, "alpha.ic.sharpe_window_size", 2000),
            sharpe_min_windows=_cfg_int(cfg, "alpha.ic.sharpe_min_windows", 30),
            subsample_min_stride=_cfg_int(cfg, "alpha.ic.subsample_min_stride", 5),
            min_reliable_n=_cfg_int(cfg, "alpha.ic.min_reliable_n", 100),
            hac_max_lag=_cfg_int(cfg, "alpha.ic.hac_max_lag", 3),
            lookahead_fast=_cfg_int(cfg, "alpha.ic.lookahead.fast", 1),
            lookahead_mid=_cfg_int(cfg, "alpha.ic.lookahead.mid", 5),
            lookahead_slow=_cfg_int(cfg, "alpha.ic.lookahead.slow", 20),
            lookahead_extended=_cfg_int(cfg, "alpha.ic.lookahead.extended", 60),
            n_workers=_cfg_int(cfg, "infra.ensemble_ic_engine.workers", 12),
            decay_threshold=_cfg_float(cfg, "alpha.ensemble_ic.decay_threshold", 0.1),
            min_qualifying_fraction=_cfg_float(
                cfg, "alpha.ensemble_ic.min_qualifying_fraction", 0.60
            ),
            wf_stability_ratio=_cfg_float(cfg, "alpha.ensemble_ic.wf_stability_ratio", 3.0),
            gate_lookahead=_cfg_str(cfg, "alpha.ensemble_ic.gate_lookahead", "fast"),
            wf_stability_metric=_cfg_str(cfg, "alpha.ensemble_ic.wf_stability_metric", "ic_ratio"),
            min_obs_per_regime=_cfg_int(cfg, "alpha.ensemble_ic.min_obs_per_regime", 3000),
        )


# ---------------------------------------------------------------------------
# EIC-03: walk_forward_stable (D-142A-R1 -- fold IC-magnitude ratio, LOCKED)
# ---------------------------------------------------------------------------


def compute_walk_forward_stable(
    fold_ics: list[float] | np.ndarray,
    wf_stability_ratio: float,
    wf_stability_metric: str = "ic_ratio",
) -> bool:
    """EIC-03 (D-142A-R1): walk_forward_stable is the max/min ratio of per-fold IC
    MAGNITUDE, NOT per-fold IC Sharpe.

    ROADMAP EIC-03 says 'IC Sharpe ratio', but a reliable per-fold Sharpe needs
    sharpe_min_windows(30) * sharpe_window_size(2000) = 60,000 bars inside ONE fold's
    test slice -- orders of magnitude above per-cell per-fold N (each fold test slice
    is gated at min_reliable_n=100). ic_engine.py's own walk-forward gate (lines
    969-973) likewise uses fold IC scalars, not fold Sharpe. Metric is swappable via
    alpha.ensemble_ic.wf_stability_metric; add an 'ic_sharpe_ratio' branch here if a
    future cell N ever supports it. See CONTEXT.md D-142A-R1.
    """
    if wf_stability_metric == "ic_ratio":
        if len(fold_ics) < 2:
            return False
        abs_fold_ics = np.abs(np.asarray(fold_ics, dtype=float))
        min_abs = float(abs_fold_ics.min())
        if min_abs == 0.0:
            return False  # undefined ratio -- treat as unstable
        max_abs = float(abs_fold_ics.max())
        return (max_abs / min_abs) < wf_stability_ratio
    elif wf_stability_metric == "ic_sharpe_ratio":
        raise NotImplementedError(
            "wf_stability_metric='ic_sharpe_ratio' is not yet implemented. "
            "See D-142A-R1 (142A-CONTEXT.md): a per-fold IC Sharpe requires "
            "sharpe_min_windows * sharpe_window_size bars inside a single fold's test "
            "slice, far above typical per-cell per-fold N. Swap in an implementation "
            "here only once cell N reliably supports it."
        )
    else:
        raise ValueError(f"Unknown wf_stability_metric: {wf_stability_metric!r}")


# ---------------------------------------------------------------------------
# EIC-02: IC decay curve -> hold_max_bars calibration (review finding #6)
# ---------------------------------------------------------------------------


def _select_hold_bars_from_decay(
    cells: list[dict[str, Any]],
    decay_threshold: float,
    scale_to_bars: dict[str, int],
) -> int | None:
    """Pure function: select hold_bars from one (symbol, tf, regime) group's IC decay curve.

    Significance + sufficiency gate (review finding #6, MANDATORY): a cell must have
    BOTH passes_fdr=true AND reliable=true to participate in the decay walk. A cell that
    failed BH-FDR is statistically indistinguishable from noise; a cell that is not
    reliable passed FDR on insufficient N (n_valid < min_reliable_n) and its ic_sharpe is
    unstable. Either condition alone is insufficient to gate on -- both must hold.

    After filtering, walks the qualifying cells in canonical scale order
    [fast, mid, slow, extended]. At the first scale where ic_sharpe is not None and
    ic_sharpe < decay_threshold, returns the lookahead_bars of the PRECEDING qualifying
    scale (the last scale where the edge was still alive) -- or 1 if the very first
    qualifying scale is already below threshold. If no scale crosses the threshold,
    returns scale_to_bars['extended'] (edge persists to the longest horizon measured).
    A cell with ic_sharpe=None is treated as "no data" and skipped in the walk, not as
    a below-threshold crossing.

    Returns None if there are zero qualifying cells for this group -- the caller must
    interpret this as "no qualifying signal; skip calibration, leave the prior APR
    value in place" rather than defaulting to any hold_bars value.
    """
    qualifying = [c for c in cells if c.get("passes_fdr") is True and c.get("reliable") is True]
    if not qualifying:
        return None

    by_scale = {c["lookahead"]: c for c in qualifying}
    ordered_scales = [s for s in _SCALES if s in by_scale]
    if not ordered_scales:
        return None

    preceding_bars: int | None = None
    for scale in ordered_scales:
        ic_sharpe = by_scale[scale]["ic_sharpe"]
        if ic_sharpe is None:
            continue  # no data at this scale -- skip, do not treat as a decay crossing
        if ic_sharpe < decay_threshold:
            return preceding_bars if preceding_bars is not None else 1
        preceding_bars = scale_to_bars[scale]

    # No scale crossed the threshold -- edge persists to the longest horizon measured.
    return scale_to_bars["extended"]


# ---------------------------------------------------------------------------
# scored_at pinning + row construction (D-142A-R2, review finding #3)
# ---------------------------------------------------------------------------


def build_ensemble_ic_row(
    symbol: str,
    tf: str,
    regime: str,
    lookahead: str,
    lookahead_bars: int,
    run_ts: datetime,
    ic_value: float | None = None,
    ic_ci_lower: float | None = None,
    ic_ci_upper: float | None = None,
    ic_sharpe: float | None = None,
    ic_sharpe_hac: float | None = None,
    bh_adjusted_p: float | None = None,
    passes_fdr: bool | None = None,
    walk_forward_stable: bool | None = None,
    n_independent: int | None = None,
    reliable: bool | None = None,
) -> dict[str, Any]:
    """Build one alpha_ensemble_ic row dict.

    event_row_id = BaseBatch.content_key(symbol, tf, regime, lookahead) -- deliberately
    excludes run_ts so re-runs on the same cell within one invocation collide on
    (event_row_id, scored_at) and hit ON CONFLICT DO UPDATE (D-142A-R2). scored_at is
    stamped with the single pinned run_ts passed in (never a fresh "now" per-row).
    """
    is_pooled = symbol == _POOLED_SYMBOL
    return {
        "event_row_id": BaseBatch.content_key(symbol, tf, regime, lookahead),
        "symbol": symbol,
        "tf": tf,
        "regime": regime,
        "lookahead": lookahead,
        "lookahead_bars": lookahead_bars,
        "is_pooled": is_pooled,
        "n_independent": n_independent,
        "reliable": reliable,
        "ic_value": ic_value,
        "ic_ci_lower": ic_ci_lower,
        "ic_ci_upper": ic_ci_upper,
        "ic_sharpe": ic_sharpe,
        "ic_sharpe_hac": ic_sharpe_hac,
        "bh_adjusted_p": bh_adjusted_p,
        "passes_fdr": passes_fdr,
        "walk_forward_stable": walk_forward_stable,
        "scored_at": run_ts,
    }


_ENSEMBLE_IC_INSERT_SQL = """
    INSERT INTO alpha_ensemble_ic (
        event_row_id, symbol, tf, regime, lookahead, lookahead_bars, is_pooled,
        n_independent, reliable, ic_value, ic_ci_lower, ic_ci_upper,
        ic_sharpe, ic_sharpe_hac, bh_adjusted_p, passes_fdr, walk_forward_stable, scored_at
    )
    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16, $17, $18)
    ON CONFLICT (event_row_id, scored_at) DO UPDATE SET
        ic_value = EXCLUDED.ic_value,
        ic_ci_lower = EXCLUDED.ic_ci_lower,
        ic_ci_upper = EXCLUDED.ic_ci_upper,
        ic_sharpe = EXCLUDED.ic_sharpe,
        ic_sharpe_hac = EXCLUDED.ic_sharpe_hac,
        bh_adjusted_p = EXCLUDED.bh_adjusted_p,
        passes_fdr = EXCLUDED.passes_fdr,
        walk_forward_stable = EXCLUDED.walk_forward_stable,
        n_independent = EXCLUDED.n_independent,
        reliable = EXCLUDED.reliable
"""
# (D-142A-R2, review finding #3): this DO UPDATE only fires when a re-run supplies the
# SAME scored_at -- which happens on a within-invocation retry because scored_at is
# pinned to one run_ts for the whole run. Separate invocations use a fresh run_ts and
# therefore INSERT new vintage rows, exactly like ic_engine.computed_at.

_ROW_COLUMN_ORDER: tuple[str, ...] = (
    "event_row_id",
    "symbol",
    "tf",
    "regime",
    "lookahead",
    "lookahead_bars",
    "is_pooled",
    "n_independent",
    "reliable",
    "ic_value",
    "ic_ci_lower",
    "ic_ci_upper",
    "ic_sharpe",
    "ic_sharpe_hac",
    "bh_adjusted_p",
    "passes_fdr",
    "walk_forward_stable",
    "scored_at",
)


def _row_to_tuple(row: dict[str, Any]) -> tuple[Any, ...]:
    return tuple(row[col] for col in _ROW_COLUMN_ORDER)


# ---------------------------------------------------------------------------
# Startup crash-loud gates (review finding #5: market_regimes added)
# ---------------------------------------------------------------------------


async def _assert_prerequisites(conn: asyncpg.Connection, tfs: list[str] | None = None) -> None:
    """Three COUNT checks; raise RuntimeError (crash loud) if any is empty."""
    n_alpha = await conn.fetchval("SELECT count(*) FROM alpha_events")
    if not n_alpha:
        raise RuntimeError(
            "EnsembleICEngine startup gate FAILED: alpha_events is empty. "
            "Run Phase B corpus (ensemble_trainer + alpha_publisher) first."
        )

    n_fr = await conn.fetchval(
        "SELECT count(*) FROM forward_returns WHERE return_type = 'executable_open_to_open'"
    )
    if not n_fr:
        raise RuntimeError(
            "EnsembleICEngine startup gate FAILED: forward_returns (executable_open_to_open) "
            "is empty."
        )

    # market_regimes is empty -- the 9-label regime stratification the entire measurement
    # depends on is missing; cannot proceed (review finding #5).
    if tfs:
        n_mr = await conn.fetchval(
            "SELECT count(*) FROM market_regimes WHERE tf = ANY($1::text[])", tfs
        )
    else:
        n_mr = await conn.fetchval("SELECT count(*) FROM market_regimes")
    if not n_mr:
        raise RuntimeError(
            "EnsembleICEngine startup gate FAILED: market_regimes is empty. The 9-label "
            "regime stratification the entire measurement depends on is missing; cannot "
            "proceed. Run services/equity_regime_model.py first."
        )


# ---------------------------------------------------------------------------
# Worker (pure compute -- zero database connections)
# ---------------------------------------------------------------------------


def _run_ensemble_ic_worker(args: tuple) -> dict[str, Any]:
    """ProcessPoolExecutor worker -- runs in subprocess. PURE COMPUTE, ZERO DB connections.

    All data fetching happens in the main process BEFORE dispatch (CLAUDE.md:
    ProcessPoolExecutor workers are compute-only). Args are numpy arrays plus the pinned
    run_ts -- never a DSN, never a connection.

    Args:
        args: (symbol, tf, alpha_scores, returns_by_scale, regime_labels, config, run_ts)
            alpha_scores: np.ndarray [n_obs] -- the composite alpha_score for this (symbol, tf)
            returns_by_scale: dict[str, np.ndarray] -- forward_return_<scale> aligned to alpha_scores
            regime_labels: np.ndarray [n_obs] -- cross-sectional market_regimes.regime_label
            config: EnsembleICConfig (frozen, picklable)
            run_ts: datetime -- pinned once per invocation (D-142A-R2)

    Returns:
        dict with keys: rows (list[dict]), pvals (list[float]), pval_idxs (list[int])
    """
    symbol, tf, alpha_scores, returns_by_scale, regime_labels, config, run_ts = args

    rows: list[dict[str, Any]] = []
    pvals: list[float] = []
    pval_idxs: list[int] = []

    is_pooled = symbol == _POOLED_SYMBOL
    distinct_regimes = sorted({r for r in regime_labels.tolist() if r is not None})

    for regime in distinct_regimes:
        mask = regime_labels == regime
        if mask.sum() == 0:
            continue
        alpha_regime = alpha_scores[mask]

        for scale in _SCALES:
            lookahead_bars = config.lookaheads[scale]
            returns_scale = returns_by_scale.get(scale)
            if returns_scale is None:
                continue
            returns_regime = returns_scale[mask]

            stride = max(config.subsample_min_stride, lookahead_bars)
            sub_idx = np.arange(0, len(alpha_regime), stride)
            alpha_sub = alpha_regime[sub_idx]
            returns_sub = returns_regime[sub_idx]

            valid_mask = np.isfinite(alpha_sub) & np.isfinite(returns_sub)
            n_valid = int(valid_mask.sum())
            if n_valid < config.min_reliable_n:
                continue

            alpha_valid = alpha_sub[valid_mask]
            returns_valid = returns_sub[valid_mask]

            ranks_x = rankdata(alpha_valid.reshape(-1, 1), axis=0)
            ranks_y = rankdata(returns_valid)
            ic_vector = _vectorized_ic(ranks_x, ranks_y)
            ic_value = float(ic_vector[0])
            p_value = float(_p_values_from_ic(ic_vector, n_valid)[0])
            ci_lower_nd, ci_upper_nd = _fisher_z_ci(ic_vector, n_valid)
            ic_ci_lower = _nan_to_none(float(ci_lower_nd[0]))
            ic_ci_upper = _nan_to_none(float(ci_upper_nd[0]))

            # Expanding-window walk-forward with scale-specific embargo (P3 fix pattern).
            embargo_bars = lookahead_bars
            walk_forward_folds = config.walk_forward_folds
            fold_ics: list[float] = []
            for k in range(walk_forward_folds):
                train_end = int(n_valid * (k + 1) / (walk_forward_folds + 1))
                test_start = train_end + embargo_bars
                test_end = int(n_valid * (k + 2) / (walk_forward_folds + 1))
                if test_start >= test_end or (test_end - test_start) < config.min_reliable_n:
                    continue
                x_test = alpha_valid[test_start:test_end]
                y_test = returns_valid[test_start:test_end]
                if len(x_test) < 2:
                    continue
                rx_test = rankdata(x_test.reshape(-1, 1), axis=0)
                ry_test = rankdata(y_test)
                fold_ics.append(float(_vectorized_ic(rx_test, ry_test)[0]))

            wf_stable = compute_walk_forward_stable(
                fold_ics, config.wf_stability_ratio, config.wf_stability_metric
            )

            # Cell-level IC Sharpe / HAC Sharpe over the FULL cell series (distinct from
            # the per-fold quantities above; not used for EIC-03 stability).
            complete_mask = np.ones(n_valid, dtype=bool)
            returns_2d = returns_valid.reshape(-1, 1)
            sharpe_arr, sharpe_hac_arr, _sortino, _win_rate, _n_windows = (
                _compute_ic_rolling_metrics(
                    X_sub=alpha_valid.reshape(-1, 1),
                    returns_sub=returns_2d,
                    scale_idx=0,
                    complete_mask=complete_mask,
                    config=config,
                    non_degenerate_mask=np.array([True]),
                    n_total_features=1,
                    stride=stride,
                )
            )
            ic_sharpe = _nan_to_none(float(sharpe_arr[0]))
            ic_sharpe_hac = _nan_to_none(float(sharpe_hac_arr[0]))

            row = build_ensemble_ic_row(
                symbol=symbol,
                tf=tf,
                regime=str(regime),
                lookahead=scale,
                lookahead_bars=lookahead_bars,
                run_ts=run_ts,
                ic_value=ic_value,
                ic_ci_lower=ic_ci_lower,
                ic_ci_upper=ic_ci_upper,
                ic_sharpe=ic_sharpe,
                ic_sharpe_hac=ic_sharpe_hac,
                walk_forward_stable=wf_stable,
                n_independent=n_valid,
                reliable=n_valid >= config.min_reliable_n,
            )

            pval_idxs.append(len(rows))
            pvals.append(p_value)
            rows.append(row)

    return {"rows": rows, "pvals": pvals, "pval_idxs": pval_idxs, "is_pooled": is_pooled}


# ---------------------------------------------------------------------------
# EnsembleICEngine
# ---------------------------------------------------------------------------


class EnsembleICEngine(BaseBatch):
    """Batch compute service: alpha_events + forward_returns + market_regimes -> alpha_ensemble_ic.

    Measures IC(alpha_score, forward_return_<scale>) per (symbol, tf, regime, lookahead)
    using the same Fisher-z CI + corpus-level BH-FDR + walk-forward machinery as ic_engine.
    """

    job_name = "ensemble-ic-engine"
    compute_version = "1.0.0"

    async def execute(self, pool: asyncpg.Pool) -> None:
        manifest = CorpusManifest("ensemble_ic_engine", Path(".planning/corpus_manifests"))
        try:
            await self._execute_inner(pool, manifest)
        except Exception as error:  # CLAUDE.md: exception variable name is `error`
            manifest.add_error(str(error))
            try:
                manifest.write()
            except Exception:
                pass
            raise

    async def _execute_inner(self, pool: asyncpg.Pool, manifest: CorpusManifest) -> None:
        # D-142A-R2: pin ONE run_ts for the entire invocation; reused as scored_at for
        # every row produced. Mirrors ic_engine.py:2009.
        run_ts = datetime.now(UTC)
        self.logger.info("ensemble_ic.run_ts_locked", run_ts=str(run_ts))

        async with pool.acquire() as conn:
            apr_cfg = await _load_apr(conn)
            config = EnsembleICConfig.from_apr(apr_cfg)

            tfs = await conn.fetch("SELECT DISTINCT tf FROM alpha_events")
            tf_list = [r["tf"] for r in tfs]

            await _assert_prerequisites(conn, tfs=tf_list)

            oos_start_gate_error = RuntimeError(
                "EnsembleICEngine startup gate FAILED: alpha.validation.oos_start is not set "
                "in config_state (or is not a valid timestamp). A missing/invalid OOS boundary "
                "would silently exclude all rows from measurement (bar_ts < NULL never matches) "
                "or crash on an opaque cast error -- see Phase 141.1 CR-01. Set the key via "
                "ConfigService before running this engine."
            )
            try:
                oos_start = await conn.fetchval(
                    "SELECT config_value::timestamptz FROM config_state "
                    "WHERE config_key = 'alpha.validation.oos_start'"
                )
            except (asyncpg.DataError, asyncpg.InvalidTextRepresentationError) as error:
                raise oos_start_gate_error from error
            if oos_start is None:
                raise oos_start_gate_error

            symbols_rows = await conn.fetch(
                "SELECT DISTINCT symbol, tf FROM alpha_events WHERE bar_ts < $1", oos_start
            )
            symbol_tf_pairs = [(r["symbol"], r["tf"]) for r in symbols_rows]

            worker_args = []
            for symbol, tf in symbol_tf_pairs:
                rows = await conn.fetch(
                    """
                    SELECT ae.alpha_score, fr.return_fast, fr.return_mid,
                           fr.return_slow, fr.return_extended, mr.regime_label
                    FROM alpha_events ae
                    JOIN forward_returns fr
                      ON fr.symbol = ae.symbol AND fr.tf = ae.tf AND fr.bar_ts = ae.bar_ts
                      AND fr.return_type = 'executable_open_to_open'
                    JOIN market_regimes mr
                      ON mr.asset_class = 'equity' AND mr.tf = ae.tf AND mr.ts = ae.bar_ts
                    WHERE ae.symbol = $1 AND ae.tf = $2 AND ae.bar_ts < $3
                    ORDER BY ae.bar_ts
                    """,
                    symbol,
                    tf,
                    oos_start,
                )
                if not rows:
                    continue

                alpha_scores = np.array([float(r["alpha_score"]) for r in rows])
                returns_by_scale = {
                    "fast": np.array(
                        [
                            float(r["return_fast"]) if r["return_fast"] is not None else np.nan
                            for r in rows
                        ]
                    ),
                    "mid": np.array(
                        [
                            float(r["return_mid"]) if r["return_mid"] is not None else np.nan
                            for r in rows
                        ]
                    ),
                    "slow": np.array(
                        [
                            float(r["return_slow"]) if r["return_slow"] is not None else np.nan
                            for r in rows
                        ]
                    ),
                    "extended": np.array(
                        [
                            (
                                float(r["return_extended"])
                                if r["return_extended"] is not None
                                else np.nan
                            )
                            for r in rows
                        ]
                    ),
                }
                regime_labels = np.array([r["regime_label"] for r in rows], dtype=object)

                worker_args.append(
                    (symbol, tf, alpha_scores, returns_by_scale, regime_labels, config, run_ts)
                )

            corpus_all_results: list[dict[str, Any]] = []
            corpus_pvals_flat: list[float] = []
            corpus_pval_result_idxs: list[int] = []

            with ProcessPoolExecutor(max_workers=config.n_workers) as exe:
                for result in exe.map(_run_ensemble_ic_worker, worker_args, chunksize=1):
                    offset = len(corpus_all_results)
                    corpus_all_results.extend(result["rows"])
                    corpus_pvals_flat.extend(result["pvals"])
                    corpus_pval_result_idxs.extend(offset + i for i in result["pval_idxs"])

            # Corpus-level BH-FDR: ONE multipletests call across all cells (Phase A P2
            # fix). Note (review finding, accepted as-is for v1): this mixes pooled and
            # per-symbol cell p-values into one correction -- inherited from ic_engine's
            # precedent; acceptable simplification for the first run.
            if corpus_pvals_flat:
                reject_all, p_corr_all, _, _ = multipletests(
                    corpus_pvals_flat, alpha=config.fdr_alpha, method="fdr_bh"
                )
                for flat_idx, result_idx in enumerate(corpus_pval_result_idxs):
                    corpus_all_results[result_idx]["bh_adjusted_p"] = float(p_corr_all[flat_idx])
                    corpus_all_results[result_idx]["passes_fdr"] = bool(reject_all[flat_idx])

            rows_to_write = [_row_to_tuple(row) for row in corpus_all_results]

        async with pool.acquire() as wconn:
            async with wconn.transaction():
                if rows_to_write:
                    await wconn.executemany(_ENSEMBLE_IC_INSERT_SQL, rows_to_write)

        # EIC-02: calibrate alpha.frame.hold_max_bars.<regime>.<tf> from the IC decay
        # curve AFTER the serial write completes successfully (this task only adds this
        # post-write calibration phase; the IC computation/write above is Plan 01's).
        n_keys_written = await self._calibrate_hold_max_bars(pool, corpus_all_results, config)

        manifest.write()
        self.logger.info(
            "ensemble_ic.run_complete",
            n_rows=len(rows_to_write),
            n_symbol_tf_pairs=len(symbol_tf_pairs),
            n_hold_max_bars_keys_written=n_keys_written,
        )

    async def _calibrate_hold_max_bars(
        self,
        pool: asyncpg.Pool,
        results: list[dict[str, Any]],
        config: EnsembleICConfig,
    ) -> int:
        """EIC-02: derive alpha.frame.hold_max_bars.<regime>.<tf> from the just-written
        IC decay curve and write via ConfigService.set.

        Per-symbol calibration: group results by (symbol, tf, regime), call
        _select_hold_bars_from_decay for each group. Per-(regime, tf) aggregation: take
        the MEDIAN hold_bars across the symbols that returned a non-None result (more
        robust to a single outlier symbol than min/max). A (regime, tf) pair with zero
        qualifying symbols is SKIPPED entirely -- no config_service.set call, no
        fallback default -- the prior APR value (existing calibration or the migration's
        [initial_estimate] seed) remains authoritative until a future run qualifies.

        Excludes is_pooled=true rows: hold_max_bars is a per-symbol execution parameter,
        and the POOLED row is a diagnostic aggregate, not a tradable (symbol, tf, regime)
        cell -- including it in the per-symbol median would let a single non-tradable
        row skew a value that governs real position holds.
        """
        groups: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
        for row in results:
            if row.get("is_pooled"):
                continue
            key = (row["symbol"], row["tf"], row["regime"])
            groups.setdefault(key, []).append(row)

        scale_to_bars = {
            "fast": config.lookahead_fast,
            "mid": config.lookahead_mid,
            "slow": config.lookahead_slow,
            "extended": config.lookahead_extended,
        }

        # per_regime_tf[(regime, tf)] = list of qualifying per-symbol hold_bars values.
        per_regime_tf: dict[tuple[str, str], list[int]] = {}
        for (_symbol, tf, regime), cells in groups.items():
            hold_bars = _select_hold_bars_from_decay(cells, config.decay_threshold, scale_to_bars)
            if hold_bars is None:
                continue
            per_regime_tf.setdefault((regime, tf), []).append(hold_bars)

        if not per_regime_tf:
            return 0

        config_service = ConfigService(database_url=self._db_dsn, pool=pool)
        await config_service.initialize()

        n_written = 0
        for (regime, tf), qualifying_hold_bars in per_regime_tf.items():
            n_qualifying = len(qualifying_hold_bars)
            median_hold_bars = int(np.median(qualifying_hold_bars))
            key = f"alpha.frame.hold_max_bars.{regime}.{tf}"
            await config_service.set(
                key,
                str(median_hold_bars),
                changed_by="ensemble-ic-engine",
                reason=(
                    "calibrated from IC decay curve (EIC-02); median across "
                    f"{n_qualifying} qualifying (passes_fdr=true AND reliable=true) "
                    f"symbols; decay_threshold={config.decay_threshold}"
                ),
            )
            n_written += 1

        return n_written


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    try:
        init_otel_providers("indicagent-ensemble-ic-engine")
    except OTelInitError as error:
        _logger.warning("ensemble_ic_engine.otel_init_failed", error=str(error))

    settings = Settings()
    db_dsn = settings.database_url.replace("postgresql+asyncpg://", "postgresql://")
    asyncio.run(EnsembleICEngine(db_dsn=db_dsn).run())
