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
its hysteresis state from the last built month and refuses to extend a ledger whose rule ids are
off the schedule (`rule_id_for`). A month-end after L = 2026-11-09 has no list of its own: its
candidates and types are the list at L (the closed list, rule id `stage2-closed-list`, amendment
2026-11-18), so a name that list did not place is never a member. Such a month is refused until a later canonical
1d bar exists (its own bars may still be arriving). The run fails loudly, writing nothing, on: a month-end whose snapshot capture is not
complete (both lists, contiguous pages, last page without next_url, status OK); no inactive name
among the placed symbols (a survivor-only build); an empty month once any built month had
members. The price test uses the as-traded close: canonical closes are un-adjusted by every
current market split of the symbol (`corporate_action_current` rows `is_market_split` accepts, no
time filter: the set `daily_rule.split_scale` divided by, via
`bar_derivation._SELECT_DAILY_SPLITS_SQL`, mirrored by the migration 588 lineage view) with
effective_date on or after the month-end. The build refuses when canonical is not current with
the splits: any corporate_action row (superseding and void rows included) recorded after the
symbol's latest 1d `bar_content_digest.computed_at`, or actions and no 1d digest.
Every run writes `data/universe_membership/<through>/vanished_without_final_bar.csv`
(members whose bars stop well before their placed span). A run without `--apply` does everything
and rolls the transaction back.

    .venv/bin/python -m services.universe_membership_writer --through 2026-10-30 \\
        # rehearsal
    (same command with --apply to write)

Not to be run on real data before the step 7 data gate passes and the stage 2 load (preregistration
gate 3) is done.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import math
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import Any

import asyncpg
import numpy as np

from src.config.settings import Settings
from src.core.agent.base_batch import BaseBatch
from src.intelligence.bars.corporate_actions import is_market_split
from src.intelligence.bars.sessions import nyse_sessions
from src.intelligence.bars.split_rescale import SplitFactor
from src.intelligence.universe_membership import (
    ARCHIVE_START,
    LAST_LIST_DATE,
    RULE,
    RULE_ID,
    MembershipRow,
    SecurityHistory,
    closed_list_candidates_problem,
    ledger_rule_problem,
    memberships_for_security,
    month_end_sessions,
    rule_id_for,
    type_list_date,
)
from src.observability.otel import OTelInitError, init_otel_providers

_JOB = "universe-membership-writer"
_LOCK_KEY = 5970001  # advisory lock: one run at a time (the table's one writer)
_SYMBOL_CHUNK = 500  # symbols per bar read; membership of one symbol never depends on another
_OUT_ROOT = Path(__file__).resolve().parents[1] / "data" / "universe_membership"
# A last bar this many calendar days before the end of the symbol's last placed span (or before
# `--through` for an open span) is a name that vanished without its final bars (weekends and
# holidays stay under it).
_VANISH_GRACE_DAYS = 7

