#!/usr/bin/env python3
"""Regime Writer — oneshot that populates feature_vectors.regime via causal HMM decoding.

Builds one GaussianHMM model per (symbol, tf) from market_data_ohlcv (log-returns +
ATR-proxy realized vol), decodes causally via forward-filter alpha-pass ONLY, then
batch-UPDATEs feature_vectors.regime with canonical text labels.

CORRECTNESS INVARIANTS:
- Observation matrix from market_data_ohlcv, NOT feature_vectors (no OHLCV columns there).
- Decoding uses forward-filter (alpha-pass only), mirroring hmm_regime.py:_forward_step().
  model.predict() is NOT used — it runs full-sequence Viterbi and leaks future information.
- Each (symbol, tf) gets its own independent HMM fit. No shared model across TFs.
- Regime labels are deterministically mapped: highest mean log-return -> trending_up,
  lowest -> trending_down, remaining -> ranging.

DAG invariant note: this oneshot is exempt from the "only writer subclasses touch DB"
rule exactly as backfill_feature_factory.py is — it is a batch labeling tool, not a
real-time daemon. The ring 2 boundary still holds: no async pipeline, no Kafka.

Usage:
    python services/regime_writer.py
    python services/regime_writer.py --symbols SPY TLT
    python services/regime_writer.py --tf 5m 15m
    python services/regime_writer.py --symbols SPY --tf 5m
"""

from __future__ import annotations

import argparse
import contextlib
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any

import numpy as np
import psycopg2
import psycopg2.extras
import structlog
from hmmlearn.hmm import GaussianHMM
from opentelemetry import trace
from sklearn.preprocessing import StandardScaler

# Set up sys.path before project imports
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from services._batch_utils import load_config_service_sync as _load_config_service_shared
from src.config.settings import Settings
from src.core.service_utils import setup_service_logging
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

# Minimum obs rows per (symbol, tf) = n_components * this factor.
# Below this, the fit is meaningless (too few state transitions to estimate A).
_MIN_OBS_FACTOR = 50

# Canonical regime label set — no other values written to DB.
_LABEL_TRENDING_UP = "trending_up"
_LABEL_TRENDING_DOWN = "trending_down"
_LABEL_RANGING = "ranging"

# Batch size for psycopg2 execute_batch UPDATE calls.
_UPDATE_BATCH_SIZE = 500


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
# Core HMM functions
# ---------------------------------------------------------------------------


def _rolling(arr: np.ndarray, window: int, fn) -> np.ndarray:
    """Apply fn over a sliding window, zero-padding the warm-up prefix."""
    windows = np.lib.stride_tricks.sliding_window_view(arr, window)
    return np.concatenate([np.zeros(window - 1), fn(windows, axis=1)])


def _build_obs_matrix(
    timestamps: list,
    closes: list[float],
    volumes: list[float],
    vol_window: int,
    momentum_window: int,
    vol_of_vol_window: int,
) -> tuple[np.ndarray, list]:
    """Build (n_valid, 5) observation matrix from OHLCV prices and volumes.

    Observation dimensions:
      [0] log_return   = ln(close[t] / close[t-1])
      [1] realized_vol = rolling std of log_returns over vol_window bars
      [2] momentum     = sum(log_returns[-momentum_window:]) / (realized_vol + eps)
                         Directional drift signal, vol-normalized.
      [3] vol_of_vol   = rolling std of realized_vol over vol_of_vol_window bars
                         Regime transition indicator: stable regimes have stable vol.
      [4] rel_volume   = log(volume[t]) - rolling mean(log(volume), vol_window)
                         Volume anomaly relative to recent baseline.

    valid_start = max(vol_window, momentum_window, vol_of_vol_window) - 1
    All rows before valid_start are discarded (insufficient window history).
    Returns (obs_matrix, valid_timestamps).
    """
    closes_arr = np.array(closes, dtype=float)
    volumes_arr = np.maximum(np.array(volumes, dtype=float), 1.0)  # guard zero volume

    log_returns = np.log(closes_arr[1:] / np.maximum(closes_arr[:-1], 1e-12))
    log_volumes = np.log(volumes_arr[1:])  # aligned to log_returns
    ts_shifted = timestamps[1:]

    if len(log_returns) < max(vol_window, momentum_window, vol_of_vol_window):
        return np.empty((0, 5), dtype=float), []

    realized_vol = _rolling(log_returns, vol_window, np.std)
    mom_raw = _rolling(log_returns, momentum_window, np.sum)
    momentum = mom_raw / np.maximum(realized_vol, 1e-8)
    vol_of_vol = _rolling(realized_vol, vol_of_vol_window, np.std)
    rolling_mean_logvol = _rolling(log_volumes, vol_window, np.mean)
    rel_volume = log_volumes - rolling_mean_logvol

    # --- discard rows before all windows are warm ---
    valid_start = max(vol_window, momentum_window, vol_of_vol_window) - 1
    if valid_start >= len(log_returns):
        return np.empty((0, 5), dtype=float), []

    obs = np.column_stack(
        [
            log_returns[valid_start:],
            realized_vol[valid_start:],
            momentum[valid_start:],
            vol_of_vol[valid_start:],
            rel_volume[valid_start:],
        ]
    )
    valid_ts = ts_shifted[valid_start:]
    return obs, valid_ts


