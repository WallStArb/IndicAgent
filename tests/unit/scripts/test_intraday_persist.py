"""Tests for scripts/infrastructure/backfill/_intraday_persist.py (plan 12, task 1b; plan 191-05).

The helper makes a fetched chunk's answer atomic (todo 462, T-185-12-07): the chunk's raw rows
(through the raw-first ingress contract), its ohlcv_request rows and, when asked, its
ohlcv_coverage update commit in ONE transaction, so a recorded answer can never outrun its stored
bars. The helper owns no INSERT for any table: raw rows go through
services/ohlcv_ingress_contract.apply_raw_contract and request rows through
services/ohlcv_request_writer.write_request_rows (the fetch ledger writer, keeping ohlcv_request at
one INSERT definition).

The raw write runs first because the request row's content digest is the digest of what the chunk
stored (every offered row lands last-wins, D-191-N).

RequestSink.flush() must never run inside the transaction: flush demands an idle connection and
opens its own transaction, so an open helper transaction would trap its SET LOCAL ROLE. The helper
takes the request rows as data (the caller pulled them off the sink buffer via take_requests) and
never touches the sink.
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
from services.ohlcv_ingress_contract import IngressResult
from services.ohlcv_raw_writer import RawRow
from services.ohlcv_request_writer import write_request_rows

_REQUEST_ID = uuid.uuid4()
_REQUEST_ROW = (
    _REQUEST_ID,
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
    None,  # partial_bars (migration 479)
)

_T0 = datetime(2026, 9, 27, 13, 30, tzinfo=UTC)
_ANSWERED = datetime(2026, 9, 27, 21, 0, tzinfo=UTC)
_T1 = datetime(2026, 9, 27, 13, 45, tzinfo=UTC)
_T2 = datetime(2026, 9, 27, 14, 0, tzinfo=UTC)
_FETCHED_AT = datetime(2026, 9, 27, 14, 30, tzinfo=UTC)


def _bar(
    ts: datetime = _T0, volume: int | None = 1000, *, symbol: str = "SPY", tf: str = "15m"
) -> RawRow:
    return RawRow(ts, symbol, tf, "ibkr", "named", 600.0, 601.0, 599.0, 600.5, volume)


_RAW_ROW = _bar()


class FakeConn:
    """Records every statement with its inside-transaction flag; can fail on a
    statement substring to force a rollback."""

    def __init__(self, fail_on: str | None = None, idle: bool = True) -> None:
        self.statements: list[tuple[str, bool]] = []
        self.copies: list[tuple[str, list[tuple]]] = []
        self.fail_on = fail_on
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
        return []

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


def _result(rows: list[RawRow], *, existing=()) -> IngressResult:
    stamps = sorted({r.timestamp for r in rows} - set(existing))
    return IngressResult(
        n_offered=len(rows),
        n_new=len(stamps),
        n_changed=0,
        n_unchanged=0,
        selected_slots=0,
        new_timestamps=tuple(stamps),
    )


@pytest.fixture()
def contract(monkeypatch):
    """apply_raw_contract replaced by a recorder that issues one statement on the connection (so
    the test sees it inside the transaction) and returns a scripted IngressResult."""
    state = SimpleNamespace(calls=[], existing=(), fail=False, read_params=[])

    def fake(conn, rows, *, caller, request_id, answered_at, params=None):
        with conn.cursor() as cur:
            cur.execute("INSERT INTO ohlcv_raw (<contract>)", [])
        if state.fail:
            raise RuntimeError("forced failure in contract")
        state.calls.append(
            {
                "rows": list(rows),
                "caller": caller,
                "request_id": request_id,
                "answered_at": answered_at,
                "params": params,
            }
        )
        return _result(rows, existing=state.existing)

    def fake_read_params(cur):
        cur.execute("SELECT <read raw params>", None)
        state.read_params.append(cur)
        return "read-params"

    monkeypatch.setattr(_intraday_persist, "apply_raw_contract", fake)
    monkeypatch.setattr(_intraday_persist, "read_raw_params", fake_read_params)
    return state


def test_raw_and_request_rows_commit_in_one_transaction(contract):
    conn = FakeConn()
    result = persist_chunk_atomically(conn, request_rows=[_REQUEST_ROW], raw_rows=[_RAW_ROW])
    assert (result.n_requests, result.n_rows) == (1, 1)
    kinds = [sql for sql, _inside in conn.statements]
    assert kinds[0] == "<begin>"
    assert kinds[-1] == "<commit>"
    inside = [sql for sql, inside in conn.statements if inside]
    assert inside == [
        "SELECT <read raw params>",
        "SET LOCAL ROLE bar_derivation_writer",
        "INSERT INTO ohlcv_raw (<contract>)",
        "SET LOCAL ROLE ohlcv_observation_writer",
        conn.copies[0][0],
        "<copy done>",
    ]
    # The request row carries the content digest of the answer the chunk stored (plan 185-39).
    assert conn.copies[0][1] == [_REQUEST_ROW + (chunk_digest([_RAW_ROW]),)]
    assert contract.calls[0]["rows"] == [_RAW_ROW]


def test_failure_in_the_contract_rolls_back_and_writes_no_request_row(contract):
    contract.fail = True
    conn = FakeConn()
    with pytest.raises(RuntimeError, match="forced failure in contract"):
        persist_chunk_atomically(conn, request_rows=[_REQUEST_ROW], raw_rows=[_RAW_ROW])
    kinds = [sql for sql, _ in conn.statements]
    assert kinds[-1] == "<rollback>" and "<commit>" not in kinds
    assert conn.copies == []  # the answer is never recorded without its bars


def test_failure_on_the_request_insert_rolls_back_the_raw_rows(contract):
    conn = FakeConn(fail_on="ohlcv_request")
    with pytest.raises(RuntimeError, match="forced failure"):
        persist_chunk_atomically(conn, request_rows=[_REQUEST_ROW], raw_rows=[_RAW_ROW])
    kinds = [sql for sql, _ in conn.statements]
    assert kinds[-1] == "<rollback>"
    assert "<commit>" not in kinds
    assert contract.calls  # the raw write ran inside the transaction that rolled back


def test_helper_refuses_a_connection_that_is_not_idle(contract):
    conn = FakeConn(idle=False)
    with pytest.raises(RuntimeError, match="idle connection"):
        persist_chunk_atomically(conn, request_rows=[_REQUEST_ROW], raw_rows=[_RAW_ROW])
    assert conn.statements == [] and contract.calls == []


def test_helper_never_flushes_inside_its_transaction(contract):
    conn = FakeConn()
    persist_chunk_atomically(conn, request_rows=[_REQUEST_ROW], raw_rows=[_RAW_ROW])
    inside = [sql for sql, inside_flag in conn.statements if inside_flag]
    assert all(
        sql.startswith(("SET LOCAL ROLE", "COPY ohlcv_request", "INSERT INTO", "SELECT <read"))
        or sql == "<copy done>"
        for sql in inside
    )
    assert not any("flush" in sql.lower() for sql in inside)


def test_helper_defines_no_insert_of_its_own_and_knows_no_archive_or_observation_table():
    """single_writer: ohlcv_request's one INSERT definition is the request writer's COPY and
    ohlcv_raw's is the raw writer's; nothing here reaches the retired stores."""
    source = inspect.getsource(_intraday_persist)
    code = "\n".join(line for line in source.splitlines() if not line.lstrip().startswith("#"))
    body = code.split('"""', 2)[2]  # past the module docstring
    assert "INSERT INTO ohlcv_request" not in body
    assert "INSERT INTO ohlcv_raw" not in body
    for retired in ("ohlcv_intraday_raw_archive", "archive_refusal_rows", "RevisionRefused"):
        assert retired not in body
    assert "ObservationSink" not in body and ".flush(" not in body
    assert "write_request_rows" in body and "apply_raw_contract" in body


