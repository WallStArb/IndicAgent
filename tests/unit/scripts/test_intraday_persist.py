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

from scripts.infrastructure.backfill import _intraday_persist
from scripts.infrastructure.backfill._intraday_persist import (
    chunk_digest,
    persist_chunk_atomically,
)
from services.ohlcv_coverage_writer import (
    FETCH_STATUSES,
    CoverageDelta,
    record_fetch_outcome,
    upsert_coverage,
)
from services.ohlcv_ingress_contract import RevisionRefused, SeriesLoad
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
        self.existing: list[datetime] = []  # timestamps the destination already stores
        self.params: dict[str, object] = {}
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
            self._conn.record("<begin>")
            self._conn._in_txn = True
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
        self.rowcount = 0

    def fetchall(self) -> list[tuple]:
        return [(ts,) for ts in self._conn.existing]

    def __enter__(self) -> FakeCursor:
        return self

    def __exit__(self, *exc: object) -> bool:
        return False

    def execute(self, sql: str, params: object = None) -> None:
        self._conn.record(sql)
        self._conn.params[sql] = params

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
    # The request row carries the content digest of the answer the chunk stored (plan 185-39).
    assert conn.copies[0][1] == [_REQUEST_ROW + (chunk_digest([_ARCHIVE_ROW]),)]
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


def test_digest_is_the_chunk_content_digest_and_null_without_bars(archive_writer):
    no_bars = _REQUEST_ROW[:11] + ("no_data",) + _REQUEST_ROW[12:14] + (0,) + _REQUEST_ROW[15:]
    conn = FakeConn()
    persist_chunk_atomically(
        conn,
        request_rows=[_REQUEST_ROW, no_bars],
        archive_rows=[_ARCHIVE_ROW],
        write_archive_rows=archive_writer,
    )
    with_bars, without = conn.copies[0][1]
    assert len(with_bars) == 20 and len(without) == 20
    assert with_bars[-1] == chunk_digest([_ARCHIVE_ROW])
    assert len(with_bars[-1]) == 64
    assert without[-1] is None


def test_digest_moves_with_the_answer_and_ignores_duplicate_timestamps():
    other = _ARCHIVE_ROW[:6] + (600.6,) + _ARCHIVE_ROW[7:]
    assert chunk_digest([_ARCHIVE_ROW]) != chunk_digest([other])
    assert chunk_digest([other, _ARCHIVE_ROW]) == chunk_digest([_ARCHIVE_ROW])


def test_request_row_with_a_digest_already_attached_is_refused(archive_writer):
    conn = FakeConn()
    with pytest.raises(ValueError, match="without a digest column"):
        persist_chunk_atomically(
            conn,
            request_rows=[_REQUEST_ROW + ("x",)],
            archive_rows=[_ARCHIVE_ROW],
            write_archive_rows=archive_writer,
        )


def _refusal() -> RevisionRefused:
    load = SeriesLoad(
        symbol="SPY",
        timeframe="15m",
        destination="archive",
        caller="ibkr-history-fetch",
        n_bars=1000,
        n_stored=1000,
        n_new=0,
        n_changed=30,
        n_unchanged=970,
        first_bar=datetime(2026, 9, 27).date(),
        last_bar=datetime(2026, 9, 27).date(),
    )
    return RevisionRefused(load, ratio=0.03, max_ratio=0.02)


def test_a_refused_chunk_rolls_back_then_records_requests_and_the_refused_load():
    def refusing_writer(cur, rows):
        raise _refusal()

    conn = FakeConn()
    with pytest.raises(RevisionRefused):
        persist_chunk_atomically(
            conn,
            request_rows=[_REQUEST_ROW],
            archive_rows=[_ARCHIVE_ROW],
            write_archive_rows=refusing_writer,
        )
    kinds = [sql for sql, _ in conn.statements]
    assert kinds.count("<rollback>") == 1 and kinds.count("<commit>") == 1
    assert kinds.index("<rollback>") < kinds.index("<commit>")
    # The second transaction wrote the request row (digest NULL) and the refused load row.
    assert conn.copies[-1][1] == [_REQUEST_ROW + (None,)]
    load_sql = [sql for sql, _ in conn.statements if sql.startswith("INSERT INTO ohlcv_load")]
    assert len(load_sql) == 1
    params = next(v for k, v in conn.params.items() if k.startswith("INSERT INTO ohlcv_load"))
    assert "refused" in params and "ibkr" in params
    detail = [p for p in params if isinstance(p, str) and p.startswith("refused:")]
    assert detail and "0.0300" in detail[0]


def test_empty_chunk_is_a_noop(archive_writer):
    conn = FakeConn()
    assert persist_chunk_atomically(
        conn, request_rows=[], archive_rows=[], write_archive_rows=archive_writer
    ) == (0, 0)
    assert conn.statements == []


