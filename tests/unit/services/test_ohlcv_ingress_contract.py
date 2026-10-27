"""Unit tests for services/ohlcv_ingress_contract.py (plan 185-39; raw-first since phase 191).

A fake connection scripts the stored raw rows and records every statement; no database (todo 494).
The retired entry point (`apply_ingress_contract`, `RevisionRefused`, the archive destination) is
gone with plan 191-05; the DB-level proof is tests/integration/test_ingress_write_contract.py.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from services.ohlcv_ingress_contract import read_detector_params
from src.intelligence.bars.restatement import DetectorParams

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


def test_detector_thresholds_come_from_config_state_and_a_missing_key_is_loud():
    keys = {
        "threshold.bar_integrity.restatement_flag_share": "0.02",
        "threshold.bar_integrity.restatement_flag_min_stored": "500",
        "threshold.bar_integrity.restatement_signature_min_bars": "20",
        "threshold.bar_integrity.restatement_ratio_tolerance": "0.0005",
        "threshold.bar_integrity.restatement_shift_min_share": "0.5",
        "threshold.bar_integrity.restatement_ratio_min_share": "0.8",
        "threshold.bar_integrity.restatement_ratio_min_move": "0.002",
        "threshold.bar_integrity.restatement_price_tick": "0.01",
        "threshold.bar_integrity.restatement_volume_tolerance": "0.01",
        "threshold.bar_integrity.restatement_volume_min_move": "0.2",
    }
    assert read_detector_params(FakeCursor(config=keys)) == DetectorParams(
        0.02, 500, 20, 0.0005, 0.5, 0.8, 0.002, 0.01, 0.01, 0.2
    )
    with pytest.raises(RuntimeError, match="missing from config_state"):
        read_detector_params(FakeCursor(config={}))


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
        "RefusedSeries",
        "OUTCOME_REFUSED",
        "read_open_holds",
        "held_answers",
    ):
        assert not hasattr(module, retired), retired


# --- apply_raw_contract (phase 191 plan 04) ------------------------------------------------

import uuid  # noqa: E402

import services.ohlcv_ingress_contract as contract  # noqa: E402
from services.ohlcv_ingress_contract import (  # noqa: E402
    RawContractParams,
    apply_raw_contract,
)
from services.ohlcv_raw_writer import RawRow, RawWriteParams  # noqa: E402

_RAW_PARAMS = RawContractParams(
    detector=DetectorParams(0.02, 500, 20, 0.0005, 0.5),
    write=RawWriteParams(batch_rows=50_000, future_tolerance_s=3600),
    vendor_codes=frozenset({"ibkr", "alpaca"}),
    kind_codes=frozenset({"named", "sip_rth"}),
    kind_order={"named": 1, "sip_rth": 2},
    policy_rows=(),
)
_REQUEST = uuid.uuid4()
_ANSWERED = datetime(2026, 10, 1, 21, 0, tzinfo=UTC)
_EARLIER = _ANSWERED - timedelta(days=2)


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
                _sym, _tf, vendor, kind, stamps, _lo, _hi = params
                self._result = [
                    r for r in self.conn.stored.get((vendor, kind), []) if r[0] in stamps
                ]

        def fetchall(self) -> list[tuple]:
            return self._result

    def starting(self, prefix: str) -> list[tuple[str, object]]:
        return [(s, p) for s, p in self.statements if s.startswith(prefix)]


def _stored_raw(rows: list[RawRow], served_at=_EARLIER) -> list[tuple]:
    return [
        (r.timestamp, r.open, r.high, r.low, r.close, r.volume, uuid.uuid4(), served_at)
        for r in rows
    ]


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
        answered_at=_ANSWERED,
        params=_RAW_PARAMS,
    )
    kinds = [s.split("(")[0].strip()[:40] for s, _ in conn.statements]
    load = next(i for i, s in enumerate(kinds) if s.startswith("INSERT INTO ohlcv_load"))
    raw = next(i for i, s in enumerate(kinds) if s.startswith("INSERT INTO ohlcv_raw"))
    assert load < raw
    assert not conn.starting("UPDATE ohlcv_load")  # the role may INSERT a load row, not UPDATE
    load_params = conn.starting("INSERT INTO ohlcv_load")[0][1]
    assert load_params[3] == "ibkr" and load_params[14] == "raw"
    assert (result.n_offered, result.n_new, result.n_changed, result.flagged) == (2, 2, 0, ())
    assert len(selections) == 1 and selections[0]["timeframe"] == "5m"
    assert result.selected_slots == 1


def test_raw_contract_cross_vendor_difference_is_never_a_revision_or_a_flag(selections):
    ibkr = [_raw(i) for i in range(600)]
    conn = RawFakeConn({("ibkr", "named"): _stored_raw(ibkr)})
    alpaca = [_raw(i, vendor="alpaca", kind="sip_rth", close=99.0) for i in range(600)]
    result = apply_raw_contract(
        conn,
        alpaca,
        caller="alpaca-5m-load",
        request_id=_REQUEST,
        answered_at=_ANSWERED,
        params=_RAW_PARAMS,
    )
    assert result.flagged == () and result.n_new == 600 and result.n_changed == 0
    assert conn.starting("INSERT INTO ohlcv_revision") == []
    assert len(selections) == 1


def test_raw_contract_raw_only_timeframes_get_no_selection(selections):
    row = RawRow(_T0, "ZZ191A", "1h", "ibkr", "named", 10.0, 11.0, 9.0, 10.5, 100)
    conn = RawFakeConn()
    result = apply_raw_contract(
        conn,
        [row],
        caller="ibkr-history-fetch",
        request_id=_REQUEST,
        answered_at=_ANSWERED,
        params=_RAW_PARAMS,
    )
    assert result.n_new == 1 and selections == [] and result.selected_slots == 0


def test_raw_contract_does_not_use_the_label_vendor_map():
    import inspect

    source = inspect.getsource(contract.apply_raw_contract)
    assert "LABEL_VENDOR" not in source


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
        answered_at=_ANSWERED,
        params=_RAW_PARAMS,
    )
    assert result.n_unselected == 3


# --- last-wins and the restatement detector (owner decision D-191-N) -------------------------


def test_a_restatement_beyond_the_old_threshold_lands_last_wins_and_is_flagged(selections):
    ibkr = [_raw(i) for i in range(600)]
    conn = RawFakeConn({("ibkr", "named"): _stored_raw(ibkr)})
    restated = [_raw(i, close=12.0) if i < 30 else _raw(i) for i in range(600)]  # 5 % > 2 %
    result = apply_raw_contract(
        conn,
        restated,
        caller="ibkr-history-fetch",
        request_id=_REQUEST,
        answered_at=_ANSWERED,
        params=_RAW_PARAMS,
    )
    assert result.n_changed == 30 and len(selections) == 1
    assert len(conn.starting("INSERT INTO ohlcv_raw")) == 1
    ((_, revision),) = conn.starting("INSERT INTO ohlcv_revision")
    rows = [revision[i : i + 14] for i in range(0, len(revision), 14)]
    assert len(rows) == 30 and {r[13] for r in rows} == {"raw"}  # old values logged
    load = conn.starting("INSERT INTO ohlcv_load")[0][1]
    assert load[6] == "applied" and "restatement flagged" in load[12]
    ((flag,),) = [(p,) for s, p in conn.statements if s == contract._INSERT_FLAG_SQL]
    assert flag[5:7] == (600, 30) and flag[8] == ["share"]
    (flagged,) = result.flagged
    assert flagged.restatement.signatures == ("share",)


def test_a_small_window_restatement_lands_and_is_not_flagged(selections):
    ibkr = [_raw(i) for i in range(78)]
    conn = RawFakeConn({("ibkr", "named"): _stored_raw(ibkr)})
    restated = [_raw(i, close=12.0) if i < 10 else _raw(i) for i in range(78)]  # 78 < 500
    result = apply_raw_contract(
        conn,
        restated,
        caller="ibkr-history-fetch",
        request_id=_REQUEST,
        answered_at=_ANSWERED,
        params=_RAW_PARAMS,
    )
    assert result.n_changed == 10 and result.flagged == ()
    assert not [s for s, _ in conn.statements if s == contract._INSERT_FLAG_SQL]


def test_a_cross_vendor_series_and_a_restated_series_both_land(selections):
    ibkr = [_raw(i) for i in range(600)]
    conn = RawFakeConn({("ibkr", "named"): _stored_raw(ibkr)})
    restated = [_raw(i, close=12.0) if i < 30 else _raw(i) for i in range(600)]
    alpaca = [_raw(i, vendor="alpaca", kind="sip_rth") for i in range(5)]
    result = apply_raw_contract(
        conn,
        restated + alpaca,
        caller="x",
        request_id=_REQUEST,
        answered_at=_ANSWERED,
        params=_RAW_PARAMS,
    )
    assert result.n_new == 5 and result.n_changed == 30
    assert len(conn.starting("INSERT INTO ohlcv_raw")) == 2 and len(selections) == 1


# --- last-wins by serve time and the basis-change gate (fourth review of 191-07) -------------


def test_an_older_offer_is_superseded_counted_on_the_load_and_kept_out_of_the_detector(
    selections,
):
    ibkr = [_raw(i) for i in range(600)]
    later = _ANSWERED + timedelta(hours=6)
    conn = RawFakeConn({("ibkr", "named"): _stored_raw(ibkr, served_at=later)})
    replay = [_raw(i, close=12.0) for i in range(600)]  # an old artifact, answered earlier
    result = apply_raw_contract(
        conn,
        replay,
        caller="alpaca-5m-load",
        request_id=_REQUEST,
        answered_at=_ANSWERED,
        params=_RAW_PARAMS,
    )
    assert (result.n_changed, result.n_superseded, result.flagged) == (0, 600, ())
    assert conn.starting("INSERT INTO ohlcv_raw") == []
    ((_, revision),) = conn.starting("INSERT INTO ohlcv_revision")
    assert {revision[i + 13] for i in range(0, len(revision), 14)} == {"superseded"}
    load = conn.starting("INSERT INTO ohlcv_load")[0][1]
    assert load[18] == 600 and "superseded" in load[12]


def test_a_split_re_serve_is_a_basis_flag(selections):
    ibkr = [_raw(i) for i in range(78)]
    conn = RawFakeConn({("ibkr", "named"): _stored_raw(ibkr)})
    split = [
        RawRow(r.timestamp, r.symbol, r.timeframe, r.vendor, r.kind, 5.0, 5.5, 4.5, 5.25, 200)
        for r in ibkr
    ]
    result = apply_raw_contract(
        conn,
        split,
        caller="ibkr-history-fetch",
        request_id=_REQUEST,
        answered_at=_ANSWERED,
        params=_RAW_PARAMS,
    )
    assert result.n_changed == 78 and result.n_basis_flagged == 1
    (flagged,) = result.flagged
    assert flagged.restatement.basis_change and "price_ratio" in flagged.restatement.signatures


def test_a_share_only_flag_is_no_basis_flag(selections):
    ibkr = [_raw(i) for i in range(600)]
    conn = RawFakeConn({("ibkr", "named"): _stored_raw(ibkr)})
    restated = [_raw(i, close=10.51) if i < 30 else _raw(i) for i in range(600)]
    result = apply_raw_contract(
        conn,
        restated,
        caller="x",
        request_id=_REQUEST,
        answered_at=_ANSWERED,
        params=_RAW_PARAMS,
    )
    assert len(result.flagged) == 1 and result.n_basis_flagged == 0


def test_a_review_names_its_reviewer_and_never_overwrites_a_first_review():
    cur = FakeCursor()
    cur.rowcount = 1
    assert contract.mark_reviewed(cur, [_REQUEST], reviewed_by="brandon", note="split 2:1") == 1
    ((sql, params),) = cur.statements
    assert sql.startswith("UPDATE ohlcv_restatement_flag") and "reviewed_at IS NULL" in sql
    assert params == ("brandon", "split 2:1", [_REQUEST])
    with pytest.raises(ValueError, match="reviewer"):
        contract.mark_reviewed(FakeCursor(), [_REQUEST], reviewed_by=" ", note="x")
