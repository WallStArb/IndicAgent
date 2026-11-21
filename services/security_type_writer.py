"""SecurityTypeWriter: the one writer of `security_type`.

Stage 2 universe (todo 648, amendment 2026-11-21 of the preregistration). Oneshot batch. Reads every
captured Massive point-in-time ticker list (`reference_raw_current`, endpoint `pit_snapshots`, one
per month-end), counts for each security (symbol) the type labels its own ticker carried on each
list date (the ticker the symbol's live `ticker_event` span places on that date), resolves one type
per security with `src.intelligence.security_type.resolve_security_type`, and appends the typed
securities in a single transaction. A security with no label gets no row: untyped is never filled.

Deterministic: the result is a function of the snapshots and the spans, never of row order. The run
fails loudly, writing nothing, on: a list date whose capture is not complete (the same check the
membership build makes), a typed symbol with no `instruments` row, or no list at all. A second run
under the same rule id recomputes the rows and compares them with the stored ones: equal writes
nothing (`up_to_date`), different raises (the lists or spans moved after the build; a changed result
is a new `TYPE_RULE_ID` and a dated amendment, never an edit). Only lists dated up to L are read (the
last list Massive captured, `LAST_LIST_DATE`); a later one raises. A run without `--apply` does
everything and rolls the transaction back (the rehearsal).

    .venv/bin/python -m services.security_type_writer          # rehearsal
    .venv/bin/python -m services.security_type_writer --apply

Not to be applied before the owner adopts the 2026-11-21 amendment and migration 606 is applied.
"""

from __future__ import annotations

import argparse
import asyncio
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date

import asyncpg

from services.universe_membership_writer import _SNAPSHOT_PAGES_SQL, snapshot_problem
from src.config.settings import Settings
from src.core.agent.base_batch import BaseBatch
from src.intelligence.security_type import TYPE_RULE_ID, resolve_security_type
from src.intelligence.universe_membership import LAST_LIST_DATE
from src.observability.otel import OTelInitError, init_otel_providers

_JOB = "security-type-writer"
_LOCK_KEY = 6060001  # advisory lock: one run at a time (the table's one writer)
_SOURCE = "pit_snapshots"

_STORED_SQL = """
SELECT symbol, security_type, class_conflict, evidence FROM security_type
 WHERE rule_id = $1 ORDER BY symbol
"""
_LIST_DATES_SQL = """
SELECT DISTINCT as_of FROM reference_raw_current
 WHERE vendor = 'massive' AND endpoint = 'pit_snapshots' ORDER BY as_of
"""
# The labels each security carried on one list date: the list row of the ticker the symbol's live
# span places on that day. One count per (symbol, label, date) however many rows (the `@active` and
# `@inactive` lists, two tickers of one span) say it, so the counts do not depend on row multiplicity.
_LABELS_SQL = """
SELECT te.symbol, x->>'type' AS label
  FROM reference_raw_current r
 CROSS JOIN LATERAL jsonb_array_elements(
        CASE WHEN jsonb_typeof(r.body->'results') = 'array' THEN r.body->'results' ELSE '[]'::jsonb END
      ) AS x
  JOIN ticker_event te
    ON te.vendor = 'massive' AND te.ticker = x->>'ticker' AND te.retired_at IS NULL
   AND te.valid_from <= r.as_of AND (te.valid_to IS NULL OR r.as_of < te.valid_to)
 WHERE r.vendor = 'massive' AND r.endpoint = 'pit_snapshots' AND r.as_of = $1
   AND r.http_status = 200 AND x->>'type' IS NOT NULL AND x->>'type' <> ''
 GROUP BY te.symbol, x->>'type'
"""
_INSTRUMENTS_SQL = "SELECT symbol FROM instruments"
_INSERT_SQL = """
INSERT INTO security_type (symbol, rule_id, security_type, class_conflict, evidence, source)
VALUES ($1, $2, $3, $4, $5, $6)
"""


@dataclass
class _Evidence:
    """One security's labels: list dates per label and the first and last date it was typed."""

    counts: Counter[str] = field(default_factory=Counter)
    first: date | None = None
    last: date | None = None

    def add(self, label: str, as_of: date) -> None:
        self.counts[label] += 1
        self.first = as_of if self.first is None else min(self.first, as_of)
        self.last = as_of if self.last is None else max(self.last, as_of)


