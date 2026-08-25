#!/usr/bin/env python3
"""IC Engine -- Spearman IC measurement substrate for v3.0 AlphaEngine.

Computes Information Coefficient (IC) per feature x symbol x TF x regime x lookahead,
with a circular block bootstrap confidence interval, BH-FDR multiple-testing correction,
60-bar-embargo walk-forward validation, IC Sharpe, and idempotent upsert into
feature_ic_scores.

CORRECTNESS INVARIANTS:
- CI uses a circular block bootstrap (`_circular_block_bootstrap_ic`,
  src/intelligence/statistics/ic_math.py; Component A / todo 091, Phase 143.1-01).
  Replaces the Fisher z-transform CI this file used from 2026-06-26 to 2026-07-11: the
  2026-07-09 empirical-null diagnostic (`ops_ic_null_calibration.py`) found Fisher-z's
  asymptotic SE assumption empirically miscalibrated on this corpus (38% SUSPECT rate,
  11/29 evaluated cells across 4/8 (tf, is_pooled) strata) -- the analytic CLT-converged
  claim did not hold at this corpus's actual autocorrelation/regime structure. The
  bootstrap re-ranks the resampled subset every iteration (the pre-ranking bug that
  caused THIS function's own prior 2026-06-26 removal is fixed, not reintroduced --
  see ic_math.py's docstring). `services/ensemble_ic_engine.py` and
  `scripts/ops/corpus/ops_oos_holdout_eval.py` intentionally stay on Fisher-z this
  phase (stated scope boundary, 143.1-CONTEXT.md resolved item 3).
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
    python services/ic_engine.py --training-window-end 2025-12-24T05:15:00+00:00
    python services/ic_engine.py --symbols VUG --tf 1h --training-window-end 2025-12-24T05:15:00+00:00
    python services/ic_engine.py --symbols SPY TLT --tf 5m 15m --training-window-end 2025-12-24T05:15:00+00:00

--training-window-end is REQUIRED (not optional). It is the sole OOS holdout enforcement
point for this file -- ops_corpus_pipeline_run.sh computes it as
LEAST(MAX(bar_ts), alpha.validation.oos_start) and passes it through. A bare MAX(bar_ts)
fallback would silently consume the OOS holdout window on any ad-hoc invocation; see
docs/plans/OOS-EVAL-PROTOCOL.md and Phase 141.1 (CR-01). For an ad-hoc single-symbol/TF
run, compute the same clamped value manually:
    SELECT LEAST(MAX(bar_ts), (SELECT config_value::timestamptz FROM config_state
        WHERE config_key = 'alpha.validation.oos_start')) FROM feature_vectors;
"""

from __future__ import annotations

import argparse
import ast
import dataclasses
import hashlib
import json
import math
import sys
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

import numpy as np

# Corpus manifest system
sys.path.insert(0, "src")
import structlog
from opentelemetry import trace
from opentelemetry.trace import StatusCode
from scipy.cluster.hierarchy import fcluster, linkage
from scipy.spatial.distance import squareform
from scipy.stats import rankdata

from observability.corpus_manifest import CorpusManifest

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from services._batch_utils import (
    ACTIVE_SCALES_FALLBACKS_BY_TF,
    Float32ChunkAccumulator,
    bulk_update_by_key,
    canonicalize_active_scales,
    connect_db_from_url,
    get_list_config,
    limit_blas_threads,
    lookahead_by_scale_from_apr,
    lookaheads_for_tf,
    make_worker_pool,
    short_lived_conn,
)
from services._batch_utils import compressed_hypertable_write_session as _write_session
from services._batch_utils import load_config_service_sync as _load_config_service
from src.config.settings import Settings
from src.core.agent.base_batch import BaseBatch
from src.core.integrity_monitor import INTEGRITY_MONITOR_INSERT_SQL, emit_integrity_fact_sync
from src.core.rng import hash_key_to_int
from src.core.service_utils import (
    format_iso_ts,
    parse_training_window_end,
    setup_service_logging,
)
from src.intelligence.concept_registry_service import ConceptRegistryService
from src.intelligence.schemas import FeatureVector
from src.intelligence.statistics.ic_math import (
    GuardVerdict,
    _compute_ic_rolling_metrics,
    _expand,
    _nan_to_none,
    _p_values_from_ic,
    _vectorized_ic,
    apply_bh_fdr,
    build_walk_forward_folds,
    evaluate_guard_fraction,
    expand_int,
    magnitude_conditional_ic,
    sign_hit_rate,
    update_cumulative_e_value,
    vol_normalized_return,
)
from src.observability.metrics import (
    ALPHA_DECAY_CELLS_FLAGGED,
    ALPHA_DECAY_ENSEMBLE_REBUILD_TOTAL,
    EFFECTIVE_N_GAUGE,
    FEATURE_IC_PASSING_WALKFORWARD_TOTAL,
    FEATURES_SURVIVING_FDR_GAUGE,
    IC_ENGINE_CELLS_COMPLETED_TOTAL,
    IC_ENGINE_CELLS_SKIPPED_TOTAL,
    IC_ENGINE_LAST_RUN_AGE_DAYS,
    IC_ENGINE_RUN_LATENCY_SECONDS,
    IC_ENGINE_RUN_SYMBOLS_TOTAL,
    IC_ENGINE_SYMBOLS_COMPLETED_TOTAL,
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

# Sentinel regime value for pooled (cross-regime) IC rows.
# The feature_ic_scores PK includes regime (NOT NULL), so we can't store NULL.
# is_pooled=true + regime='_pooled' is the canonical pooled-row identity.
_POOLED_REGIME_SENTINEL = "_pooled"

# Default TFs if not passed via --tf. Cheapest/most-reliable first (todo 132): the
# cross-sectional pass (_compute_cross_sectional_tf) writes each cell's rows
# immediately on completion, and per-cell cost scales with pooled row count -- 5m
# cells (the most rows, e.g. ~361674 for a single (group, regime) cell) are the ones
# that take ~1h+ each even after the todo-131 bootstrap-threading fix, while 1d/1h/15m
# cells are minutes. Processing 5m FIRST (the pre-131 order) meant the run spent its
# first many hours entirely in the tier most likely to hit an unrelated crash (OOM,
# connection drop, host reboot) with zero rows banked. Cheapest-first means a crash
# during the expensive 5m tail loses only the 5m tier's rows, not everything.
_DEFAULT_TFS: list[str] = ["1d", "1h", "15m", "5m"]

# Cross-sectional symbol sentinel: used when symbol='POOLED' (all 58 equity ETFs pooled).
# feature_ic_scores.symbol is NOT NULL, so we use a string sentinel.
_CROSS_SECTIONAL_SYMBOL = "POOLED"

# Magnitude-conditional IC percentile threshold (Component B, todo 090): defines
# "large |prediction|" as the top quartile by |X| per feature. [conventional]
# statistical concept definition (a quartile cutoff), not a tunable APR weight --
# same APR-exempt class as the "5" in momentum_z_5 (CLAUDE.md APR-exempt list).
# Diagnostic-only column; changing this does not affect any eligibility gate.
_MAGNITUDE_IC_PERCENTILE = 75.0

# Anytime-valid e-value pilot scope (Component C, todo 079): 5m ONLY this phase, not a
# full rollout -- genuinely new statistical machinery for the codebase, source doc
# explicitly cautions to pilot on one tf first (docs/research/
# fable-2026-07-07-renaissance-layer-refinements.md §L4-1). Deliberately a hardcoded
# scope constant, not an APR key -- this pilot's own scope decision, not a tunable
# parameter (widening to all TFs is a future-phase code change, not a config flip).
_E_VALUE_PILOT_TFS: frozenset[str] = frozenset({"5m"})


def _e_value_pilot_active(tf: str) -> bool:
    """True only for tf values in the e-value pilot's scope this phase (5m only).

    Pure predicate -- guards the e-process read/update/persist block inside
    _compute_cross_sectional_tf so every other timeframe's cumulative_e_value
    column stays NULL/untouched, exactly as the pilot's scope requires.
    """
    return tf in _E_VALUE_PILOT_TFS


def _resolve_regime_scope(is_pooled: bool, cross_sectional: bool) -> str:
    """Resolve the label vocabulary a feature_ic_scores row's regime column draws from.

    Scope reflects the label SOURCE (regime_label_source / mr_dict presence at compute
    time), never the label string itself -- see migration 192 rationale. Fixed schema
    enum values, not APR-backed (statistical concept definitions, not tunable params).

    Phase 172 plan 06: 'symbol_hmm' now denotes the volatility-vocabulary
    (calm/elevated/turbulent, feature_vectors.regime_volatility) per-symbol
    GaussianHMM, not the retired 5-label trend vocabulary. Rows written under this
    same scope value before Phase 172 carry the retired trend vocabulary
    (trending_down/transition_down/ranging/transition_up/trending_up,
    feature_vectors.regime) -- the two vintages are distinguishable by their regime
    label string alone, because the two vocabularies never intersect (see
    172-IC-ENGINE-CUTOVER.md's vintage-separation audit). No new scope value was
    added for the volatility vintage; the label SOURCE (a per-symbol GaussianHMM)
    is unchanged, only the observation columns and vocabulary it was fit on.
    """
    if is_pooled:
        return "pooled"
    if cross_sectional:
        return "cross_sectional"
    return "symbol_hmm"


class CellTooLargeError(RuntimeError):
    """Raised when a single IC compute cell's raw row count exceeds
    alpha.ic.max_cell_rows (162-01 Task 3, todo 140).

    Crash-loud by design: a cell this large is a data-integrity/capacity signal
    (either a real corpus-size milestone or a routing bug pooling unrelated
    symbols), never something to silently route to an alternate/degraded
    algorithm ("silent wrong answers are worse than loud crashes", CLAUDE.md
    north star). A distinct exception type (not a bare RuntimeError) so
    _run_ic_worker's per-tf exception handler can re-raise this specific
    failure instead of swallowing it like other per-cell exceptions -- an
    oversized cell must fail the whole job (nonzero exit code, error recorded
    in the run summary/manifest), not just skip silently to the next tf.
    """


# ---------------------------------------------------------------------------
# Symbol -> regime group routing (Phase 144 Plan 05)
# ---------------------------------------------------------------------------


class AmbiguousRegimeGroupError(ValueError):
    """Raised when a symbol's tags match more than one enabled regime group.

    Regime groups must partition the universe: a symbol occupies exactly one
    discrete regime state at a time, so tag_filter overlap across groups is a
    config authoring error, not something to resolve silently by JSON array
    order. Fix by tightening tag_filter prefixes or the instrument_tags data
    so the overlap is removed, then restart.
    """


def _build_symbol_regime_class(
    tags_by_symbol: dict[str, set[str]],
    group_configs: list[dict],
) -> dict[str, str]:
    """Map each symbol to its regime group name from the groups APR config.

    A symbol matches a group if any of its instrument_tags starts with any
    prefix in the group's tag_filter (trailing * stripped). Enabled groups'
    tag_filters must be mutually exclusive over the resolved universe -- if a
    symbol matches more than one group, this raises AmbiguousRegimeGroupError
    rather than silently picking the first match, since group order in the
    APR JSON is not a meaningful ranking and must never be load-bearing.

    A group's optional `exclude_symbols` list is the one sanctioned escape
    hatch from that invariant: a small, explicit, named set of symbols with
    genuine dual-categorical membership (e.g. sector ETFs whose earnings
    driver is a single commodity -- both their `eq_*` and `commodity_*` tags
    are legitimately weight=1.0, not a tagging error) that this routing pass
    should not match for this group. It is a documented, auditable carve-out
    -- not a silent precedence rule -- and only affects Job 2's single-label
    routing here; Job 1 (cross_sectional_regime_model.py's peer-averaging)
    has no such constraint and keeps using the symbol as a full peer.

    Symbols with no matching enabled group are OMITTED from the returned
    dict -- they get no regime_group and are excluded from regime-stratified
    IC (the pooled IC pass still covers them; no data is dropped, only the
    regime-conditional cut). This was previously a silent default to
    'equity', which mislabeled non-equity instruments (bonds, gold, bitcoin
    ETFs) under the SPY-vol x equity-breadth regime whenever their true
    group was absent or disabled. Silent mislabeling is worse than an
    explicit gap -- see the caller's loud startup log of unrouted symbols.
    """
    prefixes_by_group: list[tuple[str, list[str], frozenset[str]]] = [
        (
            g["name"],
            [p.rstrip("*") for p in g.get("tag_filter", [])],
            frozenset(g.get("exclude_symbols", [])),
        )
        for g in group_configs
        if g.get("enabled", True)
    ]
    result: dict[str, str] = {}
    for symbol, tags in tags_by_symbol.items():
        matches = [
            group_name
            for group_name, prefixes, exclude_symbols in prefixes_by_group
            if symbol not in exclude_symbols
            and any(any(t.startswith(pfx) for t in tags) for pfx in prefixes)
        ]
        if len(matches) > 1:
            raise AmbiguousRegimeGroupError(
                f"Symbol {symbol!r} matches multiple enabled regime groups "
                f"{matches} -- tag_filter patterns must be mutually exclusive. "
                f"Tags: {sorted(tags)}"
            )
        if matches:
            result[symbol] = matches[0]
    return result


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
        regime_label_source, computed_at, cluster_id, feature_status_at_eval, regime_scope,
        sign_hit_rate, magnitude_conditional_ic, cumulative_e_value
    )
    VALUES (
        %(feature_name)s, %(vector_domain)s, %(symbol)s, %(tf)s, %(regime)s,
        %(lookahead_bars)s, %(training_window_end)s, %(is_pooled)s,
        %(n_independent)s, %(reliable)s, %(ic_value)s, %(ic_sign)s, %(p_value)s,
        %(ic_ci_lower)s, %(ic_ci_upper)s, %(passes_ci_gate)s, %(bh_adjusted_p)s,
        %(passes_fdr)s, %(wf_fold_count)s, %(wf_pass_count)s, %(passes_walkforward)s,
        %(ic_sharpe)s, %(ic_sharpe_hac)s, %(ic_sharpe_n_windows)s, %(ic_sortino)s, %(ic_win_rate)s,
        %(regime_label_source)s, %(computed_at)s, %(cluster_id)s,
        %(feature_status_at_eval)s, %(regime_scope)s,
        %(sign_hit_rate)s, %(magnitude_conditional_ic)s, %(cumulative_e_value)s
    )