def _causal_decode(
    obs_matrix: np.ndarray,
    means: np.ndarray,
    variances: np.ndarray,
    A: np.ndarray,
    K: int,
) -> tuple[np.ndarray, np.ndarray]:
    """Causal forward-filter (alpha-pass only) HMM decoding - vectorized.

    Precomputes log emission probabilities for all timesteps as a batch
    (n, K) matrix before the sequential alpha-pass loop, eliminating the
    K-sized Python loop that ran per timestep in the original implementation.

    The sequential t-loop is retained - causality requires alpha[t] to depend
    only on alpha[t-1]. Each loop iteration is pure numpy K-vector ops.

    Args:
        obs_matrix: (n, d) observation matrix (StandardScaler-transformed)
        means: (K, d) emission means per state (in scaled space)
        variances: (K, d) emission variances per state (in scaled space, diagonal)
        A: (K, K) transition matrix
        K: number of hidden states

    Returns:
        (states, alpha_history): states[t] = argmax(alpha[t]),
        alpha_history[t] = normalized probability vector over K states.
    """
    n, d = obs_matrix.shape
    var_clipped = np.maximum(variances[:, :d], 1e-300)  # (K, d)

    # Precompute log emission for all timesteps: shape (n, K)
    # diff[t, k, j] = obs[t, j] - means[k, j]
    diff = obs_matrix[:, np.newaxis, :] - means[np.newaxis, :, :d]  # (n, K, d)
    log_emit = (
        -0.5 * np.sum(diff**2 / var_clipped[np.newaxis, :, :], axis=2)
        - 0.5 * np.sum(np.log(2 * np.pi * var_clipped), axis=1)[np.newaxis, :]
    )  # (n, K)

    log_A = np.log(np.maximum(A, 1e-300))  # (K, K): log_A[i, j] = log P(i -> j)

    states = np.zeros(n, dtype=int)
    alpha_history = np.zeros((n, K))
    alpha = np.full(K, 1.0 / K)  # uniform prior

    for t in range(n):
        # log_alpha_prev + log_A: broadcast (K,) over (K, K)
        # log_trans[i, j] = log_alpha[i] + log_A[i, j]
        log_alpha = np.log(np.maximum(alpha, 1e-300))
        log_trans = log_alpha[:, np.newaxis] + log_A  # (K, K)
        # logsumexp over source states for each target state j
        max_lt = log_trans.max(axis=0)  # (K,)
        log_alpha_new = max_lt + np.log(np.sum(np.exp(log_trans - max_lt), axis=0))
        log_alpha_new += log_emit[t]  # add emission

        # Normalize in log space then exponentiate
        max_la = log_alpha_new.max()
        alpha = np.exp(log_alpha_new - max_la)
        total = alpha.sum()
        alpha /= total if total > 0 else 1.0

        states[t] = int(alpha.argmax())
        alpha_history[t] = alpha

    return states, alpha_history


