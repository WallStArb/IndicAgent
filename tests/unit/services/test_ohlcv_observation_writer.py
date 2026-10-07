"""Unit tests for the D1 COPY writer (phase 185 plan 02), all against fakes -- no DB.

The fake psycopg connection/cursor records executed statements (with an
inside-transaction flag) and COPY targets with their write_row rows in call order, so
the tests assert the load-bearing ordering properties: requests before observations,
SET LOCAL ROLE as the transaction's first statement, and no SQL before validation
raises.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta, timezone
from types import SimpleNamespace

import psycopg
import pytest

from services.ohlcv_observation_writer import (
    AsyncObservationSink,
    ObservationSink,
    drop_unchanged_observations,
    new_fetch_run_id,
    write_request_rows,
)
from src.providers.base import OHLCVBar


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


def _bars(n: int = 3, *, close: float | None = None) -> list[OHLCVBar]:
    return [
        OHLCVBar(
            symbol="SPY",
            timeframe="1d",
            timestamp=datetime(2024, 1, 2 + i, 0, 0, tzinfo=UTC),
            open=100.0 + i,
            high=101.0 + i,
            low=99.0 + i,
            close=(close if close is not None else 100.5 + i),
            volume=1_000 * (i + 1),
            source="ibkr",
        )
        for i in range(n)
    ]


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


def test_new_fetch_run_id_is_a_uuid_string():
    value = new_fetch_run_id()
    assert isinstance(value, str)
    uuid.UUID(value)  # raises if not a uuid


def test_flush_writes_requests_before_observations():
    conn = FakeConnection()
    sink = ObservationSink(conn, caller="unit-test")
    run = new_fetch_run_id()
    record = _record(run, str(uuid.uuid4()))
    sink.on_request(record)
    sink.on_observation(record, _bars(3))
    assert sink.flush() == (1, 3)
    targets = [sql.split()[1] for sql, _ in conn.copies]
    assert targets == ["ohlcv_request", "ohlcv_observation"]


def test_flush_first_statement_in_transaction_is_set_local_role():
    conn = FakeConnection()
    sink = ObservationSink(conn, caller="unit-test")
    record = _record(new_fetch_run_id(), str(uuid.uuid4()))
    sink.on_request(record)
    sink.on_observation(record, _bars(2))
    sink.flush()
    # Health check runs outside the transaction; SET LOCAL ROLE leads inside it.
    assert conn.statements[0] == ("SELECT 1", False)
    in_transaction = [sql for sql, inside in conn.statements if inside]
    assert in_transaction[0] == "SET LOCAL ROLE ohlcv_observation_writer"


def test_flush_empties_buffers_and_pending_returns_zero():
    conn = FakeConnection()
    sink = ObservationSink(conn, caller="unit-test")
    record = _record(new_fetch_run_id(), str(uuid.uuid4()))
    sink.on_request(record)
    sink.on_observation(record, _bars(3))
    assert sink.pending() == 4
    assert sink.flush() == (1, 3)
    assert sink.pending() == 0
    assert sink.flush() == (0, 0)  # empty flush issues no SQL
    assert len(conn.copies) == 2


def test_orphan_observation_raises_at_flush():
    conn = FakeConnection()
    sink = ObservationSink(conn, caller="unit-test")
    orphan = _record(new_fetch_run_id(), str(uuid.uuid4()))
    sink.on_observation(orphan, _bars(2))  # request never buffered in this sink
    with pytest.raises(ValueError, match="never buffered in this sink"):
        sink.flush()
    assert not conn.copies


def test_request_flushed_earlier_in_same_sink_still_satisfies_fk():
    conn = FakeConnection()
    sink = ObservationSink(conn, caller="unit-test")
    record = _record(new_fetch_run_id(), str(uuid.uuid4()))
    sink.on_request(record)
    sink.flush()
    sink.on_observation(record, _bars(2))
    assert sink.flush() == (0, 2)
    assert len(conn.copies) == 2  # second flush copied observations only


def test_non_finite_price_raises_before_any_sql():
    conn = FakeConnection()
    sink = ObservationSink(conn, caller="unit-test")
    record = _record(new_fetch_run_id(), str(uuid.uuid4()))
    sink.on_request(record)
    with pytest.raises(ValueError, match="non-finite"):
        sink.on_observation(record, _bars(2, close=float("inf")))
    assert conn.statements == [] and conn.copies == []


def test_intraday_observations_rejected_any_timeframe_requests_accepted():
    conn = FakeConnection()
    sink = ObservationSink(conn, caller="unit-test")
    intraday = _record(new_fetch_run_id(), str(uuid.uuid4()), timeframe="5m")
    sink.on_request(intraday)  # requests for any timeframe are accepted
    with pytest.raises(ValueError, match="1d only"):
        sink.on_observation(intraday, _bars(1))
    assert conn.statements == []


def test_observation_rows_carry_uuid_and_utc_bar_date():
    conn = FakeConnection()
    sink = ObservationSink(conn, caller="unit-test")
    request_id = str(uuid.uuid4())
    record = _record(new_fetch_run_id(), request_id)
    sink.on_request(record)
    sink.on_observation(record, _bars(1))
    sink.flush()
    request_row = conn.copies[0][1][0]
    observation_row = conn.copies[1][1][0]
    assert request_row[0] == uuid.UUID(request_id)
    assert observation_row[0] == uuid.UUID(request_id)
    assert observation_row[3] == date(2024, 1, 2)  # bar_date from the 00:00 UTC stamp
    assert observation_row[2] == "1d"


def test_naive_bar_timestamp_raises_before_any_sql():
    conn = FakeConnection()
    sink = ObservationSink(conn, caller="unit-test")
    record = _record(new_fetch_run_id(), str(uuid.uuid4()))
    naive_bar = OHLCVBar(
        symbol="SPY",
        timeframe="1d",
        timestamp=datetime(2024, 1, 2, 0, 0),  # naive: astimezone would assume local
        open=100.0,
        high=101.0,
        low=99.0,
        close=100.5,
        volume=1_000,
        source="ibkr",
    )
    sink.on_request(record)
    with pytest.raises(ValueError, match="tz-aware UTC"):
        sink.on_observation(record, [naive_bar])
    assert conn.statements == [] and conn.copies == []


def test_bar_date_is_the_utc_date_for_non_utc_aware_stamps():
    conn = FakeConnection()
    sink = ObservationSink(conn, caller="unit-test")
    request_id = str(uuid.uuid4())
    record = _record(new_fetch_run_id(), request_id)
    # 2024-01-02 20:00 America/New_York (UTC-5) is 2024-01-03 01:00 UTC.
    evening_bar = OHLCVBar(
        symbol="SPY",
        timeframe="1d",
        timestamp=datetime(2024, 1, 2, 20, 0, tzinfo=timezone(timedelta(hours=-5))),
        open=100.0,
        high=101.0,
        low=99.0,
        close=100.5,
        volume=1_000,
        source="ibkr",
    )
    sink.on_request(record)
    sink.on_observation(record, [evening_bar])
    sink.flush()
    assert conn.copies[1][1][0][3] == date(2024, 1, 3)


def test_sync_sink_auto_flushes_at_max_buffer_rows():
    conn = FakeConnection()
    sink = ObservationSink(conn, caller="unit-test", max_buffer_rows=4)
    record = _record(new_fetch_run_id(), str(uuid.uuid4()))
    sink.on_request(record)
    sink.on_observation(record, _bars(3))  # pending hits 4 = max_buffer_rows
    assert len(conn.copies) == 2  # auto-flush ran: requests then observations
    assert sink.pending() == 0


def test_sync_flush_refuses_an_open_caller_transaction():
    # An open transaction would demote the write transaction to a savepoint and
    # trap SET LOCAL ROLE past the flush (found live by the integration test).
    conn = FakeConnection()
    conn.transaction_status = psycopg.pq.TransactionStatus.INTRANS
    sink = ObservationSink(conn, caller="unit-test")
    record = _record(new_fetch_run_id(), str(uuid.uuid4()))
    sink.on_request(record)
    with pytest.raises(RuntimeError, match="idle connection"):
        sink.flush()
    assert conn.copies == []


def test_sync_flush_commits_the_health_check_transaction():
    conn = FakeConnection()
    sink = ObservationSink(conn, caller="unit-test")
    record = _record(new_fetch_run_id(), str(uuid.uuid4()))
    sink.on_request(record)
    sink.on_observation(record, _bars(1))
    sink.flush()
    # The SELECT 1 check's implicit transaction is ended before the write
    # transaction, keeping it top-level so SET LOCAL ROLE reverts at its commit.
    assert conn.commits == 1


@pytest.mark.asyncio
async def test_async_flush_requests_first_and_role_first_statement():
    conn = FakeAsyncConnection()
    sink = AsyncObservationSink(caller="unit-test")
    record = _record(new_fetch_run_id(), str(uuid.uuid4()))
    sink.on_request(record)
    sink.on_observation(record, _bars(2))
    assert await sink.flush(conn) == (1, 2)
    assert conn.statements[0] == "SET LOCAL ROLE ohlcv_observation_writer"
    assert [table for table, _ in conn.copies] == ["ohlcv_request", "ohlcv_observation"]


@pytest.mark.asyncio
async def test_async_sink_does_not_auto_flush():
    conn = FakeAsyncConnection()
    sink = AsyncObservationSink(caller="unit-test", max_buffer_rows=2)
    record = _record(new_fetch_run_id(), str(uuid.uuid4()))
    sink.on_request(record)
    sink.on_observation(record, _bars(3))
    assert sink.pending() == 4  # the caller owns the flush check on the async path
    assert conn.copies == []


@pytest.mark.asyncio
async def test_async_orphan_observation_raises_at_flush():
    conn = FakeAsyncConnection()
    sink = AsyncObservationSink(caller="unit-test")
    sink.on_observation(_record(new_fetch_run_id(), str(uuid.uuid4())), _bars(1))
    with pytest.raises(ValueError, match="never buffered in this sink"):
        await sink.flush(conn)
    assert conn.copies == []


@pytest.mark.asyncio
async def test_async_flush_refuses_an_open_caller_transaction():
    conn = FakeAsyncConnection()
    conn.open_transaction = True
    sink = AsyncObservationSink(caller="unit-test")
    sink.on_request(_record(new_fetch_run_id(), str(uuid.uuid4())))
    with pytest.raises(RuntimeError, match="idle connection"):
        await sink.flush(conn)
    assert conn.copies == []


def test_take_requests_removes_only_the_wanted_rows_and_keeps_the_rest():
    """The atomic persist helper (plan 12) commits a chunk's request rows
    itself; take_requests hands them over without flushing, and the remaining
    buffer (1d observations, failed requests) flushes afterwards as before."""
    conn = FakeConnection()
    sink = ObservationSink(conn, caller="unit-test")
    run = new_fetch_run_id()
    chunk_a = _record(run, str(uuid.uuid4()), timeframe="15m")
    chunk_b = _record(run, str(uuid.uuid4()), timeframe="15m")
    daily = _record(run, str(uuid.uuid4()), timeframe="1d")
    sink.on_request(chunk_a)
    sink.on_request(chunk_b)
    sink.on_request(daily)
    sink.on_observation(daily, _bars(2))

    taken = sink.take_requests([chunk_a.request_id])
    assert [row[0] for row in taken] == [uuid.UUID(str(chunk_a.request_id))]
    # The rest is still buffered: chunk_b's and daily's requests, daily's 2 rows.
    assert sink.pending() == 4
    assert sink.flush() == (2, 2)
    copied_requests = conn.copies[0][1]
    assert uuid.UUID(str(chunk_a.request_id)) not in {row[0] for row in copied_requests}
    assert uuid.UUID(str(chunk_b.request_id)) in {row[0] for row in copied_requests}


def test_take_requests_with_no_match_returns_empty_and_changes_nothing():
    conn = FakeConnection()
    sink = ObservationSink(conn, caller="unit-test")
    record = _record(new_fetch_run_id(), str(uuid.uuid4()))
    sink.on_request(record)
    assert sink.take_requests([str(uuid.uuid4())]) == []
    assert sink.pending() == 1
    assert sink.flush() == (1, 0)


def test_taken_requests_never_flush_twice():
    conn = FakeConnection()
    sink = ObservationSink(conn, caller="unit-test")
    record = _record(new_fetch_run_id(), str(uuid.uuid4()))
    sink.on_request(record)
    taken = sink.take_requests([record.request_id])
    assert len(taken) == 1
    assert sink.flush() == (0, 0)  # nothing left: the taken rows are the helper's
    assert conn.copies == []


# --- plan 185-39: the optional content_digest column on a request row -------------------------


def _request_values(n: int = 19) -> tuple:
    return tuple(range(n))


def test_write_request_rows_without_a_digest_copies_the_original_columns():
    conn = FakeConnection()
    write_request_rows(conn.cursor(), [_request_values(19)])
    sql, rows = conn.copies[0]
    assert "content_digest" not in sql and sql.count(",") == 18
    assert rows == [_request_values(19)]


def test_write_request_rows_with_a_digest_adds_the_column():
    conn = FakeConnection()
    write_request_rows(conn.cursor(), [_request_values(20)])
    sql, rows = conn.copies[0]
    assert sql.startswith("COPY ohlcv_request (") and sql.count(",") == 19
    assert "answered_at, content_digest)" in sql
    assert rows == [_request_values(20)]


def test_write_request_rows_refuses_mixed_widths_before_any_sql():
    conn = FakeConnection()
    with pytest.raises(ValueError, match="all"):
        write_request_rows(conn.cursor(), [_request_values(19), _request_values(20)])
    assert conn.statements == []


# --- plan 185-39: D1 elision of IBKR observations equal to the latest stored one --------------

_DAY0 = date(2024, 1, 2)


def _stored_latest(bars: list[OHLCVBar]) -> list[tuple]:
    """The rows the elision read returns for `bars` as already stored (route SMART, TRADES)."""
    return [
        (
            "SPY",
            bar.timestamp.date(),
            "SMART",
            "TRADES",
            bar.open,
            bar.high,
            bar.low,
            bar.close,
            bar.volume,
        )
        for bar in bars
    ]


def _flushed_observations(conn: FakeConnection) -> list[tuple]:
    return next((rows for sql, rows in conn.copies if "ohlcv_observation (" in sql), [])


def test_an_identical_answer_lands_no_observation_but_the_request_keeps_its_length():
    conn = FakeConnection()
    conn.latest_rows = _stored_latest(_bars(3))
    sink = ObservationSink(conn, caller="ibkr-history-fetch")
    record = _record(new_fetch_run_id(), str(uuid.uuid4()), n_bars=3)
    sink.on_request(record)
    sink.on_observation(record, _bars(3))
    assert sink.flush() == (1, 0)
    assert _flushed_observations(conn) == []
    (request_rows,) = [rows for sql, rows in conn.copies if "ohlcv_request (" in sql]
    assert request_rows[0][14] == 3  # n_bars is the full answer length


def test_a_differing_observation_lands_and_an_unchanged_one_beside_it_does_not():
    conn = FakeConnection()
    conn.latest_rows = _stored_latest(_bars(3))
    sink = ObservationSink(conn, caller="ibkr-history-fetch")
    record = _record(new_fetch_run_id(), str(uuid.uuid4()))
    sink.on_request(record)
    revised = _bars(3)
    revised[1] = revised[1].model_copy(update={"close": 150.0})
    sink.on_observation(record, revised)
    assert sink.flush() == (1, 1)
    (landed,) = _flushed_observations(conn)
    assert landed[3] == date(2024, 1, 3) and landed[7] == 150.0


def test_a_first_load_lands_every_observation():
    conn = FakeConnection()
    sink = ObservationSink(conn, caller="ibkr-history-fetch")
    record = _record(new_fetch_run_id(), str(uuid.uuid4()))
    sink.on_request(record)
    sink.on_observation(record, _bars(3))
    assert sink.flush() == (1, 3)


def test_the_same_answer_buffered_twice_in_one_flush_lands_once():
    conn = FakeConnection()
    sink = ObservationSink(conn, caller="ibkr-history-fetch")
    first = _record(new_fetch_run_id(), str(uuid.uuid4()))
    second = _record(first.fetch_run_id, str(uuid.uuid4()))
    for record in (first, second):
        sink.on_request(record)
        sink.on_observation(record, _bars(2))
    assert sink.flush() == (2, 2)


def test_the_read_excludes_test_callers_and_keys_on_route_and_what_to_show():
    conn = FakeConnection()
    sink = ObservationSink(conn, caller="ibkr-history-fetch")
    record = _record(new_fetch_run_id(), str(uuid.uuid4()))
    sink.on_request(record)
    sink.on_observation(record, _bars(2))
    sink.flush()
    read = next(sql for sql, _ in conn.statements if "DISTINCT ON" in sql)
    assert "NOT starts_with(q.caller, 'test-')" in read
    assert "o.route = k.route AND o.what_to_show = k.what_to_show" in read
    keys = next(p for p in conn.params if p)
    assert keys[2] == ["SMART", "SMART"] and keys[3] == ["TRADES", "TRADES"]


def test_a_test_caller_sink_never_elides_so_fixtures_land_as_written():
    conn = FakeConnection()
    conn.latest_rows = _stored_latest(_bars(3))
    sink = ObservationSink(conn, caller="test-d2-fixture")
    record = _record(new_fetch_run_id(), str(uuid.uuid4()))
    sink.on_request(record)
    sink.on_observation(record, _bars(3))
    assert sink.flush() == (1, 3)
    assert not any("DISTINCT ON" in sql for sql, _ in conn.statements)


@pytest.mark.asyncio
async def test_async_sink_elides_an_identical_answer_too():
    conn = FakeAsyncConnection()
    conn.latest_rows = _stored_latest(_bars(2))
    sink = AsyncObservationSink(caller="ibkr-history-fetch")
    record = _record(new_fetch_run_id(), str(uuid.uuid4()), n_bars=2)
    sink.on_request(record)
    sink.on_observation(record, _bars(2))
    assert await sink.flush(conn) == (1, 0)
    assert [table for table, _ in conn.copies] == ["ohlcv_request"]
    assert len(conn.fetch_args[0]) == 4  # symbol, date, route, what_to_show arrays


def test_elision_compares_a_null_volume_as_a_value():
    stored = {("SPY", date(2024, 1, 2), "SMART", "TRADES"): (1.0, 2.0, 0.5, 1.5, None)}
    row = (
        None,
        "SPY",
        "1d",
        date(2024, 1, 2),
        1.0,
        2.0,
        0.5,
        1.5,
        None,
        "ibkr",
        "SMART",
        "TRADES",
        None,
    )
    assert drop_unchanged_observations([row], stored) == []
    changed = row[:8] + (10,) + row[9:]
    assert drop_unchanged_observations([changed], stored) == [changed]


def test_a_tradier_sink_does_not_elide_the_loader_does_its_own():
    conn = FakeConnection()
    conn.latest_rows = _stored_latest(_bars(3))
    sink = ObservationSink(conn, caller="tradier-daily", source="tradier")
    record = _record(new_fetch_run_id(), str(uuid.uuid4()))
    sink.on_request(record)
    sink.on_observation(record, _bars(3))
    assert sink.flush() == (1, 3)
    assert not any("DISTINCT ON" in sql for sql, _ in conn.statements)
