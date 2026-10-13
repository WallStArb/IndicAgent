"""Tests for src/intelligence/bars/selection.py and services/bar_selection.py (phase 191 plan 02)."""

from __future__ import annotations

import random
from datetime import UTC, date, datetime, timedelta

import pytest

from services.bar_selection import SelectionResult, canonical_columns, select_and_write
from src.intelligence.bars.selection import (
    Candidate,
    PolicyRow,
    rank_vendors,
    select_all,
    select_slot,
)

KIND_ORDER = {
    "named": 1,
    "venue": 2,
    "continuous": 3,
    "generic": 5,
    "smart_adjusted": 7,
    "sip_rth": 10,
}
T0 = datetime(2026, 10, 12, 14, 30, tzinfo=UTC)
DEFAULT = PolicyRow("5m", None, date(2020, 1, 1), None, "ibkr", "alpaca")


def _cand(vendor="ibkr", kind="named", i=0, symbol="SPY", close=10.0, volume=100):
    return Candidate(
        T0 + timedelta(minutes=5 * i), symbol, "5m", vendor, kind, 9.0, 11.0, 8.5, close, volume
    )


def test_rank_symbol_row_beats_default_and_lists_fallback():
    spy = PolicyRow("5m", "SPY", date(2026, 1, 1), None, "alpaca", None)
    assert rank_vendors([DEFAULT, spy], "SPY", "5m", date(2026, 10, 1)) == ["alpaca"]
    assert rank_vendors([DEFAULT, spy], "QQQ", "5m", date(2026, 10, 1)) == ["ibkr", "alpaca"]
    assert rank_vendors([DEFAULT, spy], "SPY", "5m", date(2025, 12, 31)) == ["ibkr", "alpaca"]


def test_rank_end_date_is_exclusive_and_gap_raises():
    closed = PolicyRow("5m", None, date(2026, 1, 1), date(2026, 6, 1), "ibkr", None)
    assert rank_vendors([closed], "SPY", "5m", date(2026, 5, 31)) == ["ibkr"]
    with pytest.raises(LookupError, match="no bar_source_policy"):
        rank_vendors([closed], "SPY", "5m", date(2026, 6, 1))
    with pytest.raises(LookupError):
        rank_vendors([closed], "SPY", "1m", date(2026, 5, 31))


def test_select_prefers_ranking_then_kind_order():
    held = [_cand("alpaca", "sip_rth"), _cand("ibkr", "generic"), _cand("ibkr", "venue")]
    assert select_slot(held, ["ibkr", "alpaca"], KIND_ORDER).kind == "venue"
    assert select_slot(held, ["alpaca", "ibkr"], KIND_ORDER).vendor == "alpaca"


def test_select_never_picks_unranked_derived_or_adjusted():
    assert select_slot([_cand("alpaca", "sip_rth")], ["ibkr"], KIND_ORDER) is None
    assert select_slot([_cand("derived", "named")], ["derived", "ibkr"], KIND_ORDER) is None
    assert select_slot([_cand("ibkr", "smart_adjusted")], ["ibkr"], KIND_ORDER) is None
    assert select_slot([], ["ibkr"], KIND_ORDER) is None


def test_select_falls_to_next_vendor_when_primary_has_no_row():
    assert (
        select_slot([_cand("alpaca", "sip_rth")], ["ibkr", "alpaca"], KIND_ORDER).vendor == "alpaca"
    )


def test_select_unknown_kind_raises():
    with pytest.raises(KeyError, match="mystery"):
        select_slot([_cand("ibkr", "mystery")], ["ibkr"], KIND_ORDER)


def test_selection_is_order_independent():
    rng = random.Random(7)
    cands = [
        _cand(v, k, i, close=float(10 + j))
        for i in range(20)
        for j, (v, k) in enumerate(
            [("ibkr", "named"), ("ibkr", "venue"), ("alpaca", "sip_rth"), ("ibkr", "generic")]
        )
        if rng.random() < 0.7
    ]
    expected = select_all(cands, [DEFAULT], KIND_ORDER)
    assert expected
    for seed in range(25):
        shuffled = cands[:]
        random.Random(seed).shuffle(shuffled)
        assert select_all(shuffled, [DEFAULT], KIND_ORDER) == expected


