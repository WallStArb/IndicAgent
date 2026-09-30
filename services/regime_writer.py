#!/usr/bin/env python3
"""Regime Writer — oneshot that populates feature_vectors.regime and .regime_volatility.

Walk-forward is the only mode (D-29): the full-history single fit and its `--walk-forward`
switches are deleted. The HMM math lives in `src/intelligence/features/kernels/_hmm.py` and is
exposed as pure registry kernels in `kernels/regime.py` (`hmm_trend_walk_forward`,
`hmm_volatility_walk_forward` and their label kernels). This module fetches bars, calls the
kernels and batch-UPDATEs feature_vectors with canonical text labels. Its UPDATE path is
refused by the todo 426 disk guard in `compressed_hypertable_write_session`; the rebuild
(186-25) computes regime columns in its own append-only pass from the same kernels (R-10).

Each (symbol, tf) gets one walk-forward HMM: at every refit boundary a GaussianHMM (log-returns
+ realized-vol observation matrix from market_data_ohlcv_tradeable, NOT feature_vectors) is
fit on the observations before that boundary only, and the next segment is decoded causally
by forward-filter alpha-pass ONLY.

CORRECTNESS INVARIANTS:
- Observation matrix from market_data_ohlcv_tradeable, NOT feature_vectors (no OHLCV columns there).
- Decoding uses forward-filter (alpha-pass only), mirroring hmm_regime.py:_forward_step().
  model.predict() is NOT used — it runs full-sequence Viterbi and leaks future information.
- Each (symbol, tf) gets its own independent HMM fit. No shared model across TFs.
- Regime labels are deterministically mapped by emission mean[:, 0] (log-return dimension):
    K=2: trending_up (high), trending_down (low)
    K=3: trending_up, ranging, trending_down
    K=5: trending_up, transition_up, ranging, transition_down, trending_down
         (BIC-validated K as of Phase 140.5-P2 BIC study 2026-06-26)
  For K>3, hmm_prob_trending_up/down aggregate all bullish/bearish probability mass.

DAG invariant note: this oneshot is exempt from the "only writer subclasses touch DB"
rule exactly as backfill_feature_factory.py is — it is a batch labeling tool, not a
real-time daemon. The ring 2 boundary still holds: no async pipeline, no Kafka.

KNOWN, REASONED EXCLUSIONS (todo 168, investigated 2026-07-24 — do not re-investigate
from scratch, read this first): the following (symbol, tf) cells reliably fail
_check_occupation_gate (degenerate_occupation) and are NOT a bug:
  - LQD, PFF, USMV: degenerate/near-miss at EVERY tf (1d included)
  - EFA, FXI: 1h only
  - FXY: 15m, 1h (15m is a severe collapse, min_fraction ~0.00008)
  - RSP: 15m, 1h, 5m
  - UUP: 15m, 5m (5m is a true collapse, two of five states never occur)
  - VWO, XRT: 5m only
Ruled out as causes (don't re-test these): the min_state_occupation=0.05 floor itself
(corpus-wide distribution check across 198 already-successful (symbol,tf) cells shows
the worst successful fit is 0.0502 — right at the floor, not evidence of miscalibration)
and min_hold_bars smoothing (tested directly at 1/2/3/5 against 3 of the worst cases,
zero effect). Pattern: near-universal success at 1d, failures concentrated at intraday
tf, for lower-beta/mean-reverting instrument types (bonds, preferred shares, low-vol
factor, currency ETFs) — reads as a genuine limit of a uniform K=5 trend-state HMM at
high frequency for these instruments, not a defect. Do not force these onto K=5 by
construction; a per-symbol K override was considered and rejected as unwarranted
complexity for a bounded, already-identified set of cells.

Usage:
    python services/regime_writer.py
    python services/regime_writer.py --symbols SPY TLT
    python services/regime_writer.py --tf 5m 15m
    python services/regime_writer.py --symbols SPY --tf 5m
    python services/regime_writer.py --workers 12 --refit
"""

from __future__ import annotations

import argparse
import contextlib
import math
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np
import psycopg
import structlog
from opentelemetry import trace

# Set up sys.path before project imports
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from services._batch_utils import bulk_update_by_key as _bulk_update_by_key
from services._batch_utils import compressed_hypertable_write_session as _write_session
from services._batch_utils import load_config_service_sync as _load_config_service_shared
from services._batch_utils import make_worker_pool as _make_worker_pool
from src.config.settings import Settings
from src.core.service_utils import setup_service_logging
from src.intelligence.features.feature_vector_persistence import (
    REGIME_VOLATILITY_WRITER_OWNED_COLUMN_NAMES,
    REGIME_WRITER_OWNED_COLUMN_NAMES,
)