def test_request_rows_written_through_the_request_writer_row_writer():
    conn = FakeConn()
    write_request_rows(conn.cursor(), [_REQUEST_ROW])
    assert conn.copies[0][0].startswith("COPY ohlcv_request (")
    assert conn.copies[0][1] == [_REQUEST_ROW]


def test_digest_is_the_chunk_content_digest_and_null_without_bars(contract):
    no_bars = _REQUEST_ROW[:11] + ("no_data",) + _REQUEST_ROW[12:14] + (0,) + _REQUEST_ROW[15:]
    conn = FakeConn()
    persist_chunk_atomically(conn, request_rows=[_REQUEST_ROW, no_bars], raw_rows=[_RAW_ROW])
    with_bars, without = conn.copies[0][1]
    assert len(with_bars) == 21 and len(without) == 21
    assert with_bars[-1] == chunk_digest([_RAW_ROW])
    assert len(with_bars[-1]) == 64
    assert without[-1] is None


def test_digest_moves_with_the_answer_and_ignores_duplicate_timestamps():
    other = RawRow(_T0, "SPY", "15m", "ibkr", "named", 600.0, 601.0, 599.0, 600.6, 1000)
    assert chunk_digest([_RAW_ROW]) != chunk_digest([other])
    assert chunk_digest([other, _RAW_ROW]) == chunk_digest([_RAW_ROW])


