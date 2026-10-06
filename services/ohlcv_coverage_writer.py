"""The single writer of ohlcv_coverage (phase 189 plan 01, CD-03/CD-04/CD-05; migration 432).

ohlcv_coverage is a materialized rollup per (symbol, timeframe): stored bounds, stored row
count, the latest fetch outcome and a genuine-failure counter. The IBKR history fetcher ranks
its queue from it in O(1) instead of scanning bars per symbol per run. It is not a competing
truth: ohlcv_request and the bar tables stay authoritative, and the ledger stays in step with
them only because it is written here and nowhere else (single_writer; CI guard
tests/unit/test_ohlcv_coverage_writer_boundary.py), from two places:

- upsert_coverage, inside persist_chunk_atomically's one transaction, right after the bar
  insert (request rows -> bars -> coverage, one COMMIT), so the ledger can never describe bars
  that did not land;
- record_fetch_outcome / reset_failures, from the fetcher's per-item outcome write and its
  --reset-failures flag, so operators never hand-write the table;
- refresh_1d_bounds, from the fetcher after the daily derivation stage (1d bars are D2's,
  never a fetched chunk's, so their bounds are recomputed from the canonical rows);
- rebuild_from_stored_state, from the fetcher's --rebuild-coverage flag under its lock, which
  recomputes every row from the stored bars when another writer stored bars around the ledger.

Every function takes a psycopg cursor whose transaction has already run
SET LOCAL ROLE bar_derivation_writer (the only role granted SELECT, INSERT, UPDATE here).
DB only: no IBKR, no network, no commits of its own.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

# The ledger's CHECK values (migration 432). 'no_data' is a correct empty answer, never a
# failure (CD-05); only 'error' counts toward infra.backfill.max_consecutive_failures.
FETCH_STATUSES = ("ok", "no_data", "error")
_ERROR_STATUS = "error"

# Fetch destination -> the bar table it stores into (schema identifiers, APR-exempt). 15m/1h
# fetches land in the raw archive since 185-12; every other timeframe lands in the grid table.
DESTINATION_ARCHIVE = "archive"
DESTINATION_GRID = "grid"
DESTINATION_TABLES = {
    DESTINATION_ARCHIVE: "ohlcv_intraday_raw_archive",
    DESTINATION_GRID: "market_data_ohlcv",
}

_UPSERT_SQL = """
INSERT INTO ohlcv_coverage (
    symbol, timeframe, earliest_timestamp, latest_timestamp, row_count,
    last_fetched_at, last_fetch_status, consecutive_failures
) VALUES (%s, %s, %s, %s, %s, %s, 'ok', 0)
ON CONFLICT (symbol, timeframe) DO UPDATE SET
    earliest_timestamp = LEAST(ohlcv_coverage.earliest_timestamp, EXCLUDED.earliest_timestamp),
    latest_timestamp = GREATEST(ohlcv_coverage.latest_timestamp, EXCLUDED.latest_timestamp),
    row_count = ohlcv_coverage.row_count + EXCLUDED.row_count,
    last_fetched_at = EXCLUDED.last_fetched_at,
    last_fetch_status = 'ok',
    consecutive_failures = 0
"""

_OUTCOME_SQL = """
INSERT INTO ohlcv_coverage (
    symbol, timeframe, last_fetched_at, last_fetch_status, consecutive_failures
) VALUES (%s, %s, %s, %s, %s)
ON CONFLICT (symbol, timeframe) DO UPDATE SET
    last_fetched_at = EXCLUDED.last_fetched_at,
    last_fetch_status = EXCLUDED.last_fetch_status,
    consecutive_failures = CASE
        WHEN EXCLUDED.last_fetch_status = 'error' THEN ohlcv_coverage.consecutive_failures + 1
        ELSE 0
    END