# Moved to the registry kernels (186-13); re-imported under their old names so ops scripts
# and tests keep importing them from here.
from src.intelligence.features.kernels._hmm import (
    _LABEL_CALM as _LABEL_CALM,
)
from src.intelligence.features.kernels._hmm import (
    _LABEL_ELEVATED as _LABEL_ELEVATED,
)
from src.intelligence.features.kernels._hmm import (
    _LABEL_RANGING as _LABEL_RANGING,
)
from src.intelligence.features.kernels._hmm import (
    _LABEL_TRANSITION_DOWN as _LABEL_TRANSITION_DOWN,
)
from src.intelligence.features.kernels._hmm import (
    _LABEL_TRANSITION_UP as _LABEL_TRANSITION_UP,
)
from src.intelligence.features.kernels._hmm import (
    _LABEL_TRENDING_DOWN as _LABEL_TRENDING_DOWN,
)
from src.intelligence.features.kernels._hmm import (
    _LABEL_TRENDING_UP as _LABEL_TRENDING_UP,
)
from src.intelligence.features.kernels._hmm import (
    _LABEL_TURBULENT as _LABEL_TURBULENT,
)
from src.intelligence.features.kernels._hmm import (
    _MIN_OBS_FACTOR_DEFAULT as _MIN_OBS_FACTOR_DEFAULT,
)
from src.intelligence.features.kernels._hmm import (
    _TREND_VOCAB as _TREND_VOCAB,
)
from src.intelligence.features.kernels._hmm import (
    _VOLATILITY_VOCAB as _VOLATILITY_VOCAB,
)
from src.intelligence.features.kernels._hmm import (
    _WALK_FORWARD_DEFAULT_PARAMS as _WALK_FORWARD_DEFAULT_PARAMS,
)
from src.intelligence.features.kernels._hmm import (
    _alpha_history_to_regime_probs as _alpha_history_to_regime_probs,
)
from src.intelligence.features.kernels._hmm import (
    _alpha_pass as _alpha_pass,
)
from src.intelligence.features.kernels._hmm import (
    _build_label_map as _build_label_map,
)
from src.intelligence.features.kernels._hmm import (
    _build_obs_matrix as _build_obs_matrix,
)
from src.intelligence.features.kernels._hmm import (
    _build_obs_matrix_volatility as _build_obs_matrix_volatility,
)
from src.intelligence.features.kernels._hmm import (
    _causal_decode as _causal_decode,
)
from src.intelligence.features.kernels._hmm import (
    _check_occupation_gate as _check_occupation_gate,
)
from src.intelligence.features.kernels._hmm import (
    _compute_hmm_churn as _compute_hmm_churn,
)
from src.intelligence.features.kernels._hmm import (
    _compute_log_emit as _compute_log_emit,
)
from src.intelligence.features.kernels._hmm import (
    _hmm_seed_stability_check as _hmm_seed_stability_check,
)
from src.intelligence.features.kernels._hmm import (
    _log_emit_diag as _log_emit_diag,
)
from src.intelligence.features.kernels._hmm import (
    _log_emit_full as _log_emit_full,
)
from src.intelligence.features.kernels._hmm import (
    _rolling as _rolling,
)
from src.intelligence.features.kernels._hmm import (
    _seed_prior_from_label as _seed_prior_from_label,
)
from src.intelligence.features.kernels._hmm import (
    _smooth_states as _smooth_states,
)
from src.intelligence.features.kernels._hmm import (
    _state_groups as _state_groups,
)
from src.intelligence.features.kernels._hmm import (
    _state_groups_by_vocab as _state_groups_by_vocab,
)
from src.intelligence.features.kernels._hmm import (
    _stationary_distribution as _stationary_distribution,
)
from src.intelligence.features.kernels._hmm import (
    _walk_forward_hmm_full as _walk_forward_hmm_full,
)
from src.intelligence.features.kernels._hmm import (
    _walk_forward_hmm_labels as _walk_forward_hmm_labels,
)
from src.intelligence.features.kernels._hmm import (
    hmm_config_fields_from_values,
)
from src.intelligence.hmm_jit import alpha_pass_jit as _alpha_pass_jit
from src.observability.metrics import (
    JOB_COMPLETED_TOTAL,
    REGIME_WRITER_NULL_REGIME_REMAINING,
    REGIME_WRITER_ROWS_UPDATED_TOTAL,
    REGIME_WRITER_RUN_LATENCY_SECONDS,
    flush_and_shutdown_metrics,
)
from src.observability.otel import OTelInitError, init_otel_providers

setup_service_logging("logs/regime_writer.log")

_logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_JOB = "regime-writer"

# HMM random state loaded from APR at runtime: alpha.hmm.random_state (default 42).
# Changing it invalidates all regime labels in feature_vectors — requires full re-run.

# Default target timeframes (matches backfill_feature_factory.py targets).
_DEFAULT_TFS: list[str] = ["5m", "15m", "1h", "1d"]

# The only two feature_vectors columns _discover_symbols is ever allowed to query
# against. label_column is internally sourced (from --regime-column, itself
# argparse `choices`-constrained) so this is defense-in-depth, not a real external
# injection surface -- but validating against this frozenset before interpolation
# makes that true structurally rather than by inspection (T-172-04-SQL).
_DISCOVERY_LABEL_COLUMNS = frozenset({"regime", "regime_volatility"})


@contextlib.contextmanager
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


# ---------------------------------------------------------------------------
# Walk-forward compute over the regime kernels
# ---------------------------------------------------------------------------


def _fetch_bars(conn: Any, symbol: str, tf: str) -> dict[str, Any] | None:
    """Timestamps, closes and volumes of one (symbol, tf) series from
    `market_data_ohlcv_tradeable`, or None (logging `regime_writer.no_ohlcv`) when there are none.

    Server-side cursors require no active transaction, so any open one is committed first.
    """
    timestamps: list = []
    closes: list[float] = []
    volumes: list[float] = []
    conn.commit()
    with conn.cursor("ohlcv_stream") as cur:
        cur.execute(
            "SELECT timestamp, close, volume "
            "FROM market_data_ohlcv_tradeable "
            "WHERE symbol = %s AND timeframe = %s "
            "ORDER BY timestamp ASC",
            (symbol, tf),
        )
        while True:
            batch = cur.fetchmany(10000)
            if not batch:
                break
            for r in batch:
                timestamps.append(r[0])
                closes.append(float(r[1]))
                volumes.append(float(r[2]))
    if not timestamps:
        _logger.warning("regime_writer.no_ohlcv", symbol=symbol, tf=tf)
        return None
    return {"timestamps": timestamps, "close": closes, "volume": volumes}