"""
_POOLED_INSERT_SQL = (
    _INSERT_BODY
    + "    ON CONFLICT (feature_name, symbol, tf, lookahead_bars, training_window_end)\n"
    + "        WHERE is_pooled = true AND symbol <> 'POOLED'\n"
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
# Sync span helper -- matches observed_span semantics for sync psycopg services
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
    """Open a psycopg connection to the TimescaleDB instance."""
    return connect_db_from_url(settings.database_url)


@contextmanager
def _short_lived_conn(settings: Settings):
    """Open a connection scoped to one unit of work, guaranteeing it closes.

    Main-process helper for the "own connection per unit of work" pattern used
    throughout this module (todo 130) -- opened right before use and closed
    right after, never held idle across a compute phase (the todo-125/143.1-07
    incident: a connection opened before hours of compute, dead by the time it
    was finally used). Worker-side connections (`connect_db_from_url(dsn)` in
    `_compute_symbol_tf`/`_compute_cross_sectional_tf`) are a separate pattern --
    they cross a ProcessPoolExecutor boundary and take a `dsn: str`, not a
    `Settings`, so they don't fit this helper (todo 129).
    """
    conn = _connect_db(settings)
    try:
        yield conn
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# APR compile-time binding
# ---------------------------------------------------------------------------


def _load_per_tf_apr_dict(cfg: Any, key_prefix: str, defaults: dict[str, int]) -> dict[str, int]:
    """{tf: int(cfg.get_sync(f"{key_prefix}.{tf}", default))} for every tf in defaults.

    Shared by bootstrap_block_size and cross_sectional_bootstrap_threads (162
    simplify-pass) -- previously each field copy-pasted this comprehension with its
    own tf-default tuple, a third independent enumeration of "the 4 tfs" alongside
    _DEFAULT_TFS.
    """
    return {
        tf: int(cfg.get_sync(f"{key_prefix}.{tf}", default)) for tf, default in defaults.items()
    }


@dataclasses.dataclass(frozen=True)
class ICEngineConfig:
    """Frozen config snapshot bound once at startup from APR.

    All values are immutable for the entire corpus run — no mid-run drift if
    config_state is updated externally. Pickle-safe so workers can receive it
    directly via ProcessPoolExecutor without re-loading from DB.
    """

    min_observations: int
    fdr_alpha: float
    walk_forward_folds: int
    sharpe_window_size: int
    sharpe_min_windows: int
    subsample_min_stride: int
    min_reliable_n: int
    cluster_max_corr: float
    lookahead_fast: dict[str, int]
    lookahead_mid: dict[str, int]
    lookahead_slow: dict[str, int]
    lookahead_extended: dict[str, int]
    active_scales: dict[str, tuple[str, ...]]
    equity_model_enabled: bool
    hac_max_lag: int
    cs_chunk_ts: int
    symbol_fetch_chunk_rows: int
    n_workers: int
    blas_threads_per_worker: int
    # Phase 143 Plan 03: post-run lifecycle hook (LIFECYCLE-03/04/05) thresholds.
    # Defaulted (matching the APR defaults from_apr() falls back to) rather than
    # required -- from_apr() always binds these explicitly in production; the
    # defaults exist so pre-existing direct ICEngineConfig(...) construction sites
    # (e.g. tests/unit/test_hac_ic_sharpe.py, which predates this plan and only
    # exercises the original 18 fields) don't break on this dataclass's field-count
    # growth (Rule 1 fix -- caught by the full tests/unit/ suite run).
    decay_materiality_threshold: float = 0.005
    # Todo 144: stratified, self-calibrating regime-shift guard, replacing the flat
    # decay_regime_shift_fraction (removed above). Rails are RCA-grounded against
    # EIC-04's established 96-98% normal failure-rate base, not guesses -- see
    # migration 237. Defaulted for the same reason as every other post-143 field:
    # pre-existing direct ICEngineConfig(...) construction sites must not break on
    # this dataclass's field-count growth.
    guard_fail_rate_max: float = 0.995
    guard_fail_rate_min: float = 0.85
    guard_band_z: float = 3.0
    guard_min_cells: int = 100
    guard_min_history: int = 8
    guard_history_window: int = 20
    decay_recovery_min_observations: int = 2000
    decay_recovery_min_passes: int = 2
    demotion_min_consecutive: int = 2
    meta_fdr_min_fraction: float = 0.50
    ic_staleness_alert_days: int = 5
    # Fable N4: pins the standing-weight JOIN to the APR champion weight_version --
    # the SAME key ensemble_trainer defaults to absent a CLI --weight-version override.
    # NEVER resolved by `ORDER BY computed_at DESC LIMIT 1` (would silently leak a
    # challenger epoch's weights into the materiality gate the moment E1/E2 A/B ships).
    ensemble_weight_version: str = "v1"
    # Phase 143.1-01 (Component A, todo 091): circular block bootstrap CI params.
    # Migrations 161/165/177 seeded these keys long before this plan gave them a
    # reader -- migration 222 strips the [deprecated] description prefix in the
    # same commit as this rewiring. Defaulted (not required) for the same reason
    # as the Phase 143 fields above: pre-existing direct ICEngineConfig(...)
    # construction sites (test_hac_ic_sharpe.py) must not break on field-count growth.
    bootstrap_resamples: int = 2000
    bootstrap_seed: int = 42
    # Todo 227 (2026-08-05): adaptive early-stop on the bootstrap_resamples loop --
    # stop once the running ci_lower/ci_upper percentile estimate has stabilized
    # (max abs change across a feature block <= bootstrap_early_stop_tol) for
    # bootstrap_early_stop_stable_checks consecutive checkpoints, never before
    # bootstrap_early_stop_min_resamples. Defaults to disabled: landing this code
    # must not itself change any existing ci_lower/ci_upper value (same "off by
    # default, flipping on is a separate deploy decision" pattern as
    # alpha.hmm.walk_forward.enabled). Bit-identical reproducibility is NOT
    # load-bearing for this CI -- every downstream consumer (ensemble_trainer's
    # significance clause, alpha_publisher's direction-aware gate, counterfactual_
    # tracker's exit condition) reads ci_lower/ci_upper as a threshold/sign gate
    # (> 0, < 0, > cost_hurdle), never compares an exact value run-to-run. Contrast
    # with HMM_RANDOM_STATE-style seeds, which ARE load-bearing (see glossary).
    bootstrap_early_stop_enabled: bool = False
    bootstrap_early_stop_check_interval: int = 200
    bootstrap_early_stop_tol: float = 0.002
    bootstrap_early_stop_min_resamples: int = 200
    bootstrap_early_stop_stable_checks: int = 2
    bootstrap_block_size: dict[str, int] = dataclasses.field(
        default_factory=lambda: {"5m": 78, "15m": 26, "1h": 10, "1d": 10}
    )
    # Todo 129 (2026-07-17), converted to a per-tf dict by todo 133 (162-02 Task 1,
    # migration 250): thread pool size for _subsample_and_rank's re-rank+IC step,
    # cross-sectional pass ONLY. 5m defaults threaded (largest cells benefit); 15m/1h/1d
    # default serial=1 (finish in minutes, threading only adds dispatch overhead).
    # CORRECTED 2026-07-30 (todo 215): migration 250's original description claimed
    # raising this for the per-symbol path would "oversubscribe cores instead of
    # speeding anything up" -- that was asserted, never measured, and an isolated-
    # single-worker live benchmark found the opposite (scipy's rankdata/argsort
    # releases the GIL; threading gave a real 2-6x wall-time reduction). See
    # per_symbol_bootstrap_threads below, migration 274 for the corrected persisted
    # description. Thread count changes wall time only, never output -- guaranteed
    # structurally by 162-01's precomputed resample-index matrix (starts_matrix),
    # drawn once per scale.
    cross_sectional_bootstrap_threads: dict[str, int] = dataclasses.field(
        default_factory=lambda: {"5m": 6, "15m": 1, "1h": 1, "1d": 1}
    )
    # Todo 215 (2026-07-30): per-symbol-path sibling of cross_sectional_bootstrap_threads
    # above, same shape (per-tf, same underlying _blocked_bootstrap_ci call) -- see that
    # field's comment for the corrected oversubscription claim. Previously hardcoded
    # max_workers=1 (this field did not exist). All-1s here, NOT the benchmarked value:
    # unlike the cross-sectional pass (runs single-process after the per-symbol pool has
    # already shut down), this path runs INSIDE all n_workers processes simultaneously,
    # and whether a given thread count nets positive under that real concurrent
    # contention (vs. the clean isolated-worker benchmark) has not yet been measured --
    # deliberately not tested live while a corpus pipeline run was in flight (see
    # STATE.md). Migration 273. Raise only after a dedicated multi-worker contention
    # benchmark, not by inference from the isolated-worker numbers alone.
    per_symbol_bootstrap_threads: dict[str, int] = dataclasses.field(
        default_factory=lambda: {"5m": 1, "15m": 1, "1h": 1, "1d": 1}
    )
    # Phase 143.1-04 (Component E, todo 094): champion/challenger behavior switch shared
    # with ensemble_trainer.py's alpha.ensemble.sign_symmetric. Gates ONLY the
    # _run_lifecycle_hook demote/material/worst_cell predicates below -- defaulted to the
    # APR fallback (false) so direct-constructor test sites (test_hac_ic_sharpe.py
    # precedent, commit b47595b9) do not break on this dataclass's field-count growth.
    sign_symmetric: bool = False
    # Phase 151 Plan 02: global switch widening the existing regime_passes symbol_hmm
    # stratification pass (previously gated ONLY by a routed symbol's per-group
    # dual_write_symbol_hmm field, migration 247) to run for every regime-group-routed
    # symbol. Purely additive (new regime_scope='symbol_hmm' rows only), unlike
    # dual_write_symbol_hmm this is a run-level APR key, not a per-group field --
    # resolved once here, not via _resolve_symbol_routing. Defaulted to the APR
    # seed (migration 286: true) so direct-constructor test sites match production
    # behavior by default.
    cluster_regime_conditioned: bool = True
    # Phase 144 Plan 05: regime_group routing. Raw JSON string (or already-parsed
    # list[dict] normalized to a JSON string here -- see from_apr()) of the
    # alpha.regime.groups APR config -- passed to
    # services.cross_sectional_regime_model._parse_group_configs() in main() to
    # derive enabled_groups. Defaulted for the same reason as every other
    # post-143 field: pre-existing direct ICEngineConfig(...) construction sites
    # (test_hac_ic_sharpe.py, test_ic_engine_lifecycle_hook.py) must not break on
    # this dataclass's field-count growth.
    regime_groups_json: str = "[]"
    # Todo 096: fixed window size in SUBSAMPLED bars for _compute_ic_rolling_metrics
    # (ic_math.py), replacing the old sharpe_window_size (raw bars // stride)
    # semantics, which let per-window statistical power collapse at longer
    # lookaheads and mechanically deflated ic_sharpe with zero real signal decay.
    # New APR key (alpha.ic.sharpe_window_size_subsampled, migration 230) rather
    # than a redefinition of sharpe_window_size -- avoids silent code/config
    # rollback skew and preserves the old key's raw-bar provenance in
    # config_history. sharpe_window_size itself is now vestigial (no longer read
    # by ic_math.py) but kept bound below for APR provenance continuity; do not
    # wire it into any new logic. Defaulted for the same reason as every other
    # post-143 field.
    sharpe_window_size_subsampled: int = 100
    # 162-01 Task 3 (todos 139/140): feature-axis chunk size for the feature-blocked
    # rank/IC/CI/fold rewrite (_subsample_and_rank) -- bounds peak transient memory to
    # O(n_sub x block) instead of O(n_sub x n_features). Migration 249. Defaulted for
    # the same reason as every other post-143 field.
    feature_block_columns: int = 32
    # 162-01 Task 3 (todo 140): crash-loud row-count ceiling. A cell above this raises
    # CellTooLargeError rather than silently routing to an alternate algorithm.
    # Migration 249. Defaulted for the same reason as every other post-143 field.
    max_cell_rows: int = 1_200_000
    # 162-04 Task 2 (todo 134 follow-on, migration 252): forward-looking, currently
    # UNUSED field. Seeded 0 (disabled) -- no auto-carry-forward behavior is wired to
    # read this value yet; a nonzero value would (once wired) let a cell's prior IC
    # be carried forward across a --training-window-end bump when the fraction of
    # bars new since the last compute is below this threshold. Stays 0 until the
    # drift study (ops_ic_fingerprint_equivalence.py --drift-study) empirically
    # justifies otherwise. Defaulted for the same reason as every other post-143
    # field.
    refresh_min_new_fraction: float = 0.0

    def lookaheads_for(self, tf: str) -> dict[str, int]:
        """Gradient-scale lookahead mapping for ONE timeframe (todo 146: bar counts
        differ per tf -- 60 bars is ~3 months at 1d but ~5 hours at 5m, so a single
        global grid was measuring a different real-world horizon per tf under the
        same scale name)."""
        return lookaheads_for_tf(
            self.lookahead_fast,
            self.lookahead_mid,
            self.lookahead_slow,
            self.lookahead_extended,
            tf,
        )

    def active_scales_for(self, tf: str) -> tuple[str, ...]:
        """Which scales ic_engine actually attempts computation for on this tf
        (2026-07-30 per-tf active-scale-set design). A scale absent here still has
        a bar-count value in lookahead_{fast,mid,slow,extended} (metadata persists)
        but is never attempted -- distinct from a scale that's active but happens
        to score below a reliability gate at runtime."""
        return self.active_scales[tf]

    @classmethod
    def from_apr(cls, cfg: Any) -> ICEngineConfig:
        """Load all IC engine APR parameters from ConfigService in one pass."""
        # Phase 144 Plan 05: alpha.regime.groups is a JSON-typed APR key -- once
        # cached, ConfigService._parse_value() has ALREADY called json.loads() on
        # it, so cfg.get_sync() returns an already-parsed list[dict], not a raw
        # string. Normalize here: json.dumps() a parsed list back to a string (so
        # ICEngineConfig stays a flat, picklable dataclass of primitives); pass a
        # raw string straight through unchanged. NEVER str() a list[dict] -- Python's
        # repr uses single quotes and True/False, which is not valid JSON and breaks
        # the json.loads() call inside _parse_group_configs() downstream.
        _raw_regime_groups = cfg.get_sync("alpha.regime.groups", "[]")
        regime_groups_json = (
            _raw_regime_groups
            if isinstance(_raw_regime_groups, str)
            else json.dumps(_raw_regime_groups)
        )
        # Lookaheads per (tf, scale) -- todo 146: a single global grid measured a
        # different real-world horizon per tf under the same scale name. Shared
        # loading logic lives in lookahead_by_scale_from_apr (services/_batch_utils.py).
        _lookahead_by_scale = lookahead_by_scale_from_apr(
            lambda key, default: int(cfg.get_sync(key, default))
        )
        # Active-scale set per tf (2026-07-30 design) -- which of the four scales
        # ic_engine actually attempts, distinct from the bar-count VALUES above
        # (lookahead_{fast,mid,slow,extended}), which stay populated even for an
        # excluded scale. canonicalize_active_scales() guarantees a deterministic
        # tuple order regardless of how the configured JSON array is written, so
        # _compute_apr_snapshot_key's fingerprint never moves on a semantically-
        # unchanged reorder. list(fb) NOT fb directly: get_list_config's `default: list`
        # type contract expects a list, not ACTIVE_SCALES_FALLBACKS_BY_TF's tuple values.
        active_scales = {
            tf: canonicalize_active_scales(
                get_list_config(cfg, f"alpha.ic.active_scales.{tf}", list(fb))
            )
            for tf, fb in ACTIVE_SCALES_FALLBACKS_BY_TF.items()
        }
        return cls(
            min_observations=int(cfg.get_sync("alpha.ic.min_observations", 500)),
            fdr_alpha=float(cfg.get_sync("alpha.ic.fdr_alpha", 0.05)),
            walk_forward_folds=int(cfg.get_sync("alpha.ic.walk_forward_folds", 3)),
            sharpe_window_size=int(cfg.get_sync("alpha.ic.sharpe_window_size", 2000)),
            sharpe_window_size_subsampled=int(
                cfg.get_sync("alpha.ic.sharpe_window_size_subsampled", 100)
            ),
            sharpe_min_windows=int(cfg.get_sync("alpha.ic.sharpe_min_windows", 10)),
            subsample_min_stride=int(cfg.get_sync("alpha.ic.subsample_min_stride", 5)),
            min_reliable_n=int(cfg.get_sync("alpha.ic.min_reliable_n", 100)),
            cluster_max_corr=float(cfg.get_sync("alpha.ic.cluster_max_corr", 0.70)),
            lookahead_fast=_lookahead_by_scale["fast"],
            lookahead_mid=_lookahead_by_scale["mid"],
            lookahead_slow=_lookahead_by_scale["slow"],
            lookahead_extended=_lookahead_by_scale["extended"],
            active_scales=active_scales,
            # Cross-sectional equity regime model flag (migration 174)
            equity_model_enabled=str(
                cfg.get_sync("alpha.regime.equity_model_enabled", "true")
            ).lower()
            == "true",
            # Newey-West HAC max lag for IC Sharpe autocorrelation correction (migration 177).
            # K=0 disables HAC (ic_sharpe_hac == ic_sharpe).
            hac_max_lag=int(cfg.get_sync("alpha.ic.hac_max_lag", 3)),
            # Cross-sectional timestamp chunk size (migration 183).
            cs_chunk_ts=int(cfg.get_sync("infra.ic_engine.cs_chunk_ts", 5000)),
            # Per-symbol feature-vector server-side cursor batch size (migration 212).
            symbol_fetch_chunk_rows=int(
                cfg.get_sync("infra.ic_engine.symbol_fetch_chunk_rows", 5000)
            ),
            # Worker pool size (override via --workers CLI flag).
            n_workers=int(cfg.get_sync("infra.ic_engine.workers", 1)),
            # todo 216: BLAS thread cap, see make_worker_pool()/limit_blas_threads().
            blas_threads_per_worker=int(cfg.get_sync("infra.blas_threads_per_worker", 1)),
            # Phase 143 Plan 03: post-run lifecycle hook (LIFECYCLE-03/04/05).
            # Reused APR keys (migration 161/172) -- not new, so demotion and the
            # ensemble's own inclusion gate share one threshold and can't drift apart.
            decay_materiality_threshold=float(
                cfg.get_sync("alpha.decay.materiality_threshold", 0.005)
            ),
            # Todo 144: stratified regime-shift guard rails (migration 237).
            guard_fail_rate_max=float(cfg.get_sync("alpha.decay.guard_fail_rate_max", 0.995)),
            guard_fail_rate_min=float(cfg.get_sync("alpha.decay.guard_fail_rate_min", 0.85)),
            guard_band_z=float(cfg.get_sync("alpha.decay.guard_band_z", 3.0)),
            guard_min_cells=int(cfg.get_sync("alpha.decay.guard_min_cells", 100)),
            guard_min_history=int(cfg.get_sync("alpha.decay.guard_min_history", 8)),
            guard_history_window=int(cfg.get_sync("alpha.decay.guard_history_window", 20)),
            decay_recovery_min_observations=int(
                cfg.get_sync("alpha.decay.recovery_min_observations", 2000)
            ),
            decay_recovery_min_passes=int(cfg.get_sync("alpha.decay.recovery_min_passes", 2)),
            demotion_min_consecutive=int(cfg.get_sync("alpha.decay.demotion_min_consecutive", 2)),
            meta_fdr_min_fraction=float(cfg.get_sync("alpha.ensemble.meta_fdr_min_fraction", 0.50)),
            # New key (migration 219).
            ic_staleness_alert_days=int(cfg.get_sync("alpha.ic.staleness_alert_days", 5)),
            # Fable N4 -- same key ensemble_trainer defaults to absent a CLI override.
            ensemble_weight_version=str(cfg.get_sync("alpha.ensemble.weight_version", "v1")),
            # Circular block bootstrap CI (migrations 161/165/177; reactivated migration 222).
            bootstrap_resamples=int(cfg.get_sync("alpha.ic.bootstrap_resamples", 2000)),
            bootstrap_seed=int(cfg.get_sync("alpha.ic.bootstrap_seed", 42)),
            # Todo 227 (migration 298): adaptive bootstrap early-stop, off by default.
            bootstrap_early_stop_enabled=bool(
                cfg.get_sync("alpha.ic.bootstrap_early_stop.enabled", False)
            ),
            bootstrap_early_stop_check_interval=int(
                cfg.get_sync("alpha.ic.bootstrap_early_stop.check_interval", 200)
            ),
            bootstrap_early_stop_tol=float(
                cfg.get_sync("alpha.ic.bootstrap_early_stop.tol", 0.002)
            ),
            bootstrap_early_stop_min_resamples=int(
                cfg.get_sync("alpha.ic.bootstrap_early_stop.min_resamples", 200)
            ),
            bootstrap_early_stop_stable_checks=int(
                cfg.get_sync("alpha.ic.bootstrap_early_stop.stable_checks", 2)
            ),
            bootstrap_block_size=_load_per_tf_apr_dict(
                cfg,
                "alpha.ic.bootstrap_block_size",
                {"5m": 78, "15m": 26, "1h": 10, "1d": 10},
            ),
            # Phase 143.1-04 (Component E, todo 094). Same APR key ensemble_trainer.py
            # reads -- one flag, two consumers, so the champion/challenger switch can't
            # drift between eligibility and the lifecycle hook's demote predicate.
            sign_symmetric=bool(cfg.get_sync("alpha.ensemble.sign_symmetric", False)),
            # Phase 151 Plan 02 (migration 286). Same read idiom as sign_symmetric
            # directly above -- resolved once here, never re-read inside a per-cell loop.
            cluster_regime_conditioned=bool(
                cfg.get_sync("alpha.ensemble.cluster_regime_conditioned", True)
            ),
            regime_groups_json=regime_groups_json,
            # Todo 133 (162-02 Task 1, migration 250): per-tf dict, mirrors
            # bootstrap_block_size above. Old scalar key
            # (infra.ic_engine.cross_sectional_bootstrap_threads) retired.
            cross_sectional_bootstrap_threads=_load_per_tf_apr_dict(
                cfg,
                "alpha.ic.cross_sectional_bootstrap_threads",
                {"5m": 6, "15m": 1, "1h": 1, "1d": 1},
            ),
            # Todo 215, migration 273.
            per_symbol_bootstrap_threads=_load_per_tf_apr_dict(
                cfg,
                "infra.ic_engine.per_symbol_bootstrap_threads",
                {"5m": 1, "15m": 1, "1h": 1, "1d": 1},
            ),
            # 162-01 Task 3 (todos 139/140, migration 249).
            feature_block_columns=int(cfg.get_sync("alpha.ic.feature_block_columns", 32)),
            max_cell_rows=int(cfg.get_sync("alpha.ic.max_cell_rows", 1_200_000)),
            # 162-04 Task 2 (todo 134 follow-on, migration 252). Forward-looking,
            # unused until a drift study justifies a nonzero value -- see the
            # dataclass field's own comment above.
            refresh_min_new_fraction=float(cfg.get_sync("alpha.ic.refresh_min_new_fraction", 0.0)),
        )


# ---------------------------------------------------------------------------
# ICEngineConfig field classification (162-03 Task 1, todos 134/122)
#
# Every ICEngineConfig field is classified as either COMPUTATIONAL (a change moves
# the IC VALUES written to feature_ic_scores -- must invalidate the fingerprint) or
# OPERATIONAL (throughput/observability/post-run-lifecycle-only -- must never
# invalidate the fingerprint, or every operator tuning a thread count would trigger
# a full, wasted corpus recompute). The classification test below (see
# test_ic_engine_fingerprint.py) asserts these two sets PARTITION
# dataclasses.fields(ICEngineConfig) exactly -- any field present on the dataclass
# but classified in neither set fails that test loudly, so a future field addition
# can never silently skip fingerprint classification.
# ---------------------------------------------------------------------------

_COMPUTATIONAL_CONFIG_FIELDS: frozenset[str] = frozenset(
    {
        "min_observations",  # min-sample-size gate -- moves n_independent/reliable
        "fdr_alpha",  # BH-FDR threshold -- moves passes_fdr
        "walk_forward_folds",  # fold count -- moves wf_fold_count/wf_pass_count
        "sharpe_min_windows",  # ic_sharpe reliability gate
        "subsample_min_stride",  # subsampling stride -- moves which rows are observed
        "min_reliable_n",  # reliability gate on n_valid
        "cluster_max_corr",  # feature-clustering cutoff -- moves cluster_id/BH-FDR reps
        "lookahead_fast",  # forward-return horizon
        "lookahead_mid",  # forward-return horizon
        "lookahead_slow",  # forward-return horizon
        "lookahead_extended",  # forward-return horizon
        # Which scales are attempted at all for a tf (2026-07-30 design) -- excluding
        # a scale changes which feature_ic_scores rows get written, same class of
        # change as the lookahead bar-count values themselves.
        "active_scales",
        # Changes which regime label SOURCE (market_regimes vs
        # feature_vectors.regime_volatility) feeds every non-pooled row's
        # regime/regime_scope columns -- see _compute_symbol_tf's mr_dict docstring.
        "equity_model_enabled",
        "hac_max_lag",  # Newey-West HAC lag -- moves ic_sharpe_hac
        "bootstrap_resamples",  # circular block bootstrap CI resample count
        # RNG seed for the circular block bootstrap -- APR-mandate "Seeds that affect
        # algorithm output" category; changing it re-draws every CI, not just reruns.
        "bootstrap_seed",
        "bootstrap_block_size",  # per-tf block size -- moves the bootstrap CI values
        # Todo 227 (2026-08-05): when enabled, stops the bootstrap resample loop
        # early once the CI estimate stabilizes -- moves ci_lower/ci_upper (an
        # approximation of the fixed-bootstrap_resamples value), unlike the
        # thread-count fields below which are output-invariant by construction.
        # All 5 fields classified COMPUTATIONAL together: enabled is the gate,
        # the other 4 all shape WHEN/whether it stops early, i.e. WHAT gets
        # computed, not just how fast.
        "bootstrap_early_stop_enabled",
        "bootstrap_early_stop_check_interval",
        "bootstrap_early_stop_tol",
        "bootstrap_early_stop_min_resamples",
        "bootstrap_early_stop_stable_checks",
        # Conservative: currently gates ONLY the post-run lifecycle-hook demote/
        # material/worst_cell predicates (see ic_engine.py:798's docstring), not the
        # feature_ic_scores rows written by this file today. Classified COMPUTATIONAL
        # anyway (not OPERATIONAL) as a deliberate safety margin against future
        # coupling into the measurement path itself -- costs at most one extra safe
        # recompute, never a silent-stale read.
        "sign_symmetric",
        # Determines enabled_groups -> symbol_regime_class routing -> which symbols
        # feed which cross-sectional cell and which regime labels a per-symbol row
        # gets -- a routing change moves real rows, not just downstream policy.
        "regime_groups_json",
        # Widens the symbol_hmm regime_passes gate (see the field's own dataclass
        # comment) -- toggling it changes WHICH feature_ic_scores rows exist
        # (new regime_scope='symbol_hmm' rows appear/disappear), the same class of
        # routing change as regime_groups_json directly above.
        "cluster_regime_conditioned",
        "sharpe_window_size_subsampled",  # fixed subsampled-bar window -- moves ic_sharpe
        # 162-04 Task 2: currently UNUSED (0=disabled, no read path). Classified
        # COMPUTATIONAL as a deliberate conservative safety margin (same reasoning as
        # sign_symmetric above) -- once wired, a nonzero value changes WHICH rows get
        # carried-forward vs recomputed, moving feature_ic_scores content directly.
        # Costs at most one extra safe recompute today (value never changes from the
        # migration 252 seed), never a silent-stale read once carry-forward ships.
        "refresh_min_new_fraction",
    }
)

_OPERATIONAL_CONFIG_FIELDS: frozenset[str] = frozenset(
    {
        # Vestigial: no longer read by ic_math.py (superseded by
        # sharpe_window_size_subsampled, todo 096) -- kept bound only for APR
        # provenance continuity, per the dataclass's own field comment.
        "sharpe_window_size",
        "cs_chunk_ts",  # cross-sectional fetch chunk size -- pure throughput knob
        "symbol_fetch_chunk_rows",  # per-symbol fetch chunk size -- pure throughput knob
        "n_workers",  # ProcessPoolExecutor pool size -- pure throughput knob
        # Per-worker BLAS thread cap (todo 216) -- empirically verified OPERATIONAL, not
        # assumed. See limit_blas_threads()'s docstring in _batch_utils.py for the test.
        "blas_threads_per_worker",
        # Post-run lifecycle hook (_apply_feature_transitions/_run_lifecycle_hook)
        # ONLY -- operates on concept_registry/ensemble decisions AFTER
        # feature_ic_scores rows are already written; never affects the rows
        # themselves. Verified via grep: only referenced inside those two functions.
        "decay_materiality_threshold",
        "guard_fail_rate_max",  # lifecycle hook only (regime-shift guard rail)
        "guard_fail_rate_min",  # lifecycle hook only (regime-shift guard rail)
        "guard_band_z",  # lifecycle hook only (regime-shift guard rail)
        "guard_min_cells",  # lifecycle hook only (regime-shift guard rail)
        "guard_min_history",  # lifecycle hook only (regime-shift guard rail)
        "guard_history_window",  # lifecycle hook only (regime-shift guard rail)
        "decay_recovery_min_observations",  # lifecycle hook only
        "decay_recovery_min_passes",  # lifecycle hook only
        "demotion_min_consecutive",  # lifecycle hook only (todo 323 demotion hysteresis)
        "meta_fdr_min_fraction",  # lifecycle hook only (demotion floor)
        "ic_staleness_alert_days",  # observability/alerting threshold only
        "ensemble_weight_version",  # pins lifecycle hook's standing-weight JOIN only
        # Thread count changes wall time only, never output -- guaranteed
        # structurally by 162-01's precomputed resample-index matrix (starts_matrix,
        # drawn once per scale before the feature-block loop). Explicitly OPERATIONAL
        # per this plan's own directive.
        "cross_sectional_bootstrap_threads",
        # Same reasoning as cross_sectional_bootstrap_threads directly above -- todo 215.
        "per_symbol_bootstrap_threads",
        # Memory-layout chunk size only -- bit-identical by construction (162-01
        # SUMMARY: synthetic feature-blocked-vs-unblocked equivalence verified).
        "feature_block_columns",
        # Crash-loud row-count ceiling -- under the ceiling, output is unaffected;
        # over it, the run raises CellTooLargeError rather than silently degrading.
        "max_cell_rows",
    }
)


def _compute_apr_snapshot_key(config: ICEngineConfig) -> str:
    """BaseBatch.content_key() over sorted COMPUTATIONAL-only ICEngineConfig fields.

    Only fields in _COMPUTATIONAL_CONFIG_FIELDS ever move this key -- an OPERATIONAL
    field (thread counts, chunk sizes, throughput knobs, lifecycle-hook-only
    thresholds) changing must NEVER invalidate a fingerprint-valid cell. Dict-valued
    fields (bootstrap_block_size) are serialized as a sorted, stable "k=v,k=v" join
    so key insertion order can never affect the hash.
    """
    parts: list[str] = []
    for field_name in sorted(_COMPUTATIONAL_CONFIG_FIELDS):
        value = getattr(config, field_name)
        if isinstance(value, dict):
            value_str = ",".join(f"{k}={value[k]}" for k in sorted(value))
        else:
            value_str = str(value)
        parts.append(f"{field_name}={value_str}")
    return BaseBatch.content_key(*parts)


def _check_cell_size(n_rows: int, config: ICEngineConfig, context_label: str) -> None:
    """Crash-loud row-count ceiling (162-01 Task 3, todo 140) -- fails loud rather
    than silently routing an oversized cell to an alternate/degraded algorithm.
    Shared by the per-symbol and cross-sectional cell computes (162 simplify-pass;
    previously this exact check was copy-pasted at both call sites).
    """
    if config.max_cell_rows and n_rows > config.max_cell_rows:
        raise CellTooLargeError(
            f"{context_label} has {n_rows} rows, exceeding "
            f"alpha.ic.max_cell_rows={config.max_cell_rows}."
        )


# ---------------------------------------------------------------------------
# Per-table upstream watermark (162-03 Task 2, resolves RESEARCH Open Question #1)
#
# A naive MAX(bar_ts)/COUNT(*) watermark is blind to an in-place VALUE mutation
# (price-sanity correction, HMM relabel, concept_registry status transition) that
# changes zero rows and zero timestamps -- exactly the failure class this function
# exists to catch. Every component below is either a write-timestamp column that
# bumps on correction (forward_returns.computed_at) or a content hash over the
# actual values (market_regimes/instrument_tags/concept_registry), never bar_ts/
# COUNT alone.
# ---------------------------------------------------------------------------


def _watermark_concept_registry(conn: Any) -> dict[str, Any]:
    """(e) concept_registry (domain='feature') status hash -- run-invariant,
    applies to EVERY pass_type (every row type -- pooled/symbol_hmm/cross_sectional
    -- writes feature_status_at_eval from this same snapshot).

    Takes no cell-scoped input, so compute this exactly ONCE per ic_engine.py
    invocation and pass the result into every cell's watermark (162 simplify-pass --
    previously recomputed on every single per-cell call, up to ~700+ identical
    round trips for a full corpus run).

    Phase 170 Plan 06: repointed from feature_registry to concept_registry
    (domain='feature'). The md5 INPUT STRING keeps the exact same shape
    (`name || '=' || status ORDER BY name`, formerly `feature_name || '=' ||
    status ORDER BY feature_name`) so that, with both registries in sync, the
    hash VALUE is byte-identical to before the repoint -- see
    _fingerprint_computational_key's docstring for why that identity matters.

    JOINs concept_gate (like ConceptRegistryService's own _LOAD_CONCEPTS_SYNC_SQL)
    rather than filtering on domain='feature' alone: migration 284 seeded 2
    TOMBSTONE concept_registry rows (metadata->>'migrated_from' =
    'feature_transition_log') for orphaned feature_transition_log history whose
    feature_name no longer exists in feature_registry -- these carry no
    concept_gate row by design (284's header, "ORPHANED TRANSITION-LOG ROWS").
    An unscoped domain='feature' count is 251 (249 real + 2 tombstones), which
    would never match feature_registry's 249 and would permanently fail this
    plan's own byte-identical-hash acceptance criterion, plus make the alignment
    gate below raise on every single run. The INNER JOIN naturally excludes them,
    matching ConceptRegistryService's own semantics exactly (verified live,
    2026-08-04: both hashes equal 4fadbe90ab6050fa12e7f25196f32b28 with this join).
    """
    with conn.cursor() as cur:
        cur.execute(
            "SELECT md5(COALESCE(string_agg("
            "cr.name || '=' || cr.status, '' ORDER BY cr.name), '')) "
            "FROM concept_registry cr JOIN concept_gate cg USING (concept_id) "
            "WHERE cr.domain = 'feature'"
        )
        (status_hash,) = cur.fetchone()
    return {"status_hash": status_hash}


def _watermark_forward_returns_feature_vectors(
    conn: Any, symbols: list[str], tf: str
) -> dict[str, Any]:
    """(a) forward_returns + (b) feature_vectors -- scoped to (symbols, tf) only,
    NOT pass_type.

    Callers should cache the result per (symbol-or-regime_group, tf) pair (162
    simplify-pass) -- pooled/symbol_hmm/cross_sectional (plus an optional dual-write
    symbol_hmm) share the same symbol+tf and previously recomputed these two
    identical queries once per pass_type.
    """
    watermark: dict[str, Any] = {}
    with conn.cursor() as cur:
        # (a) forward_returns -- the label side, PRIMARY in-place-mutation detector.
        # computed_at is DEFAULT now() and bumps on every recompute, so a bar-level
        # correction (which recomputes forward_returns) moves it even when
        # bar_ts/count are unchanged.
        cur.execute(
            """
            SELECT MAX(bar_ts), COUNT(*), MAX(computed_at)
            FROM forward_returns
            WHERE symbol = ANY(%(symbols)s) AND tf = %(tf)s
              AND return_type = 'executable_open_to_open'
            """,
            {"symbols": symbols, "tf": tf},
        )
        max_bar_ts, fr_count, max_computed_at = cur.fetchone()
        watermark["forward_returns"] = {
            "max_bar_ts": format_iso_ts(max_bar_ts) if max_bar_ts else None,
            "count": fr_count,
            "max_computed_at": format_iso_ts(max_computed_at) if max_computed_at else None,
        }

        # (b) feature_vectors -- the feature side, no write-timestamp column.
        # In-place feature mutations are covered TRANSITIVELY: a feature-code change
        # moves code_content_key; a bar correction recomputes forward_returns
        # (caught by (a), since the correction workflow recomputes both from the
        # same corrected bars).
        cur.execute(
            "SELECT MAX(bar_ts), COUNT(*) FROM feature_vectors "
            "WHERE symbol = ANY(%(symbols)s) AND tf = %(tf)s",
            {"symbols": symbols, "tf": tf},
        )
        max_fv_bar_ts, fv_count = cur.fetchone()
        watermark["feature_vectors"] = {
            "max_bar_ts": format_iso_ts(max_fv_bar_ts) if max_fv_bar_ts else None,
            "count": fv_count,
        }
    return watermark


def _watermark_market_regimes_instrument_tags(
    conn: Any, regime_group: str | None, tf: str, symbol_list: list[str] | None
) -> dict[str, Any]:
    """(c) market_regimes + (d) instrument_tags -- scoped to (regime_group, tf) and
    symbol_list only, NOT regime_label.

    Callers should cache per (regime_group, tf) (162 simplify-pass) -- every
    regime_label within a group shares the same (regime_group, tf) and previously
    recomputed these two identical queries once per regime_label.
    """
    watermark: dict[str, Any] = {}
    with conn.cursor() as cur:
        # (c) market_regimes -- an HMM relabel mutates `regime_label` in place with
        # unchanged ts/count, so add a value-sensitive content hash. Column is
        # `regime_label` (not `regime` -- 162-04 live-DB fix, confirmed via `\d
        # market_regimes`; the plan's own main() code at the cs_regimes discovery
        # site already reads regime_label correctly, only this watermark query had
        # the wrong column name).
        cur.execute(
            """
            SELECT MAX(ts), COUNT(*),
                   md5(COALESCE(string_agg(regime_label, '' ORDER BY ts), ''))
            FROM market_regimes
            WHERE regime_group = %(regime_group)s AND tf = %(tf)s
            """,
            {"regime_group": regime_group, "tf": tf},
        )
        max_ts, mr_count, regime_hash = cur.fetchone()
        watermark["market_regimes"] = {
            "max_ts": format_iso_ts(max_ts) if max_ts else None,
            "count": mr_count,
            "regime_hash": regime_hash,
        }

        # (d) instrument_tags -- cross-sectional routing. Catches any tag add/
        # remove/reweight across this regime_group's peer set that changes
        # which symbols are pooled into the cell.
        cur.execute(
            """
            SELECT md5(COALESCE(string_agg(
                symbol || E'\t' || tag || E'\t' || source || E'\t' || weight::text,
                '' ORDER BY symbol, tag
            ), ''))
            FROM instrument_tags
            WHERE symbol = ANY(%(symbols)s)
            """,
            {"symbols": symbol_list},
        )
        (tags_hash,) = cur.fetchone()
        watermark["instrument_tags"] = {"tags_hash": tags_hash}
    return watermark


def _compute_upstream_watermark(
    conn: Any,
    symbol: str | None,
    tf: str,
    *,
    is_group_pooled: bool = False,
    regime_group: str | None = None,
    symbol_list: list[str] | None = None,
    concept_registry_watermark: dict[str, Any] | None = None,
    fr_fv_cache: dict[tuple[str | None, str], dict[str, Any]] | None = None,
    mr_tags_cache: dict[tuple[str | None, str], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """JSON-serializable per-cell upstream watermark.

    Deliberately takes no pass_type parameter (162 code-review CR-01 fix): the
    caller's pass_type string ('pooled'/'symbol_hmm'/'cross_sectional') used to
    decide is_cross_sectional here, which meant the per-symbol prepass loop's
    'cross_sectional' cells (a regime-group-routed symbol's OWN row, symbol=<real
    symbol>, NOT the group-pooled cell) silently computed their watermark against
    symbol_list=None/regime_group=None instead of [symbol] -- permanently
    defeating invalidation for every regime-group-routed symbol. is_group_pooled
    now fully determines behavior; a caller cannot reintroduce that bug by
    passing the "wrong" pass_type, because this function never sees it.

    is_group_pooled=False (default, ALL per-symbol rows regardless of pass_type):
    components (a) forward_returns and (b) feature_vectors are scoped to that one
    symbol.

    is_group_pooled=True (ONLY the cs_cell_plan/group-level POOLED cell computed
    once per (regime_group, tf, regime_label)): there is no single instrument
    symbol -- symbol_list carries regime_group's whole peer set, and components
    (a)/(b) aggregate across it (Rule 2 addition beyond the plan's literal 4-arg
    sketch: without this, an in-place correction to a PEER symbol's
    forward_returns/feature_vectors would silently fail to invalidate a cross-
    sectional cell -- T-162-03-01, the phase's highest-severity threat).
    Components (c) market_regimes and (d) instrument_tags additionally apply,
    keyed by regime_group and symbol_list respectively.

    (e) concept_registry (domain='feature') status applies to EVERY row type --
    every row (pooled/symbol_hmm/cross_sectional, per-symbol or group-pooled)
    writes feature_status_at_eval from the same registry snapshot.

    Timestamps serialized via format_iso_ts() (never inline .isoformat()). Does
    NOT log -- callers accumulate a counter across all per-cell calls and log
    ONCE per run (corpus-loop logging rule, CLAUDE.md).

    Caching (162 simplify-pass): concept_registry_watermark is run-invariant --
    pass it in precomputed once (via _watermark_concept_registry) rather than
    letting this function requery it per cell. fr_fv_cache/mr_tags_cache are
    optional caller-owned memoization dicts keyed by ((symbol-or-regime_group), tf);
    when provided, this function populates them on first computation for a given
    key and reuses the stored value on every subsequent call for that same key --
    the output dict is identical either way, just computed with fewer round trips.
    """
    if is_group_pooled:
        assert symbol is None and regime_group is not None, (
            "is_group_pooled=True requires symbol=None and a real regime_group -- "
            "the group-pooled cell has no single instrument symbol"
        )
    else:
        assert symbol is not None, (
            "is_group_pooled=False requires a real symbol -- every per-symbol row "
            "is scoped to exactly one symbol regardless of its pass_type"
        )

    symbols_for_fr_fv = symbol_list if is_group_pooled else [symbol]

    watermark: dict[str, Any] = {}

    fr_fv_key = (regime_group if is_group_pooled else symbol, tf)
    if fr_fv_cache is not None and fr_fv_key in fr_fv_cache:
        watermark.update(fr_fv_cache[fr_fv_key])
    else:
        fr_fv = _watermark_forward_returns_feature_vectors(conn, symbols_for_fr_fv, tf)
        if fr_fv_cache is not None:
            fr_fv_cache[fr_fv_key] = fr_fv
        watermark.update(fr_fv)

    if is_group_pooled:
        mr_tags_key = (regime_group, tf)
        if mr_tags_cache is not None and mr_tags_key in mr_tags_cache:
            watermark.update(mr_tags_cache[mr_tags_key])
        else:
            mr_tags = _watermark_market_regimes_instrument_tags(conn, regime_group, tf, symbol_list)
            if mr_tags_cache is not None:
                mr_tags_cache[mr_tags_key] = mr_tags
            watermark.update(mr_tags)

    watermark["concept_registry"] = (
        concept_registry_watermark
        if concept_registry_watermark is not None
        else _watermark_concept_registry(conn)
    )

    return watermark


# ---------------------------------------------------------------------------
# Whole-cell fingerprint validity + invalidation (162-03 Task 3, todos 134/122)
# ---------------------------------------------------------------------------


def _fingerprint_is_valid(stored: dict[str, Any] | None, current: dict[str, Any]) -> bool:
    """True only when code_content_key AND apr_snapshot_key AND upstream_watermark
    ALL match -- a partial match is a full miss (crash-loud-not-silently-partial).
    """
    if stored is None:
        return False
    return (
        stored.get("code_content_key") == current.get("code_content_key")
        and stored.get("apr_snapshot_key") == current.get("apr_snapshot_key")
        and stored.get("upstream_watermark") == current.get("upstream_watermark")
    )


# Phase 170 Plan 06: _fingerprint_computational_key must drop BOTH the pre-cutover
# ("feature_registry") and post-cutover ("concept_registry") watermark key names,
# not just the new one. A stored ic_cell_fingerprints row written by yesterday's
# (pre-Plan-06) code carries "feature_registry" in its upstream_watermark; the very
# next run's freshly-computed fingerprint carries "concept_registry" instead. If the
# filter only dropped "concept_registry", the OLD stored row's "feature_registry"
# entry would survive filtering while the NEW current fingerprint's watermark would
# not have a corresponding entry to compare it against -- a spurious computational-key
# mismatch on literally every cell in the corpus on the first post-cutover run, i.e.
# exactly the ~70h recompute this whole plan exists to avoid. Dropping both names
# keeps stored (old key) and current (new key) fingerprints computationally equal
# through the transition, and is a permanent no-op once every stored row has been
# refreshed to the new key (see test_computational_key_unchanged_by_registry_key_rename).
_LEGACY_REGISTRY_WATERMARK_KEYS = frozenset({"feature_registry", "concept_registry"})


def _fingerprint_computational_key(fp: dict[str, Any]) -> dict[str, Any]:
    """The subset of a fingerprint that gates whether the expensive bootstrap-CI
    compute must rerun -- upstream_watermark minus its registry-status component.

    concept_registry.status_hash never changes WHAT gets computed: ic_engine's
    per-cell compute always calls get_all_concepts(), never a status-filtered
    accessor (see main()'s registry-drift gate), so every feature is
    bootstrap-CI'd regardless of status. status only feeds the
    feature_status_at_eval provenance column on each row -- treating a
    status-hash change as computationally invalidating (2026-07-29
    rca_analysis, todo 198) forces a full multi-hour recompute for an edit
    that alters zero computed IC/CI value.

    NOTE (2026-07-29 code review): status_hash also moves on registry MEMBERSHIP
    changes (feature added/removed/renamed), which DOES change computed output --
    excluding it here is safe only because main()'s alignment gate forces
    concept_registry(domain='feature') membership to equal FeatureVector's
    fields exactly, so a real membership change requires a FeatureVector edit
    that moves code_content_key instead. If that gate is ever relaxed, this
    function must be revisited to track membership separately from status.

    Phase 170 Plan 06: watermark dict key renamed "feature_registry" ->
    "concept_registry" (_compute_upstream_watermark). This function filters out
    BOTH names via _LEGACY_REGISTRY_WATERMARK_KEYS -- see that constant's
    docstring for why a single-name filter would spuriously invalidate every
    cell on the first post-cutover run.
    """
    watermark = fp.get("upstream_watermark") or {}
    return {
        "code_content_key": fp.get("code_content_key"),
        "apr_snapshot_key": fp.get("apr_snapshot_key"),
        "upstream_watermark": {
            k: v for k, v in watermark.items() if k not in _LEGACY_REGISTRY_WATERMARK_KEYS
        },
    }


def _fingerprint_is_computationally_valid(
    stored: dict[str, Any] | None, current: dict[str, Any]
) -> bool:
    """True when everything that can actually move a computed IC/CI value
    matches -- ignores concept_registry.status_hash (see
    _fingerprint_computational_key). A cell valid here but not under
    _fingerprint_is_valid is status-only-stale: safe to skip the expensive
    compute, but its feature_status_at_eval provenance needs a cheap refresh
    (_fingerprint_is_status_only_stale, _FEATURE_STATUS_REFRESH_SQL).
    """
    if stored is None:
        return False
    return _fingerprint_computational_key(stored) == _fingerprint_computational_key(current)


def _fingerprint_is_status_only_stale(
    stored: dict[str, Any] | None, current: dict[str, Any]
) -> bool:
    """True iff the cell's expensive compute is reusable but its
    feature_status_at_eval provenance is stale -- computationally valid AND
    NOT fully valid. False on a never-computed cell (stored=None): that must
    take the full compute path, not a metadata-only refresh of rows that don't
    exist. False when computationally invalid too: that's a full recompute,
    which already rewrites feature_status_at_eval as a side effect -- a
    separate refresh there would be redundant, and if ordered wrong relative
    to the recompute, could clobber it.
    """
    return _fingerprint_is_computationally_valid(stored, current) and not _fingerprint_is_valid(
        stored, current
    )


_FingerprintClassification = Literal["valid", "status_only_stale", "invalid"]


def _classify_fingerprint(
    stored: dict[str, Any] | None, current: dict[str, Any], *, force_refresh: bool
) -> _FingerprintClassification:
    """The one decision function shared by both the per-symbol and cross-
    sectional prepass loops (2026-07-29 rca_analysis, todo 198) -- both call
    this instead of independently re-deriving valid/stale/invalid, so the two
    passes structurally cannot diverge in what counts as which.

    force_refresh (the --refresh CLI flag) always forces "invalid", matching
    the pre-existing args.refresh semantics unchanged: an explicit refresh
    request means redo everything, not just a status-only metadata touch-up.
    """
    if force_refresh or not _fingerprint_is_computationally_valid(stored, current):
        return "invalid"
    return "status_only_stale" if _fingerprint_is_status_only_stale(stored, current) else "valid"


def _partition_symbol_cells(
    cell_classifications: dict[tuple[str, str], _FingerprintClassification],
) -> tuple[list[tuple[str, str]], bool]:
    """Aggregates one symbol's per-cell _classify_fingerprint results into
    (invalid_cells, needs_status_refresh) -- TWO INDEPENDENT values, never an
    either/or bucket (2026-07-29 code review regression, todo 198).

    The bug this replaced: the original wiring used a single elif to bucket a
    symbol as EITHER dispatched (has an invalid cell) OR needing a status
    refresh (no invalid cell, but a status_only_stale one) -- never both. A
    symbol with an invalid cell in one (tf, pass_type) AND a status_only_stale
    cell in a DIFFERENT (tf, pass_type) got dispatched (correctly, for the
    invalid cell) but its status_only_stale sibling was silently never
    refreshed: the dispatched worker's redundant recompute of that
    fingerprint-valid sibling hits feature_ic_scores' ON CONFLICT ... DO
    NOTHING (T-162-03-06 -- deliberately harmless pre-todo-190, since a
    fingerprint-valid sibling's recomputed row was always byte-identical to
    what's already there), which now silently discards the fresh
    feature_status_at_eval, while the post-compute fingerprint upsert (which
    covers ALL of a dispatched symbol's cells, unconditionally -- see the
    "UPSERT fingerprint rows for ALL of this symbol's expected cells" comment
    below) stamps that cell's fingerprint fresh anyway. Net effect: permanent,
    silent status drift, never detected or corrected on any future run --
    exactly the "silent wrong answer" failure mode this project treats as
    worse than a loud crash.

    dispatch is `bool(invalid_cells)`, independent of needs_status_refresh --
    callers must act on both, not chain them as if/elif.
    """
    invalid_cells = [
        cell_key for cell_key, result in cell_classifications.items() if result == "invalid"
    ]
    needs_status_refresh = any(
        result == "status_only_stale" for result in cell_classifications.values()
    )
    return invalid_cells, needs_status_refresh


# Scoped to the exact ic_cell_fingerprints PK columns (symbol, tf, pass_type via
# regime_scope, training_window_end) -- never a bare training_window_end filter,
# which would delete valid unrelated cells at the same window (T-162-03-03).
# Used for pass_type IN ('pooled', 'symbol_hmm'): symbol is the real instrument
# symbol; a 'symbol_hmm' cell writes multiple regime labels for that one (symbol,
# tf), all belonging to the same fingerprinted cell, so no regime filter is needed.
_FINGERPRINT_INVALIDATE_DELETE_SQL = """
    DELETE FROM feature_ic_scores
    WHERE symbol = %(symbol)s
      AND tf = %(tf)s
      AND regime_scope = %(pass_type)s
      AND training_window_end = %(training_window_end)s
"""

# Cross-sectional variant: feature_ic_scores.symbol is always the 'POOLED' sentinel
# for cross-sectional rows (regime_group identity is NOT a column there -- see
# migration 251's header), and the fingerprint's own per-(regime_group, regime_label)
# grain requires an explicit regime filter to avoid deleting a sibling regime_label's
# valid rows at the same (tf, regime_scope, training_window_end).
_FINGERPRINT_INVALIDATE_DELETE_CROSS_SECTIONAL_SQL = """
    DELETE FROM feature_ic_scores
    WHERE symbol = %(symbol)s
      AND tf = %(tf)s
      AND regime_scope = 'cross_sectional'
      AND regime = %(regime_label)s
      AND training_window_end = %(training_window_end)s
"""

# Todo 252: archive-before-delete -- run immediately before each DELETE above, in the SAME
# transaction/connection, so archive-and-delete are atomic (a crash between the two can only
# ever leave the pre-delete row still in feature_ic_scores, never a silently-lost row with
# nothing archived). Column list is explicit (not SELECT *) so a future feature_ic_scores
# ALTER TABLE fails loudly here rather than silently misaligning the two tables' columns.
#
# fp.symbol is bound as a SEPARATE parameter (%(fp_symbol)s) from feature_ic_scores.symbol
# (%(symbol)s) because ic_cell_fingerprints and feature_ic_scores use DIFFERENT symbol-key
# conventions for cross-sectional cells: feature_ic_scores.symbol is always the 'POOLED'
# sentinel there, while ic_cell_fingerprints.symbol is the real per-cell key
# f"{group_name}:{regime_label}" (see cs_symbol_key at the cross-sectional call site) -- a
# naive same-column JOIN would silently miss every cross-sectional fingerprint. For the
# per-symbol variant the caller passes the same value for both params (the real instrument
# symbol matches on both tables there), so this generalizes cleanly to both call sites.
_ARCHIVE_BEFORE_DELETE_SQL = """
    INSERT INTO feature_ic_scores_history (
        feature_name, vector_domain, symbol, tf, regime, lookahead_bars, training_window_end,
        is_pooled, n_independent, reliable, ic_value, ic_sign, p_value, ic_ci_lower, ic_ci_upper,
        passes_ci_gate, bh_adjusted_p, passes_fdr, wf_fold_count, wf_pass_count, wf_ic_sharpe,
        passes_walkforward, ic_sharpe, ic_sharpe_n_windows, regime_label_source, computed_at,
        ic_sortino, ic_win_rate, cluster_id, feature_status_at_eval, ic_sharpe_hac, regime_scope,
        ic_shrunk, shrinkage_weight, partial_ic, partial_ic_p_value, partial_ic_n,
        passes_partial_fdr, sign_hit_rate, magnitude_conditional_ic, cumulative_e_value,
        archived_code_content_key, archived_apr_snapshot_key, archived_upstream_watermark
    )
    SELECT
        fis.feature_name, fis.vector_domain, fis.symbol, fis.tf, fis.regime, fis.lookahead_bars,
        fis.training_window_end, fis.is_pooled, fis.n_independent, fis.reliable, fis.ic_value,
        fis.ic_sign, fis.p_value, fis.ic_ci_lower, fis.ic_ci_upper, fis.passes_ci_gate,
        fis.bh_adjusted_p, fis.passes_fdr, fis.wf_fold_count, fis.wf_pass_count, fis.wf_ic_sharpe,
        fis.passes_walkforward, fis.ic_sharpe, fis.ic_sharpe_n_windows, fis.regime_label_source,
        fis.computed_at, fis.ic_sortino, fis.ic_win_rate, fis.cluster_id,
        fis.feature_status_at_eval, fis.ic_sharpe_hac, fis.regime_scope, fis.ic_shrunk,
        fis.shrinkage_weight, fis.partial_ic, fis.partial_ic_p_value, fis.partial_ic_n,
        fis.passes_partial_fdr, fis.sign_hit_rate, fis.magnitude_conditional_ic,
        fis.cumulative_e_value,
        fp.code_content_key, fp.apr_snapshot_key, fp.upstream_watermark
    FROM feature_ic_scores fis
    LEFT JOIN ic_cell_fingerprints fp
        ON fp.symbol = %(fp_symbol)s
       AND fp.tf = %(tf)s
       AND fp.pass_type = %(pass_type)s
       AND fp.training_window_end = %(training_window_end)s
    WHERE fis.symbol = %(symbol)s
      AND fis.tf = %(tf)s
      AND fis.regime_scope = %(pass_type)s
      AND fis.training_window_end = %(training_window_end)s
"""

# Cross-sectional variant of the archive step -- same shape as
# _FINGERPRINT_INVALIDATE_DELETE_CROSS_SECTIONAL_SQL, with the same explicit regime filter.
_ARCHIVE_BEFORE_DELETE_CROSS_SECTIONAL_SQL = """
    INSERT INTO feature_ic_scores_history (
        feature_name, vector_domain, symbol, tf, regime, lookahead_bars, training_window_end,
        is_pooled, n_independent, reliable, ic_value, ic_sign, p_value, ic_ci_lower, ic_ci_upper,
        passes_ci_gate, bh_adjusted_p, passes_fdr, wf_fold_count, wf_pass_count, wf_ic_sharpe,
        passes_walkforward, ic_sharpe, ic_sharpe_n_windows, regime_label_source, computed_at,
        ic_sortino, ic_win_rate, cluster_id, feature_status_at_eval, ic_sharpe_hac, regime_scope,
        ic_shrunk, shrinkage_weight, partial_ic, partial_ic_p_value, partial_ic_n,
        passes_partial_fdr, sign_hit_rate, magnitude_conditional_ic, cumulative_e_value,
        archived_code_content_key, archived_apr_snapshot_key, archived_upstream_watermark
    )
    SELECT
        fis.feature_name, fis.vector_domain, fis.symbol, fis.tf, fis.regime, fis.lookahead_bars,
        fis.training_window_end, fis.is_pooled, fis.n_independent, fis.reliable, fis.ic_value,
        fis.ic_sign, fis.p_value, fis.ic_ci_lower, fis.ic_ci_upper, fis.passes_ci_gate,
        fis.bh_adjusted_p, fis.passes_fdr, fis.wf_fold_count, fis.wf_pass_count, fis.wf_ic_sharpe,
        fis.passes_walkforward, fis.ic_sharpe, fis.ic_sharpe_n_windows, fis.regime_label_source,
        fis.computed_at, fis.ic_sortino, fis.ic_win_rate, fis.cluster_id,
        fis.feature_status_at_eval, fis.ic_sharpe_hac, fis.regime_scope, fis.ic_shrunk,
        fis.shrinkage_weight, fis.partial_ic, fis.partial_ic_p_value, fis.partial_ic_n,
        fis.passes_partial_fdr, fis.sign_hit_rate, fis.magnitude_conditional_ic,
        fis.cumulative_e_value,
        fp.code_content_key, fp.apr_snapshot_key, fp.upstream_watermark
    FROM feature_ic_scores fis
    LEFT JOIN ic_cell_fingerprints fp
        ON fp.symbol = %(fp_symbol)s
       AND fp.tf = %(tf)s
       AND fp.pass_type = 'cross_sectional'
       AND fp.training_window_end = %(training_window_end)s
    WHERE fis.symbol = %(symbol)s
      AND fis.tf = %(tf)s
      AND fis.regime_scope = 'cross_sectional'
      AND fis.regime = %(regime_label)s
      AND fis.training_window_end = %(training_window_end)s
"""

_FINGERPRINT_UPSERT_SQL = """
    INSERT INTO ic_cell_fingerprints (
        symbol, tf, pass_type, training_window_end,
        code_content_key, apr_snapshot_key, upstream_watermark, computed_at
    )
    VALUES (
        %(symbol)s, %(tf)s, %(pass_type)s, %(training_window_end)s,
        %(code_content_key)s, %(apr_snapshot_key)s, %(upstream_watermark)s, NOW()
    )
    ON CONFLICT (symbol, tf, pass_type, training_window_end) DO UPDATE SET
        code_content_key = EXCLUDED.code_content_key,
        apr_snapshot_key = EXCLUDED.apr_snapshot_key,
        upstream_watermark = EXCLUDED.upstream_watermark,
        computed_at = EXCLUDED.computed_at
"""

# Companion to _fingerprint_is_status_only_stale (todo 198): a cheap metadata-only
# refresh for cells whose expensive bootstrap-CI math is still valid but whose
# feature_status_at_eval provenance has drifted from a concept_registry status
# transition. IS DISTINCT FROM (not !=, which is NULL-unsafe) keeps this a no-op
# UPDATE on rows already current -- safe and cheap to run on every status-only-
# stale symbol/cell, not just the one whose status actually moved, since we only
# know the AGGREGATE status_hash changed, not which individual feature moved.
# Phase 170 Plan 06: repointed from feature_registry to concept_registry
# (domain='feature'), joined on name = feature_name. Also joins concept_gate
# (matching _watermark_concept_registry and ConceptRegistryService's own
# _LOAD_CONCEPTS_SYNC_SQL) to exclude migration 284's 2 gate-less tombstone
# rows -- belt-and-suspenders, since no feature_ic_scores row has ever named
# either tombstone feature (verified live, 2026-08-04), but this keeps every
# concept_registry(domain='feature') read in this file scoped identically.
_FEATURE_STATUS_REFRESH_SQL = """
    UPDATE feature_ic_scores fis
    SET feature_status_at_eval = cr.status
    FROM concept_registry cr
    JOIN concept_gate cg ON cg.concept_id = cr.concept_id
    WHERE cr.domain = 'feature'
      AND fis.feature_name = cr.name
      AND fis.symbol = ANY(%(symbols)s)
      AND fis.training_window_end = %(training_window_end)s
      AND fis.feature_status_at_eval IS DISTINCT FROM cr.status
"""


def _fp_row(
    symbol_key: str,
    tf: str,
    pass_type: str,
    training_window_end: Any,
    fp: dict[str, Any],
) -> dict[str, Any]:
    """Build one ic_cell_fingerprints UPSERT row from a fingerprint dict.

    Shared by the per-symbol pass's fp_rows list and the cross-sectional pass's
    single-cell UPSERT (162 simplify-pass; previously this exact 7-field shape was
    built inline at both call sites).
    """
    return {
        "symbol": symbol_key,
        "tf": tf,
        "pass_type": pass_type,
        "training_window_end": training_window_end,
        "code_content_key": fp["code_content_key"],
        "apr_snapshot_key": fp["apr_snapshot_key"],
        "upstream_watermark": json.dumps(fp["upstream_watermark"]),
    }


def _resolve_symbol_routing(
    symbol: str,
    symbol_regime_class: dict[str, str],
    group_by_name: dict[str, dict],
    equity_model_enabled: bool,
) -> tuple[str | None, bool]:
    """Single source of truth for one symbol's regime-group routing decision.

    Returns (routed_group_name, dual_write_symbol_hmm). routed_group_name is None
    when the symbol isn't cross-sectionally routed (equity_model_enabled=False or
    the symbol has no group assignment). Used identically by _symbol_expected_cells
    (the fingerprint gate's notion of "this symbol's cells") and main()'s
    worker_args construction (the actual dispatch) so the two derivations can
    never drift apart (162 simplify-pass; previously duplicated inline in both
    places with only a comment tying them together).
    """
    routed_group_name = symbol_regime_class.get(symbol) if equity_model_enabled else None
    dual_write = bool(
        group_by_name.get(routed_group_name, {}).get("dual_write_symbol_hmm", False)
        if routed_group_name
        else False
    )
    return routed_group_name, dual_write


def _symbol_expected_cells(
    symbol: str,
    tfs: list[str],
    symbol_regime_class: dict[str, str],
    group_by_name: dict[str, dict],
    equity_model_enabled: bool,
    cluster_regime_conditioned: bool = False,
) -> list[tuple[str, str]]:
    """The full set of (tf, pass_type) fingerprint cells one symbol writes.

    Mirrors main()'s own worker_args routing logic exactly (via the shared
    _resolve_symbol_routing helper) so the fingerprint gate's notion of "this
    symbol's cells" can never drift from what _compute_symbol_tf actually writes.
    'pooled' is always written exactly once per tf (regardless of label source).
    The primary regime pass writes 'cross_sectional' when this symbol is routed to
    an enabled group, else 'symbol_hmm'. An additional 'symbol_hmm' dual-write pass
    is added when the routed group has dual_write_symbol_hmm=true OR the Phase 151
    Plan 02 run-level cluster_regime_conditioned switch is true (migration 286) --
    mirrors _compute_symbol_tf's two-condition symbol_hmm-pass gate exactly. Getting
    this wrong would silently stop tracking staleness for the
    widened symbol_hmm cells: an untracked cell is never re-checked against a fresh
    upstream_watermark, so it would never be redispatched once written, even as
    feature_vectors grows underneath it.
    """
    routed_group_name, dual_write = _resolve_symbol_routing(
        symbol, symbol_regime_class, group_by_name, equity_model_enabled
    )
    cross_sectional = routed_group_name is not None
    primary_pass_type = "cross_sectional" if cross_sectional else "symbol_hmm"

    cells: list[tuple[str, str]] = []
    for tf in tfs:
        cells.append((tf, "pooled"))
        cells.append((tf, primary_pass_type))
        if cross_sectional and (dual_write or cluster_regime_conditioned):
            cells.append((tf, "symbol_hmm"))
    return cells


# ---------------------------------------------------------------------------
# Startup crash-loud gates
# ---------------------------------------------------------------------------


def _assert_prerequisites(
    conn: Any,
    tfs: list[str] | None = None,
    equity_model_enabled: bool = True,
    group_configs: list[dict] | None = None,
) -> None:
    """Crash-loud startup gates. Three (or more) explicit RuntimeError raises.

    A run that 'succeeds' with empty feature_ic_scores is a data-integrity
    failure. These gates prevent it by failing loud before any compute.

    When equity_model_enabled=True (i.e. bool(enabled_groups)), also verifies
    market_regimes has rows for each (regime_group, tf) pair in group_configs.
    """
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM feature_vectors")
        n_fv = cur.fetchone()[0]
    if n_fv == 0:
        raise RuntimeError(
            "IC Engine startup gate FAILED: feature_vectors is empty. "
            "Run services/backfill_feature_factory.py first."
        )

    # Phase 172 plan 06: gate on regime_volatility, not the legacy regime column.
    # The legacy `regime` column is still present and readable during the phased
    # cutover (feature_ic_scores vintage separation depends on it staying byte-for-byte
    # unchanged, see 172-IC-ENGINE-CUTOVER.md), but it is deliberately no longer this
    # gate's subject -- a corpus where `regime` is fully populated and
    # `regime_volatility` is all-NULL must fail loud, not pass on the retired column.
    with conn.cursor() as cur:
        cur.execute(
            "SELECT EXISTS(SELECT 1 FROM feature_vectors WHERE regime_volatility IS NOT NULL)"
        )
        has_regime_volatility = cur.fetchone()[0]
    if not has_regime_volatility:
        raise RuntimeError(
            "IC Engine startup gate FAILED: feature_vectors.regime_volatility is all-NULL. "
            "Run services/regime_writer.py --regime-column regime_volatility first."
        )

    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM forward_returns")
        n_fr = cur.fetchone()[0]
    if n_fr == 0:
        raise RuntimeError(
            "IC Engine startup gate FAILED: forward_returns is empty. "
            "Run services/forward_return_writer.py first."
        )

    # market_regimes prerequisite: required when equity_model_enabled=True, checked
    # per (regime_group, tf) for every enabled group -- not just 'equity'.
    if equity_model_enabled and tfs and group_configs:
        for group in group_configs:
            if not group.get("enabled", True):
                continue
            group_name = group["name"]
            for tf in tfs:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT count(*) FROM market_regimes WHERE regime_group=%s AND tf=%s",
                        (group_name, tf),
                    )
                    n_mr = cur.fetchone()[0]
                if n_mr == 0:
                    raise RuntimeError(
                        f"IC Engine startup gate FAILED: market_regimes empty for "
                        f"regime_group={group_name} tf={tf}. "
                        "Run services/cross_sectional_regime_model.py first."
                    )


# ---------------------------------------------------------------------------
# Collinearity clustering
# ---------------------------------------------------------------------------


def _cluster_features(X_nd: np.ndarray, cluster_max_corr: float) -> np.ndarray:
    """Distance-threshold dendrogram clustering of non-degenerate feature columns.

    Returns a 1-based int cluster label per column (len == X_nd.shape[1]).
    Uses single linkage: two clusters merge only when the CLOSEST pair across
    clusters meets the distance threshold. Conservative for redundancy elimination
    -- no transitive merging of uncorrelated features.
    """
    n_nd = X_nd.shape[1]
    if n_nd < 2:
        return np.ones(n_nd, dtype=int)
    corr = np.corrcoef(X_nd.T)
    corr = np.nan_to_num(corr, nan=0.0)
    dist = np.sqrt(0.5 * (1.0 - np.clip(corr, -1.0, 1.0)))
    np.fill_diagonal(dist, 0.0)
    Z = linkage(squareform(dist, checks=False), method="single")
    dist_threshold = np.sqrt(0.5 * (1.0 - cluster_max_corr))
    return fcluster(Z, t=dist_threshold, criterion="distance")  # 1-based ints


# ---------------------------------------------------------------------------
# Bootstrap CI worker-safe RNG derivation (Component A, todo 091)
# ---------------------------------------------------------------------------


def _derive_worker_rng_seed(cell_key: str, bootstrap_seed: int) -> int:
    """Deterministic per-cell RNG seed for the circular block bootstrap CI.

    Restores the removed `_derive_worker_rng_seed(symbol, bootstrap_seed)` pattern
    (git show c6f5056b^:services/ic_engine.py), generalized from "symbol" to any
    cell-identifying string so both the per-symbol ProcessPoolExecutor path
    (_compute_symbol_tf, keyed by symbol) and the single-process cross-sectional
    path (_compute_cross_sectional_tf, keyed by f"{tf}:{regime_label}") get their
    own deterministic, reproducible, collision-resistant seed without any DB write
    or shared RNG state (ProcessPoolExecutor workers are compute-only, CLAUDE.md).

    Derived as bootstrap_seed + MD5(cell_key)[:8] % 2**31. The hash-to-int step is
    the shared Ring-0 primitive (src/core/rng.py, extracted 2026-07-29 /simplify
    pass, todo 203, after src/intelligence/feature_factory.py's canary seeding
    independently re-derived the same idiom) -- this function's own combination
    formula is unchanged, so every existing (cell_key, bootstrap_seed) pair still
    produces byte-identical output to before the extraction.
    """
    return bootstrap_seed + hash_key_to_int(cell_key) % (2**31)


def _sign_consistent_wf_pass_count(fold_ic_arr: np.ndarray, ic_vector_nd: np.ndarray) -> np.ndarray:
    """Count walk-forward folds whose IC sign matches the feature's full-sample sign.

    Component E (todo 094) fix: the pre-existing criterion `(fold_ic_arr > 0).sum(...)`
    is sign-asymmetric -- it can never be satisfied by a persistently-negative
    (contrarian, ic_sign=-1) feature no matter how stable its folds are, which is
    exactly the mechanism that silently excludes 100% of negative-IC features from
    `passes_walkforward` and therefore from ensemble eligibility (`_ELIGIBILITY_BASE_WHERE`
    requires `passes_walkforward = true`).

    Equivalence-preserving for ic_sign=1 features: `np.sign(ic_vector_nd)` is `+1`, so
    `fold_ic_arr * sign_nd` is a no-op and this reduces byte-for-byte to the old
    `(fold_ic_arr > 0)` criterion. For ic_sign=-1 features, a fold now "passes" when its
    sign matches the feature's OWN full-sample sign (both negative), not when the raw
    fold IC happens to be positive.

    Unconditional (no APR flag) -- this is a measurement-layer fix, not a policy switch;
    see 143.1-04-PLAN.md objective for why walk-forward must stay unconditional while
    `alpha.ensemble.sign_symmetric` gates only the downstream eligibility/weighting/
    lifecycle policy layer.

    Args:
        fold_ic_arr: Shape [n_folds, n_nd] -- per-fold IC point estimates.
        ic_vector_nd: Shape [n_nd] -- full-sample IC point estimate per feature.

    Returns:
        wf_pass_count_nd: Shape [n_nd] int array -- folds passing per feature.
    """
    sign_nd = np.sign(ic_vector_nd)
    return ((fold_ic_arr * sign_nd[None, :]) > 0).sum(axis=0)


# ---------------------------------------------------------------------------
# Shared feature-blocked rank/IC/CI/fold compute (162-01 Task 3, todos 139/140)
# ---------------------------------------------------------------------------


def _blocked_bootstrap_ci(
    X_raw_block: np.ndarray,
    Y_scale: np.ndarray,
    starts_matrix: np.ndarray,
    offsets: np.ndarray,
    n_valid: int,
    pool: ThreadPoolExecutor | None,
    early_stop_enabled: bool = False,
    early_stop_check_interval: int = 200,
    early_stop_tol: float = 0.002,
    early_stop_min_resamples: int = 200,
    early_stop_stable_checks: int = 2,
) -> tuple[np.ndarray, np.ndarray]:
    """95% circular block bootstrap CI for one feature block.

    Reuses a resample block-start index matrix (`starts_matrix`) drawn ONCE per
    scale by the caller (`_subsample_and_rank`'s CRITICAL RNG invariant) --
    this function draws no randomness of its own, so calling it once per
    feature block never perturbs RNG consumption order vs the unblocked path.
    `starts_matrix`'s shape (and therefore the RNG draw that produced it) is
    UNCHANGED by early-stop -- only how many of its already-drawn rows this
    function actually spends the expensive rankdata/IC compute on varies.

    Threading (mirrors `_circular_block_bootstrap_ic`'s todo-131 design, but
    simpler): since every iteration's resample indices are already fully
    determined by `starts_matrix` before this function is ever called,
    dispatch order no longer matters for correctness -- unlike the unblocked
    function, which interleaves serial RNG draws with threaded resampling.
    `np.percentile` is invariant to the order of `boot_ics` along axis=0, so
    a caller-owned `pool` (cross-sectional path only, todo 131 -- never passed
    for the per-symbol ProcessPoolExecutor worker path) is safe regardless of
    completion order.

    `pool` is caller-owned and reused across every feature block within one
    cell (162 simplify-pass -- previously this function spun up and tore down
    its own ThreadPoolExecutor once PER BLOCK, ~5x per cell for a typical
    ~150-feature/32-column-block cell, multiplied by every cross-sectional
    cell on that tf). `pool=None` takes the serial path, matching the original
    `max_workers<=1` contract.

    Todo 227 (2026-08-05): early_stop_enabled=False (the default) is byte-
    identical to the pre-todo-227 function -- always computes exactly
    starts_matrix.shape[0] resamples. When True, computes in chunks of
    early_stop_check_interval resamples, and once at least early_stop_min_
    resamples have been computed, stops as soon as the running ci_lower/
    ci_upper estimate (recomputed from ALL resamples so far, elementwise
    across the block) has changed by no more than early_stop_tol for
    early_stop_stable_checks consecutive checkpoints. Bit-identical
    reproducibility across different resample counts was confirmed NOT
    load-bearing for this CI (see ICEngineConfig.bootstrap_early_stop_enabled's
    comment) -- every downstream consumer reads ci_lower/ci_upper as a
    threshold/sign gate, never an exact value compared run-to-run.
    """
    n_boot = starts_matrix.shape[0]
    block_p = X_raw_block.shape[1]

    def _resample_ic(b: int) -> np.ndarray:
        idx = (starts_matrix[b][:, None] + offsets).ravel()[:n_valid] % n_valid
        ranks_X_boot = rankdata(X_raw_block[idx], axis=0)
        ranks_Y_boot = rankdata(Y_scale[idx])
        return _vectorized_ic(ranks_X_boot, ranks_Y_boot)

    if not early_stop_enabled:
        if pool is None:
            boot_ics = np.zeros((n_boot, block_p))
            for b in range(n_boot):
                boot_ics[b] = _resample_ic(b)
        else:
            boot_ics = np.array(list(pool.map(_resample_ic, range(n_boot))))
        ci_lower = np.percentile(boot_ics, 2.5, axis=0)
        ci_upper = np.percentile(boot_ics, 97.5, axis=0)
        return ci_lower, ci_upper

    boot_ics = np.zeros((n_boot, block_p))
    prev_ci_lower: np.ndarray | None = None
    prev_ci_upper: np.ndarray | None = None
    stable_count = 0
    n_computed = 0
    for chunk_start in range(0, n_boot, early_stop_check_interval):
        chunk_end = min(chunk_start + early_stop_check_interval, n_boot)
        chunk_range = range(chunk_start, chunk_end)
        if pool is None:
            for b in chunk_range:
                boot_ics[b] = _resample_ic(b)
        else:
            for b, val in zip(chunk_range, pool.map(_resample_ic, chunk_range)):
                boot_ics[b] = val
        n_computed = chunk_end

        if n_computed < early_stop_min_resamples:
            continue

        cur_ci_lower = np.percentile(boot_ics[:n_computed], 2.5, axis=0)
        cur_ci_upper = np.percentile(boot_ics[:n_computed], 97.5, axis=0)

        if prev_ci_lower is not None:
            max_delta = max(
                float(np.max(np.abs(cur_ci_lower - prev_ci_lower))),
                float(np.max(np.abs(cur_ci_upper - prev_ci_upper))),
            )
            stable_count = stable_count + 1 if max_delta <= early_stop_tol else 0
            if stable_count >= early_stop_stable_checks:
                return cur_ci_lower, cur_ci_upper

        prev_ci_lower = cur_ci_lower
        prev_ci_upper = cur_ci_upper

    # Exhausted every resample in starts_matrix without stabilizing -- same
    # full-sample estimate the disabled path would have produced.
    ci_lower = np.percentile(boot_ics, 2.5, axis=0)
    ci_upper = np.percentile(boot_ics, 97.5, axis=0)
    return ci_lower, ci_upper


def _subsample_and_rank(
    X_sub_nd: np.ndarray,
    valid_mask: np.ndarray,
    returns_scale: np.ndarray,
    *,
    walk_forward_folds: int,
    embargo_bars: int,
    min_reliable_n: int,
    bootstrap_block_size: int,
    bootstrap_resamples: int,
    rng: np.random.Generator,
    max_workers: int,
    feature_block_columns: int,
    bootstrap_early_stop_enabled: bool = False,
    bootstrap_early_stop_check_interval: int = 200,
    bootstrap_early_stop_tol: float = 0.002,
    bootstrap_early_stop_min_resamples: int = 200,
    bootstrap_early_stop_stable_checks: int = 2,
) -> tuple[
    np.ndarray,
    np.ndarray,
    np.ndarray,
    np.ndarray,
    np.ndarray,
    np.ndarray,
    np.ndarray,
    list[np.ndarray],
]:
    """Feature-blocked rank -> IC -> circular block bootstrap CI -> walk-forward
    fold pipeline, shared by _compute_one_regime_cell and
    _compute_one_cross_sectional_cell (todos 139/140).

    Processes rankdata(X_sub_nd, axis=0) -- the root-cause transient behind the
    2026-07-18 OOM (rankdata() always returns float64 regardless of input
    dtype, silently defeating the float32 memory optimization one line
    earlier) -- in bounded column blocks of feature_block_columns, writing
    each block's ranks into one preallocated float32 output, so peak transient
    is O(n_sub x block) rather than O(n_sub x n_features). Chunks the FEATURE
    axis only, never the time/row axis (rankdata over a row-block is a
    DIFFERENT statistic -- explicitly rejected by the 2026-07-19 design pass;
    rankdata(X, axis=0) ranks each feature column independently, so splitting
    columns preserves the exact statistic while splitting rows would not).

    CRITICAL RNG invariant: the circular block bootstrap's resample
    block-start index matrix (shape [bootstrap_resamples,
    ceil(n_valid/bootstrap_block_size)]) is drawn from `rng` exactly ONCE,
    BEFORE the feature-block loop begins, and reused identically across every
    block. Drawing inside the block loop would call rng.integers()
    feature_block_columns-times-more-often than the unblocked path, consuming
    a different sequence of draws and silently changing every CI -- this is
    what makes the feature-blocked output bit-identical to the unblocked path
    (verified: a single batched `rng.integers(..., size=(B, K))` call
    consumes the RNG stream identically to B sequential
    `rng.integers(..., size=K)` calls) rather than merely "close."

    Walk-forward fold boundaries are likewise feature-independent and computed
    once per scale via build_walk_forward_folds, not per block.

    Todo 227 (2026-08-05): bootstrap_early_stop_* params (all optional, default
    disabled) pass straight through to _blocked_bootstrap_ci per feature block.
    This RNG invariant is untouched by early-stop -- the index matrix above is
    still drawn at full bootstrap_resamples size regardless; early-stop only
    changes how many of its rows _blocked_bootstrap_ci actually spends compute
    on before returning.

    Args:
        X_sub_nd: [n_sub, n_features_nd] RAW (unranked), non-degenerate feature
            columns for this scale's stride subsample -- BEFORE valid_mask.
        valid_mask: [n_sub] bool -- completeness & finite-return mask.
        returns_scale: [n_sub] RAW forward-return column for this scale --
            BEFORE valid_mask (masked internally, matching X_sub_nd).

    Returns:
        X_raw_scale: [n_valid, n_features_nd] RAW (unranked) -- needed by the
            caller for sign_hit_rate/magnitude_conditional_ic.
        ranks_X_scale: [n_valid, n_features_nd] float32.
        ranks_Y: [n_valid] float32.
        ic_vector_nd: [n_features_nd] float64.
        p_vector_nd: [n_features_nd] float64.
        ci_lower_nd, ci_upper_nd: [n_features_nd] float64 -- 95% circular block
            bootstrap CI bounds (the CI that gates ensemble eligibility for
            cross-sectional POOLED rows).
        fold_ics_list: one [n_features_nd] IC vector per walk-forward fold that
            cleared the length-2 guard -- same list shape the unblocked path
            produced, so `wf_fold_count = len(fold_ics_list)` at the call site
            is unchanged.
    """
    n_features_nd = X_sub_nd.shape[1]
    X_raw_scale = X_sub_nd[valid_mask]
    n_valid = X_raw_scale.shape[0]
    Y_scale = returns_scale[valid_mask]
    ranks_Y = rankdata(Y_scale).astype(np.float32)

    # Bootstrap resample block-start index matrix -- see CRITICAL RNG invariant above.
    n_time_blocks = math.ceil(n_valid / bootstrap_block_size)
    starts_matrix = rng.integers(0, n_valid, size=(bootstrap_resamples, n_time_blocks))
    offsets = np.arange(bootstrap_block_size)

    # Walk-forward fold boundaries -- feature-independent, computed once per scale.
    # Same len(X_test) < 2 guard the unblocked path applied per-fold (row-count
    # based, not feature-based, so identical across every block below).
    folds = [
        (s, e)
        for s, e in build_walk_forward_folds(
            n_valid, walk_forward_folds, embargo_bars, min_reliable_n
        )
        if (e - s) >= 2
    ]

    ranks_X_scale = np.empty((n_valid, n_features_nd), dtype=np.float32)
    ic_vector_nd = np.empty(n_features_nd, dtype=np.float64)
    ci_lower_nd = np.empty(n_features_nd, dtype=np.float64)
    ci_upper_nd = np.empty(n_features_nd, dtype=np.float64)
    fold_ic_mat = np.empty((len(folds), n_features_nd), dtype=np.float64) if folds else None

    # One thread pool for the whole cell, reused across every feature block
    # (162 simplify-pass -- previously _blocked_bootstrap_ci created and tore
    # down its own pool once per block; see that function's docstring).
    pool = ThreadPoolExecutor(max_workers=max_workers) if max_workers > 1 else None
    try:
        for block_start in range(0, n_features_nd, feature_block_columns):
            block_end = min(block_start + feature_block_columns, n_features_nd)

            # The root-cause transient (rankdata always returns float64) -- bounded to
            # this block's width, not the full n_features_nd.
            ranks_block = rankdata(X_sub_nd[:, block_start:block_end], axis=0).astype(np.float32)[
                valid_mask
            ]
            ranks_X_scale[:, block_start:block_end] = ranks_block

            X_raw_block = X_raw_scale[:, block_start:block_end]

            ic_vector_nd[block_start:block_end] = _vectorized_ic(ranks_block, ranks_Y)

            ci_lower_block, ci_upper_block = _blocked_bootstrap_ci(
                X_raw_block,
                Y_scale,
                starts_matrix,
                offsets,
                n_valid,
                pool,
                early_stop_enabled=bootstrap_early_stop_enabled,
                early_stop_check_interval=bootstrap_early_stop_check_interval,
                early_stop_tol=bootstrap_early_stop_tol,
                early_stop_min_resamples=bootstrap_early_stop_min_resamples,
                early_stop_stable_checks=bootstrap_early_stop_stable_checks,
            )
            ci_lower_nd[block_start:block_end] = ci_lower_block
            ci_upper_nd[block_start:block_end] = ci_upper_block

            for k, (test_start, test_end) in enumerate(folds):
                X_test = ranks_block[test_start:test_end]
                Y_test = ranks_Y[test_start:test_end]
                # float32, not float64 (2026-07-19 OOM fix, same pattern as
                # ranks_block/ranks_Y above).
                rX_test = rankdata(X_test, axis=0).astype(np.float32)
                rY_test = rankdata(Y_test).astype(np.float32)
                fold_ic_mat[k, block_start:block_end] = _vectorized_ic(rX_test, rY_test)
    finally:
        if pool is not None:
            pool.shutdown(wait=True)

    p_vector_nd = _p_values_from_ic(ic_vector_nd, n_valid)
    fold_ics_list = [fold_ic_mat[k] for k in range(len(folds))] if folds else []

    return (
        X_raw_scale,
        ranks_X_scale,
        ranks_Y,
        ic_vector_nd,
        p_vector_nd,
        ci_lower_nd,
        ci_upper_nd,
        fold_ics_list,
    )


# ---------------------------------------------------------------------------
# Main compute loop for a single (symbol, tf)
# ---------------------------------------------------------------------------

_EMPTY_SYMBOL_RESULT: tuple = (
    [],
    [],
    {"n_committed": 0, "n_skipped": 0, "pvals_flat": [], "pval_result_idxs": []},
)


def _compute_one_regime_cell(
    regime_label: str,
    is_pooled: bool,
    mask: np.ndarray,
    resolved_regime_scope: str,
    *,
    X_aligned: np.ndarray,
    returns_mat: np.ndarray,
    complete_mat: np.ndarray,
    config: ICEngineConfig,
    symbol: str,
    tf: str,
    rng: np.random.Generator,
    training_window_end: Any,
    feature_status_map: dict[str, str] | None,
    run_ts: datetime,
) -> tuple[list[dict], int, dict[str, int]]:
    """Compute clustering + per-scale IC/CI/walk-forward/Sharpe for ONE regime cell.

    Extracted from _compute_symbol_tf's single-pass loop (todo: restore symbol_hmm
    measurement for regime-group-routed symbols) so the same per-cell compute logic
    can run multiple times per (symbol, tf) -- once for the pooled cell (always,
    exactly once), once for the symbol's primary label source (cross-sectional or
    its own per-symbol HMM), and optionally once more for a dual-write pass using a
    second label source under a different regime_scope tag.

    resolved_regime_scope is passed in explicitly (not recomputed via
    _resolve_regime_scope(is_pooled, cross_sectional) internally) since a caller now
    decides scope per call, not per (is_pooled, cross_sectional) combination.

    rng is a shared, stateful np.random.Generator -- calling this function consumes
    draws from it by design (matches the existing per-worker RNG-scope contract:
    never re-seeded per-cell, advanced monotonically across every cell a worker
    computes for its symbol).

    Returns (result_rows, n_skipped_features, skip_reasons) for this cell only.
    skip_reasons is {skip_reason: count}, the same breakdown
    IC_ENGINE_CELLS_SKIPPED_TOTAL needs -- this function itself never touches OTel
    (runs inside a ProcessPoolExecutor worker, which has no metrics exporter
    initialized; a direct .add() call here would silently no-op forever, see todo
    009/2026-07-31 fix). The caller emits the real metric from the main process,
    where result_rows/skip_reasons from every worker are aggregated.

    Does NOT populate pvals_flat/pval_result_idxs -- cluster-representative
    selection for BH-FDR runs downstream in _compute_symbol_tf, after ALL cells
    (across every pass) have been accumulated into all_results, and needs no
    changes for this to work correctly regardless of how many passes contributed
    rows.
    """
    lookaheads = config.lookaheads_for(tf)
    subsample_min_stride = config.subsample_min_stride
    min_reliable_n = config.min_reliable_n
    walk_forward_folds = config.walk_forward_folds
    cluster_max_corr = config.cluster_max_corr
    n_features = len(_FEATURE_NAMES)

    result_rows: list[dict] = []
    skip_reasons: dict[str, int] = {}
    n_skipped = 0

    X_regime = X_aligned[mask]
    returns_regime = returns_mat[mask]
    complete_regime = complete_mat[mask]
    n_regime_raw = X_regime.shape[0]

    _check_cell_size(n_regime_raw, config, f"Cell symbol={symbol} tf={tf} regime={regime_label}")

    # ------------------------------------------------------------------
    # Degenerate feature detection on FULL regime data (std < 1e-8 = constant column).
    # Using X_regime (not a subsample) ensures the mask is stable across all scales
    # regardless of stride. A feature constant in the full regime is constant in any
    # subsample — but the converse may not hold for large strides.
    # ------------------------------------------------------------------
    # dtype=float64: X_regime is float32 now (memory optimization), force the
    # reduction itself to accumulate in float64 so this threshold check stays
    # exactly as precise as before -- see the cross-sectional path's identical note.
    feature_stds = np.std(X_regime, axis=0, dtype=np.float64)
    degenerate_mask = feature_stds < 1e-8
    non_degenerate_mask = ~degenerate_mask
    n_degenerate = int(degenerate_mask.sum())
    if n_degenerate > 0:
        skip_reasons["degenerate_feature"] = (
            skip_reasons.get("degenerate_feature", 0) + n_degenerate
        )
        n_skipped += n_degenerate

    # Non-degenerate slice of full regime matrix — shared across scales.
    X_regime_nd = X_regime[:, non_degenerate_mask]
    if X_regime_nd.shape[1] == 0:
        # Was `continue` (skip to next regime_label) in the pre-extraction
        # for-loop over regime_passes; this cell has no "next regime" to fall
        # through to now that each cell is its own function call, so the
        # equivalent behavior is to return immediately with whatever
        # result_rows/n_skipped/skip_reasons this cell has accumulated so far
        # (empty rows; n_skipped/skip_reasons already reflect the
        # degenerate-feature count above).
        return result_rows, n_skipped, skip_reasons

    # ------------------------------------------------------------------
    # Distance-threshold dendrogram clustering per (symbol, tf, regime)
    # NOTE: dendrogram distance cutoff -- transitive linkage can merge
    # features whose direct pairwise correlation is below cluster_max_corr.
    # ------------------------------------------------------------------
    cluster_ids_nd = _cluster_features(X_regime_nd, cluster_max_corr)
    # Expand to full feature space: None for degenerate, cluster_id for non-degenerate
    cluster_id_full = expand_int(cluster_ids_nd, non_degenerate_mask, n_features)

    _logger.info(
        "ic_engine.clustering",
        symbol=symbol,
        tf=tf,
        regime=regime_label,
        n_clusters=int(cluster_ids_nd.max()) if len(cluster_ids_nd) > 0 else 0,
        n_features=len(cluster_ids_nd),
    )

    scales = config.active_scales_for(tf)
    for scale_idx, scale in enumerate(scales):
        lookahead_bars = lookaheads[scale]

        # Per-scale subsampling: stride = max(min_stride, lookahead_bars).
        # Fast scale (lookahead=1) uses stride=min_stride, giving ~N/5 obs per regime.
        # Extended scale (lookahead=60) uses stride=60, giving ~N/60 obs per regime.
        # Previously all scales used stride=60, starving fast scale by 60x.
        scale_stride = max(subsample_min_stride, lookahead_bars)
        # Slice, not fancy-index (2026-07-19 OOM fix) -- see the identical
        # fix + rationale in _compute_cross_sectional_tf.
        stride = slice(0, n_regime_raw, scale_stride)
        X_sub_scale = X_regime[stride]  # full features for _compute_ic_rolling_metrics
        X_sub_nd = X_regime_nd[stride]  # non-degen columns for rankdata
        returns_sub = returns_regime[stride]
        complete_sub = complete_regime[stride]
        n_independent = len(X_sub_scale)

        if n_independent < min_reliable_n:
            skip_reasons["insufficient_n"] = skip_reasons.get("insufficient_n", 0) + len(
                _FEATURE_NAMES
            )
            n_skipped += len(_FEATURE_NAMES)
            continue

        # Filter to complete rows for this lookahead
        scale_complete = complete_sub[:, scale_idx]
        returns_scale = returns_sub[:, scale_idx]
        valid_mask = scale_complete & np.isfinite(returns_scale)
        n_valid = valid_mask.sum()

        if n_valid < min_reliable_n:
            skip_reasons["insufficient_n"] = skip_reasons.get("insufficient_n", 0) + len(
                _FEATURE_NAMES
            )
            n_skipped += len(_FEATURE_NAMES)
            continue

        # embargo_bars = lookahead_bars for this scale (P3 fix: was max(lookaheads)=60).
        # Fast scale (lookahead=1) uses embargo=1; extended scale (lookahead=60) uses 60.
        # This prevents overlapping forward-return labels from leaking across fold
        # boundaries without discarding 59 valid observations per fold for fast scale.
        embargo_bars = lookahead_bars

        # -------------------------------------------------------
        # Shared feature-blocked rank -> IC -> circular block bootstrap CI ->
        # walk-forward fold pipeline (162-01 Task 3, todos 139/140). Per-symbol
        # path, thread count now per-tf configurable (todo 215,
        # config.per_symbol_bootstrap_threads[tf] -- see that field's comment).
        # -------------------------------------------------------
        (
            X_raw_scale,
            ranks_X_scale,
            ranks_Y,
            ic_vector_nd,
            p_vector_nd,
            ci_lower_nd,
            ci_upper_nd,
            fold_ics_list,
        ) = _subsample_and_rank(
            X_sub_nd,
            valid_mask,
            returns_scale,
            walk_forward_folds=walk_forward_folds,
            embargo_bars=embargo_bars,
            min_reliable_n=min_reliable_n,
            bootstrap_block_size=config.bootstrap_block_size[tf],
            bootstrap_resamples=config.bootstrap_resamples,
            rng=rng,
            max_workers=config.per_symbol_bootstrap_threads[tf],
            feature_block_columns=config.feature_block_columns,
            bootstrap_early_stop_enabled=config.bootstrap_early_stop_enabled,
            bootstrap_early_stop_check_interval=config.bootstrap_early_stop_check_interval,
            bootstrap_early_stop_tol=config.bootstrap_early_stop_tol,
            bootstrap_early_stop_min_resamples=config.bootstrap_early_stop_min_resamples,
            bootstrap_early_stop_stable_checks=config.bootstrap_early_stop_stable_checks,
        )
        Y_scale = returns_scale[valid_mask]

        # Expand back to full feature space (NaN for degenerate)
        ic_full = _expand(ic_vector_nd, non_degenerate_mask, n_features)
        p_full = _expand(p_vector_nd, non_degenerate_mask, n_features)

        ci_lower_full = _expand(ci_lower_nd, non_degenerate_mask, n_features)
        ci_upper_full = _expand(ci_upper_nd, non_degenerate_mask, n_features)
        passes_ci_full = np.where(non_degenerate_mask, ci_lower_full > 0.0, False)

        wf_fold_count = len(fold_ics_list)
        if wf_fold_count > 0:
            fold_ic_arr = np.array(fold_ics_list)  # [n_folds, n_nd]
            wf_pass_count_nd = _sign_consistent_wf_pass_count(fold_ic_arr, ic_vector_nd)
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
            config,
            non_degenerate_mask,
            n_features,
            scale_stride,  # per-scale stride for raw→subsampled window conversion
        )

        # -------------------------------------------------------
        # IC decomposition: sign_hit_rate + magnitude-conditional IC
        # (Component B, todo 090). Diagnostic-only columns, no gate impact.
        # Reuses X_raw_scale/Y_scale already assembled above for the
        # bootstrap CI -- no additional query or array materialization.
        # -------------------------------------------------------
        sign_hit_rate_nd = sign_hit_rate(X_raw_scale, Y_scale)
        magnitude_ic_nd = magnitude_conditional_ic(X_raw_scale, Y_scale, _MAGNITUDE_IC_PERCENTILE)
        sign_hit_rate_full = _expand(sign_hit_rate_nd, non_degenerate_mask, n_features)
        magnitude_ic_full = _expand(magnitude_ic_nd, non_degenerate_mask, n_features)

        # -------------------------------------------------------
        # Collect results -- BH-FDR is applied after all regimes/scales
        # using representative-only selection per cluster.
        # -------------------------------------------------------
        for feat_idx, feat_name in enumerate(_FEATURE_NAMES):
            # 162-03: the whole-cell fingerprint gate in main() is now the SOLE skip
            # decision (before this function is ever called) -- no per-feature
            # already-present skip here. A dispatched cell recomputes every feature
            # unconditionally; a fingerprint-valid sibling that gets recomputed
            # anyway is harmless (identical rows hit ON CONFLICT DO NOTHING).
            ic_val = ic_full[feat_idx]
            p_val = p_full[feat_idx]
            result_rows.append(
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
                    "regime_scope": resolved_regime_scope,
                    "sign_hit_rate": _nan_to_none(sign_hit_rate_full[feat_idx]),
                    "magnitude_conditional_ic": _nan_to_none(magnitude_ic_full[feat_idx]),
                    # e-value pilot (Component C, todo 079) is scoped to
                    # _compute_cross_sectional_tf's tf=5m POOLED cells only --
                    # this per-symbol path never computes it.
                    "cumulative_e_value": None,
                }
            )

    return result_rows, n_skipped, skip_reasons


def _merge_skip_reasons(total: dict[str, int], addition: dict[str, int]) -> None:
    """Accumulate a cell/pass-level skip_reasons dict into a running total, in place.

    Pure, OTel-free (unlike the counter it ultimately feeds) so it can run inside a
    ProcessPoolExecutor worker without needing any exporter initialized there --
    only the caller in main(), after aggregating every worker's result, actually
    calls IC_ENGINE_CELLS_SKIPPED_TOTAL.add() with the merged counts.
    """
    for reason, count in addition.items():
        total[reason] = total.get(reason, 0) + count


def _build_regime_passes(
    regime_aligned_market: np.ndarray,
    distinct_regimes: list,
    regime_aligned: np.ndarray,
    cross_sectional: bool,
    dual_write_symbol_hmm: bool,
    cluster_regime_conditioned: bool,
    primary_resolved_scope: str,
) -> list[tuple[np.ndarray, list, str]]:
    """Build the list of (label_array, distinct_labels, resolved_scope) passes
    _compute_symbol_tf's per-label-array loop iterates over.

    Pure, DB-free extraction (Phase 151 Plan 02, mirrors _group_cells_for_metrics'
    own extraction rationale) of the regime_passes construction previously inline
    in _compute_symbol_tf -- lets Task 3's unit tests assert directly on
    regime_passes' length/resolved_scope without a live DB connection.

    Primary pass is always exactly one entry. An additional 'symbol_hmm' entry is
    appended once when cross_sectional AND (dual_write_symbol_hmm OR
    cluster_regime_conditioned) -- the `or` is not a double-append, matching
    _compute_symbol_tf's own gate exactly (see that function's inline comment for
    the two gates' provenance). Never includes the pooled sentinel -- pooled is
    handled once, separately, by the caller.
    """
    regime_passes: list[tuple[np.ndarray, list, str]] = [
        (regime_aligned_market, distinct_regimes, primary_resolved_scope)
    ]
    if cross_sectional and (dual_write_symbol_hmm or cluster_regime_conditioned):
        distinct_symbol_hmm_regimes = [r for r in set(regime_aligned) if r is not None]
        regime_passes.append((regime_aligned, distinct_symbol_hmm_regimes, "symbol_hmm"))
    return regime_passes


def _group_cells_for_metrics(
    all_results: list[dict], symbol: str, tf: str
) -> list[tuple[dict[str, Any], int]]:
    """Group all_results rows into per-cell OTel metric emissions.

    Grouping key is (regime, is_pooled, regime_scope) -- NOT just (regime,
    is_pooled). A dual-write symbol_hmm pass and the primary cross-sectional
    pass can produce the same HMM regime LABEL STRING (e.g. both
    "trending_up") while being two genuinely distinct measurement passes;
    grouping on label alone would merge their counts into one metric
    emission and mis-attribute the combined count to whichever regime_scope
    happened to be read last. Returns (attrs, count) pairs ready to hand to
    IC_ENGINE_CELLS_COMPLETED_TOTAL.add(count, attrs) -- extracted from
    _compute_symbol_tf so the grouping logic itself is unit-testable without
    a live OTel metrics backend.
    """
    distinct_cells = {(r["regime"], r["is_pooled"], r["regime_scope"]) for r in all_results}
    emissions: list[tuple[dict[str, Any], int]] = []
    for regime_label, is_pooled, regime_scope in distinct_cells:
        regime_results = [
            r
            for r in all_results
            if r["regime"] == regime_label
            and r["is_pooled"] == is_pooled
            and r["regime_scope"] == regime_scope
        ]
        if not regime_results:
            continue
        attrs = {
            "symbol": symbol,
            "tf": tf,
            "regime": regime_label,
            "regime_scope": regime_scope,
        }
        emissions.append((attrs, len(regime_results)))
    return emissions


def _compute_symbol_tf(
    dsn: str,
    symbol: str,
    tf: str,
    training_window_end: Any,
    config: ICEngineConfig,
    tracer: Any,
    run_ts: datetime,
    rng: np.random.Generator,
    feature_status_map: dict[str, str] | None = None,
    mr_dict: dict | None = None,
    dual_write_symbol_hmm: bool = False,
    cluster_regime_conditioned: bool = False,
) -> tuple[list[dict], list[dict], dict[str, Any]]:
    """Compute IC for all (regime, lookahead) cells for one (symbol, tf).

    rng: worker-safe circular block bootstrap RNG (Component A, todo 091), derived
    deterministically per-symbol via _derive_worker_rng_seed() and shared/advanced
    across every (regime, scale) cell and the daily context-features loop within
    this one (symbol, tf) call -- never re-seeded per-cell, matching the removed
    reference implementation's per-worker (not per-cell) RNG scope.

    No DB writes — returns (pooled_rows, regime_rows, stats_dict). Writes happen
    serially in main process via _write_ic_results AFTER corpus-level BH-FDR
    is applied (P2 fix). rows have bh_adjusted_p=None/passes_fdr=None for
    non-representatives; pvals_flat + pval_result_idxs returned for FDR pass.

    dsn: connection string, not a live connection. This function opens two
    short-lived connections internally (one for the feature/forward-return
    fetch, one later for the context-features fetch) rather than holding a
    single connection across the clustering/bootstrap compute loop between
    them (todo 102, 2026-07-12: that loop routinely runs long enough to
    exceed postgres's idle_session_timeout, and a connection left idle across
    it gets killed server-side before ever being used again — the corpus
    re-run was silently writing zero rows as a result).

    feature_status_map: dict mapping feature_name → status from concept_registry
    (domain='feature'). If provided, each IC score row receives
    feature_status_at_eval from this map.
    Defaults to 'unknown' for any feature not found in the map.

    mr_dict: optional dict {ts -> regime_label} from market_regimes for this TF.
    When provided (equity_model_enabled=True), regime labels come from market_regimes
    instead of feature_vectors.regime_volatility, enabling cross-symbol IC
    stratification. When None (equity_model_enabled=False), falls back to
    feature_vectors.regime_volatility (Phase 172 plan 06; was feature_vectors.regime
    before this cutover).

    cluster_regime_conditioned: Phase 151 Plan 02 global switch (run-level
    ICEngineConfig field, not per-group like dual_write_symbol_hmm). When True
    (alongside dual_write_symbol_hmm), widens the symbol_hmm regime_passes entry
    to run for every cross-sectionally-routed symbol, not only those whose group
    sets dual_write_symbol_hmm. See the regime_passes construction below.

    Returns (pooled_rows, regime_rows, stats_dict) where stats_dict contains
    all_results, pvals_flat, pval_result_idxs, n_committed, n_skipped, n_passing_wf,
    skip_reasons ({skip_reason: count}), and cell_emissions (the pre-computed
    _group_cells_for_metrics() output) -- the latter two exist purely so the caller
    (in the main process) can emit IC_ENGINE_CELLS_SKIPPED_TOTAL/
    IC_ENGINE_CELLS_COMPLETED_TOTAL/FEATURE_IC_PASSING_WALKFORWARD_TOTAL itself;
    this function never touches OTel (see the emission block at the end of this
    function's body for why).
    """
    lookaheads = config.lookaheads_for(tf)
    subsample_min_stride = config.subsample_min_stride
    min_reliable_n = config.min_reliable_n
    fdr_alpha = config.fdr_alpha
    walk_forward_folds = config.walk_forward_folds
    cluster_max_corr = config.cluster_max_corr
    n_features = len(_FEATURE_NAMES)
    scales = config.active_scales_for(tf)

    with _observed_span("ic_engine.compute_symbol_tf", tracer, symbol=symbol, tf=tf):
        # Short-lived fetch connection -- opened here, closed as soon as the
        # feature/forward-return fetch below completes (see dsn note in the
        # docstring). It must not stay open across the clustering/bootstrap loop
        # that follows.
        with short_lived_conn(dsn) as conn:
            # Server-side cursor requires no active transaction -- commit any open
            # transaction first (a no-op read-only boundary clear, not a data write;
            # matches regime_writer.py's _compute_symbol_tf and ensemble_ic_engine.py's
            # pooled worker fetch, both of which commit at their own named-cursor
            # call site rather than pushing this precondition onto the caller).
            conn.commit()
            # ------------------------------------------------------------------
            # Load feature matrix
            # ------------------------------------------------------------------
            # Phase 172 plan 06: per-symbol regime label source repointed to
            # feature_vectors.regime_volatility (calm/elevated/turbulent). The legacy
            # feature_vectors.regime column is deliberately not read here anymore --
            # see 172-IC-ENGINE-CUTOVER.md for the audit of what does and does not change.
            feature_cols = ", ".join(f'"{f}"' for f in _FEATURE_NAMES)
            fv_sql = f"""
                SELECT bar_ts, regime_volatility, {feature_cols}
                FROM feature_vectors
                WHERE symbol = %s AND tf = %s AND bar_ts <= %s
                ORDER BY bar_ts
            """
            # Named (server-side) cursor + itersize: rows are fetched from the server in
            # bounded batches, so peak memory is O(chunk_rows), not O(all rows). A plain
            # conn.cursor() -- what this used before -- pulls the ENTIRE result across
            # the wire into the driver's client-side buffer at execute() time regardless of
            # how the Python side iterates it; itersize on an unnamed cursor is a no-op
            # (the prior comment here describing "fetchmany(itersize) under the hood" was
            # incorrect assumption, not an actual fix). That gap caused the
            # 2026-07-09 per-symbol ProcessPoolExecutor OOM: QQQ/5m alone (392K rows x
            # 150 features) measured at 4.3 GB peak RSS materialising bar_ts_list/
            # regime_list/X_list before conversion; with 12 workers concurrently in their
            # 5m pass that's 50+ GB against a 29 GB box. Chunked server-side fetch (now
            # sharing Float32ChunkAccumulator, todo 087, with _compute_cross_sectional_tf's
            # own OOM fix below; ensemble_ic_engine.py's pooled_fetch_itersize fix reduces
            # via a generator instead and doesn't share this accumulator shape) measured
            # at ~700 MB peak for the same symbol.
            #
            # Only the wide feature matrix (150 columns) needs chunked conversion --
            # bar_ts/regime are one scalar per row and stay cheap (tens of MB at most)
            # as plain flat lists even at 400K+ rows, so they're appended directly with
            # no threshold/flush bookkeeping. Float32ChunkAccumulator (todo 087) owns the
            # buffer-to-array bookkeeping shared with _compute_cross_sectional_tf's own
            # OOM fix below; the streaming-cursor mechanics stay here.
            fetch_chunk_rows = config.symbol_fetch_chunk_rows
            bar_ts_list: list = []
            regime_list: list = []
            acc = Float32ChunkAccumulator(flush_at=fetch_chunk_rows)
            with conn.cursor(name=f"fv_{symbol}_{tf}") as cur:
                cur.itersize = fetch_chunk_rows
                cur.execute(fv_sql, (symbol, tf, training_window_end))
                for r in cur:
                    bar_ts_list.append(r[0])
                    regime_list.append(r[1])
                    acc.append_row(r[2:])

            if not bar_ts_list:
                _logger.info("ic_engine.no_feature_vectors", symbol=symbol, tf=tf)
                return _EMPTY_SYMBOL_RESULT

            n_raw_bars = len(bar_ts_list)
            bar_ts_arr = np.array(bar_ts_list)
            del bar_ts_list
            regime_arr = np.array(regime_list)
            del regime_list
            # float32: see the analogous cross-sectional comment in
            # _compute_cross_sectional_tf -- rank-based IC doesn't need float64 raw values.
            X_raw = acc.finalize()

            # ------------------------------------------------------------------
            # Load forward returns aligned by bar_ts
            # ------------------------------------------------------------------
            return_cols = ", ".join(f"return_{s}" for s in scales)
            complete_cols = ", ".join(f"complete_{s}" for s in scales)
            fr_sql = f"""
                SELECT bar_ts, {return_cols}, {complete_cols}
                FROM forward_returns
                WHERE symbol = %s AND tf = %s AND bar_ts <= %s
                  AND return_type = 'executable_open_to_open'
                ORDER BY bar_ts
            """
            with conn.cursor() as cur:
                cur.execute(fr_sql, (symbol, tf, training_window_end))
                fr_rows = cur.fetchall()

            if not fr_rows:
                _logger.info("ic_engine.no_forward_returns", symbol=symbol, tf=tf)
                return _EMPTY_SYMBOL_RESULT

            fr_ts = {r[0]: r for r in fr_rows}
            del fr_rows  # dict lookup is sufficient; raw tuples no longer needed

            # Align feature matrix to forward_returns rows (exact bar_ts match)
            aligned_idx = [i for i, ts in enumerate(bar_ts_arr) if ts in fr_ts]
            if not aligned_idx:
                _logger.info("ic_engine.no_alignment", symbol=symbol, tf=tf)
                return _EMPTY_SYMBOL_RESULT

            aligned_idx_arr = np.array(aligned_idx)
            X_aligned = X_raw[aligned_idx_arr]
            del X_raw  # fancy index produces a copy; original no longer needed
            regime_aligned = regime_arr[aligned_idx_arr]
            del regime_arr
            bar_ts_aligned = bar_ts_arr[aligned_idx_arr]
            del bar_ts_arr

            n_scales = len(scales)
            # returns_mat: [n_aligned, n_scales]; complete_mat: [n_aligned, n_scales]
            returns_mat = np.full((len(aligned_idx), n_scales), np.nan)
            complete_mat = np.zeros((len(aligned_idx), n_scales), dtype=bool)
            for i, ts in enumerate(bar_ts_aligned):
                row = fr_ts[ts]
                for j in range(n_scales):
                    returns_mat[i, j] = row[1 + j] if row[1 + j] is not None else np.nan
                    complete_mat[i, j] = bool(row[1 + n_scales + j])
            del fr_ts  # returns_mat/complete_mat are sufficient; dict no longer needed

        # Regime source: market_regimes (cross-sectional) or feature_vectors.regime_volatility
        # (per-symbol, calm/elevated/turbulent -- Phase 172 plan 06 repoint).
        # When mr_dict is provided, map each aligned bar_ts to its cross-sectional regime.
        # Bars without a market_regimes entry get None (excluded from regime-stratified IC).
        # cross_sectional feeds _resolve_regime_scope for every non-pooled row this
        # (symbol, tf) computes -- it reflects the label SOURCE, not the label string.
        cross_sectional = mr_dict is not None
        if cross_sectional:
            # equity_model_enabled=True: use cross-sectional labels from market_regimes
            regime_aligned_market = np.array([mr_dict.get(ts) for ts in bar_ts_aligned])
            distinct_regimes = [r for r in set(regime_aligned_market) if r is not None]
        else:
            # equity_model_enabled=False: fallback to feature_vectors.regime_volatility
            # (per-symbol, calm/elevated/turbulent). Phase 172 plan 06 repoint.
            regime_aligned_market = regime_aligned
            distinct_regimes = [r for r in set(regime_aligned) if r is not None]

        # Pooled pass -- always exactly once, regardless of how many regime-label
        # sources this (symbol, tf) computes. Pooled doesn't condition on regime
        # labels at all (mask = all rows), so running it per label-source would
        # silently duplicate the identical (feature, symbol, tf, lookahead,
        # is_pooled=True) cell.
        all_results: list[dict] = []
        pvals_flat: list[float] = []
        pval_result_idxs: list[int] = []
        n_committed = 0
        n_skipped = 0
        skip_reasons: dict[str, int] = {}

        pooled_rows, pooled_skipped, pooled_skip_reasons = _compute_one_regime_cell(
            _POOLED_REGIME_SENTINEL,
            True,
            np.ones(len(aligned_idx), dtype=bool),
            _resolve_regime_scope(True, cross_sectional),
            X_aligned=X_aligned,
            returns_mat=returns_mat,
            complete_mat=complete_mat,
            config=config,
            symbol=symbol,
            tf=tf,
            rng=rng,
            training_window_end=training_window_end,
            feature_status_map=feature_status_map,
            run_ts=run_ts,
        )
        all_results.extend(pooled_rows)
        n_skipped += pooled_skipped
        _merge_skip_reasons(skip_reasons, pooled_skip_reasons)

        # Primary pass (today's exact existing behavior) + optional symbol_hmm pass
        # (restore per-symbol-HMM-regime-stratified measurement for regime-group-routed
        # symbols) share the same per-label-array loop shape, built by
        # _build_regime_passes (extracted pure helper, Phase 151 Plan 02) rather than
        # duplicated inline. distinct_regimes is computed once above (/simplify
        # finding: it was previously dead code, recomputed via a second full set()
        # pass over regime_aligned_market) and passed straight through. Two
        # independent gates decide whether the symbol_hmm pass runs, both require
        # cross_sectional=True: dual_write_symbol_hmm (per-group field,
        # alpha.regime.groups[*], live: rates only, migration 247) OR
        # cluster_regime_conditioned (Phase 151 Plan 02's run-level APR switch,
        # migration 286, making the second stratification axis unconditional across
        # every routed symbol). See _build_regime_passes' own docstring for the
        # no-double-append guarantee.
        regime_passes = _build_regime_passes(
            regime_aligned_market,
            distinct_regimes,
            regime_aligned,
            cross_sectional,
            dual_write_symbol_hmm,
            cluster_regime_conditioned,
            _resolve_regime_scope(False, cross_sectional),
        )

        for label_array, labels_this_pass, resolved_scope in regime_passes:
            for regime_label in labels_this_pass:
                pass_rows, pass_skipped, pass_skip_reasons = _compute_one_regime_cell(
                    regime_label,
                    False,
                    label_array == regime_label,
                    resolved_scope,
                    X_aligned=X_aligned,
                    returns_mat=returns_mat,
                    complete_mat=complete_mat,
                    config=config,
                    symbol=symbol,
                    tf=tf,
                    rng=rng,
                    training_window_end=training_window_end,
                    feature_status_map=feature_status_map,
                    run_ts=run_ts,
                )
                all_results.extend(pass_rows)
                n_skipped += pass_skipped
                _merge_skip_reasons(skip_reasons, pass_skip_reasons)

        # ------------------------------------------------------------------
        # BH-FDR correction -- representative-only per (regime, lookahead, cluster)
        #
        # Within each (regime_label, lookahead_bars, cluster_id) group only the
        # feature with max(abs(ic_value)) enters multipletests. Non-representatives
        # receive passes_fdr=False and bh_adjusted_p=None directly. Degenerate
        # features (cluster_id is None) are also excluded from BH-FDR.
        # ------------------------------------------------------------------

        # ------------------------------------------------------------------
        # Cluster representative selection for corpus-level BH-FDR (P2 fix).
        #
        # Within each (regime_label, lookahead_bars, cluster_id) group only the
        # feature with max(abs(ic_value)) is a representative. Non-representatives
        # receive passes_fdr=False and bh_adjusted_p=None immediately.
        # Representatives' p-values are returned to the main process for a single
        # corpus-level BH-FDR pass across all 58 symbols × 4 TFs = 232 cells.
        # Degenerate features (cluster_id is None) are excluded from BH-FDR.
        # ------------------------------------------------------------------
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

        # BH-FDR is NOT applied here (P2 fix). pvals_flat and pval_result_idxs are
        # returned to the caller (_run_ic_worker -> main process) for corpus-level FDR.

        # ------------------------------------------------------------------
        # Prepare rows for batch INSERT (written by main process after corpus BH-FDR)
        # ------------------------------------------------------------------
        pooled_rows = [r for r in all_results if r["is_pooled"]]
        regime_rows = [r for r in all_results if not r["is_pooled"]]

        n_committed = len(all_results)

        # ------------------------------------------------------------------
        # Per-cell OTel metrics -- computed here (pure, no OTel calls), emitted by
        # the caller in the main process (todo 009/2026-07-31 fix). This function
        # runs inside a ProcessPoolExecutor worker with no metrics exporter
        # initialized (_run_ic_worker: "No OTel tracer -- workers log only") --
        # calling any counter/gauge instrument's add-or-set method directly from
        # here would silently no-op forever, exactly as it did before this fix.
        # cell_emissions/n_passing_wf/skip_reasons flow back through
        # _run_ic_worker's return dict instead.
        #
        # all_results is populated by 1 pooled call above plus a loop over
        # 1-or-2 regime_passes (primary, and optionally a dual-write
        # symbol_hmm pass -- see regime_passes construction above).
        # _group_cells_for_metrics groups on (regime, is_pooled, regime_scope)
        # so a dual-write symbol_hmm cell never gets conflated with a primary
        # cross-sectional cell sharing the same HMM regime label string.
        # ------------------------------------------------------------------
        cell_emissions = _group_cells_for_metrics(all_results, symbol, tf)
        n_passing_wf = sum(1 for r in all_results if r.get("passes_walkforward"))

        return (
            pooled_rows,
            regime_rows,
            {
                "n_committed": n_committed,
                "n_skipped": n_skipped,
                "n_passing_wf": n_passing_wf,
                "all_results": all_results,
                "pvals_flat": pvals_flat,
                "pval_result_idxs": pval_result_idxs,
                "skip_reasons": skip_reasons,
                "cell_emissions": cell_emissions,
            },
        )


# ---------------------------------------------------------------------------
# Cross-sectional IC computation (equity_model_enabled=True)
# ---------------------------------------------------------------------------


def _cross_sectional_vol_normalized_target(
    X_sub: np.ndarray, valid_mask: np.ndarray, returns_scale: np.ndarray
) -> np.ndarray:
    """Vol-normalized POOLED-strata return target (Component F, todo 097).

    Produces the vol-normalized return array from arrays already assembled inside
    `_compute_cross_sectional_tf`'s per-scale loop -- `X_sub` (raw, unranked,
    all-feature array fetched by the existing `chunk_sql` query, no new SELECT),
    `valid_mask` (the same completeness/finite-value mask gating the production
    `X_raw_scale`/`Y_scale` arrays), and `returns_scale` (the raw forward-return
    column for this scale, sourced from the same `fr.return_type =
    'executable_open_to_open'`-filtered query -- Invariant 1 untouched, no new
    query, no new join).

    NOT called from `_compute_cross_sectional_tf`'s production path -- this is
    reachable/importable measurement-time diagnostic scaffolding for
    `scripts/ops/alpha/ops_vol_normalized_target_ab.py`'s explicit A/B (Component F's
    locked validation contract: never a silent production-target swap; retire the
    transform if vol-normalized rankings are materially identical to raw). Callable
    directly from inside `_compute_cross_sectional_tf` too, at the same point
    `X_raw_scale`/`Y_scale` are sliced (both already index with the identical
    `valid_mask`), if a future decision promotes this to production.

    Args:
        X_sub: Shape [n_independent, n_features] -- ALL features (not just
            non-degenerate), pre-`valid_mask`, for this scale's stride subsample.
        valid_mask: Shape [n_independent] -- completeness & finite-return mask,
            identical to the one gating `X_raw_scale`/`Y_scale` in the caller.
        returns_scale: Shape [n_independent] -- raw forward-return column for this
            scale, pre-`valid_mask`.

    Returns:
        Shape [n_valid] -- vol-normalized target aligned 1:1 with `Y_scale`.
    """
    tr_idx = _FEATURE_NAMES.index("true_range_pct")
    true_range_pct_scale = X_sub[valid_mask, tr_idx]
    Y_scale = returns_scale[valid_mask]
    return vol_normalized_return(Y_scale, true_range_pct_scale)


def _compute_one_cross_sectional_cell(
    regime_label: str,
    *,
    X_raw: np.ndarray,
    returns_mat: np.ndarray,
    complete_mat: np.ndarray,
    config: ICEngineConfig,
    tf: str,
    rng: np.random.Generator,
    training_window_end: Any,
    feature_status_map: dict[str, str] | None,
    run_ts: datetime,
    prior_e_values: dict[tuple[str, int], float],
) -> tuple[list[dict], int]:
    """Compute clustering + per-scale IC/CI/walk-forward/Sharpe for ONE cross-sectional cell.

    Extracted from _compute_cross_sectional_tf's inline per-scale loop (162-01 Task 3,
    todos 139/140), mirroring _compute_one_regime_cell's shape on the per-symbol side.
    Unlike _compute_one_regime_cell, X_raw/returns_mat/complete_mat here are ALREADY the
    full cell's pooled cross-symbol data -- the caller's chunked fetch scopes to exactly
    this (tf, regime_label) cell, so there is no additional `mask` selection step (cross-
    sectional cells are fetched one at a time, not sliced out of a larger per-symbol array).

    Preserves the two cross-sectional-only extras _compute_one_regime_cell's per-symbol
    path lacks: the e-value-pilot cumulative_e_value column (Component C, todo 079, tf=5m
    POOLED cells only, via prior_e_values) and the max_workers= bootstrap knob
    (config.cross_sectional_bootstrap_threads[tf], todo 131/133 -- safe to raise here
    since this pass runs single-process, after the per-symbol ProcessPoolExecutor pool
    has shut down).

    rng is a shared, stateful np.random.Generator -- calling this function consumes draws
    from it by design (matches _compute_one_regime_cell's per-worker RNG-scope contract).

    Returns (result_rows, n_skipped_features) for this cell only. Does NOT populate
    pvals_flat/pval_result_idxs or run cluster-representative selection -- that stays in
    the caller (_compute_cross_sectional_tf), same division of responsibility as
    _compute_one_regime_cell/_compute_symbol_tf.
    """
    lookaheads = config.lookaheads_for(tf)
    subsample_min_stride = config.subsample_min_stride
    min_reliable_n = config.min_reliable_n
    walk_forward_folds = config.walk_forward_folds
    cluster_max_corr = config.cluster_max_corr
    n_features = len(_FEATURE_NAMES)
    scales = config.active_scales_for(tf)

    n_raw = len(X_raw)

    _check_cell_size(n_raw, config, f"Cross-sectional cell tf={tf} regime={regime_label}")

    # Degenerate feature detection. dtype=float64 here despite X_raw being float32:
    # this reduction produces only an n_features-length result (cheap either way), and
    # forcing float64 accumulation keeps the 1e-8 threshold check exactly as precise
    # as before the float32 memory optimization above -- variance is sensitive to
    # accumulation precision in a way rank order is not.
    feature_stds = np.std(X_raw, axis=0, dtype=np.float64)
    degenerate_mask = feature_stds < 1e-8
    non_degenerate_mask = ~degenerate_mask
    X_nd = X_raw[:, non_degenerate_mask]

    n_skipped = int(degenerate_mask.sum())
    if X_nd.shape[1] == 0:
        return [], n_skipped

    cluster_ids_nd = _cluster_features(X_nd, cluster_max_corr)
    cluster_id_full = expand_int(cluster_ids_nd, non_degenerate_mask, n_features)

    all_results: list[dict] = []

    for scale_idx, scale in enumerate(scales):
        lookahead_bars = lookaheads[scale]
        # Scale-specific embargo: each scale purges only its own lookahead window (P3 fix).
        embargo_bars = lookahead_bars
        scale_stride = max(subsample_min_stride, lookahead_bars)
        # Slice, not fancy-index (2026-07-19 OOM fix): regular-stride subsampling
        # is exactly expressible as a basic slice, which numpy returns as a VIEW
        # sharing memory with X_raw/X_nd -- arr[np.arange(0, n, stride)] would
        # instead allocate a full copy. Eliminates 2 more full-cell-sized
        # allocations from the peak (alongside the rankdata float32 cast below)
        # for the largest cross-sectional cells.
        X_sub = X_raw[0:n_raw:scale_stride]
        X_sub_nd = X_nd[0:n_raw:scale_stride]
        returns_sub = returns_mat[0:n_raw:scale_stride]
        complete_sub = complete_mat[0:n_raw:scale_stride]
        n_independent = len(X_sub)

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

        # -------------------------------------------------------
        # Shared feature-blocked rank -> IC -> circular block bootstrap CI ->
        # walk-forward fold pipeline (162-01 Task 3, todos 139/140). Cross-
        # sectional path -- max_workers=config.cross_sectional_bootstrap_threads[tf]
        # (todo 131/133, per-tf as of migration 250): safe to raise here since this
        # pass runs single-process, after the per-symbol ProcessPoolExecutor pool
        # has already shut down.
        # -------------------------------------------------------
        (
            X_raw_scale,
            ranks_X_scale,
            ranks_Y,
            ic_vector_nd,
            p_vector_nd,
            ci_lower_nd,
            ci_upper_nd,
            fold_ics_list,
        ) = _subsample_and_rank(
            X_sub_nd,
            valid_mask,
            returns_scale,
            walk_forward_folds=walk_forward_folds,
            embargo_bars=embargo_bars,
            min_reliable_n=min_reliable_n,
            bootstrap_block_size=config.bootstrap_block_size[tf],
            bootstrap_resamples=config.bootstrap_resamples,
            rng=rng,
            max_workers=config.cross_sectional_bootstrap_threads[tf],
            feature_block_columns=config.feature_block_columns,
            bootstrap_early_stop_enabled=config.bootstrap_early_stop_enabled,
            bootstrap_early_stop_check_interval=config.bootstrap_early_stop_check_interval,
            bootstrap_early_stop_tol=config.bootstrap_early_stop_tol,
            bootstrap_early_stop_min_resamples=config.bootstrap_early_stop_min_resamples,
            bootstrap_early_stop_stable_checks=config.bootstrap_early_stop_stable_checks,
        )
        Y_scale = returns_scale[valid_mask]

        ic_full = _expand(ic_vector_nd, non_degenerate_mask, n_features)
        p_full = _expand(p_vector_nd, non_degenerate_mask, n_features)

        ci_lower_full = _expand(ci_lower_nd, non_degenerate_mask, n_features)
        ci_upper_full = _expand(ci_upper_nd, non_degenerate_mask, n_features)
        passes_ci_full = np.where(non_degenerate_mask, ci_lower_full > 0.0, False)

        wf_fold_count = len(fold_ics_list)
        if wf_fold_count > 0:
            fold_ic_arr = np.array(fold_ics_list)
            wf_pass_count_nd = _sign_consistent_wf_pass_count(fold_ic_arr, ic_vector_nd)
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
                config,
                non_degenerate_mask,
                n_features,
                scale_stride,
            )
        )

        # IC decomposition: sign_hit_rate + magnitude-conditional IC (Component B,
        # todo 090). Diagnostic-only columns, no gate impact. Reuses X_raw_scale/
        # Y_scale already assembled above for the bootstrap CI.
        sign_hit_rate_nd = sign_hit_rate(X_raw_scale, Y_scale)
        magnitude_ic_nd = magnitude_conditional_ic(X_raw_scale, Y_scale, _MAGNITUDE_IC_PERCENTILE)
        sign_hit_rate_full = _expand(sign_hit_rate_nd, non_degenerate_mask, n_features)
        magnitude_ic_full = _expand(magnitude_ic_nd, non_degenerate_mask, n_features)

        for feat_idx, feat_name in enumerate(_FEATURE_NAMES):
            # 162-03: no per-feature already-present skip -- the whole-cell
            # fingerprint gate in main() is the sole skip decision.
            ic_val = ic_full[feat_idx]
            p_val = p_full[feat_idx]
            ic_sign_val = None if np.isnan(ic_val) else (1 if ic_val > 0 else -1)

            # e-value pilot (Component C, todo 079): tf=5m POOLED cross-sectional
            # cells ONLY. Reads this cell's prior cumulative e-value (prior_e_values,
            # fetched once by the caller; defaults to the neutral prior 1.0 on first
            # look) and multiplies in this run's e-value factor -- evidence compounds
            # across corpus reruns instead of resetting each build.
            cumulative_e_value = (
                update_cumulative_e_value(
                    prior_e_values.get((feat_name, lookahead_bars), 1.0),
                    ic_sign_val,
                )
                if _e_value_pilot_active(tf)
                else None
            )

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
                    "ic_sign": ic_sign_val,
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
                    "regime_scope": "cross_sectional",
                    "sign_hit_rate": _nan_to_none(sign_hit_rate_full[feat_idx]),
                    "magnitude_conditional_ic": _nan_to_none(magnitude_ic_full[feat_idx]),
                    "cumulative_e_value": cumulative_e_value,
                }
            )

    return all_results, n_skipped


def _compute_cross_sectional_tf(
    dsn: str,
    tf: str,
    regime_label: str,
    regime_group: str,
    symbol_list: list[str],
    training_window_end: Any,
    config: ICEngineConfig,
    tracer: Any,
    run_ts: datetime,
    rng: np.random.Generator,
    feature_status_map: dict[str, str] | None = None,
) -> tuple[list[dict], dict[str, Any]]:
    """Compute cross-sectional IC for one (regime_group, tf, regime_label) cell.

    Fetches feature_vectors JOIN forward_returns for ALL symbols in symbol_list
    (regime_group's own peer symbols, resolved by the caller from
    symbol_regime_class) pooled into a single observation set. Computes Spearman
    IC across all peer symbols simultaneously -- each (bar_ts, symbol) pair is an
    independent observation.

    Broadcast-feature significance correction (Phase 173, todo 270): this independence
    assumption is false for symbol-invariant (broadcast) features -- the same value
    repeated across every symbol in a cell is not 231 independent observations of the
    underlying signal, it is one observation duplicated 231 times. Broadcast features
    are excluded from this cell's matrix and measured separately, in their own cell,
    against an equal-weighted market-aggregate return; classification is read from
    `concept_registry.metadata->>'broadcast'`, not a hand-maintained frozenset -- see
    todo 270's design rationale for why a hardcoded list (this module's now-deleted
    bespoke daily-cadence frozenset was the cautionary example) does not scale to the
    full broadcast population.

    symbol_list is THE contamination fix (Phase 144 D-01): before this, every
    symbol in the corpus (fi_* bonds, GLD/SLV/VNQ, IBIT) was pooled into every
    cross-sectional cell regardless of regime_group, because chunk_sql had no
    symbol filter at all -- only a bar_ts filter derived from a market_regimes
    timestamp prefetch that was itself hardcoded to the (now-renamed, migration
    229) equity-only asset class column.

    No DB writes — returns (all_results, stats_dict). Writes happen serially in main
    process via _write_cross_sectional_results.

    dsn: connection string, not a live connection (todo 125, 2026-07-17). This function
    opens one short-lived connection internally for the e-value/regime-timestamp
    prefetch and the chunked feature/return fetch, then closes it before the
    clustering + circular block bootstrap resampling phase -- which routinely runs for
    hours with zero DB traffic. Same defect and same fix as _compute_symbol_tf's
    todo-102 fix (2026-07-12), just never generalized to this sibling function: the
    143.1-07 corpus re-run crashed twice at the identical transition point (one cell
    finishes its multi-hour compute, the next cell's first query dies on
    "server closed the connection unexpectedly" -- the connection sat idle across the
    whole compute phase and was silently killed at some point before the code returned
    to use it again).

    The result is stored with symbol=_CROSS_SECTIONAL_SYMBOL ('POOLED'), is_pooled=True,
    regime=regime_label (actual label, not '_pooled' sentinel). regime_group is NOT
    persisted on the result row -- feature_ic_scores has no regime_group column;
    group identity stays implicit in regime_label string uniqueness across enabled
    groups (see cross_sectional_regime_model.py's _assign_labels docstring for the
    label-vocabulary-uniqueness invariant this relies on).

    rng: worker-safe circular block bootstrap RNG (Component A, todo 091) -- this pass
    runs single-process (not ProcessPoolExecutor), so the caller derives one seed via
    _derive_worker_rng_seed() and shares/advances it across every (regime_group, tf,
    regime_label) cell in the cross-sectional loop, same reuse-not-reseed convention
    as the per-symbol worker path.

    Returns dict with n_committed, n_skipped, all_results.
    """
    # Only n_features/cs_chunk_ts are needed directly in this function's own fetch
    # code below -- subsample_min_stride/min_reliable_n/fdr_alpha/walk_forward_folds/
    # cluster_max_corr/lookaheads moved into _compute_one_cross_sectional_cell
    # (162-01 Task 3), which pulls them from `config` itself rather than receiving
    # them as separate params, matching _compute_one_regime_cell's convention.
    n_features = len(_FEATURE_NAMES)
    scales = config.active_scales_for(tf)

    cs_chunk_ts: int = config.cs_chunk_ts

    # 162-03: no whole-regime already-present short-circuit here -- the whole-cell
    # fingerprint gate in main() decides skip/compute for this (regime_group, tf,
    # regime_label) cell BEFORE this function is ever called, replacing this
    # short-circuit entirely (it ran a data fetch's worth of nothing anyway; the
    # fingerprint gate skips the call outright).

    # Short-lived fetch connection (todo 125, 2026-07-17) -- opened here, closed as
    # soon as the chunked feature/return fetch below completes. It must not stay open
    # across the clustering/bootstrap loop that follows (see dsn note in the
    # docstring). Session tuning for the large cross-sectional join (disable parallel
    # workers, raise work_mem) is per-connection, so it's applied fresh here rather
    # than once on a long-lived caller connection as before.
    with short_lived_conn(dsn) as conn:
        with conn.cursor() as tune_cur:
            tune_cur.execute("SET max_parallel_workers_per_gather = 0")
            tune_cur.execute("SET work_mem = '256MB'")
        conn.commit()

        # e-value pilot (Component C, todo 079): tf=5m POOLED cross-sectional cells ONLY
        # (_e_value_pilot_active gate) -- fetch this cell's prior cumulative_e_value per
        # (feature_name, lookahead_bars), one batched query per (tf, regime_label) call
        # rather than per-feature, so evidence compounds across corpus reruns instead of
        # resetting each build. DISTINCT ON picks the most recent PRIOR training_window_end
        # (strictly before this run's) per cell -- a feature/lookahead pair with no prior
        # row (first-ever look) is absent from the dict and defaults to the neutral prior
        # of 1.0 at the per-feature lookup site below.
        prior_e_values: dict[tuple[str, int], float] = {}
        if _e_value_pilot_active(tf):
            with conn.cursor() as e_val_cur:
                e_val_cur.execute(
                    """
                    SELECT DISTINCT ON (feature_name, lookahead_bars)
                        feature_name, lookahead_bars, cumulative_e_value
                    FROM feature_ic_scores
                    WHERE symbol = %(symbol)s AND tf = %(tf)s AND regime = %(regime_label)s
                      AND is_pooled = true AND training_window_end < %(training_window_end)s
                    ORDER BY feature_name, lookahead_bars, training_window_end DESC
                    """,
                    {
                        "symbol": _CROSS_SECTIONAL_SYMBOL,
                        "tf": tf,
                        "regime_label": regime_label,
                        "training_window_end": training_window_end,
                    },
                )
                for _feat_name, _lookahead, _cumulative in e_val_cur.fetchall():
                    if _cumulative is not None:
                        prior_e_values[(_feat_name, _lookahead)] = float(_cumulative)
            conn.commit()

        feature_cols = ", ".join(f'"fv"."{f}"' for f in _FEATURE_NAMES)
        return_cols = ", ".join(f'"fr".return_{s}' for s in scales)
        complete_cols = ", ".join(f'"fr".complete_{s}' for s in scales)

        # Step 1: Pre-fetch regime timestamps.
        # market_regimes has one row per (tf, ts, regime_label) -- e.g. 120K rows for
        # 5m/low_bull over the full training window.  This result set is small (120K
        # datetime objects) and fast to fetch.
        with conn.cursor() as ts_cur:
            ts_cur.execute(
                """
                SELECT ts FROM market_regimes
                WHERE regime_group = %(regime_group)s
                  AND tf = %(tf)s
                  AND regime_label = %(regime_label)s
                  AND ts <= %(training_window_end)s
                ORDER BY ts
                """,
                {
                    "regime_group": regime_group,
                    "tf": tf,
                    "regime_label": regime_label,
                    "training_window_end": training_window_end,
                },
            )
            regime_timestamps = [r[0] for r in ts_cur.fetchall()]
        conn.commit()

        if not regime_timestamps:
            _logger.info(
                "ic_engine.cross_sectional_no_data",
                tf=tf,
                regime=regime_label,
            )
            return [], {"n_committed": 0, "n_skipped": 0}

        # Step 2: Query feature_vectors+forward_returns in timestamp chunks.
        # Replaces a 3-way JOIN (feature_vectors × market_regimes × forward_returns) that
        # caused the PostgreSQL backend to OOM for large regimes:
        #   5m/low_bull: 120K regime timestamps × 58 symbols = 7M rows in one query.
        # Chunked approach: cs_chunk_ts timestamps × 58 symbols ≈ 290K rows/query at
        # default cs_chunk_ts=5000.  Fits comfortably in PostgreSQL working memory.
        # feature_vectors.bar_ts is TF-bucket-aligned, so bar_ts = ANY(ts_chunk) is
        # equivalent to time_bucket(interval, bar_ts) = ANY(ts_chunk) and uses the index.
        # Rule 3 auto-fix: blocking PostgreSQL backend OOM on 3-way JOIN.
        # symbol = ANY(%(symbol_list)s): THE contamination fix (Phase 144 D-01) -- without
        # this filter every symbol in the corpus (not just this regime_group's peers) was
        # pooled into this cell, since ts_chunk alone doesn't scope by symbol.
        chunk_sql = f"""
            SELECT fv.bar_ts, {feature_cols}, {return_cols}, {complete_cols}
            FROM feature_vectors fv
            INNER JOIN forward_returns fr
                ON fr.symbol = fv.symbol
                AND fr.tf = fv.tf
                AND fr.bar_ts = fv.bar_ts
                AND fr.return_type = 'executable_open_to_open'
            WHERE fv.tf = %(tf)s
              AND fv.bar_ts = ANY(%(ts_chunk)s)
              AND fv.symbol = ANY(%(symbol_list)s)
            ORDER BY fv.bar_ts
        """

        n_scales = len(scales)
        # Float32ChunkAccumulator (todo 087) owns the buffer-to-array bookkeeping shared
        # with _compute_symbol_tf's own OOM fix above; the ts_chunk re-execution mechanics
        # and the ret/cmp matrices (different dtypes, NULL-substitution logic -- not the
        # same shape as X) stay here.
        X_acc = Float32ChunkAccumulator()
        ret_chunks: list[np.ndarray] = []
        cmp_chunks: list[np.ndarray] = []

        _logger.info(
            "ic_engine.cross_sectional_chunk_pass",
            tf=tf,
            regime=regime_label,
            n_regime_ts=len(regime_timestamps),
            cs_chunk_ts=cs_chunk_ts,
            n_chunks=(len(regime_timestamps) + cs_chunk_ts - 1) // cs_chunk_ts,
        )

        for chunk_start in range(0, len(regime_timestamps), cs_chunk_ts):
            ts_chunk = regime_timestamps[chunk_start : chunk_start + cs_chunk_ts]
            with conn.cursor() as chunk_cur:
                chunk_cur.execute(
                    chunk_sql,
                    {"tf": tf, "ts_chunk": ts_chunk, "symbol_list": symbol_list},
                )
                batch = chunk_cur.fetchall()
            conn.commit()
            if not batch:
                continue
            n_batch = len(batch)
            # float32, not float64: every downstream use of this array (_vectorized_ic,
            # _compute_ic_rolling_metrics) ranks it via rankdata() and computes statistics
            # on the resulting ranks/IC values, never on the raw floats directly -- rank
            # order is preserved essentially perfectly at float32 precision for z-score/
            # ratio-scale feature values. Halves the memory of X_raw, X_nd, and every
            # per-scale subsample copy below -- the direct fix for the 2026-07-08 OOM
            # incidents, where the largest cross-sectional cell (5m/low_bull, ~9.4M rows
            # x 152 features after the 80-symbol ETF expansion) peaked at 20GB+ RSS.
            X_acc.append_chunk([[r[i + 1] for i in range(n_features)] for r in batch])
            ret_chunk = np.full((n_batch, n_scales), np.nan)
            cmp_chunk = np.zeros((n_batch, n_scales), dtype=bool)
            for i, row in enumerate(batch):
                for j in range(n_scales):
                    val = row[1 + n_features + j]
                    ret_chunk[i, j] = val if val is not None else np.nan
                    cmp_chunk[i, j] = bool(row[1 + n_features + n_scales + j])
            ret_chunks.append(ret_chunk)
            cmp_chunks.append(cmp_chunk)

    X_raw = X_acc.finalize()
    if X_raw is None:
        _logger.info(
            "ic_engine.cross_sectional_no_data",
            tf=tf,
            regime=regime_label,
        )
        return [], {"n_committed": 0, "n_skipped": 0}

    returns_mat = np.vstack(ret_chunks)
    del ret_chunks
    complete_mat = np.vstack(cmp_chunks)
    del cmp_chunks
    n_raw = len(X_raw)

    # 162-01 Task 3: clustering + per-scale IC/CI/walk-forward/Sharpe compute
    # extracted into _compute_one_cross_sectional_cell, mirroring
    # _compute_one_regime_cell's shape on the per-symbol side. This function keeps
    # only the fetch phase (above), the crash-loud row-count ceiling and per-scale
    # compute (inside the extracted function), and cluster-representative
    # selection for corpus-level BH-FDR (below) -- same division of
    # responsibility as _compute_symbol_tf/_compute_one_regime_cell.
    all_results, n_skipped = _compute_one_cross_sectional_cell(
        regime_label,
        X_raw=X_raw,
        returns_mat=returns_mat,
        complete_mat=complete_mat,
        config=config,
        tf=tf,
        rng=rng,
        training_window_end=training_window_end,
        feature_status_map=feature_status_map,
        run_ts=run_ts,
        prior_e_values=prior_e_values,
    )
    pvals_flat: list[float] = []
    pval_result_idxs: list[int] = []

    # Cluster representative selection for corpus-level BH-FDR (P2 fix).
    # Non-representatives are marked immediately; representatives' p-values
    # are returned to the main process for the single corpus-level FDR pass.
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

    # BH-FDR is NOT applied here (P2 fix). pvals_flat and pval_result_idxs are
    # returned to main process for corpus-level FDR.
    n_committed = len(all_results)
    return (
        all_results,
        {
            "n_committed": n_committed,
            "n_skipped": n_skipped,
            "pvals_flat": pvals_flat,
            "pval_result_idxs": pval_result_idxs,
        },
    )


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
# Serial write function (called in main process only)
# ---------------------------------------------------------------------------


def _write_ic_results(
    conn: Any,
    pooled_rows: list[dict],
    regime_rows: list[dict],
) -> int:
    """Write IC results to feature_ic_scores in main process.

    Runs serially in main process — single write connection, no concurrent writers.
    Returns n_committed.
    """
    n_committed = 0
    if pooled_rows:
        with conn.cursor() as cur:
            cur.executemany(_POOLED_INSERT_SQL, pooled_rows)
        n_committed += len(pooled_rows)
        # Commit now rather than batching with regime_rows below: regime_rows is
        # typically far larger, and ON CONFLICT DO NOTHING makes an early commit
        # safe to re-run into -- a failure partway through regime_rows no longer
        # loses the already-computed pooled_rows write too.
        conn.commit()
    if regime_rows:
        with conn.cursor() as cur:
            cur.executemany(_REGIME_INSERT_SQL, regime_rows)
        n_committed += len(regime_rows)
    conn.commit()
    return n_committed


def _normalized_source_for_hash(source: bytes) -> bytes:
    """AST-normalized source bytes for content hashing.

    Comments and whitespace/formatting are never part of the AST, so they drop
    out for free; docstrings (the first `Expr`/`Constant` string statement in a
    module/function/class body) are explicitly blanked below. Without this, a
    pure comment or docstring reword -- e.g. the actual todo-165 commit
    "reword post-merge-caught comment tripping causal-safety lint" -- moves the
    hash exactly as much as a real logic change, forcing a multi-day corpus run
    to discard and recompute everything for a edit that alters zero computed
    output. Falls back to the raw bytes on a parse failure: that only makes the
    hash MORE change-sensitive for that one file, never masks a real change, so
    it's a safe direction to fail in.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return source
    docstring_holders = (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
    for node in ast.walk(tree):
        if not isinstance(node, docstring_holders) or not node.body:
            continue
        first = node.body[0]
        if (
            isinstance(first, ast.Expr)
            and isinstance(first.value, ast.Constant)
            and isinstance(first.value.value, str)
        ):
            first.value.value = ""
    return ast.dump(tree).encode()


def _checkpoint_content_key() -> str:
    """Content hash of every first-party module actually imported into this process.

    A checkpoint computed under one version of ic_engine's code is not safe to
    blindly reuse under another -- 2026-07-12 found a corpus rerun computing 5h of
    results against stale routing logic while a concurrent session merged Phase
    144's regime_group fix underneath it. Keying checkpoints to a content hash
    means a real code change automatically invalidates old checkpoints (they
    simply won't be found under the new directory) instead of silently being
    replayed.

    Previously keyed on `git rev-parse --short HEAD`, which invalidates on *any*
    commit landing anywhere in the repo -- 2026-07-15 lost ~31h of a multi-day
    corpus run's checkpoints to an unrelated merge (a diagnostic-tooling branch
    that never touched ic_engine.py or its dependencies) shifting HEAD's hash.
    Hashing sys.modules instead of a hand-maintained import list means the
    dependency set can't silently drift out of date as ic_engine's real imports
    change -- it's derived from what Python actually loaded, including the full
    transitive graph, not from a list a future edit could forget to update.

    Hashes AST-normalized source (`_normalized_source_for_hash`), not raw bytes
    (2026-07-29 rca_analysis, todo 198): comment/docstring-only edits to any of
    the ~30 transitively-loaded first-party modules were forcing full recompute
    of multi-day runs for changes that alter zero computed output -- confirmed
    against a live comment-only commit landing mid-run. A real semantic change
    still moves the hash; this only removes false positives.
    """
    repo_root = Path(__file__).resolve().parent.parent
    # Allowlist first-party source roots (Ring 0/1/2 per naming-system.md) rather
    # than blocklisting vendored paths -- a venv living somewhere unexpected
    # inside repo_root would otherwise leak in silently.
    first_party_roots = (repo_root / "src", repo_root / "services")
    hasher = hashlib.sha256()
    paths: set[Path] = set()
    for module in list(sys.modules.values()):
        module_file = getattr(module, "__file__", None)
        if not module_file:
            continue
        path = Path(module_file).resolve()
        if any(path.is_relative_to(root) for root in first_party_roots):
            paths.add(path)
    for path in sorted(paths):
        try:
            hasher.update(_normalized_source_for_hash(path.read_bytes()))
        except OSError:
            continue
    # 12 hex chars (48 bits) -- generous collision margin, short enough to stay
    # readable when embedded in a fingerprint's code_content_key field.
    return hasher.hexdigest()[:12]


# 162-03 Task 3 (todo 122): the .pkl checkpoint system (_checkpoint_dir,
# _load_checkpoint, _save_checkpoint) is deleted outright -- per-symbol immediate
# writes (_record_symbol_result -> _write_symbol_results, already unconditional
# since todo 130) plus the cross-run whole-cell fingerprint gate fully supersede
# its intra-run crash-resume purpose: a killed run simply resumes by re-running
# ic_engine.py -- fingerprint-valid completed cells skip (fetch+compute, not just
# the write), incomplete/invalidated ones recompute. This also closes todo 122's
# APR-drift surface (a stale .pkl computed under an old config could be replayed
# under a changed one) by removing the mechanism entirely rather than patching it.
# _checkpoint_content_key is KEPT -- it is reused verbatim as the fingerprint's
# code_content_key component.


def _write_symbol_results(
    settings: Settings,
    pooled_rows: list[dict],
    regime_rows: list[dict],
    conn: Any | None = None,
) -> int:
    """Write one symbol's already-computed rows to feature_ic_scores immediately
    (todo 130).

    Prior behavior held every symbol's rows in memory for the whole corpus run
    (30+ hours) and wrote them all in one call at the very end -- a crash at any
    point before that final write (e.g. during the cross-sectional pass) lost the
    entire run's compute, including this already-complete symbol. Writing here,
    right after this symbol's compute finishes, means a later crash only costs
    whatever hasn't been computed yet. bh_adjusted_p/passes_fdr are already final
    for non-representative rows (False, set by the worker) and pending (NULL) for
    cluster representatives -- _backfill_bh_fdr resolves those once the whole
    corpus is done.

    If `conn` is given, writes on it and leaves it open (caller owns the
    lifecycle -- the checkpoint-resume loop in main() shares one connection
    across all resumed symbols, since that loop has no compute between
    iterations to make an idle connection risky). Otherwise opens and closes
    its own short-lived connection, matching _compute_cross_sectional_tf's
    todo-125 fix for the ProcessPoolExecutor as_completed path, where real
    compute (waiting on other workers) happens between iterations.
    """
    if not pooled_rows and not regime_rows:
        return 0
    if conn is not None:
        return _write_ic_results(conn, pooled_rows, regime_rows)
    with _short_lived_conn(settings) as owned_conn:
        return _write_ic_results(owned_conn, pooled_rows, regime_rows)


def _record_symbol_result(
    settings: Settings,
    result: dict,
    per_symbol_results: list[tuple[str, list[dict]]],
    conn: Any | None = None,
) -> int:
    """Write one symbol's rows immediately and record them for later OTel gauge
    emission (todo 130). Shared by the checkpoint-resume path and the fresh
    ProcessPoolExecutor as_completed path in main() -- both hand this the same
    worker-result shape (symbol, pooled_rows, regime_rows, all_results) and both
    need the identical write-then-record sequence. n_skipped is not part of this
    -- callers read result["n_skipped"] directly, since one caller (the error
    branch of the as_completed loop) still needs it even though pooled_rows/
    regime_rows there may be a partial, pre-failure subset.

    `conn`: see _write_symbol_results -- pass a shared connection for the
    resume loop, leave None for the as_completed loop (own connection per
    symbol, opened right when a result arrives).

    Returns n_committed.
    """
    n_committed = _write_symbol_results(
        settings, result["pooled_rows"], result["regime_rows"], conn=conn
    )
    per_symbol_results.append((result["symbol"], result["all_results"]))
    return n_committed


def _write_cross_sectional_results(
    conn: Any,
    all_results: list[dict],
) -> int:
    """Write cross-sectional IC results to feature_ic_scores in main process.

    Runs serially in main process — single write connection, no concurrent writers.
    Returns n_committed.
    """
    if all_results:
        with conn.cursor() as cur:
            cur.executemany(_CROSS_SECTIONAL_INSERT_SQL, all_results)
        conn.commit()
    return len(all_results)


def _write_cs_cell_results(settings: Settings, cs_rows: list[dict]) -> int:
    """Write one cross-sectional cell's rows to feature_ic_scores immediately
    (todo 130), in its own short-lived connection. See _write_symbol_results for
    the crash-durability rationale; same pattern, cross-sectional pass.
    """
    if not cs_rows:
        return 0
    with _short_lived_conn(settings) as conn:
        return _write_cross_sectional_results(conn, cs_rows)


def _upsert_cell_fingerprints(settings: Settings, fp_rows: list[dict]) -> None:
    """UPSERT one or more freshly-computed cell fingerprint rows (162-03 Task 3).

    Called right after the corresponding feature_ic_scores rows are durable --
    a fingerprint row is only ever as fresh as the compute it describes. Uses
    its own short-lived connection (same pattern as _write_cs_cell_results),
    since this runs from the same as_completed/cross-sectional loop context
    that must not hold a connection idle across compute.
    """
    if not fp_rows:
        return
    with _short_lived_conn(settings) as conn:
        with conn.cursor() as cur:
            cur.executemany(_FINGERPRINT_UPSERT_SQL, fp_rows)
        conn.commit()


# feature_ic_scores' primary key (todo 307) -- same 6-column shape
# scripts/ops/alpha/ops_ic_shrinkage.py's _PK_COLS/_COL_TYPES already use for its own
# bulk_update_by_key call against this table.
_BH_FDR_KEY_COLS: list[str] = [
    "feature_name",
    "symbol",
    "tf",
    "regime",
    "lookahead_bars",
    "training_window_end",
]
_BH_FDR_SET_COLS: list[str] = ["bh_adjusted_p", "passes_fdr"]
_BH_FDR_COL_TYPES: dict[str, str] = {
    "bh_adjusted_p": "double precision",
    "passes_fdr": "boolean",
    "feature_name": "text",
    "symbol": "text",
    "tf": "text",
    "regime": "text",
    "lookahead_bars": "integer",
    "training_window_end": "timestamptz",
}


def _backfill_bh_fdr(
    conn: Any,
    training_window_end: Any,
    fdr_alpha: float,
) -> list[dict]:
    """Corpus-wide BH-FDR backfill: UPDATE-only pass over already-persisted rows
    (todo 130).

    The FDR correction is intentionally corpus-wide -- every row's pass/fail
    determination statistically depends on ranking every cluster-representative
    p-value from the entire run together (the P2 fix: per-cell FDR inflated the
    effective false-discovery rate ~232x). That corpus-wide dependency applies
    only to the p-values, not to the rows themselves, which are already durable
    by the time this runs (_write_symbol_results / _write_cs_cell_results).

    Queries the DB directly for whatever is currently pending -- rows with
    passes_fdr IS NULL -- rather than relying on in-memory bookkeeping from this
    process invocation. Non-representative and degenerate rows already have
    their final passes_fdr=False set at compute time and are never touched here;
    only cluster representatives are ever left pending. This makes the backfill
    naturally resumable: if a prior run wrote rows and crashed before reaching
    this step, a later invocation picks up exactly those pending rows regardless
    of which process wrote them, and corrects the whole set together -- still one
    multipletests() call spanning the true full corpus for this training window.

    Returns the list of {feature_name, symbol, tf, regime, lookahead_bars,
    bh_adjusted_p, passes_fdr} dicts written, so the caller can patch matching
    in-memory result dicts before emitting OTel health gauges (which must reflect
    final FDR state, not the pending-representative placeholder).
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT feature_name, symbol, tf, regime, lookahead_bars, p_value
            FROM feature_ic_scores
            WHERE training_window_end = %s AND passes_fdr IS NULL
            """,
            (training_window_end,),
        )
        pending = cur.fetchall()

    if not pending:
        return []

    pvals = [row[5] for row in pending]
    reject, p_corr = apply_bh_fdr(pvals, alpha=fdr_alpha)

    updates = [
        {
            "feature_name": row[0],
            "symbol": row[1],
            "tf": row[2],
            "regime": row[3],
            "lookahead_bars": row[4],
            "bh_adjusted_p": float(p_corr[i]),
            "passes_fdr": bool(reject[i]),
        }
        for i, row in enumerate(pending)
    ]

    # feature_ic_scores is a compressed hypertable -- this UPDATE is corpus-wide
    # within training_window_end (every pending cluster-representative row for the
    # run), the same forced-full-decompress-scan exposure every other writer against
    # this table was already fixed for (todo 307). Only the write below needs the
    # bracket -- the SELECT above reads fine against compressed chunks, no decompress
    # required for that. bulk_update_by_key (not a hand-rolled executemany() UPDATE)
    # is the established primitive for exactly this shape -- keyed on the same 6-column
    # PK ops_ic_shrinkage.py's own bulk_update_by_key call against this table already
    # uses -- and it structurally refuses to run against a compressed hypertable with
    # no active session, rather than relying only on the CI grep guard.
    with _write_session(conn, "feature_ic_scores"):
        bulk_update_by_key(
            conn,
            table="feature_ic_scores",
            temp_table="tmp_ic_engine_bh_fdr_backfill",
            key_cols=_BH_FDR_KEY_COLS,
            set_cols=_BH_FDR_SET_COLS,
            col_types=_BH_FDR_COL_TYPES,
            rows=[
                (
                    u["bh_adjusted_p"],
                    u["passes_fdr"],
                    u["feature_name"],
                    u["symbol"],
                    u["tf"],
                    u["regime"],
                    u["lookahead_bars"],
                    training_window_end,
                )
                for u in updates
            ],
        )
        conn.commit()
    return updates


