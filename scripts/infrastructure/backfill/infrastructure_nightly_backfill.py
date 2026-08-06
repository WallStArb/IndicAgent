#!/usr/bin/env python3
"""
infrastructure_nightly_backfill.py — nightly incremental OHLCV backfill

Picks the N least-backfilled active instruments and delegates to
infrastructure_run_historical_pipeline.py to fill them in, one bounded batch per
night, instead of one large multi-day foreground sprint. Gap detection stays
entirely in the delegate script (detect_gaps) -- this wrapper only ranks
candidates and dispatches; it never decides what data is actually missing.

Batch size and the completeness threshold are APR-governed
(infra.ibkr.nightly_backfill_batch_size / infra.ibkr.nightly_backfill_completeness_threshold,
migration 304) so they can be tuned without a code change.

Ranking heuristic note: _select_next_batch uses a simple 1h-row-count proxy, not the
delegate's own more accurate _reorder_contracts_by_gap() (which nets each symbol's shortfall
against its own proven-depth ceiling, correctly distinguishing "truncated by a prior run" from
"genuinely young instrument"). Reusing that logic directly was considered and deliberately
deferred -- it isn't currently exposed as an importable, gaps-returning function, and refactoring
it for reuse is out of scope for this change. Tracked as follow-up in todo 274's spirit; file a
dedicated todo before scaling this heuristic further. Harmless in the meantime: whatever this
picks, the delegate's detect_gaps() is the real correctness check and no-ops instantly on
anything already covered.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import psycopg
import structlog

project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from scripts.infrastructure.backfill.infrastructure_run_historical_pipeline import (  # noqa: E402
    connect_db,
)
from src.config.settings import Settings  # noqa: E402
from src.core.service_utils import setup_service_logging  # noqa: E402
from src.observability.metrics import JOB_COMPLETED_TOTAL, flush_and_shutdown_metrics  # noqa: E402
from src.observability.otel import OTelInitError, init_otel_providers  # noqa: E402

_logger = structlog.get_logger(__name__)

_JOB = "nightly-backfill"
_NIGHTLY_CLIENT_ID = 45  # dedicated lane; ibkr.py auto-rotates on Error 326 collision
_RANKING_TF = "1h"  # cheap-to-count proxy for "how far along is this symbol" (see module docstring)
_DELEGATE_SCRIPT = (Path(__file__).parent / "infrastructure_run_historical_pipeline.py").resolve()

_DEFAULT_BATCH_SIZE = 20
_DEFAULT_COMPLETENESS_THRESHOLD = 150_000  # ~150k 1h rows; full 20yr target is ~182k


def _is_another_backfill_running() -> bool:
    """True if any infrastructure_run_historical_pipeline.py process is already active.

    Avoids two backfill processes contending for the same IBKR rate-limit budget and
    potentially double-fetching the same symbols -- a real risk this session already
    hit once with an unrelated one-off sprint still in flight.
    """
    result = subprocess.run(
        ["pgrep", "-f", _DELEGATE_SCRIPT.name],
        capture_output=True,
        text=True,
        check=False,
    )
    return bool(result.stdout.strip())


def _select_next_batch(
    conn: psycopg.Connection, batch_size: int, completeness_threshold: int
) -> list[str]:
    """Return up to `batch_size` active symbols with the least `_RANKING_TF` coverage.

    Ranking is a proxy, not a correctness check -- a symbol above the threshold might
    still have real gaps (e.g. genuinely shorter listed history dilutes the count), and
    one below it might already be complete for its own available history. Either case
    is harmless: the delegate script's detect_gaps() does the real gap accounting and
    no-ops instantly on anything that's actually already covered.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT i.symbol, COALESCE(cnt.rows_ranking_tf, 0) AS rows_ranking_tf
            FROM instruments i
            LEFT JOIN (
                SELECT symbol, COUNT(*) AS rows_ranking_tf
                FROM market_data_ohlcv
                WHERE timeframe = %s
                GROUP BY symbol
            ) cnt ON cnt.symbol = i.symbol
            WHERE i.is_active = true
              AND COALESCE(cnt.rows_ranking_tf, 0) < %s
            ORDER BY rows_ranking_tf ASC, i.symbol ASC
            LIMIT %s
            """,
            (_RANKING_TF, completeness_threshold, batch_size),
        )
        return [row[0] for row in cur.fetchall()]


def _load_config(conn: psycopg.Connection) -> tuple[int, int]:
    """Read the two nightly-backfill APR values directly off config_state.

    Deliberately bypasses ConfigService (which requires its own asyncpg pool) -- this
    oneshot script already holds a synchronous psycopg connection for the ranking query,
    and spinning up a second connection stack (min_size=2/max_size=10) just to read two
    scalars isn't worth it here. Falls back to the module defaults if the migration 304
    rows aren't present yet.
    """
    defaults = {
        "infra.ibkr.nightly_backfill_batch_size": _DEFAULT_BATCH_SIZE,
        "infra.ibkr.nightly_backfill_completeness_threshold": _DEFAULT_COMPLETENESS_THRESHOLD,
    }
    with conn.cursor() as cur:
        cur.execute(
            "SELECT config_key, config_value FROM config_state WHERE config_key = ANY(%s)",
            (list(defaults.keys()),),
        )
        values = dict(cur.fetchall())
    batch_size = int(
        values.get(
            "infra.ibkr.nightly_backfill_batch_size",
            defaults["infra.ibkr.nightly_backfill_batch_size"],
        )
    )
    completeness_threshold = int(
        values.get(
            "infra.ibkr.nightly_backfill_completeness_threshold",
            defaults["infra.ibkr.nightly_backfill_completeness_threshold"],
        )
    )
    return batch_size, completeness_threshold


def _finish(status: str, message: str, returncode: int = 0) -> int:
    """Log, print, emit job_completed_total, flush OTel, and return the process exit code."""
    _logger.info(f"nightly_backfill.{status}")
    print(message)
    JOB_COMPLETED_TOTAL.add(1, {"job": _JOB, "status": status})
    flush_and_shutdown_metrics()
    return returncode


def main() -> int:
    setup_service_logging("logs/infrastructure_nightly_backfill.log")
    settings = Settings()

    if _is_another_backfill_running():
        return _finish(
            "skipped_concurrent_run",
            "Another historical-backfill process is already running -- skipping tonight.",
        )

    conn = connect_db(settings)
    try:
        batch_size, completeness_threshold = _load_config(conn)
        symbols = _select_next_batch(conn, batch_size, completeness_threshold)
    finally:
        conn.close()

    if not symbols:
        return _finish(
            "nothing_to_do",
            "No active symbols below the completeness threshold -- nothing to do tonight.",
        )

    print(f"Nightly backfill: {len(symbols)} symbols -- {', '.join(symbols)}")
    _logger.info("nightly_backfill.batch_selected", symbols=symbols, batch_size=batch_size)

    result = subprocess.run(
        [
            sys.executable,
            str(_DELEGATE_SCRIPT),
            "--symbols",
            ",".join(symbols),
            "--client-id",
            str(_NIGHTLY_CLIENT_ID),
        ],
        cwd=str(project_root),
        env={**os.environ, "PYTHONPATH": str(project_root)},
    )

    status = "success" if result.returncode == 0 else "failed"
    return _finish(
        status,
        f"Nightly backfill delegate finished: returncode={result.returncode}",
        returncode=result.returncode,
    )


if __name__ == "__main__":
    try:
        init_otel_providers(_JOB)
    except OTelInitError as error:
        print(f"[warn] OTel init failed — metrics disabled: {error}")
    sys.exit(main())