class SecurityTypeWriter(BaseBatch):
    """Appends one resolved type per typed security under the current type rule."""

    job_name = _JOB
    compute_version = TYPE_RULE_ID

    def __init__(self, db_dsn: str, apply: bool = False) -> None:
        super().__init__(db_dsn)
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
        evidence = await self._evidence(conn)
        known = {row["symbol"] for row in await conn.fetch(_INSTRUMENTS_SQL)}
        orphans = sorted(set(evidence) - known)
        if orphans:
            raise RuntimeError(
                f"{len(orphans)} typed symbol(s) have no instruments row, first {orphans[:10]}; "
                "nothing written"
            )
        records = []
        by_type: Counter[str] = Counter()
        conflicts = 0
        for symbol in sorted(evidence):
            seen = evidence[symbol]
            security_type, conflict = resolve_security_type(seen.counts)
            if security_type is None:  # unreachable: a label was counted to get here
                raise RuntimeError(f"{symbol} has evidence but resolves to no type")
            by_type[security_type] += 1
            conflicts += conflict
            document = {
                "labels": dict(sorted(seen.counts.items())),
                "first_list": seen.first.isoformat() if seen.first else None,
                "last_list": seen.last.isoformat() if seen.last else None,
            }
            records.append((symbol, TYPE_RULE_ID, security_type, conflict, document, _SOURCE))
        stored = await conn.fetch(_STORED_SQL, TYPE_RULE_ID)
        if stored:
            # by key, not position: the database collation need not sort like Python
            computed = {r[0]: (r[2], r[3], r[4]) for r in records}
            if computed != {
                r["symbol"]: (r["security_type"], r["class_conflict"], r["evidence"])
                for r in stored
            }:
                raise RuntimeError(
                    f"security_type under {TYPE_RULE_ID} no longer matches the lists and spans it "
                    "was built from; a changed result needs a new TYPE_RULE_ID and a dated "
                    "amendment; nothing written"
                )
            self.logger.info("security_type.up_to_date", rule_id=TYPE_RULE_ID)
            return False
        # executemany, not COPY: the binary COPY path has no encoder for the jsonb text codec
        await conn.executemany(_INSERT_SQL, records)
        self.logger.info(
            "security_type.built",
            rule_id=TYPE_RULE_ID,
            securities=len(records),
            class_conflicts=conflicts,
            by_type=dict(by_type.most_common()),
            apply=self._apply,
        )
        return True

    async def _evidence(self, conn: asyncpg.Connection) -> dict[str, _Evidence]:
        """Label evidence per symbol over every captured list date, one query per date (no symbol
        array, so the read stays linear at the full universe). An incomplete capture raises."""
        evidence: dict[str, _Evidence] = defaultdict(_Evidence)
        dates = [row["as_of"] for row in await conn.fetch(_LIST_DATES_SQL)]
        if not dates:
            raise RuntimeError("no pit_snapshots list is captured; nothing written")
        if dates[-1] > LAST_LIST_DATE:
            raise RuntimeError(
                f"a list dated {dates[-1]} is captured after L = {LAST_LIST_DATE}: the closed list "
                "and the pin assume none; a dated amendment moves L; nothing written"
            )
        for as_of in dates:
            problem = snapshot_problem(as_of, await conn.fetch(_SNAPSHOT_PAGES_SQL, as_of))
            if problem:
                raise RuntimeError(f"pit_snapshots for list {as_of}: {problem}; nothing written")
            for row in await conn.fetch(_LABELS_SQL, as_of):
                evidence[row["symbol"]].add(row["label"], as_of)
        return dict(evidence)


def main() -> None:
    parser = argparse.ArgumentParser(description="Build security_type, one resolved type each")
    parser.add_argument(
        "--apply", action="store_true", help="write (default: rolled-back rehearsal)"
    )
    args = parser.parse_args()
    try:
        init_otel_providers(f"indicagent-{_JOB}")
    except OTelInitError:
        pass
    db_dsn = Settings().database_url.replace("postgresql+asyncpg://", "postgresql://")
    asyncio.run(SecurityTypeWriter(db_dsn, args.apply).run())


if __name__ == "__main__":
    main()
