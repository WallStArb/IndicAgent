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
import sys
import time
from itertools import repeat
from pathlib import Path
from typing import Any, NamedTuple

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
    _TREND_VOCAB as _TREND_VOCAB,
)
from src.intelligence.features.kernels._hmm import (
    _VOLATILITY_VOCAB as _VOLATILITY_VOCAB,
)
from src.intelligence.features.kernels._hmm import (
    DEFAULT_ROLLING_BLOCK_ROWS,
    EVENT_SEGMENT_SKIPPED,
    FAMILY_SPECS,
    STATUS_WRITTEN,
    HmmConfig,
    RegimeFamilySpec,
    load_rolling_block_rows,
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
from src.intelligence.features.kernels.regime import compute_regime_columns
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


_SPEC_BY_COLUMN = {spec.regime_column: spec for spec in FAMILY_SPECS.values()}

# The only feature_vectors columns _discover_symbols is ever allowed to query against: the
# families' own label columns. label_column is internally sourced (from --regime-column, itself
# argparse `choices`-constrained) so this is defense-in-depth, not a real external injection
# surface -- but validating against this frozenset before interpolation makes that true
# structurally rather than by inspection (T-172-04-SQL).
_DISCOVERY_LABEL_COLUMNS = frozenset(_SPEC_BY_COLUMN)


def _staging_table(spec: RegimeFamilySpec) -> str:
    """Temp table `bulk_update_by_key` stages one family's rows in."""
    return f"_{spec.regime_column}_writer_staging"


def _span_name(spec: RegimeFamilySpec) -> str:
    return f"regime_writer.write_{spec.event_prefix}symbol_tf"


def _fetch_bars(conn: Any, symbol: str, tf: str, with_volume: bool = True) -> dict[str, Any] | None:
    """Timestamps, closes and (with `with_volume`) volumes of one (symbol, tf) series from
    `market_data_ohlcv_tradeable`, or None (logging `regime_writer.no_ohlcv`) when there are none.

    The volatility family never reads volume, so its runs do not fetch it (`volume` is None).
    Server-side cursors require no active transaction, so any open one is committed first.
    """
    timestamps: list = []
    closes: list = []
    volumes: list = []
    columns = "timestamp, close, volume" if with_volume else "timestamp, close"
    conn.commit()
    with conn.cursor("ohlcv_stream") as cur:
        cur.execute(
            f"SELECT {columns} "
            "FROM market_data_ohlcv_tradeable "
            "WHERE symbol = %s AND timeframe = %s "
            "ORDER BY timestamp ASC",
            (symbol, tf),
        )
        while True:
            batch = cur.fetchmany(10000)
            if not batch:
                break
            by_column = list(zip(*batch, strict=True))
            timestamps.extend(by_column[0])
            closes.extend(by_column[1])
            if with_volume:
                volumes.extend(by_column[2])
    if not timestamps:
        _logger.warning("regime_writer.no_ohlcv", symbol=symbol, tf=tf)
        return None
    return {
        "timestamps": timestamps,
        "close": np.array(closes, dtype=float),
        "volume": np.array(volumes, dtype=float) if with_volume else None,
    }


def _log_events(events: Any, spec: RegimeFamilySpec, symbol: str, tf: str) -> None:
    """Log the kernel's fit and skip events with the cell's symbol and tf, under the names
    triage greps for: `regime_writer.walk_forward_hmm_convergence_iters` (info) and
    `regime_writer.<family prefix>walk_forward_segment_skipped` (warning)."""
    for event in events:
        if event.kind == EVENT_SEGMENT_SKIPPED:
            _logger.warning(
                f"regime_writer.{spec.event_prefix}{event.kind}",
                symbol=symbol,
                tf=tf,
                **event.fields,
            )
        else:
            _logger.info(f"regime_writer.{event.kind}", symbol=symbol, tf=tf, **event.fields)


def _compute_family_rows(
    bars: dict[str, Any],
    spec: RegimeFamilySpec,
    params: HmmConfig,
    tf: str,
    symbol: str,
    block_rows: int = DEFAULT_ROLLING_BLOCK_ROWS,
) -> list[tuple] | None:
    """Run one family's walk-forward kernel over `bars` and build the UPDATE rows.

    Each row is (label, the 7 numeric columns in owned-column order, symbol, tf, timestamp),
    the order `bulk_update_by_key` needs. Bars the kernel did not write (before the first model,
    or in a degenerate or non-converged segment) are absent, so a fresh `feature_vectors` row
    stays NULL rather than carrying a fabricated value. Returns None when no bar was written,
    logging why from the segment status (`insufficient_obs`: no model was fit; otherwise
    `all_segments_degenerate`; the per-segment skips are logged by the kernel).

    `params` is the loaded `HmmConfig`; `block_rows` is `infra.hmm.rolling_block_rows`. The
    columns come from `compute_regime_columns`, the entry the rebuild shares.
    """
    columns, events = compute_regime_columns(
        bars["close"], bars.get("volume"), params, tf, spec, block_rows
    )
    _log_events(events, spec, symbol, tf)
    status = columns[spec.status_output]
    written = np.flatnonzero(status == STATUS_WRITTEN)
    if len(written) == 0:
        event = "insufficient_obs" if not status.any() else "all_segments_degenerate"
        _logger.warning(
            f"regime_writer.{spec.event_prefix}walk_forward_{event}",
            symbol=symbol,
            tf=tf,
            n_obs=len(status),
        )
        return None
    written_rows = written.tolist()
    timestamps = bars["timestamps"]
    return list(
        zip(
            columns[spec.regime_column][written].tolist(),
            *(columns[name][written].tolist() for name in spec.numeric_outputs),
            repeat(symbol),
            repeat(tf),
            [timestamps[i] for i in written_rows],
            strict=False,
        )
    )


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


def _write_family_results(
    conn: Any,
    spec: RegimeFamilySpec,
    symbol: str,
    tf: str,
    update_rows: list[tuple],
    tracer: Any,
) -> int:
    """Write one family's labels for one (symbol, tf) cell to feature_vectors and return the
    number of rows updated (the JOIN-UPDATE's rowcount; no follow-up count query).

    Runs in the main process — single serial write connection, no concurrency. The row order
    is (*owned_columns, symbol, tf, bar_ts), as `bulk_update_by_key` requires. The owned-column
    tuples come from feature_vector_persistence.py (Ring 1), the one source of truth this
    module and that module's --refresh exclusion both derive from.
    """
    with tracer.start_as_current_span(
        _span_name(spec), attributes={"symbol": symbol, "tf": tf}
    ) as span:
        try:
            n_updated = _bulk_update_by_key(
                conn,
                table="feature_vectors",
                temp_table=_staging_table(spec),
                key_cols=["symbol", "tf", "bar_ts"],
                set_cols=list(spec.owned_columns),
                col_types=_regime_family_col_types(spec.owned_columns),
                rows=update_rows,
            )
            conn.commit()
            span.set_attribute("n_updated", n_updated)
            _logger.info(
                f"regime_writer.{spec.event_prefix}symbol_tf_done",
                symbol=symbol,
                tf=tf,
                n_updated=n_updated,
            )
            return n_updated

        except Exception as error:
            from opentelemetry.trace import StatusCode

            span.set_status(StatusCode.ERROR, str(error))
            span.record_exception(error)
            raise


def _record_null_remaining(
    conn: Any, spec: RegimeFamilySpec, symbols: list[str], tfs: list[str]
) -> None:
    """One grouped query at the end of a run: NULL labels left per (symbol, tf) of the
    timeframes the run covered, set on the `REGIME_WRITER_NULL_REGIME_REMAINING` gauge with
    `regime_column` so the two families are separate series. Replaces the per-cell count(*) each
    write used to issue. The `tf` filter keeps the count off the compressed chunks of the
    timeframes this run did not touch."""
    with conn.cursor() as cur:
        # regime_column comes from the family table (`FAMILY_SPECS`), never external input.
        cur.execute(
            f"SELECT symbol, tf, count(*) FILTER (WHERE {spec.regime_column} IS NULL) "
            "FROM feature_vectors WHERE symbol = ANY(%s) AND tf = ANY(%s) GROUP BY symbol, tf",
            (symbols, tfs),
        )
        rows = cur.fetchall()
    conn.commit()
    for symbol, tf, remaining in rows:
        REGIME_WRITER_NULL_REGIME_REMAINING.set(
            int(remaining), {"symbol": symbol, "tf": tf, "regime_column": spec.regime_column}
        )


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


class _WorkerArgs(NamedTuple):
    """What crosses the ProcessPoolExecutor boundary, by field name.

    `params` carries every APR value the kernels read (`HmmConfig.from_values`), loaded once
    in main(): both families and every timeframe's schedule are in it, so a worker needs no
    per-family parameter plumbing. `block_rows` is `infra.hmm.rolling_block_rows`.
    """

    symbol: str
    tfs: list[str]
    dsn: str
    regime_column: str
    params: HmmConfig
    block_rows: int


def _run_symbol_worker(args: _WorkerArgs) -> dict:
    """Worker function for ProcessPoolExecutor — runs in subprocess.

    Opens its own psycopg connection for OHLCV reads only. Runs the walk-forward kernel for
    `args.regime_column`'s family and returns update_rows to the main process; never writes to
    the DB (workers are compute-only: concurrent writers on one hypertable deadlock).

    Returns:
        dict with keys:
          symbol: str
          results: list of {tf, update_rows} (update_rows None when nothing was written) or
                   {tf, error}
          error: str | None  (set if connection itself failed)
    """
    symbol, tfs, dsn, regime_column, params, block_rows = args
    spec = _SPEC_BY_COLUMN[regime_column]

    setup_service_logging("logs/regime_writer.log")
    worker_log = structlog.get_logger(__name__)

    conn = None
    results: list[dict[str, Any]] = []
    error_msg = None

    try:
        conn = psycopg.connect(dsn, options="-c idle_in_transaction_session_timeout=0")

        for tf in tfs:
            try:
                bars = _fetch_bars(conn, symbol, tf, with_volume=spec.needs_volume)
                update_rows = (
                    None
                    if bars is None
                    else _compute_family_rows(bars, spec, params, tf, symbol, block_rows)
                )
                results.append({"tf": tf, "update_rows": update_rows})
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
    """Run the regime labeler across all (symbol, tf) cells."""
    parser = argparse.ArgumentParser(
        description="Populate feature_vectors.regime / regime_volatility via walk-forward HMM"
    )
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
        choices=sorted(_SPEC_BY_COLUMN),
        default="regime",
        help=(
            "Which column family this invocation writes. One invocation writes "
            "exactly one family -- the two are deliberately not computed together "
            "(default: regime)."
        ),
    )
    args = parser.parse_args()
    spec = _SPEC_BY_COLUMN[args.regime_column]

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
                # Every APR value both families and every timeframe's schedule read, from the
                # same keys and fallbacks the kernels' golden was captured under.
                params = HmmConfig.from_values(cfg.get_sync)
                block_rows = load_rolling_block_rows(cfg.get_sync)
                n_components, covariance_type = spec.model_fields(params)

                symbols = (
                    args.symbols
                    if args.symbols
                    else _discover_symbols(_conn, label_column=spec.regime_column)
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
                covariance_type=covariance_type,
                n_iter=params.hmm_n_iter,
                n_workers=n_workers,
                min_hold_bars=params.hmm_min_hold_bars,
                min_state_occupation=params.hmm_min_state_occupation,
                churn_window=params.hmm_churn_window,
                rolling_block_rows=block_rows,
                regime_column=spec.regime_column,
            )

            worker_args = [
                _WorkerArgs(symbol, tfs, dsn, spec.regime_column, params, block_rows)
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
                                n = _write_family_results(
                                    conn=write_conn,
                                    spec=spec,
                                    symbol=symbol,
                                    tf=tf,
                                    update_rows=cell["update_rows"],
                                    tracer=tracer,
                                )
                                total_updated += n
                                REGIME_WRITER_ROWS_UPDATED_TOTAL.add(
                                    n,
                                    {
                                        "symbol": symbol,
                                        "tf": tf,
                                        "regime_column": spec.regime_column,
                                    },
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
                try:
                    _record_null_remaining(write_conn, spec, symbols, tfs)
                except Exception as error:
                    _logger.error("regime_writer.null_remaining_failed", error=str(error))
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