# ---------------------------------------------------------------------------
# ProcessPoolExecutor worker support
# ---------------------------------------------------------------------------


def _run_ic_worker(args: tuple) -> dict:
    """Worker function for ProcessPoolExecutor -- runs in subprocess.

    Each worker processes one symbol x all TFs. No single connection is held
    across a whole symbol/tf -- _compute_symbol_tf opens and closes its own
    short-lived connections per fetch phase (todo 102 fix: a connection held
    idle across the clustering/bootstrap compute loop was getting killed by
    postgres's idle_session_timeout before ever being used again). No OTel
    tracer -- workers log only. No DB writes -- returns rows for serial write
    in main process after corpus-level BH-FDR (P2 fix).

    Args:
        args: (symbol, tfs, dsn, training_window_end, config, run_ts,
               feature_status_map, mr_dict_by_tf, dual_write_symbol_hmm,
               cluster_regime_conditioned) --
               mr_dict_by_tf is already scoped to THIS symbol's own regime_group
               (Phase 144 Plan 05: mr_dicts_by_group.get(symbol_regime_class.get(
               symbol)) in main()), never another group's labels.
               dual_write_symbol_hmm (bool) -- resolved once per symbol from its
               routed group's APR field (alpha.regime.groups[*].dual_write_symbol_hmm).
               cluster_regime_conditioned (bool) -- Phase 151 Plan 02's run-level APR
               switch (config.cluster_regime_conditioned), threaded explicitly through
               this tuple the same way dual_write_symbol_hmm is, even though it is
               also reachable via config -- keeps both symbol_hmm-pass gates visible
               at the same call-site shape.
               162-03: no existing_keys parameter -- the whole-cell fingerprint gate
               in main() is the sole skip decision, applied BEFORE a symbol is ever
               dispatched to a worker; a dispatched worker always recomputes every
               feature for every cell it touches unconditionally.

    Returns:
        dict with keys: symbol, pooled_rows (list), regime_rows (list),
        all_results (list), pvals_flat (list), pval_result_idxs (list),
        n_skipped (int), error (str|None), cell_emissions (list[tuple[dict, int]]),
        n_passing_wf_by_tf (dict[tf, int]), skip_reasons_by_tf (dict[tf, dict[str, int]]).
        The last three exist purely so the main process can emit
        IC_ENGINE_CELLS_COMPLETED_TOTAL/FEATURE_IC_PASSING_WALKFORWARD_TOTAL/
        IC_ENGINE_CELLS_SKIPPED_TOTAL itself -- this worker has no OTel exporter
        initialized (see "No OTel tracer" above), so it never calls any OTel
        instrument directly; every metric-worthy count is data until main() decides
        to emit it (todo 009/2026-07-31 fix -- these 3 metrics were previously
        emitted from inside this worker and silently never reached Prometheus).
    """
    (
        symbol,
        tfs,
        dsn,
        training_window_end,
        config,
        run_ts,
        feature_status_map,
        mr_dict_by_tf,
        dual_write_symbol_hmm,
        cluster_regime_conditioned,
    ) = args

    from src.core.service_utils import setup_service_logging

    setup_service_logging("logs/ic_engine.log")
    worker_log = structlog.get_logger(__name__)

    noop_tracer = _NoopTracer()

    # Circular block bootstrap CI (Component A, todo 091): ONE deterministic RNG per
    # symbol, derived from bootstrap_seed, shared/advanced across every tf/regime/scale
    # cell this worker computes for this symbol (never re-seeded per-cell -- matches the
    # removed reference implementation's per-worker RNG scope). No DB write from the
    # worker (ProcessPoolExecutor workers are compute-only, CLAUDE.md).
    rng = np.random.default_rng(seed=_derive_worker_rng_seed(symbol, config.bootstrap_seed))

    all_results: list[dict] = []
    pooled_rows: list[dict] = []
    regime_rows: list[dict] = []
    # Corpus-level BH-FDR accumulators (P2 fix).
    # pval_result_idxs are offsets into all_results (adjusted per TF call).
    pvals_flat: list[float] = []
    pval_result_idxs: list[int] = []
    total_skipped = 0
    error_msg = None
    # OTel-metric-worthy data, accumulated across every tf this worker computes --
    # emitted by main() only, never from inside this worker (see docstring above).
    cell_emissions: list[tuple[dict, int]] = []
    n_passing_wf_by_tf: dict[str, int] = {}
    skip_reasons_by_tf: dict[str, dict[str, int]] = {}

    try:
        for tf in tfs:
            try:
                tf_pooled, tf_regime, stats = _compute_symbol_tf(
                    dsn=dsn,
                    symbol=symbol,
                    tf=tf,
                    training_window_end=training_window_end,
                    config=config,
                    tracer=noop_tracer,
                    run_ts=run_ts,
                    rng=rng,
                    feature_status_map=feature_status_map,
                    mr_dict=mr_dict_by_tf.get(tf) if mr_dict_by_tf else None,
                    dual_write_symbol_hmm=dual_write_symbol_hmm,
                    cluster_regime_conditioned=cluster_regime_conditioned,
                )
                # Adjust pval_result_idxs to point into this worker's global all_results list.
                offset = len(all_results)
                for idx in stats.get("pval_result_idxs", []):
                    pval_result_idxs.append(offset + idx)
                pvals_flat.extend(stats.get("pvals_flat", []))
                pooled_rows.extend(tf_pooled)
                regime_rows.extend(tf_regime)
                total_skipped += stats.get("n_skipped", 0)
                all_results.extend(stats.get("all_results", []))
                cell_emissions.extend(stats.get("cell_emissions", []))
                n_passing_wf_by_tf[tf] = stats.get("n_passing_wf", 0)
                skip_reasons_by_tf[tf] = stats.get("skip_reasons", {})
            except CellTooLargeError:
                # Crash-loud (162-01 Task 3, todo 140): re-raise instead of the
                # generic swallow-and-continue-to-next-tf behavior below -- an
                # oversized cell must fail the whole job (nonzero exit code,
                # error recorded in the run summary), never route to an
                # alternate algorithm or be silently skipped.
                raise
            except Exception as error:
                worker_log.error(
                    "ic_engine.worker_cell_failed",
                    symbol=symbol,
                    tf=tf,
                    error=str(error),
                )
                # No shared connection to roll back -- _compute_symbol_tf opens and
                # closes its own short-lived connections per fetch phase, so a
                # failure inside it cannot leave a stale transaction on some
                # connection this loop still holds across TF iterations.
    except Exception as error:
        error_msg = str(error)
        worker_log.error("ic_engine.worker_failed", symbol=symbol, error=error_msg)

    return {
        "symbol": symbol,
        "pooled_rows": pooled_rows,
        "regime_rows": regime_rows,
        "all_results": all_results,
        "pvals_flat": pvals_flat,
        "pval_result_idxs": pval_result_idxs,
        "n_skipped": total_skipped,
        "error": error_msg,
        "cell_emissions": cell_emissions,
        "n_passing_wf_by_tf": n_passing_wf_by_tf,
        "skip_reasons_by_tf": skip_reasons_by_tf,
    }