# ---------------------------------------------------------------------------
# Coverage: the third write (phase 189 plan 01, CD-03/CD-04)
# ---------------------------------------------------------------------------


def _bar(ts: datetime, volume: int = 1000, *, symbol: str = "SPY", tf: str = "15m") -> tuple:
    return (ts, symbol, tf, 600.0, 601.0, 599.0, 600.5, volume, "ibkr", None)


_T0 = datetime(2026, 9, 27, 13, 30, tzinfo=UTC)
_T1 = datetime(2026, 9, 27, 13, 45, tzinfo=UTC)
_T2 = datetime(2026, 9, 27, 14, 0, tzinfo=UTC)
_FETCHED_AT = datetime(2026, 9, 27, 14, 30, tzinfo=UTC)


def _delta(destination: str = "archive") -> CoverageDelta:
    return CoverageDelta(
        symbol="SPY", timeframe="15m", destination=destination, fetched_at=_FETCHED_AT
    )


@pytest.fixture()
def recorded_upserts(monkeypatch):
    calls: list[dict] = []

    def _record(cur, delta, *, earliest, latest, n_new_rows):
        cur.execute("INSERT INTO ohlcv_coverage <recorded>", None)
        calls.append(
            {"delta": delta, "earliest": earliest, "latest": latest, "n_new_rows": n_new_rows}
        )

    monkeypatch.setattr(_intraday_persist, "upsert_coverage", _record)
    return calls


def test_coverage_write_is_the_third_write_inside_the_same_transaction(archive_writer):
    conn = FakeConn()
    assert persist_chunk_atomically(
        conn,
        request_rows=[_REQUEST_ROW],
        archive_rows=[_ARCHIVE_ROW],
        write_archive_rows=archive_writer,
        coverage=_delta(),
    ) == (1, 1)
    kinds = [sql for sql, _ in conn.statements]
    assert kinds[0] == "<begin>" and kinds[-1] == "<commit>"
    inside = [sql for sql, inside_flag in conn.statements if inside_flag]
    assert inside[:4] == [
        "SET LOCAL ROLE ohlcv_observation_writer",
        conn.copies[0][0],
        "<copy done>",
        "SET LOCAL ROLE bar_derivation_writer",
    ]
    assert inside[4].lstrip().startswith("SELECT timestamp FROM ohlcv_intraday_raw_archive")
    assert inside[5] == "INSERT INTO ohlcv_intraday_raw_archive (...)"
    assert inside[6].lstrip().startswith("INSERT INTO ohlcv_coverage")
    assert len(inside) == 7


def test_no_coverage_means_no_coverage_sql(archive_writer):
    conn = FakeConn()
    persist_chunk_atomically(
        conn,
        request_rows=[_REQUEST_ROW],
        archive_rows=[_ARCHIVE_ROW],
        write_archive_rows=archive_writer,
    )
    assert not any("ohlcv_coverage" in sql for sql, _ in conn.statements)
    assert not any(sql.lstrip().startswith("SELECT") for sql, _ in conn.statements)


def test_failure_in_the_coverage_upsert_rolls_back_everything(archive_writer):
    conn = FakeConn(fail_on="ohlcv_coverage")
    with pytest.raises(RuntimeError, match="forced failure"):
        persist_chunk_atomically(
            conn,
            request_rows=[_REQUEST_ROW],
            archive_rows=[_ARCHIVE_ROW],
            write_archive_rows=archive_writer,
            coverage=_delta(),
        )
    kinds = [sql for sql, _ in conn.statements]
    assert kinds[-1] == "<rollback>"
    assert "<commit>" not in kinds
    assert archive_writer.calls  # the bars were offered, and roll back with the coverage


def test_archive_counts_only_timestamps_not_already_stored(archive_writer, recorded_upserts):
    conn = FakeConn()
    conn.existing = [_T0]
    persist_chunk_atomically(
        conn,
        request_rows=[],
        archive_rows=[_bar(_T0), _bar(_T1, volume=0), _bar(_T2)],
        write_archive_rows=archive_writer,
        coverage=_delta("archive"),
    )
    (call,) = recorded_upserts
    # archive: every new row counts, zero-volume included
    assert call["n_new_rows"] == 2
    assert (call["earliest"], call["latest"]) == (_T1, _T2)


def test_grid_counts_only_new_tradeable_rows(archive_writer, recorded_upserts):
    conn = FakeConn()
    conn.existing = [_T0]
    persist_chunk_atomically(
        conn,
        request_rows=[],
        archive_rows=[_bar(_T0), _bar(_T1, volume=0), _bar(_T2)],
        write_archive_rows=archive_writer,
        coverage=_delta("grid"),
    )
    (call,) = recorded_upserts
    assert call["n_new_rows"] == 1
    assert (call["earliest"], call["latest"]) == (_T2, _T2)
    assert "FROM market_data_ohlcv" in conn.statements[2][0]


