"""Tests for scripts/infrastructure/backfill/_intraday_persist.py (plan 12, task 1b).

The helper makes a fetched chunk's answer atomic (todo 462, T-185-12-07): the
chunk's ohlcv_request rows and its destination bar rows commit in one
transaction, so a recorded answer can never outrun its stored bars. The
helper owns no INSERT for any table: request rows go through
services/ohlcv_observation_writer.write_request_rows (the sink's own row
writer, keeping ohlcv_request at one INSERT definition) and the bar rows go
through the caller-supplied destination writer (the archive's
insert_fetched_archive_rows here, the pipeline's 5m store in plan 18).

ObservationSink.flush() must never run inside the transaction: flush demands
an idle connection and opens its own transaction, so an open helper
transaction would trap its SET LOCAL ROLE. The helper takes the request rows
as data (the caller pulled them off the sink buffer via the new public
take_requests method) and never touches the sink.
"""

from __future__ import annotations

import inspect
import uuid
from datetime import UTC, datetime
from types import SimpleNamespace

import psycopg
import pytest
from scripts.infrastructure.backfill._intraday_persist import persist_chunk_atomically

from scripts.infrastructure.backfill import _intraday_persist
from services.ohlcv_observation_writer import write_request_rows

_REQUEST_ROW = (
    uuid.uuid4(),
    uuid.uuid4(),
    "SPY",
    "15m",
    "ibkr",
    "SMART",
    "TRADES",
    "NYSE",
    datetime(2026, 9, 27, 13, 30, tzinfo=UTC),
    datetime(2026, 9, 27, 14, 30, tzinfo=UTC),
    None,
    "bars",
    None,
    None,
    4,
    46,
    "historical-pipeline",
    datetime(2026, 9, 27, 14, 30, tzinfo=UTC),
    datetime(2026, 9, 27, 14, 30, tzinfo=UTC),
)

_ARCHIVE_ROW = (
    datetime(2026, 9, 27, 13, 30, tzinfo=UTC),
    "SPY",
    "15m",
    600.0,
    601.0,
    599.0,
    600.5,
    1000,
    "ibkr",
    None,
)


class FakeConn:
    """Records every statement with its inside-transaction flag; can fail on a
    statement substring to force a rollback."""

    def __init__(self, fail_on: str | None = None, idle: bool = True) -> None:
        self.statements: list[tuple[str, bool]] = []
        self.copies: list[tuple[str, list[tuple]]] = []
        self.fail_on = fail_on
        self._in_txn = False
        self.transaction_status = (
            psycopg.pq.TransactionStatus.IDLE if idle else psycopg.pq.TransactionStatus.INTRANS
        )

    def record(self, sql: str) -> None:
        if self.fail_on is not None and self.fail_on in sql:
            raise RuntimeError(f"forced failure on {sql!r}")
        self.statements.append((sql, self._in_txn))

    @property
    def info(self) -> SimpleNamespace:
        return SimpleNamespace(transaction_status=self.transaction_status)

    def cursor(self) -> FakeCursor:
        return FakeCursor(self)

    class _Txn:
        def __init__(self, conn: FakeConn) -> None:
            self._conn = conn

        def __enter__(self) -> FakeConn._Txn:
            self._conn._in_txn = True
            self._conn.record("<begin>")
            return self

        def __exit__(self, *exc: object) -> bool:
            self._conn._in_txn = False
            self._conn.record("<commit>" if not exc[0] else "<rollback>")
            return False

    def transaction(self) -> FakeConn._Txn:
        return self._Txn(self)


class FakeCursor:
    def __init__(self, conn: FakeConn) -> None:
        self._conn = conn

    def __enter__(self) -> FakeCursor:
        return self

    def __exit__(self, *exc: object) -> bool:
        return False

    def execute(self, sql: str, params: object = None) -> None:
        self._conn.record(sql)

    def copy(self, sql: str) -> _RecordingCopy:
        self._conn.record(sql)
        return _RecordingCopy(self._conn, sql)


class _RecordingCopy:
    def __init__(self, conn: FakeConn, sql: str) -> None:
        self._conn = conn
        self._sql = sql
        self.rows: list[tuple] = []

    def write_row(self, row: tuple) -> None:
        self.rows.append(tuple(row))

    def __enter__(self) -> _RecordingCopy:
        return self

    def __exit__(self, *exc: object) -> bool:
        self._conn.copies.append((self._sql, self.rows))
        self._conn.record("<copy done>")
        return False


@pytest.fixture()
def archive_writer():
    calls: list[tuple[object, list[tuple]]] = []

    def _write(cur, rows):
        cur.execute("INSERT INTO ohlcv_intraday_raw_archive (...)", [])
        calls.append((cur, rows))
        return len(rows)

    _write.calls = calls
    return _write