def _compute_family_rows(
    bars: dict[str, Any], family: str, config: Any, tf: str, symbol: str
) -> tuple[list[tuple], bool, float] | None:
    """Run one family's walk-forward kernel over `bars` and build the UPDATE rows.

    Each row is (label, the 7 numeric columns in owned-column order, symbol, tf, timestamp),
    the order `bulk_update_by_key` needs. Bars the kernel did not write (before the first model,
    or in a degenerate or non-converged segment) are absent, so a fresh `feature_vectors` row
    stays NULL rather than carrying a fabricated value. Returns None when no bar was written.
    `converged` is True whenever anything was written, because the segment gate refuses a
    non-converged fit; `heldout_ll` is always NaN, as walk-forward has no single held-out score.
    """
    from src.intelligence.features.contract.registry import compute_kernels, default_registry
    from src.intelligence.features.kernels.regime import FAMILY_KERNELS

    spec = FAMILY_KERNELS[family]
    prefix = "volatility_" if family == "volatility" else ""
    n = len(bars["timestamps"])
    inputs = {
        "ts": np.array([int(t.timestamp()) * 1_000_000_000 for t in bars["timestamps"]]),
        "close": np.asarray(bars["close"], dtype=float),
        "volume": np.asarray(bars["volume"], dtype=float),
        "tf": np.array([tf] * n, dtype=object),
    }
    out = compute_kernels(
        default_registry(),
        inputs,
        config,
        outputs=[spec.code_output, spec.status_output, *spec.numeric_outputs],
    )
    status = out[spec.status_output]
    written = np.flatnonzero(status == 1.0)
    if len(written) == 0:
        event = "insufficient_obs" if not status.any() else "all_segments_degenerate"
        _logger.warning(
            f"regime_writer.{prefix}walk_forward_{event}", symbol=symbol, tf=tf, n_obs=n
        )
        return None
    codes = out[spec.code_output]
    numeric = [out[name] for name in spec.numeric_outputs]
    timestamps = bars["timestamps"]
    update_rows = [
        (
            spec.labels[int(codes[i])],
            *(float(column[i]) for column in numeric),
            symbol,
            tf,
            timestamps[i],
        )
        for i in written
    ]
    return update_rows, True, float("nan")


def _compute_symbol_tf_walk_forward(
    conn: Any,
    symbol: str,
    tf: str,
    n_components: int,
    vol_window: int,
    n_iter: int,
    hmm_random_state: int,
    momentum_window: int,
    vol_of_vol_window: int,
    refit_every_bars: int,
    initial_warmup_bars: int,
    covariance_type: str = "full",
    min_hold_bars: int = 3,
    full_cov_min_obs: int = 500,
    min_state_occupation: float = 0.05,
    churn_window: int = 10,
    min_obs_factor: int = _MIN_OBS_FACTOR_DEFAULT,
) -> tuple[list[tuple], bool, float] | None:
    """Walk-forward trend regime for one (symbol, tf) cell: (update_rows, converged, heldout_ll)
    or None. Fetches the bars and runs the `hmm_trend_walk_forward` kernel; the fit, gates,
    duration and churn rules are the kernel's (see `_hmm.walk_forward_family_arrays`).
    """
    bars = _fetch_bars(conn, symbol, tf)
    if bars is None:
        return None
    config = _hmm_kernel_config(
        tf,
        refit_every_bars,
        initial_warmup_bars,
        hmm_n_components=n_components,
        hmm_vol_window=vol_window,
        hmm_momentum_window=momentum_window,
        hmm_vol_of_vol_window=vol_of_vol_window,
        hmm_n_iter=n_iter,
        hmm_random_state=hmm_random_state,
        hmm_covariance_type=covariance_type,
        hmm_min_hold_bars=min_hold_bars,
        hmm_full_cov_min_obs=full_cov_min_obs,
        hmm_min_state_occupation=min_state_occupation,
        hmm_churn_window=churn_window,
        hmm_min_obs_factor=min_obs_factor,
    )
    return _compute_family_rows(bars, "trend", config, tf, symbol)


def _compute_symbol_tf_volatility_walk_forward(
    conn: Any,
    symbol: str,
    tf: str,
    n_components: int,
    vol_window: int,
    vol_of_vol_window: int,
    n_iter: int,
    hmm_random_state: int,
    refit_every_bars: int,
    initial_warmup_bars: int,
    covariance_type: str = "full",
    min_hold_bars: int = 3,
    full_cov_min_obs: int = 500,
    min_state_occupation: float = 0.05,
    churn_window: int = 10,
    min_obs_factor: int = _MIN_OBS_FACTOR_DEFAULT,
) -> tuple[list[tuple], bool, float] | None:
    """Volatility counterpart of `_compute_symbol_tf_walk_forward`, over the
    `hmm_volatility_walk_forward` kernel (close only; the volume column is fetched with the
    bars and not read)."""
    bars = _fetch_bars(conn, symbol, tf)
    if bars is None:
        return None
    config = _hmm_kernel_config(
        tf,
        refit_every_bars,
        initial_warmup_bars,
        hmm_volatility_n_components=n_components,
        hmm_volatility_vol_window=vol_window,
        hmm_volatility_vol_of_vol_window=vol_of_vol_window,
        hmm_volatility_covariance_type=covariance_type,
        hmm_n_iter=n_iter,
        hmm_random_state=hmm_random_state,
        hmm_min_hold_bars=min_hold_bars,
        hmm_full_cov_min_obs=full_cov_min_obs,
        hmm_min_state_occupation=min_state_occupation,
        hmm_churn_window=churn_window,
        hmm_min_obs_factor=min_obs_factor,
    )
    return _compute_family_rows(bars, "volatility", config, tf, symbol)


