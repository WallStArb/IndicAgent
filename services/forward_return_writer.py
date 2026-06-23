#!/usr/bin/env python3
"""Forward Return Writer — oneshot that computes executable causal forward log returns.

Reads market_data_ohlcv (OHLCV), computes forward returns via LEAD() window functions,
and inserts rows into forward_returns for every (symbol, tf) that has a matching
feature_vectors row. This is the dependent variable (Y) for IC measurement.

CORRECTNESS INVARIANTS:
- Forward return formula (IC spec §V): ln(open[T+N+1] / open[T+1]).
  Entry at T+1 open, exit at T+N+1 open. NEVER ln(close[T+N]/close[T]).
- TRAINING_WINDOW_END gate: only bars with timestamp <= MAX(bar_ts) FROM feature_vectors
  are processed. Prevents future-gap rows (bars beyond the training corpus).
- JOIN gate: only emits rows where bar_ts has a matching feature_vectors row (exact JOIN).
- Idempotent: ON CONFLICT (symbol, tf, bar_ts) DO NOTHING. Re-run inserts 0 rows.
- complete_Nbar=false for the last N bars of each (symbol, tf) series where
  open[T+N+1] is NULL (insufficient future data).

DAG invariant note: this oneshot is exempt from the "only writer subclasses touch DB"
rule exactly as backfill_feature_factory.py is — batch labeling tool, not a daemon.

Usage:
    python services/forward_return_writer.py
    python services/forward_return_writer.py --symbols SPY TLT
    python services/forward_return_writer.py --symbols SPY --tf 5m
"""

from __future__ import annotations

import argparse
import hashlib
import sys
import time
import uuid
from collections.abc import Generator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import psycopg2
import psycopg2.extras
import structlog
from opentelemetry import trace
from opentelemetry.trace import StatusCode

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from services._batch_utils import load_config_service_sync as _load_config_service
from src.config.settings import Settings
from src.core.service_utils import setup_service_logging
from src.observability.metrics import (
    FORWARD_RETURN_WRITER_ROWS_WRITTEN_TOTAL,
    FORWARD_RETURN_WRITER_RUN_LATENCY_SECONDS,
    JOB_COMPLETED_TOTAL,
    OUTCOME_LABELS_COVERAGE,
    flush_and_shutdown_metrics,
)
from src.observability.otel import OTelInitError, init_otel_providers

setup_service_logging("logs/forward_return_writer.log")

_logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_JOB = "forward-return-writer"

# Gradient scale identifiers — schema column names for forward return horizons.
# Schema holds the concept (fast/mid/slow/extended); APR holds the period in bars
# under alpha.ic.lookahead.{scale}. Loaded at runtime from APR.
_SCALES: tuple[str, ...] = ("fast", "mid", "slow", "extended")

# Fallback defaults used only when APR key is absent (pre-migration bootstrap).
_SCALE_FALLBACKS: dict[str, int] = {"fast": 1, "mid": 5, "slow": 20, "extended": 60}

_DEFAULT_TFS: list[str] = ["5m", "15m", "1h", "1d"]

# Fallback only — actual value read from APR at runtime via cfg.get_sync()
_INSERT_BATCH_SIZE_DEFAULT = 500


def _make_forward_return_id(
    symbol: str, tf: str, bar_ts: datetime, pipeline_version: str
) -> uuid.UUID:
    """SHA-256(symbol|tf|bar_ts_ns|pipeline_version)[:32] as UUID.

    Mirrors make_feature_vector_id in feature_vector_persistence.py.
    bar_ts_ns uses nanosecond epoch to avoid sub-second precision loss.
    """
    bar_ts_ns = str(int(bar_ts.timestamp() * 1_000_000_000))
    digest = hashlib.sha256(f"{symbol}|{tf}|{bar_ts_ns}|{pipeline_version}".encode()).hexdigest()[
        :32
    ]
    return uuid.UUID(digest)


# ---------------------------------------------------------------------------
# Sync span helper — matches observed_span semantics for sync psycopg2 services
# ---------------------------------------------------------------------------


@contextmanager
def observed_span(name: str, tracer: Any, **attrs: Any) -> Generator[Any]:
    """Sync context manager mirroring src/observability/spans.py:observed_span.

    Creates a span, records exceptions, sets ERROR status on raise.
    Used here because forward_return_writer is sync (psycopg2), not async.
    """
    with tracer.start_as_current_span(name, attributes=attrs) as span:
        try:
            yield span
        except Exception as error:
            span.set_status(StatusCode.ERROR, str(error))
            span.record_exception(error)
            raise


# ---------------------------------------------------------------------------
# Pure forward return helper (unit-testable, no DB)
# ---------------------------------------------------------------------------


