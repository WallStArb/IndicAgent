"""Unit tests for services/ohlcv_ingress_contract.py (plan 185-39; raw-first since phase 191).

A fake connection scripts the stored raw rows and records every statement; no database (todo 494).
The retired entry point (`apply_ingress_contract`, `RevisionRefused`, the archive destination) is
gone with plan 191-05; the DB-level proof is tests/integration/test_ingress_write_contract.py.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from services.ohlcv_ingress_contract import ContractParams, read_params

_T0 = datetime(2026, 10, 1, 13, 30, tzinfo=UTC)


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


def test_thresholds_come_from_config_state_and_a_missing_key_is_loud():
    keys = {
        "threshold.bar_integrity.max_revision_ratio": "0.02",
        "threshold.bar_integrity.revision_ratio_min_stored": "500",
    }
    assert read_params(FakeCursor(config=keys)) == ContractParams(0.02, 500)
    with pytest.raises(RuntimeError, match="missing from config_state"):
        read_params(FakeCursor(config={}))


def test_the_retired_entry_point_and_refusal_exception_are_gone():
    import services.ohlcv_ingress_contract as module

    for retired in (
        "apply_ingress_contract",
        "RevisionRefused",
        "record_refused_load",
        "read_stored",
        "DESTINATION_ARCHIVE",
        "DESTINATION_GRID",
        "write_market_data_batches",
        "MARKET_DATA_INSERT_HEAD",
        "LABEL_VENDOR",
    ):
        assert not hasattr(module, retired), retired


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


def test_raw_contract_counts_a_null_volume_winner_with_the_unselected_slots(monkeypatch):
    """191-07 review (low): the writer skips a NULL-volume winner and the slot keeps its previous
    canonical row, so the offered row reached raw and no canonical row took it."""
    from services.bar_selection import SelectionResult

    def fake_select(conn, **kwargs):
        return SelectionResult(new=0, changed=0, unchanged=0, skipped_null_volume=2, unselected=1)

    monkeypatch.setattr(contract, "select_and_write", fake_select)
    result = apply_raw_contract(
        RawFakeConn(),
        [_raw(0)],
        caller="ibkr-history-fetch",
        request_id=_REQUEST,
        params=_RAW_PARAMS,
    )
    assert result.n_unselected == 3


# --- a refusal holds against small asks (third review of plan 191-07, finding 2) ------------

_REFUSED_AT = datetime(2026, 10, 12, 12, 14, tzinfo=UTC)


class HeldFakeConn(RawFakeConn):
    """RawFakeConn plus pending holds of a refused load (timestamp -> values) and the loads that
    wrote the current raw rows (timestamp -> (loaded_at, outcome, destination, caller))."""

    def __init__(self, stored, holds, writers=None) -> None:
        super().__init__(stored)
        self.holds = holds
        self.writers = writers or {}

    def cursor(self):
        conn = self
        base = RawFakeConn._Cur(self)
        execute = base.execute

        def run(sql, params=None):
            execute(sql, params)
            if sql == contract._OPEN_HOLDS_SQL:
                stamps = params[4]
                base._result = [
                    (ts, *values, _REFUSED_AT) for ts, values in conn.holds.items() if ts in stamps
                ]
            elif sql == contract._RAW_WRITER_AT_SQL:
                stamps = params[4]
                base._result = [(ts, *w) for ts, w in conn.writers.items() if ts in stamps]

        base.execute = run
        return base


def _vals(row: RawRow) -> tuple:
    return (row.open, row.high, row.low, row.close, row.volume)


def test_a_one_session_ask_cannot_land_values_a_refused_load_holds(selections):
    # GE d2adcf51: refused at 40 % over its span; a one-session ask (78 bars, under the 500-row
    # minimum) serving the same two-decimal values must not land them (old code: accepted)
    stored = [_raw(i) for i in range(78)]
    held = {_raw(i).timestamp: _vals(_raw(i, close=10.0)) for i in range(0, 78, 2)}
    conn = HeldFakeConn({("ibkr", "named"): _stored_raw(stored)}, held)
    offer = [_raw(i, close=10.0) if i % 2 == 0 else _raw(i) for i in range(78)]
    result = apply_raw_contract(
        conn, offer, caller="ibkr-history-fetch", request_id=_REQUEST, params=_RAW_PARAMS
    )
    assert result.refused and result.n_changed == 0 and result.n_held == 39
    assert conn.starting("INSERT INTO ohlcv_raw") == [] and selections == []
    assert {a for *_, a in result.held_answers} == {contract.HELD_OFFER}
    assert len(result.held_answers) == 39
    load = conn.starting("INSERT INTO ohlcv_load")[0][1]
    assert load[6] == "refused" and "explicit decision" in load[12]


def test_a_re_serve_of_a_withdrawn_held_key_is_reported_not_landed(selections):
    # ADM 2026-10-01: raw holds no row (withdrawn), the held offer is pending; the vendor
    # serves the held value again: verified and reported, still held
    stored = [_raw(i) for i in range(10)]
    held = {_raw(10).timestamp: _vals(_raw(10))}
    conn = HeldFakeConn({("ibkr", "named"): _stored_raw(stored)}, held)
    result = apply_raw_contract(
        conn,
        [_raw(i) for i in range(11)],
        caller="ibkr-history-fetch",
        request_id=_REQUEST,
        params=_RAW_PARAMS,
    )
    assert result.refused and result.n_new == 0
    assert result.held_answers == (
        ("ZZ191A", "5m", "ibkr", "named", _raw(10).timestamp, contract.HELD_OFFER),
    )
    assert conn.starting("INSERT INTO ohlcv_raw") == []


def test_an_ask_serving_the_stored_value_at_a_held_key_is_judged_normally(selections):
    stored = [_raw(i) for i in range(10)]
    held = {_raw(3).timestamp: _vals(_raw(3, close=10.0))}
    conn = HeldFakeConn({("ibkr", "named"): _stored_raw(stored)}, held)
    offer = [_raw(i) for i in range(10)] + [_raw(10)]
    result = apply_raw_contract(
        conn, offer, caller="ibkr-history-fetch", request_id=_REQUEST, params=_RAW_PARAMS
    )
    assert not result.refused and result.n_new == 1
    assert [a for *_, a in result.held_answers] == [contract.STORED_VALUE]


def test_a_new_value_at_a_held_key_is_refused_and_one_answered_again_holds_nothing(selections):
    stored = [_raw(i) for i in range(10)]
    held = {_raw(3).timestamp: _vals(_raw(3, close=10.0))}
    offer = [_raw(i, close=10.7) if i == 3 else _raw(i) for i in range(10)]
    conn = HeldFakeConn({("ibkr", "named"): _stored_raw(stored)}, held)
    result = apply_raw_contract(
        conn, offer, caller="ibkr-history-fetch", request_id=_REQUEST, params=_RAW_PARAMS
    )
    assert result.refused and [a for *_, a in result.held_answers] == [contract.NEW_VALUE]
    # the current raw row was written by an applied raw serve after the refusal: no hold left
    later = (_REFUSED_AT + timedelta(hours=1), "applied", "raw", "ibkr-history-fetch")
    conn = HeldFakeConn(
        {("ibkr", "named"): _stored_raw(stored)}, held, writers={_raw(3).timestamp: later}
    )
    result = apply_raw_contract(
        conn, offer, caller="ibkr-history-fetch", request_id=_REQUEST, params=_RAW_PARAMS
    )
    assert not result.refused and result.n_changed == 1 and result.held_answers == ()
