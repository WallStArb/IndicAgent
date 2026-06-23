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
import sys
import time
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

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

# Statistical-concept-defining lookaheads — these numbers define the column names
# (return_1bar/5bar/20bar/60bar) and are NOT tunable parameters. APR rules allow
# numbers in column names when they define the statistical concept.
_LOOKAHEADS: list[int] = [1, 5, 20, 60]

_DEFAULT_TFS: list[str] = ["5m", "15m", "1h", "1d"]

# Fallback only — actual value read from APR at runtime via cfg.get_sync()
_INSERT_BATCH_SIZE_DEFAULT = 500


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
# SQL
# ---------------------------------------------------------------------------

# LEAD() CTE: computes all lookahead opens in one pass per (symbol, tf).
# ROWS BETWEEN CURRENT ROW AND 61 FOLLOWING — explicit frame to avoid default
# range-frame semantics which can produce unexpected results on ties (RESEARCH.md F8).
# Only bars with timestamp <= TRAINING_WINDOW_END are included in the window.
_FORWARD_RETURN_SQL = """
WITH windowed AS (
    SELECT
        m.timestamp                            AS bar_ts,
        m.symbol,
        m.timeframe                            AS tf,
        fv.pipeline_version,
        LEAD(m.open, 1)  OVER w               AS open_t1,
        LEAD(m.open, 2)  OVER w               AS open_t2,
        LEAD(m.open, 6)  OVER w               AS open_t6,
        LEAD(m.open, 21) OVER w               AS open_t21,
        LEAD(m.open, 61) OVER w               AS open_t61
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
        ROWS BETWEEN CURRENT ROW AND 61 FOLLOWING
    )
)
SELECT
    bar_ts,
    symbol,
    tf,
    pipeline_version,
    CASE WHEN open_t1 > 0 AND open_t2  > 0 THEN ln(open_t2  / open_t1) END AS return_1bar,
    CASE WHEN open_t1 > 0 AND open_t6  > 0 THEN ln(open_t6  / open_t1) END AS return_5bar,
    CASE WHEN open_t1 > 0 AND open_t21 > 0 THEN ln(open_t21 / open_t1) END AS return_20bar,
    CASE WHEN open_t1 > 0 AND open_t61 > 0 THEN ln(open_t61 / open_t1) END AS return_60bar,
    (open_t2  IS NOT NULL) AS complete_1bar,
    (open_t6  IS NOT NULL) AS complete_5bar,
    (open_t21 IS NOT NULL) AS complete_20bar,
    (open_t61 IS NOT NULL) AS complete_60bar
FROM windowed
WHERE bar_ts > %(hwm)s
ORDER BY bar_ts
"""

_INSERT_SQL = """
INSERT INTO forward_returns (
    symbol, tf, bar_ts, pipeline_version,
    return_1bar, return_5bar, return_20bar, return_60bar,
    complete_1bar, complete_5bar, complete_20bar, complete_60bar
)
VALUES (
    %(symbol)s, %(tf)s, %(bar_ts)s, %(pipeline_version)s,
    %(return_1bar)s, %(return_5bar)s, %(return_20bar)s, %(return_60bar)s,
    %(complete_1bar)s, %(complete_5bar)s, %(complete_20bar)s, %(complete_60bar)s
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
    batch_size: int = _INSERT_BATCH_SIZE_DEFAULT,
) -> int:
    """Compute and insert forward returns for one (symbol, tf) cell.

    Returns number of rows inserted.
    """
    with observed_span(
        "forward_return_writer.label_symbol_tf", tracer, symbol=symbol, tf=tf
    ) as span:
        # High-water mark: on subsequent runs, recompute the tail window (last 61 bars
        # before the current max) so previously-incomplete rows get completeness updates
        # as future bars arrive. On first run, MAX(bar_ts) is NULL — use epoch to fetch all.
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
            # Map tf to a PostgreSQL interval for the 61-bar lookback window
            _TF_INTERVAL = {
                "5m": "305 minutes",
                "15m": "915 minutes",
                "1h": "61 hours",
                "1d": "61 days",
            }
            interval = _TF_INTERVAL.get(tf, "61 days")
            with conn.cursor() as cur:
                cur.execute("SELECT %s::timestamptz - INTERVAL %s", (max_bar_ts, interval))
                hwm = cur.fetchone()[0]

        params = {
            "symbol": symbol,
            "tf": tf,
            "training_window_end": training_window_end,
            "hwm": hwm,
        }

        with conn.cursor() as cur:
            cur.execute(_FORWARD_RETURN_SQL, params)
            rows = cur.fetchall()
            col_names = [d[0] for d in cur.description]

        if not rows:
            return 0

        insert_rows = [dict(zip(col_names, r)) for r in rows]

        with conn.cursor() as cur:
            psycopg2.extras.execute_batch(
                cur,
                _INSERT_SQL,
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


def _emit_coverage(conn: Any, symbols: list[str], tfs: list[str]) -> None:
    """Compute and emit OUTCOME_LABELS_COVERAGE per (lookahead, symbol, tf)."""
    for symbol in symbols:
        for tf in tfs:
            for n in _LOOKAHEADS:
                col = f"complete_{n}bar"
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
                            fraction, {"lookahead": str(n), "symbol": symbol, "tf": tf}
                        )
                except Exception as error:
                    _logger.warning(
                        "forward_return_writer.coverage_gauge_error",
                        symbol=symbol,
                        tf=tf,
                        lookahead=n,
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

                _emit_coverage(conn, symbols, tfs)

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
