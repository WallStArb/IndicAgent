"""Tests for scripts/infrastructure/backfill/_d1_gaps.py (plan 185-18 task 1a).

`plan_gaps` (src/intelligence/bars/gap_plan.py) is the one pure definition of a
missing bar; _d1_gaps is its psycopg SQL-reading wrapper for the fetch pipeline.
These tests pin the wrapper's contract against a sequenced fake connection: the
two queries it issues (this vendor's own raw rows, this vendor's answered request
windows), the vendor scoping of both, the empty-history folding with its freshness
gate, and the plan's mandated case -- a fully fetched name with a recorded no_data head returns
no ranges; the same name with the no_data row deleted returns the head.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta

import pytest

from scripts.infrastructure.backfill._d1_gaps import (
    _MATCH_S_SQL,
    daily_no_data_coverage,
    detect_gaps_1d_from_d1,
    detect_gaps_from_record,
    load_answered_windows,
    subtract_windows,
)
from scripts.infrastructure.backfill._empty_history import EmptyRange
from src.intelligence.bars.gap_plan import AnsweredWindows, live_partials

_Q = timedelta(minutes=15)


def _t(hour: int, minute: int) -> datetime:
    return datetime(2026, 1, 2, hour, minute, tzinfo=UTC)


class _FakeCursor:
    def __init__(self, conn: _FakeConn) -> None:
        self._conn = conn

    def __enter__(self) -> _FakeCursor:
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def execute(self, sql: str, params: object = None) -> None:
        self._conn.queries.append((sql, params))

    def fetchall(self) -> list:
        if self._conn.queries and self._conn.queries[-1][0] == _MATCH_S_SQL:
            return [("5",)]  # the APR request-to-load match tolerance (config_state)
        return self._conn.results.pop(0)


class _FakeConn:
    """Answers fetchall() calls in order; records every (sql, params)."""

    def __init__(self, *results: list) -> None:
        self.results = list(results)
        self.queries: list[tuple[str, object]] = []

    def cursor(self) -> _FakeCursor:
        return _FakeCursor(self)


_NOW = datetime(2026, 1, 3, 0, 0, tzinfo=UTC)
_HEAD_SLOTS = [_t(14, 30), _t(14, 45), _t(15, 0), _t(15, 15), _t(15, 30)]
_STORED_TAIL = [(_t(15, 0),), (_t(15, 15),), (_t(15, 30),)]


class TestDetectGapsFromRecord:
    def test_fully_fetched_name_with_a_recorded_no_data_head_returns_no_ranges(self):
        conn = _FakeConn(_STORED_TAIL, [(_t(14, 30), _t(15, 0), None)])
        plan = detect_gaps_from_record(
            conn, "SPY", "15m", _t(14, 30), _t(15, 30), _HEAD_SLOTS, vendor="ibkr", now=_NOW
        )
        assert plan == []

    def test_same_name_with_the_no_data_row_deleted_returns_the_head(self):
        conn = _FakeConn(_STORED_TAIL, [])
        plan = detect_gaps_from_record(
            conn, "SPY", "15m", _t(14, 30), _t(15, 30), _HEAD_SLOTS, vendor="ibkr", now=_NOW
        )
        # End-exclusive: the head window ends at the last missing slot's end.
        assert plan == [(_t(14, 30), _t(15, 0))]

    def test_windows_are_end_exclusive_one_slot_gap_is_one_bar_interval(self):
        conn = _FakeConn([(_t(14, 45),)], [])
        plan = detect_gaps_from_record(
            conn, "SPY", "15m", _t(14, 30), _t(15, 0), _HEAD_SLOTS[:3], vendor="ibkr", now=_NOW
        )
        assert plan == [(_t(14, 30), _t(14, 45))]

    def test_slot_still_forming_stays_a_gap_capped_at_the_run_end(self):
        conn = _FakeConn([], [])
        plan = detect_gaps_from_record(
            conn,
            "SPY",
            "15m",
            _t(15, 0),
            _t(15, 7),
            [_t(15, 0), _t(15, 15)],
            vendor="ibkr",
            now=_NOW,
        )
        # The 15:15 slot starts after the run's end and is not planned; the
        # forming 15:00 slot is asked for, capped at the run's end.
        assert plan == [(_t(15, 0), _t(15, 7))]

    def test_every_intraday_timeframe_reads_the_vendors_own_raw_rows(self):
        for tf in ("5m", "15m", "1h"):
            conn = _FakeConn([], [], [], [])  # 5m adds the Alpaca windows and applied loads
            detect_gaps_from_record(
                conn, "SPY", tf, _t(14, 30), _t(15, 30), [], vendor="ibkr", now=_NOW
            )
            stored_sql = conn.queries[0][0]
            assert "FROM ohlcv_raw" in stored_sql
            assert "vendor = %s" in stored_sql
            assert "ohlcv_intraday_raw_archive" not in stored_sql
            assert "market_data_ohlcv" not in stored_sql

    def test_stored_query_is_scoped_to_the_series_vendor_and_window(self):
        conn = _FakeConn([], [])
        detect_gaps_from_record(
            conn, "SPY", "15m", _t(14, 30), _t(15, 30), _HEAD_SLOTS, vendor="alpaca", now=_NOW
        )
        sql, params = conn.queries[0]
        assert "symbol = %s" in sql and "timeframe = %s" in sql
        assert '"timestamp" >= %s' in sql and '"timestamp" <= %s' in sql
        assert params == ("SPY", "15m", "alpaca", _t(14, 30), _t(15, 30))

    def test_the_answered_window_read_is_scoped_to_the_same_vendor(self):
        conn = _FakeConn([], [], [], [])  # 5m adds the Alpaca windows and applied loads
        detect_gaps_from_record(
            conn, "SPY", "5m", _t(14, 30), _t(15, 30), _HEAD_SLOTS, vendor="alpaca", now=_NOW
        )
        sql, params = conn.queries[2]
        assert "r.source = %(vendor)s" in sql
        assert params["vendor"] == "alpaca"

    def test_a_fresh_confirmed_empty_span_suppresses_the_head(self):
        empty = EmptyRange(
            empty_from=_t(14, 30),
            empty_through=_t(14, 45),
            verified_at=_NOW - timedelta(days=1),
            n_confirming_chunks=3,
        )
        conn = _FakeConn(_STORED_TAIL, [])
        skipped: list[EmptyRange] = []
        plan = detect_gaps_from_record(
            conn,
            "SPY",
            "15m",
            _t(14, 30),
            _t(15, 30),
            _HEAD_SLOTS,
            vendor="ibkr",
            empty=empty,
            now=_NOW,
            reverify_days=7,
            min_confirmations=2,
            on_skip=skipped.append,
        )
        assert plan == []
        assert skipped == [empty]

    def test_a_stale_empty_span_suppresses_nothing(self):
        empty = EmptyRange(
            empty_from=_t(14, 30),
            empty_through=_t(14, 45),
            verified_at=_NOW - timedelta(days=30),
            n_confirming_chunks=3,
        )
        conn = _FakeConn(_STORED_TAIL, [])
        skipped: list[EmptyRange] = []
        plan = detect_gaps_from_record(
            conn,
            "SPY",
            "15m",
            _t(14, 30),
            _t(15, 30),
            _HEAD_SLOTS,
            vendor="ibkr",
            empty=empty,
            now=_NOW,
            reverify_days=7,
            min_confirmations=2,
            on_skip=skipped.append,
        )
        assert plan == [(_t(14, 30), _t(15, 0))]
        assert skipped == []

    def test_an_underconfirmed_empty_span_suppresses_nothing(self):
        empty = EmptyRange(
            empty_from=_t(14, 30),
            empty_through=_t(14, 45),
            verified_at=_NOW - timedelta(days=1),
            n_confirming_chunks=1,
        )
        conn = _FakeConn(_STORED_TAIL, [])
        plan = detect_gaps_from_record(
            conn,
            "SPY",
            "15m",
            _t(14, 30),
            _t(15, 30),
            _HEAD_SLOTS,
            vendor="ibkr",
            empty=empty,
            now=_NOW,
            reverify_days=7,
            min_confirmations=2,
        )
        assert plan == [(_t(14, 30), _t(15, 0))]

    def test_timeframes_outside_the_record_planner_are_refused(self):
        conn = _FakeConn()
        with pytest.raises(ValueError, match="1m"):
            detect_gaps_from_record(
                conn, "SPY", "1m", _t(14, 30), _t(15, 30), [], vendor="ibkr", now=_NOW
            )


class TestDetectGaps1dFromD1:
    """Plan 185-18 task 1b: 1d asks come from D1, through the same plan_gaps rule
    every other timeframe uses. A NYSE session with a TRADES observation (SMART or
    venue, D-20) is covered; a definitive no_data window containing the whole
    session day is covered; the rest come back as contiguous end-exclusive
    (date, date) ranges whose end is the last missing session's day end."""

    _D1 = date(2026, 1, 5)  # Monday
    _D2 = date(2026, 1, 6)  # Tuesday
    _D3 = date(2026, 1, 7)  # Wednesday
    # After every session in the window: all three session slots are plannable.
    _NOW_1D = datetime(2026, 1, 8, 2, 0, tzinfo=UTC)

    def _sessions(self) -> dict[date, tuple[datetime, datetime]]:
        def _sess(d: date) -> tuple[datetime, datetime]:
            return (
                datetime(d.year, d.month, d.day, 14, 30, tzinfo=UTC),
                datetime(d.year, d.month, d.day, 21, 0, tzinfo=UTC),
            )

        return {d: _sess(d) for d in (self._D1, self._D2, self._D3)}

    @staticmethod
    def _midnight(d: date) -> datetime:
        return datetime(d.year, d.month, d.day, tzinfo=UTC)

    def test_sessions_with_observations_are_not_gaps(self):
        conn = _FakeConn([(self._midnight(d), None) for d in (self._D1, self._D2, self._D3)], [])
        plan = detect_gaps_1d_from_d1(
            conn, "SPY", self._D1, self._D3, self._sessions(), vendor="ibkr", now=self._NOW_1D
        )
        assert plan == []

    def test_a_no_data_window_spanning_whole_session_days_is_not_a_gap(self):
        conn = _FakeConn(
            [(self._midnight(self._D3), None)],
            [("SMART", "no_data", self._midnight(self._D1), self._midnight(self._D3), None, None)],
        )
        plan = detect_gaps_1d_from_d1(
            conn, "SPY", self._D1, self._D3, self._sessions(), vendor="ibkr", now=self._NOW_1D
        )
        assert plan == []

    def test_missing_sessions_come_back_as_one_contiguous_end_exclusive_range(self):
        conn = _FakeConn([(self._midnight(self._D3), None)], [])
        plan = detect_gaps_1d_from_d1(
            conn, "SPY", self._D1, self._D3, self._sessions(), vendor="ibkr", now=self._NOW_1D
        )
        # End-exclusive: the range ends at the last missing session's own day end.
        assert plan == [(self._D1, self._D3)]

    def test_a_session_still_forming_is_not_planned(self):
        # Mid-session on the 6th (02:00 UTC is the evening of the 5th in New York, D2 not
        # started): D1 is stored, D2 and D3 are not complete, so nothing is asked.
        early = datetime(2026, 1, 6, 2, 0, tzinfo=UTC)
        conn = _FakeConn([(self._midnight(self._D1), None)], [])
        plan = detect_gaps_1d_from_d1(
            conn, "SPY", self._D1, self._D3, self._sessions(), vendor="ibkr", now=early
        )
        assert plan == []
        midday = datetime(2026, 1, 6, 18, 0, tzinfo=UTC)  # D2 still trading (closes 21:00)
        conn = _FakeConn([(self._midnight(self._D1), None)], [])
        assert (
            detect_gaps_1d_from_d1(
                conn, "SPY", self._D1, self._D3, self._sessions(), vendor="ibkr", now=midday
            )
            == []
        )

    def test_a_closed_session_is_asked_the_moment_it_closes_never_a_zero_length_window(self):
        # 22:00 UTC on the 6th: D2 closed at 21:00, before the next 00:00 UTC. The window is the
        # whole session day (D2, D3), end-exclusive, never capped at now into (D2, D2).
        closed = datetime(2026, 1, 6, 22, 0, tzinfo=UTC)
        conn = _FakeConn([(self._midnight(self._D1), None)], [])
        plan = detect_gaps_1d_from_d1(
            conn, "SPY", self._D1, self._D3, self._sessions(), vendor="ibkr", now=closed
        )
        assert plan == [(self._D2, self._D3)]
        assert all(start < end for start, end in plan)

    def test_sessions_outside_the_requested_window_are_ignored(self):
        sessions = self._sessions()
        sessions[date(2026, 1, 9)] = (  # a Friday outside [start, end]
            datetime(2026, 1, 9, 14, 30, tzinfo=UTC),
            datetime(2026, 1, 9, 21, 0, tzinfo=UTC),
        )
        conn = _FakeConn([], [])
        plan = detect_gaps_1d_from_d1(
            conn, "SPY", self._D2, self._D3, sessions, vendor="ibkr", now=self._NOW_1D
        )
        assert plan == [(self._D2, date(2026, 1, 8))]

    def test_stored_query_reads_the_vendors_own_raw_rows_except_the_adjusted_kind(self):
        conn = _FakeConn([], [])
        detect_gaps_1d_from_d1(
            conn,
            "SPY",
            self._D1,
            self._D3,
            self._sessions(),
            vendor="ibkr",
            now=self._NOW_1D,
        )
        sql, params = conn.queries[0]
        assert "FROM ohlcv_raw" in sql
        assert "timeframe = '1d'" in sql
        assert "vendor = %s" in sql
        # D-20: a listing-venue bar covers its session exactly like a SMART one, so no route
        # kind is named; the dividend-adjusted series covers nothing. Another vendor's rows
        # never match the vendor filter (a tradier-only series leaves every session a gap).
        assert "kind <> ALL(%s)" in sql
        assert params[:3] == ("SPY", "ibkr", ["smart_adjusted"])
        assert "ohlcv_observation" not in sql

    def test_a_vendor_with_no_rows_of_its_own_has_every_session_as_a_gap(self):
        # The query is vendor-scoped, so a tradier-only series returns no rows to the ibkr
        # planner; the fake stands in for that empty result.
        conn = _FakeConn([], [])
        plan = detect_gaps_1d_from_d1(
            conn,
            "SPY",
            self._D1,
            self._D3,
            self._sessions(),
            vendor="ibkr",
            now=self._NOW_1D,
        )
        assert plan == [(self._D1, date(2026, 1, 8))]

    def test_a_bar_served_before_its_session_closed_is_not_coverage(self):
        # D-191-J: the D2 bar was served at 18:00 UTC, before the 21:00 close, so it is a
        # forming bar and the session stays a gap; D1 and D3 were served after their closes.
        closed = lambda d: datetime(d.year, d.month, d.day, 22, 0, tzinfo=UTC)  # noqa: E731
        forming = datetime(2026, 1, 6, 18, 0, tzinfo=UTC)
        conn = _FakeConn(
            [
                (self._midnight(self._D1), closed(self._D1)),
                (self._midnight(self._D2), forming),
                (self._midnight(self._D3), closed(self._D3)),
            ],
            [],
        )
        plan = detect_gaps_1d_from_d1(
            conn,
            "SPY",
            self._D1,
            self._D3,
            self._sessions(),
            vendor="ibkr",
            now=self._NOW_1D,
        )
        assert plan == [(self._D2, self._D3)]

    def test_daily_coverage_reads_the_vendors_no_data_and_failed_answers(self):
        conn = _FakeConn([], [])
        detect_gaps_1d_from_d1(
            conn,
            "SPY",
            self._D1,
            self._D3,
            self._sessions(),
            vendor="ibkr",
            now=self._NOW_1D,
        )
        sql, params = conn.queries[1]
        assert "FROM ohlcv_request" in sql and "source = %(vendor)s" in sql
        assert "outcome IN ('no_data', 'bars', 'failed', 'timeout')" in sql
        assert (params["symbol"], params["vendor"], params["what"]) == ("SPY", "ibkr", "TRADES")
        assert params["routes"] == ["SMART", "AMEX", "ARCA", "BATS", "ISLAND", "NYSE"]

    def test_a_fresh_confirmed_empty_span_suppresses_the_pre_listing_head(self):
        empty = EmptyRange(
            empty_from=self._midnight(self._D1),
            empty_through=datetime(2026, 1, 6, 14, 30, tzinfo=UTC),
            verified_at=self._NOW_1D - timedelta(days=1),
            n_confirming_chunks=3,
        )
        conn = _FakeConn([(self._midnight(self._D3), None)], [])
        skipped: list[EmptyRange] = []
        plan = detect_gaps_1d_from_d1(
            conn,
            "SPY",
            self._D1,
            self._D3,
            self._sessions(),
            vendor="ibkr",
            empty=empty,
            now=self._NOW_1D,
            reverify_days=7,
            min_confirmations=2,
            on_skip=skipped.append,
        )
        assert plan == []
        assert skipped == [empty]

    def test_a_stale_empty_span_suppresses_nothing(self):
        empty = EmptyRange(
            empty_from=self._midnight(self._D1),
            empty_through=datetime(2026, 1, 6, 14, 30, tzinfo=UTC),
            verified_at=self._NOW_1D - timedelta(days=30),
            n_confirming_chunks=3,
        )
        conn = _FakeConn([(self._midnight(self._D3), None)], [])
        skipped: list[EmptyRange] = []
        plan = detect_gaps_1d_from_d1(
            conn,
            "SPY",
            self._D1,
            self._D3,
            self._sessions(),
            vendor="ibkr",
            empty=empty,
            now=self._NOW_1D,
            reverify_days=7,
            min_confirmations=2,
            on_skip=skipped.append,
        )
        assert plan == [(self._D1, self._D3)]
        assert skipped == []


