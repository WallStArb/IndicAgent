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
- refresh_1d_bounds, from the fetcher after its 1d answers landed (a 1d answer carries no
  coverage delta, so its bounds are recomputed from the vendor's raw rows);
- rebuild_from_stored_state, from the fetcher's --rebuild-coverage flag under its lock, which
  recomputes every row from the vendor's raw rows when another writer stored bars around the
  ledger.

Coverage is per source (phase 191 plan 06): a row (symbol, timeframe, provider) describes what
that vendor holds in ohlcv_raw, counted in distinct slots, whether or not another vendor's rows
are canonical at those slots.

Every function takes a psycopg cursor whose transaction has already run
SET LOCAL ROLE bar_derivation_writer (the only role granted SELECT, INSERT, UPDATE here).
DB only: no IBKR, no network, no commits of its own.

Provider dimension (phase 190 plan 02, migration 464): every write carries the authoring
fetch plane's label, `provider`, defaulting to "ibkr" -- the stored-state default until a
second provider exists (the alpaca entries land with the todo-521 leaf). The label is the
canonical tier's authoring plane, never a per-vendor provenance claim over the stored bars
(vendor claims live in ohlcv_load.source and the per-provider tier). The upserts' CONFLICT
TARGET STAYS THE OLD SHAPE (symbol, timeframe) in this plan: see the comment on _UPSERT_SQL.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from src.intelligence.bars.gap_plan import DAILY_NOT_COVERAGE_KINDS

# The ledger's CHECK values (migration 432). 'no_data' is a correct empty answer, never a
# failure (CD-05); only 'error' counts toward infra.backfill.max_consecutive_failures.
FETCH_STATUSES = ("ok", "no_data", "error")
_ERROR_STATUS = "error"

# The ledger fetch status of each recorded request outcome (src/providers/base.py's outcome
# contract). The one definition: the rebuild's CASE and outcome filter are generated from it, so an
# incremental status write and a rebuild cannot disagree.
_OUTCOME_STATUS = {
    "bars": "ok",
    "no_data": "no_data",
    "timeout": _ERROR_STATUS,
    "failed": _ERROR_STATUS,
}
_OUTCOME_LIST = ", ".join(f"'{outcome}'" for outcome in _OUTCOME_STATUS)
_OUTCOME_CASE = (
    "CASE outcome "
    + " ".join(f"WHEN '{outcome}' THEN '{status}'" for outcome, status in _OUTCOME_STATUS.items())
    + " END"
)


def fetch_status_for_outcome(outcome: str) -> str | None:
    """The ledger fetch status of a recorded request outcome, or None for an outcome the rebuild
    ignores (it reads only the contract's four), so an incremental write never records what a
    rebuild would not."""
    return _OUTCOME_STATUS.get(outcome)


# Every fetched bar lands in ohlcv_raw, keyed by the vendor that served it (schema identifier,
# APR-exempt). The one destination is kept as the delta's declared target so a caller that
# still names another store fails loudly instead of crediting the wrong ledger.
DESTINATION_RAW = "raw"

_UPSERT_SQL = """
INSERT INTO ohlcv_coverage (
    symbol, timeframe, earliest_timestamp, latest_timestamp, row_count,
    last_fetched_at, last_fetch_status, consecutive_failures, provider
) VALUES (%s, %s, %s, %s, %s, %s, 'ok', 0, %s)
ON CONFLICT (symbol, timeframe, provider) DO UPDATE SET
    earliest_timestamp = LEAST(ohlcv_coverage.earliest_timestamp, EXCLUDED.earliest_timestamp),
    latest_timestamp = GREATEST(ohlcv_coverage.latest_timestamp, EXCLUDED.latest_timestamp),
    row_count = ohlcv_coverage.row_count + EXCLUDED.row_count,
    last_fetched_at = EXCLUDED.last_fetched_at,
    last_fetch_status = 'ok',
    consecutive_failures = 0
"""

_OUTCOME_SQL = """
INSERT INTO ohlcv_coverage (
    symbol, timeframe, last_fetched_at, last_fetch_status, consecutive_failures, provider
) VALUES (%s, %s, %s, %s, %s, %s)
ON CONFLICT (symbol, timeframe, provider) DO UPDATE SET
    last_fetched_at = EXCLUDED.last_fetched_at,
    last_fetch_status = EXCLUDED.last_fetch_status,
    consecutive_failures = CASE
        WHEN EXCLUDED.last_fetch_status = 'error' THEN ohlcv_coverage.consecutive_failures + 1
        ELSE 0
    END
"""


@dataclass(frozen=True)
class CoverageDelta:
    """Which series one fetched chunk belongs to, where its bars are stored (ohlcv_raw), and
    which vendor served the chunk.

    `provider` is the canonical tier's stored-state label (migration 464): the vendor whose
    fetch path actually produced the chunk, so a second vendor's coverage can never
    silently record as ibkr. The default keeps every pre-190 caller valid and is the
    stored-state default until a second provider exists; it is not a provenance claim over
    the stored bars (those live in ohlcv_load.source and the per-provider tier).
    """

    symbol: str
    timeframe: str
    destination: str
    fetched_at: datetime
    provider: str = "ibkr"

    def __post_init__(self) -> None:
        if self.destination != DESTINATION_RAW:
            raise ValueError(
                f"unknown coverage destination {self.destination!r}; "
                f"the only destination is {DESTINATION_RAW!r}"
            )


def upsert_coverage(
    cur: Any,
    delta: CoverageDelta,
    *,
    earliest: datetime,
    latest: datetime,
    n_new_rows: int,
) -> None:
    """Widen the series' stored bounds, add its new rows, and mark the fetch ok.

    The row is labeled with the delta's provider (the vendor that fetched the chunk), under
    the per-provider conflict target (symbol, timeframe, provider) that migration 465
    introduced. Runs under SET LOCAL ROLE
    bar_derivation_writer inside the bars' transaction. LEAST and GREATEST ignore NULLs, so
    the first bars onto a no_data-only row set its bounds.
    """
    if n_new_rows < 0:
        raise ValueError(f"n_new_rows must be >= 0, got {n_new_rows}")
    cur.execute(
        _UPSERT_SQL,
        (
            delta.symbol,
            delta.timeframe,
            earliest,
            latest,
            n_new_rows,
            delta.fetched_at,
            delta.provider,
        ),
    )


def record_fetch_outcome(
    cur: Any,
    symbol: str,
    timeframe: str,
    status: str,
    fetched_at: datetime,
    *,
    provider: str = "ibkr",
) -> None:
    """Record one queue item's outcome; only 'error' increments consecutive_failures (CD-05).

    'ok' and 'no_data' reset the counter: a correct empty answer is an answer. The outcome is
    per-provider row state (the label is the stored-state default until a second provider
    exists). Runs under SET LOCAL ROLE bar_derivation_writer. An unknown status raises
    before any SQL.
    """
    if status not in FETCH_STATUSES:
        raise ValueError(f"unknown fetch status {status!r}; expected one of {FETCH_STATUSES}")
    initial_failures = 1 if status == _ERROR_STATUS else 0
    cur.execute(_OUTCOME_SQL, (symbol, timeframe, fetched_at, status, initial_failures, provider))


_HELD_ROWS_SQL = """
SELECT "timestamp", count(*) FROM ohlcv_raw
WHERE symbol = %s AND timeframe = %s AND vendor = %s AND "timestamp" = ANY(%s)
GROUP BY "timestamp"
"""


def count_new_slots(
    cur: Any, symbol: str, timeframe: str, provider: str, new_timestamps: Iterable[datetime]
) -> int:
    """Distinct slots a chunk added to the provider's series, which is what row_count counts.

    `new_timestamps` lists one entry per newly inserted raw row, so a stamp the provider already
    held under another kind (alpaca sip_rth and iex_rth share stamps) appears new while adding no
    slot. A stamp is a new slot only when every row the provider holds there is one of this
    chunk's new rows; call after the raw write, in its transaction.
    """
    inserted = dict(Counter(new_timestamps))
    if not inserted:
        return 0
    cur.execute(_HELD_ROWS_SQL, (symbol, timeframe, provider, list(inserted)))
    # a stored stamp that is not one of the chunk's keys (a naive or shifted datetime) raises
    return sum(1 for stamp, held in cur.fetchall() if held == inserted[stamp])


_NOT_COVERAGE = list(DAILY_NOT_COVERAGE_KINDS)

_REFRESH_1D_SQL = """
INSERT INTO ohlcv_coverage (symbol, timeframe, earliest_timestamp, latest_timestamp, row_count, provider)
SELECT symbol, '1d', min("timestamp"), max("timestamp"), count(DISTINCT "timestamp"), %s
FROM ohlcv_raw
WHERE vendor = %s AND timeframe = '1d' AND kind <> ALL(%s) AND symbol = ANY(%s)
GROUP BY symbol
ON CONFLICT (symbol, timeframe, provider) DO UPDATE SET
    earliest_timestamp = EXCLUDED.earliest_timestamp,
    latest_timestamp = EXCLUDED.latest_timestamp,
    row_count = EXCLUDED.row_count
"""


# A ledger row that states bounds or a row count for a series the provider holds no raw row of
# is stale state under that provider's label (a pre-191 Tradier-era 1d bound labeled ibkr): the
# row equals a direct count over the provider's own raw, which is zero. The upsert above only
# reaches series present in raw or in requests, so this zeroes the rest. Fetch status, the
# failure counter and last_fetched_at are untouched: they describe the fetcher's own outcomes.
_ZERO_NO_RAW_SQL = """
UPDATE ohlcv_coverage c
SET earliest_timestamp = NULL, latest_timestamp = NULL, row_count = 0
WHERE c.provider = %(provider)s {where}
  AND (c.row_count <> 0 OR c.earliest_timestamp IS NOT NULL OR c.latest_timestamp IS NOT NULL)
  AND NOT EXISTS (
      SELECT 1 FROM ohlcv_raw m
      WHERE m.symbol = c.symbol AND m.timeframe = c.timeframe AND m.vendor = c.provider
        AND NOT (m.timeframe = '1d' AND m.kind = ANY(%(not_coverage)s))
  )
"""


def refresh_1d_bounds(cur: Any, symbols: Iterable[str], *, provider: str = "ibkr") -> int:
    """Recompute the 1d bounds and row count of `symbols` from the provider's own raw rows of the
    kinds that cover a session (DAILY_NOT_COVERAGE_KINDS, the adjusted series, are left out).

    A 1d answer arrives as a daily observation, not a chunk, so no persist_chunk_atomically
    call moves a 1d series' bounds. The fetcher calls this after the symbols it fetched, so
    the queue's 1d staleness reads what this vendor holds. Counted in distinct session
    stamps (a vendor's listing-venue and adjusted kinds share a stamp). Recomputed, not
    widened: a vendor may restate a history. Fetch status and the failure counter are left to
    record_fetch_outcome. A symbol with no raw 1d row of the provider has its row zeroed (no
    bounds, no rows): the ledger never states bars the provider does not hold.
    Runs under SET LOCAL ROLE bar_derivation_writer. Returns rows written.
    """
    symbol_list = sorted(set(symbols))
    if not symbol_list:
        return 0
    cur.execute(_REFRESH_1D_SQL, (provider, provider, list(DAILY_NOT_COVERAGE_KINDS), symbol_list))
    written = int(cur.rowcount)
    cur.execute(
        _ZERO_NO_RAW_SQL.format(where="AND c.timeframe = '1d' AND c.symbol = ANY(%(symbols)s)"),
        {"provider": provider, "symbols": symbol_list, "not_coverage": _NOT_COVERAGE},
    )
    return written + int(cur.rowcount)


# The per-source aggregate: every row derives from this vendor's own ohlcv_raw rows, grouped by
# (symbol, timeframe), counted in distinct slots (one slot is one stamp whatever its kinds).
# {where} is either empty or a symbol filter; it is spliced into the raw scan so a scoped rebuild
# reads only its rows. The rebuilt rows carry the %(provider)s label, which is the raw vendor.
_REBUILD_SQL = """
INSERT INTO ohlcv_coverage (
    symbol, timeframe, earliest_timestamp, latest_timestamp, row_count,
    last_fetched_at, last_fetch_status, provider
)
WITH bars AS (
    SELECT symbol, timeframe,
           min("timestamp") AS earliest, max("timestamp") AS latest,
           count(DISTINCT "timestamp") AS n
    FROM ohlcv_raw
    WHERE vendor = %(provider)s AND NOT (timeframe = '1d' AND kind = ANY(%(not_coverage)s)) {where}
    GROUP BY symbol, timeframe
),
requests AS (
    SELECT DISTINCT ON (symbol, timeframe)
           symbol, timeframe, answered_at,
           __OUTCOME_CASE__ AS status
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
       r.status,
       %(provider)s
FROM bars b
FULL OUTER JOIN requests r
  ON r.symbol = b.symbol AND r.timeframe = b.timeframe
ON CONFLICT (symbol, timeframe, provider) DO UPDATE SET
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
_REBUILD_SQL = _REBUILD_SQL.replace("__OUTCOME_CASE__", _OUTCOME_CASE)
# Per-provider rebuild inputs: the provider's own request shape decides which ohlcv_request rows
# advance the fetch status. A provider whose requests are not recorded in ohlcv_request (the
# Alpaca loader writes none) advances nothing and keeps its stored status.
_REBUILD_FILTERS: dict[str, str] = {
    "ibkr": (
        "WHERE source = 'ibkr' AND route = 'SMART' AND what_to_show = 'TRADES' "
        f"AND outcome IN ({_OUTCOME_LIST})"
    ),
    "alpaca": f"WHERE source = 'alpaca' AND outcome IN ({_OUTCOME_LIST})",
}
REBUILD_PROVIDERS: tuple[str, ...] = tuple(_REBUILD_FILTERS)


def rebuild_from_stored_state(
    cur: Any, symbols: Iterable[str] | None = None, *, provider: str | None = None
) -> int:
    """Recompute every ledger row's bounds and row count from the provider's raw rows, in place.

    Migration 432 bootstrapped the ledger once with ON CONFLICT DO NOTHING, so a writer that
    stored bars without going through persist_chunk_atomically leaves rows stale or missing.
    This is the same aggregate over ohlcv_raw, per source: earliest, latest and row_count
    (distinct slots) are recomputed (not widened) from the rows of `vendor = provider`, whether
    or not another vendor's rows are canonical there; missing series are inserted, and a provider row
    with no raw row of its own is zeroed. The
    provider's own request shape (_REBUILD_FILTERS) advances last_fetched_at and
    last_fetch_status only when it is newer than what the ledger holds. `provider` None
    rebuilds every provider (REBUILD_PROVIDERS). An unknown provider raises before any SQL (a
    new provider's filter arrives with its leaf, never hand-written here).
    consecutive_failures is never touched: it counts the fetcher's own item outcomes.

    `symbols` scopes the rebuild (tests use a synthetic symbol); None rebuilds every series.
    Run under SET LOCAL ROLE bar_derivation_writer while holding the fetcher lock, so no
    persist_chunk_atomically delta can interleave. Returns rows inserted or updated.
    """
    if provider is None:
        symbol_arg = None if symbols is None else list(symbols)
        return sum(
            rebuild_from_stored_state(cur, symbol_arg, provider=name) for name in REBUILD_PROVIDERS
        )
    if provider not in _REBUILD_FILTERS:
        raise ValueError(
            f"unknown coverage provider {provider!r}; expected one of {sorted(_REBUILD_FILTERS)}"
        )
    request_filter = _REBUILD_FILTERS[provider]
    if symbols is None:
        sql = _REBUILD_SQL.format(where="", request_where=request_filter)
        cur.execute(sql, {"provider": provider, "not_coverage": _NOT_COVERAGE})
        written = int(cur.rowcount)
        cur.execute(
            _ZERO_NO_RAW_SQL.format(where=""),
            {"provider": provider, "not_coverage": _NOT_COVERAGE},
        )
        return written + int(cur.rowcount)
    symbol_list = sorted(set(symbols))
    if not symbol_list:
        return 0
    sql = _REBUILD_SQL.format(
        where="AND symbol = ANY(%(symbols)s)",
        request_where=f"{request_filter} AND symbol = ANY(%(symbols)s)",
    )
    cur.execute(sql, {"provider": provider, "symbols": symbol_list, "not_coverage": _NOT_COVERAGE})
    written = int(cur.rowcount)
    cur.execute(
        _ZERO_NO_RAW_SQL.format(where="AND c.symbol = ANY(%(symbols)s)"),
        {"provider": provider, "symbols": symbol_list, "not_coverage": _NOT_COVERAGE},
    )
    return written + int(cur.rowcount)


def reset_failures(cur: Any, symbol: str, timeframe: str | None, *, provider: str = "ibkr") -> int:
    """Zero consecutive_failures for a symbol (one timeframe, or all when None).

    The fetcher's --reset-failures path re-admits an excluded series to the queue; the
    counter is per-provider row state, so the reset is scoped to the provider's rows. Runs
    under SET LOCAL ROLE bar_derivation_writer. Returns the number of rows reset.
    """
    if timeframe is None:
        cur.execute(
            "UPDATE ohlcv_coverage SET consecutive_failures = 0 "
            "WHERE symbol = %s AND provider = %s",
            (symbol, provider),
        )
    else:
        cur.execute(
            "UPDATE ohlcv_coverage SET consecutive_failures = 0 "
            "WHERE symbol = %s AND timeframe = %s AND provider = %s",
            (symbol, timeframe, provider),
        )
    return cur.rowcount