def forward_log_return(opens: np.ndarray, n: int) -> np.ndarray:
    """Compute forward log return: ln(open[T+N+1] / open[T+1]) for each T.

    This mirrors the SQL LEAD()-based formula in _build_forward_return_sql():
      - Entry at T+1 open (next bar's open, simulating market-on-open entry)
      - Exit at T+N+1 open (N bars later, simulating market-on-open exit)

    The last n rows have no complete forward return (opens[T+N+1] is unknown)
    and are set to NaN.

    Args:
        opens: Array of length M open prices, ordered by time.
        n: Lookahead in bars (1=fast, 5=mid, 20=slow, 60=extended).

    Returns:
        Array of length M float64. Value at index T = ln(opens[T+n+1] / opens[T+1]).
        Indices where T+n+1 >= M are NaN (complete_Nbar would be False in SQL).
        Index T uses only opens at indices > T (no lookahead bias).
    """
    opens_arr = np.asarray(opens, dtype=float)
    m = len(opens_arr)
    result = np.full(m, np.nan)
    # result[T] = ln(opens[T+n+1] / opens[T+1]) for T in [0, m-n-2]
    # Requires: T+1 < m (entry) and T+n+1 < m (exit)
    # So valid T range: 0 <= T <= m - n - 2
    valid_end = m - n - 1  # last valid T (inclusive) = m - n - 2
    if valid_end > 0:
        entry_idx = np.arange(1, valid_end + 1)  # T+1
        exit_idx = np.arange(n + 1, valid_end + n + 1)  # T+n+1
        entry_prices = opens_arr[entry_idx]
        exit_prices = opens_arr[exit_idx]
        valid = (entry_prices > 0) & (exit_prices > 0)
        result[:valid_end] = np.where(valid, np.log(exit_prices / entry_prices), np.nan)
    return result


# ---------------------------------------------------------------------------
# SQL
# ---------------------------------------------------------------------------


# LEAD() CTE: computes all lookahead opens in one pass per (symbol, tf).
# ROWS BETWEEN CURRENT ROW AND 61 FOLLOWING — explicit frame to avoid default
# range-frame semantics which can produce unexpected results on ties (RESEARCH.md F8).
# Only bars with timestamp <= TRAINING_WINDOW_END are included in the window.
def _build_forward_return_sql(lookaheads: dict[str, int]) -> str:
    """Build LEAD()-based SQL using APR-backed lookahead periods.

    lookaheads maps scale name -> period in bars (e.g. {"fast": 1, "mid": 5, ...}).
    The max period + 1 determines the ROWS BETWEEN frame size.
    """
    max_n = max(lookaheads.values())
    frame_size = max_n + 1

    # Build comma-separated LEAD column list (each needs a comma separator)
    lead_col_list = [
        f"LEAD(m.open, {n + 1}) OVER w AS open_{scale}" for scale, n in lookaheads.items()
    ]
    lead_cols = ",\n        ".join(lead_col_list)
    # open_entry = LEAD(open, 1) is always needed for the entry price (T+1 open)
    lead_t1 = "LEAD(m.open, 1) OVER w AS open_entry"

    return_col_list = [
        f"CASE WHEN open_entry > 0 AND open_{scale} > 0 "
        f"THEN ln(open_{scale} / open_entry) END AS return_{scale}"
        for scale in lookaheads
    ]
    return_cols = ",\n    ".join(return_col_list)

    complete_col_list = [f"(open_{scale} IS NOT NULL) AS complete_{scale}" for scale in lookaheads]
    complete_cols = ",\n    ".join(complete_col_list)

    return f"""
WITH windowed AS (
    SELECT
        m.timestamp                            AS bar_ts,
        m.symbol,
        m.timeframe                            AS tf,
        fv.pipeline_version,
        {lead_t1},
        {lead_cols}
    FROM market_data_ohlcv m
    JOIN feature_vectors fv
        ON fv.symbol   = m.symbol
       AND fv.tf       = m.timeframe
       AND fv.bar_ts   = m.timestamp
    WHERE m.symbol    = %(symbol)s
      AND m.timeframe = %(tf)s
      AND m.timestamp <= %(training_window_end)s
    WINDOW w AS (
        PARTITION BY m.symbol, m.timeframe
        ORDER BY m.timestamp
        ROWS BETWEEN CURRENT ROW AND {frame_size} FOLLOWING
    )
)
SELECT
    bar_ts,
    symbol,
    tf,
    pipeline_version,
    {return_cols},
    {complete_cols}
FROM windowed
WHERE bar_ts > %(hwm)s
ORDER BY bar_ts
"""


