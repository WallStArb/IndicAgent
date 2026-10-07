"""Atomic request-and-bars persist for archive-bound fetch chunks (todo 462,
phase 185 plan 12; design: docs/plans/2026-09-29-intraday-bar-store-redesign.md).

Today's shape has the observation sink writing request rows from its own
connection while the chunk's bars commit from another, so a failed bar insert
leaves a request that looks answered. This helper writes both in ONE
transaction:

    BEGIN
      SET LOCAL ROLE ohlcv_observation_writer   -- the request rows
      <sink's write_request_rows COPY>
      SET LOCAL ROLE bar_derivation_writer      -- the archive rows
      <the destination's own insert, injected>
    COMMIT

so a recorded answer can never outrun its stored bars (T-185-12-07), and no
grant is added: both NOLOGIN roles already hold the grants they need
(migrations 380 and 383), and sequential SET LOCAL ROLE inside one top-level
transaction is the same verified pattern plan 11 uses.

Phase 189 (CD-03/CD-04, migration 432) adds an optional third write. When the
caller passes a CoverageDelta, the series' ohlcv_coverage row is upserted in
the same transaction, still under bar_derivation_writer:

    BEGIN
      SET LOCAL ROLE ohlcv_observation_writer   -- ohlcv_request rows
      write_request_rows(...)
      SET LOCAL ROLE bar_derivation_writer      -- archive/grid rows
      existing_timestamps(...)                  -- which offered rows are new
      write_archive_rows(...)
      upsert_coverage(...)                      -- coverage rollup
    COMMIT

so the coverage ledger can never describe bars that did not land.

Phase 185 plan 39 adds the ingress write contract and the request digest. Each request row that
answered with bars carries the content digest of the answer the chunk stored (design section 3,
direct mode provenance; src/intelligence/bars/digest.py arithmetic over the chunk's rows, one per
timestamp, last wins). The bar writers classify against the stored rows (see
services/ohlcv_ingress_contract.py); a chunk they refuse raises RevisionRefused, this helper rolls
the transaction back, then records the request rows (digest NULL: nothing was stored) and an
ohlcv_load row with outcome refused in a second transaction and re-raises, so the item fails
loudly (phase 189's failure path and max_consecutive_failures) and the refusal is a finding.

Without a CoverageDelta (the default) the helper issues exactly the two writes above and
nothing else, so callers that predate the ledger are unchanged.

Discipline the caller owes:

- The helper demands an idle connection, exactly like the observation sink's
  flush, and a flush is NEVER called inside the helper's transaction (a flush
  opens its own and would trap the SET LOCAL ROLE). If the sink holds other
  pending rows (1d observations from the same run), the caller flushes them
  on the idle connection before or after this helper, never between.
- The request rows arrive as data: the caller pulled them off the sink buffer
  via the sink's public take_requests method, so the helper never touches the
  sink and ohlcv_request keeps one INSERT definition (the sink's
  write_request_rows, imported here).
- The destination is injected: write_archive_rows is the bar table's own
  write function (services/intraday_raw_archive.insert_fetched_archive_rows
  for the 15m/1h archive path; the pipeline's 5m store function when plan 18
  reuses this helper for 5m). The helper owns no INSERT for any bar table.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import numpy as np
import psycopg

from services.ohlcv_coverage_writer import (
    DESTINATION_GRID,
    CoverageDelta,
    existing_timestamps,
    upsert_coverage,
)
from services.ohlcv_ingress_contract import RevisionRefused, record_refused_load
from services.ohlcv_observation_writer import write_request_rows
from src.intelligence.bars.digest import bar_content_digest

_REQUEST_ROLE = "ohlcv_observation_writer"
# bar_derivation_writer holds INSERT on ohlcv_intraday_raw_archive per
# migration 383; it is the bar-writer role, not a second archive owner.
_ARCHIVE_ROLE = "bar_derivation_writer"


def persist_chunk_atomically(
    conn: Any,
    *,
    request_rows: list[tuple],
    archive_rows: list[tuple],
    write_archive_rows: Callable[[Any, list[tuple]], int],
    coverage: CoverageDelta | None = None,
) -> tuple[int, int]:
    """Commit one fetched chunk's request rows, its bar rows and (when `coverage`
    is given) its ohlcv_coverage update together.

    Returns (n_request_rows, n_bar_rows). Raises with the transaction rolled
    back if any write fails: no answer is recorded without its bars, no bars
    land without their answer, and the ledger never moves without both.
    """
    if not request_rows and not archive_rows:
        return (0, 0)
    if coverage is not None:
        _check_rows_match_series(archive_rows, coverage)
    if conn.info.transaction_status != psycopg.pq.TransactionStatus.IDLE:
        raise RuntimeError(
            "persist_chunk_atomically requires an idle connection: an open caller "
            "transaction would demote this to a savepoint and trap SET LOCAL ROLE"
        )
    stamped = [_with_digest(row, archive_rows) for row in request_rows]
    try:
        with conn.transaction():
            with conn.cursor() as cur:
                if stamped:
                    cur.execute(f"SET LOCAL ROLE {_REQUEST_ROLE}")
                    write_request_rows(cur, stamped)
                if archive_rows:
                    cur.execute(f"SET LOCAL ROLE {_ARCHIVE_ROLE}")
                    if coverage is None:
                        write_archive_rows(cur, archive_rows)
                    else:
                        _write_bars_and_coverage(cur, archive_rows, write_archive_rows, coverage)
    except RevisionRefused as refusal:
        _record_refusal(conn, request_rows, refusal)
        raise
    return len(request_rows), len(archive_rows)


# ohlcv_request row layout (services/ohlcv_observation_writer._REQUEST_COLUMNS).
_REQ_OUTCOME, _REQ_N_BARS, _REQUEST_COLUMNS_WITHOUT_DIGEST = 11, 14, 19


def chunk_digest(rows: list[tuple]) -> str:
    """Content digest of the answer a chunk offers: one row per timestamp (last wins), the
    bar content digest arithmetic with no quarantine rules (the ingress rows carry none)."""
    keyed = {row[_TS]: row for row in rows}
    ordered = [keyed[ts] for ts in sorted(keyed)]
    return bar_content_digest(
        np.array([ts.timestamp() for ts in sorted(keyed)], dtype=np.int64),
        np.array([row[3] for row in ordered], dtype=np.float64),
        np.array([row[4] for row in ordered], dtype=np.float64),
        np.array([row[5] for row in ordered], dtype=np.float64),
        np.array([row[6] for row in ordered], dtype=np.float64),
        np.array([row[_VOLUME] for row in ordered], dtype=np.float64),
        [() for _ in ordered],
    )


def _with_digest(request_row: tuple, bar_rows: list[tuple]) -> tuple:
    """The request row with its content digest appended: the chunk's digest when the request
    answered with bars, NULL otherwise."""
    if len(request_row) != _REQUEST_COLUMNS_WITHOUT_DIGEST:
        raise ValueError(
            f"request rows reach the persist helper without a digest column "
            f"({_REQUEST_COLUMNS_WITHOUT_DIGEST} values); got {len(request_row)}"
        )
    has_bars = request_row[_REQ_OUTCOME] == "bars" and request_row[_REQ_N_BARS] > 0
    return request_row + ((chunk_digest(bar_rows) if has_bars and bar_rows else None),)


def _record_refusal(conn: Any, request_rows: list[tuple], refusal: RevisionRefused) -> None:
    """Second transaction after a refused chunk rolled back: the answers are still recorded
    (digest NULL, no bar was stored) and the load row says why nothing was written."""
    with conn.transaction():
        with conn.cursor() as cur:
            if request_rows:
                cur.execute(f"SET LOCAL ROLE {_REQUEST_ROLE}")
                write_request_rows(cur, [row + (None,) for row in request_rows])
            cur.execute(f"SET LOCAL ROLE {_ARCHIVE_ROLE}")
            record_refused_load(cur, refusal)


# Bar row layout shared by the archive 10-tuple and the market_data_ohlcv 9-tuple.
_TS, _SYMBOL, _TIMEFRAME, _VOLUME = 0, 1, 2, 7


def _check_rows_match_series(rows: list[tuple], coverage: CoverageDelta) -> None:
    """Refuse, before any SQL, a chunk holding rows for a series other than the
    one its coverage update names: the ledger would silently credit the wrong row."""
    series = {(row[_SYMBOL], row[_TIMEFRAME]) for row in rows}
    if series - {(coverage.symbol, coverage.timeframe)}:
        raise ValueError(
            f"chunk rows span series {sorted(series)} but the coverage update names "
            f"({coverage.symbol!r}, {coverage.timeframe!r})"
        )


def _write_bars_and_coverage(
    cur: Any,
    rows: list[tuple],
    write_archive_rows: Callable[[Any, list[tuple]], int],
    coverage: CoverageDelta,
) -> None:
    """Bar insert plus the coverage upsert, under the bar-writer role already set.

    The bar writers (the ingress write contract) return rows offered, not rows
    written, so the stored-before set is read first and only genuinely new timestamps are
    counted.
    The grid counts tradeable rows only (volume > 0), matching the
    market_data_ohlcv_tradeable bootstrap; the archive counts every new row.
    """
    stored = existing_timestamps(
        cur,
        coverage.destination,
        coverage.symbol,
        coverage.timeframe,
        sorted({row[_TS] for row in rows}),
    )
    write_archive_rows(cur, rows)
    tradeable_only = coverage.destination == DESTINATION_GRID
    new_timestamps = {
        row[_TS]
        for row in rows
        if row[_TS] not in stored and (not tradeable_only or (row[_VOLUME] or 0) > 0)
    }
    # Bounds follow the counted rows; when none are new they still reflect the
    # offered rows, which are stored either way.
    bounds = new_timestamps or {row[_TS] for row in rows}
    upsert_coverage(
        cur,
        coverage,
        earliest=min(bounds),
        latest=max(bounds),
        n_new_rows=len(new_timestamps),
    )
