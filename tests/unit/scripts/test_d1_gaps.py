"""Tests for scripts/infrastructure/backfill/_d1_gaps.py (plan 185-18 task 1a).

`plan_gaps` (src/intelligence/bars/gap_plan.py) is the one pure definition of a
missing bar; _d1_gaps is its psycopg SQL-reading wrapper for the fetch pipeline.
These tests pin the wrapper's contract against a sequenced fake connection: the
two queries it issues (stored observations, answered request windows), the table
each timeframe reads, the empty-history folding with its freshness gate, and the
plan's mandated case -- a fully fetched name with a recorded no_data head returns
no ranges; the same name with the no_data row deleted returns the head.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from scripts.infrastructure.backfill._d1_gaps import (
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
        conn = _FakeConn(_STORED_TAIL, [(_t(14, 30), _t(15, 0))])
        plan = detect_gaps_from_record(
            conn, "SPY", "15m", _t(14, 30), _t(15, 30), _HEAD_SLOTS, now=_NOW
        )
        assert plan == []

    def test_same_name_with_the_no_data_row_deleted_returns_the_head(self):
        conn = _FakeConn(_STORED_TAIL, [])
        plan = detect_gaps_from_record(
            conn, "SPY", "15m", _t(14, 30), _t(15, 30), _HEAD_SLOTS, now=_NOW
        )
        # End-exclusive: the head window ends at the last missing slot's end.
        assert plan == [(_t(14, 30), _t(15, 0))]

    def test_windows_are_end_exclusive_one_slot_gap_is_one_bar_interval(self):
        conn = _FakeConn([(_t(14, 45),)], [])
        plan = detect_gaps_from_record(
            conn, "SPY", "15m", _t(14, 30), _t(15, 0), _HEAD_SLOTS[:3], now=_NOW
        )
        assert plan == [(_t(14, 30), _t(14, 45))]

    def test_slot_still_forming_stays_a_gap_capped_at_the_run_end(self):
        conn = _FakeConn([], [])
        plan = detect_gaps_from_record(
            conn, "SPY", "15m", _t(15, 0), _t(15, 7), [_t(15, 0), _t(15, 15)], now=_NOW
        )
        # The 15:15 slot starts after the run's end and is not planned; the
        # forming 15:00 slot is asked for, capped at the run's end.
        assert plan == [(_t(15, 0), _t(15, 7))]

    def test_15m_and_1h_read_stored_observations_from_the_archive(self):
        for tf in ("15m", "1h"):
            conn = _FakeConn([], [])
            detect_gaps_from_record(conn, "SPY", tf, _t(14, 30), _t(15, 30), [], now=_NOW)
            stored_sql = conn.queries[0][0]
            assert "ohlcv_intraday_raw_archive" in stored_sql
            assert "market_data_ohlcv" not in stored_sql

    def test_5m_reads_stored_observations_from_market_data_ohlcv(self):
        conn = _FakeConn([], [])
        detect_gaps_from_record(conn, "SPY", "5m", _t(14, 30), _t(15, 30), [], now=_NOW)
        stored_sql = conn.queries[0][0]
        assert "FROM market_data_ohlcv" in stored_sql
        assert "ohlcv_intraday_raw_archive" not in stored_sql

    def test_stored_query_is_scoped_to_the_series_and_window(self):
        conn = _FakeConn([], [])
        detect_gaps_from_record(conn, "SPY", "15m", _t(14, 30), _t(15, 30), _HEAD_SLOTS, now=_NOW)
        sql, params = conn.queries[0]
        assert "symbol = %s" in sql and "timeframe = %s" in sql
        assert "timestamp >= %s" in sql and "timestamp <= %s" in sql
        assert params == ("SPY", "15m", _t(14, 30), _t(15, 30))

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
            empty=empty,
            now=_NOW,
            reverify_days=7,
            min_confirmations=2,
        )
        assert plan == [(_t(14, 30), _t(15, 0))]

    def test_timeframes_outside_the_record_planner_are_refused(self):
        conn = _FakeConn()
        with pytest.raises(ValueError, match="1m"):
            detect_gaps_from_record(conn, "SPY", "1m", _t(14, 30), _t(15, 30), [], now=_NOW)


class TestLoadAnsweredWindows:
    def test_reads_smart_trades_answers_only(self):
        conn = _FakeConn([(_t(14, 30), _t(15, 0)), (_t(15, 0), _t(15, 30))])
        windows = load_answered_windows(conn, "SPY", "15m")
        sql, params = conn.queries[0]
        assert params == ("SPY", "15m", "SMART", "TRADES", ["bars", "no_data"])
        assert "ohlcv_request" in sql
        assert "window_start IS NOT NULL" in sql
        # a bars answer is covered only when a bar is stored in its window (the
        # insert may have failed)
        assert "EXISTS" in sql
        assert windows.starts == (_t(14, 30),) and windows.ends == (_t(15, 30),)

    def test_corroboration_reads_the_archive_for_15m_and_the_grid_for_5m(self):
        for tf, table in (("15m", "ohlcv_intraday_raw_archive"), ("5m", "market_data_ohlcv")):
            conn = _FakeConn([])
            load_answered_windows(conn, "SPY", tf)
            sql = conn.queries[0][0]
            assert f"FROM {table} m" in sql