def test_request_and_archive_rows_commit_in_one_transaction(archive_writer):
    conn = FakeConn()
    n_requests, n_rows = persist_chunk_atomically(
        conn,
        request_rows=[_REQUEST_ROW],
        archive_rows=[_ARCHIVE_ROW],
        write_archive_rows=archive_writer,
    )
    assert (n_requests, n_rows) == (1, 1)
    kinds = [sql for sql, _inside in conn.statements]
    assert kinds[0] == "<begin>"
    assert kinds[-1] == "<commit>"
    # Inside ONE transaction: role for the request rows, then role for the
    # archive rows. No nested transaction, no separate commit in between.
    inside = [sql for sql, inside in conn.statements if inside]
    assert inside == [
        "SET LOCAL ROLE ohlcv_observation_writer",
        conn.copies[0][0],
        "<copy done>",
        "SET LOCAL ROLE bar_derivation_writer",
        "INSERT INTO ohlcv_intraday_raw_archive (...)",
    ]
    assert conn.copies[0][1] == [_REQUEST_ROW]
    assert archive_writer.calls[0][1] == [_ARCHIVE_ROW]


def test_failure_on_the_archive_insert_rolls_back_the_request_row(archive_writer):
    conn = FakeConn(fail_on="ohlcv_intraday_raw_archive")
    with pytest.raises(RuntimeError, match="forced failure"):
        persist_chunk_atomically(
            conn,
            request_rows=[_REQUEST_ROW],
            archive_rows=[_ARCHIVE_ROW],
            write_archive_rows=archive_writer,
        )
    kinds = [sql for sql, _ in conn.statements]
    assert kinds[-1] == "<rollback>"
    assert "<commit>" not in kinds  # the answer never lands without its bars


def test_failure_on_the_request_insert_rolls_back_the_archive_rows(archive_writer):
    conn = FakeConn(fail_on="ohlcv_request")
    with pytest.raises(RuntimeError, match="forced failure"):
        persist_chunk_atomically(
            conn,
            request_rows=[_REQUEST_ROW],
            archive_rows=[_ARCHIVE_ROW],
            write_archive_rows=archive_writer,
        )
    kinds = [sql for sql, _ in conn.statements]
    assert kinds[-1] == "<rollback>"
    assert "<commit>" not in kinds
    assert archive_writer.calls == []  # the archive write never ran


def test_helper_refuses_a_connection_that_is_not_idle(archive_writer):
    conn = FakeConn(idle=False)
    with pytest.raises(RuntimeError, match="idle connection"):
        persist_chunk_atomically(
            conn,
            request_rows=[_REQUEST_ROW],
            archive_rows=[_ARCHIVE_ROW],
            write_archive_rows=archive_writer,
        )
    assert conn.statements == []  # nothing written, no transaction opened


def test_helper_never_flushes_inside_its_transaction(archive_writer):
    """The chunk path's contract: between BEGIN and COMMIT only the two role
    switches, the request COPY and the destination write appear -- no sink
    flush (which would demand an idle connection and open its own
    transaction, trapping SET LOCAL ROLE)."""
    conn = FakeConn()
    persist_chunk_atomically(
        conn,
        request_rows=[_REQUEST_ROW],
        archive_rows=[_ARCHIVE_ROW],
        write_archive_rows=archive_writer,
    )
    inside = [sql for sql, inside_flag in conn.statements if inside_flag]
    assert all(
        sql.startswith(("SET LOCAL ROLE", "COPY ohlcv_request", "INSERT INTO"))
        or sql == "<copy done>"
        for sql in inside
    )
    assert not any("flush" in sql.lower() for sql in inside)


def test_helper_defines_no_insert_of_its_own_for_any_table():
    """single_writer: ohlcv_request's one INSERT definition is the sink's COPY;
    the archive's one INSERT definition is services/intraday_raw_archive's."""
    source = inspect.getsource(_intraday_persist)
    assert "INSERT INTO ohlcv_request" not in source
    assert "INSERT INTO ohlcv_intraday_raw_archive" not in source
    assert "ObservationSink" not in source
    assert ".flush(" not in source
    # The request rows go through the sink module's own row writer.
    assert "write_request_rows" in source


def test_request_rows_written_through_the_sink_row_writer(archive_writer):
    """write_request_rows is the same function the sink's flush path uses, so
    ohlcv_request keeps exactly one row-writing shape."""
    conn = FakeConn()
    write_request_rows(conn.cursor(), [_REQUEST_ROW])
    assert conn.copies[0][0].startswith("COPY ohlcv_request (")
    assert conn.copies[0][1] == [_REQUEST_ROW]


def test_empty_chunk_is_a_noop(archive_writer):
    conn = FakeConn()
    assert persist_chunk_atomically(
        conn, request_rows=[], archive_rows=[], write_archive_rows=archive_writer
    ) == (0, 0)
    assert conn.statements == []
