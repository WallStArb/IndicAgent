"""D1 append-only COPY writer for raw IBKR 1d observations (phase 185 plan 02, D-05).

ohlcv_request and ohlcv_observation are permanent: every later campaign appends its
raw answers here, and nothing ever rewrites them. This module is the one writer
shape: buffer request records and observations in memory, then COPY the requests
first (the observation FK holds inside one flush) and the observations after, inside
a single transaction whose first statement is SET LOCAL ROLE
ohlcv_observation_writer. UPDATE and DELETE do not exist here, by design and by
grants.

Record arguments are duck-typed and carry the RequestRecord contract (plan 03 adds
the dataclass to src/providers/base.py): request_id, fetch_run_id, symbol, timeframe,
route, what_to_show, primary_exchange, window_start, window_end, ib_req_id, outcome,
error_code, error_text, n_bars, client_id, requested_at, answered_at. caller and
source are sink-level facts (whose run this is, which vendor answered), not per-row
provider output, so they come from the constructor.

Buffer discipline: the sync sink auto-flushes once pending() reaches max_buffer_rows
(it owns its connection); the async sink's flush takes the caller's connection, so
its caller owns the same check (the APR key infra.ohlcv_observation.copy_batch_rows
is the source for that number). A failed flush leaves the buffers intact for retry.
"""

from __future__ import annotations

import math
import uuid as uuid_module
from datetime import UTC, datetime
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

_OBSERVATION_COLUMNS = (
    "request_id",
    "symbol",
    "timeframe",
    "bar_date",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "source",
    "route",
    "what_to_show",
    "fetched_at",
)

_ROLE = "ohlcv_observation_writer"

# Default = the migration 380 APR seed for infra.ohlcv_observation.copy_batch_rows;
# callers with ConfigService access should read the key and pass it instead.
_DEFAULT_MAX_BUFFER_ROWS = 50_000


def new_fetch_run_id() -> str:
    """One fetch_run_id per job invocation; TRADES and ADJUSTED_LAST pair only
    within one run (the pair is the seam audit's evidence, plan 15)."""
    return str(uuid_module.uuid4())


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


def _observation_rows(
    record: Any, bars: list[Any], *, source: str, fetched_at: datetime
) -> list[tuple]:
    """Validate and serialize one request's bars. D1 stores 1d only (D-02): an
    intraday record's requests are logged, never its bars."""
    if record.timeframe != "1d":
        raise ValueError(
            f"ohlcv_observation stores 1d only (D-02); got timeframe {record.timeframe!r} "
            f"for {record.symbol} request {record.request_id}"
        )
    rows: list[tuple] = []
    for bar in bars:
        for field in ("open", "high", "low", "close"):
            value = getattr(bar, field)
            if not math.isfinite(value):
                raise ValueError(
                    f"non-finite {field} {value!r} on bar {bar.timestamp!r} of request "
                    f"{record.request_id}; D1 stores raw answers, not placeholders"
                )
        # bar_date is the UTC date of the bar. A naive timestamp would make
        # astimezone() assume local time and silently shift bar_date a day, and
        # D1 rows are permanent (no UPDATE exists), so refuse it loudly.
        if bar.timestamp.tzinfo is None:
            raise ValueError(
                f"naive timestamp {bar.timestamp!r} on request {record.request_id}; "
                f"D1 bar_date requires tz-aware UTC stamps"
            )
        bar_date = bar.timestamp.astimezone(UTC).date()
        rows.append(
            (
                uuid_module.UUID(str(record.request_id)),
                record.symbol,
                "1d",
                bar_date,
                bar.open,
                bar.high,
                bar.low,
                bar.close,
                bar.volume,
                source,
                record.route,
                record.what_to_show,
                fetched_at,
            )
        )
    return rows


class _Buffer:
    """Shared request/observation buffer with the orphan guard (D-05: no
    observation without its request)."""

    def __init__(self, *, caller: str, source: str, max_buffer_rows: int) -> None:
        self._caller = caller
        self._source = source
        self._max_buffer_rows = max_buffer_rows
        self._requests: list[tuple] = []
        self._observations: list[tuple] = []
        self._seen_request_ids: set[uuid_module.UUID] = set()

    @property
    def max_buffer_rows(self) -> int:
        return self._max_buffer_rows

    @property
    def caller(self) -> str:
        return self._caller

    def add_request(self, record: Any) -> None:
        row = _request_row(record, caller=self._caller, source=self._source)
        self._requests.append(row)
        self._seen_request_ids.add(row[0])

    def add_observations(self, record: Any, bars: list[Any]) -> None:
        fetched_at = datetime.now(UTC)
        self._observations.extend(
            _observation_rows(record, bars, source=self._source, fetched_at=fetched_at)
        )

    def take_rows(self) -> tuple[list[tuple], list[tuple]]:
        """Return the buffered rows, refusing orphans: every observation's
        request must have been buffered by this sink at some point (a request
        flushed earlier still counts)."""
        orphaned = sorted(
            str(rid)
            for rid in {row[0] for row in self._observations}
            if rid not in self._seen_request_ids
        )
        if orphaned:
            raise ValueError(
                f"flush refused: {len(orphaned)} observation request_id(s) never "
                f"buffered in this sink (no orphan observations); first few: "
                f"{orphaned[:3]}"
            )
        return self._requests, self._observations

    def clear(self) -> None:
        self._requests = []
        self._observations = []

    def pending(self) -> int:
        return len(self._requests) + len(self._observations)


