"""Tests for services/ohlcv_raw_writer.py (phase 191 plan 02): fake connection, no DB."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from services.ohlcv_raw_writer import (
    BATCH_ROWS_KEY,
    FUTURE_TOLERANCE_KEY,
    RawRow,
    preview_series,
    read_write_params,
    write_raw,
)

VENDORS = {"ibkr", "alpaca", "tradier", "derived"}
KINDS = {"named", "venue", "sip_rth", "fallback", "5m_grid", "consolidated", "smart_trades"}
NOW = datetime(2026, 10, 12, 20, 0, tzinfo=UTC)
T0 = datetime(2026, 10, 12, 14, 30, tzinfo=UTC)
LOAD = uuid.uuid4()
REQUEST = uuid.uuid4()
OLD_REQUEST = uuid.uuid4()


class FakeCursor:
    def __init__(self, stored: list[tuple]) -> None:
        self.stored = stored
        self.executed: list[tuple[str, list]] = []
        self._result: list[tuple] = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=None):
        self.executed.append((sql, list(params or ())))
        self._result = self.stored if sql.startswith("SELECT") else []

    def fetchall(self):
        return self._result


class FakeConn:
    def __init__(self, stored: list[tuple] | None = None) -> None:
        self.cur = FakeCursor(stored or [])
        self.calls: list[str] = []

    def cursor(self):
        return self.cur

    def commit(self):
        self.calls.append("commit")

    def rollback(self):
        self.calls.append("rollback")

    def sql(self, prefix: str):
        return [(s, p) for s, p in self.cur.executed if s.startswith(prefix)]


def _row(i=0, *, vendor="ibkr", kind="named", close=10.0, volume=100, ts=None, **kw) -> RawRow:
    return RawRow(
        timestamp=ts or T0 + timedelta(minutes=5 * i),
        symbol="SPY",
        timeframe="5m",
        vendor=vendor,
        kind=kind,
        open=9.0,
        high=11.0,
        low=8.5,
        close=close,
        volume=volume,
        **kw,
    )


def _stored(row: RawRow, *, close=None, request_id=OLD_REQUEST) -> tuple:
    return (row.timestamp, row.open, row.high, row.low, close or row.close, row.volume, request_id)


def _write(conn, rows, **kw):
    args = dict(
        load_id=LOAD,
        request_id=REQUEST,
        vendor_codes=VENDORS,
        kind_codes=KINDS,
        batch_rows=50_000,
        future_tolerance_s=3600,
        now=NOW,
    )
    args.update(kw)
    return write_raw(conn, rows, **args)


def test_new_rows_insert_without_revision():
    conn = FakeConn()
    (delta,) = _write(conn, [_row(0), _row(1)])
    assert (delta.new, delta.changed, delta.unchanged, delta.n_stored) == (2, 0, 0, 0)
    ((sql, params),) = conn.sql("INSERT INTO ohlcv_raw")
    assert "ON CONFLICT" not in sql and sql.count("now()") == 2
    assert params[-2:] == [REQUEST, LOAD]
    assert not conn.sql("INSERT INTO ohlcv_revision")


def test_unchanged_writes_and_logs_nothing():
    row = _row(0)
    conn = FakeConn([_stored(row)])
    (delta,) = _write(conn, [row])
    assert (delta.new, delta.changed, delta.unchanged) == (0, 0, 1)
    assert not conn.sql("INSERT")


def test_changed_row_replaced_and_old_values_logged():
    row = _row(0, close=12.0)
    conn = FakeConn([_stored(_row(0), close=10.0)])
    (delta,) = _write(conn, [row])
    assert (delta.new, delta.changed, delta.unchanged) == (0, 1, 0)
    assert delta.changed_old[row.timestamp] == (9.0, 11.0, 8.5, 10.0, 100)
    ((rev_sql, rev),) = conn.sql("INSERT INTO ohlcv_revision")
    assert rev[0] == LOAD and rev[3] == row.timestamp
    assert rev[4:9] == [9.0, 11.0, 8.5, 10.0, 100]
    assert rev[9:] == ["ibkr_named", "ibkr", "named", OLD_REQUEST, "raw"]
    ((up_sql, up),) = conn.sql("INSERT INTO ohlcv_raw")
    assert up_sql.count("ON CONFLICT") == 1 and "DO UPDATE" in up_sql
    assert "served_at = EXCLUDED.served_at" in up_sql
    assert up[-2:] == [REQUEST, LOAD]
    # revision is written before the replacement; the writer never commits or rolls back
    order = [s for s, _ in conn.cur.executed]
    assert order.index(rev_sql) < order.index(up_sql)
    assert conn.calls == []


def test_other_vendor_at_same_slot_is_new_not_changed():
    ibkr = _row(0)
    conn = FakeConn([])  # the stored lookup is keyed by vendor, so alpaca finds nothing
    deltas = _write(conn, [ibkr, _row(0, vendor="alpaca", kind="sip_rth", close=99.0)])
    assert [(d.vendor, d.new, d.changed) for d in deltas] == [("alpaca", 1, 0), ("ibkr", 1, 0)]
    selects = conn.sql("SELECT")
    assert {tuple(p[2:4]) for _, p in selects} == {("alpaca", "sip_rth"), ("ibkr", "named")}
    assert not conn.sql("INSERT INTO ohlcv_revision")


@pytest.mark.parametrize(
    "bad,match",
    [
        (_row(vendor="nope"), "vendor 'nope'"),
        (_row(kind="nope"), "kind 'nope'"),
        (_row(vendor="synthetic_fill"), "synthetic_fill"),
        (_row(kind="synthetic_fill"), "synthetic_fill"),
        (_row(close=float("nan")), "non-finite"),
        (_row(close=float("inf")), "non-finite"),
        (_row(volume=-1), "volume"),
        (_row(vendor="derived", kind="5m_grid"), "derived"),
        (_row(vendor="derived", kind="named"), "derived"),
        (_row(kind="fallback"), "canonical only"),
        (_row(kind="5m_grid"), "canonical only"),
        (_row(ts=datetime(2026, 10, 12, 14, 30)), "naive"),
        (_row(ts=NOW + timedelta(seconds=3601)), "future bar"),
    ],
)
def test_invalid_rows_raise_before_any_sql(bad, match):
    conn = FakeConn()
    with pytest.raises(ValueError, match=match):
        _write(conn, [_row(5), bad])
    assert conn.cur.executed == []


def test_derived_vendor_and_canonical_only_kinds_are_separate_errors():
    with pytest.raises(ValueError, match="vendor 'derived'"):
        _write(FakeConn(), [_row(vendor="derived", kind="named")])
    with pytest.raises(ValueError, match="kind 'fallback'"):
        _write(FakeConn(), [_row(kind="fallback")])
    with pytest.raises(ValueError, match="kind '5m_grid'"):
        _write(FakeConn(), [_row(vendor="ibkr", kind="5m_grid")])


def test_future_tolerance_boundary_is_inclusive():
    conn = FakeConn()
    _write(conn, [_row(ts=NOW + timedelta(seconds=3600))])
    assert conn.sql("INSERT INTO ohlcv_raw")


@pytest.mark.parametrize("missing", ["load_id", "request_id"])
def test_missing_lineage_ids_raise(missing):
    with pytest.raises(ValueError, match="load_id and request_id"):
        _write(FakeConn(), [_row()], **{missing: None})


def test_batches_respect_the_parameter_limit_and_batch_rows():
    conn = FakeConn()
    rows = [_row(i) for i in range(7)]
    _write(conn, rows, batch_rows=3)
    sizes = [sql.count("now()") for sql, _ in conn.sql("INSERT INTO ohlcv_raw")]
    assert sizes == [3, 3, 1]
    big = FakeConn()
    _write(big, [_row(-i) for i in range(6000)], batch_rows=50_000)
    for sql, params in big.sql("INSERT INTO ohlcv_raw"):
        assert len(params) <= 65535
    assert len(big.sql("INSERT INTO ohlcv_raw")) == 2


def test_later_duplicate_in_chunk_wins():
    conn = FakeConn()
    (delta,) = _write(conn, [_row(0, close=10.0), _row(0, close=11.0)])
    assert delta.new == 1
    ((_, params),) = conn.sql("INSERT INTO ohlcv_raw")
    assert 11.0 in params and 10.0 not in params


def test_empty_input_does_nothing():
    conn = FakeConn()
    assert _write(conn, []) == []
    assert conn.cur.executed == []


@pytest.mark.asyncio
async def test_read_write_params_reads_both_apr_keys():
    seen = {}

    class Config:
        async def get(self, key, default=None):
            seen[key] = default
            return {BATCH_ROWS_KEY: "4000", FUTURE_TOLERANCE_KEY: 60}[key]

    params = await read_write_params(Config())
    assert (params.batch_rows, params.future_tolerance_s) == (4000, 60)
    assert set(seen) == {BATCH_ROWS_KEY, FUTURE_TOLERANCE_KEY}


def test_preview_series_matches_write_raw_counts_and_writes_nothing():
    stored = [_stored(_row(0)), _stored(_row(1))]
    rows = [_row(0), _row(1, close=11.0), _row(2)]
    conn = FakeConn(stored)
    delta = preview_series(conn, rows)
    assert (delta.n_stored, delta.new, delta.changed, delta.unchanged) == (2, 1, 1, 1)
    assert [s for s, _ in conn.cur.executed if not s.startswith("SELECT")] == []
    written = _write(FakeConn(stored), rows)[0]
    assert (written.new, written.changed, written.unchanged) == (1, 1, 1)


def test_preview_series_refuses_more_than_one_series():
    with pytest.raises(ValueError, match="exactly one series"):
        preview_series(FakeConn(), [_row(0), _row(1, vendor="alpaca", kind="sip_rth")])