def _build_insert_sql(scales: tuple[str, ...]) -> str:
    """Build INSERT SQL for gradient-named return columns."""
    return_cols = ", ".join(f"return_{s}" for s in scales)
    complete_cols = ", ".join(f"complete_{s}" for s in scales)
    return_vals = ", ".join(f"%(return_{s})s" for s in scales)
    complete_vals = ", ".join(f"%(complete_{s})s" for s in scales)
    return f"""
INSERT INTO forward_returns (
    forward_return_id, symbol, tf, bar_ts, pipeline_version,
    {return_cols},
    {complete_cols}
)
VALUES (
    %(forward_return_id)s, %(symbol)s, %(tf)s, %(bar_ts)s, %(pipeline_version)s,
    {return_vals},
    {complete_vals}
)
ON CONFLICT (symbol, tf, bar_ts) DO NOTHING
"""


# ---------------------------------------------------------------------------
# Symbol discovery
# ---------------------------------------------------------------------------


def _discover_symbols(conn: Any) -> list[str]:
    with conn.cursor() as cur:
        cur.execute("SELECT DISTINCT symbol FROM feature_vectors ORDER BY symbol")
        return [r[0] for r in cur.fetchall()]


# ---------------------------------------------------------------------------
# Per-(symbol, tf) labeling
# ---------------------------------------------------------------------------


def _label_symbol_tf(
    conn: Any,
    symbol: str,
    tf: str,
    training_window_end: Any,
    tracer: Any,
    lookaheads: dict[str, int],
    batch_size: int = _INSERT_BATCH_SIZE_DEFAULT,
) -> int:
    """Compute and insert forward returns for one (symbol, tf) cell.

    Returns number of rows inserted.
    """
    with observed_span(
        "forward_return_writer.label_symbol_tf", tracer, symbol=symbol, tf=tf
    ) as span:
        max_n = max(lookaheads.values())
        # High-water mark: on subsequent runs, recompute the tail window (last max_n+1 bars
        # before the current max) so previously-incomplete rows get completeness updates.
        # On first run, MAX(bar_ts) is NULL — use epoch to fetch all.
        with conn.cursor() as cur:
            cur.execute(
                "SELECT MAX(bar_ts) FROM forward_returns WHERE symbol = %s AND tf = %s",
                (symbol, tf),
            )
            row = cur.fetchone()
            max_bar_ts = row[0] if row else None
        if max_bar_ts is None:
            hwm = "1970-01-01T00:00:00+00:00"
        else:
            _TF_MINUTES = {"5m": 5, "15m": 15, "1h": 60, "1d": 1440}
            minutes_per_bar = _TF_MINUTES.get(tf, 1440)
            lookback_minutes = (max_n + 1) * minutes_per_bar
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT %s::timestamptz - INTERVAL %s",
                    (max_bar_ts, f"{lookback_minutes} minutes"),
                )
                hwm = cur.fetchone()[0]

        forward_return_sql = _build_forward_return_sql(lookaheads)
        insert_sql = _build_insert_sql(_SCALES)

        params = {
            "symbol": symbol,
            "tf": tf,
            "training_window_end": training_window_end,
            "hwm": hwm,
        }

        with conn.cursor() as cur:
            cur.execute(forward_return_sql, params)
            rows = cur.fetchall()
            col_names = [d[0] for d in cur.description]

        if not rows:
            return 0

        insert_rows = [dict(zip(col_names, r)) for r in rows]
        for row in insert_rows:
            row["forward_return_id"] = _make_forward_return_id(
                row["symbol"], row["tf"], row["bar_ts"], row["pipeline_version"]
            )

        with conn.cursor() as cur:
            psycopg2.extras.execute_batch(
                cur,
                insert_sql,
                insert_rows,
                page_size=batch_size,
            )
        conn.commit()

        n_inserted = len(insert_rows)
        FORWARD_RETURN_WRITER_ROWS_WRITTEN_TOTAL.add(n_inserted, {"symbol": symbol, "tf": tf})

        _logger.info(
            "forward_return_writer.symbol_tf_done",
            symbol=symbol,
            tf=tf,
            n_inserted=n_inserted,
            training_window_end=str(training_window_end),
        )
        span.set_attribute("n_inserted", n_inserted)
        return n_inserted


# ---------------------------------------------------------------------------
# Coverage gauge
# ---------------------------------------------------------------------------


