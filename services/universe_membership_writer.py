"""UniverseMembershipWriter: the one writer of `universe_membership` and its build ledger.

Stage 2 universe (todo 609, preregistration 2026-11-13). Oneshot batch. Reads the canonical 1d
bars (`market_data_ohlcv_tradeable`, restricted to days a live `ticker_event` span places on the
symbol, so a reused ticker is two securities and an unplaced span is never a member) and the
captured Massive point-in-time ticker snapshots (`reference_raw_current`, endpoint
`pit_snapshots`, one per NYSE month-end), applies the pure rule of
`src.intelligence.universe_membership` per security, and appends the member rows and one ledger
row per month-end in a single transaction.

Inputs are pinned by `--through DAY`: every NYSE month-end up to and including DAY that is not
yet in the ledger is built, in order, from bars strictly before DAY + 1. A resumed build seeds
its hysteresis state from the last built month and refuses to extend a build made under another
rule id. A month-end with no snapshot, or an empty month after the first member, fails the run loudly; nothing is
written. A run without `--apply` does everything and rolls the transaction back.

    .venv/bin/python -m services.universe_membership_writer --through 2026-10-30            # rehearsal
    .venv/bin/python -m services.universe_membership_writer --through 2026-10-30 --apply

Not to be run on real data before the step 7 data gate passes and the stage 2 load (preregistration
gate 3) is done.
"""

from __future__ import annotations

import argparse
import asyncio
from collections import Counter, defaultdict
from collections.abc import Sequence
from datetime import UTC, date, datetime, time, timedelta
from typing import Any

import asyncpg
import numpy as np

from src.config.settings import Settings
from src.core.agent.base_batch import BaseBatch
from src.intelligence.bars.sessions import nyse_sessions
from src.intelligence.universe_membership import (
    ARCHIVE_START,
    RULE,
    RULE_ID,
    MembershipRow,
    SecurityHistory,
    memberships_for_security,
    month_end_sessions,
)
from src.observability.otel import OTelInitError, init_otel_providers

_JOB = "universe-membership-writer"
_LOCK_KEY = 5970001  # advisory lock: one run at a time (the table's one writer)
_SYMBOL_CHUNK = 500  # symbols per bar read; membership of one symbol never depends on another

_PLACED_SYMBOLS_SQL = """
SELECT DISTINCT symbol FROM ticker_event WHERE vendor = 'massive' AND retired_at IS NULL
ORDER BY symbol
"""
_LEDGER_SQL = "SELECT as_of, rule_id FROM universe_membership_build ORDER BY as_of"
_MEMBERS_AT_SQL = "SELECT symbol FROM universe_membership WHERE as_of = $1"
_SNAPSHOT_PRESENT_SQL = """
SELECT count(*) FROM reference_raw_current
 WHERE vendor = 'massive' AND endpoint = 'pit_snapshots' AND as_of = $1 AND http_status = 200
"""
# The type of each placed symbol on the month-end: the snapshot row of the ticker the symbol's
# live span places on that day. `@active` answers sort before `@inactive` so they win a conflict.
_TYPES_SQL = """
SELECT te.symbol, x->>'type' AS security_type
  FROM reference_raw_current r
 CROSS JOIN LATERAL jsonb_array_elements(
        CASE WHEN jsonb_typeof(r.body->'results') = 'array' THEN r.body->'results' ELSE '[]'::jsonb END
      ) AS x
  JOIN ticker_event te
    ON te.vendor = 'massive' AND te.ticker = x->>'ticker' AND te.retired_at IS NULL
   AND te.valid_from <= r.as_of AND (te.valid_to IS NULL OR r.as_of < te.valid_to)
 WHERE r.vendor = 'massive' AND r.endpoint = 'pit_snapshots' AND r.as_of = $1
   AND r.http_status = 200
 ORDER BY (r.request_key LIKE '%@active') DESC, te.symbol
"""
_BARS_SQL = """
SELECT b.symbol, (b."timestamp" AT TIME ZONE 'UTC')::date AS day, b.close, b.volume
  FROM market_data_ohlcv_tradeable b
 WHERE b.timeframe = '1d' AND b.symbol = ANY($1) AND b."timestamp" < $2
   AND EXISTS (
        SELECT 1 FROM ticker_event te
         WHERE te.vendor = 'massive' AND te.symbol = b.symbol AND te.retired_at IS NULL
           AND te.valid_from <= (b."timestamp" AT TIME ZONE 'UTC')::date
           AND (te.valid_to IS NULL
                OR (b."timestamp" AT TIME ZONE 'UTC')::date < te.valid_to))
 ORDER BY b.symbol, b."timestamp"
"""


def month_ends_through(through: date) -> list[date]:
    """Every NYSE month-end from the archive start up to and including `through`."""
    month_end = (through.replace(day=1) + timedelta(days=32)).replace(day=1) - timedelta(days=1)
    sessions = nyse_sessions(ARCHIVE_START, month_end)
    return [day for day in month_end_sessions(sessions) if day <= through]


def histories_from_records(records: Sequence[Any]) -> dict[str, SecurityHistory]:
    """Group (symbol, day, close, volume) records, ordered by symbol and day, into histories."""
    grouped: dict[str, list[tuple[date, float, float]]] = defaultdict(list)
    for symbol, day, close, volume in records:
        grouped[symbol].append((day, float(close), float(volume)))
    out: dict[str, SecurityHistory] = {}
    for symbol, bars in grouped.items():
        out[symbol] = SecurityHistory(
            symbol=symbol,
            days=np.array([b[0] for b in bars], dtype="datetime64[D]"),
            close=np.array([b[1] for b in bars], dtype=np.float64),
            volume=np.array([b[2] for b in bars], dtype=np.float64),
        )
    return out