# ---------------------------------------------------------------------------
# Post-run lifecycle hook (Phase 143 Plan 03: LIFECYCLE-03/04/05)
#
# Closes the loop opened by the feature governance registry's status column:
# features that lose IC demote to shadow_only, recovered ones promote back
# through the same evidence bar, and a regime dislocation is never misread as
# mass decay. Writes one gate-evaluation fact to integrity_monitor per run
# (observability only -- feature_transition_log / concept_transition_log stay
# the authoritative transition record) and the IC staleness gauge.
#
# Phase 170 Plan 08 (todo 118 scope item 4): concept_registry domain='feature'
# (via concept_svc) is the sole feature-lifecycle writer. feature_registry and
# its shadow-mode dual write (Plan 06) were retired by migration 311 after the
# dual-write shadow period's evidence -- see docs/research/concept-unified-registry.md's
# revision history for the retirement record.
#
# Sync psycopg throughout -- ic_engine.py is a plain argparse script (no class, no
# BaseBatch, no async/await anywhere). Guarded so a hook failure logs loudly but never
# corrupts the already-committed IC results (the hook runs after the primary write is
# durable).
# ---------------------------------------------------------------------------


def _get_prior_ic_engine_completion(
    write_conn: Any,
    manifest: CorpusManifest,
    training_window_end: Any,
) -> datetime | None:
    """Prior successful ic_engine run's completion timestamp, for LIFECYCLE-05 staleness.

    Tries the on-disk CorpusManifest history first -- the manifest FILE for step_name
    "ic_engine" still holds the PRIOR run's data at this point, because this run's own
    manifest.write() call happens later in main(), after the lifecycle hook returns.
    Falls back to MAX(training_window_end) in feature_ic_scores strictly BEFORE this
    run's training_window_end (a plain MAX would just return this run's own
    already-committed training_window_end) when no prior manifest exists. Returns None
    if neither source yields a timestamp -- the documented first-run fallback.
    """
    try:
        prior = CorpusManifest.read(manifest.manifest_dir, manifest.step_name)
        ts_str = prior.get("timestamp")
        if ts_str:
            ts = datetime.fromisoformat(ts_str)
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=UTC)
            return ts
    except FileNotFoundError:
        pass
    except Exception as error:
        _logger.warning("ic_engine.lifecycle_hook_manifest_read_failed", error=str(error))

    with write_conn.cursor() as cur:
        cur.execute(
            "SELECT max(training_window_end) FROM feature_ic_scores WHERE training_window_end < %s",
            (training_window_end,),
        )
        row = cur.fetchone()
        if row and row[0] is not None:
            return row[0]
    return None