def _emit_coverage(conn: Any, symbols: list[str], tfs: list[str], scales: tuple[str, ...]) -> None:
    """Compute and emit OUTCOME_LABELS_COVERAGE per (scale, symbol, tf)."""
    for symbol in symbols:
        for tf in tfs:
            for scale in scales:
                col = f"complete_{scale}"
                try:
                    with conn.cursor() as cur:
                        cur.execute(
                            f"SELECT "
                            f"  count(*) FILTER (WHERE {col}) AS complete, "
                            f"  count(*) AS total "
                            f"FROM forward_returns WHERE symbol = %s AND tf = %s",
                            (symbol, tf),
                        )
                        row = cur.fetchone()
                    if row and row[1] > 0:
                        fraction = row[0] / row[1]
                        OUTCOME_LABELS_COVERAGE.set(
                            fraction, {"lookahead_scale": scale, "symbol": symbol, "tf": tf}
                        )
                except Exception as error:
                    _logger.warning(
                        "forward_return_writer.coverage_gauge_error",
                        symbol=symbol,
                        tf=tf,
                        scale=scale,
                        error=str(error),
                    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Populate forward_returns with causal forward log returns"
    )
    parser.add_argument("--symbols", nargs="*", default=None)
    parser.add_argument("--tf", nargs="*", default=_DEFAULT_TFS)
    args = parser.parse_args()

    try:
        init_otel_providers(service_name=_JOB)
    except OTelInitError as error:
        _logger.warning("forward_return_writer.otel_init_failed", error=str(error))

    tracer = trace.get_tracer("indicagent")
    t0 = time.monotonic()
    status = "success"

    try:
        settings = Settings()
        psycopg2.extras.register_uuid()
        with observed_span("forward_return_writer.run", tracer):
            conn = psycopg2.connect(
                settings.database_url,
                options="-c idle_in_transaction_session_timeout=0",
            )
            try:
                cfg = _load_config_service(conn)
                batch_size = int(
                    cfg.get_sync("alpha.ic.insert_batch_size", _INSERT_BATCH_SIZE_DEFAULT)
                )

                # Load lookahead periods from APR (alpha.ic.lookahead.{scale})
                lookaheads = {
                    scale: int(cfg.get_sync(f"alpha.ic.lookahead.{scale}", fb))
                    for scale, fb in _SCALE_FALLBACKS.items()
                }
                _logger.info("forward_return_writer.lookaheads", lookaheads=lookaheads)

                # TRAINING_WINDOW_END gate — must be computed and logged before any SQL
                with conn.cursor() as cur:
                    cur.execute("SELECT MAX(bar_ts) FROM feature_vectors")
                    training_window_end = cur.fetchone()[0]

                if training_window_end is None:
                    _logger.error(
                        "forward_return_writer.no_feature_vectors",
                        note="feature_vectors is empty — run backfill_feature_factory first",
                    )
                    status = "failure"
                    sys.exit(1)

                _logger.info(
                    "forward_return_writer.training_window_end",
                    TRAINING_WINDOW_END=str(training_window_end),
                )

                symbols = args.symbols if args.symbols else _discover_symbols(conn)
                tfs: list[str] = args.tf

                _logger.info(
                    "forward_return_writer.starting",
                    symbols_count=len(symbols),
                    tfs=tfs,
                    TRAINING_WINDOW_END=str(training_window_end),
                )

                total_inserted = 0
                failures: list[str] = []

                for symbol in symbols:
                    for tf in tfs:
                        try:
                            n = _label_symbol_tf(
                                conn=conn,
                                symbol=symbol,
                                tf=tf,
                                training_window_end=training_window_end,
                                tracer=tracer,
                                lookaheads=lookaheads,
                                batch_size=batch_size,
                            )
                            total_inserted += n
                        except Exception as error:
                            cell = f"{symbol}/{tf}"
                            _logger.error(
                                "forward_return_writer.cell_failed",
                                cell=cell,
                                error=str(error),
                            )
                            failures.append(cell)
                            try:
                                conn.rollback()
                            except Exception:
                                try:
                                    conn.close()
                                except Exception:
                                    pass
                                conn = psycopg2.connect(
                                    settings.database_url,
                                    options="-c idle_in_transaction_session_timeout=0",
                                )

                elapsed_s = time.monotonic() - t0
                FORWARD_RETURN_WRITER_RUN_LATENCY_SECONDS.record(elapsed_s)

                _emit_coverage(conn, symbols, tfs, _SCALES)

                _logger.info(
                    "forward_return_writer.run_complete",
                    total_inserted=total_inserted,
                    failed_cells=failures,
                    elapsed_s=round(elapsed_s, 2),
                )

            finally:
                conn.close()

    except Exception as error:
        status = "failure"
        _logger.error("forward_return_writer.fatal_error", error=str(error))
        raise
    finally:
        JOB_COMPLETED_TOTAL.add(1, {"job": _JOB, "status": status})
        flush_and_shutdown_metrics()
        if status == "failure":
            sys.exit(1)


if __name__ == "__main__":
    main()
