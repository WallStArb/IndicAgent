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
    day = {s for s in stamps if s.date() == date(2026, 10, 12)}
    assert len(day) == 78  # a full session: 09:30 to 15:55 EDT
    assert datetime(2026, 10, 12, 13, 30, tzinfo=UTC) in stamps  # 09:30 EDT open
    assert datetime(2026, 10, 12, 19, 55, tzinfo=UTC) in stamps  # 15:55 EDT, last bar
    assert datetime(2026, 10, 12, 20, 0, tzinfo=UTC) not in stamps  # the close itself
    assert datetime(2026, 10, 12, 13, 25, tzinfo=UTC) not in stamps  # pre-market
    # 2025-11-28 closes 13:00 EST: last bar 12:55 EST = 17:55 UTC
    assert datetime(2025, 11, 28, 17, 55, tzinfo=UTC) in stamps
    assert datetime(2025, 11, 28, 18, 0, tzinfo=UTC) not in stamps
    assert len({s for s in stamps if s.date() == date(2025, 11, 28)}) == 42  # 09:30 to 12:55 EST


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


# --- held keys (second review of plan 191-07, finding 4) ---------------------------------------


def test_held_keys_are_pending_values_or_refused_serves_that_displaced_an_own_value():
    from services.bar_selection import held_keys

    held_value = _cand("ibkr", "named", i=0, close=10.9)
    own_value = _cand("ibkr", "named", i=1, close=10.0)
    copied = _cand("ibkr", "named", i=2, close=10.7)
    unchanged = _cand("ibkr", "named", i=3, close=10.0)
    key = lambda c: (c.timestamp, c.vendor, c.kind)  # noqa: E731
    vals = lambda c, close=None: (c.open, c.high, c.low, close or c.close, c.volume)  # noqa: E731
    held = held_keys(
        [held_value, own_value, copied, unchanged],
        pending={key(held_value): {vals(held_value)}, key(own_value): {vals(own_value, 10.5)}},
        refused_served={key(copied), key(unchanged)},
        displaced={key(copied): {vals(copied, 10.0)}},
    )
    # the pending value is current; a refused serve displaced the vendor's own value. A raw value
    # other than the pending one, and a refused serve that displaced nothing, are not held.
    assert held == {key(held_value), key(copied)}


class HeldCursor(FakeCursor):
    """FakeCursor with one refused load whose value is held pending at the first slot."""

    def __init__(self, raw, canonical, pending):
        super().__init__(raw, canonical)
        self.pending = pending

    def execute(self, sql, params=None):
        if "FROM ohlcv_load WHERE" in sql and "refused" in sql:
            self.executed.append((sql, list(params or ())))
            self._result = [("R", "ibkr", T0 - timedelta(days=1))]
        elif "origin = 'pending'" in sql:
            self.executed.append((sql, list(params or ())))
            self._result = self.pending
        else:
            super().execute(sql, params)


def test_writer_never_selects_a_held_raw_value():
    held = _cand("ibkr", "named", i=0, close=10.9)
    alpaca = _cand("alpaca", "sip_rth", i=0, close=10.1)
    pending = [(held.timestamp, "ibkr", "named", 9.0, 11.0, 8.5, 10.9, 100)]
    conn = FakeConn([held, alpaca])
    conn.cur = HeldCursor([held, alpaca], [], pending)
    result = _run(conn)
    # the held IBKR value never wins, and its slot is not handed to the fallback (that would
    # splice a second vendor into the primary's session, finding 3): canonical keeps its row
    assert result.held == 1
    assert _inserts(conn) == [] and result.dropped == 0


def test_retract_deletes_a_canonical_row_only_where_no_vendor_holds_the_slot():
    from services.bar_selection import retract_unselected_slots

    kept = _cand("alpaca", "sip_rth", i=1)
    conn = FakeConn([kept])
    conn.cur.rowcount = 1
    n = retract_unselected_slots(
        conn,
        symbol="SPY",
        timeframe="5m",
        timestamps=[T0, kept.timestamp],
        policy_rows=[DEFAULT],
        kind_order=KIND_ORDER,
    )
    deletes = [p for s, p in conn.cur.executed if s.startswith("DELETE FROM market_data_ohlcv")]
    # slot 0 has no raw row left: its canonical row goes; slot 1 keeps Alpaca's
    assert n == 1 and [d[2] for d in deletes] == [T0]


# --- session-level fallback (second review of plan 191-07, finding 3) --------------------------

# 2026-10-09 09:30 to 10:00 EDT: a six-slot "session" is enough for the rule (completeness is
# relative to the slots the ranked vendors hold, not to a calendar count).
S0 = datetime(2026, 10, 9, 13, 30, tzinfo=UTC)
ALPACA_FIRST = PolicyRow("5m", "SPY", date(2026, 10, 1), date(2026, 10, 13), "alpaca", "ibkr")


def _slot(i, vendor, volume=100, day=S0):
    kind = "sip_rth" if vendor == "alpaca" else "named"
    return Candidate(
        day + timedelta(minutes=5 * i), "SPY", "5m", vendor, kind, 9, 11, 8, 10, volume
    )


