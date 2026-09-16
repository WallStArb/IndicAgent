#!/usr/bin/env python3
"""
infrastructure_nightly_backfill.py — nightly incremental OHLCV backfill

Picks the N stalest active instruments and delegates to
infrastructure_run_historical_pipeline.py to catch them up, one bounded batch per
night, instead of one large multi-day foreground sprint. Gap detection stays
entirely in the delegate script (detect_gaps) -- this wrapper only ranks
candidates and dispatches; it never decides what data is actually missing.

Batch size is APR-governed (infra.ibkr.nightly_backfill_batch_size, migration 304) so
it can be tuned without a code change.

Bug fixed 2026-09-16: this originally ranked candidates by 1h row count and hard-filtered
to `WHERE row_count < completeness_threshold` (150,000) -- a symbol's total row count only
grows, so any symbol that ever crossed that threshold became PERMANENTLY invisible to this
job, forever, no matter how stale its most recent bar got. Verified live that 168 of 273
active instruments -- the entire mature single-name/ETF book, everything ic_engine trains
on -- had silently stopped receiving any update the moment they individually crossed
150,000 1h rows, the bulk of them frozen since 2026-08-10 while the systemd service logged
`status=success` every single night (the ~20-40 still-incomplete symbols below the
threshold kept it busy and green). Fixed by ranking on the actual staleness signal
(MAX(timestamp) ascending) instead of a proxy (row count) with a hard cutoff -- every active
symbol is a candidate every night, batch_size just caps how many of the stalest get worked
in one run. A symbol that's already current today naturally sorts last and won't be picked
while staler symbols exist; the delegate's own detect_gaps() no-ops instantly on anything
truly already covered, so there's no cost to leaving fully-current symbols eligible.

Ranking heuristic note: _select_next_batch's MAX(timestamp) is still a proxy, not the
delegate's own more accurate _reorder_contracts_by_gap() (which nets each symbol's shortfall
against its own proven-depth ceiling and can find gaps earlier in a symbol's history even
when its most recent bar is current). Reusing that logic directly was considered and
deliberately deferred -- it isn't currently exposed as an importable, gaps-returning
function, and refactoring it for reuse is out of scope for this change. Tracked as follow-up
in todo 274's spirit; file a dedicated todo before scaling this heuristic further. Harmless
in the meantime: whatever this picks, the delegate's detect_gaps() is the real correctness
check and no-ops instantly on anything already covered.
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


def _select_next_batch(conn: psycopg.Connection, batch_size: int) -> list[str]:
    """Return up to `batch_size` active symbols, staliest `_RANKING_TF` bar first.

    No hard exclusion filter: every active symbol is a candidate every night, ranked
    by how old its most recent bar is (NULLs -- never backfilled at all -- sort first
    via the epoch fallback). A symbol already current today naturally sorts last and
    loses out to staler ones within the batch_size cap; it costs nothing to leave it
    eligible since the delegate script's detect_gaps() no-ops instantly when there's
    truly nothing to fetch. This replaces a prior row-count-below-a-fixed-threshold
    design that had a severe hidden bug: a symbol's row count only grows, so once it
    crossed the threshold it became permanently invisible to this job regardless of
    staleness (see module docstring, bug fixed 2026-09-16).
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT i.symbol
            FROM instruments i
            LEFT JOIN (
                SELECT symbol, MAX(timestamp) AS latest_bar
                FROM market_data_ohlcv
                WHERE timeframe = %s
                GROUP BY symbol
            ) latest ON latest.symbol = i.symbol
            WHERE i.is_active = true
            ORDER BY COALESCE(latest.latest_bar, '1970-01-01'::timestamptz) ASC, i.symbol ASC
            LIMIT %s
            """,
            (_RANKING_TF, batch_size),
        )
        return [row[0] for row in cur.fetchall()]


def _load_config(conn: psycopg.Connection) -> int:
    """Read the nightly-backfill batch-size APR value directly off config_state.

    Deliberately bypasses ConfigService (which requires its own asyncpg pool) -- this
    oneshot script already holds a synchronous psycopg connection for the ranking query,
    and spinning up a second connection stack (min_size=2/max_size=10) just to read one
    scalar isn't worth it here. Falls back to the module default if the migration 304
    row isn't present yet.
    """
    with conn.cursor() as cur:
        cur.execute(
            "SELECT config_value FROM config_state WHERE config_key = %s",
            ("infra.ibkr.nightly_backfill_batch_size",),
        )
        row = cur.fetchone()
    return int(row[0]) if row else _DEFAULT_BATCH_SIZE


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
        batch_size = _load_config(conn)
        symbols = _select_next_batch(conn, batch_size)
    finally:
        conn.close()

    if not symbols:
        return _finish(
            "nothing_to_do",
            "No active instruments found -- nothing to do tonight.",
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