_PLACED_SYMBOLS_SQL = """
SELECT DISTINCT symbol FROM ticker_event WHERE vendor = 'massive' AND retired_at IS NULL
ORDER BY symbol
"""
_LEDGER_SQL = "SELECT as_of, rule_id, n_members FROM universe_membership_build ORDER BY as_of"
_INACTIVE_PLACED_SQL = "SELECT count(*) FROM instruments WHERE symbol = ANY($1) AND NOT is_active"
_SPAN_END_SQL = """
SELECT symbol, bool_or(valid_to IS NULL) AS open_span, max(valid_to) AS span_end
  FROM ticker_event
 WHERE vendor = 'massive' AND retired_at IS NULL AND symbol = ANY($1)
 GROUP BY symbol
"""
# Exactly the split set the canonical 1d close was divided by: every current corporate_action row
# of the symbol (bar_derivation._SELECT_DAILY_SPLITS_SQL), no recorded_at horizon, kept when
# is_market_split accepts it (daily_rule.split_scale; migration 588 lineage view).
_SPLITS_SQL = """
SELECT symbol, effective_date, factor, inferred_by, detail ? 'rows_file' AS rows_file
  FROM corporate_action_current
 WHERE symbol = ANY($1)
 ORDER BY symbol, effective_date
"""
# Canonical is not current with the splits when any corporate_action row of the symbol (the base
# table: superseding and void rows count) was recorded after the symbol's latest 1d digest, or
# the symbol has actions and no 1d digest at all.
_STALE_SPLITS_SQL = """
SELECT ca.symbol, max(ca.recorded_at) AS latest_action, d.computed_at AS latest_digest
  FROM corporate_action ca
  LEFT JOIN (
        SELECT symbol, max(computed_at) AS computed_at
          FROM bar_content_digest WHERE timeframe = '1d' AND symbol = ANY($1)
         GROUP BY symbol
       ) d ON d.symbol = ca.symbol
 WHERE ca.symbol = ANY($1)
 GROUP BY ca.symbol, d.computed_at
HAVING d.computed_at IS NULL OR max(ca.recorded_at) > d.computed_at
 ORDER BY ca.symbol
"""
# A month-end after L has no list of its own, so no capture check says its bars have arrived: a
# later canonical 1d bar stands in for it (the nightly that loaded the next session also answered
# the month-end's window), and the build refuses without one. Bars arrive per session, so a
# half-loaded month-end would turn the names still missing a bar into non-members for good.
_LATER_BAR_SQL = """
SELECT EXISTS (SELECT 1 FROM market_data_ohlcv_tradeable
                WHERE timeframe = '1d' AND "timestamp" >= $1)
"""
_MEMBERS_AT_SQL = "SELECT symbol, tier_5m FROM universe_membership WHERE as_of = $1"
# Every page of the month-end's two snapshot lists (`<date>@active` and `<date>@inactive`).
_SNAPSHOT_PAGES_SQL = """
SELECT request_key, page, http_status, body->>'status' AS status, body->>'next_url' AS next_url
  FROM reference_raw_current
 WHERE vendor = 'massive' AND endpoint = 'pit_snapshots' AND as_of = $1
 ORDER BY request_key, page
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
 ORDER BY (r.request_key LIKE '%@active') DESC, te.symbol, x->>'type', x->>'ticker'
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


def snapshot_problem(as_of: date, pages: Sequence[Mapping[str, Any]]) -> str | None:
    """Why the month-end's snapshot capture is not a complete answer, or None when it is.

    Both lists (`<date>@active` and `<date>@inactive`) must be present; each list's pages must
    be exactly 1..n, every page HTTP 200 with body status OK, every page but the last pointing to
    a next page, and the last page's next_url empty. A truncated or one-sided capture would turn
    missing names into non-members silently."""
    by_key: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for page in pages:
        by_key[page["request_key"]].append(page)
    for suffix in ("active", "inactive"):
        key = f"{as_of.isoformat()}@{suffix}"
        got = sorted(by_key.get(key, []), key=lambda p: p["page"])
        if not got:
            return f"{key} is not captured"
        if [p["page"] for p in got] != list(range(1, len(got) + 1)):
            return f"{key} pages {[p['page'] for p in got]} are not 1..{len(got)}"
        for p in got:
            if p["http_status"] != 200 or p["status"] != "OK":
                return f"{key} page {p['page']} is http {p['http_status']} status {p['status']!r}"
        if any(not p["next_url"] for p in got[:-1]):
            return f"{key} has a page before the last with no next_url"
        if got[-1]["next_url"]:
            return f"{key} last page {got[-1]['page']} still has a next_url (truncated capture)"
    return None


def _number(value: Any) -> float:
    """A bar value as float; NULL is NaN (not a member, never filled)."""
    return math.nan if value is None else float(value)


def histories_from_records(
    records: Sequence[Any], splits: Mapping[str, Sequence[SplitFactor]] | None = None
) -> dict[str, SecurityHistory]:
    """Group (symbol, day, close, volume) records, ordered by symbol and day, into histories.
    A NULL close or volume becomes NaN; `splits` are the symbol's market splits."""
    grouped: dict[str, list[tuple[date, float, float]]] = defaultdict(list)
    for symbol, day, close, volume in records:
        grouped[symbol].append((day, _number(close), _number(volume)))
    out: dict[str, SecurityHistory] = {}
    for symbol, bars in grouped.items():
        out[symbol] = SecurityHistory(
            symbol=symbol,
            days=np.array([b[0] for b in bars], dtype="datetime64[D]"),
            close=np.array([b[1] for b in bars], dtype=np.float64),
            volume=np.array([b[2] for b in bars], dtype=np.float64),
            splits=tuple((splits or {}).get(symbol, ())),
        )
    return out


