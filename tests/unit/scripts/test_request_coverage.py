"""Answered-request coverage for intraday gap detection (todo 462): pure window logic and the
query parameters, no database."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

from scripts.infrastructure.backfill._request_coverage import (
    AnsweredWindows,
    load_answered_windows,
)

_HOUR = timedelta(hours=1)


def _t(day: int, hour: int) -> datetime:
    return datetime(2026, 1, day, hour, 0, tzinfo=UTC)


class TestAnsweredWindows:
    def test_empty_covers_nothing(self):
        assert not AnsweredWindows().covers(_t(2, 15), _HOUR)

    def test_slot_inside_a_window_is_covered(self):
        windows = AnsweredWindows.from_rows([(_t(2, 15), _t(2, 18))])
        assert windows.covers(_t(2, 15), _HOUR)
        assert windows.covers(_t(2, 17), _HOUR)

    def test_slot_running_past_the_window_end_is_not_covered(self):
        windows = AnsweredWindows.from_rows([(_t(2, 15), _t(2, 18))])
        assert not windows.covers(_t(2, 18), _HOUR)
        assert not windows.covers(_t(2, 14), _HOUR)
        # a 90 minute bar starting at 17:00 would end at 18:30, past the window
        assert not windows.covers(_t(2, 17), timedelta(minutes=90))

    def test_overlapping_and_touching_windows_merge(self):
        windows = AnsweredWindows.from_rows(
            [(_t(2, 17), _t(2, 19)), (_t(2, 15), _t(2, 18)), (_t(2, 19), _t(2, 21))]
        )
        assert windows.starts == (_t(2, 15),)
        assert windows.ends == (_t(2, 21),)

    def test_disjoint_windows_leave_the_gap_uncovered(self):
        windows = AnsweredWindows.from_rows([(_t(2, 15), _t(2, 16)), (_t(2, 18), _t(2, 19))])
        assert windows.covers(_t(2, 15), _HOUR)
        assert not windows.covers(_t(2, 16), _HOUR)
        assert not windows.covers(_t(2, 17), _HOUR)
        assert windows.covers(_t(2, 18), _HOUR)

    def test_empty_or_inverted_window_is_ignored(self):
        windows = AnsweredWindows.from_rows([(_t(2, 15), _t(2, 15)), (_t(2, 17), _t(2, 16))])
        assert windows == AnsweredWindows()


class TestLoadAnsweredWindows:
    def test_reads_smart_trades_answers_only(self):
        conn = MagicMock()
        cur = conn.cursor.return_value.__enter__.return_value
        cur.fetchall.return_value = [(_t(2, 15), _t(2, 18)), (_t(2, 18), _t(2, 20))]

        windows = load_answered_windows(conn, "AAA", "15m")

        sql, params = cur.execute.call_args.args
        assert params == ("AAA", "15m", "SMART", "TRADES", ["bars", "no_data"])
        assert "window_start IS NOT NULL" in sql
        # a bars answer is covered only when a bar is stored in its window (the insert may have failed)
        assert "EXISTS" in sql
        assert windows.starts == (_t(2, 15),) and windows.ends == (_t(2, 20),)