def test_request_row_with_a_digest_already_attached_is_refused(contract):
    conn = FakeConn()
    with pytest.raises(ValueError, match="without a digest column"):
        persist_chunk_atomically(conn, request_rows=[_REQUEST_ROW + ("x",)], raw_rows=[_RAW_ROW])


def test_the_raw_rows_carry_the_chunks_answering_request_id(contract):
    no_bars = _REQUEST_ROW[:11] + ("no_data",) + _REQUEST_ROW[12:14] + (0,) + _REQUEST_ROW[15:]
    later_empty = (uuid.uuid4(),) + no_bars[1:]
    persist_chunk_atomically(
        FakeConn(), request_rows=[_REQUEST_ROW, later_empty], raw_rows=[_RAW_ROW]
    )
    assert contract.calls[0]["request_id"] == _REQUEST_ID


def test_an_explicit_request_id_wins_and_a_chunk_without_requests_gets_a_fresh_one(contract):
    explicit = uuid.uuid4()
    persist_chunk_atomically(
        FakeConn(), request_rows=[], raw_rows=[_RAW_ROW], answered_at=_ANSWERED, request_id=explicit
    )
    persist_chunk_atomically(
        FakeConn(), request_rows=[], raw_rows=[_RAW_ROW], answered_at=_ANSWERED
    )
    assert contract.calls[0]["request_id"] == explicit
    assert isinstance(contract.calls[1]["request_id"], uuid.UUID)
    assert contract.calls[1]["request_id"] != explicit


def test_the_caller_reaches_the_contract(contract):
    persist_chunk_atomically(
        FakeConn(),
        request_rows=[],
        raw_rows=[_RAW_ROW],
        answered_at=_ANSWERED,
        caller="alpaca-5m-load",
    )
    assert contract.calls[0]["caller"] == "alpaca-5m-load"


def test_preread_contract_params_reach_the_contract_and_are_not_read_again(contract):
    sentinel = object()
    persist_chunk_atomically(
        FakeConn(), request_rows=[], raw_rows=[_RAW_ROW], answered_at=_ANSWERED, params=sentinel  # type: ignore[arg-type]
    )
    assert contract.calls[0]["params"] is sentinel and contract.read_params == []


def test_the_contract_settings_are_read_before_the_role_switch(contract):
    """bar_derivation_writer holds no grant on config_state, the CVR or bar_source_policy (found
    by the integration test under the real role): the read happens as the connection's user."""
    conn = FakeConn()
    persist_chunk_atomically(conn, request_rows=[], raw_rows=[_RAW_ROW], answered_at=_ANSWERED)
    statements = [sql for sql, _ in conn.statements]
    assert statements.index("SELECT <read raw params>") < statements.index(
        "SET LOCAL ROLE bar_derivation_writer"
    )
    assert contract.calls[0]["params"] == "read-params"


def test_empty_chunk_is_a_noop(contract):
    conn = FakeConn()
    result = persist_chunk_atomically(conn, request_rows=[], raw_rows=[])
    assert (result.n_requests, result.n_rows, result.ingress) == (0, 0, None)
    assert conn.statements == []


# ---------------------------------------------------------------------------
# Coverage: the third write (phase 189 plan 01, CD-03/CD-04)
# ---------------------------------------------------------------------------


def _delta(destination: str = "raw") -> CoverageDelta:
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
    # one stamp is one slot here; the real count (a stamp held under another kind) is tested below
    monkeypatch.setattr(
        _intraday_persist,
        "count_new_slots",
        lambda cur, symbol, timeframe, provider, stamps: len(set(stamps)),
    )
    return calls