class TestLoadAnsweredWindows:
    def test_reads_the_vendors_smart_trades_answers_only(self):
        conn = _FakeConn([(_t(14, 30), _t(15, 0), None), (_t(15, 0), _t(15, 30), None)])
        windows = load_answered_windows(conn, "SPY", "15m", "ibkr")
        sql, params = conn.queries[1]
        assert params == {
            "symbol": "SPY",
            "timeframe": "15m",
            "vendor": "ibkr",
            "what": "TRADES",
            "routes": ["SMART"],
            "outcomes": ["bars", "no_data"],
            "match_s": 5.0,
        }
        assert "ohlcv_request" in sql
        assert "window_start IS NOT NULL" in sql
        # a bars answer is covered only when this vendor stored a bar in its window (the
        # insert may have failed)
        assert "EXISTS" in sql
        assert windows.starts == (_t(14, 30),) and windows.ends == (_t(15, 30),)
        assert "partial_bars" in sql

    def test_a_slot_an_answer_served_incomplete_is_not_answered(self):
        """Migration 479 (finding 5): the window holds 14:45, but the answer recorded its bar
        as partial, so the slot stays a gap; jsonb arrives decoded or as text."""
        partial = [{"t": "2026-01-02T14:45:00+00:00", "o": 1, "h": 1, "l": 1, "c": 1, "v": 5}]
        for value in (partial, json.dumps(partial)):
            conn = _FakeConn([(_t(14, 30), _t(15, 30), value)])
            windows = load_answered_windows(conn, "SPY", "15m", "ibkr")
            assert windows.covers(_t(14, 30), timedelta(minutes=15))
            assert not windows.covers(_t(14, 45), timedelta(minutes=15))
            assert windows.covers(_t(15, 0), timedelta(minutes=15))

    def test_one_sql_serves_every_timeframe_and_corroborates_in_raw_by_vendor(self):
        seen = set()
        for tf in ("5m", "15m", "1h"):  # 1d reads the confirmed empty spans (item 6)
            conn = _FakeConn([], [], [])  # 5m adds the Alpaca windows and applied loads
            load_answered_windows(conn, "SPY", tf, "alpaca")
            sql = conn.queries[1][0]
            seen.add(sql)
            assert "FROM ohlcv_raw m" in sql
            assert "m.vendor = r.source" in sql
            assert "ohlcv_intraday_raw_archive" not in sql
            assert "market_data_ohlcv" not in sql
        assert len(seen) == 1

    def test_tradier_requests_are_not_an_ibkr_answer(self):
        conn = _FakeConn([], [], [])  # 5m adds the Alpaca windows and applied loads
        load_answered_windows(conn, "SPY", "5m", "ibkr")
        sql, params = conn.queries[1]
        assert "r.source = %(vendor)s" in sql
        assert "tradier" not in params.values() and "TRADIER" not in params["routes"]

    def test_a_refused_answer_never_covers_its_window(self):
        """Third review of plan 191-07, finding 3: BAC's refused 2026-09-27..10-10 window held
        IBKR rows on 09-28 to 09-30, so its lost 10-01..10-09 sessions read as answered. A bars
        request whose own load (the latest request at or before it, within the APR tolerance)
        was refused is excluded."""
        conn = _FakeConn([], [], [])  # 5m adds the Alpaca windows and applied loads
        load_answered_windows(conn, "BAC", "5m", "ibkr")
        sql, params = conn.queries[1]
        assert "l.outcome = 'refused'" in sql and "make_interval(secs => %(match_s)s)" in sql
        assert "q.answered_at > r.answered_at AND q.answered_at <= l.loaded_at" in sql
        assert params["match_s"] == 5.0

    def test_a_missing_match_tolerance_is_loud(self):
        class _Empty(_FakeConn):
            def cursor(self):
                cur = _FakeCursor(self)
                cur.fetchall = lambda: []
                return cur

        with pytest.raises(RuntimeError, match="request_load_match_s"):
            load_answered_windows(_Empty(), "SPY", "5m", "ibkr")