class ObservationSink:
    """Sync (psycopg 3) D1 writer: append-only COPY under the writer role."""

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

    def on_request(self, record: Any) -> None:
        self._buffer.add_request(record)
        if self._buffer.pending() >= self._buffer.max_buffer_rows:
            self.flush()

    def on_observation(self, record: Any, bars: list[Any]) -> None:
        self._buffer.add_observations(record, bars)
        if self._buffer.pending() >= self._buffer.max_buffer_rows:
            self.flush()

    def pending(self) -> int:
        return self._buffer.pending()

    def reconnect(self, conn: Any) -> None:
        """Swap in a fresh connection, keeping the buffered rows. The only
        buffer-preserving recovery when the old connection died mid-run (a new
        sink would drop unflushed rows); the caller supplies the replacement
        because the sink owns no connection factory."""
        self._conn = conn

    def flush(self) -> tuple[int, int]:
        requests, observations = self._buffer.take_rows()
        if not requests and not observations:
            return (0, 0)
        n_requests, n_observations = len(requests), len(observations)
        # SET LOCAL ROLE only reverts at a real transaction boundary. If the caller
        # already has a transaction open, conn.transaction() demotes to a savepoint
        # and the role leaks past the flush, leaving their connection unable to
        # UPDATE/DELETE anything. Refuse instead (caught live by the plan 02
        # integration test, 2026-09-27).
        if self._conn.info.transaction_status != psycopg.pq.TransactionStatus.IDLE:
            raise RuntimeError(
                "ObservationSink.flush requires an idle connection: an open caller "
                "transaction would trap SET LOCAL ROLE past the flush"
            )
        # Connection health next (a dead connection should fail here, not mid-COPY),
        # like the backfill's _persist_chunk guard; commit ends the check's own
        # implicit transaction so the write transaction below is top-level.
        with self._conn.cursor() as cur:
            cur.execute("SELECT 1")
        self._conn.commit()
        with self._conn.transaction():
            with self._conn.cursor() as cur:
                cur.execute(f"SET LOCAL ROLE {_ROLE}")
                if requests:
                    sql = f"COPY ohlcv_request ({', '.join(_REQUEST_COLUMNS)}) FROM STDIN"
                    with cur.copy(sql) as copy:
                        for row in requests:
                            copy.write_row(row)
                if observations:
                    sql = (
                        f"COPY ohlcv_observation ({', '.join(_OBSERVATION_COLUMNS)}) " "FROM STDIN"
                    )
                    with cur.copy(sql) as copy:
                        for row in observations:
                            copy.write_row(row)
        self._buffer.clear()
        logger.info(
            "ohlcv_observation_writer.flushed",
            caller=self._buffer.caller,
            n_requests=n_requests,
            n_observations=n_observations,
        )
        return (n_requests, n_observations)


class AsyncObservationSink:
    """Async (asyncpg) D1 writer: append-only COPY under the writer role. The
    connection arrives with flush (campaigns own their pool), so the caller also
    owns the max_buffer_rows flush check."""

    def __init__(
        self,
        *,
        caller: str,
        source: str = "ibkr",
        max_buffer_rows: int = _DEFAULT_MAX_BUFFER_ROWS,
    ) -> None:
        self._buffer = _Buffer(caller=caller, source=source, max_buffer_rows=max_buffer_rows)

    def on_request(self, record: Any) -> None:
        self._buffer.add_request(record)

    def on_observation(self, record: Any, bars: list[Any]) -> None:
        self._buffer.add_observations(record, bars)

    def pending(self) -> int:
        return self._buffer.pending()

    async def flush(self, conn: Any) -> tuple[int, int]:
        requests, observations = self._buffer.take_rows()
        if not requests and not observations:
            return (0, 0)
        n_requests, n_observations = len(requests), len(observations)
        # Same guard as the sync sink: asyncpg also demotes a nested transaction()
        # to a savepoint, which would trap SET LOCAL ROLE past the flush.
        if conn.is_in_transaction():
            raise RuntimeError(
                "AsyncObservationSink.flush requires an idle connection: an open "
                "caller transaction would trap SET LOCAL ROLE past the flush"
            )
        async with conn.transaction():
            await conn.execute(f"SET LOCAL ROLE {_ROLE}")
            if requests:
                await conn.copy_records_to_table(
                    "ohlcv_request", records=requests, columns=list(_REQUEST_COLUMNS)
                )
            if observations:
                await conn.copy_records_to_table(
                    "ohlcv_observation",
                    records=observations,
                    columns=list(_OBSERVATION_COLUMNS),
                )
        self._buffer.clear()
        logger.info(
            "ohlcv_observation_writer.flushed",
            caller=self._buffer.caller,
            n_requests=n_requests,
            n_observations=n_observations,
        )
        return (n_requests, n_observations)