def test_coverage_write_is_the_third_write_inside_the_same_transaction(contract):
    conn = FakeConn()
    result = persist_chunk_atomically(
        conn, request_rows=[_REQUEST_ROW], raw_rows=[_RAW_ROW], coverage=_delta()
    )
    assert (result.n_requests, result.n_rows) == (1, 1)
    kinds = [sql for sql, _ in conn.statements]
    assert kinds[0] == "<begin>" and kinds[-1] == "<commit>"
    inside = [sql for sql, inside_flag in conn.statements if inside_flag]
    assert inside[:6] == [
        "SELECT <read raw params>",
        "SET LOCAL ROLE bar_derivation_writer",
        "INSERT INTO ohlcv_raw (<contract>)",
        "SET LOCAL ROLE ohlcv_observation_writer",
        conn.copies[0][0],
        "<copy done>",
    ]
    assert inside[6] == "SET LOCAL ROLE bar_derivation_writer"
    held, upsert = inside[7:]
    assert "FROM ohlcv_raw" in held and upsert.lstrip().startswith("INSERT INTO ohlcv_coverage")


def test_no_coverage_means_no_coverage_sql(contract):
    conn = FakeConn()
    persist_chunk_atomically(conn, request_rows=[_REQUEST_ROW], raw_rows=[_RAW_ROW])
    assert not any("ohlcv_coverage" in sql for sql, _ in conn.statements)
    selects = [sql for sql, _ in conn.statements if sql.lstrip().startswith("SELECT")]
    assert selects == ["SELECT <read raw params>"]


def test_a_daily_refresh_runs_inside_the_same_transaction_for_the_chunks_symbols(
    contract, monkeypatch
):
    refreshed: list[tuple[list[str], str]] = []

    def _refresh(cur, symbols, *, provider):
        cur.execute("INSERT INTO ohlcv_coverage <1d refresh>", None)
        refreshed.append((sorted(symbols), provider))

    monkeypatch.setattr(_intraday_persist, "refresh_1d_bounds", _refresh)
    conn = FakeConn()
    persist_chunk_atomically(
        conn,
        request_rows=[_REQUEST_ROW],
        raw_rows=[_RAW_ROW],
        refresh_1d_provider="ibkr",
    )
    assert refreshed == [(["SPY"], "ibkr")]
    inside = [sql for sql, inside_flag in conn.statements if inside_flag]
    assert inside[-2:] == [
        "SET LOCAL ROLE bar_derivation_writer",
        "INSERT INTO ohlcv_coverage <1d refresh>",
    ]
    assert [sql for sql, _ in conn.statements][-1] == "<commit>"


def test_no_daily_refresh_unless_asked(contract, monkeypatch):
    monkeypatch.setattr(
        _intraday_persist, "refresh_1d_bounds", lambda *a, **k: pytest.fail("refreshed")
    )
    persist_chunk_atomically(FakeConn(), request_rows=[_REQUEST_ROW], raw_rows=[_RAW_ROW])


def test_failure_in_the_coverage_upsert_rolls_back_everything(contract):
    conn = FakeConn(fail_on="ohlcv_coverage")
    with pytest.raises(RuntimeError, match="forced failure"):
        persist_chunk_atomically(
            conn, request_rows=[_REQUEST_ROW], raw_rows=[_RAW_ROW], coverage=_delta()
        )
    kinds = [sql for sql, _ in conn.statements]
    assert kinds[-1] == "<rollback>"
    assert "<commit>" not in kinds
    assert contract.calls  # the bars were offered, and roll back with the coverage


def test_coverage_counts_only_rows_the_raw_write_found_new(contract, recorded_upserts):
    contract.existing = (_T0,)
    persist_chunk_atomically(
        FakeConn(),
        request_rows=[],
        answered_at=_ANSWERED,
        raw_rows=[_bar(_T0), _bar(_T1, volume=0), _bar(_T2)],
        coverage=_delta(),
    )
    (call,) = recorded_upserts
    # every new row counts, zero-volume included
    assert call["n_new_rows"] == 2
    assert (call["earliest"], call["latest"]) == (_T1, _T2)


