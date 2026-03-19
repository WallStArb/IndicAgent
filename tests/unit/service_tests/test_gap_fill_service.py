"""Unit tests for gap_fill_service — pure functions only, no I/O."""

from __future__ import annotations

from datetime import date, timedelta

from services.gap_fill_service import detect_gaps, generate_rth_timestamps


class TestRTHWindowGeneration:
    def test_weekday_produces_390_bars(self) -> None:
        """Standard weekday RTH session has exactly 390 1-minute bars."""
        # Monday 2026-03-16
        timestamps = generate_rth_timestamps(date(2026, 3, 16))
        assert len(timestamps) == 390

    def test_first_bar_is_0930_et(self) -> None:
        """First bar timestamp corresponds to 09:30 ET in UTC.

        2026-03-16 is EDT (UTC-4), so 09:30 ET = 13:30 UTC.
        """
        timestamps = generate_rth_timestamps(date(2026, 3, 16))
        assert timestamps[0].hour == 13
        assert timestamps[0].minute == 30

    def test_last_bar_is_1559_et(self) -> None:
        """Last bar timestamp corresponds to 15:59 ET in UTC.

        2026-03-16 is EDT (UTC-4), so 15:59 ET = 19:59 UTC.
        """
        timestamps = generate_rth_timestamps(date(2026, 3, 16))
        assert timestamps[-1].hour == 19
        assert timestamps[-1].minute == 59

    def test_saturday_returns_empty(self) -> None:
        """Saturday produces no RTH timestamps."""
        timestamps = generate_rth_timestamps(date(2026, 3, 14))  # Saturday
        assert timestamps == []

    def test_sunday_returns_empty(self) -> None:
        """Sunday produces no RTH timestamps."""
        timestamps = generate_rth_timestamps(date(2026, 3, 15))  # Sunday
        assert timestamps == []

    def test_all_timestamps_are_utc(self) -> None:
        """All returned timestamps are timezone-aware UTC."""
        timestamps = generate_rth_timestamps(date(2026, 3, 16))
        for ts in timestamps:
            assert ts.tzinfo is not None
            assert ts.utcoffset() == timedelta(0)

    def test_timestamps_are_one_minute_apart(self) -> None:
        """Each bar is exactly 1 minute after the previous one."""
        timestamps = generate_rth_timestamps(date(2026, 3, 16))
        for i in range(1, len(timestamps)):
            delta = timestamps[i] - timestamps[i - 1]
            assert delta == timedelta(minutes=1)

    def test_est_session_first_bar_is_1430_utc(self) -> None:
        """During EST (winter), 09:30 ET = 14:30 UTC.

        2026-01-05 is EST (UTC-5) — before DST.
        """
        timestamps = generate_rth_timestamps(date(2026, 1, 5))  # Monday
        assert len(timestamps) == 390
        assert timestamps[0].hour == 14
        assert timestamps[0].minute == 30


class TestGapDetection:
    def test_no_gaps_returns_empty(self) -> None:
        """When all expected bars exist, no gaps detected."""
        expected = generate_rth_timestamps(date(2026, 3, 16))
        actual = set(expected)
        assert detect_gaps(expected, actual) == []

    def test_missing_bars_detected(self) -> None:
        """Missing bars are correctly identified."""
        expected = generate_rth_timestamps(date(2026, 3, 16))
        actual = set(expected[5:])  # Remove first 5 bars
        gaps = detect_gaps(expected, actual)
        assert len(gaps) == 5
        assert gaps == expected[:5]

    def test_all_missing_returns_full_list(self) -> None:
        """When no actual bars exist, all expected are gaps."""
        expected = generate_rth_timestamps(date(2026, 3, 16))
        gaps = detect_gaps(expected, set())
        assert len(gaps) == 390

    def test_gaps_are_sorted(self) -> None:
        """Returned gaps are in chronological order."""
        expected = generate_rth_timestamps(date(2026, 3, 16))
        # Remove a few scattered bars
        actual = set(expected) - {expected[10], expected[50], expected[3]}
        gaps = detect_gaps(expected, actual)
        assert gaps == sorted(gaps)

    def test_middle_gaps_detected(self) -> None:
        """Gaps in the middle of the session are detected correctly."""
        expected = generate_rth_timestamps(date(2026, 3, 16))
        # Remove bars 100-109 (10 consecutive mid-session bars)
        actual = set(expected) - set(expected[100:110])
        gaps = detect_gaps(expected, actual)
        assert len(gaps) == 10
        assert gaps == expected[100:110]

    def test_empty_expected_returns_empty(self) -> None:
        """Empty expected list (weekend) produces no gaps."""
        expected = generate_rth_timestamps(date(2026, 3, 14))  # Saturday
        gaps = detect_gaps(expected, set())
        assert gaps == []