class UniverseMembershipWriter(BaseBatch):
    """Appends the month-ends not yet in the ledger, under the preregistered rule."""

    job_name = _JOB
    compute_version = RULE_ID

    def __init__(
        self,
        db_dsn: str,
        through: date,
        apply: bool = False,
        out_dir: Path | None = None,
    ) -> None:
        super().__init__(db_dsn)
        self._through = through
        self._apply = apply
        self._out_dir = out_dir or _OUT_ROOT / through.isoformat()

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
        problem = ledger_rule_problem((r["as_of"], r["rule_id"]) for r in ledger)
        if problem:
            raise RuntimeError(problem)
        built = [r["as_of"] for r in ledger]
        had_members = any(r["n_members"] > 0 for r in ledger)
        month_ends = month_ends_through(self._through)
        if built and built[-1] not in month_ends:
            raise RuntimeError(
                f"last built month {built[-1]} is not a month-end through {self._through}"
            )
        todo = [m for m in month_ends if not built or m > built[-1]]
        if not todo:
            self.logger.info("universe_membership.up_to_date", through=str(self._through))
            return False

        after_l = [m for m in todo if m > LAST_LIST_DATE]
        if after_l:
            next_day = datetime.combine(after_l[-1] + timedelta(days=1), time.min, tzinfo=UTC)
            if not await conn.fetchval(_LATER_BAR_SQL, next_day):
                raise RuntimeError(
                    f"no canonical 1d bar after month-end {after_l[-1]}: its bars may be "
                    "incomplete, and a month built on them cannot be corrected; nothing written"
                )
        types = await self._types(conn, todo)
        if after_l:  # a closed-list month reads the candidate set at L: it must be the pinned one
            problem = closed_list_candidates_problem(types[after_l[0]])
            if problem:
                raise RuntimeError(f"{problem}; nothing written")
        seed = {
            r["symbol"]: r["tier_5m"]
            for r in (await conn.fetch(_MEMBERS_AT_SQL, built[-1]) if built else [])
        }
        symbols = [r["symbol"] for r in await conn.fetch(_PLACED_SYMBOLS_SQL)]
        if not await conn.fetchval(_INACTIVE_PLACED_SQL, symbols):
            raise RuntimeError(
                "no placed symbol is inactive: a survivor-only build is the survivorship this "
                "universe exists to remove (stage 2 gates 3 and 4 are not done); nothing written"
            )
        stop = datetime.combine(self._through + timedelta(days=1), time.min, tzinfo=UTC)

        rows: list[MembershipRow] = []
        vanished: list[tuple[str, date, date, str]] = []
        stale: list[str] = []
        for lo in range(0, len(symbols), _SYMBOL_CHUNK):
            chunk = symbols[lo : lo + _SYMBOL_CHUNK]
            stale += [
                f"{r['symbol']} (split recorded {r['latest_action']}, 1d digest {r['latest_digest']})"
                for r in await conn.fetch(_STALE_SPLITS_SQL, chunk)
            ]
            splits = await self._splits(conn, chunk)
            histories = histories_from_records(await conn.fetch(_BARS_SQL, chunk, stop), splits)
            ends = {r["symbol"]: r for r in await conn.fetch(_SPAN_END_SQL, chunk)}
            for symbol, history in histories.items():
                member_rows = memberships_for_security(
                    history,
                    todo,
                    {m: types[m].get(symbol) for m in todo},
                    was_member=symbol in seed,
                    was_tier=seed.get(symbol, False),
                    rule=RULE,
                )
                rows += member_rows
                if member_rows:
                    gone = self._vanished(history, member_rows[-1].as_of, ends.get(symbol))
                    if gone:
                        vanished.append(gone)
        self._write_report(vanished)
        if stale:
            raise RuntimeError(
                f"canonical 1d is not current with the splits for {len(stale)} symbol(s); "
                f"re-derive them first: {'; '.join(stale[:20])}"
                f"{' ...' if len(stale) > 20 else ''}; nothing written"
            )

        counts = Counter(row.as_of for row in rows)
        # Early month-ends have under 60 sessions of history and are legitimately empty; once a
        # month has members, an empty month (or no member at all in the run) is a failed build.
        first = next((m for m in todo if counts[m]), None)
        empty = [
            m for m in todo if counts[m] == 0 and (had_members or (first is not None and m > first))
        ]
        if (first is None and not had_members) or empty:
            raise RuntimeError(
                f"no member at month-end(s) {[str(m) for m in (empty or todo)]}; nothing written"
            )
        await conn.executemany(
            "INSERT INTO universe_membership_build (as_of, rule_id, n_members) VALUES ($1, $2, $3)",
            [(m, rule_id_for(m), counts[m]) for m in todo],
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
                "tier_5m",
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
                    r.tier_5m,
                )
                for r in rows
            ],
        )
        tier_counts = Counter(row.as_of for row in rows if row.tier_5m)
        by_year: Counter[int] = Counter()
        tier_by_year: Counter[int] = Counter()
        for m in todo:
            by_year[m.year] = max(by_year[m.year], counts[m])
            tier_by_year[m.year] = max(tier_by_year[m.year], tier_counts[m])
        self.logger.info(
            "universe_membership.built",
            months=len(todo),
            rows=len(rows),
            first=str(todo[0]),
            last=str(todo[-1]),
            apply=self._apply,
            max_members_by_year=dict(sorted(by_year.items())),
            max_tier_5m_by_year=dict(sorted(tier_by_year.items())),
            vanished_without_final_bar=len(vanished),
        )
        return True

    @staticmethod
    async def _splits(
        conn: asyncpg.Connection, symbols: Sequence[str]
    ) -> dict[str, list[SplitFactor]]:
        """Each symbol's market splits, the set canonical 1d was divided by (daily_rule.split_scale
        over bar_derivation._SELECT_DAILY_SPLITS_SQL; the migration 588 lineage view)."""
        out: dict[str, list[SplitFactor]] = defaultdict(list)
        for r in await conn.fetch(_SPLITS_SQL, list(symbols)):
            if is_market_split(r["inferred_by"], operator_rows_file=r["rows_file"]):
                out[r["symbol"]].append(SplitFactor(r["effective_date"], r["factor"]))
        return dict(out)

    def _vanished(
        self, history: SecurityHistory, last_member: date, span: Mapping[str, Any] | None
    ) -> tuple[str, date, date, str] | None:
        """(symbol, last member month-end, last bar, expected end) for a member whose bars stop
        well before its placed span does (before `--through` for an open span); else None."""
        if span is None:
            return None
        last_bar = history.days[-1].astype("datetime64[D]").item()
        expected = (
            self._through
            if span["open_span"] or span["span_end"] is None
            else span["span_end"] - timedelta(days=1)
        )
        if (expected - last_bar).days > _VANISH_GRACE_DAYS:
            return (history.symbol, last_member, last_bar, expected.isoformat())
        return None

    def _write_report(self, vanished: Sequence[tuple[str, date, date, str]]) -> None:
        """Names that were members and vanished without a final bar (preregistration failure
        mode), written on every run, rehearsal included."""
        self._out_dir.mkdir(parents=True, exist_ok=True)
        with (self._out_dir / "vanished_without_final_bar.csv").open("w", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(["symbol", "last_member_as_of", "last_bar", "expected_end"])
            writer.writerows(sorted(vanished))

    @staticmethod
    async def _types(
        conn: asyncpg.Connection, month_ends: Sequence[date]
    ) -> dict[date, dict[str, str]]:
        """Type by symbol for each month-end, read from the list that decides it (its own, or the
        list at L after L: the closed list). A list that was not captured completely raises."""
        by_list: dict[date, dict[str, str]] = {}
        for as_of in month_ends:
            list_date = type_list_date(as_of)
            if list_date in by_list:
                continue
            problem = snapshot_problem(list_date, await conn.fetch(_SNAPSHOT_PAGES_SQL, list_date))
            if problem:
                raise RuntimeError(
                    f"pit_snapshots for list {list_date} (month-end {as_of}): {problem}"
                )
            found: dict[str, str] = {}
            for row in await conn.fetch(_TYPES_SQL, list_date):
                if row["security_type"]:
                    found.setdefault(row["symbol"], row["security_type"])
            by_list[list_date] = found
        return {as_of: by_list[type_list_date(as_of)] for as_of in month_ends}


async def candidates_at_l(conn: asyncpg.Connection) -> dict[str, str]:
    """The candidates (symbol -> type) the list at L places, read as a build reads them."""
    return (await UniverseMembershipWriter._types(conn, [LAST_LIST_DATE]))[LAST_LIST_DATE]


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
        UniverseMembershipWriter(
            db_dsn,
            date.fromisoformat(args.through),
            args.apply,
        ).run()
    )


if __name__ == "__main__":
    main()
