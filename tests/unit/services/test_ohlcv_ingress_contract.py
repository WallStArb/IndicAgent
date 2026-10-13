"""Unit tests for services/ohlcv_ingress_contract.py (plan 185-39).

A fake cursor scripts the stored rows and records every statement; no database (todo 494).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from services.ohlcv_ingress_contract import (
    DESTINATION_ARCHIVE,
    DESTINATION_GRID,
    ContractParams,
    RevisionRefused,
    apply_ingress_contract,
    read_params,
)
from src.intelligence.bars.vendor_kind import LABEL_TO_VENDOR_KIND

_T0 = datetime(2026, 10, 1, 13, 30, tzinfo=UTC)
_PARAMS = ContractParams(max_ratio=0.02, min_stored=500)


_LABEL = "ibkr_named"  # the label IBKR fetched bars carry; the load row records vendor ibkr


def _row(i: int, close: float = 10.5, volume: int = 100, symbol: str = "ZZ185A") -> tuple:
    return (_T0 + timedelta(minutes=5 * i), symbol, "5m", 10.0, 11.0, 9.0, close, volume, _LABEL)


def _stored(rows: list[tuple]) -> list[tuple]:
    """The (timestamp, open, high, low, close, volume, source) rows a SELECT returns."""
    return [(r[0], r[3], r[4], r[5], r[6], r[7], r[8]) for r in rows]


class FakeCursor:
    def __init__(self, stored: list[tuple] | None = None, config: dict | None = None) -> None:
        self.stored = stored or []
        self.config = config
        self.statements: list[tuple[str, object]] = []
        self._result: list[tuple] = []

    def execute(self, sql: str, params: object = None) -> None:
        self.statements.append((sql, params))
        if sql.lstrip().startswith("SELECT config_key"):
            self._result = list((self.config or {}).items())
        elif sql.lstrip().startswith("SELECT"):
            self._result = self.stored

    def fetchall(self) -> list[tuple]:
        return self._result

    def sql_starting(self, prefix: str) -> list[tuple[str, object]]:
        return [(s, p) for s, p in self.statements if s.startswith(prefix)]


class Writers:
    def __init__(self) -> None:
        self.new: list[tuple] = []
        self.changed: list[tuple] = []

    def write_new(self, cur: object, rows: list[tuple]) -> None:
        self.new.extend(rows)

    def write_changed(self, cur: object, rows: list[tuple]) -> None:
        self.changed.extend(rows)


def _apply(cur: FakeCursor, rows: list[tuple], writers: Writers, **kwargs) -> int:
    return apply_ingress_contract(
        cur,
        rows,
        destination=kwargs.pop("destination", DESTINATION_GRID),
        caller="ibkr-history-fetch",
        write_new=writers.write_new,
        write_changed=writers.write_changed,
        params=kwargs.pop("params", _PARAMS),
    )


def test_the_same_answer_twice_writes_no_bar_and_no_revision_but_one_load_row():
    rows = [_row(i) for i in range(10)]
    cur, writers = FakeCursor(_stored(rows)), Writers()
    assert _apply(cur, rows, writers) == 10
    assert writers.new == [] and writers.changed == []
    assert cur.sql_starting("INSERT INTO ohlcv_revision") == []
    (load,) = cur.sql_starting("INSERT INTO ohlcv_load")
    params = load[1]
    # outcome applied, n_bars 10, n_new 0, n_changed 0, source ibkr, n_unchanged 10,
    # n_removed 0, n_archived 0 (an applied load never archives)
    assert params[3] == "ibkr" and params[6] == "applied" and params[7:10] == (10, 0, 0)
    assert params[13] == "ibkr-history-fetch" and params[14] == "market_data_ohlcv"
    assert params[15:] == (10, 0, 0)


def test_one_changed_bar_writes_one_row_and_one_revision_with_old_values():
    old = [_row(i) for i in range(10)]
    incoming = [_row(i) if i != 4 else _row(4, close=10.75) for i in range(10)]
    cur, writers = FakeCursor(_stored(old)), Writers()
    _apply(cur, incoming, writers)
    assert writers.new == [] and writers.changed == [incoming[4]]
    (revision,) = cur.sql_starting("INSERT INTO ohlcv_revision")
    values = tuple(revision[1])
    # load_id, symbol, timeframe, timestamp, old_open..old_close, old_volume, old_source, origin
    assert values[1:4] == ("ZZ185A", "5m", old[4][0])
    assert values[4:10] == (10.0, 11.0, 9.0, 10.5, 100, _LABEL)
    assert values[10:12] == LABEL_TO_VENDOR_KIND[_LABEL] and values[12] == "load"
    load_params = cur.sql_starting("INSERT INTO ohlcv_load")[0][1]
    assert load_params[0] == values[0]  # the revision hangs off the load row
    assert load_params[7:10] == (10, 0, 1) and load_params[15] == 9


def test_new_keys_go_to_the_insert_writer_and_changed_to_the_replace_writer():
    stored = [_row(0), _row(1)]
    incoming = [_row(0), _row(1, close=11.0), _row(2)]
    cur, writers = FakeCursor(_stored(stored)), Writers()
    _apply(cur, incoming, writers)
    assert writers.new == [incoming[2]] and writers.changed == [incoming[1]]


def test_tail_window_below_the_floor_is_written_and_recorded_not_refused():
    stored = [_row(i) for i in range(78)]
    incoming = [_row(i, close=10.9) if i in (10, 11) else _row(i) for i in range(78)]
    cur, writers = FakeCursor(_stored(stored)), Writers()
    _apply(cur, incoming, writers)  # 2/78 = 2.6% > 2%, but 78 < min_stored 500
    assert len(writers.changed) == 2
    assert len(cur.sql_starting("INSERT INTO ohlcv_revision")) == 1  # one batched statement
    assert len(cur.sql_starting("INSERT INTO ohlcv_revision")[0][1]) == 2 * 13


def test_a_breach_at_the_floor_is_refused_before_any_write():
    stored = [_row(i) for i in range(1000)]
    incoming = [_row(i, close=10.9) if i < 30 else _row(i) for i in range(1000)]
    cur, writers = FakeCursor(_stored(stored)), Writers()
    with pytest.raises(RevisionRefused) as caught:
        _apply(cur, incoming, writers)
    assert writers.new == [] and writers.changed == []
    assert cur.sql_starting("INSERT") == []
    assert caught.value.load.n_changed == 30 and caught.value.load.n_stored == 1000
    assert "0.0300" in caught.value.detail
    # The offered rows ride the refusal (todo 528): the raw archive captures them.
    assert caught.value.rows == incoming


def test_at_the_threshold_exactly_is_written():
    stored = [_row(i) for i in range(1000)]
    incoming = [_row(i, close=10.9) if i < 20 else _row(i) for i in range(1000)]  # 2.0%
    cur, writers = FakeCursor(_stored(stored)), Writers()
    _apply(cur, incoming, writers)
    assert len(writers.changed) == 20


def test_a_chunk_of_new_rows_is_never_refused():
    cur, writers = FakeCursor([]), Writers()
    _apply(cur, [_row(i) for i in range(2000)], writers)
    assert len(writers.new) == 2000


def test_duplicate_timestamps_in_a_chunk_resolve_last_wins():
    cur, writers = FakeCursor([]), Writers()
    first, second = _row(0, close=10.0), _row(0, close=10.25)
    assert _apply(cur, [first, second], writers) == 2  # rows offered
    assert writers.new == [second]


def test_a_source_change_alone_is_a_change():
    stored = _stored([_row(0)])
    incoming = _row(0)[:8] + ("ibkr_venue",)
    cur, writers = FakeCursor(stored), Writers()
    _apply(cur, [incoming], writers)
    assert writers.changed == [incoming]


def test_the_load_row_names_the_vendor_not_the_row_label():
    # ohlcv_load.source admits vendor names only; the bar keeps its own label (regression:
    # ibkr_named reached the load row and every IBKR write failed the CHECK, 2026-10-10..12)
    cur, writers = FakeCursor([]), Writers()
    _apply(cur, [_row(0), _row(1)[:8] + ("ibkr_venue",)], writers)
    assert cur.sql_starting("INSERT INTO ohlcv_load")[0][1][3] == "ibkr"
    assert writers.new[0][8] == _LABEL


def test_an_unmapped_source_label_is_refused_before_any_write():
    cur, writers = FakeCursor([]), Writers()
    with pytest.raises(ValueError, match="no writing vendor"):
        _apply(cur, [_row(0)[:8] + ("historical_backfill",)], writers)
    assert writers.new == [] and cur.statements == []


def test_archive_destination_reads_the_archive_table():
    cur, writers = FakeCursor([]), Writers()
    _apply(cur, [_row(0) + (None,)], writers, destination=DESTINATION_ARCHIVE)
    select = cur.sql_starting("SELECT")[0][0]
    assert "FROM ohlcv_intraday_raw_archive" in select
    assert cur.sql_starting("INSERT INTO ohlcv_load")[0][1][14] == "archive"


def test_nan_in_an_incoming_row_raises_instead_of_writing():
    cur, writers = FakeCursor([]), Writers()
    bad = _row(0)[:6] + (float("nan"),) + _row(0)[7:]
    with pytest.raises(ValueError, match="NaN"):
        _apply(cur, [bad], writers)
    assert writers.new == []


def test_an_empty_chunk_issues_no_sql_and_an_unknown_destination_is_refused():
    cur, writers = FakeCursor(), Writers()
    assert _apply(cur, [], writers) == 0 and cur.statements == []
    with pytest.raises(ValueError, match="destination"):
        _apply(cur, [_row(0)], writers, destination="d1")


def test_thresholds_come_from_config_state_and_a_missing_key_is_loud():
    keys = {
        "threshold.bar_integrity.max_revision_ratio": "0.02",
        "threshold.bar_integrity.revision_ratio_min_stored": "500",
    }
    assert read_params(FakeCursor(config=keys)) == ContractParams(0.02, 500)
    with pytest.raises(RuntimeError, match="missing from config_state"):
        read_params(FakeCursor(config={}))


def test_params_are_read_from_the_cursor_when_not_passed():
    cur, writers = (
        FakeCursor(
            [],
            config={
                "threshold.bar_integrity.max_revision_ratio": "0.02",
                "threshold.bar_integrity.revision_ratio_min_stored": "500",
            },
        ),
        Writers(),
    )
    apply_ingress_contract(
        cur,
        [_row(0)],
        destination=DESTINATION_GRID,
        caller="c",
        write_new=writers.write_new,
        write_changed=writers.write_changed,
    )
    assert cur.statements[0][0].startswith("SELECT config_key")


def test_a_waived_rescale_is_written_and_recorded_with_the_waiver_named():
    """Plan 189-10 Task 1: the update lane's escalation re-fetch after a recorded corporate
    action rewrites the whole series on the new scale; the refusal is waived exactly as D2
    waives it, and the load row says so."""
    stored = [_row(i) for i in range(1000)]
    incoming = [_row(i, close=5.25) for i in range(1000)]
    cur, writers = FakeCursor(_stored(stored)), Writers()
    apply_ingress_contract(
        cur,
        incoming,
        destination=DESTINATION_GRID,
        caller="ibkr-history-fetch",
        write_new=writers.write_new,
        write_changed=writers.write_changed,
        params=_PARAMS,
        waived=True,
    )
    assert len(writers.changed) == 1000
    (load,) = cur.sql_starting("INSERT INTO ohlcv_load")
    assert load[1][6] == "applied" and "waived" in load[1][12]
    assert len(cur.sql_starting("INSERT INTO ohlcv_revision")) == 1


def test_an_unwaived_load_row_carries_no_detail():
    rows = [_row(i) for i in range(3)]
    cur, writers = FakeCursor([]), Writers()
    _apply(cur, rows, writers)
    (load,) = cur.sql_starting("INSERT INTO ohlcv_load")
    assert load[1][12] is None


# --- apply_raw_contract (phase 191 plan 04) ------------------------------------------------

import uuid  # noqa: E402

import services.ohlcv_ingress_contract as contract  # noqa: E402
from services.ohlcv_ingress_contract import (  # noqa: E402
    RawContractParams,
    apply_raw_contract,
    read_raw_params,
)
from services.ohlcv_raw_writer import RawRow, RawWriteParams  # noqa: E402

_RAW_PARAMS = RawContractParams(
    thresholds=ContractParams(max_ratio=0.02, min_stored=500),
    write=RawWriteParams(batch_rows=50_000, future_tolerance_s=3600),
    vendor_codes=frozenset({"ibkr", "alpaca"}),
    kind_codes=frozenset({"named", "sip_rth"}),
    kind_order={"named": 1, "sip_rth": 2},
    policy_rows=(),
)
_REQUEST = uuid.uuid4()


def _raw(i: int, *, vendor="ibkr", kind="named", close=10.5, symbol="ZZ191A") -> RawRow:
    return RawRow(
        timestamp=_T0 + timedelta(minutes=5 * i),
        symbol=symbol,
        timeframe="5m",
        vendor=vendor,
        kind=kind,
        open=10.0,
        high=11.0,
        low=9.0,
        close=close,
        volume=100,
    )


class RawFakeConn:
    """Scripted connection: stored raw rows per (vendor, kind); every statement is recorded."""

    def __init__(self, stored: dict[tuple[str, str], list[tuple]] | None = None) -> None:
        self.stored = stored or {}
        self.statements: list[tuple[str, object]] = []

    def cursor(self) -> RawFakeConn._Cur:
        return RawFakeConn._Cur(self)

    class _Cur:
        def __init__(self, conn: RawFakeConn) -> None:
            self.conn = conn
            self._result: list[tuple] = []

        def __enter__(self):
            return self

        def __exit__(self, *_exc) -> None:
            return None

        def execute(self, sql: str, params: object = None) -> None:
            self.conn.statements.append((sql, params))
            if sql.startswith('SELECT "timestamp", open, high, low, close, volume, request_id'):
                _sym, _tf, vendor, kind, stamps = params
                self._result = [
                    r for r in self.conn.stored.get((vendor, kind), []) if r[0] in stamps
                ]

        def fetchall(self) -> list[tuple]:
            return self._result

    def starting(self, prefix: str) -> list[tuple[str, object]]:
        return [(s, p) for s, p in self.statements if s.startswith(prefix)]


def _stored_raw(rows: list[RawRow]) -> list[tuple]:
    return [(r.timestamp, r.open, r.high, r.low, r.close, r.volume, uuid.uuid4()) for r in rows]


@pytest.fixture
def selections(monkeypatch):
    calls: list[dict] = []

    def fake_select(conn, **kwargs):
        calls.append(kwargs)
        from services.bar_selection import SelectionResult

        return SelectionResult(
            new=len(kwargs["symbols"]), changed=0, unchanged=0, skipped_null_volume=0
        )

    monkeypatch.setattr(contract, "select_and_write", fake_select)
    return calls


def test_raw_contract_records_the_load_then_raw_then_selects(selections):
    conn = RawFakeConn()
    result = apply_raw_contract(
        conn,
        [_raw(0), _raw(1)],
        caller="ibkr-history-fetch",
        request_id=_REQUEST,
        params=_RAW_PARAMS,
    )
    kinds = [s.split("(")[0].strip()[:40] for s, _ in conn.statements]
    load = next(i for i, s in enumerate(kinds) if s.startswith("INSERT INTO ohlcv_load"))
    raw = next(i for i, s in enumerate(kinds) if s.startswith("INSERT INTO ohlcv_raw"))
    assert load < raw
    assert not conn.starting("UPDATE ohlcv_load")  # the role may INSERT a load row, not UPDATE
    load_params = conn.starting("INSERT INTO ohlcv_load")[0][1]
    assert load_params[3] == "ibkr" and load_params[14] == "raw"
    assert (result.n_offered, result.n_new, result.n_changed, result.refused) == (2, 2, 0, False)
    assert len(selections) == 1 and selections[0]["timeframe"] == "5m"
    assert result.selected_slots == 1


def test_raw_contract_cross_vendor_difference_never_refuses_or_logs_a_revision(selections):
    ibkr = [_raw(i) for i in range(600)]
    conn = RawFakeConn({("ibkr", "named"): _stored_raw(ibkr)})
    alpaca = [_raw(i, vendor="alpaca", kind="sip_rth", close=99.0) for i in range(600)]
    result = apply_raw_contract(
        conn, alpaca, caller="alpaca-5m-load", request_id=_REQUEST, params=_RAW_PARAMS
    )
    assert result.refused is False and result.n_new == 600 and result.n_changed == 0
    assert conn.starting("INSERT INTO ohlcv_revision") == []
    assert len(selections) == 1


def test_raw_contract_refused_series_is_held_as_pending_and_raw_is_untouched(selections):
    ibkr = [_raw(i) for i in range(600)]
    conn = RawFakeConn({("ibkr", "named"): _stored_raw(ibkr)})
    restated = [_raw(i, close=12.0) if i < 30 else _raw(i) for i in range(600)]  # 5% > 2%
    result = apply_raw_contract(
        conn, restated, caller="ibkr-history-fetch", request_id=_REQUEST, params=_RAW_PARAMS
    )
    assert result.refused is True and len(result.refused_series) == 1
    series = result.refused_series[0]
    assert series.n_changed == 30 and series.vendor == "ibkr" and series.n_held == 30
    # The stored rows stay current: no raw write at all, so selection cannot promote the values.
    assert conn.starting("INSERT INTO ohlcv_raw") == []
    ((_, revision),) = conn.starting("INSERT INTO ohlcv_revision")
    rows = [revision[i : i + 14] for i in range(0, len(revision), 14)]
    assert len(rows) == 30 and {r[13] for r in rows} == {"pending"}
    assert all(r[4:8] == [10.0, 11.0, 9.0, 12.0] for r in rows)
    assert result.n_held == 30 and result.n_changed == 0 and result.n_new == 0
    assert selections == []
    load = conn.starting("INSERT INTO ohlcv_load")[0][1]
    assert load[6] == "refused" and load[8:10] == (0, 0) and load[17] == 600
    assert "held as pending" in load[12]


def test_raw_contract_refused_series_holds_new_rows_too_and_writes_no_raw(selections):
    ibkr = [_raw(i) for i in range(600)]
    conn = RawFakeConn({("ibkr", "named"): _stored_raw(ibkr)})
    offered = [_raw(i, close=12.0) if i < 30 else _raw(i) for i in range(600)] + [_raw(600)]
    result = apply_raw_contract(
        conn, offered, caller="ibkr-history-fetch", request_id=_REQUEST, params=_RAW_PARAMS
    )
    assert result.refused and result.n_held == 31 and result.n_new == 0
    assert conn.starting("INSERT INTO ohlcv_raw") == []
    assert result.new_timestamps == ()


def test_raw_contract_refusal_survives_an_unchanged_reoffer(selections):
    """Refuse, then re-offer the same values: still refused, raw never moves, nothing selected."""
    ibkr = [_raw(i) for i in range(600)]
    conn = RawFakeConn({("ibkr", "named"): _stored_raw(ibkr)})
    restated = [_raw(i, close=12.0) if i < 30 else _raw(i) for i in range(600)]
    for _ in range(2):
        result = apply_raw_contract(
            conn, restated, caller="ibkr-history-fetch", request_id=_REQUEST, params=_RAW_PARAMS
        )
        assert result.refused is True and result.selected_slots == 0
    assert conn.starting("INSERT INTO ohlcv_raw") == []
    assert selections == []
    assert len(conn.starting("INSERT INTO ohlcv_load")) == 2  # each offer is recorded


def test_raw_contract_a_refused_series_does_not_stop_the_other_series_from_landing(selections):
    ibkr = [_raw(i) for i in range(600)]
    conn = RawFakeConn({("ibkr", "named"): _stored_raw(ibkr)})
    restated = [_raw(i, close=12.0) if i < 30 else _raw(i) for i in range(600)]
    alpaca = [_raw(i, vendor="alpaca", kind="sip_rth") for i in range(5)]
    result = apply_raw_contract(
        conn, restated + alpaca, caller="x", request_id=_REQUEST, params=_RAW_PARAMS
    )
    assert result.refused and result.n_new == 5
    assert len(conn.starting("INSERT INTO ohlcv_raw")) == 1
    assert selections == []  # the (symbol, timeframe) slot has a refused series: not selected


def test_raw_contract_small_window_restatement_is_written_not_refused(selections):
    ibkr = [_raw(i) for i in range(78)]
    conn = RawFakeConn({("ibkr", "named"): _stored_raw(ibkr)})
    restated = [_raw(i, close=12.0) if i < 10 else _raw(i) for i in range(78)]  # 78 < 500
    result = apply_raw_contract(
        conn, restated, caller="ibkr-history-fetch", request_id=_REQUEST, params=_RAW_PARAMS
    )
    assert result.refused is False and result.n_changed == 10
    assert len(selections) == 1


def test_raw_contract_waiver_refuses_nothing_and_names_the_waiver(selections):
    ibkr = [_raw(i) for i in range(600)]
    conn = RawFakeConn({("ibkr", "named"): _stored_raw(ibkr)})
    restated = [_raw(i, close=12.0) for i in range(600)]
    result = apply_raw_contract(
        conn,
        restated,
        caller="ibkr-history-fetch",
        request_id=_REQUEST,
        params=_RAW_PARAMS,
        waived=True,
    )
    assert result.refused is False and result.n_changed == 600
    load = conn.starting("INSERT INTO ohlcv_load")[0][1]
    assert load[6] == "applied" and "waived" in load[12]


def test_raw_contract_raw_only_timeframes_get_no_selection(selections):
    row = RawRow(_T0, "ZZ191A", "1h", "ibkr", "named", 10.0, 11.0, 9.0, 10.5, 100)
    conn = RawFakeConn()
    result = apply_raw_contract(
        conn, [row], caller="ibkr-history-fetch", request_id=_REQUEST, params=_RAW_PARAMS
    )
    assert result.n_new == 1 and selections == [] and result.selected_slots == 0


def test_raw_contract_does_not_use_the_label_vendor_map():
    import inspect

    source = inspect.getsource(contract.apply_raw_contract)
    assert "LABEL_VENDOR" not in source


def test_read_raw_params_missing_key_is_a_loud_error():
    cur = FakeCursor(config={contract.MAX_RATIO_KEY: 0.02, contract.MIN_STORED_KEY: 500})
    with pytest.raises(RuntimeError, match="missing from config_state"):
        read_raw_params(cur)