def _hmm_kernel_config(
    tf: str, refit_every_bars: int, initial_warmup_bars: int, **fields: Any
) -> SimpleNamespace:
    """The hmm_* config attributes the regime kernels read, for one tf's schedule.

    The kernels read only `hmm_*` attributes, so the writer (which has no full
    `FeatureFactoryConfig`) passes this namespace over the APR defaults.
    """
    base = hmm_config_fields_from_values(lambda key, default: default)
    base.update(fields)
    base[f"hmm_refit_every_bars_{tf}"] = refit_every_bars
    base[f"hmm_initial_warmup_bars_{tf}"] = initial_warmup_bars
    return SimpleNamespace(**base)


def _regime_family_col_types(owned_columns: tuple[str, ...]) -> dict[str, str]:
    """Derive `_bulk_update_by_key`'s `col_types` from an owned-column tuple.

    Both regime column families share one shape: element 0 is the text label
    column, every remaining element is a `real` probability/stat
    column, plus the fixed `(symbol, tf, bar_ts)` key columns. Deriving this
    instead of hand-typing it in each writer keeps col_types from drifting out
    of sync with REGIME_WRITER_OWNED_COLUMN_NAMES /
    REGIME_VOLATILITY_WRITER_OWNED_COLUMN_NAMES the same way set_cols already
    does -- a column added to one and not the other used to be a silent
    KeyError risk in `_bulk_update_by_key`.

    Corrected 2026-08-14 (todo 312): these columns were `double precision` when this
    function was first written but migrations 201/312 narrowed them all to `real` --
    that drift went undetected because col_types was, until the same fix, only used for
    the temp table's DDL (psycopg's implicit double->real cast at the final UPDATE
    masked the mismatch, right up until a genuinely out-of-range value -- an HMM
    posterior probability underflowing float4's representable range -- finally made it
    visible as a write failure). Now also the source of truth for bulk_update_by_key's
    float-range clamp, so this string must track the live schema exactly, not just be
    "close enough" for DDL purposes.
    """
    label_col, *stat_cols = owned_columns
    return {
        label_col: "text",
        **{c: "real" for c in stat_cols},
        "symbol": "text",
        "tf": "text",
        "bar_ts": "timestamptz",
    }


def _write_regime_results(
    conn: Any,
    symbol: str,
    tf: str,
    update_rows: list[tuple],
    converged: bool,
    heldout_ll: float,
    tracer: Any,
) -> int:
    """Write HMM regime labels for one (symbol, tf) cell to feature_vectors.

    Runs in the main process — single serial write connection, no concurrency.
    Returns n_updated.
    """
    with tracer.start_as_current_span(
        "regime_writer.write_symbol_tf",
        attributes={"symbol": symbol, "tf": tf},
    ) as span:
        try:
            _bulk_update_by_key(
                conn,
                table="feature_vectors",
                temp_table="_regime_writer_staging",
                key_cols=["symbol", "tf", "bar_ts"],
                # Ordered tuple, not a set, because bulk_update_by_key's `rows` param
                # requires (*set_cols, *key_cols) positional order -- see the
                # docstring on the fitting function above:
                # (regime, p_up, p_ranging, p_down, prob_val, entropy_val,
                # duration, hmm_churn, symbol, tf, ts). Imported from
                # feature_vector_persistence.py (Ring 1) rather than hand-typed
                # here so this ownership list can never drift from the one
                # feature_vector_persistence.py excludes from --refresh's
                # DO UPDATE SET -- both now derive from the same source of truth.
                set_cols=list(REGIME_WRITER_OWNED_COLUMN_NAMES),
                col_types=_regime_family_col_types(REGIME_WRITER_OWNED_COLUMN_NAMES),
                rows=update_rows,
            )
            conn.commit()
            # Single query returns both counts in one round trip.
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT "
                    "  count(*) FILTER (WHERE regime IS NOT NULL), "
                    "  count(*) FILTER (WHERE regime IS NULL) "
                    "FROM feature_vectors WHERE symbol = %s AND tf = %s",
                    (symbol, tf),
                )
                n_updated, remaining = cur.fetchone()
                n_updated = int(n_updated)
                remaining = int(remaining)

            REGIME_WRITER_NULL_REGIME_REMAINING.set(remaining, {"symbol": symbol, "tf": tf})
            span.set_attribute("n_updated", n_updated)
            span.set_attribute("null_remaining", remaining)
            _logger.info(
                "regime_writer.symbol_tf_done",
                symbol=symbol,
                tf=tf,
                n_updated=n_updated,
                null_remaining=remaining,
                converged=converged,
                heldout_ll_per_obs=round(heldout_ll, 4) if math.isfinite(heldout_ll) else None,
            )
            return n_updated

        except Exception as error:
            from opentelemetry.trace import StatusCode

            span.set_status(StatusCode.ERROR, str(error))
            span.record_exception(error)
            raise