def _build_label_map(means: np.ndarray) -> dict[int, str]:
    """Map integer HMM states to canonical regime text labels.

    Sorted deterministically by fitted emission mean[:, 0] (log-return dimension):
      - State with highest mean log-return -> "trending_up"
      - State with lowest mean log-return  -> "trending_down"
      - Remaining state(s)                 -> "ranging"

    This produces semantically stable labels regardless of which integer
    hmmlearn assigns to which state.

    Args:
        means: Shape (K, n_features) -- emission means from fitted HMM.
                Column 0 is the log-return dimension used for sorting.

    Returns:
        dict mapping integer state index -> canonical text label.
    """
    n_components = means.shape[0]
    means_ret = means[:, 0]  # log-return dimension
    order = np.argsort(means_ret)  # ascending: [most_neg, ..., most_pos]
    label_map: dict[int, str] = {}
    label_map[int(order[-1])] = _LABEL_TRENDING_UP  # highest mean return
    label_map[int(order[0])] = _LABEL_TRENDING_DOWN  # lowest mean return
    for i in range(n_components):
        if i not in label_map:
            label_map[i] = _LABEL_RANGING
    return label_map


# ---------------------------------------------------------------------------
# Per-(symbol, tf) labeling
# ---------------------------------------------------------------------------