class TestAlpacaEvidenceOnThe5mSeries:
    """The 5m series reads the Alpaca nightly's answers and applied loads too (todo 565/567);
    15m/1h stay IBKR-only."""

    def test_an_alpaca_window_answers_5m_slots(self):
        conn = _FakeConn(
            [(_t(14, 30), _t(15, 0), None, _t(20, 0))],  # the vendor's own SMART window
            [(_t(15, 0), _t(15, 30), None, _t(21, 0))],  # an Alpaca SIP 5Min window
            [],
        )
        windows = load_answered_windows(conn, "SPY", "5m", "ibkr")
        assert windows.covers(_t(14, 30), _Q)
        assert windows.covers(_t(15, 0), _Q)
        assert not windows.covers(_t(15, 30), _Q)

    def test_an_applied_load_answers_every_slot_of_its_requested_range(self):
        conn = _FakeConn([], [], [(date(2026, 1, 2), date(2026, 1, 2))])
        windows = load_answered_windows(conn, "SPY", "5m", "ibkr")
        assert windows.covers(_t(15, 30), _Q)  # a no-trade slot: the load range is inclusive
        assert windows.covers(_t(20, 0), _Q)
        assert not windows.covers(datetime(2026, 1, 5, 15, 0, tzinfo=UTC), _Q)

    def test_the_alpaca_query_is_scoped_to_sip_5min_and_the_loads_to_applied(self):
        conn = _FakeConn([], [], [])
        load_answered_windows(conn, "SPY", "5m", "ibkr")
        alpaca_sql, alpaca_params = conn.queries[2]
        assert "FROM ohlcv_request" in alpaca_sql and "m.vendor = r.source" in alpaca_sql
        # the same refused-load guard as the vendor's own read (one predicate, one rule)
        assert "l.outcome = 'refused'" in alpaca_sql
        assert alpaca_params["source"] == "alpaca"
        assert alpaca_params["route"] == "SIP" and alpaca_params["what"] == "5Min"
        loads_sql, loads_params = conn.queries[3]
        assert "FROM ohlcv_load" in loads_sql
        assert loads_params["outcomes"] == ["applied"]
        assert sorted(loads_params["destinations"]) == ["market_data_ohlcv", "raw"]

    def test_start_and_end_bound_the_alpaca_reads(self):
        conn = _FakeConn([], [], [])
        start, end = _t(14, 30), _t(15, 30)
        load_answered_windows(conn, "SPY", "5m", "ibkr", start=start, end=end)
        alpaca_sql, alpaca_params = conn.queries[2]
        assert "r.window_end >= %(start)s AND r.window_start < %(end)s" in alpaca_sql
        assert alpaca_params["start"] == start and alpaca_params["end"] == end
        loads_sql, loads_params = conn.queries[3]
        assert "l.requested_end >= %(start)s AND l.requested_start < %(end)s" in loads_sql
        assert loads_params["start"] == start and loads_params["end"] == end

    def test_15m_and_1h_ask_no_alpaca_question(self):
        for tf in ("15m", "1h"):
            conn = _FakeConn([])
            load_answered_windows(conn, "SPY", tf, "ibkr")
            assert len(conn.queries) == 2  # match tolerance + the vendor's own windows

    def test_an_alpaca_partial_slot_stays_missing(self):
        partial = [{"t": "2026-01-02T15:00:00+00:00"}]
        conn = _FakeConn([], [(_t(15, 0), _t(15, 30), partial, _t(21, 0))], [])
        windows = load_answered_windows(conn, "SPY", "5m", "ibkr")
        assert not windows.covers(_t(15, 0), _Q)
        assert windows.covers(_t(15, 15), _Q)