def _write_regime_volatility_results(
    conn: Any,
    symbol: str,
    tf: str,
    update_rows: list[tuple],
    converged: bool,
    tracer: Any,
) -> int:
    """Write regime_volatility labels for one (symbol, tf) cell to feature_vectors
    (Phase 172). Volatility-family counterpart of `_write_regime_results` -- same shape
    (bulk UPDATE via a temp-table JOIN, then a paired NOT NULL / NULL count query, then a
    log record), pointed at the 8-column `regime_volatility` family instead of the legacy
    `regime` family. No `heldout_ll` parameter/field -- the volatility path is
    walk-forward-only and that value is always NaN there (see
    `_compute_symbol_tf_volatility_walk_forward`'s docstring).

    Runs in the main process — single serial write connection, no concurrency.
    Returns n_updated.
    """
    with tracer.start_as_current_span(
        "regime_writer.write_volatility_symbol_tf",
        attributes={"symbol": symbol, "tf": tf},
    ) as span:
        try:
            _bulk_update_by_key(
                conn,
                table="feature_vectors",
                temp_table="_regime_volatility_writer_staging",
                key_cols=["symbol", "tf", "bar_ts"],
                # Ordered tuple, not a set -- see _write_regime_results' equivalent
                # comment. Imported from feature_vector_persistence.py (Ring 1) so this
                # ownership list can never drift from the one that module excludes from
                # --refresh's DO UPDATE SET; both derive from the same source of truth.
                set_cols=list(REGIME_VOLATILITY_WRITER_OWNED_COLUMN_NAMES),
                col_types=_regime_family_col_types(REGIME_VOLATILITY_WRITER_OWNED_COLUMN_NAMES),
                rows=update_rows,
            )
            conn.commit()
            # Single query returns both counts in one round trip.
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT "
                    "  count(*) FILTER (WHERE regime_volatility IS NOT NULL), "
                    "  count(*) FILTER (WHERE regime_volatility IS NULL) "
                    "FROM feature_vectors WHERE symbol = %s AND tf = %s",
                    (symbol, tf),
                )
                n_updated, remaining = cur.fetchone()
                n_updated = int(n_updated)
                remaining = int(remaining)

            # Extra "regime_column" attribute makes this a distinct time series from
            # _write_regime_results' two-attribute series -- the existing series keeps
            # its identity and the two families are never conflated in the same gauge.
            REGIME_WRITER_NULL_REGIME_REMAINING.set(
                remaining, {"symbol": symbol, "tf": tf, "regime_column": "regime_volatility"}
            )
            span.set_attribute("n_updated", n_updated)
            span.set_attribute("null_remaining", remaining)
            _logger.info(
                "regime_writer.volatility_symbol_tf_done",
                symbol=symbol,
                tf=tf,
                n_updated=n_updated,
                null_remaining=remaining,
                converged=converged,
            )
            return n_updated

        except Exception as error:
            from opentelemetry.trace import StatusCode

            span.set_status(StatusCode.ERROR, str(error))
            span.record_exception(error)
            raise


# ---------------------------------------------------------------------------
# Symbol discovery
# ---------------------------------------------------------------------------


def _discover_symbols(conn: Any, label_column: str = "regime") -> list[str]:
    """Return symbols that have at least one un-labeled row in feature_vectors,
    where "un-labeled" means `label_column IS NULL`.

    Skips symbols where every row already has a label in `label_column`, so restarts
    are safe. `label_column` defaults to `"regime"` (today's behavior, unchanged) and
    is validated against `_DISCOVERY_LABEL_COLUMNS` before being interpolated into the
    query -- raises `ValueError` on anything else, so this parameter can never become
    a SQL injection surface even though its only caller (`main()`) sources it from an
    argparse `choices`-constrained flag. Getting this column wrong on a
    `regime_volatility` run is not cosmetic: querying `regime IS NULL` for a
    volatility run would skip every symbol whose legacy `regime` column happens to be
    fully populated, silently dropping it from the corpus relabel -- CLAUDE.md's data
    retention rule requires every qualifying cell be labeled, never quietly omitted.
    """
    if label_column not in _DISCOVERY_LABEL_COLUMNS:
        raise ValueError(
            f"_discover_symbols: label_column must be one of {sorted(_DISCOVERY_LABEL_COLUMNS)}, "
            f"got {label_column!r}"
        )
    with conn.cursor() as cur:
        # label_column is validated against _DISCOVERY_LABEL_COLUMNS above, so this
        # f-string interpolation can never carry attacker-controlled SQL.
        cur.execute(
            f"SELECT DISTINCT symbol FROM feature_vectors "
            f"WHERE {label_column} IS NULL ORDER BY symbol"
        )
        return [r[0] for r in cur.fetchall()]


# ---------------------------------------------------------------------------
# Subprocess worker for ProcessPoolExecutor
# ---------------------------------------------------------------------------


