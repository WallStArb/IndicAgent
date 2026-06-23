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
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np
import psycopg2
import psycopg2.extras
import structlog
from hmmlearn.hmm import GaussianHMM
from opentelemetry import trace

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


# ---------------------------------------------------------------------------
# Core HMM functions
# ---------------------------------------------------------------------------


def _build_obs_matrix(
    timestamps: list,
    closes: list[float],
    vol_window: int,
) -> tuple[np.ndarray, list]:
    """Build (n_valid, 2) observation matrix from OHLCV close prices.

    Observation dimensions:
      [0] log_return  = ln(close[t] / close[t-1])
      [1] realized_vol = rolling std of log_returns over vol_window bars

    The first vol_window rows are discarded because realized_vol is undefined
    (insufficient history). Returns aligned (obs_matrix, valid_timestamps).
    """
    closes_arr = np.array(closes, dtype=float)
    n = len(closes_arr)

    # Log returns: length n-1 (index 0 = return at bar 1 relative to bar 0)
    log_returns = np.log(closes_arr[1:] / np.maximum(closes_arr[:-1], 1e-12))

    # Aligned timestamps (skip first bar which has no return)
    ts_shifted = timestamps[1:]

    # Realized vol: rolling std over vol_window bars of log returns.
    # sliding_window_view gives full-size windows from index vol_window-1 onwards.
    if len(log_returns) >= vol_window:
        windows = np.lib.stride_tricks.sliding_window_view(log_returns, vol_window)
        realized_vol = np.concatenate([np.zeros(vol_window - 1), np.std(windows, axis=1)])
    else:
        realized_vol = np.zeros(len(log_returns))

    # Discard first vol_window rows where vol is unreliable
    valid_start = vol_window - 1
    if valid_start >= len(log_returns):
        return np.empty((0, 2), dtype=float), []

    obs = np.column_stack([log_returns[valid_start:], realized_vol[valid_start:]])
    valid_ts = ts_shifted[valid_start:]
    return obs, valid_ts


def _causal_decode(
    obs_matrix: np.ndarray,
    means: np.ndarray,
    variances: np.ndarray,
    A: np.ndarray,
    K: int,
) -> np.ndarray:
    """Causal forward-filter (alpha-pass only) HMM decoding.

    At each timestep t, the decoded state = argmax(alpha[t]) where alpha[t]
    depends ONLY on observations obs[0..t] and the prior alpha[t-1].
    No backward pass, no smoothing, no Viterbi over the full sequence.

    Mirrors src/intelligence/features/smc_context/hmm_regime.py:_forward_step()
    for batch-mode use. Do NOT replace with model.predict().

    Args:
        obs_matrix: (n, d) observation matrix
        means: (K, d) emission means per state
        variances: (K, d) emission variances per state (diagonal covariance)
        A: (K, K) transition matrix
        K: number of hidden states

    Returns:
        (states, alpha_history) where states[t] = argmax(alpha[t]) and
        alpha_history[t] is the normalized probability vector over K states.
    """
    n, d = obs_matrix.shape
    states = np.zeros(n, dtype=int)
    alpha_history = np.zeros((n, K))
    # Uniform prior — mirrors _make_initial_state in hmm_regime.py
    alpha = np.full(K, 1.0 / K)

    for t in range(n):
        obs = obs_matrix[t]
        # Emission log-probabilities (diagonal Gaussian)
        log_emit = np.zeros(K)
        for k in range(K):
            diff = obs - means[k, :d]
            var = variances[k, :d]
            log_emit[k] = -0.5 * np.sum(diff**2 / np.maximum(var, 1e-300)) - 0.5 * np.sum(
                np.log(2 * np.pi * np.maximum(var, 1e-300))
            )

        # Forward update in log space (mirrors _forward_step in hmm_regime.py)
        log_alpha = np.log(np.maximum(alpha, 1e-300))
        log_alpha_new = np.zeros(K)
        for k in range(K):
            log_trans = log_alpha + np.log(np.maximum(A[:, k], 1e-300))
            max_lt = np.max(log_trans)
            log_alpha_new[k] = max_lt + np.log(np.sum(np.exp(log_trans - max_lt)))
        log_alpha_new += log_emit

        # Normalize
        max_la = np.max(log_alpha_new)
        alpha = np.exp(log_alpha_new - max_la)
        total = np.sum(alpha)
        alpha /= total if total > 0 else 1.0

        states[t] = int(np.argmax(alpha))
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
            # Server-side cursor requires no active transaction — commit any
            # open transaction first.
            conn.commit()
            with conn.cursor("ohlcv_stream") as cur:
                cur.execute(
                    "SELECT timestamp, close "
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
            obs_matrix, valid_ts = _build_obs_matrix(timestamps, closes, vol_window)

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
            # model.covars_ shape for 'diag': (K, n_features) — already variances
            # ------------------------------------------------------------------
            raw_states, alpha_history = _causal_decode(
                obs_matrix,
                model.means_,
                model.covars_,
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
            conn = psycopg2.connect(
                dsn,
                # Disable idle-in-transaction timeout for this long-running batch
                # session. The default (30s) kills server-side cursors during HMM
                # computation which keeps connections open while processing rows.
                options="-c idle_in_transaction_session_timeout=0",
            )
            try:
                # Load APR config
                cfg = _load_config_service_shared(conn)
                n_components = int(cfg.get_sync("feature.hmm.n_components", 3))
                vol_window = int(cfg.get_sync("feature.hmm.vol_window", 20))
                n_iter = int(cfg.get_sync("feature.hmm.n_iter", 100))
                hmm_random_state = int(cfg.get_sync("alpha.hmm.random_state", 42))

                # Resolve symbols
                symbols = args.symbols if args.symbols else _discover_symbols(conn)
                tfs: list[str] = args.tf

                _logger.info(
                    "regime_writer.starting",
                    symbols_count=len(symbols),
                    tfs=tfs,
                    n_components=n_components,
                    vol_window=vol_window,
                    n_iter=n_iter,
                )

                total_updated = 0
                failures: list[str] = []

                for symbol in symbols:
                    for tf in tfs:
                        try:
                            n = _label_symbol_tf(
                                conn=conn,
                                symbol=symbol,
                                tf=tf,
                                n_components=n_components,
                                vol_window=vol_window,
                                n_iter=n_iter,
                                hmm_random_state=hmm_random_state,
                                tracer=tracer,
                            )
                            total_updated += n
                        except Exception as error:
                            cell = f"{symbol}/{tf}"
                            _logger.error(
                                "regime_writer.cell_failed",
                                cell=cell,
                                error=str(error),
                            )
                            failures.append(cell)
                            # Attempt rollback; if connection is broken, reopen it so
                            # subsequent cells can proceed (handles server OOM kills).
                            try:
                                conn.rollback()
                            except Exception:
                                _logger.warning(
                                    "regime_writer.reconnecting",
                                    cell=cell,
                                    note="Connection lost; reopening for remaining cells",
                                )
                                try:
                                    conn.close()
                                except Exception:
                                    pass
                                conn = psycopg2.connect(
                                    dsn,
                                    options="-c idle_in_transaction_session_timeout=0",
                                )
                            # continue to next cell — do not abort the whole run
                            continue

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

            finally:
                conn.close()

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