"""


@dataclass(frozen=True)
class CoverageDelta:
    """Which series one fetched chunk belongs to, and where its bars are stored."""

    symbol: str
    timeframe: str
    destination: str
    fetched_at: datetime

    def __post_init__(self) -> None:
        if self.destination not in DESTINATION_TABLES:
            raise ValueError(
                f"unknown coverage destination {self.destination!r}; "
                f"expected one of {sorted(DESTINATION_TABLES)}"
            )


def existing_timestamps(
    cur: Any, destination: str, symbol: str, timeframe: str, timestamps: Iterable[datetime]
) -> set[datetime]:
    """Timestamps among `timestamps` the destination table already stores for the series.

    One indexed read, run before the bar insert so the caller can count how many offered rows
    are genuinely new (the bar writers use ON CONFLICT DO NOTHING and return rows offered).
    """
    table = DESTINATION_TABLES[destination]
    cur.execute(
        f"SELECT timestamp FROM {table} "
        "WHERE symbol = %s AND timeframe = %s AND timestamp = ANY(%s)",
        (symbol, timeframe, list(timestamps)),
    )
    return {row[0] for row in cur.fetchall()}


def upsert_coverage(
    cur: Any,
    delta: CoverageDelta,
    *,
    earliest: datetime,
    latest: datetime,
    n_new_rows: int,
) -> None:
    """Widen the series' stored bounds, add its new rows, and mark the fetch ok.

    Runs under SET LOCAL ROLE bar_derivation_writer inside the bars' transaction. LEAST and
    GREATEST ignore NULLs, so the first bars onto a no_data-only row set its bounds.
    """
    if n_new_rows < 0:
        raise ValueError(f"n_new_rows must be >= 0, got {n_new_rows}")
    cur.execute(
        _UPSERT_SQL,
        (delta.symbol, delta.timeframe, earliest, latest, n_new_rows, delta.fetched_at),
    )


def record_fetch_outcome(
    cur: Any, symbol: str, timeframe: str, status: str, fetched_at: datetime
) -> None:
    """Record one queue item's outcome; only 'error' increments consecutive_failures (CD-05).

    'ok' and 'no_data' reset the counter: a correct empty answer is an answer. Runs under
    SET LOCAL ROLE bar_derivation_writer. An unknown status raises before any SQL.
    """
    if status not in FETCH_STATUSES:
        raise ValueError(f"unknown fetch status {status!r}; expected one of {FETCH_STATUSES}")
    initial_failures = 1 if status == _ERROR_STATUS else 0
    cur.execute(_OUTCOME_SQL, (symbol, timeframe, fetched_at, status, initial_failures))


_REFRESH_1D_SQL = """
INSERT INTO ohlcv_coverage (symbol, timeframe, earliest_timestamp, latest_timestamp, row_count)
SELECT symbol, '1d', min("timestamp"), max("timestamp"), count(*)
FROM market_data_ohlcv_tradeable
WHERE symbol = ANY(%s) AND timeframe = '1d'
GROUP BY symbol
ON CONFLICT (symbol, timeframe) DO UPDATE SET
    earliest_timestamp = EXCLUDED.earliest_timestamp,
    latest_timestamp = EXCLUDED.latest_timestamp,
    row_count = EXCLUDED.row_count
"""


def refresh_1d_bounds(cur: Any, symbols: Iterable[str]) -> int:
    """Recompute the 1d bounds and row count of `symbols` from the canonical 1d rows.

    A 1d fetch stores no bar (the daily derivation stage is the sole 1d writer, plan 185-18
    task 1b), so no persist_chunk_atomically call ever moves a 1d series' bounds. The fetcher
    calls this after the daily stage derived the symbols it fetched, so the queue's 1d
    staleness reads the rows D2 wrote rather than the migration 432 bootstrap. Recomputed,
    not widened: D2 may rewrite a 1d history (split re-derivation). Fetch status and the
    failure counter are left to record_fetch_outcome. A symbol with no tradeable 1d row is
    left untouched. Runs under SET LOCAL ROLE bar_derivation_writer. Returns rows written.
    """
    symbol_list = sorted(set(symbols))
    if not symbol_list:
        return 0
    cur.execute(_REFRESH_1D_SQL, (symbol_list,))
    return int(cur.rowcount)


# Migration 432's bootstrap aggregate, as an update-in-place. {where} is either empty or a
# symbol filter; it is spliced into every source scan so a scoped rebuild reads only its rows.
_REBUILD_SQL = """
INSERT INTO ohlcv_coverage (
    symbol, timeframe, earliest_timestamp, latest_timestamp, row_count,
    last_fetched_at, last_fetch_status
)
WITH grid AS (
    SELECT symbol, timeframe,
           min("timestamp") AS earliest, max("timestamp") AS latest, count(*) AS n
    FROM market_data_ohlcv_tradeable
    {where}
    GROUP BY symbol, timeframe
),
archive AS (
    SELECT symbol, timeframe,
           min("timestamp") AS earliest, max("timestamp") AS latest, count(*) AS n
    FROM ohlcv_intraday_raw_archive
    {where}
    GROUP BY symbol, timeframe
),
bars AS (
    SELECT coalesce(g.symbol, a.symbol) AS symbol,
           coalesce(g.timeframe, a.timeframe) AS timeframe,
           LEAST(g.earliest, a.earliest) AS earliest,
           GREATEST(g.latest, a.latest) AS latest,
           GREATEST(coalesce(g.n, 0), coalesce(a.n, 0)) AS n
    FROM grid g
    FULL OUTER JOIN archive a
      ON a.symbol = g.symbol AND a.timeframe = g.timeframe
    WHERE coalesce(g.timeframe, a.timeframe) IN ('15m', '1h')
    UNION ALL
    SELECT symbol, timeframe, earliest, latest, n
    FROM grid
    WHERE timeframe NOT IN ('15m', '1h')
),
requests AS (
    SELECT DISTINCT ON (symbol, timeframe)
           symbol, timeframe, answered_at,
           CASE outcome
               WHEN 'bars' THEN 'ok'
               WHEN 'no_data' THEN 'no_data'
               ELSE 'error'
           END AS status
    FROM ohlcv_request
    {request_where}
    ORDER BY symbol, timeframe, answered_at DESC
)
SELECT coalesce(b.symbol, r.symbol),
       coalesce(b.timeframe, r.timeframe),
       b.earliest,
       b.latest,
       coalesce(b.n, 0),
       r.answered_at,
       r.status