def _run_symbol_worker(args: tuple) -> dict:
    """Worker function for ProcessPoolExecutor — runs in subprocess.

    Opens its own psycopg connection for OHLCV reads only. Runs HMM compute
    and returns update_rows to the main process; never writes to the DB.

    Args:
        args: a 17-element positional tuple. A long positional tuple crossing a
            ProcessPoolExecutor boundary has no arity or ordering enforcement at the
            call site -- a future insertion anywhere before the last position shifts every
            element after it and binds silently, producing wrong parameters rather
            than an error. This enumeration, and the test suite's arity/position pin,
            are the containment for that failure mode:

            0.  symbol: str
            1.  tfs: list[str]
            2.  dsn: str
            3.  n_components: int
            4.  vol_window: int
            5.  momentum_window: int
            6.  vol_of_vol_window: int
            7.  n_iter: int
            8.  hmm_random_state: int
            9.  covariance_type: str
            10. min_hold_bars: int
            11. full_cov_min_obs: int
            12. min_state_occupation: float
            13. churn_window: int
            14. min_obs_factor: int
            15. walk_forward_params: dict[str, tuple[int, int]]
            16. regime_column: str  ("regime" or "regime_volatility", Phase 172)

        walk_forward_params: dict[str, tuple[int, int]] mapping tf ->
            (refit_every_bars, initial_warmup_bars), tf-calibrated (APR:
            alpha.hmm.walk_forward.refit_every_bars.<tf> /
            .initial_warmup_bars.<tf>) since bars-per-refit-window is the
            actionable variable behind the pilot's cross-tf stability finding
            (docs/analysis/hmm-parameter-lookahead-pilot-spy-1h.md's broadened
            results). Consulted for either column family -- the schedule is calibrated
            on bar density per refit window, a property of the timeframe, not of which
            observation columns are fitted (migration 307's reuse decision).
        regime_column (Phase 172): "regime" routes every tf through
            `_compute_symbol_tf_walk_forward`, "regime_volatility" through
            `_compute_symbol_tf_volatility_walk_forward`. Walk-forward is the only mode
            (D-29): the full-history single fit is deleted.

    Returns:
        dict with keys:
          symbol: str
          results: list of {tf, update_rows, converged, heldout_ll} or {tf, error}
          error: str | None  (set if connection itself failed)
    """
    (
        symbol,
        tfs,
        dsn,
        n_components,
        vol_window,
        momentum_window,
        vol_of_vol_window,
        n_iter,
        hmm_random_state,
        covariance_type,
        min_hold_bars,
        full_cov_min_obs,
        min_state_occupation,
        churn_window,
        min_obs_factor,
        walk_forward_params,
        regime_column,
    ) = args

    setup_service_logging("logs/regime_writer.log")
    worker_log = structlog.get_logger(__name__)

    conn = None
    results = []
    error_msg = None

    try:
        conn = psycopg.connect(dsn, options="-c idle_in_transaction_session_timeout=0")

        for tf in tfs:
            try:
                refit_every_bars, initial_warmup_bars = walk_forward_params[tf]
                if regime_column == "regime_volatility":
                    result = _compute_symbol_tf_volatility_walk_forward(
                        conn=conn,
                        symbol=symbol,
                        tf=tf,
                        n_components=n_components,
                        vol_window=vol_window,
                        vol_of_vol_window=vol_of_vol_window,
                        n_iter=n_iter,
                        hmm_random_state=hmm_random_state,
                        refit_every_bars=refit_every_bars,
                        initial_warmup_bars=initial_warmup_bars,
                        covariance_type=covariance_type,
                        min_hold_bars=min_hold_bars,
                        full_cov_min_obs=full_cov_min_obs,
                        min_state_occupation=min_state_occupation,
                        churn_window=churn_window,
                        min_obs_factor=min_obs_factor,
                    )
                else:
                    result = _compute_symbol_tf_walk_forward(
                        conn=conn,
                        symbol=symbol,
                        tf=tf,
                        n_components=n_components,
                        vol_window=vol_window,
                        n_iter=n_iter,
                        hmm_random_state=hmm_random_state,
                        momentum_window=momentum_window,
                        vol_of_vol_window=vol_of_vol_window,
                        refit_every_bars=refit_every_bars,
                        initial_warmup_bars=initial_warmup_bars,
                        covariance_type=covariance_type,
                        min_hold_bars=min_hold_bars,
                        full_cov_min_obs=full_cov_min_obs,
                        min_state_occupation=min_state_occupation,
                        churn_window=churn_window,
                        min_obs_factor=min_obs_factor,
                    )
                if result is None:
                    results.append(
                        {
                            "tf": tf,
                            "update_rows": None,
                            "converged": False,
                            "heldout_ll": float("nan"),
                        }
                    )
                else:
                    update_rows, converged, heldout_ll = result
                    results.append(
                        {
                            "tf": tf,
                            "update_rows": update_rows,
                            "converged": converged,
                            "heldout_ll": heldout_ll,
                        }
                    )
            except Exception as error:
                worker_log.error(
                    "regime_writer.worker_cell_failed",
                    symbol=symbol,
                    tf=tf,
                    error=str(error),
                )
                results.append({"tf": tf, "update_rows": None, "error": str(error)})
                try:
                    conn.rollback()
                except Exception:
                    # Connection is dead; remaining TFs for this symbol would also fail.
                    break

    except Exception as error:
        error_msg = str(error)
        worker_log.error("regime_writer.worker_failed", symbol=symbol, error=error_msg)
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass

    return {"symbol": symbol, "results": results, "error": error_msg}


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def _determine_run_status(total_updated: int, failures: list[str]) -> str:
    """Classify a completed run as success or failure.

    A run that attempted writes and failed every one of them (total_updated == 0
    with at least one failure) is a hard failure, not a completion -- confirmed
    2026-08-13 when a disk-full/Postgres-crash window caused every symbol/tf
    write to fail while the run still logged as regime_writer.run_complete.
    """
    if failures and total_updated == 0:
        return "failure"
    return "success"


