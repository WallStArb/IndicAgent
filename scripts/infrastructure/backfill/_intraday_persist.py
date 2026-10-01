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

import psycopg

from services.ohlcv_observation_writer import write_request_rows

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
) -> tuple[int, int]:
    """Commit one fetched chunk's request rows and its bar rows together.

    Returns (n_request_rows, n_bar_rows). Raises with the transaction rolled
    back if either side fails: no answer is recorded without its bars, and no
    bars land without their answer.
    """
    if not request_rows and not archive_rows:
        return (0, 0)
    if conn.info.transaction_status != psycopg.pq.TransactionStatus.IDLE:
        raise RuntimeError(
            "persist_chunk_atomically requires an idle connection: an open caller "
            "transaction would demote this to a savepoint and trap SET LOCAL ROLE"
        )
    with conn.transaction():
        with conn.cursor() as cur:
            if request_rows:
                cur.execute(f"SET LOCAL ROLE {_REQUEST_ROLE}")
                write_request_rows(cur, request_rows)
            if archive_rows:
                cur.execute(f"SET LOCAL ROLE {_ARCHIVE_ROLE}")
                write_archive_rows(cur, archive_rows)
    return len(request_rows), len(archive_rows)