def test_bounds_fall_back_to_offered_rows_when_nothing_new(archive_writer, recorded_upserts):
    conn = FakeConn()
    conn.existing = [_T0, _T1]
    persist_chunk_atomically(
        conn,
        request_rows=[],
        archive_rows=[_bar(_T0), _bar(_T1)],
        write_archive_rows=archive_writer,
        coverage=_delta(),
    )
    (call,) = recorded_upserts
    assert call["n_new_rows"] == 0
    assert (call["earliest"], call["latest"]) == (_T0, _T1)


def test_duplicate_timestamps_in_a_chunk_count_once(archive_writer, recorded_upserts):
    conn = FakeConn()
    persist_chunk_atomically(
        conn,
        request_rows=[],
        archive_rows=[_bar(_T0), _bar(_T0)],
        write_archive_rows=archive_writer,
        coverage=_delta(),
    )
    assert recorded_upserts[0]["n_new_rows"] == 1


def test_rows_for_another_series_are_refused_before_any_sql(archive_writer):
    conn = FakeConn()
    with pytest.raises(ValueError, match="series"):
        persist_chunk_atomically(
            conn,
            request_rows=[_REQUEST_ROW],
            archive_rows=[_bar(_T0, symbol="QQQ")],
            write_archive_rows=archive_writer,
            coverage=_delta(),
        )
    assert conn.statements == []


def test_coverage_delta_rejects_an_unknown_destination():
    with pytest.raises(ValueError, match="destination"):
        CoverageDelta(symbol="SPY", timeframe="15m", destination="nowhere", fetched_at=_FETCHED_AT)


def test_coverage_delta_defaults_to_the_ibkr_stored_state_label():
    assert _delta().provider == "ibkr"


def test_a_non_default_provider_on_the_delta_reaches_the_upsert(archive_writer, recorded_upserts):
    """T-190-02b: the coverage row is labeled by the vendor that actually fetched the chunk.
    The helper threads the delta's provider through untouched; a second vendor's coverage can
    never silently record as ibkr."""
    conn = FakeConn()
    alpaca = CoverageDelta(
        symbol="SPY",
        timeframe="15m",
        destination="archive",
        fetched_at=_FETCHED_AT,
        provider="alpaca",
    )
    persist_chunk_atomically(
        conn,
        request_rows=[_REQUEST_ROW],
        archive_rows=[_ARCHIVE_ROW],
        write_archive_rows=archive_writer,
        coverage=alpaca,
    )
    (call,) = recorded_upserts
    assert call["delta"].provider == "alpaca"


def test_upsert_labels_the_row_from_the_delta_provider():
    """At the SQL level: the provider parameter rides in the INSERT column list, so the
    labeled row lands even while the conflict target is still the old shape."""
    conn = FakeConn()
    upsert_coverage(
        conn.cursor(),
        CoverageDelta(symbol="SPY", timeframe="15m", destination="archive", fetched_at=_FETCHED_AT),
        earliest=_T0,
        latest=_T1,
        n_new_rows=2,
    )
    ((sql, _),) = conn.statements
    assert "provider" in sql.split("INSERT INTO ohlcv_coverage (")[1].split(")")[0]
    assert "ON CONFLICT (symbol, timeframe)" in sql
    params = conn.params[sql]
    assert params[-1] == "ibkr"  # the delta's provider, last in the VALUES tuple


def test_record_fetch_outcome_rejects_an_unknown_status_before_sql():
    conn = FakeConn()
    with pytest.raises(ValueError, match="status"):
        record_fetch_outcome(conn.cursor(), "SPY", "15m", "timeout", _FETCHED_AT)
    assert conn.statements == []


def test_record_fetch_outcome_never_increments_on_no_data():
    """CD-05 at the SQL level: only an error adds to consecutive_failures."""
    conn = FakeConn()
    record_fetch_outcome(conn.cursor(), "SPY", "15m", "no_data", _FETCHED_AT)
    ((sql, _),) = conn.statements
    params = conn.params[sql]
    assert "WHEN EXCLUDED.last_fetch_status = 'error'" in sql
    assert "ohlcv_coverage.consecutive_failures + 1" in sql
    assert params[-2] == 0  # insert path: no_data starts at zero
    assert params[-1] == "ibkr"  # the stored-state provider default labels the row
    conn = FakeConn()
    record_fetch_outcome(conn.cursor(), "SPY", "15m", "error", _FETCHED_AT)
    assert conn.params[conn.statements[0][0]][-2] == 1


def test_fetch_statuses_are_the_ledger_check_values():
    assert FETCH_STATUSES == ("ok", "no_data", "error")
