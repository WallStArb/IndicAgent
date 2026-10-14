"""Unit tests for the fetch ledger writer (phase 191 plan 02), all against fakes -- no DB.

Ported from the request half of test_ohlcv_observation_writer.py; the observation tests stay with
the old module until plan 16.

The fake psycopg connection/cursor records executed statements (with an
inside-transaction flag) and COPY targets with their write_row rows in call order, so
the tests assert the load-bearing ordering properties: requests before observations,
SET LOCAL ROLE as the transaction's first statement, and no SQL before validation
raises.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace

import psycopg
import pytest

from services.ohlcv_request_writer import (
    AsyncRequestSink,
    RequestSink,
    new_fetch_run_id,
    write_request_rows,
)


def _record(
    fetch_run_id: str,
    request_id: str,
    *,
    timeframe: str = "1d",
    outcome: str = "bars",
    n_bars: int = 3,
) -> SimpleNamespace:
    now = datetime.now(UTC)
    return SimpleNamespace(
        request_id=request_id,
        fetch_run_id=fetch_run_id,
        symbol="SPY",
        timeframe=timeframe,
        route="SMART",
        what_to_show="TRADES",
        primary_exchange="NYSE",
        window_start=None,
        window_end=now,
        ib_req_id=None,
        outcome=outcome,
        error_code=None,
        error_text=None,
        n_bars=n_bars,
        client_id=None,
        requested_at=now,
        answered_at=now,
    )


class _RecordingCopy:
    def __init__(self, statements: list, copies: list, sql: str) -> None:
        self._statements = statements
        self._copies = copies
        self._sql = sql
        self.rows: list[tuple] = []

    def write_row(self, row: tuple) -> None:
        self.rows.append(tuple(row))

    def __enter__(self) -> _RecordingCopy:
        return self

    def __exit__(self, *exc: object) -> bool:
        self._copies.append((self._sql, self.rows))
        return False


class FakeCursor:
    def __init__(self, conn: FakeConnection) -> None:
        self._conn = conn

    def __enter__(self) -> FakeCursor:
        return self

    def __exit__(self, *exc: object) -> bool:
        return False

    def execute(self, sql: str, params: object = None) -> None:
        self._conn.statements.append((sql, self._conn.in_transaction))
        self._conn.params.append(params)

    def fetchall(self) -> list[tuple]:
        return self._conn.latest_rows

    def copy(self, sql: str) -> _RecordingCopy:
        self._conn.statements.append((sql, self._conn.in_transaction))
        return _RecordingCopy(self._conn.statements, self._conn.copies, sql)


class _FakeTransaction:
    def __init__(self, conn: FakeConnection) -> None:
        self._conn = conn

    def __enter__(self) -> None:
        self._conn.in_transaction = True

    def __exit__(self, *exc: object) -> bool:
        self._conn.in_transaction = False
        return False


class FakeConnection:
    def __init__(self) -> None:
        self.statements: list[tuple[str, bool]] = []
        self.copies: list[tuple[str, list[tuple]]] = []
        self.params: list[object] = []
        self.latest_rows: list[tuple] = []  # what the elision read returns (stored latest)
        self.in_transaction = False
        self.commits = 0
        self.transaction_status = psycopg.pq.TransactionStatus.IDLE

    @property
    def info(self) -> SimpleNamespace:
        return SimpleNamespace(transaction_status=self.transaction_status)

    def commit(self) -> None:
        self.commits += 1

    def cursor(self) -> FakeCursor:
        return FakeCursor(self)

    def transaction(self) -> _FakeTransaction:
        return _FakeTransaction(self)


class _FakeAsyncTransaction:
    def __init__(self, conn: FakeAsyncConnection) -> None:
        self._conn = conn

    async def __aenter__(self) -> None:
        self._conn.in_transaction = True

    async def __aexit__(self, *exc: object) -> bool:
        self._conn.in_transaction = False
        return False


class FakeAsyncConnection:
    def __init__(self) -> None:
        self.statements: list[str] = []
        self.copies: list[tuple[str, list[tuple]]] = []
        self.latest_rows: list[tuple] = []
        self.fetch_args: list[tuple] = []
        self.in_transaction = False
        self.open_transaction = False

    def is_in_transaction(self) -> bool:
        return self.open_transaction

    def transaction(self) -> _FakeAsyncTransaction:
        return _FakeAsyncTransaction(self)

    async def execute(self, sql: str) -> None:
        self.statements.append(sql)

    async def fetch(self, sql: str, *args: object) -> list[tuple]:
        self.statements.append(sql)
        self.fetch_args.append(args)
        return self.latest_rows

    async def copy_records_to_table(self, table_name: str, *, records: list, columns: list) -> None:
        self.copies.append((table_name, [tuple(r) for r in records]))


def test_request_sink_new_fetch_run_id_is_a_uuid_string():
    uuid.UUID(new_fetch_run_id())


def _sink(conn=None, **kw):
    conn = conn or FakeConnection()
    return conn, RequestSink(conn, caller="unit-test", **kw)


def test_flush_copies_only_requests_and_returns_their_count():
    conn, sink = _sink()
    sink.on_request(_record(new_fetch_run_id(), str(uuid.uuid4())))
    sink.on_request(_record(new_fetch_run_id(), str(uuid.uuid4())))
    assert sink.pending() == 2
    assert sink.flush() == 2
    assert [sql.split()[1] for sql, _ in conn.copies] == ["ohlcv_request"]
    assert not any("ohlcv_observation " in sql for sql, _ in conn.statements)
    assert sink.pending() == 0
    assert sink.flush() == 0  # empty flush issues no SQL
    assert len(conn.copies) == 1


def test_request_sink_flush_first_statement_in_transaction_is_set_local_role():
    conn, sink = _sink()
    sink.on_request(_record(new_fetch_run_id(), str(uuid.uuid4())))
    sink.flush()
    assert conn.statements[0] == ("SELECT 1", False)
    assert [sql for sql, inside in conn.statements if inside][0] == (
        "SET LOCAL ROLE ohlcv_observation_writer"
    )
    assert conn.commits == 1


def test_request_sink_sync_sink_auto_flushes_at_max_buffer_rows():
    conn, sink = _sink(max_buffer_rows=2)
    sink.on_request(_record(new_fetch_run_id(), str(uuid.uuid4())))
    assert conn.copies == []
    sink.on_request(_record(new_fetch_run_id(), str(uuid.uuid4())))
    assert len(conn.copies) == 1 and sink.pending() == 0


def test_request_sink_sync_flush_refuses_an_open_caller_transaction():
    conn, sink = _sink()
    conn.transaction_status = psycopg.pq.TransactionStatus.INTRANS
    sink.on_request(_record(new_fetch_run_id(), str(uuid.uuid4())))
    with pytest.raises(RuntimeError, match="idle connection"):
        sink.flush()
    assert conn.copies == [] and sink.pending() == 1


def test_reconnect_keeps_the_buffer():
    _, sink = _sink()
    sink.on_request(_record(new_fetch_run_id(), str(uuid.uuid4())))
    fresh = FakeConnection()
    sink.reconnect(fresh)
    assert sink.flush() == 1 and len(fresh.copies) == 1


@pytest.mark.asyncio
async def test_async_flush_role_first_then_requests():
    conn = FakeAsyncConnection()
    sink = AsyncRequestSink(caller="unit-test")
    sink.on_request(_record(new_fetch_run_id(), str(uuid.uuid4())))
    assert await sink.flush(conn) == 1
    assert conn.statements[0] == "SET LOCAL ROLE ohlcv_observation_writer"
    assert [table for table, _ in conn.copies] == ["ohlcv_request"]
    assert await sink.flush(conn) == 0


@pytest.mark.asyncio
async def test_async_sink_does_not_auto_flush_and_refuses_open_transaction():
    conn = FakeAsyncConnection()
    sink = AsyncRequestSink(caller="unit-test", max_buffer_rows=1)
    sink.on_request(_record(new_fetch_run_id(), str(uuid.uuid4())))
    assert sink.pending() == 1 and conn.copies == []
    conn.open_transaction = True
    with pytest.raises(RuntimeError, match="idle connection"):
        await sink.flush(conn)


def test_request_sink_take_requests_removes_only_the_wanted_rows_and_keeps_the_rest():
    conn, sink = _sink()
    run = new_fetch_run_id()
    chunk_a = _record(run, str(uuid.uuid4()), timeframe="15m")
    chunk_b = _record(run, str(uuid.uuid4()), timeframe="15m")
    sink.on_request(chunk_a)
    sink.on_request(chunk_b)
    taken = sink.take_requests([chunk_a.request_id])
    assert [row[0] for row in taken] == [uuid.UUID(str(chunk_a.request_id))]
    assert sink.pending() == 1
    assert sink.flush() == 1
    assert {row[0] for row in conn.copies[0][1]} == {uuid.UUID(str(chunk_b.request_id))}


def test_request_sink_take_requests_with_no_match_returns_empty_and_changes_nothing():
    _, sink = _sink()
    sink.on_request(_record(new_fetch_run_id(), str(uuid.uuid4())))
    assert sink.take_requests([str(uuid.uuid4())]) == []
    assert sink.take_requests([]) == []
    assert sink.pending() == 1


def test_request_sink_taken_requests_never_flush_twice():
    conn, sink = _sink()
    record = _record(new_fetch_run_id(), str(uuid.uuid4()))
    sink.on_request(record)
    assert len(sink.take_requests([record.request_id])) == 1
    assert sink.flush() == 0 and conn.copies == []


def _request_values(n: int = 20) -> tuple:
    return tuple(range(n))


def test_request_sink_write_request_rows_without_a_digest_copies_the_original_columns():
    conn = FakeConnection()
    write_request_rows(conn.cursor(), [_request_values(20)])
    sql, rows = conn.copies[0]
    assert "content_digest" not in sql and sql.count(",") == 19
    assert "answered_at, partial_bars)" in sql
    assert rows == [_request_values(20)]


def test_request_sink_write_request_rows_with_a_digest_adds_the_column():
    conn = FakeConnection()
    write_request_rows(conn.cursor(), [_request_values(21)])
    sql, rows = conn.copies[0]
    assert sql.startswith("COPY ohlcv_request (") and sql.count(",") == 20
    assert "partial_bars, content_digest)" in sql
    assert rows == [_request_values(21)]


def test_a_buffered_request_row_carries_its_partial_bars_and_defaults_to_null():
    """Migration 479 (finding 5): the fetch layer notes an answer's incomplete bars on the
    request row before it leaves the buffer; every other row writes NULL."""
    conn = FakeConnection()
    sink = RequestSink(conn, caller="unit-test")
    run = new_fetch_run_id()
    noted, plain = _record(run, str(uuid.uuid4())), _record(run, str(uuid.uuid4()))
    sink.on_request(noted)
    sink.on_request(plain)
    sink.note_partial(noted.request_id, '[{"t": "2026-10-12T19:55:00+00:00"}]')
    rows = {str(row[0]): row for row in sink.take_requests([noted.request_id, plain.request_id])}
    assert rows[noted.request_id][-1] == '[{"t": "2026-10-12T19:55:00+00:00"}]'
    assert rows[plain.request_id][-1] is None
    assert len(rows[plain.request_id]) == 20


def test_noting_partial_bars_on_a_request_no_longer_buffered_is_loud():
    sink = RequestSink(FakeConnection(), caller="unit-test")
    with pytest.raises(LookupError, match="not buffered"):
        sink.note_partial(str(uuid.uuid4()), "[]")


def test_request_sink_write_request_rows_refuses_mixed_widths_before_any_sql():
    conn = FakeConnection()
    with pytest.raises(ValueError, match="all"):
        write_request_rows(conn.cursor(), [_request_values(20), _request_values(21)])
    assert conn.statements == []


# --- buffer handover (phase 191 plan 05, review finding 12) ---------------------------------


class _AppendDuringCopyConnection(FakeAsyncConnection):
    """A request arriving while the flush awaits its COPY."""

    def __init__(self, sink: AsyncRequestSink, late: SimpleNamespace) -> None:
        super().__init__()
        self._sink, self._late = sink, late

    async def copy_records_to_table(self, table_name: str, *, records: list, columns: list) -> None:
        self._sink.on_request(self._late)
        await super().copy_records_to_table(table_name, records=records, columns=columns)


@pytest.mark.asyncio
async def test_async_flush_keeps_a_request_added_while_the_copy_is_awaited():
    sink = AsyncRequestSink(caller="unit-test")
    late = _record(new_fetch_run_id(), str(uuid.uuid4()))
    conn = _AppendDuringCopyConnection(sink, late)
    sink.on_request(_record(new_fetch_run_id(), str(uuid.uuid4())))
    assert await sink.flush(conn) == 1
    assert sink.pending() == 1  # the late row survives the post-COPY bookkeeping
    assert await sink.flush(FakeAsyncConnection()) == 1


@pytest.mark.asyncio
async def test_async_flush_failure_restores_the_taken_rows_ahead_of_newer_ones():
    class Failing(FakeAsyncConnection):
        async def copy_records_to_table(self, *a: object, **k: object) -> None:
            raise OSError("copy failed")

    sink = AsyncRequestSink(caller="unit-test")
    first = _record(new_fetch_run_id(), str(uuid.uuid4()))
    sink.on_request(first)
    with pytest.raises(OSError):
        await sink.flush(Failing())
    assert sink.pending() == 1
    ok = FakeAsyncConnection()
    assert await sink.flush(ok) == 1
    assert ok.copies[0][1][0][0] == uuid.UUID(str(first.request_id))


def test_sync_flush_failure_keeps_the_buffer_in_order():
    conn, sink = _sink()
    first = _record(new_fetch_run_id(), str(uuid.uuid4()))
    conn.transaction_status = psycopg.pq.TransactionStatus.INTRANS
    sink.on_request(first)
    with pytest.raises(RuntimeError):
        sink.flush()
    sink.on_request(_record(new_fetch_run_id(), str(uuid.uuid4())))
    conn.transaction_status = psycopg.pq.TransactionStatus.IDLE
    assert sink.flush() == 2
    assert conn.copies[0][1][0][0] == uuid.UUID(str(first.request_id))


class _CommitLostConnection(FakeConnection):
    """The COPY ran, then the transaction exit (the COMMIT) raised: the server may have committed."""

    def __init__(self) -> None:
        super().__init__()
        self.lose_commit = True

    def transaction(self) -> _FakeTransaction:
        conn = self

        class Tx(_FakeTransaction):
            def __exit__(self, *exc: object) -> bool:
                super().__exit__(*exc)
                if conn.lose_commit and exc[0] is None:
                    raise OSError("connection lost during COMMIT")
                return False

        return Tx(self)


def test_sync_restore_after_an_ambiguous_commit_does_not_reinsert_written_rows():
    """Review finding 12: the server committed before the connection died; the restored rows
    would hit the request_id key on the next flush and wedge the buffer."""
    conn = _CommitLostConnection()
    sink = RequestSink(conn, caller="unit-test")
    kept = _record(new_fetch_run_id(), str(uuid.uuid4()))
    written = _record(new_fetch_run_id(), str(uuid.uuid4()))
    sink.on_request(written)
    with pytest.raises(OSError):
        sink.flush()
    assert sink.pending() == 1
    sink.on_request(kept)
    conn.lose_commit = False
    conn.latest_rows = [(uuid.UUID(str(written.request_id)),)]  # the existence check finds it
    assert sink.flush() == 1
    assert [row[0] for row in conn.copies[-1][1]] == [uuid.UUID(str(kept.request_id))]
    assert any("FROM ohlcv_request WHERE request_id" in sql for sql, _ in conn.statements)


def test_sync_flush_failure_before_the_copy_does_not_run_the_existence_check():
    conn, sink = _sink()
    conn.transaction_status = psycopg.pq.TransactionStatus.INTRANS
    sink.on_request(_record(new_fetch_run_id(), str(uuid.uuid4())))
    with pytest.raises(RuntimeError):
        sink.flush()
    conn.transaction_status = psycopg.pq.TransactionStatus.IDLE
    assert sink.flush() == 1
    assert not any("FROM ohlcv_request WHERE request_id" in sql for sql, _ in conn.statements)


@pytest.mark.asyncio
async def test_async_restore_after_an_ambiguous_commit_does_not_reinsert_written_rows():
    class LostCommit(FakeAsyncConnection):
        lose = True

        def transaction(self):
            conn = self

            class Tx(_FakeAsyncTransaction):
                async def __aexit__(self, *exc: object) -> bool:
                    await super().__aexit__(*exc)
                    if conn.lose and exc[0] is None:
                        raise OSError("connection lost during COMMIT")
                    return False

            return Tx(self)

    sink = AsyncRequestSink(caller="unit-test")
    written = _record(new_fetch_run_id(), str(uuid.uuid4()))
    sink.on_request(written)
    conn = LostCommit()
    with pytest.raises(OSError):
        await sink.flush(conn)
    conn.lose = False
    conn.latest_rows = [(uuid.UUID(str(written.request_id)),)]
    assert await sink.flush(conn) == 0
    assert sink.pending() == 0