def main() -> None:
    """Run regime labeler across all (symbol, tf) cells."""
    parser = argparse.ArgumentParser(description="Populate feature_vectors.regime via causal HMM")
    parser.add_argument(
        "--symbols",
        nargs="*",
        default=None,
        help="Symbols to label (default: all distinct symbols in feature_vectors)",
    )
    parser.add_argument(
        "--tf",
        nargs="*",
        default=_DEFAULT_TFS,
        help=f"Timeframes to label (default: {_DEFAULT_TFS})",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=None,
        help="Number of parallel workers (default: APR infra.regime_writer.workers, fallback 1)",
    )
    parser.add_argument(
        "--refit",
        action="store_true",
        default=False,
        help=(
            "Force regime re-labeling only (feature_vectors compute already done). "
            "Semantic documentation flag — regime_writer always fits GaussianHMM from scratch; "
            "--refit signals intent to callers that this run re-labels an existing corpus."
        ),
    )
    parser.add_argument(
        "--regime-column",
        choices=["regime", "regime_volatility"],
        default="regime",
        help=(
            "Which column family this invocation writes. One invocation writes "
            "exactly one family -- the two are deliberately not computed together "
            "because a 'regime_volatility' run must not rewrite the legacy 'regime' "
            "column, whose existing values were produced by the retired "
            "full-history-fit method (default: regime)."
        ),
    )
    args = parser.parse_args()

    # ------------------------------------------------------------------
    # OTel init (graceful — metrics are hard failure, traces optional)
    # ------------------------------------------------------------------
    try:
        init_otel_providers(service_name=_JOB)
    except OTelInitError as error:
        _logger.warning(
            "regime_writer.otel_init_failed",
            error=str(error),
            note="Continuing without OTel — metrics will not reach collector",
        )

    if args.refit:
        _logger.info(
            "regime_writer.refit_mode",
            note="Running in refit mode: re-labeling regimes only, feature_vectors compute already complete.",
        )

    tracer = trace.get_tracer("indicagent")
    t0 = time.monotonic()
    status = "success"

    try:
        settings = Settings()
        dsn = settings.database_url

        with tracer.start_as_current_span("regime_writer.run") as run_span:
            # Open a short-lived connection for APR load + symbol discovery, then close it.
            # Workers open their own connections — nothing is shared across processes.
            _conn = psycopg.connect(
                dsn,
                options="-c idle_in_transaction_session_timeout=0",
            )
            try:
                cfg = _load_config_service_shared(_conn)
                n_components = int(cfg.get_sync("feature.hmm.n_components", 3))
                vol_window = int(cfg.get_sync("feature.hmm.vol_window", 20))
                n_iter = int(cfg.get_sync("feature.hmm.n_iter", 200))
                hmm_random_state = int(cfg.get_sync("alpha.hmm.random_state", 42))
                momentum_window = int(cfg.get_sync("feature.hmm.obs_momentum_window", 20))
                vol_of_vol_window = int(cfg.get_sync("feature.hmm.obs_vol_of_vol_window", 20))
                covariance_type = cfg.get_sync("feature.hmm.covariance_type", "full")
                min_hold_bars = int(cfg.get_sync("feature.hmm.min_hold_bars", 3))
                full_cov_min_obs = int(cfg.get_sync("feature.hmm.full_cov_min_obs", 500))
                min_state_occupation = float(cfg.get_sync("feature.hmm.min_state_occupation", 0.05))
                churn_window = int(cfg.get_sync("feature.hmm.churn_window", 10))
                min_obs_factor = int(
                    cfg.get_sync("feature.hmm.min_obs_factor", _MIN_OBS_FACTOR_DEFAULT)
                )

                # Phase 172: for a regime_volatility run, override the 4 keys migration
                # 307 seeded under alpha.hmm_volatility.* -- n_components, vol_window,
                # vol_of_vol_window, covariance_type. Every other key above
                # (n_iter, hmm_random_state, momentum_window, min_hold_bars,
                # full_cov_min_obs, min_state_occupation, churn_window,
                # min_obs_factor, and the per-tf walk-forward schedule below) is REUSED
                # unchanged from its existing feature.hmm.*/alpha.hmm.* key -- migration
                # 307's own comments record this reuse decision explicitly (171-FINAL-VERDICT.md
                # section 1: the fitting-mechanics parameters were never implicated by the
                # investigation). momentum_window is read but never consumed on the
                # volatility path (_compute_symbol_tf_volatility_walk_forward has no such
                # parameter) -- harmless to still load it here since the two branches share
                # this one APR-load block.
                if args.regime_column == "regime_volatility":
                    n_components = int(cfg.get_sync("alpha.hmm_volatility.n_components", 3))
                    vol_window = int(cfg.get_sync("alpha.hmm_volatility.vol_window", 20))
                    vol_of_vol_window = int(
                        cfg.get_sync("alpha.hmm_volatility.vol_of_vol_window", 60)
                    )
                    covariance_type = cfg.get_sync("alpha.hmm_volatility.covariance_type", "full")

                # Per-tf (refit_every_bars, initial_warmup_bars) -- see
                # _WALK_FORWARD_DEFAULT_PARAMS' own docstring/comment above for the
                # full per-tf provenance and certainty caveats.
                walk_forward_params: dict[str, tuple[int, int]] = {
                    tf_key: (
                        int(
                            cfg.get_sync(
                                f"alpha.hmm.walk_forward.refit_every_bars.{tf_key}",
                                _WALK_FORWARD_DEFAULT_PARAMS[tf_key][0],
                            )
                        ),
                        int(
                            cfg.get_sync(
                                f"alpha.hmm.walk_forward.initial_warmup_bars.{tf_key}",
                                _WALK_FORWARD_DEFAULT_PARAMS[tf_key][1],
                            )
                        ),
                    )
                    for tf_key in _WALK_FORWARD_DEFAULT_PARAMS
                }

                symbols = (
                    args.symbols
                    if args.symbols
                    else _discover_symbols(_conn, label_column=args.regime_column)
                )
                tfs: list[str] = args.tf

                n_workers = args.workers
                if n_workers is None:
                    n_workers = int(cfg.get_sync("infra.regime_writer.workers", 1))
                # todo 216: BLAS thread cap, see make_worker_pool()/limit_blas_threads().
                blas_threads_per_worker = int(cfg.get_sync("infra.blas_threads_per_worker", 1))
            finally:
                _conn.close()
            # dsn is passed to workers; no connection is held in main beyond this point.

            _logger.info(
                "regime_writer.starting",
                symbols_count=len(symbols),
                tfs=tfs,
                n_components=n_components,
                vol_window=vol_window,
                momentum_window=momentum_window,
                vol_of_vol_window=vol_of_vol_window,
                n_iter=n_iter,
                n_workers=n_workers,
                covariance_type=covariance_type,
                min_hold_bars=min_hold_bars,
                min_state_occupation=min_state_occupation,
                churn_window=churn_window,
                regime_column=args.regime_column,
            )

            worker_args = [
                (
                    symbol,
                    tfs,
                    dsn,
                    n_components,
                    vol_window,
                    momentum_window,
                    vol_of_vol_window,
                    n_iter,
                    hmm_random_state,
                    covariance_type,
                    min_hold_bars,
                    full_cov_min_obs,
                    min_state_occupation,
                    churn_window,
                    min_obs_factor,
                    walk_forward_params,
                    args.regime_column,
                )
                for symbol in symbols
            ]

            # Pre-compile the JIT in the main process before spawning workers.
            # With cache=True the compile writes __pycache__ once; workers then load
            # the artifact read-only — no concurrent compile, no file-lock race.
            _jit_emit = np.zeros((10, n_components), dtype=np.float64)
            _jit_log_A = np.log(np.full((n_components, n_components), 1.0 / n_components))
            _jit_pi0 = np.full(n_components, 1.0 / n_components)
            _alpha_pass_jit(_jit_emit, _jit_log_A, _jit_pi0)
            _logger.info("regime_writer.jit_ready", n_components=n_components)

            total_updated = 0
            failures: list[str] = []

            write_conn = psycopg.connect(
                dsn,
                options="-c idle_in_transaction_session_timeout=0",
            )
            try:
                with (
                    _write_session(write_conn, "feature_vectors"),
                    _make_worker_pool(n_workers, blas_threads_per_worker) as pool,
                ):
                    for result in pool.map(_run_symbol_worker, worker_args, chunksize=1):
                        symbol = result["symbol"]
                        if result["error"]:
                            failures.append(symbol)
                            _logger.error(
                                "regime_writer.symbol_failed",
                                symbol=symbol,
                                error=result["error"],
                            )
                        for cell in result["results"]:
                            tf = cell["tf"]
                            if "error" in cell:
                                failures.append(f"{symbol}/{tf}")
                                continue
                            if cell["update_rows"] is None:
                                continue
                            try:
                                if args.regime_column == "regime_volatility":
                                    n = _write_regime_volatility_results(
                                        conn=write_conn,
                                        symbol=symbol,
                                        tf=tf,
                                        update_rows=cell["update_rows"],
                                        converged=cell.get("converged", False),
                                        tracer=tracer,
                                    )
                                    total_updated += n
                                    REGIME_WRITER_ROWS_UPDATED_TOTAL.add(
                                        n,
                                        {
                                            "symbol": symbol,
                                            "tf": tf,
                                            "regime_column": "regime_volatility",
                                        },
                                    )
                                else:
                                    n = _write_regime_results(
                                        conn=write_conn,
                                        symbol=symbol,
                                        tf=tf,
                                        update_rows=cell["update_rows"],
                                        converged=cell.get("converged", False),
                                        heldout_ll=cell.get("heldout_ll", float("nan")),
                                        tracer=tracer,
                                    )
                                    total_updated += n
                                    REGIME_WRITER_ROWS_UPDATED_TOTAL.add(
                                        n, {"symbol": symbol, "tf": tf}
                                    )
                            except Exception as error:
                                _logger.error(
                                    "regime_writer.write_failed",
                                    symbol=symbol,
                                    tf=tf,
                                    error=str(error),
                                )
                                failures.append(f"{symbol}/{tf}")
                                try:
                                    write_conn.rollback()
                                except Exception:
                                    pass
            finally:
                write_conn.close()

            elapsed_s = time.monotonic() - t0
            REGIME_WRITER_RUN_LATENCY_SECONDS.record(elapsed_s)

            run_span.set_attribute("total_updated", total_updated)
            run_span.set_attribute("failed_cells", len(failures))

            _logger.info(
                "regime_writer.run_complete",
                total_updated=total_updated,
                failed_cells=failures,
                elapsed_s=round(elapsed_s, 2),
            )

            if failures:
                status = _determine_run_status(total_updated, failures)
                if status == "failure":
                    _logger.error(
                        "regime_writer.total_failure",
                        failed_cells=failures,
                        note="Zero rows written despite attempted work; treating as hard failure",
                    )
                else:
                    _logger.warning(
                        "regime_writer.partial_failure",
                        failed_cells=failures,
                        note="Some cells failed; overall run still marked success since some cells completed",
                    )

    except Exception as error:
        status = "failure"
        _logger.error("regime_writer.fatal_error", error=str(error))
        raise
    finally:
        JOB_COMPLETED_TOTAL.add(1, {"job": _JOB, "status": status})
        flush_and_shutdown_metrics()
        if status == "failure":
            sys.exit(1)


if __name__ == "__main__":
    main()
