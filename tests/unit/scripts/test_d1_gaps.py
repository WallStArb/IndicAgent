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

from scripts.infrastructure.backfill import _d1_gaps as d1_gaps
from scripts.infrastructure.backfill._d1_gaps import (
    _MATCH_S_SQL,
    detect_gaps_1d_from_d1,
    detect_gaps_from_record,
    load_answered_windows,
)
from scripts.infrastructure.backfill._empty_history import EmptyRange

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
            conn = _FakeConn([], [])
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
        conn = _FakeConn([], [])
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

    @pytest.fixture(autouse=True)
    def _confirmed_spans_from_the_fake(self, monkeypatch):
        """The 1d answered windows are the confirmed empty spans (todo 535 item 6); here the
        fake's second result stands in for them. TestDailyCoverageNeedsEveryRoute runs the real
        rule."""
        self.span_calls: list[tuple] = []

        def fake(conn, symbol, timeframe, vendor):
            self.span_calls.append((symbol, timeframe, vendor))
            return [(r[0], r[1]) for r in conn.results.pop(0)]

        monkeypatch.setattr(d1_gaps._empty_history, "confirmed_empty_spans", fake)

    def test_sessions_with_observations_are_not_gaps(self):
        conn = _FakeConn([(self._midnight(d), None) for d in (self._D1, self._D2, self._D3)], [])
        plan = detect_gaps_1d_from_d1(
            conn, "SPY", self._D1, self._D3, self._sessions(), vendor="ibkr", now=self._NOW_1D
        )
        assert plan == []

    def test_a_no_data_window_spanning_whole_session_days_is_not_a_gap(self):
        conn = _FakeConn(
            [(self._midnight(self._D3), None)],
            [(self._midnight(self._D1), self._midnight(self._D3), None)],
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

    def test_a_bar_with_no_serve_stamp_still_counts(self):
        conn = _FakeConn([(self._midnight(d), None) for d in (self._D1, self._D2, self._D3)], [])
        plan = detect_gaps_1d_from_d1(
            conn,
            "SPY",
            self._D1,
            self._D3,
            self._sessions(),
            vendor="ibkr",
            now=self._NOW_1D,
        )
        assert plan == []

    def test_daily_coverage_is_the_vendors_confirmed_empty_spans(self):
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
        assert self.span_calls == [("SPY", "1d", "ibkr")]
        # No per-route request read: one route's no_data never covers a session.
        assert not any("FROM ohlcv_request" in sql for sql, _ in conn.queries)

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
            conn = _FakeConn([])
            load_answered_windows(conn, "SPY", tf, "alpaca")
            sql = conn.queries[1][0]
            seen.add(sql)
            assert "FROM ohlcv_raw m" in sql
            assert "m.vendor = r.source" in sql
            assert "ohlcv_intraday_raw_archive" not in sql
            assert "market_data_ohlcv" not in sql
        assert len(seen) == 1

    def test_tradier_requests_are_not_an_ibkr_answer(self):
        conn = _FakeConn([])
        load_answered_windows(conn, "SPY", "5m", "ibkr")
        sql, params = conn.queries[1]
        assert "r.source = %(vendor)s" in sql
        assert "tradier" not in params.values() and "TRADIER" not in params["routes"]

    def test_a_refused_answer_never_covers_its_window(self):
        """Third review of plan 191-07, finding 3: BAC's refused 2026-09-27..10-10 window held
        IBKR rows on 09-28 to 09-30, so its lost 10-01..10-09 sessions read as answered. A bars
        request whose own load (the latest request at or before it, within the APR tolerance)
        was refused is excluded."""
        conn = _FakeConn([])
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


def test_a_partial_slot_is_cleared_by_a_later_answer_that_served_it_whole():
    """Third review of plan 191-07, low item: a slot once recorded partial was re-asked forever."""
    from scripts.infrastructure.backfill._d1_gaps import live_partials

    partial = [{"t": "2026-01-02T14:45:00+00:00"}]
    first = (_t(14, 30), _t(15, 30), partial, _t(20, 0))
    later_whole = (_t(14, 30), _t(15, 30), None, _t(21, 0))
    later_partial_again = (_t(14, 30), _t(15, 30), partial, _t(21, 0))
    elsewhere = (_t(15, 0), _t(15, 30), None, _t(21, 0))
    assert live_partials([first]) == {_t(14, 45)}
    assert live_partials([first, later_whole]) == set()
    assert live_partials([first, later_partial_again]) == {_t(14, 45)}
    assert live_partials([first, elsewhere]) == {_t(14, 45)}


class TestDailyCoverageNeedsEveryRoute:
    """Todo 535 item 6: a 1d session is answered only where SMART and every non-primary former
    venue answered no_data in one run, the empty-history rule (D-20), with the real
    _empty_history.confirmed_empty_spans over a scripted connection."""

    _START = datetime(2006, 10, 5, tzinfo=UTC)
    _END = datetime(2010, 3, 4, tzinfo=UTC)
    _SESSION = datetime(2008, 6, 2, tzinfo=UTC)

    def _windows(self, skip: tuple[str, ...]):
        from tests.unit.scripts.test_empty_history_from_d1 import FakeConn, _answers

        conn = FakeConn(requests={"SCHW": _answers("r1", self._START, self._END, skip=skip)})
        return load_answered_windows(conn, "SCHW", "1d", "ibkr")

    def test_smart_no_data_over_a_span_a_venue_route_failed_is_a_gap(self):
        # SCHW-like: SMART no_data, ARCA failed (no no_data window): the session is asked again.
        windows = self._windows(skip=("ARCA",))
        assert not windows.covers(self._SESSION, timedelta(days=1))

    def test_every_required_route_no_data_in_one_run_covers_the_session(self):
        windows = self._windows(skip=("ISLAND",))  # ISLAND is the primary NASDAQ's own route
        assert windows.covers(self._SESSION, timedelta(days=1))


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