def _apply_feature_transitions(
    write_conn: Any,
    concept_svc: ConceptRegistryService,
    config: ICEngineConfig,
    cell_rows: list[dict],
    material_fail_count: int,
    training_window_end: Any,
) -> None:
    """Step 4/5 of the lifecycle hook: per-feature demotion/promotion, then one
    integrity_monitor gate-evaluation fact. Extracted so the calling function's
    `if not any_hold:` guard wraps a single call instead of re-indenting this
    whole block (todo 144 /simplify pass) -- logic is unchanged from before that
    extraction.

    Phase 170 Plan 08 (todo 118 scope item 4): concept_svc (concept_registry
    domain='feature') is the sole feature-lifecycle writer. Plan 06's shadow-mode
    dual write against feature_registry (and the parity-precondition/divergence
    machinery it required) was removed once the shadow period's evidence
    authorised feature_registry's retirement -- see migration 311.
    """
    # Step 4: per-feature aggregation (GROUP BY feature_name) -- demotion/promotion.
    cells_by_feature: dict[str, list[dict]] = defaultdict(list)
    for cell in cell_rows:
        cells_by_feature[cell["feature_name"]].append(cell)

    demotion_fraction_floor = 1.0 - config.meta_fdr_min_fraction

    # concept_svc is the sole feature-lifecycle status source (Phase 170 Plan 08 --
    # the parity precondition against feature_registry that used to live here was
    # removed along with the registry itself; there is only one registry now). Full
    # concept dict, not just status (todo 323) -- min_demotion_consecutive's per-concept
    # override lives on this same row.
    concepts_by_feature = {c["name"]: c for c in concept_svc.get_all_concepts()}

    for feature_name, cells in cells_by_feature.items():
        concept = concepts_by_feature.get(feature_name)
        status = concept["status"] if concept else None

        if status == "active":
            active_feature_cells = [c for c in cells if c["feature_status_at_eval"] == "active"]
            if not active_feature_cells:
                continue
            material_fail_cells = [c for c in active_feature_cells if c["_material_fail"]]
            demote_fraction = len(material_fail_cells) / len(active_feature_cells)
            run_passed = demote_fraction < demotion_fraction_floor

            # Todo 323: advance the fail-streak for EVERY active concept evaluated this
            # run, not just ones about to be demoted -- a concept recovering from a
            # prior bad run must have its streak actually reset to 0, or hysteresis
            # never lets go once a concept gets close to the floor.
            concept_svc.advance_active_counters_sync(
                write_conn,
                domain="feature",
                name=feature_name,
                passed=run_passed,
                expected_status=status,
            )

            if not run_passed:
                # Non-NULL concept_gate.min_demotion_consecutive overrides the APR
                # default -- same convention record_comparison_outcome's
                # default_min_promotion_consecutive parameter already uses.
                min_demotion_consecutive = (
                    concept.get("min_demotion_consecutive")
                    if concept.get("min_demotion_consecutive") is not None
                    else config.demotion_min_consecutive
                )
                if not concept_svc.is_demotion_eligible(feature_name, min_demotion_consecutive):
                    # Fails again, but hasn't repeated enough times yet -- not demoted
                    # this run (todo 323's whole point: one bad run is not proof).
                    continue
                # Representative aggregates for the ic_* audit fields (worst cell by
                # ic_ci_lower, its own ic_sharpe_hac, summed n_independent).
                #
                # Sign-aware under the flag: `_signed_margin` (set in Step 2) is
                # ic_ci_lower for ic_sign=1 and -ic_ci_upper for ic_sign=-1 -- the
                # smallest value is always the worst cell on ITS OWN side, so one min()
                # correctly ranks a feature's mixed-sign cells (e.g. contrarian in one
                # regime, positive in another) without picking a positive feature's
                # cell using a contrarian's raw ic_ci_lower (which is meaningless for
                # a negative-full-sample-sign estimate). Flag OFF: `_signed_margin` ==
                # `ic_ci_lower` unconditionally (equivalence property, tested).
                worst_cell = min(
                    active_feature_cells,
                    key=lambda c: (c["_signed_margin"] if c["_signed_margin"] is not None else 0.0),
                )
                ic_n = sum(c["n_independent"] for c in active_feature_cells)
                # Sign-aware audit value: report ic_ci_upper (not ic_ci_lower) for a
                # contrarian worst_cell under the flag -- ic_ci_lower on a persistently
                # negative estimate is not the bound that determined "worst" here.
                worst_cell_ic_value = (
                    worst_cell["ic_ci_upper"]
                    if config.sign_symmetric and worst_cell["ic_sign"] == -1
                    else worst_cell["ic_ci_lower"]
                )
                concept_svc.record_transition_sync(
                    write_conn,
                    domain="feature",
                    name=feature_name,
                    from_status="active",
                    to_status="shadow_only",
                    reason="demotion_performance",
                    gate_metric=worst_cell["ic_sharpe_hac"],
                    gate_n=ic_n,
                    ci_lower=worst_cell_ic_value,
                )
                ALPHA_DECAY_ENSEMBLE_REBUILD_TOTAL.add(1, {"feature_name": feature_name})

        elif status == "shadow_only":
            passes_fdr_count = sum(1 for c in cells if c["passes_fdr"])
            pass_fraction = passes_fdr_count / len(cells)
            passed = pass_fraction >= config.meta_fdr_min_fraction
            new_observations = sum(c["n_independent"] for c in cells)
            concept_svc.advance_shadow_counters_sync(
                write_conn,
                domain="feature",
                name=feature_name,
                passed=passed,
                new_observations=new_observations,
                expected_status=status,
            )
            if concept_svc.is_promotion_eligible(
                feature_name,
                config.decay_recovery_min_observations,
                config.decay_recovery_min_passes,
            ):
                # Promotion is the status flip alone -- ic_engine NEVER writes
                # ensemble_weights (sole-writer invariant, T-143-12); the next ic_engine
                # run stamps feature_status_at_eval='active' and the next
                # ensemble_trainer run naturally recomputes the weight from current IC.
                # fdr_passed=True is EARNED here, not asserted for convenience --
                # promotion is already gated upstream by config.meta_fdr_min_fraction
                # over passes_fdr cells (the `passed` bool computed above from this
                # run's passes_fdr fraction, and is_promotion_eligible's multi-run
                # consecutive-pass/observation floors), which IS the executed
                # multiplicity correction Plan 02's fail-closed guard asks the caller
                # to attest to. Never pass fdr_passed=True anywhere that fraction
                # wasn't actually computed.
                concept_svc.record_transition_sync(
                    write_conn,
                    domain="feature",
                    name=feature_name,
                    from_status="shadow_only",
                    to_status="active",
                    reason="promotion",
                    fdr_passed=True,
                )
                ALPHA_DECAY_ENSEMBLE_REBUILD_TOTAL.add(1, {"feature_name": feature_name})

    # Step 5: one integrity_monitor gate-evaluation fact per (non-hold) run. Uses the
    # shared emit_integrity_fact_sync helper (todo 150) with commit=False and
    # idempotency_check=False -- both intentional here: commit is deferred to the
    # single commit point at the end of _run_lifecycle_hook (this fact must land in
    # the same transaction as Step 3's guard facts below, not commit on its own),
    # and Step 0 at the top of _run_lifecycle_hook already pre-checks this exact
    # (monitor_type, training_window_end) pair before either of this hook's two
    # integrity_monitor call sites can be reached -- a second pre-check here would
    # be redundant, not wrong.
    emit_integrity_fact_sync(
        write_conn,
        "ic_lifecycle",
        None,
        "decay_cells_flagged",
        float(material_fail_count),
        config.decay_materiality_threshold,
        True,
        training_window_end,
    )