def _label_symbol_tf(
    conn: Any,
    symbol: str,
    tf: str,
    n_components: int,
    vol_window: int,
    n_iter: int,
    hmm_random_state: int,
    momentum_window: int,
    vol_of_vol_window: int,
    tracer: Any,
) -> int:
    """Fit HMM and UPDATE feature_vectors.regime for one (symbol, tf) cell.

    Returns the number of rows updated.
    """
    with tracer.start_as_current_span(
        "regime_writer.label_symbol_tf",
        attributes={"symbol": symbol, "tf": tf},
    ) as span:
        try:
            # ------------------------------------------------------------------
            # Fetch OHLCV from market_data_ohlcv (NOT feature_vectors)
            # Use a server-side named cursor to stream large datasets without
            # loading all rows into client memory (avoids large memory spikes).
            # autocommit=True on the connection avoids implicit transaction
            # wrapping which can conflict with concurrent write activity.
            # ------------------------------------------------------------------
            timestamps = []
            closes = []
            volumes = []
            # Server-side cursor requires no active transaction — commit any
            # open transaction first.
            conn.commit()
            with conn.cursor("ohlcv_stream") as cur:
                cur.execute(
                    "SELECT timestamp, close, volume "
                    "FROM market_data_ohlcv "
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
                _logger.warning(
                    "regime_writer.no_ohlcv",
                    symbol=symbol,
                    tf=tf,
                )
                return 0

            # ------------------------------------------------------------------
            # Build observation matrix
            # ------------------------------------------------------------------
            obs_matrix, valid_ts = _build_obs_matrix(
                timestamps,
                closes,
                volumes,
                vol_window=vol_window,
                momentum_window=momentum_window,
                vol_of_vol_window=vol_of_vol_window,
            )

            min_rows = n_components * _MIN_OBS_FACTOR
            if len(valid_ts) < min_rows:
                _logger.warning(
                    "regime_writer.insufficient_obs",
                    symbol=symbol,
                    tf=tf,
                    n_obs=len(valid_ts),
                    min_required=min_rows,
                )
                return 0

            # Standardize per-series: fit on this series, transform in-place.
            # Both fit() and _causal_decode() receive the scaled matrix so
            # means/covars are in scaled space — internally consistent.
            scaler = StandardScaler()
            obs_matrix = scaler.fit_transform(obs_matrix)

            # ------------------------------------------------------------------
            # Fit HMM (parameter estimation only, NOT decoding)
            # ------------------------------------------------------------------
            model = GaussianHMM(
                n_components=n_components,
                covariance_type="diag",
                n_iter=n_iter,
                random_state=hmm_random_state,
            )
            model.fit(obs_matrix)

            # ------------------------------------------------------------------
            # Causal forward-filter decoding (NOT model.predict())
            # model.covars_ shape for 'diag': (K, d, d) with zeros off-diagonal.
            # Extract diagonal only for _causal_decode: (K, d)
            # ------------------------------------------------------------------
            d = model.means_.shape[1]
            covars_diag = model.covars_[:, np.arange(d), np.arange(d)]
            raw_states, alpha_history = _causal_decode(
                obs_matrix,
                model.means_,
                covars_diag,
                model.transmat_,
                n_components,
            )

            label_map = _build_label_map(model.means_)

            # State index lookups for alpha vector column mapping
            up_state = next(k for k, v in label_map.items() if v == _LABEL_TRENDING_UP)
            down_state = next(k for k, v in label_map.items() if v == _LABEL_TRENDING_DOWN)
            rang_state = next(k for k, v in label_map.items() if v == _LABEL_RANGING)

            # ------------------------------------------------------------------
            # Build update rows with full HMM probability vector.
            # Explicit loop (not generator) — required for index-based alpha_history
            # access and stateful duration counter simultaneously.
            # ------------------------------------------------------------------
            update_rows = []
            prev_state: int | None = None
            duration = 0
            for i, (ts, state_idx) in enumerate(zip(valid_ts, raw_states)):
                state_idx = int(state_idx)
                if state_idx == prev_state:
                    duration += 1
                else:
                    duration = 1
                    prev_state = state_idx
                alpha = alpha_history[i]
                p_up = float(alpha[up_state])  # hmm_prob_trending_up
                p_ranging = float(alpha[rang_state])
                p_down = float(alpha[down_state])
                prob_val = float(np.max(alpha))
                entropy_val = float(-np.sum(alpha * np.log(np.maximum(alpha, 1e-300))))
                update_rows.append(
                    (
                        label_map[state_idx],  # regime
                        p_up,
                        p_ranging,
                        p_down,
                        prob_val,  # hmm_regime_prob
                        entropy_val,  # hmm_entropy
                        float(duration),  # hmm_duration
                        symbol,
                        tf,
                        ts,
                    )
                )

            # ------------------------------------------------------------------
            # Batch UPDATE feature_vectors with regime + full probability vector
            # ------------------------------------------------------------------
            update_sql = (
                "UPDATE feature_vectors "
                "SET regime               = %s, "
                "    hmm_prob_trending_up  = %s, "
                "    hmm_prob_ranging      = %s, "
                "    hmm_prob_trending_down = %s, "
                "    hmm_regime_prob       = %s, "
                "    hmm_entropy           = %s, "
                "    hmm_duration          = %s "
                "WHERE symbol = %s AND tf = %s AND bar_ts = %s"
            )
            with conn.cursor() as cur:
                psycopg2.extras.execute_batch(
                    cur,
                    update_sql,
                    update_rows,
                    page_size=_UPDATE_BATCH_SIZE,
                )
            conn.commit()
            # psycopg2.extras.execute_batch rowcount is unreliable (reflects last batch only).
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
            REGIME_WRITER_ROWS_UPDATED_TOTAL.add(n_updated, {"symbol": symbol, "tf": tf})

            # ------------------------------------------------------------------
            # Record null-remaining gauge
            # ------------------------------------------------------------------

            REGIME_WRITER_NULL_REGIME_REMAINING.set(remaining, {"symbol": symbol, "tf": tf})

            _logger.info(
                "regime_writer.symbol_tf_done",
                symbol=symbol,
                tf=tf,
                n_updated=n_updated,
                null_remaining=remaining,
                converged=model.monitor_.converged,
            )

            span.set_attribute("n_updated", n_updated)
            span.set_attribute("null_remaining", remaining)
            return n_updated

        except Exception as error:
            from opentelemetry.trace import StatusCode

            span.set_status(StatusCode.ERROR, str(error))
            span.record_exception(error)
            raise


# ---------------------------------------------------------------------------
# Symbol discovery
# ---------------------------------------------------------------------------


def _discover_symbols(conn: Any) -> list[str]:
    """Return all distinct symbols present in feature_vectors."""
    with conn.cursor() as cur:
        cur.execute("SELECT DISTINCT symbol FROM feature_vectors ORDER BY symbol")
        return [r[0] for r in cur.fetchall()]


# ---------------------------------------------------------------------------
# Subprocess worker for ProcessPoolExecutor
# ---------------------------------------------------------------------------


def _run_symbol_worker(args: tuple) -> dict:
    """Worker function for ProcessPoolExecutor — runs in subprocess.

    Opens its own psycopg2 connection (connections are not picklable and
    must not be shared across processes). No OTel tracer — workers log only;
    main process aggregates results and emits metrics.

    Args:
        args: (symbol, tfs, dsn, n_components, vol_window, momentum_window,
               vol_of_vol_window, n_iter, hmm_random_state)
               Packed as a tuple for ProcessPoolExecutor.map compatibility.

    Returns:
        dict with keys: symbol, results (list of {tf, n_updated}), error (str|None)
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
    ) = args

    # Initialize logging in subprocess (each process needs its own handler)
    setup_service_logging("logs/regime_writer.log")
    worker_log = structlog.get_logger(__name__)

    conn = None
    results = []
    error_msg = None

    try:
        conn = psycopg2.connect(
            dsn,
            options="-c idle_in_transaction_session_timeout=0",
        )

        noop_tracer = _NoopTracer()

        for tf in tfs:
            try:
                n = _label_symbol_tf(
                    conn=conn,
                    symbol=symbol,
                    tf=tf,
                    n_components=n_components,
                    vol_window=vol_window,
                    momentum_window=momentum_window,
                    vol_of_vol_window=vol_of_vol_window,
                    n_iter=n_iter,
                    hmm_random_state=hmm_random_state,
                    tracer=noop_tracer,
                )
                results.append({"tf": tf, "n_updated": n})
            except Exception as error:
                worker_log.error(
                    "regime_writer.worker_cell_failed",
                    symbol=symbol,
                    tf=tf,
                    error=str(error),
                )
                results.append({"tf": tf, "n_updated": 0, "error": str(error)})
                try:
                    conn.rollback()
                except Exception:
                    # Connection is dead (e.g. server OOM). Attempt to reopen so
                    # remaining TFs for this symbol can proceed rather than failing
                    # with InFailedSqlTransaction.
                    try:
                        conn.close()
                    except Exception:
                        pass
                    try:
                        conn = psycopg2.connect(
                            dsn,
                            options="-c idle_in_transaction_session_timeout=0",
                        )
                        worker_log.warning(
                            "regime_writer.worker_reconnected",
                            symbol=symbol,
                            tf=tf,
                        )
                    except Exception as reconnect_error:
                        worker_log.error(
                            "regime_writer.worker_reconnect_failed",
                            symbol=symbol,
                            error=str(reconnect_error),
                        )
                        # Cannot recover; remaining TFs for this symbol will fail.
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

    tracer = trace.get_tracer("indicagent")
    t0 = time.monotonic()
    status = "success"

    try:
        settings = Settings()
        dsn = settings.database_url

        with tracer.start_as_current_span("regime_writer.run") as run_span:
            # Open a short-lived connection for APR load + symbol discovery, then close it.
            # Workers open their own connections — nothing is shared across processes.
            _conn = psycopg2.connect(
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

                symbols = args.symbols if args.symbols else _discover_symbols(_conn)
                tfs: list[str] = args.tf

                n_workers = args.workers
                if n_workers is None:
                    n_workers = int(cfg.get_sync("infra.regime_writer.workers", 1))
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
                )
                for symbol in symbols
            ]

            total_updated = 0
            failures: list[str] = []

            with ProcessPoolExecutor(max_workers=n_workers) as pool:
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
                        n = cell.get("n_updated", 0)
                        total_updated += n
                        tf = cell["tf"]
                        REGIME_WRITER_ROWS_UPDATED_TOTAL.add(n, {"symbol": symbol, "tf": tf})
                        if "error" in cell:
                            failures.append(f"{symbol}/{tf}")

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
                _logger.warning(
                    "regime_writer.partial_failure",
                    failed_cells=failures,
                    note="Some cells failed; overall run still marked success if >0 cells completed",
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