def test_a_partial_slot_is_cleared_by_a_later_answer_that_served_it_whole():
    """Third review of plan 191-07, low item: a slot once recorded partial was re-asked forever."""
    partial = [{"t": "2026-01-02T14:45:00+00:00"}]
    first = (_t(14, 30), _t(15, 30), partial, _t(20, 0))
    later_whole = (_t(14, 30), _t(15, 30), None, _t(21, 0))
    later_partial_again = (_t(14, 30), _t(15, 30), partial, _t(21, 0))
    elsewhere = (_t(15, 0), _t(15, 30), None, _t(21, 0))
    assert live_partials([first]) == {_t(14, 45)}
    assert live_partials([first, later_whole]) == set()
    assert live_partials([first, later_partial_again]) == {_t(14, 45)}
    assert live_partials([first, elsewhere]) == {_t(14, 45)}


def _day(d: int) -> datetime:
    return datetime(2008, 6, d, tzinfo=UTC)


_T_RUN = datetime(2026, 10, 1, tzinfo=UTC)


class TestDailyNoDataCoverage:
    """Todo 535 item 6: a 1d session inside a no_data window is covered unless some route's
    latest answer over it was a transport failure (a timeout, or a failure with error text)."""

    def test_a_no_data_window_of_any_route_covers(self):
        rows = [("SMART", "no_data", _day(2), _day(9), _T_RUN, None)]
        assert daily_no_data_coverage(rows) == [(_day(2), _day(9))]

    def test_a_venue_walk_a_connection_error_cut_under_smart_no_data_is_not_covered(self):
        rows = [
            ("SMART", "no_data", _day(2), _day(9), _T_RUN, None),
            ("ISLAND", "failed", _day(4), _day(6), _T_RUN, "ConnectionError: Not connected"),
        ]
        coverage = daily_no_data_coverage(rows)
        assert coverage == [(_day(2), _day(4)), (_day(6), _day(9))]
        windows = AnsweredWindows.from_rows(coverage)
        assert not windows.covers(_day(4), timedelta(days=1))
        assert windows.covers(_day(3), timedelta(days=1))

    def test_a_later_answer_of_the_same_route_closes_the_failure(self):
        later = _T_RUN + timedelta(days=1)
        for outcome in ("no_data", "bars"):
            rows = [
                ("SMART", "no_data", _day(2), _day(9), _T_RUN, None),
                ("ISLAND", "failed", _day(4), _day(6), _T_RUN, "ConnectionError: Not connected"),
                ("ISLAND", outcome, _day(3), _day(5), later, None),
            ]
            assert daily_no_data_coverage(rows) == [(_day(2), _day(5)), (_day(6), _day(9))]

    def test_an_earlier_answer_or_another_route_does_not_close_it(self):
        rows = [
            ("SMART", "no_data", _day(2), _day(9), _T_RUN, None),
            ("ISLAND", "no_data", _day(2), _day(9), _T_RUN - timedelta(days=1), None),
            ("ARCA", "no_data", _day(2), _day(9), _T_RUN + timedelta(days=1), None),
            ("ISLAND", "timeout", _day(4), _day(6), _T_RUN, None),
        ]
        assert daily_no_data_coverage(rows) == [(_day(2), _day(4)), (_day(6), _day(9))]

    def test_an_ibkr_error_answer_without_error_text_withdraws_nothing(self):
        # ISLAND refuses a name not listed on NASDAQ on every ask: no transport failure.
        rows = [
            ("SMART", "no_data", _day(2), _day(9), _T_RUN, None),
            ("ISLAND", "failed", _day(4), _day(6), _T_RUN, None),
        ]
        assert daily_no_data_coverage(rows) == [(_day(2), _day(9))]

    def test_bars_answers_cover_nothing_by_themselves(self):
        assert daily_no_data_coverage([("SMART", "bars", _day(2), _day(9), _T_RUN, None)]) == []

    def test_subtract_windows_is_end_exclusive_and_merged(self):
        assert subtract_windows([(_day(2), _day(5)), (_day(5), _day(9))], [(_day(5), _day(6))]) == [
            (_day(2), _day(5)),
            (_day(6), _day(9)),
        ]
        assert subtract_windows([(_day(2), _day(9))], [(_day(1), _day(10))]) == []


class TestIntradayHorizonStopsAtNow:
    """Todo 535 items 10 and 15: a slot whose bar has not ended by `now` is never planned, so
    no ask records a window over a bar the leaf drops as forming."""

    def test_a_forming_slot_is_not_planned(self):
        now = _t(15, 7)
        conn = _FakeConn([], [])
        plan = detect_gaps_from_record(
            conn,
            "SPY",
            "15m",
            _t(14, 30),
            now,
            [_t(14, 30), _t(14, 45), _t(15, 0)],
            vendor="ibkr",
            now=now,
        )
        assert plan == [(_t(14, 30), _t(15, 0))]

    def test_a_slot_ending_exactly_at_now_is_planned(self):
        now = _t(15, 15)
        conn = _FakeConn([], [])
        plan = detect_gaps_from_record(
            conn, "SPY", "15m", _t(15, 0), now, [_t(15, 0)], vendor="ibkr", now=now
        )
        assert plan == [(_t(15, 0), _t(15, 15))]
