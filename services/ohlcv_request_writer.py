"""The fetch ledger writer: ohlcv_request rows, COPY under the writer role (phase 191 plan 02).

`ohlcv_request` stays after `ohlcv_observation` folds into `ohlcv_raw` (design doc, Fetch ledger):
answered and `no_data` windows cannot be read off bars. This module is the request half of
services/ohlcv_observation_writer.py, ported without the observation buffer, the observation COPY
and the D1 elision. Until plan 05 stops the fetcher importing the old module and plan 16 deletes it,
both write ohlcv_request (a deliberate, registered duplication).

Buffer request records in memory, then COPY them inside one transaction whose first statement is
SET LOCAL ROLE ohlcv_observation_writer (the role name is kept: a role rename is a migration with
no benefit). UPDATE and DELETE do not exist here, by design and by grants.

Record arguments are duck-typed and carry the RequestRecord contract: request_id, fetch_run_id,
symbol, timeframe, route, what_to_show, primary_exchange, window_start, window_end, ib_req_id,
outcome, error_code, error_text, n_bars, client_id, requested_at, answered_at. caller and source
are sink-level facts (whose run this is, which vendor answered).

Buffer discipline: the sync sink auto-flushes once pending() reaches max_buffer_rows (it owns its
connection); the async sink's flush takes the caller's connection, so its caller owns the same
check (APR key infra.ohlcv_observation.copy_batch_rows). A failed flush restores the
rows it took, in order; the buffer is handed over by swap, so a request added while a flush is
awaiting its COPY is kept (review of 191-01..03, finding 12).
"""

from __future__ import annotations

import uuid as uuid_module
from typing import Any

import psycopg
import structlog

logger = structlog.get_logger(__name__)

_REQUEST_COLUMNS = (
    "request_id",
    "fetch_run_id",
    "symbol",
    "timeframe",
    "source",
    "route",
    "what_to_show",
    "primary_exchange",
    "window_start",
    "window_end",
    "ib_req_id",
    "outcome",
    "error_code",
    "error_text",
    "n_bars",
    "client_id",
    "caller",
    "requested_at",
    "answered_at",
)

# The content digest of the answer a chunk stored, an optional 20th value on a request row; the
# sink's own 19-value rows leave it NULL.
_DIGEST_COLUMN = "content_digest"

_ROLE = "ohlcv_observation_writer"

# Which of these request_ids already exist: asked once after a flush whose COMMIT outcome is
# unknown (the COPY ran, then the transaction exit raised), before the restored rows are written.
_EXISTING_SQL = "SELECT request_id FROM ohlcv_request WHERE request_id = ANY(%s)"
_EXISTING_SQL_ASYNC = "SELECT request_id FROM ohlcv_request WHERE request_id = ANY($1::uuid[])"

# Default = the migration 380 APR seed for infra.ohlcv_observation.copy_batch_rows; callers with
# ConfigService access should read the key and pass it instead.
_DEFAULT_MAX_BUFFER_ROWS = 50_000


def new_fetch_run_id() -> str:
    """One fetch_run_id per job invocation; TRADES and ADJUSTED_LAST pair only within one run."""
    return str(uuid_module.uuid4())


def write_request_rows(cur: Any, rows: list[tuple]) -> None:
    """The one ohlcv_request row-writing shape: COPY under the writer role.

    The sink's flush path and the backfill persist helper (the atomic request-and-bars
    transaction) both go through this function, so the table keeps one INSERT definition.
    """
    columns = _REQUEST_COLUMNS
    widths = {len(row) for row in rows} or {len(_REQUEST_COLUMNS)}
    if widths == {len(_REQUEST_COLUMNS) + 1}:
        columns = (*_REQUEST_COLUMNS, _DIGEST_COLUMN)
    elif widths != {len(_REQUEST_COLUMNS)}:
        raise ValueError(
            f"request rows must all have {len(_REQUEST_COLUMNS)} values or all "
            f"{len(_REQUEST_COLUMNS) + 1} (with content_digest); got widths {sorted(widths)}"
        )
    sql = f"COPY ohlcv_request ({', '.join(columns)}) FROM STDIN"
    with cur.copy(sql) as copy:
        for row in rows:
            copy.write_row(row)


def _request_row(record: Any, *, caller: str, source: str) -> tuple:
    return (
        uuid_module.UUID(str(record.request_id)),
        uuid_module.UUID(str(record.fetch_run_id)),
        record.symbol,
        record.timeframe,
        source,
        record.route,
        record.what_to_show,
        record.primary_exchange,
        record.window_start,
        record.window_end,
        record.ib_req_id,
        record.outcome,
        record.error_code,
        record.error_text,
        record.n_bars,
        record.client_id,
        caller,
        record.requested_at,
        record.answered_at,
    )


class _Buffer:
    """The request buffer shared by the sync and async sinks."""

    def __init__(self, *, caller: str, source: str, max_buffer_rows: int) -> None:
        self._caller = caller
        self._source = source
        self._max_buffer_rows = max_buffer_rows
        self._requests: list[tuple] = []

    @property
    def max_buffer_rows(self) -> int:
        return self._max_buffer_rows

    @property
    def caller(self) -> str:
        return self._caller

    def add_request(self, record: Any) -> None:
        self._requests.append(_request_row(record, caller=self._caller, source=self._source))

    def take_rows(self) -> list[tuple]:
        """Hand the buffered rows over and start a fresh buffer in one step, so a request added
        while a flush awaits its COPY lands in the new buffer and survives. A failed flush gives
        the rows back through `restore`."""
        rows, self._requests = self._requests, []
        return rows

    def restore(self, rows: list[tuple]) -> None:
        """Put rows a failed flush could not write back ahead of anything added since."""
        self._requests = rows + self._requests

    def take_requests(self, request_ids: Any) -> list[tuple]:
        """Remove and return the buffered rows whose request_id is in `request_ids`, keeping
        every other buffered row for the normal flush (the atomic persist helper commits a
        fetched chunk's request rows together with that chunk's bars)."""
        wanted = {str(rid) for rid in request_ids}
        if not wanted:
            return []
        taken: list[tuple] = []
        kept: list[tuple] = []
        for row in self._requests:
            (taken if str(row[0]) in wanted else kept).append(row)
        self._requests = kept
        return taken

    def pending(self) -> int:
        return len(self._requests)