def _run_lifecycle_hook(
    write_conn: Any,
    concept_svc: ConceptRegistryService,
    config: ICEngineConfig,
    training_window_end: Any,
    manifest: CorpusManifest,
) -> None:
    """Post-run lifecycle hook: aggregates this run's per-cell IC to a deterministic
    feature-level demote/promote decision, holds all weights on regime shift, and
    emits the IC staleness gauge. Idempotent on training_window_end.

    See ic_engine's module docstring reference and 143-03-PLAN.md for the full
    demotion/promotion/hold specification (Fable N3/N4/N5 fixes included below).

    Phase 170 Plan 08: concept_svc is the SAME ConceptRegistryService instance
    main() already constructed and load_sync'd for the alignment gate -- never
    construct a second one here.
    """
    log = _logger

    # Step 0: idempotency short-circuit -- a rerun for a training_window_end that
    # already has a gate-evaluation fact is a no-op (Plan 02's optimistic from_status
    # lock additionally makes individual transitions rerun-safe).
    with write_conn.cursor() as cur:
        cur.execute(
            """
            SELECT 1 FROM integrity_monitor
            WHERE monitor_type = 'ic_lifecycle'
              AND training_window_end = %s
              AND metric_name IN ('decay_cells_flagged', 'guard_fail_fraction')
            LIMIT 1
            """,
            (training_window_end,),
        )
        already_ran = cur.fetchone() is not None
    if already_ran:
        log.info(
            "ic_engine.lifecycle_hook_already_ran",
            training_window_end=str(training_window_end),
        )
        return

    # Step 1: load this run's per-cell IC facts, pinned to ONE lookahead (Fable N3) so
    # each (feature_name, tf, regime) triple yields exactly one row -- never 4 -- and
    # standing weight is read at the APR champion weight_version (Fable N4), never the
    # most-recent-by-computed_at row (which could silently be a challenger epoch).
    # Todo 146: lookahead_mid is now tf-specific (5m=6, 15m=2, 1h=2, 1d=2) -- "the mid
    # scale" is no longer one bar count across all 4 timeframes. Pin per-tf in Python
    # after the fetch (matching every other lookahead consumer in this file --
    # _compute_one_regime_cell/_compute_symbol_tf/_compute_one_cross_sectional_cell all
    # resolve config.lookaheads_for(tf) in Python, never by embedding tf->bars into SQL)
    # rather than building a dynamic per-tf OR-chain here: row volume for one training
    # window (features x regimes x 4 tfs x 4 scales) is trivial, so there's no
    # performance reason to push this filter into the query.
    with write_conn.cursor() as cur:
        cur.execute(
            """
            SELECT fis.feature_name, fis.tf, fis.regime, fis.ic_ci_lower, fis.ic_ci_upper,
                   fis.ic_sign, fis.passes_fdr,
                   fis.reliable, fis.n_independent, fis.feature_status_at_eval,
                   fis.ic_sharpe_hac, fis.lookahead_bars, COALESCE(ew.weight, 0.0) AS standing_weight
            FROM feature_ic_scores fis
            LEFT JOIN ensemble_weights ew
                   ON ew.symbol = 'UNIVERSE'
                  AND ew.tf = fis.tf
                  AND ew.regime = fis.regime
                  AND ew.feature_name = fis.feature_name
                  AND ew.weight_version = %s
            WHERE fis.symbol = 'POOLED'
              AND fis.is_pooled = true
              AND fis.regime != '_pooled'
              AND fis.training_window_end = %s
            """,
            (config.ensemble_weight_version, training_window_end),
        )
        cols = [d[0] for d in cur.description]
        all_rows = [dict(zip(cols, row, strict=True)) for row in cur.fetchall()]
        cell_rows = [r for r in all_rows if r["lookahead_bars"] == config.lookahead_mid[r["tf"]]]

    # Fable N5: zero-cell guard. A per-symbol-only run or a run with the equity model
    # disabled yields zero POOLED cells for this training_window_end -- every fraction
    # below would be a division by zero. Log and return WITHOUT writing an
    # integrity_monitor fact: a fact here would incorrectly mark this training_window_end
    # as "already evaluated" for a later run against the same window that DOES have cells.
    if not cell_rows:
        log.info(
            "ic_engine.lifecycle_hook_no_cells",
            training_window_end=str(training_window_end),
        )
        return

    # Step 2: per-cell material-fail flag.
    #
    # Sign-aware (Component E, todo 094 -- BLOCKER 1, closes the third sign-asymmetric
    # gate): under config.sign_symmetric, a cell only "fails" if its CI on its OWN side
    # includes zero, or it fails FDR. The old unconditional `ic_ci_lower <= 0` predicate
    # is sign-asymmetric -- it is unconditionally true for every contrarian (ic_sign=-1),
    # since a systematically negative point estimate's CI lower bound always sits below
    # zero, silently re-demoting every contrarian one lifecycle cycle after Component E's
    # eligibility/weighting fix lands them in the ensemble. Flag OFF reproduces today's
    # exact predicate (equivalence property, tested).
    material_fail_count = 0
    for cell in cell_rows:
        ic_ci_lower = cell["ic_ci_lower"]
        ic_ci_upper = cell["ic_ci_upper"]
        ic_sign = cell["ic_sign"]
        if config.sign_symmetric:
            failed = (
                (ic_sign == 1 and ic_ci_lower is not None and ic_ci_lower <= 0)
                or (ic_sign == -1 and ic_ci_upper is not None and ic_ci_upper >= 0)
                or (not cell["passes_fdr"])
            )
            nearest_bound = ic_ci_lower if ic_sign == 1 else ic_ci_upper
            # Signed margin from zero on the cell's OWN side: ic_sign * nearest_bound.
            # For ic_sign=1 this is ic_ci_lower unchanged; for ic_sign=-1 it flips
            # ic_ci_upper (always <= 0 for a real contrarian estimate) to a positive
            # "how far below zero" measure -- the smallest value is always the worst
            # cell on its own side, letting one min() rank mixed-sign cells for the
            # same feature consistently (used by the worst_cell audit pick below).
            signed_margin = (ic_sign * nearest_bound) if nearest_bound is not None else None
        else:
            failed = (ic_ci_lower is not None and ic_ci_lower <= 0) or (not cell["passes_fdr"])
            nearest_bound = ic_ci_lower
            signed_margin = ic_ci_lower
        material = failed and (
            cell["standing_weight"] * abs(nearest_bound or 0.0) > config.decay_materiality_threshold
        )
        cell["_failed"] = failed
        cell["_material_fail"] = material
        cell["_signed_margin"] = signed_margin
        if material:
            material_fail_count += 1
            ALPHA_DECAY_CELLS_FLAGGED.add(
                1,
                {
                    "feature_name": cell["feature_name"],
                    "tf": cell["tf"],
                    "regime": cell["regime"],
                },
            )

    # Step 3: REGIME-SHIFT GUARD (todo 144) -- stratified per (tf, regime_group),
    # self-calibrating, two-sided. Evaluated over cells with
    # feature_status_at_eval='active' only. A stratum's fraction is compared
    # against seeded rails (empirically grounded, migration 237) that narrow
    # toward a robust empirical band once enough history exists for that stratum.
    # hold_high in ANY hold-authoritative stratum holds ALL transitions for this
    # training_window_end (conservative: one dislocated market/horizon is enough
    # reason to distrust the whole run's lifecycle decisions). alert_low never
    # holds -- promotion is already multi-run-gated by recovery_min_observations/
    # recovery_min_passes, so a single anomalously-high pass rate cannot itself
    # flip a feature's status.
    active_cells = [c for c in cell_rows if c["feature_status_at_eval"] == "active"]
    any_hold = False
    # Accumulated here, flushed as one executemany AFTER Step 4/5 (or the hold
    # skip) below -- see the deferred-flush note preceding the single commit.
    pending_guard_facts: list[tuple] = []
    if active_cells:
        with write_conn.cursor() as cur:
            cur.execute("SELECT DISTINCT regime_group, regime_label FROM market_regimes")
            regime_label_to_group = {row[1]: row[0] for row in cur.fetchall()}

        strata: dict[tuple[str, str], list[dict]] = defaultdict(list)
        unmapped_count = 0
        for cell in active_cells:
            group = regime_label_to_group.get(cell["regime"], "_unmapped")
            if group == "_unmapped":
                unmapped_count += 1
            strata[(cell["tf"], group)].append(cell)

        # Unconditional signal, independent of whether the "_unmapped" stratum's
        # own fraction ever trips the guard: a regime label with no match in
        # market_regimes is a data-contract violation between feature_ic_scores
        # and market_regimes (a stale/renamed label), not routine input -- it
        # should surface immediately, not ride along silently inside a guard
        # verdict that may never fire.
        if unmapped_count:
            log.warning(
                "ic_engine.regime_label_unmapped",
                n_cells=unmapped_count,
                training_window_end=str(training_window_end),
            )

        for (tf, group), stratum_cells in strata.items():
            subject = f"tf={tf}|group={group}"
            fail_fraction = sum(1 for c in stratum_cells if c["_failed"]) / len(stratum_cells)

            with write_conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT metric_value FROM integrity_monitor
                    WHERE monitor_type = 'ic_lifecycle'
                      AND metric_name = 'guard_fail_fraction'
                      AND subject = %s
                    ORDER BY evaluated_at DESC
                    LIMIT %s
                    """,
                    (subject, config.guard_history_window),
                )
                history = [row[0] for row in cur.fetchall()]

            verdict: GuardVerdict = evaluate_guard_fraction(
                fail_fraction,
                len(stratum_cells),
                history,
                min_cells=config.guard_min_cells,
                min_history=config.guard_min_history,
                band_z=config.guard_band_z,
                rail_lo=config.guard_fail_rate_min,
                rail_hi=config.guard_fail_rate_max,
            )

            # Always record a fact -- this is what builds calibration history.
            # threshold_value records whichever bound is nearer the current
            # fraction (the one a small drift would next violate); passed is
            # false for both guard tails, true for "ok" and "insufficient_cells"
            # (the latter made no claim to violate -- its rail-derived bounds are
            # informational only, never evaluated against this stratum).
            #
            # Deferred, not executed here: concept_svc.record_transition_sync /
            # advance_shadow_counters_sync (called from Step 4 below) each wrap
            # their own SQL in conn.transaction() on this SAME write_conn, which
            # commits (or rolls back, on an optimistic-lock no-op) immediately on exit.
            # Executing this INSERT eagerly here would let the first Step 4
            # registry call silently commit/rollback it before the intended
            # single commit point. Instead we only accumulate the row now and
            # flush every stratum's fact together in one executemany right
            # before that single commit -- see the note there.
            nearer_bound = (
                verdict.band_hi
                if abs(fail_fraction - verdict.band_hi) <= abs(fail_fraction - verdict.band_lo)
                else verdict.band_lo
            )
            passed = verdict.status not in ("hold_high", "alert_low")
            # Full 7-field shape matching INTEGRITY_MONITOR_INSERT_SQL's placeholder
            # order (todo 150) -- not routed through emit_integrity_fact_sync itself
            # (that helper is single-row and would commit/guard each stratum
            # independently, defeating the one-executemany-then-one-commit design
            # this whole block exists for), but reuses the SAME shared SQL constant
            # so the ON CONFLICT clause is defined in exactly one place either way.
            pending_guard_facts.append(
                (
                    "ic_lifecycle",
                    subject,
                    "guard_fail_fraction",
                    fail_fraction,
                    nearer_bound,
                    passed,
                    training_window_end,
                )
            )

            if verdict.status in ("hold_high", "alert_low"):
                event = (
                    "ic_engine.regime_shift_hold"
                    if verdict.status == "hold_high"
                    else "ic_engine.guard_suspicious_pass_rate"
                )
                log.warning(
                    event,
                    tf=tf,
                    regime_group=group,
                    fraction=fail_fraction,
                    band_lo=verdict.band_lo,
                    band_hi=verdict.band_hi,
                    band_source=verdict.band_source,
                    n_history=verdict.n_history,
                    training_window_end=str(training_window_end),
                )
                if verdict.status == "hold_high":
                    any_hold = True

    if not any_hold:
        # Step 4/5: per-feature demotion/promotion, then the decay_cells_flagged
        # fact -- extracted to _apply_feature_transitions (todo 144 /simplify
        # pass) so this guard wraps one call instead of ~100 re-indented lines.
        # _apply_feature_transitions may raise -- the caller in main() wraps
        # _run_lifecycle_hook in a guarded try/except, so this never corrupts
        # the already-committed IC results, only aborts the lifecycle hook for
        # this run.
        _apply_feature_transitions(
            write_conn,
            concept_svc,
            config,
            cell_rows,
            material_fail_count,
            training_window_end,
        )

    # Flush Step 3's accumulated per-stratum guard facts now -- unconditionally,
    # on both the hold and non-hold paths, and strictly after Step 4/5 have
    # either run or been skipped by a hold. This is what keeps the facts out of
    # concept_svc's conn.transaction() commit/rollback windows above.
    if pending_guard_facts:
        with write_conn.cursor() as cur:
            # Reuses the same INTEGRITY_MONITOR_INSERT_SQL constant emit_integrity_fact_sync
            # uses (todo 150) -- deliberately NOT emit_integrity_fact_sync itself, since
            # this is an N-row executemany flushed together at one deferred commit
            # point (see the comment above), not N independent guarded single-row
            # emits. Letting a failure here raise (rather than being swallowed
            # per-row) is correct: it must abort this whole deferred transaction,
            # exactly as it would have before this extraction.
            cur.executemany(INTEGRITY_MONITOR_INSERT_SQL, pending_guard_facts)

    # Single commit point for the whole hook: the deferred guard facts above +
    # either Step 4/5's writes (non-hold) or nothing further (hold) all land
    # together here. Step 4's individual registry transitions still self-commit
    # one at a time via ConceptRegistryService's own conn.transaction() pattern
    # (a pre-existing constraint of that shared Ring-1 service, not something
    # this fix needs to solve) -- but each
    # transition is individually rerun-safe via its own optimistic
    # `WHERE status = %s` lock (from_status), so a crash mid-Step-4 leaves no
    # integrity_monitor fact at all (nothing flushed yet) and the whole window
    # is safely retriable from scratch on the next run.
    write_conn.commit()

    # Step 6: IC staleness gauge (LIFECYCLE-05). Runs exactly once, regardless of
    # hold -- todo 144 fix: previously skipped entirely on hold (via early return),
    # which was incidental, not intended -- the gauge is diagnostic-only and
    # unrelated to whether lifecycle transitions ran this cycle.
    prior_completion = _get_prior_ic_engine_completion(write_conn, manifest, training_window_end)
    age_days, alert = _evaluate_staleness(
        prior_completion, datetime.now(UTC), config.ic_staleness_alert_days
    )
    IC_ENGINE_LAST_RUN_AGE_DAYS.set(age_days)
    if alert:
        log.warning(
            "ic_engine.stale",
            age_days=age_days,
            threshold=config.ic_staleness_alert_days,
        )


def _evaluate_staleness(
    prior_completion: datetime | None,
    now: datetime,
    staleness_alert_days: int,
) -> tuple[int, bool]:
    """Pure staleness decision (LIFECYCLE-05): (age_days, alert_should_fire).

    age_days = 0 and alert=False when prior_completion is None (first run / missing
    manifest -- the documented fallback, never an alert). Otherwise age_days is the
    integer day difference and alert fires when age_days exceeds staleness_alert_days.

    ALERT-ONLY CONTRACT (162-04 Task 2, pinned intent): this function's return value
    is consumed ONLY to set a diagnostic gauge (IC_ENGINE_LAST_RUN_AGE_DAYS) and log a
    warning at its call site below -- it NEVER triggers an auto-recompute. A
    fingerprint-valid cell (162-03's ic_cell_fingerprints gate) is never auto-stale on
    wall-clock grounds alone; data-driven refresh of a cell only ever happens via an
    explicit `--training-window-end` bump (a new cell key) or `--refresh` (an explicit
    operator override). Do not wire this alert into any recompute-triggering code path.
    """
    if prior_completion is None:
        return 0, False
    if prior_completion.tzinfo is None:
        prior_completion = prior_completion.replace(tzinfo=UTC)
    age_days = (now - prior_completion).days
    return age_days, age_days > staleness_alert_days


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
        choices=_DEFAULT_TFS,
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
        required=True,
        help="REQUIRED. Explicit training window end (ISO 8601, timezone-aware/UTC) -- "
        "the OOS holdout clamp (LEAST(MAX(bar_ts), alpha.validation.oos_start)). "
        "No default: a bare MAX(bar_ts) fallback would silently consume the OOS "
        "holdout window (Phase 141.1 CR-01). See docs/plans/OOS-EVAL-PROTOCOL.md.",
    )
    parser.add_argument(
        "--cross-sectional-only",
        action="store_true",
        default=False,
        help="Skip per-symbol pass and run only the cross-sectional (POOLED) IC pass. "
        "Requires at least one enabled group in alpha.regime.groups. Use when "
        "per-symbol rows already exist.",
    )
    parser.add_argument(
        "--refresh",
        action="store_true",
        default=False,
        help="Force full recompute, bypassing the whole-cell fingerprint check "
        "entirely (162-03). Every candidate cell is treated as invalid regardless "
        "of ic_cell_fingerprints content. Combine with --symbols/--tf to scope.",
    )
    parser.add_argument(
        "--dry-run-validity",
        action="store_true",
        default=False,
        help="Compute the fingerprint skip/compute partition and log/print the "
        "counts, then exit before any fetch, compute, or write (162-03).",
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

    # Initialize corpus manifest
    manifest_dir = CorpusManifest.DEFAULT_MANIFEST_DIR
    manifest = CorpusManifest("ic_engine", manifest_dir)

    try:
        with _observed_span("ic_engine.run", tracer):
            # ----------------------------------------------------------
            # Bind all APR parameters once at startup (compile-time binding).
            # ICEngineConfig is frozen for the entire run -- no mid-run drift.
            # ----------------------------------------------------------
            _cfg_svc = _load_config_service(conn)
            config = ICEngineConfig.from_apr(_cfg_svc)

            # Cap this (main) process's own BLAS thread pool -- covers the
            # cross-sectional pass's ThreadPoolExecutor bootstrap below, which runs
            # in-process and shares this process's OpenBLAS state. Per-symbol
            # ProcessPoolExecutor workers are capped separately via initializer=
            # at their own pool construction (todo 216).
            limit_blas_threads(config.blas_threads_per_worker)

            # ----------------------------------------------------------
            # Phase 144 Plan 05: regime_group routing. equity_model_enabled is
            # retired as a standalone APR kill-switch (alpha.regime.equity_model_enabled)
            # in favor of bool(enabled_groups) -- a project-wide grep confirmed
            # ic_engine.py is the sole runtime consumer of the old flag (see
            # 144-05-SUMMARY.md for the grep evidence). The local variable name
            # is kept for minimal diff against the rest of this function; its
            # SOURCE now derives entirely from alpha.regime.groups.
            # ----------------------------------------------------------
            from services.cross_sectional_regime_model import _parse_group_configs

            group_configs: list[dict] = _parse_group_configs(config.regime_groups_json)
            enabled_groups = [g for g in group_configs if g.get("enabled", True)]
            equity_model_enabled: bool = bool(enabled_groups)
            _logger.info(
                "ic_engine.groups_loaded",
                n_groups=len(enabled_groups),
                group_names=[g["name"] for g in enabled_groups],
            )

            with conn.cursor() as cur:
                cur.execute("SELECT symbol, array_agg(tag) FROM instrument_tags GROUP BY symbol")
                tags_by_symbol: dict[str, set[str]] = {
                    row[0]: set(row[1]) for row in cur.fetchall()
                }
            symbol_regime_class: dict[str, str] = _build_symbol_regime_class(
                tags_by_symbol, enabled_groups
            )
            group_by_name: dict[str, dict] = {g["name"]: g for g in enabled_groups}
            unrouted_symbols = sorted(set(tags_by_symbol) - set(symbol_regime_class))
            _logger.info(
                "ic_engine.routing_built",
                n_symbols=len(symbol_regime_class),
                by_group={
                    g: sum(1 for v in symbol_regime_class.values() if v == g)
                    for g in {v for v in symbol_regime_class.values()}
                },
            )
            if unrouted_symbols:
                _logger.warning(
                    "ic_engine.unrouted_symbols",
                    n_unrouted=len(unrouted_symbols),
                    symbols=unrouted_symbols,
                    note="excluded from regime-stratified IC this run (no matching "
                    "enabled regime_group); pooled IC pass still covers them",
                )

            # ----------------------------------------------------------
            # Startup crash-loud gates (market_regimes gate included when enabled)
            # ----------------------------------------------------------
            _assert_prerequisites(
                conn,
                tfs=args.tf,
                equity_model_enabled=equity_model_enabled,
                group_configs=enabled_groups,
            )

            # ----------------------------------------------------------
            # Feature registry alignment gate (Phase 170 Plan 08: concept_registry
            # domain='feature' is the sole feature-lifecycle registry; feature_registry
            # was retired by migration 311). Crash-loud: registry must match
            # FeatureVector dataclass fields exactly.
            # Use get_all_concepts() — NOT a status-filtered accessor — so the gate
            # passes even when features have been deprecated. The alignment gate
            # checks schema completeness, not lifecycle state.
            #
            # LOAD-BEARING for fingerprint safety (2026-07-29 code review, todo 198):
            # _fingerprint_computational_key excludes concept_registry.status_hash
            # from what invalidates a cell, on the grounds that status never changes
            # WHAT gets computed. That's only true of status; status_hash also moves
            # on registry MEMBERSHIP changes (a feature added/removed/renamed), which
            # DOES change computed output. Membership drift is safe to exclude only
            # because THIS gate forces registry membership to equal FeatureVector's
            # fields exactly -- so any real membership change requires editing
            # FeatureVector, a semantic AST change that moves code_content_key (which
            # IS in the computational key) via _normalized_source_for_hash. If this
            # gate is ever relaxed (e.g. registry-only computed features), that
            # coupling breaks silently and _fingerprint_computational_key must be
            # revisited to also track membership explicitly.
            # ----------------------------------------------------------
            concept_svc = ConceptRegistryService()
            concept_svc.load_sync(conn, domain="feature")
            # Single get_all_concepts() call, reused below -- avoids rebuilding the
            # same ~249-row list twice in a row (2026-08-04 simplify-pass finding).
            all_concepts = concept_svc.get_all_concepts()
            all_registry_names = {r["name"] for r in all_concepts}
            dataclass_names = {f.name for f in dataclasses.fields(FeatureVector)}
            if all_registry_names != dataclass_names:
                raise RuntimeError(
                    f"concept_registry(domain='feature') drift: "
                    f"{all_registry_names ^ dataclass_names}. "
                    "Run migration 284 (or its successor) to sync concept_registry "
                    "with FeatureVector."
                )
            # Build status map for workers: plain dict is picklable; ConceptRegistryService is not.
            feature_status_map: dict[str, str] = {
                r["name"]: (r["status"] or "unknown") for r in all_concepts
            }

            # ----------------------------------------------------------
            # Run constants (locked at start)
            # ----------------------------------------------------------
            run_ts = datetime.now(UTC)

            training_window_end = parse_training_window_end(args.training_window_end)
            _logger.info("ic_engine.training_window_end_explicit", value=str(training_window_end))

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

            # Record inputs to manifest
            manifest.set_inputs(
                training_window_end=str(training_window_end),
                tfs=tfs,
                symbols=symbols,
                cross_sectional_only=args.cross_sectional_only,
            )

            # ----------------------------------------------------------
            # Whole-cell fingerprint gate (162-03 Task 3, todo 134): loads persisted
            # fingerprints for this training_window_end and binds the two run-
            # constant fingerprint components. Per-symbol and per-cross-sectional-
            # cell validity partitions are computed below, BEFORE worker_args is
            # built -- this is what makes SC-1's "fetch+compute skipped, not just
            # the insert" true: a fully-valid symbol/cell is never dispatched.
            # --refresh bypasses the check entirely (every candidate is invalid).
            # ----------------------------------------------------------
            content_key = _checkpoint_content_key()
            apr_snapshot_key = _compute_apr_snapshot_key(config)
            # Run-invariant + narrower-than-per-cell watermark components, computed
            # once and reused across every cell's _compute_upstream_watermark call
            # below (162 simplify-pass -- previously each was recomputed on every
            # single per-cell call; see _compute_upstream_watermark's docstring).
            concept_registry_watermark = _watermark_concept_registry(conn)
            fr_fv_cache: dict[tuple[str | None, str], dict[str, Any]] = {}
            mr_tags_cache: dict[tuple[str | None, str], dict[str, Any]] = {}
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT symbol, tf, pass_type, code_content_key, apr_snapshot_key,
                           upstream_watermark
                    FROM ic_cell_fingerprints
                    WHERE training_window_end = %s
                    """,
                    (training_window_end,),
                )
                stored_fingerprints: dict[tuple[str, str, str], dict[str, Any]] = {
                    (r[0], r[1], r[2]): {
                        "code_content_key": r[3],
                        "apr_snapshot_key": r[4],
                        "upstream_watermark": r[5],
                    }
                    for r in cur.fetchall()
                }
            _logger.info("ic_engine.stored_fingerprints_loaded", count=len(stored_fingerprints))

            # APR already bound in config above; derive n_workers from config or CLI override.
            n_workers = args.workers if args.workers is not None else config.n_workers
            if args.workers is not None and args.workers != config.n_workers:
                # 2026-07-12: a silent --workers 4 override against an APR default of 8
                # (and a plan-benchmarked 12) produced a ~40x runtime blowout that took
                # hours of profiling to attribute to worker count vs. algorithm cost.
                # Loud, not silent -- "silent wrong answers are worse than loud crashes"
                # applies to performance-invalidating config drift too, not just data bugs.
                _logger.warning(
                    "ic_engine.workers_override",
                    cli_workers=args.workers,
                    apr_workers=config.n_workers,
                    note="explicit --workers overrides infra.ic_engine.workers APR value",
                )

            # ----------------------------------------------------------
            # Load market_regimes {ts -> regime_label} per (regime_group, tf).
            # Pre-materialized here so workers receive a plain dict (picklable).
            # mr_dicts_by_group: {group_name -> {tf -> {ts -> label}}} -- each
            # worker receives only ITS symbol's own group's dict (see worker_args
            # below), never another group's labels.
            # ----------------------------------------------------------
            mr_dicts_by_group: dict[str, dict[str, dict]] = {}
            if equity_model_enabled:
                for group in enabled_groups:
                    group_name = group["name"]
                    mr_dicts_by_group[group_name] = {}
                    for tf in tfs:
                        with conn.cursor() as cur:
                            cur.execute(
                                "SELECT ts, regime_label FROM market_regimes "
                                "WHERE regime_group=%s AND tf=%s",
                                (group_name, tf),
                            )
                            mr_dicts_by_group[group_name][tf] = {r[0]: r[1] for r in cur.fetchall()}
                        _logger.info(
                            "ic_engine.mr_loaded",
                            regime_group=group_name,
                            tf=tf,
                            n_rows=len(mr_dicts_by_group[group_name][tf]),
                        )

            # ----------------------------------------------------------
            # Per-symbol whole-cell fingerprint pre-pass (162-03 Task 3): for every
            # candidate symbol, compute the current fingerprint for each expected
            # (tf, pass_type) cell (_symbol_expected_cells mirrors the exact
            # routing logic worker_args uses below) and compare against the stored
            # fingerprint. A symbol is dispatched iff ANY of its cells is invalid
            # or absent (SC-1); a fully-valid symbol is skipped BEFORE worker_args
            # is built -- fetch+compute never happens for it, not just the insert.
            # Only the cells actually found invalid are DELETEd (T-162-03-06: a
            # fingerprint-valid sibling within a dispatched symbol is NOT deleted --
            # its harmless recompute hits ON CONFLICT DO NOTHING).
            # ----------------------------------------------------------
            total_skipped = 0
            total_committed = 0
            per_symbol_results: list[tuple[str, list[dict]]] = []
            symbols_to_compute: list[str] = []
            invalid_cells_by_symbol: dict[str, list[tuple[str, str]]] = {}
            current_fp_cache: dict[str, dict[tuple[str, str], dict[str, Any]]] = {}
            # todo 198: a symbol with zero invalid cells but >=1 status_only_stale
            # cell (concept_registry.status_hash moved, nothing computational did)
            # skips the expensive compute but still needs feature_status_at_eval
            # refreshed on its already-written rows -- see the refresh block below.
            # symbols_status_only_stale is the skip-compute set (mutually exclusive
            # with symbols_to_compute, used to decide fingerprint re-upsert scope);
            # symbols_needing_status_refresh is the UPDATE scope and is a SUPERSET
            # of it -- a symbol dispatched for an unrelated invalid cell can ALSO
            # need a status refresh for a different, fingerprint-valid sibling cell
            # (2026-07-29 code review regression -- see _partition_symbol_cells'
            # docstring for why these must never be collapsed into one bucket).
            symbols_status_only_stale: list[str] = []
            symbols_needing_status_refresh: list[str] = []

            if not args.cross_sectional_only:
                for symbol in symbols:
                    expected_cells = _symbol_expected_cells(
                        symbol,
                        tfs,
                        symbol_regime_class,
                        group_by_name,
                        equity_model_enabled,
                        config.cluster_regime_conditioned,
                    )
                    cell_fps: dict[tuple[str, str], dict[str, Any]] = {}
                    cell_classifications: dict[tuple[str, str], _FingerprintClassification] = {}
                    for tf, pass_type in expected_cells:
                        current_fp = {
                            "code_content_key": content_key,
                            "apr_snapshot_key": apr_snapshot_key,
                            "upstream_watermark": _compute_upstream_watermark(
                                conn,
                                symbol,
                                tf,
                                concept_registry_watermark=concept_registry_watermark,
                                fr_fv_cache=fr_fv_cache,
                                mr_tags_cache=mr_tags_cache,
                            ),
                        }
                        cell_fps[(tf, pass_type)] = current_fp
                        stored = stored_fingerprints.get((symbol, tf, pass_type))
                        cell_classifications[(tf, pass_type)] = _classify_fingerprint(
                            stored, current_fp, force_refresh=args.refresh
                        )
                    current_fp_cache[symbol] = cell_fps
                    invalid_this_symbol, needs_status_refresh = _partition_symbol_cells(
                        cell_classifications
                    )
                    if needs_status_refresh:
                        symbols_needing_status_refresh.append(symbol)
                    if invalid_this_symbol:
                        symbols_to_compute.append(symbol)
                        invalid_cells_by_symbol[symbol] = invalid_this_symbol
                    elif needs_status_refresh:
                        symbols_status_only_stale.append(symbol)

            # ----------------------------------------------------------
            # Cross-sectional cell discovery + fingerprint pre-pass (only when
            # equity_model_enabled): discovers every (regime_group, tf, regime_label)
            # cell up front (same cs_regimes query the real pass uses below, run
            # ONCE here and reused -- not duplicated) and computes its validity, so
            # --dry-run-validity can report BOTH passes' partitions without ever
            # touching _compute_cross_sectional_tf.
            # ----------------------------------------------------------
            symbols_by_group: dict[str, list[str]] = {}
            for sym in symbols:
                g = symbol_regime_class.get(sym)
                if g is not None:
                    symbols_by_group.setdefault(g, []).append(sym)

            cs_cell_plan: list[dict[str, Any]] = []
            if equity_model_enabled:
                for group in enabled_groups:
                    group_name = group["name"]
                    group_symbols = symbols_by_group.get(group_name, [])
                    if not group_symbols:
                        _logger.info(
                            "ic_engine.cross_sectional_group_skipped",
                            regime_group=group_name,
                            reason="no peer symbols in this run's symbol set",
                        )
                        continue
                    with conn.cursor() as cur:
                        cur.execute(
                            "SELECT DISTINCT regime_label FROM market_regimes "
                            "WHERE regime_group=%s AND tf=%s ORDER BY regime_label",
                            (group_name, tfs[0]),
                        )
                        cs_regimes = [r[0] for r in cur.fetchall()]
                    for tf in tfs:
                        for regime_label in cs_regimes:
                            cs_symbol_key = f"{group_name}:{regime_label}"
                            current_fp = {
                                "code_content_key": content_key,
                                "apr_snapshot_key": apr_snapshot_key,
                                "upstream_watermark": _compute_upstream_watermark(
                                    conn,
                                    symbol=None,
                                    tf=tf,
                                    is_group_pooled=True,
                                    regime_group=group_name,
                                    symbol_list=group_symbols,
                                    concept_registry_watermark=concept_registry_watermark,
                                    fr_fv_cache=fr_fv_cache,
                                    mr_tags_cache=mr_tags_cache,
                                ),
                            }
                            stored = stored_fingerprints.get((cs_symbol_key, tf, "cross_sectional"))
                            # Same _classify_fingerprint call as the per-symbol loop above
                            # (todo 198) -- the two passes cannot diverge in what counts as
                            # valid/status_only_stale/invalid. "valid" here preserves its
                            # pre-existing meaning exactly (skip the expensive compute):
                            # status_only_stale cells skip compute too, same as fully-valid
                            # ones, and are additionally flagged for the cheap metadata-only
                            # refresh below.
                            classification = _classify_fingerprint(
                                stored, current_fp, force_refresh=args.refresh
                            )
                            cs_cell_plan.append(
                                {
                                    "group_name": group_name,
                                    "tf": tf,
                                    "regime_label": regime_label,
                                    "group_symbols": group_symbols,
                                    "cs_symbol_key": cs_symbol_key,
                                    "classification": classification,
                                    "current_fp": current_fp,
                                }
                            )

            # 1 (concept_registry, computed once above) + actual cache-miss round
            # trips -- reflects real DB round trips, not cells checked (162
            # simplify-pass; multiple cells share a cache key, so this is now
            # smaller than len(symbols)+len(cs_cell_plan)).
            n_watermark_queries = 1 + len(fr_fv_cache) + len(mr_tags_cache)
            _logger.info("ic_engine.fingerprint_watermark_queries", count=n_watermark_queries)
            n_cs_skip = sum(1 for c in cs_cell_plan if c["classification"] != "invalid")
            n_cs_status_only_stale = sum(
                1 for c in cs_cell_plan if c["classification"] == "status_only_stale"
            )
            _logger.info(
                "ic_engine.fingerprint_partition",
                n_symbols=len(symbols) if not args.cross_sectional_only else 0,
                n_symbols_skip=(
                    (len(symbols) - len(symbols_to_compute) - len(symbols_status_only_stale))
                    if not args.cross_sectional_only
                    else 0
                ),
                n_symbols_status_only_stale=(
                    len(symbols_status_only_stale) if not args.cross_sectional_only else 0
                ),
                n_symbols_compute=len(symbols_to_compute),
                n_cs_cells=len(cs_cell_plan),
                n_cs_skip=n_cs_skip - n_cs_status_only_stale,
                n_cs_status_only_stale=n_cs_status_only_stale,
                n_cs_compute=len(cs_cell_plan) - n_cs_skip,
            )

            if args.dry_run_validity:
                _logger.info("ic_engine.dry_run_validity_complete", exiting=True)
                conn.close()
                conn = None
                return

            # ARCHIVE-then-DELETE stale rows for every invalid per-symbol cell BEFORE dispatch
            # (T-162-03-02/03: DELETE-then-insert, scoped to the exact cell key -- never a bare
            # training_window_end filter; todo 252: archive first, in the same transaction, so
            # the prior measurement is preserved rather than silently lost the moment a code/APR
            # change invalidates it).
            if invalid_cells_by_symbol:
                with conn.cursor() as cur:
                    for symbol, cells in invalid_cells_by_symbol.items():
                        for tf, pass_type in cells:
                            params = {
                                "symbol": symbol,
                                "fp_symbol": symbol,
                                "tf": tf,
                                "pass_type": pass_type,
                                "training_window_end": training_window_end,
                            }
                            cur.execute(_ARCHIVE_BEFORE_DELETE_SQL, params)
                            cur.execute(_FINGERPRINT_INVALIDATE_DELETE_SQL, params)
                conn.commit()

            # todo 198: status-only-stale cells skip the expensive compute entirely,
            # but their feature_status_at_eval provenance still needs refreshing to
            # the current concept_registry snapshot. The UPDATE's scope is
            # symbols_needing_status_refresh (NOT symbols_status_only_stale) -- a
            # symbol dispatched for an unrelated invalid cell can still have a
            # different, fingerprint-valid sibling cell whose rows the dispatch's
            # ON CONFLICT DO NOTHING recompute cannot touch (see
            # _partition_symbol_cells' docstring); only symbols_status_only_stale
            # (the fully-skipped subset) additionally needs its fingerprint
            # re-upserted here, since a dispatched symbol's fingerprints are already
            # re-upserted fresh by the existing post-compute path below. Cross-
            # sectional POOLED rows all share symbol='POOLED' regardless of
            # regime_group/tf/regime (feature_ic_scores has no regime_group column),
            # and concept_registry.status_hash is one global value per run, so a
            # single refresh_symbols set -- real symbols plus 'POOLED' once if any
            # cross-sectional cell is status_only_stale -- covers every case in one
            # UPDATE via _FEATURE_STATUS_REFRESH_SQL's symbol = ANY(...).
            status_only_stale_cs_cells = [
                c for c in cs_cell_plan if c["classification"] == "status_only_stale"
            ]
            refresh_symbols = list(symbols_needing_status_refresh)
            if status_only_stale_cs_cells:
                refresh_symbols.append(_CROSS_SECTIONAL_SYMBOL)
            if refresh_symbols:
                # feature_ic_scores is a compressed hypertable -- this UPDATE can hit
                # already-compressed chunks from older training_window_end values, the
                # same forced-full-decompress-scan exposure every other writer against
                # this table was already fixed for (todo 307).
                with _write_session(conn, "feature_ic_scores"):
                    with conn.cursor() as cur:
                        cur.execute(
                            _FEATURE_STATUS_REFRESH_SQL,
                            {
                                "symbols": refresh_symbols,
                                "training_window_end": training_window_end,
                            },
                        )
                        n_status_rows_refreshed = cur.rowcount
                    fp_refresh_rows = [
                        _fp_row(symbol, tf, pass_type, training_window_end, fp)
                        for symbol in symbols_status_only_stale
                        for (tf, pass_type), fp in current_fp_cache[symbol].items()
                    ] + [
                        _fp_row(
                            cell["cs_symbol_key"],
                            cell["tf"],
                            "cross_sectional",
                            training_window_end,
                            cell["current_fp"],
                        )
                        for cell in status_only_stale_cs_cells
                    ]
                    with conn.cursor() as cur:
                        cur.executemany(_FINGERPRINT_UPSERT_SQL, fp_refresh_rows)
                    conn.commit()
                _logger.info(
                    "ic_engine.feature_status_refresh",
                    n_symbols_status_only_stale=len(symbols_status_only_stale),
                    n_symbols_needing_status_refresh=len(symbols_needing_status_refresh),
                    n_cs_status_only_stale=len(status_only_stale_cs_cells),
                    n_rows_refreshed=n_status_rows_refreshed,
                    n_fingerprints_reupserted=len(fp_refresh_rows),
                )

            # ----------------------------------------------------------
            # Build worker args -- workers open their own read connections.
            # Each symbol's rows are written to feature_ic_scores immediately
            # once its compute finishes (todo 130) -- see _write_symbol_results.
            # per_symbol_results retains the same row dicts purely so OTel health
            # gauges (which need final passes_fdr) can be emitted once, after the
            # corpus-wide FDR backfill below patches them in place.
            # ----------------------------------------------------------
            if args.cross_sectional_only:
                _logger.info("ic_engine.skipping_per_symbol_pass", reason="--cross-sectional-only")
                conn.close()
                conn = None
            else:
                worker_args = []
                for symbol in symbols_to_compute:
                    routed_group_name, dual_write_symbol_hmm = _resolve_symbol_routing(
                        symbol, symbol_regime_class, group_by_name, equity_model_enabled
                    )
                    worker_args.append(
                        (
                            symbol,
                            tfs,
                            settings.database_url,
                            training_window_end,
                            config,
                            run_ts,
                            feature_status_map,
                            mr_dicts_by_group.get(routed_group_name) if enabled_groups else None,
                            dual_write_symbol_hmm if enabled_groups else False,
                            # Global run-level switch (migration 286), NOT resolved via
                            # _resolve_symbol_routing -- unlike dual_write_symbol_hmm this
                            # is not a per-group field. The cross_sectional gate inside
                            # _compute_symbol_tf (mr_dict is not None) already excludes
                            # the enabled_groups=False case, so no extra guard is needed
                            # here.
                            config.cluster_regime_conditioned,
                        )
                    )

                IC_ENGINE_RUN_SYMBOLS_TOTAL.set(len(symbols))
                _logger.info(
                    "ic_engine.starting_parallel",
                    n_symbols=len(symbols),
                    n_to_compute=len(symbols_to_compute),
                    n_workers=n_workers,
                )
                conn.close()
                conn = None  # prevent double-close in finally

                # ----------------------------------------------------------
                # Main compute loop (ProcessPoolExecutor). as_completed (not
                # pool.map) so progress reflects real completion order, not
                # submission order -- pool.map buffers a fast worker's result
                # behind a slower earlier-submitted one, which on 2026-07-12
                # made 5 already-finished symbols invisible for ~2 hours behind
                # one slow one. Written to feature_ic_scores immediately (todo
                # 130) so a crash anywhere in the rest of the run keeps this
                # symbol's compute durable -- BH-FDR annotation is backfilled
                # separately, after the whole corpus (including the cross-
                # sectional pass below) is done, by _backfill_bh_fdr.
                # ----------------------------------------------------------
                n_done = 0
                if worker_args:
                    with make_worker_pool(n_workers, config.blas_threads_per_worker) as pool:
                        futures = {pool.submit(_run_ic_worker, wa): wa[0] for wa in worker_args}
                        for future in as_completed(futures):
                            result = future.result()
                            symbol = result["symbol"]
                            if result["error"]:
                                _logger.error(
                                    "ic_engine.symbol_failed",
                                    symbol=symbol,
                                    error=result["error"],
                                )
                                status = "failure"
                                exit_code = 1
                                # Error row in the run summary (162-01 Task 3): a
                                # CellTooLargeError re-raised from _run_ic_worker
                                # lands here same as any other symbol failure --
                                # record it in the manifest, not just the log, so
                                # the crash-loud ceiling produces a durable audit
                                # trail matching the outer-exception path below.
                                manifest.add_error(result["error"])
                                # No fingerprint UPSERT on error -- a retry
                                # recomputes this symbol from scratch (its
                                # fingerprint row, if any, is left as-is/stale,
                                # so the next run correctly re-invalidates it).
                                # A per-tf error still leaves any OTHER tf's
                                # already-computed rows in result["pooled_rows"]/
                                # ["regime_rows"] (each tf is caught
                                # independently inside the worker) -- those still
                                # get written below, never dropped (Renaissance:
                                # never discard data that could contain signal).
                            total_committed += _record_symbol_result(
                                settings, result, per_symbol_results
                            )
                            total_skipped += result["n_skipped"]
                            # Per-cell OTel metrics (todo 009/2026-07-31 fix): computed
                            # inside the worker (pure, no OTel calls -- it has no
                            # exporter initialized), emitted only here in the main
                            # process. Unconditional on result["error"] -- a per-tf
                            # failure still leaves any OTHER tf's data valid (see the
                            # comment above on pooled_rows/regime_rows never being
                            # dropped), so its metrics are real and should count too.
                            for cell_attrs, cell_count in result.get("cell_emissions", []):
                                IC_ENGINE_CELLS_COMPLETED_TOTAL.add(cell_count, cell_attrs)
                            for wf_tf, n_passing_wf in result.get("n_passing_wf_by_tf", {}).items():
                                FEATURE_IC_PASSING_WALKFORWARD_TOTAL.set(
                                    n_passing_wf, {"symbol": symbol, "tf": wf_tf}
                                )
                            for skip_tf, reasons in result.get("skip_reasons_by_tf", {}).items():
                                for skip_reason, skip_count in reasons.items():
                                    if skip_count:
                                        IC_ENGINE_CELLS_SKIPPED_TOTAL.add(
                                            skip_count,
                                            {
                                                "symbol": symbol,
                                                "tf": skip_tf,
                                                "skip_reason": skip_reason,
                                            },
                                        )
                            if not result["error"]:
                                # UPSERT fingerprint rows for ALL of this symbol's
                                # expected cells (not just the ones found invalid)
                                # -- the whole symbol was recomputed, so every
                                # cell's fingerprint is now definitively fresh.
                                fp_rows = [
                                    _fp_row(symbol, tf, pass_type, training_window_end, fp)
                                    for (tf, pass_type), fp in current_fp_cache.get(
                                        symbol, {}
                                    ).items()
                                ]
                                _upsert_cell_fingerprints(settings, fp_rows)
                            n_done += 1
                            IC_ENGINE_SYMBOLS_COMPLETED_TOTAL.add(1, {"source": "fresh"})
                            _logger.info(
                                "ic_engine.symbol_computed",
                                symbol=symbol,
                                n_rows=len(result["all_results"]),
                                n_skipped=result["n_skipped"],
                                progress=f"{n_done}/{len(symbols_to_compute)}",
                            )

            # ----------------------------------------------------------
            # Cross-sectional IC pass (equity_model_enabled=True only, i.e.
            # bool(enabled_groups)). Runs in main process after per-symbol workers
            # complete. Each enabled regime_group is pooled INDEPENDENTLY -- only
            # that group's own peer symbols (symbol_list, Phase 144 D-01 fix) --
            # one cell per (regime_group, tf, regime_label). Each cell's rows are
            # written immediately once computed (todo 130) -- see
            # _write_cs_cell_results.
            # ----------------------------------------------------------
            if equity_model_enabled:
                _logger.info("ic_engine.starting_cross_sectional_pass")
                # Circular block bootstrap CI (Component A, todo 091): ONE deterministic
                # RNG for the whole cross-sectional pass, shared/advanced across every
                # (regime_group, tf, regime_label) cell -- same reuse-not-reseed
                # convention as the per-symbol worker path. This is the CI that gates
                # ensemble eligibility.
                cs_rng = np.random.default_rng(
                    seed=_derive_worker_rng_seed("cross_sectional", config.bootstrap_seed)
                )

                # No long-lived connection here (todo 125, 2026-07-17): each cell in the
                # loop below now opens its own short-lived connection inside
                # _compute_cross_sectional_tf, closed before its multi-hour compute-only
                # phase. Holding one connection open across this entire nested loop (as
                # before) meant it sat idle for hours at a time and was silently killed
                # mid-pass -- the exact cause of the 143.1-07 corpus re-run's repeated
                # "server closed the connection unexpectedly" crash.
                #
                # cs_cell_plan was discovered + fingerprint-checked in the pre-pass
                # above (same cs_regimes query, run once) -- a fingerprint-valid cell
                # skips _compute_cross_sectional_tf entirely (its multi-hour fetch+
                # compute is never invoked, not just its insert), an invalid one is
                # DELETE-then-recomputed and its fingerprint UPSERTed on success.
                for cell in cs_cell_plan:
                    group_name = cell["group_name"]
                    tf = cell["tf"]
                    regime_label = cell["regime_label"]
                    group_symbols = cell["group_symbols"]
                    cs_symbol_key = cell["cs_symbol_key"]

                    if cell["classification"] != "invalid":
                        _logger.info(
                            "ic_engine.cross_sectional_cell_skipped_fingerprint_valid",
                            regime_group=group_name,
                            tf=tf,
                            regime=regime_label,
                        )
                        continue

                    # todo 252: archive-then-delete, same transaction -- see the per-symbol
                    # call site above for the full rationale. fp_symbol is cs_symbol_key
                    # (ic_cell_fingerprints' real per-cell key), NOT _CROSS_SECTIONAL_SYMBOL
                    # (feature_ic_scores' 'POOLED' sentinel) -- see _ARCHIVE_BEFORE_DELETE_SQL's
                    # docstring for why the two tables' symbol columns mean different things
                    # for cross-sectional cells.
                    with _short_lived_conn(settings) as delete_conn:
                        with delete_conn.cursor() as cur:
                            cs_params = {
                                "symbol": _CROSS_SECTIONAL_SYMBOL,
                                "fp_symbol": cs_symbol_key,
                                "tf": tf,
                                "regime_label": regime_label,
                                "training_window_end": training_window_end,
                            }
                            cur.execute(_ARCHIVE_BEFORE_DELETE_CROSS_SECTIONAL_SQL, cs_params)
                            cur.execute(
                                _FINGERPRINT_INVALIDATE_DELETE_CROSS_SECTIONAL_SQL, cs_params
                            )
                        delete_conn.commit()

                    cs_rows, cs_stats = _compute_cross_sectional_tf(
                        dsn=settings.database_url,
                        tf=tf,
                        regime_label=regime_label,
                        regime_group=group_name,
                        symbol_list=group_symbols,
                        training_window_end=training_window_end,
                        config=config,
                        tracer=tracer,
                        run_ts=run_ts,
                        rng=cs_rng,
                        feature_status_map=feature_status_map,
                    )
                    total_committed += _write_cs_cell_results(settings, cs_rows)
                    total_skipped += cs_stats.get("n_skipped", 0)
                    fp = cell["current_fp"]
                    _upsert_cell_fingerprints(
                        settings,
                        [_fp_row(cs_symbol_key, tf, "cross_sectional", training_window_end, fp)],
                    )
                    _logger.info(
                        "ic_engine.cross_sectional_computed",
                        regime_group=group_name,
                        tf=tf,
                        regime=regime_label,
                        n_rows=len(cs_rows),
                    )

            # ----------------------------------------------------------
            # Corpus-level BH-FDR backfill (P2 fix; todo 130) through the
            # post-run lifecycle hook: one shared connection for this whole
            # block. Every step here is either a DB round-trip with no
            # intervening compute, or pure in-memory Python (the gauge-patch
            # loop below) -- none of it is the multi-hour compute phase the
            # short-lived-per-step pattern exists to protect against, so
            # there's no idle-connection risk in sharing one connection start
            # to finish.
            # ----------------------------------------------------------
            with _short_lived_conn(settings) as post_compute_conn:
                # BH-FDR backfill. Every per-symbol and cross-sectional row is
                # already durable in feature_ic_scores by this point (written
                # immediately as each unit of compute finished above) -- this
                # is a cheap, query-driven UPDATE-only pass, not a dependency
                # the rest of the run's persistence waits on. Queries whatever
                # is currently pending (passes_fdr IS NULL) for this
                # training_window_end rather than in-memory bookkeeping, so
                # it's safe to rerun after a crash regardless of which
                # invocation wrote the pending rows. See _backfill_bh_fdr's
                # docstring.
                fdr_updates = _backfill_bh_fdr(
                    post_compute_conn, training_window_end, config.fdr_alpha
                )
                _logger.info("ic_engine.corpus_fdr_backfilled", n_updated=len(fdr_updates))

                # Patch each symbol's in-memory result dicts with their final FDR
                # outcome, group by tf, and emit OTel health gauges -- one pass per
                # symbol. Gauges only ever need that symbol's own rows, so patching
                # and grouping don't need a separate corpus-wide pass before
                # emission starts.
                fdr_by_key = {
                    (u["feature_name"], u["symbol"], u["tf"], u["regime"], u["lookahead_bars"]): u
                    for u in fdr_updates
                }
                for sym, sym_results in per_symbol_results:
                    if not sym_results:
                        continue
                    by_tf: dict[str, list] = {}
                    for r in sym_results:
                        # Only cluster representatives are ever left pending
                        # (passes_fdr is None); non-representatives already
                        # got their final False locked in at compute time and
                        # can never be in fdr_by_key -- skip the lookup.
                        if r["passes_fdr"] is None:
                            match = fdr_by_key.get(
                                (
                                    r["feature_name"],
                                    r["symbol"],
                                    r["tf"],
                                    r["regime"],
                                    r["lookahead_bars"],
                                )
                            )
                            if match:
                                r["bh_adjusted_p"] = match["bh_adjusted_p"]
                                r["passes_fdr"] = match["passes_fdr"]
                        tf_key = r.get("tf")
                        if tf_key:
                            by_tf.setdefault(tf_key, []).append(r)
                    for tf_key, tf_results in by_tf.items():
                        _emit_health_gauges(sym, tf_key, tf_results)
                    _logger.info("ic_engine.symbol_done", symbol=sym, n_rows=len(sym_results))

                # Manifest stats.
                with post_compute_conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT tf, COUNT(*) as count
                        FROM feature_ic_scores
                        WHERE training_window_end = %s
                        GROUP BY tf
                        ORDER BY tf
                        """,
                        (training_window_end,),
                    )
                    rows_by_tf = {r[0]: r[1] for r in cur.fetchall()}

                    cur.execute(
                        """
                        SELECT regime, COUNT(*) as count
                        FROM feature_ic_scores
                        WHERE training_window_end = %s
                        GROUP BY regime
                        ORDER BY regime
                        """,
                        (training_window_end,),
                    )
                    rows_by_regime = {r[0]: r[1] for r in cur.fetchall()}

                    cur.execute(
                        "SELECT COUNT(*) FROM feature_ic_scores WHERE training_window_end = %s",
                        (training_window_end,),
                    )
                    rows_total = cur.fetchone()[0]

                # Post-run lifecycle hook (Phase 143 Plan 03: LIFECYCLE-03/04/
                # 05). Runs after the FDR backfill above is durable. Guarded:
                # a hook failure logs loudly but must never abort the run or
                # discard the already-committed IC results.
                try:
                    _run_lifecycle_hook(
                        post_compute_conn,
                        concept_svc,
                        config,
                        training_window_end,
                        manifest,
                    )
                except Exception as error:
                    _logger.error("ic_engine.lifecycle_hook_failed", error=str(error))

            elapsed = time.monotonic() - t0
            IC_ENGINE_RUN_LATENCY_SECONDS.record(elapsed)

            manifest.add_output(
                table_name="feature_ic_scores",
                rows_total=rows_total,
                rows_by_tf=rows_by_tf,
                rows_by_regime=rows_by_regime,
                columns_written=[
                    "feature_name",
                    "vector_domain",
                    "symbol",
                    "tf",
                    "regime",
                    "lookahead_bars",
                    "training_window_end",
                    "is_pooled",
                    "n_independent",
                    "reliable",
                    "ic_value",
                    "ic_sign",
                    "p_value",
                    "ic_ci_lower",
                    "ic_ci_upper",
                    "passes_ci_gate",
                    "bh_adjusted_p",
                    "passes_fdr",
                    "wf_fold_count",
                    "wf_pass_count",
                    "wf_ic_sharpe",
                    "passes_walkforward",
                    "ic_sharpe",
                    "ic_sharpe_n_windows",
                    "regime_label_source",
                    "cumulative_e_value",
                ],
            )

            # Mark success and write manifest
            manifest.mark_success()
            manifest_path = manifest.write()
            _logger.info("ic_engine.manifest_written", path=str(manifest_path))

            # 162-03: no .pkl checkpoint cleanup -- the checkpoint system is deleted
            # (see the module-level comment above _write_symbol_results). Per-symbol
            # immediate writes + the cross-run fingerprint gate are the durability
            # and resumability mechanism now; there is nothing on disk to clean up.

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

        # Record error in manifest
        manifest.add_error(str(error))
        try:
            manifest.write()
        except Exception:
            pass  # Don't let manifest write failure hide the original error
    finally:
        if conn is not None:
            conn.close()
        # No write_conn to close here -- every write (per-symbol, per-cell,
        # FDR backfill, manifest stats) opens and closes its own connection
        # internally (todo 130).
        JOB_COMPLETED_TOTAL.add(1, {"job": _JOB, "status": status})
        flush_and_shutdown_metrics()

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
