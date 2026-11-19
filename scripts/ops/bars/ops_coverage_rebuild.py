"""Commit the ohlcv_coverage rebuild through the ledger writer's own path.

The ledger (`ohlcv_coverage`) goes stale when raw rows change outside the fetcher's delta path
(Part F deleted the IBKR raw rows and left the ibkr ledger rows at their 2026-11-10 counts). The
reconciliation audit's coverage_cache check rebuilds inside a transaction it always rolls back,
so it only reports the drift; this script is the one place the rebuild is committed.

It refuses (exit 1, writes nothing) while a ledger writer is running: the Alpaca nightly, the
Massive nightly, the derivations or the audit (`_WRITER_UNITS`), or an `ops_massive_load` process.
Those writers do not take the fetcher lock (only the audit and corpus_rerun do), and a delta that
commits after the rebuild's aggregate would be overwritten with the stale count. It then takes the
fetcher lock (fail fast, never queues), runs `rebuild_from_stored_state` under SET LOCAL ROLE
bar_derivation_writer in one transaction, and commits only with `--apply`; without it the
transaction rolls back and the drift is reported.

Exit codes: 0 done (dry run: the drift was reported), 1 a writer is running or the fetcher lock
is held.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from collections import defaultdict
from collections.abc import Sequence
from pathlib import Path
from typing import Any

project_root = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(project_root))

import psycopg  # noqa: E402
import structlog  # noqa: E402

from scripts.infrastructure.backfill._fetcher_lock import (  # noqa: E402
    FetcherLock,
    FetcherLockHeld,
)
from services.ohlcv_coverage_writer import rebuild_from_stored_state  # noqa: E402
from src.config.settings import get_settings  # noqa: E402
from src.core.service_utils import setup_service_logging  # noqa: E402

_JOB = "coverage-rebuild"
_LOG_FILE = "logs/ops_coverage_rebuild.log"
_WRITER_ROLE_SQL = "SET LOCAL ROLE bar_derivation_writer"
# The services that write the ledger without the fetcher lock, and the loader process that does.
_WRITER_UNITS = (
    "indicagent-alpaca-nightly.service",
    "indicagent-massive-nightly.service",
    "indicagent-bar-derivation-daily.service",
    "indicagent-bar-derivation-grid.service",
    "indicagent-bar-reconciliation-audit.service",
)
_WRITER_PROCESS = "ops_massive_load"
_ROWS_SQL = """
SELECT symbol, timeframe, provider, earliest_timestamp, latest_timestamp, row_count,
       last_fetch_status
FROM ohlcv_coverage
"""

log = structlog.get_logger("ops_coverage_rebuild")


def running_writers() -> list[str]:
    """The ledger writers that are running now (empty when quiet)."""
    busy = [
        unit
        for unit in _WRITER_UNITS
        if subprocess.run(
            ["systemctl", "is-active", unit], capture_output=True, text=True
        ).stdout.strip()
        in ("active", "activating", "reloading")
    ]
    pgrep = subprocess.run(["pgrep", "-f", _WRITER_PROCESS], capture_output=True, text=True)
    return busy + ([_WRITER_PROCESS] if pgrep.stdout.strip() else [])


def rebuild_ledger(
    dsn: str,
    *,
    apply: bool,
    lock_factory: Any = FetcherLock,
    connect: Any = psycopg.connect,
    rebuild: Any = rebuild_from_stored_state,
) -> dict[str, int]:
    """Ledger rows per provider that the rebuild changes (committed only when `apply`).

    Raises FetcherLockHeld, writing nothing, when another process holds the fetcher lock."""
    lock = lock_factory(dsn, holder=_JOB)
    lock.hold_or_refuse()
    try:
        conn = connect(dsn)
        try:
            with conn.cursor() as cur:
                cur.execute(_ROWS_SQL)
                before = {(r[0], r[1], r[2]): tuple(r[3:]) for r in cur.fetchall()}
                cur.execute(_WRITER_ROLE_SQL)
                rebuild(cur)
                cur.execute(_ROWS_SQL)
                after = {(r[0], r[1], r[2]): tuple(r[3:]) for r in cur.fetchall()}
            changed: dict[str, int] = defaultdict(int)
            for key in before.keys() | after.keys():
                if before.get(key) != after.get(key):
                    changed[key[2]] += 1
            if apply:
                conn.commit()
            else:
                conn.rollback()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()
    finally:
        lock.release()
    return dict(changed)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--apply", action="store_true", help="commit the rebuild (default: roll back and report)"
    )
    args = parser.parse_args(argv)
    setup_service_logging(_LOG_FILE)
    dsn = get_settings().database_url.replace("postgresql+asyncpg://", "postgresql://")
    if busy := running_writers():
        log.error("coverage_rebuild.writer_running", writers=busy)
        return 1
    try:
        changed = rebuild_ledger(dsn, apply=args.apply)
    except FetcherLockHeld as error:
        log.error("coverage_rebuild.lock_held", error=str(error))
        return 1
    log.info("coverage_rebuild.done", applied=args.apply, changed_by_provider=changed)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
