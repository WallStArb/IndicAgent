#!/usr/bin/env python3
"""EnsembleICEngine -- measures IC(alpha_score, forward_return_*) per (symbol, tf, regime,
lookahead) for the v3.0 ensemble output (Phase 142A, EIC-01).

Proves the ensemble OUTPUT has IC before any execution rules are tested. Composes the
SAME corrected IC methodology as ic_engine.py (Fisher z-transform CI, NOT circular block
bootstrap; corpus-level BH-FDR; expanding-window walk-forward with scale-specific embargo)
onto a single composite predictor (alpha_score), reading ensemble_alpha joined to
forward_returns and market_regimes.

CORRECTNESS INVARIANTS:
- Measurement population is ensemble_alpha (every scored bar), NOT alpha_events (the
  post-emission-threshold execution subset) -- 2026-07-08 finding. This engine's own
  stated purpose is "prove the ensemble OUTPUT has IC... no frame assumptions," but
  alpha_events is ensemble_alpha AFTER a threshold + directional-CI + cost-hurdle
  filter -- an execution-policy gate, not a signal-validation population. Measuring
  IC only on bars that already cleared a confidence threshold is post-selection bias:
  it conditions the correlation test on the very thing being validated, which can bias
  the measured IC in either direction and destroys statistical power. Observed effect
  before this fix: alpha_events was 0.17% of ensemble_alpha's row count, collapsing
  per-cell N to 100-150 against a 3000-observation floor -- switching to ensemble_alpha
  empirically resolved 90-96% of 5m/15m cells to N>=3000 (1d remains structurally
  underpowered regardless of population -- too few daily bars ever, not fixable this
  way). alpha_events/the emission threshold is still the correct population for
  Phase 142B (frame simulation tests whether an execution RULE is profitable -- a
  different question, correctly downstream of signal validation).
- Executable returns only (Invariant 1): every forward_returns query filters
  WHERE return_type = 'executable_open_to_open'.
- ProcessPoolExecutor workers are dispatched one per symbol, each opening its own
  READ-ONLY connection and looping over that symbol's TFs on it (mirrors
  ic_engine._run_ic_worker's precedent exactly, todo 047 + follow-up) -- amortizes
  connection setup across TFs instead of one connection per (symbol, tf) pair, while
  still overlapping I/O with compute across workers instead of serially fetching ~232
  pairs in the main process before dispatch. Workers return list[dict] rows for a single
  serial write in the main process after corpus-level BH-FDR. CLAUDE.md's
  "workers are compute-only" invariant is about WRITE connections/commits from
  subprocesses (the deadlock risk is concurrent writers on the same hypertable) -- no
  worker here ever writes or commits.
- alpha_score is ONE predictor -- collinearity clustering is skipped (feature-level
  concern only); every cell IS representative for the single corpus-level BH-FDR call.
- scored_at is pinned to a single run_ts (UTC "now" at start) computed ONCE per
  _execute_inner and reused for every row (D-142A-R2): a failed-and-retried run upserts
  in place via ON CONFLICT (event_row_id, scored_at) DO UPDATE; separate invocations
  accumulate distinct vintages (mirrors ic_engine.computed_at).
- walk_forward_stable (EIC-03) is the fold IC-MAGNITUDE max/min ratio, NOT a fold
  IC-Sharpe ratio (D-142A-R1: reasoned v1 relaxation -- see compute_walk_forward_stable).
- Crashes loud at startup when ensemble_alpha, forward_returns, OR market_regimes is empty.
- In-sample filter: all queries restrict bar_ts < alpha.validation.oos_start (OOS half
  reserved for Phase 144).
- Pooled cross-sectional dispatch (todo 046 / D-01, Phase 142B.1 Wave 0): in addition to
  the per-(symbol, tf) workers above, one worker task with symbol=_POOLED_SYMBOL runs
  per invocation, producing symbol='POOLED' alpha_ensemble_ic rows -- the aggregation
  grain (group by (tf, regime, bar_ts), average alpha_score/returns across symbols
  BEFORE computing IC) lives in the pure function _aggregate_pooled_series. Per-symbol
  rows are retained unchanged (D-03) -- pooled is an additional diagnostic-grade
  UNIVERSE row, not a replacement.

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
from collections.abc import Iterable
from concurrent.futures import ProcessPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import asyncpg
import numpy as np
import psycopg2
import psycopg2.extras
import structlog
from scipy.stats import rankdata
from statsmodels.stats.multitest import multipletests

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# Composition, not subclassing/forking -- both this engine and ic_engine.py import the
# same shared IC math module (todo 048) rather than one reaching into the other's
# internals. EnsembleICConfig below mirrors ICEngineConfig's shared-key shape by
# convention, not by import (no direct type dependency).
from services._batch_utils import cfg as _cfg
from services._batch_utils import connect_db_from_url
from services._batch_utils import load_apr_dict_async as _load_apr_dict
from src.config.config_service import ConfigService  # EIC-02: alpha.frame.hold_max_bars writes
from src.config.settings import Settings
from src.core.agent.base_batch import BaseBatch
from src.intelligence.statistics.ic_math import (
    _compute_ic_rolling_metrics,
    _fisher_z_ci,
    _nan_to_none,
    _p_values_from_ic,
    _vectorized_ic,
)
from src.observability.corpus_manifest import CorpusManifest
from src.observability.otel import OTelInitError, init_otel_providers

_logger = structlog.get_logger(__name__)

_JOB = "ensemble-ic-engine"

# Gradient scale names for forward return horizons (matches forward_returns columns).
_SCALES: tuple[str, ...] = ("fast", "mid", "slow", "extended")

# scale name -> forward_returns column, for the returns_by_scale worker-arg fetch.
_SCALE_RETURN_COLUMNS: dict[str, str] = {
    "fast": "return_fast",
    "mid": "return_mid",
    "slow": "return_slow",
    "extended": "return_extended",
}

# Cross-sectional pooled-row sentinel (research OQ-2: 'POOLED', not '_pooled' -- alpha_events
# and alpha_ensemble_ic both use the literal string 'POOLED' for symbol, per migration 195's
# CHECK constraint (symbol = 'POOLED') = is_pooled).
_POOLED_SYMBOL = "POOLED"


def _effective_weight_version(cli_weight_version: str | None, apr_default: str) -> str:
    """CLI --weight-version overrides the APR default (mirrors ensemble_trainer.py /
    alpha_publisher.py's identical pattern) -- lets a scoped re-run measure exactly one
    weight epoch without touching alpha.ensemble.weight_version for every other consumer.
    """
    return cli_weight_version if cli_weight_version else apr_default


# ---------------------------------------------------------------------------
# APR compile-time binding
# ---------------------------------------------------------------------------

_INFRA_LIKE_PATTERNS = ["infra.ensemble_ic_engine.%"]


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
    pooled_fetch_itersize: int
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
            fdr_alpha=_cfg(cfg, "alpha.ic.fdr_alpha", 0.05),
            walk_forward_folds=_cfg(cfg, "alpha.ic.walk_forward_folds", 3),
            sharpe_window_size=_cfg(cfg, "alpha.ic.sharpe_window_size", 2000),
            sharpe_min_windows=_cfg(cfg, "alpha.ic.sharpe_min_windows", 30),
            subsample_min_stride=_cfg(cfg, "alpha.ic.subsample_min_stride", 5),
            min_reliable_n=_cfg(cfg, "alpha.ic.min_reliable_n", 100),
            hac_max_lag=_cfg(cfg, "alpha.ic.hac_max_lag", 3),
            lookahead_fast=_cfg(cfg, "alpha.ic.lookahead.fast", 1),
            lookahead_mid=_cfg(cfg, "alpha.ic.lookahead.mid", 5),
            lookahead_slow=_cfg(cfg, "alpha.ic.lookahead.slow", 20),
            lookahead_extended=_cfg(cfg, "alpha.ic.lookahead.extended", 60),
            n_workers=_cfg(cfg, "infra.ensemble_ic_engine.workers", 12),
            pooled_fetch_itersize=_cfg(
                cfg, "infra.ensemble_ic_engine.pooled_fetch_itersize", 50_000
            ),
            decay_threshold=_cfg(cfg, "alpha.ensemble_ic.decay_threshold", 0.1),
            min_qualifying_fraction=_cfg(cfg, "alpha.ensemble_ic.min_qualifying_fraction", 0.60),
            wf_stability_ratio=_cfg(cfg, "alpha.ensemble_ic.wf_stability_ratio", 3.0),
            gate_lookahead=_cfg(cfg, "alpha.ensemble_ic.gate_lookahead", "fast"),
            wf_stability_metric=_cfg(cfg, "alpha.ensemble_ic.wf_stability_metric", "ic_ratio"),
            min_obs_per_regime=_cfg(cfg, "alpha.ensemble_ic.min_obs_per_regime", 3000),
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

# Significance + sufficiency + stability gate (review finding #6, MANDATORY; extended
# 2026-07-09 to add walk_forward_stable — see ensemble_trainer.py's CORRECTNESS
# INVARIANTS docstring for why cross-sectional significance alone is not a sufficient
# bar). Mirrors EIC-04's own phase-gate query (ops_ensemble_ic_gate.py, `_GATE_SQL`).
_QUALIFYING_FLAGS = ("passes_fdr", "reliable", "walk_forward_stable")


def _select_hold_bars_from_decay(
    cells: list[dict[str, Any]],
    decay_threshold: float,
    scale_to_bars: dict[str, int],
) -> int | None:
    """Pure function: select hold_bars from one (symbol, tf, regime) group's IC decay curve.

    A cell must satisfy every flag in _QUALIFYING_FLAGS to participate in the decay
    walk: passes_fdr=true (not statistically indistinguishable from noise), reliable=true
    (not passing FDR on insufficient N with an unstable ic_sharpe), and
    walk_forward_stable=true (reproduces out-of-sample across folds, EIC-03/D-142A-R1).

    After filtering, walks the qualifying cells in canonical scale order
    [fast, mid, slow, extended]. At the first scale where ic_sharpe is not None and
    ic_sharpe < decay_threshold, returns the lookahead_bars of the PRECEDING qualifying
    scale (the last scale where the edge was still alive) -- or 1 if the very first
    qualifying scale is already below threshold. If no scale crosses the threshold,
    returns the lookahead_bars of the longest scale actually measured and confirmed
    non-decaying (preceding_bars) -- NOT the nominal ceiling scale_to_bars['extended'],
    which may not have qualified (small-N/low-significance tail cells are the common
    failure case at that horizon). Falls back to 1 if nothing qualified at all.
    A cell with ic_sharpe=None is treated as "no data" and skipped in the walk, not as
    a below-threshold crossing.

    Returns None if there are zero qualifying cells for this group -- the caller must
    interpret this as "no qualifying signal; skip calibration, leave the prior APR
    value in place" rather than defaulting to any hold_bars value.
    """
    qualifying = [c for c in cells if all(c.get(flag) is True for flag in _QUALIFYING_FLAGS)]
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

    # preceding_bars, not the extended ceiling -- see docstring.
    return preceding_bars if preceding_bars is not None else 1


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
    weight_version: str,
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

    weight_version tags which weight variant's ensemble_alpha this row measures (mirrors
    ensemble_alpha.weight_version, migration 168) -- required so Plan 05's A/B judge
    (ops_ensemble_weight_compare.py) can GROUP BY weight_version without blending two
    challengers' measurements together (migration 196 Section 3).
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
        "weight_version": weight_version,
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
        weight_version, n_independent, reliable, ic_value, ic_ci_lower, ic_ci_upper,
        ic_sharpe, ic_sharpe_hac, bh_adjusted_p, passes_fdr, walk_forward_stable, scored_at
    )
    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16, $17, $18, $19)
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


def _parse_insert_columns(insert_sql: str) -> tuple[str, ...]:
    """Extract the column list from an `INSERT INTO tbl (col1, col2, ...)` statement.

    Derives the row-tuple column order from the SQL itself so it can't drift out of
    sync with _ENSEMBLE_IC_INSERT_SQL -- previously a hand-maintained duplicate list.
    """
    start = insert_sql.index("(") + 1
    end = insert_sql.index(")", start)
    return tuple(col.strip() for col in insert_sql[start:end].split(","))


_ROW_COLUMN_ORDER: tuple[str, ...] = _parse_insert_columns(_ENSEMBLE_IC_INSERT_SQL)


def _row_to_tuple(row: dict[str, Any]) -> tuple[Any, ...]:
    return tuple(row[col] for col in _ROW_COLUMN_ORDER)


# ---------------------------------------------------------------------------
# Startup crash-loud gates (review finding #5: market_regimes added)
# ---------------------------------------------------------------------------


async def _assert_prerequisites(
    conn: asyncpg.Connection,
    weight_version: str,
    tfs: list[str] | None = None,
    manifest_dir: Path = CorpusManifest.DEFAULT_MANIFEST_DIR,
) -> None:
    """Three COUNT checks plus a manifest check; raise RuntimeError (crash loud) if any
    fails.

    ensemble_alpha is scoped to weight_version (CR-01, code review): an unscoped count(*)
    would still pass as long as SOME other weight_version has rows, letting a
    typo'd/stale --weight-version silently complete with n_rows=0 instead of crashing loud.
    """
    n_alpha = await conn.fetchval(
        "SELECT count(*) FROM ensemble_alpha WHERE weight_version = $1", weight_version
    )
    if not n_alpha:
        raise RuntimeError(
            f"EnsembleICEngine startup gate FAILED: ensemble_alpha has zero rows for "
            f"weight_version={weight_version!r}. Run ensemble_trainer.py "
            f"with --weight-version {weight_version!r} first, or check "
            f"for a typo / stale alpha.ensemble.weight_version APR value."
        )

    # A nonzero row count above does not mean the run that wrote those rows finished.
    # ensemble_trainer.py is the sole writer of ensemble_alpha; its "full replace" delete
    # (both DELETEs auto-commit standalone) then repopulates one stratum's transaction at
    # a time -- a mid-run crash after the delete leaves exactly this: nonzero but
    # incomplete rows for the weight_version. CorpusManifest.ensure_success_for closes
    # this the same way for every prerequisite-gate call site (2026-07-08 altitude
    # review finding: alpha_publisher.py's gate has the identical exposure).
    CorpusManifest.ensure_success_for(
        manifest_dir, "ensemble_trainer", scope_suffix=weight_version, weight_version=weight_version
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


# Per-(symbol, tf) fetch, run inside each worker (read-only) rather than serially in the
# main process before dispatch -- mirrors ic_engine._run_ic_worker's per-worker connection
# precedent. CLAUDE.md's "workers are compute-only" rule concerns WRITE connections/commits
# from subprocesses (the deadlock risk is concurrent writers on the same hypertable); it does
# not forbid read-only fetches, which is exactly how ic_engine already parallelizes I/O with
# compute across workers (todo 047, 2026-07-02).
# weight_version is filtered here (not just tagged on write) so a re-run scoped to a
# challenger variant (e.g. 'v1_shrunk') never blends in a different variant's
# ensemble_alpha rows that happen to share (symbol, tf, bar_ts) -- migration 196 Section 3.
# Sources from ensemble_alpha (every scored bar), NOT alpha_events (the emission-gated
# execution subset) -- see module docstring's measurement-population invariant.
_WORKER_FETCH_SQL = """
    SELECT ea.alpha_score, fr.return_fast, fr.return_mid,
           fr.return_slow, fr.return_extended, mr.regime_label
    FROM ensemble_alpha ea
    JOIN forward_returns fr
      ON fr.symbol = ea.symbol AND fr.tf = ea.tf AND fr.bar_ts = ea.bar_ts
      AND fr.return_type = 'executable_open_to_open'
    JOIN market_regimes mr
      ON mr.asset_class = 'equity' AND mr.tf = ea.tf AND mr.ts = ea.bar_ts
    WHERE ea.symbol = %s AND ea.tf = %s AND ea.weight_version = %s AND ea.bar_ts < %s
    ORDER BY ea.bar_ts
"""

# ---------------------------------------------------------------------------
# Pooled cross-sectional dispatch (todo 046 / D-01) -- Wave 0
# ---------------------------------------------------------------------------
#
# Same joins as _WORKER_FETCH_SQL but with the `ea.symbol = %s` filter dropped, so it
# returns ONE raw row per (symbol, bar_ts) across ALL symbols sharing this tf. The
# per-symbol rows are then reduced by the pure function _aggregate_pooled_series below
# BEFORE any IC math runs -- RESEARCH.md Pitfall 5 requires grouping by
# (tf, regime, bar_ts) and averaging across symbols first, never averaging first and
# labeling second. market_regimes is asset_class-scoped (not per-symbol), so every
# symbol at a given (tf, bar_ts) shares exactly one regime_label by construction --
# grouping by (regime_label, bar_ts) within a fixed tf is therefore equivalent to
# grouping by the full (tf, regime, bar_ts) triple.
_POOLED_WORKER_FETCH_SQL = """
    SELECT ea.symbol, ea.bar_ts, ea.alpha_score, fr.return_fast, fr.return_mid,
           fr.return_slow, fr.return_extended, mr.regime_label
    FROM ensemble_alpha ea
    JOIN forward_returns fr
      ON fr.symbol = ea.symbol AND fr.tf = ea.tf AND fr.bar_ts = ea.bar_ts
      AND fr.return_type = 'executable_open_to_open'
    JOIN market_regimes mr
      ON mr.asset_class = 'equity' AND mr.tf = ea.tf AND mr.ts = ea.bar_ts
    WHERE ea.tf = %s AND ea.weight_version = %s AND ea.bar_ts < %s
    ORDER BY ea.bar_ts
"""

# Value columns averaged across symbols for each pooled (tf, regime, bar_ts) cell.
_POOLED_VALUE_COLS: tuple[str, ...] = (
    "alpha_score",
    "return_fast",
    "return_mid",
    "return_slow",
    "return_extended",
)


@dataclasses.dataclass
class _RunningMean:
    """Streaming mean accumulator -- one per (cell, column). Replaces collecting a
    full list of raw values per column then calling np.mean() at the end, which
    would hold every raw row in memory simultaneously (see _aggregate_pooled_series
    docstring for why that's a real memory risk against ensemble_alpha's size)."""

    total: float = 0.0
    count: int = 0

    def add(self, value: float) -> None:
        self.total += value
        self.count += 1

    def mean(self) -> float | None:
        return self.total / self.count if self.count else None


def _aggregate_pooled_series(
    fetched_rows: Iterable[dict[str, Any]], tf: str
) -> list[dict[str, Any]]:
    """Pure function (no DB): reduce per-(symbol, bar_ts) rows to one pooled row per
    (tf, regime, bar_ts) cell, averaging alpha_score + forward returns across symbols.

    RESEARCH.md Pitfall 5 regression guard: groups by the full (tf, regime, bar_ts)
    triple BEFORE averaging -- rows sharing a bar_ts but carrying DIFFERENT
    regime_label values are never mixed into the same pooled cell (average-first-
    label-second would silently blend cross-regime observations).

    Accumulates a running (sum, count) per group instead of collecting full member
    lists -- accepts any iterable (a list, or a live server-side DB cursor), and peak
    memory is O(distinct (regime, bar_ts) cells) rather than O(raw row count). The
    pooled fetch has no per-symbol filter (by design -- it needs every symbol sharing
    a tf), so raw row count scales with symbols x bars; against ensemble_alpha's full
    scored population (not the much smaller emission-gated alpha_events this engine
    used to read from) a collect-then-mean implementation held every raw row in memory
    at once. 2026-07-08: this is the same fetchall()-before-reduce shape that OOM'd
    ic_engine.py's cross-sectional pass twice the same week; the pooled worker doesn't
    hold a full-width feature matrix like that code did, but it already caused a real
    "No space left on device" shared-memory failure on 2 of 240 symbol/tf cells during
    a live corpus run, silently dropped and logged rather than surfaced.

    Args:
        fetched_rows: raw per-(symbol, bar_ts) dicts from _POOLED_WORKER_FETCH_SQL
            (or equivalent), each with keys: bar_ts, regime_label, alpha_score,
            return_fast, return_mid, return_slow, return_extended.
        tf: the timeframe this fetch was scoped to (constant across all input rows --
            included in the group key for an explicit (tf, regime, bar_ts) grain
            rather than relying on caller discipline).

    Returns:
        list of dicts, one per (regime_label, bar_ts) cell, sorted by bar_ts, with
        each _POOLED_VALUE_COLS entry replaced by its cross-symbol mean. Rows with a
        NULL regime_label or bar_ts are dropped (cannot be assigned to a stratum).
        Returns [] for empty input -- no divide-by-zero.
    """
    groups: dict[tuple[str, Any, Any], dict[str, _RunningMean]] = {}
    for row in fetched_rows:
        regime_label = row.get("regime_label")
        bar_ts = row.get("bar_ts")
        if regime_label is None or bar_ts is None:
            continue
        key = (tf, regime_label, bar_ts)
        # Plain `if key not in groups` instead of setdefault(key, <fresh dict>) --
        # setdefault's default argument is built eagerly on every call regardless of
        # whether the key already exists, so a per-row setdefault would allocate a
        # throwaway dict for every one of the symbols x bars raw rows even though
        # there are only bars-many distinct groups.
        col_stats = groups.get(key)
        if col_stats is None:
            col_stats = {col: _RunningMean() for col in _POOLED_VALUE_COLS}
            groups[key] = col_stats
        for col in _POOLED_VALUE_COLS:
            value = row.get(col)
            if value is not None:
                col_stats[col].add(value)

    pooled: list[dict[str, Any]] = []
    for (_tf, regime_label, bar_ts), col_stats in groups.items():
        agg: dict[str, Any] = {"bar_ts": bar_ts, "regime_label": regime_label}
        for col in _POOLED_VALUE_COLS:
            agg[col] = col_stats[col].mean()
        pooled.append(agg)

    pooled.sort(key=lambda r: r["bar_ts"])
    return pooled


def _run_ensemble_ic_worker(args: tuple) -> dict[str, Any]:
    """ProcessPoolExecutor worker -- runs in subprocess. Opens ONE read-only connection
    for this symbol and loops over all its TFs, fetching + computing IC for each.

    One connection per worker dispatch (not per (symbol, tf) pair) amortizes connection
    setup across the symbol's TFs -- mirrors ic_engine._run_ic_worker exactly, which is
    dispatched per-symbol and loops TFs over a single connection (services/ic_engine.py
    _run_ic_worker). An earlier version of this worker was dispatched per (symbol, tf)
    pair, opening ~232 connections instead of ~58; grouping by symbol was the missing
    half of mirroring that precedent (todo 047 follow-up, 2026-07-02).

    Pooled cross-sectional dispatch (todo 046 / D-01, Wave 0): when symbol ==
    _POOLED_SYMBOL, this is the ONE dispatch task covering every tf's cross-sectional
    aggregate (symbol_to_tfs[_POOLED_SYMBOL] = all distinct tfs in _execute_inner) --
    it reuses this exact worker function and the entire downstream IC-computation loop
    unchanged. Only the fetch step differs: _POOLED_WORKER_FETCH_SQL pulls every
    symbol's raw rows for the tf (no `ae.symbol = %s` filter), then
    _aggregate_pooled_series reduces them to one row per (tf, regime, bar_ts) cell
    BEFORE the regime/scale loop below runs its rank-IC math -- the aggregation itself
    must be a pure, DB-free step for unit testability (RESEARCH.md Pitfall 5), so it
    could not be pushed into a SQL-side AVG.

    Args:
        args: (symbol, tfs, dsn, oos_start, config, run_ts, weight_version)
            tfs: list[str] -- all timeframes to score for this symbol.
            dsn: str -- DSN passed from the main process rather than re-instantiating
                Settings(), which re-reads env vars and would diverge if the subprocess
                environment differs (mirrors ic_engine._run_ic_worker).
            oos_start: datetime -- OOS boundary; only bar_ts < oos_start is measured.
            config: EnsembleICConfig (frozen, picklable)
            run_ts: datetime -- pinned once per invocation (D-142A-R2)
            weight_version: str -- scopes both the ensemble_alpha fetch (WHERE
                ea.weight_version = %s) and every row's tag column, so this run
                measures exactly one weight variant (migration 196 Section 3).

    Returns:
        dict with keys: rows (list[dict]), pvals (list[float]), pval_idxs (list[int]),
        is_pooled (bool), errors (list[str]) -- one entry per TF that failed to
        fetch/compute; a partial per-TF failure does not discard the symbol's other TFs.
    """
    symbol, tfs, dsn, oos_start, config, run_ts, weight_version = args

    rows: list[dict[str, Any]] = []
    pvals: list[float] = []
    pval_idxs: list[int] = []
    errors: list[str] = []
    is_pooled = symbol == _POOLED_SYMBOL

    try:
        conn = connect_db_from_url(dsn)
    except Exception as error:
        return {
            "rows": rows,
            "pvals": pvals,
            "pval_idxs": pval_idxs,
            "is_pooled": is_pooled,
            "errors": [f"{symbol}: connection failed: {error}"],
        }

    try:
        for tf in tfs:
            try:
                if is_pooled:
                    # Fetch ALL symbols' raw rows for this tf, then reduce to one
                    # pooled row per (tf, regime, bar_ts) cell in Python -- the
                    # grouping/averaging step (Pitfall 5) must happen before any IC
                    # math, so it cannot be folded into a SQL-side AVG here. No
                    # per-symbol filter means row count scales with symbols x bars;
                    # a named (server-side) cursor streams rows in itersize-sized
                    # batches instead of psycopg2's default of buffering the entire
                    # result client-side on execute() -- _aggregate_pooled_series
                    # accumulates a running sum/count per group as it consumes the
                    # cursor, so peak memory is O(distinct cells), not O(raw rows).
                    # Matches regime_writer.py's _compute_symbol_tf precedent: commit
                    # any transaction left open by a prior tf iteration on this same
                    # connection before declaring the named cursor.
                    conn.commit()
                    with conn.cursor(
                        name=f"pooled_fetch_{tf}", cursor_factory=psycopg2.extras.RealDictCursor
                    ) as cur:
                        cur.itersize = config.pooled_fetch_itersize
                        cur.execute(_POOLED_WORKER_FETCH_SQL, (tf, weight_version, oos_start))
                        fetched = _aggregate_pooled_series(cur, tf)
                else:
                    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                        cur.execute(_WORKER_FETCH_SQL, (symbol, tf, weight_version, oos_start))
                        fetched = cur.fetchall()
            except Exception as error:
                errors.append(f"{symbol}/{tf}: {error}")
                try:
                    conn.rollback()
                except Exception:
                    pass
                continue

            if not fetched:
                continue

            alpha_scores = np.array([float(r["alpha_score"]) for r in fetched])
            returns_by_scale = {
                scale: np.array([float(r[col]) if r[col] is not None else np.nan for r in fetched])
                for scale, col in _SCALE_RETURN_COLUMNS.items()
            }
            regime_labels = np.array([r["regime_label"] for r in fetched], dtype=object)

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

                    # Expanding-window walk-forward with scale-specific embargo (P3 fix
                    # pattern).
                    embargo_bars = lookahead_bars
                    walk_forward_folds = config.walk_forward_folds
                    fold_ics: list[float] = []
                    for k in range(walk_forward_folds):
                        train_end = int(n_valid * (k + 1) / (walk_forward_folds + 1))
                        test_start = train_end + embargo_bars
                        test_end = int(n_valid * (k + 2) / (walk_forward_folds + 1))
                        if (
                            test_start >= test_end
                            or (test_end - test_start) < config.min_reliable_n
                        ):
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

                    # Cell-level IC Sharpe / HAC Sharpe over the FULL cell series
                    # (distinct from the per-fold quantities above; not used for
                    # EIC-03 stability).
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
                        weight_version=weight_version,
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
    finally:
        try:
            conn.close()
        except Exception:
            pass

    return {
        "rows": rows,
        "pvals": pvals,
        "pval_idxs": pval_idxs,
        "is_pooled": is_pooled,
        "errors": errors,
    }


# ---------------------------------------------------------------------------
# EnsembleICEngine
# ---------------------------------------------------------------------------


class EnsembleICEngine(BaseBatch):
    """Batch compute service: ensemble_alpha + forward_returns + market_regimes -> alpha_ensemble_ic.

    Measures IC(alpha_score, forward_return_<scale>) per (symbol, tf, regime, lookahead)
    using the same Fisher-z CI + corpus-level BH-FDR + walk-forward machinery as ic_engine.
    """

    job_name = "ensemble-ic-engine"
    compute_version = "1.0.0"

    def __init__(self, db_dsn: str, weight_version_override: str | None = None) -> None:
        super().__init__(db_dsn)
        self._weight_version_override = weight_version_override

    async def execute(self, pool: asyncpg.Pool) -> None:
        manifest = CorpusManifest("ensemble_ic_engine", CorpusManifest.DEFAULT_MANIFEST_DIR)
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
            apr_cfg = await _load_apr_dict(conn, extra_like_patterns=_INFRA_LIKE_PATTERNS)
            config = EnsembleICConfig.from_apr(apr_cfg)

            # Per-run weight epoch: CLI --weight-version overrides the APR default so a
            # scoped measurement run (e.g. against an E1/E2 challenger's ensemble_alpha) never
            # silently reads a different weight_version's rows (migration 196 Section 3).
            champion_weight_version = _cfg(apr_cfg, "alpha.ensemble.weight_version", "v1")
            weight_version = _effective_weight_version(
                self._weight_version_override, champion_weight_version
            )
            self.logger.info("ensemble_ic.weight_version_scoped", weight_version=weight_version)

            tfs = await conn.fetch(
                "SELECT DISTINCT tf FROM ensemble_alpha WHERE weight_version = $1", weight_version
            )
            tf_list = [r["tf"] for r in tfs]

            await _assert_prerequisites(conn, weight_version, tfs=tf_list)

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
                "SELECT DISTINCT symbol, tf FROM ensemble_alpha "
                "WHERE weight_version = $1 AND bar_ts < $2",
                weight_version,
                oos_start,
            )
            symbol_tf_pairs = [(r["symbol"], r["tf"]) for r in symbols_rows]
        # conn released here -- each worker below fetches its own slice over its own
        # read-only connection (todo 047), so the main process no longer holds the pool
        # connection through ~232 serial round trips before dispatch.

        # One worker per symbol, looping its TFs over a single connection -- amortizes
        # connection setup across TFs instead of opening one per (symbol, tf) pair
        # (mirrors ic_engine._run_ic_worker's per-symbol dispatch granularity).
        symbol_to_tfs: dict[str, list[str]] = {}
        for symbol, tf in symbol_tf_pairs:
            symbol_to_tfs.setdefault(symbol, []).append(tf)

        # Pooled cross-sectional dispatch (todo 046 / D-01, Wave 0): one additional
        # worker task, symbol=_POOLED_SYMBOL, covering every tf that has ensemble_alpha.
        # Per-symbol rows above are untouched (D-03 -- per-symbol stays as a diagnostic
        # layer, never dropped); this is purely additive to symbol_to_tfs.
        symbol_to_tfs[_POOLED_SYMBOL] = tf_list

        worker_args = [
            (symbol, tfs, self._db_dsn, oos_start, config, run_ts, weight_version)
            for symbol, tfs in symbol_to_tfs.items()
        ]

        corpus_all_results: list[dict[str, Any]] = []
        corpus_pvals_flat: list[float] = []
        corpus_pval_result_idxs: list[int] = []
        worker_errors: list[str] = []

        with ProcessPoolExecutor(max_workers=config.n_workers) as exe:
            for result in exe.map(_run_ensemble_ic_worker, worker_args, chunksize=1):
                worker_errors.extend(result["errors"])
                offset = len(corpus_all_results)
                corpus_all_results.extend(result["rows"])
                corpus_pvals_flat.extend(result["pvals"])
                corpus_pval_result_idxs.extend(offset + i for i in result["pval_idxs"])

        if worker_errors:
            self.logger.error(
                "ensemble_ic.worker_fetch_failed",
                n_failed=len(worker_errors),
                n_symbols=len(worker_args),
                errors=worker_errors[:10],
            )

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
        #
        # Gated on weight_version == champion (CR-02, code review): hold_max_bars feeds
        # live position-hold execution logic. Without this gate, running this engine
        # against an unproven E1/E2 challenger (exactly the workflow --weight-version
        # exists to support, mirroring ops_ensemble_weight_compare.py's champion/challenger
        # measurement) would silently recalibrate production config from data that hasn't
        # passed the D-10/D-12 win-decision gate yet.
        if weight_version == champion_weight_version:
            n_keys_written = await self._calibrate_hold_max_bars(pool, corpus_all_results, config)
        else:
            self.logger.info(
                "ensemble_ic.hold_max_bars_calibration_skipped",
                reason="scoped_weight_version_run",
                weight_version=weight_version,
                champion_weight_version=champion_weight_version,
            )
            n_keys_written = 0

        manifest.write()
        self.logger.info(
            "ensemble_ic.run_complete",
            n_rows=len(rows_to_write),
            n_symbol_tf_pairs=len(symbol_tf_pairs),
            n_hold_max_bars_keys_written=n_keys_written,
            weight_version=weight_version,
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

        # per_regime_tf[(regime, tf)] = list of qualifying per-symbol hold_bars values.
        per_regime_tf: dict[tuple[str, str], list[int]] = {}
        for (_symbol, tf, regime), cells in groups.items():
            hold_bars = _select_hold_bars_from_decay(
                cells, config.decay_threshold, config.lookaheads
            )
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
            qualifying_flags_desc = " AND ".join(f"{flag}=true" for flag in _QUALIFYING_FLAGS)
            await config_service.set(
                key,
                str(median_hold_bars),
                changed_by="ensemble-ic-engine",
                reason=(
                    "calibrated from IC decay curve (EIC-02); median across "
                    f"{n_qualifying} qualifying ({qualifying_flags_desc}) "
                    f"symbols; decay_threshold={config.decay_threshold}"
                ),
            )
            n_written += 1

        return n_written


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="EnsembleICEngine oneshot")
    parser.add_argument(
        "--weight-version",
        default=None,
        help=(
            "Weight variant to measure; overrides alpha.ensemble.weight_version so a "
            "challenger run (e.g. after ensemble_trainer --weight-version v1_shrunk) "
            "scores only its own ensemble_alpha rows, not the champion's"
        ),
    )
    args = parser.parse_args()

    try:
        init_otel_providers("indicagent-ensemble-ic-engine")
    except OTelInitError as error:
        _logger.warning("ensemble_ic_engine.otel_init_failed", error=str(error))

    settings = Settings()
    db_dsn = settings.database_url.replace("postgresql+asyncpg://", "postgresql://")
    asyncio.run(EnsembleICEngine(db_dsn=db_dsn, weight_version_override=args.weight_version).run())
