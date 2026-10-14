"""Tests for src/intelligence/bars/selection.py and services/bar_selection.py (phase 191 plan 02)."""

from __future__ import annotations

import random
from datetime import UTC, date, datetime, timedelta

import pytest

from services.bar_selection import SelectionResult, canonical_columns, select_and_write
from src.intelligence.bars.selection import (
    Candidate,
    PolicyRow,
    partition_session,
    rank_vendors,
    rth_grid_stamps,
    select_all,
    select_slot,
    select_slots,
    session_date,
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
    assert "DO UPDATE" in sql  # new slots carry the upsert tail too (plan 191-07 review)
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


# --- plan 191-07 review amendments: session rule, session-date spans, lock, unselected counts ----


def _at(ts, vendor="alpaca", kind="sip_rth", symbol="SPY", tf="5m", volume=100):
    return Candidate(ts, symbol, tf, vendor, kind, 9.0, 11.0, 8.5, 10.0, volume)


def test_rth_grid_is_open_inclusive_close_exclusive_with_early_closes():
    stamps = rth_grid_stamps("5m", 2025, 2026)
    day = datetime(2026, 10, 12, tzinfo=UTC)
    assert datetime(2026, 10, 12, 13, 30, tzinfo=UTC) in stamps  # 09:30 EDT open
    assert datetime(2026, 10, 12, 19, 55, tzinfo=UTC) in stamps  # 15:55 EDT, last bar
    assert datetime(2026, 10, 12, 20, 0, tzinfo=UTC) not in stamps  # the close itself
    assert datetime(2026, 10, 12, 13, 25, tzinfo=UTC) not in stamps  # pre-market
    # 2025-11-28 closes 13:00 EST: last bar 12:55 EST = 17:55 UTC
    assert datetime(2025, 11, 28, 17, 55, tzinfo=UTC) in stamps
    assert datetime(2025, 11, 28, 18, 0, tzinfo=UTC) not in stamps
    assert day.date() == date(2026, 10, 12)


def test_extended_hours_candidates_never_enter_selection():
    pre = datetime(2026, 10, 12, 8, 30, tzinfo=UTC)  # 04:30 EDT
    post = datetime(2026, 10, 12, 20, 5, tzinfo=UTC)  # 16:05 EDT
    in_session = _at(T0)
    kept, dropped = partition_session([_at(pre), in_session, _at(post)])
    assert kept == [in_session] and len(dropped) == 2
    outcome = select_slots([_at(pre), in_session, _at(post)], [DEFAULT], KIND_ORDER)
    assert [c.timestamp for c in outcome.winners] == [T0]
    assert outcome.n_off_grid == 2


def test_ibkr_own_session_is_not_filtered_by_the_calendar():
    # IBKR serves bars to 16:00 ET on an early-close day; canonical holds them (CMCSA 2007-12-24).
    after_early_close = datetime(2007, 12, 24, 18, 5, tzinfo=UTC)
    stamp = _at(after_early_close, vendor="ibkr", kind="named")
    old = PolicyRow("5m", None, date(2000, 1, 1), None, "ibkr", "alpaca")
    assert select_all([stamp], [old], KIND_ORDER) == [stamp]
    assert select_all([_at(after_early_close)], [old], KIND_ORDER) == []  # sip_rth is bound


def test_no_session_grid_for_other_timeframes():
    one_minute = _at(
        datetime(2026, 10, 12, 8, 30, tzinfo=UTC), vendor="ibkr", kind="named", tf="1m"
    )
    policy = PolicyRow("1m", None, date(2020, 1, 1), None, "ibkr", None)
    assert select_all([one_minute], [policy], KIND_ORDER) == [one_minute]


def test_policy_span_matches_the_session_date_not_the_utc_date():
    # 19:30 EST on 2026-11-02 is 00:30 UTC on 2026-11-03: the 11-02 session.
    stamp = datetime(2026, 11, 3, 0, 30, tzinfo=UTC)
    assert session_date(stamp) == date(2026, 11, 2)
    span = PolicyRow("5m", "SPY", date(2026, 10, 1), date(2026, 11, 3), "alpaca", "ibkr")
    ranking = rank_vendors([DEFAULT, span], "SPY", "5m", session_date(stamp))
    assert ranking == ["alpaca", "ibkr"]
    # an in-session stamp keeps its UTC date as the session date (EDT, same date)
    assert session_date(T0) == date(2026, 10, 12)


def test_unselected_counts_a_slot_no_ranked_vendor_holds():
    ibkr_only = PolicyRow("5m", None, date(2020, 1, 1), None, "ibkr", None)
    outcome = select_slots(
        [_cand("alpaca", "sip_rth", i=0), _cand("ibkr", "named", i=1)], [ibkr_only], KIND_ORDER
    )
    assert (outcome.n_slots, outcome.n_unselected, len(outcome.winners)) == (2, 1, 1)


def test_writer_locks_each_symbol_series_in_sorted_order_before_reading():
    conn = FakeConn([_cand("ibkr", "named")])
    _run(conn, symbols=["SPY", "AAPL"])
    sql_seq = [s for s, _ in conn.cur.executed]
    assert sql_seq[0].startswith("SELECT pg_advisory_xact_lock")
    keys = [p[0] for s, p in conn.cur.executed if "pg_advisory_xact_lock" in s]
    assert keys == ["bar_selection|AAPL|5m", "bar_selection|SPY|5m"]
    assert "FROM ohlcv_raw" in sql_seq[1]


def test_writer_counts_unselected_and_off_grid():
    ibkr_only = PolicyRow("5m", None, date(2020, 1, 1), None, "ibkr", None)
    pre = _at(datetime(2026, 10, 12, 8, 30, tzinfo=UTC))
    conn = FakeConn([_cand("alpaca", "sip_rth"), pre])
    result = _run(conn, policy_rows=[ibkr_only])
    assert (result.unselected, result.off_grid, result.new) == (1, 1, 0)