def test_coverage_counts_every_new_row_whether_or_not_it_is_tradeable(contract, recorded_upserts):
    """Coverage describes what the vendor holds in raw: zero-volume and NULL-volume rows count
    (the old grid destination counted volume > 0 only)."""
    contract.existing = (_T0,)
    persist_chunk_atomically(
        FakeConn(),
        request_rows=[],
        answered_at=_ANSWERED,
        raw_rows=[_bar(_T0), _bar(_T1, volume=0), _bar(_T2), _bar(_T1.replace(minute=50), None)],
        coverage=_delta(),
    )
    (call,) = recorded_upserts
    assert call["n_new_rows"] == 3
    assert (call["earliest"], call["latest"]) == (_T1, _T2)


def test_bounds_fall_back_to_offered_rows_when_nothing_new(contract, recorded_upserts):
    contract.existing = (_T0, _T1)
    persist_chunk_atomically(
        FakeConn(),
        request_rows=[],
        raw_rows=[_bar(_T0), _bar(_T1)],
        answered_at=_ANSWERED,
        coverage=_delta(),
    )
    (call,) = recorded_upserts
    assert call["n_new_rows"] == 0
    assert (call["earliest"], call["latest"]) == (_T0, _T1)


def test_rows_for_another_series_are_refused_before_any_sql(contract):
    conn = FakeConn()
    with pytest.raises(ValueError, match="series"):
        persist_chunk_atomically(
            conn,
            request_rows=[_REQUEST_ROW],
            raw_rows=[_bar(_T0, symbol="QQQ")],
            coverage=_delta(),
        )
    assert conn.statements == [] and contract.calls == []


@pytest.mark.parametrize("destination", ["nowhere", "archive", "grid"])
def test_coverage_delta_rejects_every_destination_but_raw(destination):
    """The archive and the grid are gone: a caller still naming one fails loudly instead of
    crediting the wrong ledger."""
    with pytest.raises(ValueError, match="destination"):
        CoverageDelta(
            symbol="SPY", timeframe="15m", destination=destination, fetched_at=_FETCHED_AT
        )


def test_coverage_delta_defaults_to_the_ibkr_stored_state_label():
    assert _delta().provider == "ibkr"


def test_a_non_default_provider_on_the_delta_reaches_the_upsert(contract, recorded_upserts):
    """T-190-02b: the coverage row is labeled by the vendor that actually fetched the chunk.
    The helper threads the delta's provider through untouched; a second vendor's coverage can
    never silently record as ibkr."""
    conn = FakeConn()
    alpaca = CoverageDelta(
        symbol="SPY",
        timeframe="15m",
        destination="raw",
        fetched_at=_FETCHED_AT,
        provider="alpaca",
    )
    persist_chunk_atomically(
        conn, request_rows=[_REQUEST_ROW], raw_rows=[_RAW_ROW], coverage=alpaca
    )
    (call,) = recorded_upserts
    assert call["delta"].provider == "alpaca"


def test_upsert_labels_the_row_from_the_delta_provider():
    """At the SQL level: the provider parameter rides in the INSERT column list, so the
    labeled row lands even while the conflict target is still the old shape."""
    conn = FakeConn()
    upsert_coverage(
        conn.cursor(),
        CoverageDelta(symbol="SPY", timeframe="15m", destination="raw", fetched_at=_FETCHED_AT),
        earliest=_T0,
        latest=_T1,
        n_new_rows=2,
    )
    ((sql, _),) = conn.statements
    assert "provider" in sql.split("INSERT INTO ohlcv_coverage (")[1].split(")")[0]
    assert "ON CONFLICT (symbol, timeframe, provider)" in sql
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


def test_the_answering_request_time_is_the_serve_time_and_a_loader_must_name_one(contract):
    # fourth review of 191-07, finding 1: served_at is the vendor's answer time, never now()
    persist_chunk_atomically(FakeConn(), request_rows=[_REQUEST_ROW], raw_rows=[_RAW_ROW])
    assert contract.calls[0]["answered_at"] == _REQUEST_ROW[18]
    persist_chunk_atomically(
        FakeConn(), request_rows=[_REQUEST_ROW], raw_rows=[_RAW_ROW], answered_at=_ANSWERED
    )
    assert contract.calls[1]["answered_at"] == _ANSWERED
    conn = FakeConn()
    with pytest.raises(ValueError, match="answer time"):
        persist_chunk_atomically(conn, request_rows=[], raw_rows=[_RAW_ROW])
    assert conn.statements == []
