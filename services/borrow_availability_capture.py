"""BorrowAvailabilityCapture: IBKR shortability -> borrow_availability_snapshots, append-only.

Oneshot batch (todo 438). Borrow availability is live-only at IBKR: every unrecorded day is
lost for the forward span and the short-leg constraint (unified design 9.3). One row per
asked symbol per run; a nan vendor answer is stored as NULL `shortable_shares`, never
dropped (asked-but-unknown is data, unasked is absence). `shortable` is a generated column
(NULL shares -> NULL flag), so the derivation lives in exactly one place. Reruns add rows;
the run's as_of distinguishes them and readers take each symbol's latest.

The universe is `get_active_contracts(dimension="backfill")` by design and is deliberately
NOT a config parameter: the capture must survive compute-universe changes and can never be
silently narrowed by a config edit. Batch mechanics (size, pause, wait) are APR-backed
(`infra.borrow.*`, migration 549). All ib_async lives in `src/providers/ibkr.py`; this
module holds no vendor mechanics. Run outcomes ride the BaseBatch D-06 metric plus the
structured `borrow_capture.*` log lines; no second counter.

Usage:
    python -m services.borrow_availability_capture            # dry run: fetch, print, write nothing
    python -m services.borrow_availability_capture --apply     # write
    python -m services.borrow_availability_capture --limit 10  # smoke: first N symbols only
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import UTC, datetime

import asyncpg

from services._batch_utils import cfg as _cfg
from services._batch_utils import load_apr_dict_async
from src.config.settings import Settings, get_active_contracts
from src.core.agent.base_batch import BaseBatch
from src.core.service_utils import format_iso_ts
from src.providers.ibkr import BorrowSnapshot, IBKRProvider

_JOB = "borrow-availability-capture"
# Client id 46: outside the fetcher family (40-42) and the auth probe (44), so the daily
# capture never collides with the history lane or restarts the gateway (id > 50 would).
# Service identity, therefore exempt from APR.
_CAPTURE_CLIENT_ID = 46
_BORROW_APR_PATTERN = "infra.borrow.%"

_INSERT = """
    INSERT INTO borrow_availability_snapshots (symbol, as_of, vendor, shortable_shares)
    VALUES ($1, $2, $3, $4)
"""


def summarize(snapshots: list[BorrowSnapshot]) -> dict[str, int]:
    """Pure count breakdown for the log lines (unit-tested). One row per asked symbol,
    so `asked` is also the written-row count when --apply lands them."""
    answered = sum(1 for s in snapshots if s.shortable_shares is not None)
    return {
        "asked": len(snapshots),
        "answered": answered,
        "unknown": len(snapshots) - answered,
    }


class BorrowAvailabilityCapture(BaseBatch):
    job_name = _JOB
    compute_version = "v1"

    def __init__(
        self,
        db_dsn: str,
        *,
        apply: bool = False,
        limit: int | None = None,
        settings: Settings | None = None,
    ) -> None:
        super().__init__(db_dsn)
        self._apply = apply
        self._limit = limit
        self._settings = settings or Settings()

    async def execute(self, pool: asyncpg.Pool) -> None:
        universe = [i.symbol for i in get_active_contracts(self._settings, dimension="backfill")]
        if not universe:
            raise RuntimeError("borrow capture: active contract list is empty; refusing to run")
        symbols = universe[: self._limit] if self._limit is not None else universe

        # Stage 1: read the APR batch mechanics; release the connection before the
        # vendor phase so no pool connection sits idle across a long network fetch.
        async with pool.acquire() as conn:
            apr = dict(await load_apr_dict_async(conn, [_BORROW_APR_PATTERN]) or [])
            batch_size = int(_cfg(apr, "infra.borrow.batch_size", 50))
            batch_pause_s = float(_cfg(apr, "infra.borrow.batch_pause_s", 2.5))
            batch_wait_s = float(_cfg(apr, "infra.borrow.batch_wait_s", 8.0))

        # Stage 2: the vendor fetch. All ib_async mechanics live behind the provider.
        provider = IBKRProvider(
            host=self._settings.ib_host,
            port=self._settings.ib_port,
            client_id=_CAPTURE_CLIENT_ID,
            settings=self._settings,
        )
        if not await provider.connect():
            raise RuntimeError("borrow capture: gateway connect failed")
        try:
            self.logger.info(
                "borrow_capture.plan",
                symbols=len(symbols),
                batch_size=batch_size,
                batch_pause_s=batch_pause_s,
                batch_wait_s=batch_wait_s,
                apply=self._apply,
            )
            snapshots = await provider.fetch_borrow_snapshots(
                symbols,
                batch_size=batch_size,
                batch_pause_s=batch_pause_s,
                batch_wait_s=batch_wait_s,
            )
        finally:
            await provider.disconnect()

        as_of = datetime.now(UTC)
        counts = summarize(snapshots)
        self.logger.info("borrow_capture.fetched", **counts)
        if not self._apply:
            self.logger.info(
                "borrow_capture.dry_run", note="fetched snapshots discarded; rerun with --apply"
            )
            self.completion_status = "dry_run"
            return

        # Stage 3: the write. One serial connection for the whole batch (concurrent
        # writers on a hypertable deadlock index pages); rows exist per asked symbol.
        rows = [(s.symbol, as_of, "ibkr", s.shortable_shares) for s in snapshots]
        async with pool.acquire() as write_conn:
            await write_conn.executemany(_INSERT, rows)
        self.logger.info(
            "borrow_capture.written",
            rows=len(rows),
            **counts,
            as_of=format_iso_ts(as_of),
        )
        if counts["unknown"]:
            self.completion_status = "partial"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="write rows (default: dry run)")
    parser.add_argument("--limit", type=int, default=None, help="first N symbols only (smoke)")
    args = parser.parse_args()
    settings = Settings()
    capture = BorrowAvailabilityCapture(
        settings.database_url, apply=args.apply, limit=args.limit, settings=settings
    )
    asyncio.run(capture.run())


if __name__ == "__main__":
    main()