def test_lower_ranked_arrival_changes_nothing():
    primary = _cand("ibkr", "named", close=10.0)
    before = select_all([primary], [DEFAULT], KIND_ORDER)
    after = select_all([primary, _cand("alpaca", "sip_rth", close=99.0)], [DEFAULT], KIND_ORDER)
    assert before == after


# --- the writer, against a fake connection -----------------------------------------------------


class FakeCursor:
    def __init__(self, raw, canonical):
        self.raw, self.canonical = raw, canonical
        self.executed: list[tuple[str, list]] = []
        self._result: list[tuple] = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=None):
        self.executed.append((sql, list(params or ())))
        if "FROM ohlcv_raw" in sql:
            self._result = [
                (
                    c.timestamp,
                    c.symbol,
                    c.timeframe,
                    c.vendor,
                    c.kind,
                    c.open,
                    c.high,
                    c.low,
                    c.close,
                    c.volume,
                )
                for c in self.raw
            ]
        elif "FROM market_data_ohlcv" in sql:
            self._result = self.canonical
        else:
            self._result = []

    def fetchall(self):
        return self._result


class FakeConn:
    def __init__(self, raw, canonical=()):
        self.cur = FakeCursor(raw, list(canonical))

    def cursor(self):
        return self.cur


def _run(conn, **kw):
    args = dict(
        symbols=["SPY"],
        timeframe="5m",
        start=T0 - timedelta(days=1),
        end=T0 + timedelta(days=1),
        policy_rows=[DEFAULT],
        kind_order=KIND_ORDER,
        batch_rows=1000,
    )
    args.update(kw)
    return select_and_write(conn, **args)


def _inserts(conn):
    return [(s, p) for s, p in conn.cur.executed if s.startswith("INSERT")]


def test_writer_inserts_new_winner_with_label():
    conn = FakeConn([_cand("ibkr", "named"), _cand("alpaca", "sip_rth", close=99.0)])
    assert _run(conn) == SelectionResult(1, 0, 0, 0)
    ((sql, params),) = _inserts(conn)
    assert "ON CONFLICT" not in sql
    assert params[-1] == "ibkr_named" and params[6] == 10.0


def test_writer_replaces_changed_and_skips_unchanged():
    c0, c1 = _cand(i=0), _cand(i=1, close=12.0)
    canonical = [
        (c0.timestamp, 9.0, 11.0, 8.5, 10.0, 100, "ibkr_named"),
        (c1.timestamp, 9.0, 11.0, 8.5, 10.0, 100, "ibkr_named"),
    ]
    conn = FakeConn([c0, c1], canonical)
    assert _run(conn) == SelectionResult(0, 1, 1, 0)
    ((sql, params),) = _inserts(conn)
    assert "DO UPDATE" in sql and params[6] == 12.0
    assert not any(s.startswith("UPDATE") for s, _ in conn.cur.executed)


def test_writer_skips_null_volume_winner_without_substituting():
    conn = FakeConn([_cand("ibkr", "named", volume=None), _cand("alpaca", "sip_rth")])
    assert _run(conn) == SelectionResult(0, 0, 0, 1)
    assert _inserts(conn) == []


def test_writer_refuses_non_direct_timeframes_and_missing_policy():
    for tf in ("1d", "15m", "1h"):
        with pytest.raises(ValueError, match="direct timeframes"):
            _run(FakeConn([]), timeframe=tf)
    with pytest.raises(LookupError):
        _run(FakeConn([_cand()]), policy_rows=[])


def test_canonical_columns_maps_label_and_raises_without_one():
    assert canonical_columns("alpaca", "sip_rth") == "alpaca"
    with pytest.raises(KeyError):
        canonical_columns("ibkr", "smart_trades")