class RequestSink:
    """Sync (psycopg 3) fetch ledger writer: append-only COPY under the writer role."""

    def __init__(
        self,
        conn: Any,
        *,
        caller: str,
        source: str = "ibkr",
        max_buffer_rows: int = _DEFAULT_MAX_BUFFER_ROWS,
    ) -> None:
        self._conn = conn
        self._buffer = _Buffer(caller=caller, source=source, max_buffer_rows=max_buffer_rows)
        # The last flush failed after its COPY ran: the server may have committed those rows.
        self._commit_unknown = False

    def on_request(self, record: Any) -> None:
        self._buffer.add_request(record)
        if self._buffer.pending() >= self._buffer.max_buffer_rows:
            self.flush()

    def pending(self) -> int:
        return self._buffer.pending()

    def take_requests(self, request_ids: Any) -> list[tuple]:
        """Hand over the buffered rows for `request_ids` WITHOUT flushing."""
        return self._buffer.take_requests(request_ids)

    def reconnect(self, conn: Any) -> None:
        """Swap in a fresh connection, keeping the buffered rows (the only buffer-preserving
        recovery when the old connection died mid-run)."""
        self._conn = conn

    def _without_written(self, requests: list[tuple]) -> list[tuple]:
        """Drop the rows the server already holds (a flush whose COMMIT outcome was unknown)."""
        with self._conn.cursor() as cur:
            cur.execute(_EXISTING_SQL, ([row[0] for row in requests],))
            existing = {str(r[0]) for r in cur.fetchall()}
        self._conn.commit()
        return [row for row in requests if str(row[0]) not in existing]

    def flush(self) -> int:
        """Write the buffered request rows; return how many (rows an ambiguous earlier commit
        already wrote are not written again and not counted)."""
        requests = self._buffer.take_rows()
        if not requests:
            return 0
        copied = False
        try:
            # SET LOCAL ROLE only reverts at a real transaction boundary. A caller transaction
            # already open would demote conn.transaction() to a savepoint and leak the role.
            if self._conn.info.transaction_status != psycopg.pq.TransactionStatus.IDLE:
                raise RuntimeError(
                    "RequestSink.flush requires an idle connection: an open caller "
                    "transaction would trap SET LOCAL ROLE past the flush"
                )
            # Connection health first (a dead connection fails here, not mid-COPY); commit ends
            # the check's own implicit transaction so the write transaction below is top-level.
            with self._conn.cursor() as cur:
                cur.execute("SELECT 1")
            self._conn.commit()
            if self._commit_unknown:
                requests = self._without_written(requests)
                self._commit_unknown = bool(requests)
            if requests:
                with self._conn.transaction():
                    with self._conn.cursor() as cur:
                        cur.execute(f"SET LOCAL ROLE {_ROLE}")
                        write_request_rows(cur, requests)
                    copied = True
        except BaseException:
            self._buffer.restore(requests)
            if copied:
                self._commit_unknown = True
            raise
        self._commit_unknown = False
        n_requests = len(requests)
        logger.info(
            "ohlcv_request_writer.flushed", caller=self._buffer.caller, n_requests=n_requests
        )
        return n_requests


class AsyncRequestSink:
    """Async (asyncpg) fetch ledger writer. The connection arrives with flush (campaigns own their
    pool), so the caller also owns the max_buffer_rows flush check."""

    def __init__(
        self,
        *,
        caller: str,
        source: str = "ibkr",
        max_buffer_rows: int = _DEFAULT_MAX_BUFFER_ROWS,
    ) -> None:
        self._buffer = _Buffer(caller=caller, source=source, max_buffer_rows=max_buffer_rows)
        self._commit_unknown = False  # as RequestSink: the last flush failed after its COPY

    def on_request(self, record: Any) -> None:
        self._buffer.add_request(record)

    def pending(self) -> int:
        return self._buffer.pending()

    async def flush(self, conn: Any) -> int:
        requests = self._buffer.take_rows()
        if not requests:
            return 0
        copied = False
        try:
            # asyncpg also demotes a nested transaction() to a savepoint, which would trap the role.
            if conn.is_in_transaction():
                raise RuntimeError(
                    "AsyncRequestSink.flush requires an idle connection: an open "
                    "caller transaction would trap SET LOCAL ROLE past the flush"
                )
            if self._commit_unknown:
                found = await conn.fetch(_EXISTING_SQL_ASYNC, [row[0] for row in requests])
                existing = {str(r[0]) for r in found}
                requests = [row for row in requests if str(row[0]) not in existing]
                self._commit_unknown = bool(requests)
            if requests:
                async with conn.transaction():
                    await conn.execute(f"SET LOCAL ROLE {_ROLE}")
                    await conn.copy_records_to_table(
                        "ohlcv_request", records=requests, columns=list(_REQUEST_COLUMNS)
                    )
                    copied = True
        except BaseException:
            self._buffer.restore(requests)
            if copied:
                self._commit_unknown = True
            raise
        self._commit_unknown = False
        n_requests = len(requests)
        logger.info(
            "ohlcv_request_writer.flushed", caller=self._buffer.caller, n_requests=n_requests
        )
        return n_requests