FROM bars b
FULL OUTER JOIN requests r
  ON r.symbol = b.symbol AND r.timeframe = b.timeframe
ON CONFLICT (symbol, timeframe) DO UPDATE SET
    earliest_timestamp = EXCLUDED.earliest_timestamp,
    latest_timestamp = EXCLUDED.latest_timestamp,
    row_count = EXCLUDED.row_count,
    last_fetched_at = GREATEST(ohlcv_coverage.last_fetched_at, EXCLUDED.last_fetched_at),
    last_fetch_status = CASE
        WHEN EXCLUDED.last_fetched_at IS NOT NULL
             AND (ohlcv_coverage.last_fetched_at IS NULL
                  OR EXCLUDED.last_fetched_at > ohlcv_coverage.last_fetched_at)
        THEN EXCLUDED.last_fetch_status
        ELSE ohlcv_coverage.last_fetch_status
    END
"""
_REQUEST_FILTER = (
    "WHERE route = 'SMART' AND what_to_show = 'TRADES' "
    "AND outcome IN ('bars', 'no_data', 'timeout', 'failed')"
)


def rebuild_from_stored_state(cur: Any, symbols: Iterable[str] | None = None) -> int:
    """Recompute every ledger row's bounds and row count from the stored bars, in place.

    Migration 432 bootstrapped the ledger once with ON CONFLICT DO NOTHING, so a writer that
    stored bars without going through persist_chunk_atomically (the todo 449 lane, which ran
    with coverage=None from 2026-10-02 to the 189-06 cutover) leaves rows stale or missing.
    This is the same aggregate as that bootstrap, with DO UPDATE: earliest, latest and
    row_count are recomputed (not widened) from market_data_ohlcv_tradeable and, for 15m/1h,
    the raw archive; missing series are inserted. The latest SMART TRADES request advances
    last_fetched_at and last_fetch_status only when it is newer than what the ledger holds.
    consecutive_failures is never touched: it counts the fetcher's own item outcomes.

    `symbols` scopes the rebuild (tests use a synthetic symbol); None rebuilds every series.
    Run under SET LOCAL ROLE bar_derivation_writer while holding the fetcher lock, so no
    persist_chunk_atomically delta can interleave. Returns rows inserted or updated.
    """
    if symbols is None:
        sql = _REBUILD_SQL.format(where="", request_where=_REQUEST_FILTER)
        cur.execute(sql)
        return int(cur.rowcount)
    symbol_list = sorted(set(symbols))
    if not symbol_list:
        return 0
    sql = _REBUILD_SQL.format(
        where="WHERE symbol = ANY(%(symbols)s)",
        request_where=f"{_REQUEST_FILTER} AND symbol = ANY(%(symbols)s)",
    )
    cur.execute(sql, {"symbols": symbol_list})
    return int(cur.rowcount)


def reset_failures(cur: Any, symbol: str, timeframe: str | None) -> int:
    """Zero consecutive_failures for a symbol (one timeframe, or all when None).

    The fetcher's --reset-failures path re-admits an excluded series to the queue. Runs under
    SET LOCAL ROLE bar_derivation_writer. Returns the number of rows reset.
    """
    if timeframe is None:
        cur.execute(
            "UPDATE ohlcv_coverage SET consecutive_failures = 0 WHERE symbol = %s", (symbol,)
        )
    else:
        cur.execute(
            "UPDATE ohlcv_coverage SET consecutive_failures = 0 "
            "WHERE symbol = %s AND timeframe = %s",
            (symbol, timeframe),
        )
    return cur.rowcount