class UniverseMembershipWriter(BaseBatch):
    """Appends the month-ends not yet in the ledger, under the preregistered rule."""

    job_name = _JOB
    compute_version = RULE_ID

    def __init__(self, db_dsn: str, through: date, apply: bool = False) -> None:
        super().__init__(db_dsn)
        self._through = through
        self._apply = apply

    async def execute(self, pool: asyncpg.Pool) -> None:
        async with pool.acquire() as conn:
            tx = conn.transaction()
            await tx.start()
            try:
                if not await conn.fetchval("SELECT pg_try_advisory_xact_lock($1)", _LOCK_KEY):
                    self.completion_status = "lock_held"
                    await tx.rollback()
                    return
                written = await self._build_and_write(conn)
            except BaseException:
                await tx.rollback()
                raise
            if self._apply and written:
                await tx.commit()
            else:
                await tx.rollback()
            if not written:
                self.completion_status = "up_to_date"

    async def _build_and_write(self, conn: asyncpg.Connection) -> bool:
        ledger = await conn.fetch(_LEDGER_SQL)
        foreign = sorted({r["rule_id"] for r in ledger} - {RULE_ID})
        if foreign:
            raise RuntimeError(f"ledger holds months built under rule {foreign}, not {RULE_ID}")
        built = [r["as_of"] for r in ledger]
        month_ends = month_ends_through(self._through)
        if built and built[-1] not in month_ends:
            raise RuntimeError(
                f"last built month {built[-1]} is not a month-end through {self._through}"
            )
        todo = [m for m in month_ends if not built or m > built[-1]]
        if not todo:
            self.logger.info("universe_membership.up_to_date", through=str(self._through))
            return False

        types = await self._types(conn, todo)
        seed = (
            {r["symbol"] for r in await conn.fetch(_MEMBERS_AT_SQL, built[-1])} if built else set()
        )
        symbols = [r["symbol"] for r in await conn.fetch(_PLACED_SYMBOLS_SQL)]
        stop = datetime.combine(self._through + timedelta(days=1), time.min, tzinfo=UTC)

        rows: list[MembershipRow] = []
        for lo in range(0, len(symbols), _SYMBOL_CHUNK):
            chunk = symbols[lo : lo + _SYMBOL_CHUNK]
            histories = histories_from_records(await conn.fetch(_BARS_SQL, chunk, stop))
            for symbol, history in histories.items():
                rows += memberships_for_security(
                    history,
                    todo,
                    {m: types[m].get(symbol) for m in todo},
                    was_member=symbol in seed,
                    rule=RULE,
                )

        counts = Counter(row.as_of for row in rows)
        # Early month-ends have under 60 sessions of history and are legitimately empty; once a
        # month has members, an empty month (or no member at all in the run) is a failed build.
        first = next((m for m in todo if counts[m]), None)
        empty = [m for m in todo if counts[m] == 0 and (first is None or m > first)]
        if first is None or empty:
            raise RuntimeError(
                f"no member at month-end(s) {[str(m) for m in (empty or todo)]}; nothing written"
            )
        await conn.executemany(
            "INSERT INTO universe_membership_build (as_of, rule_id, n_members) VALUES ($1, $2, $3)",
            [(m, RULE_ID, counts[m]) for m in todo],
        )
        await conn.copy_records_to_table(
            "universe_membership",
            columns=[
                "as_of",
                "symbol",
                "security_type",
                "median_dollar_volume",
                "close",
                "sessions",
                "entered",
            ],
            records=[
                (
                    r.as_of,
                    r.symbol,
                    r.security_type,
                    r.median_dollar_volume,
                    r.close,
                    r.sessions,
                    r.entered,
                )
                for r in rows
            ],
        )
        by_year = Counter()
        for m in todo:
            by_year[m.year] = max(by_year[m.year], counts[m])
        self.logger.info(
            "universe_membership.built",
            months=len(todo),
            rows=len(rows),
            first=str(todo[0]),
            last=str(todo[-1]),
            apply=self._apply,
            max_members_by_year=dict(sorted(by_year.items())),
        )
        return True

    @staticmethod
    async def _types(
        conn: asyncpg.Connection, month_ends: Sequence[date]
    ) -> dict[date, dict[str, str]]:
        """Type by symbol for each month-end; a month-end with no captured snapshot raises."""
        out: dict[date, dict[str, str]] = {}
        for as_of in month_ends:
            if not await conn.fetchval(_SNAPSHOT_PRESENT_SQL, as_of):
                raise RuntimeError(f"no pit_snapshots capture for month-end {as_of}")
            found: dict[str, str] = {}
            for row in await conn.fetch(_TYPES_SQL, as_of):
                if row["security_type"]:
                    found.setdefault(row["symbol"], row["security_type"])
            out[as_of] = found
        return out


def main() -> None:
    parser = argparse.ArgumentParser(description="Build universe_membership month-ends")
    parser.add_argument("--through", required=True, help="last month-end to build (YYYY-MM-DD)")
    parser.add_argument(
        "--apply", action="store_true", help="write (default: rolled-back rehearsal)"
    )
    args = parser.parse_args()
    try:
        init_otel_providers(f"indicagent-{_JOB}")
    except OTelInitError:
        pass
    db_dsn = Settings().database_url.replace("postgresql+asyncpg://", "postgresql://")
    asyncio.run(
        UniverseMembershipWriter(db_dsn, date.fromisoformat(args.through), args.apply).run()
    )


if __name__ == "__main__":
    main()