def test_an_incomplete_primary_session_is_taken_whole_from_a_complete_fallback():
    """ADM 2026-10-09: Alpaca served the morning only, IBKR the whole session. Per-slot fallback
    spliced IBKR afternoons onto Alpaca mornings; the session now comes whole from IBKR."""
    alpaca = [_slot(i, "alpaca", volume=170) for i in range(3)]
    ibkr = [_slot(i, "ibkr", volume=100) for i in range(6)]
    outcome = select_slots(alpaca + ibkr, [DEFAULT, ALPACA_FIRST], KIND_ORDER)
    assert {w.vendor for w in outcome.winners} == {"ibkr"} and len(outcome.winners) == 6
    (choice,) = outcome.choices
    assert (choice.vendor, choice.complete, choice.n_slots, choice.n_vendor_slots) == (
        "ibkr",
        True,
        6,
        6,
    )
    assert choice.ranking == ("alpaca", "ibkr") and outcome.dropped == ()


def test_a_complete_primary_keeps_its_session_and_records_nothing():
    alpaca = [_slot(i, "alpaca") for i in range(6)]
    ibkr = [_slot(i, "ibkr") for i in range(4)]
    outcome = select_slots(alpaca + ibkr, [DEFAULT, ALPACA_FIRST], KIND_ORDER)
    assert {w.vendor for w in outcome.winners} == {"alpaca"} and outcome.choices == ()


def test_with_no_complete_vendor_the_session_comes_from_the_one_holding_most_and_never_mixes():
    alpaca = [_slot(i, "alpaca") for i in (0, 1, 2, 3)]
    ibkr = [_slot(i, "ibkr") for i in (0, 4)]
    outcome = select_slots(alpaca + ibkr, [DEFAULT, ALPACA_FIRST], KIND_ORDER)
    assert [w.vendor for w in outcome.winners] == ["alpaca"] * 4
    assert [ts for _s, _tf, ts in outcome.dropped] == [S0 + timedelta(minutes=20)]
    (choice,) = outcome.choices
    assert (choice.vendor, choice.complete) == ("alpaca", False)


def test_ties_between_incomplete_vendors_go_to_the_ranked_first():
    alpaca = [_slot(0, "alpaca"), _slot(1, "alpaca")]
    ibkr = [_slot(2, "ibkr"), _slot(3, "ibkr")]
    outcome = select_slots(alpaca + ibkr, [DEFAULT, ALPACA_FIRST], KIND_ORDER)
    assert {w.vendor for w in outcome.winners} == {"alpaca"} and len(outcome.dropped) == 2


def test_each_session_is_judged_on_its_own():
    day2 = S0 + timedelta(days=3)  # Monday 2026-10-12
    rows = [_slot(i, "alpaca") for i in range(2)] + [_slot(i, "ibkr") for i in range(3)]
    rows += [_slot(i, "alpaca", day=day2) for i in range(3)]
    rows += [_slot(i, "ibkr", day=day2) for i in range(3)]
    outcome = select_slots(rows, [DEFAULT, ALPACA_FIRST], KIND_ORDER)
    by_day = {(w.timestamp.date(), w.vendor) for w in outcome.winners}
    assert by_day == {(S0.date(), "ibkr"), (day2.date(), "alpaca")}


def test_a_held_candidate_counts_for_completeness_but_never_wins_or_drops():
    alpaca = [_slot(i, "alpaca") for i in range(3)]
    ibkr = [_slot(i, "ibkr") for i in range(3)]
    held = {(alpaca[1].timestamp, "alpaca", "sip_rth")}
    outcome = select_slots(alpaca + ibkr, [DEFAULT, ALPACA_FIRST], KIND_ORDER, held)
    assert [w.timestamp for w in outcome.winners] == [alpaca[0].timestamp, alpaca[2].timestamp]
    assert {w.vendor for w in outcome.winners} == {"alpaca"}
    assert outcome.n_held == 1 and outcome.dropped == ()


def test_the_writer_widens_to_whole_sessions_and_retracts_dropped_slots():
    """A window inside one session reads and writes the whole session (America/New_York
    midnight to midnight); a slot the session rule leaves out loses its canonical row."""
    alpaca = [_slot(i, "alpaca") for i in (0, 1, 2, 3)]
    ibkr = [_slot(i, "ibkr") for i in (0, 4)]
    conn = FakeConn(alpaca + ibkr)
    conn.cur.rowcount = 1
    result = _run(
        conn,
        start=S0 + timedelta(minutes=5),
        end=S0 + timedelta(minutes=10),
        policy_rows=[DEFAULT, ALPACA_FIRST],
    )
    (read,) = [p for s, p in conn.cur.executed if "FROM ohlcv_raw" in s and "load_id" not in s]
    assert read[2] == datetime(2026, 10, 9, 4, tzinfo=UTC)  # 00:00 EDT
    assert read[3] == datetime(2026, 10, 10, 4, tzinfo=UTC)
    deletes = [p for s, p in conn.cur.executed if s.startswith("DELETE")]
    assert [p[2] for p in deletes] == [S0 + timedelta(minutes=20)]
    assert (result.new, result.dropped, result.sessions_incomplete) == (4, 1, 1)


def test_the_writer_leaves_excluded_stamps_untouched():
    alpaca = [_slot(i, "alpaca") for i in (0, 1, 2, 3)]
    ibkr = [_slot(i, "ibkr") for i in (0, 4)]
    conn = FakeConn(alpaca + ibkr)
    excluded = {S0, S0 + timedelta(minutes=20)}
    result = _run(conn, policy_rows=[DEFAULT, ALPACA_FIRST], exclude=excluded)
    assert not any(s.startswith("DELETE") for s, _ in conn.cur.executed)
    ((_, params),) = _inserts(conn)
    written = {params[i] for i in range(0, len(params), 9)}
    assert written == {alpaca[i].timestamp for i in (1, 2, 3)} and result.new == 3
