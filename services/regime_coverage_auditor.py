#!/usr/bin/env python3
"""Regime Coverage Auditor — oneshot canary for todo 169.

Checks that every corpus symbol has AT LEAST ONE non-null feature_vectors.regime row
(per-symbol HMM label, written by regime_writer.py). A symbol with 100% NULL regime is
a silent gap: regime_writer.py can degenerate-skip a symbol for every (tf) cell forever
without anything else in the pipeline noticing (found by accident, todo 168, 7 symbols
affected for years). This canary exists so the NEXT such gap is caught immediately
instead of by accident during an unrelated investigation.

Any non-empty result is alert-worthy. Deliberately zero new infrastructure: one query,
run periodically (systemd timer or ad hoc), same pattern as the SQL in todo 169's filing.

Usage:
    python services/regime_coverage_auditor.py
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import psycopg
import structlog
from psycopg.rows import dict_row

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.config.settings import Settings
from src.core.service_utils import setup_service_logging
from src.observability.metrics import JOB_COMPLETED_TOTAL, flush_and_shutdown_metrics
from src.observability.otel import OTelInitError, init_otel_providers

setup_service_logging("logs/regime_coverage_auditor.log")

_logger = structlog.get_logger(__name__)

_JOB = "regime-coverage-auditor"

_COVERAGE_GAP_SQL = """
    SELECT symbol, count(*) AS total_rows, count(regime) AS non_null_regime_rows
    FROM feature_vectors
    GROUP BY symbol
    HAVING count(regime) = 0
    ORDER BY symbol
"""


def _connect_db(settings: Settings) -> psycopg.Connection:
    conn = psycopg.connect(
        settings.database_url, options="-c idle_in_transaction_session_timeout=0"
    )
    conn.autocommit = True
    return conn


def _fetch_coverage_gaps(cur: psycopg.Cursor) -> list[str]:
    """Pure-ish helper — exported for unit tests. Takes an open cursor, returns the
    list of symbols with zero non-null feature_vectors.regime rows."""
    cur.execute(_COVERAGE_GAP_SQL)
    return [row["symbol"] for row in cur.fetchall()]


def main() -> None:
    try:
        init_otel_providers(service_name=_JOB)
    except OTelInitError as error:
        _logger.warning("regime_coverage_auditor.otel_init_failed", error=str(error))

    t0 = time.monotonic()
    status = "success"
    exit_code = 0
    conn = None

    try:
        settings = Settings()
        conn = _connect_db(settings)
        with conn.cursor(row_factory=dict_row) as cur:
            gap_symbols = _fetch_coverage_gaps(cur)

        if gap_symbols:
            _logger.warning(
                "regime_coverage_auditor.gap_found",
                n_symbols=len(gap_symbols),
                symbols=gap_symbols,
                note="feature_vectors.regime is 100% NULL for these symbols — "
                "regime_writer.py has never produced a usable label for them. "
                "See todo 168 for the fix-direction precedent (near-miss vs true "
                "degenerate-collapse split).",
            )
            status = "gap_found"
            exit_code = 1
        else:
            _logger.info("regime_coverage_auditor.no_gap_found")

        elapsed = time.monotonic() - t0
        _logger.info(
            "regime_coverage_auditor.complete",
            elapsed_s=round(elapsed, 2),
            status=status,
        )

    except Exception as error:
        _logger.error("regime_coverage_auditor.run_failed", error=str(error))
        status = "failure"
        exit_code = 1
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass
        JOB_COMPLETED_TOTAL.add(1, {"job": _JOB, "status": status})
        flush_and_shutdown_metrics()

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
