"""Unit tests for SSE age filter helpers (Plan 27-03).

Verifies:
1. _TF_MINUTES dict contains all 6 timeframes
2. _signal_max_age_s() returns 2×TF×60 for signal streams, None otherwise
3. _signal_max_age_s() handles malformed stream names
4. _signal_entry_stale() returns True for old entries, False for fresh
5. _signal_entry_stale() parses Redis entry IDs correctly (Unix-ms embedded)
6. _signal_entry_stale() handles None max_age (non-signal streams always False)
"""
import time

from src.api.routes.sse import _TF_MINUTES, _signal_entry_stale, _signal_max_age_s


def _entry_id_for_age(seconds_ago: float) -> str:
    """Create a Redis entry ID that appears N seconds old."""
    unix_ms = int((time.time() - seconds_ago) * 1000)
    return f"{unix_ms}-0"


class TestTfMinutesDict:
    def test_contains_all_six_timeframes(self):
        """_TF_MINUTES must cover every supported TF."""
        expected = {"1m": 1, "5m": 5, "15m": 15, "1h": 60, "4h": 240, "1d": 1440}
        assert _TF_MINUTES == expected

    def test_values_are_integer_minutes(self):
        for tf, minutes in _TF_MINUTES.items():
            assert isinstance(minutes, int), f"{tf} value should be int"
            assert minutes > 0


class TestSignalMaxAgeS:
    def test_1m_stream_returns_120s(self):
        age = _signal_max_age_s("development:signals:ESH6:1m:aggregated")
        assert age == 120

    def test_5m_stream_returns_600s(self):
        age = _signal_max_age_s("development:signals:ESH6:5m:aggregated")
        assert age == 600

    def test_15m_stream_returns_1800s(self):
        age = _signal_max_age_s("development:signals:ESH6:15m:aggregated")
        assert age == 1800

    def test_1h_stream_returns_7200s(self):
        age = _signal_max_age_s("development:signals:ESH6:1h:aggregated")
        assert age == 7200

    def test_4h_stream_returns_28800s(self):
        age = _signal_max_age_s("development:signals:ESH6:4h:aggregated")
        assert age == 28800

    def test_1d_stream_returns_172800s(self):
        age = _signal_max_age_s("development:signals:ESH6:1d:aggregated")
        assert age == 172800

    def test_non_signal_stream_returns_none(self):
        assert _signal_max_age_s("development:intelligence:ESH6:5m") is None
        assert _signal_max_age_s("development:indicators:ESH6:5m") is None
        assert _signal_max_age_s("development:market:ESH6:5m") is None

    def test_malformed_stream_name_returns_none(self):
        """Missing 'aggregated' segment — should not crash, return None."""
        assert _signal_max_age_s("development:signals:ESH6:5m") is None

    def test_unknown_tf_returns_none(self):
        """Unknown TF like '2m' not in _TF_MINUTES — return None."""
        assert _signal_max_age_s("development:signals:ESH6:2m:aggregated") is None


class TestSignalEntryStale:
    def test_fresh_5m_entry_not_stale(self):
        """Entry 3 min old on 5m stream: max_age=600s → not stale."""
        entry_id = _entry_id_for_age(180)
        assert not _signal_entry_stale("development:signals:ESH6:5m:aggregated", entry_id)

    def test_stale_5m_entry_is_stale(self):
        """Entry 25 min old on 5m stream: max_age=600s → stale."""
        entry_id = _entry_id_for_age(1500)
        assert _signal_entry_stale("development:signals:ESH6:5m:aggregated", entry_id)

    def test_fresh_1h_entry_not_stale(self):
        """Entry 90 min old on 1h stream: max_age=7200s → not stale."""
        entry_id = _entry_id_for_age(5400)
        assert not _signal_entry_stale("development:signals:ESH6:1h:aggregated", entry_id)

    def test_stale_1h_entry_is_stale(self):
        """Entry 3h old on 1h stream: max_age=7200s → stale."""
        entry_id = _entry_id_for_age(10800)
        assert _signal_entry_stale("development:signals:ESH6:1h:aggregated", entry_id)

    def test_1m_boundary_stale(self):
        """Entry 3 min 1 sec old on 1m stream: max_age=120s → stale."""
        entry_id = _entry_id_for_age(181)
        assert _signal_entry_stale("development:signals:ESH6:1m:aggregated", entry_id)

    def test_non_signal_stream_never_stale(self):
        """Intelligence and indicator streams always return False."""
        very_old = _entry_id_for_age(99999)
        assert not _signal_entry_stale("development:intelligence:ESH6:5m", very_old)
        assert not _signal_entry_stale("development:indicators:ESH6:5m", very_old)

    def test_parses_entry_id_as_unix_ms(self):
        """entry_id format '1234567890000-0' → timestamp 1234567890 seconds."""
        # Create entry that is exactly 5 seconds old (within 5m max_age of 600s)
        entry_id = _entry_id_for_age(5)
        assert not _signal_entry_stale("development:signals:ESH6:5m:aggregated", entry_id)

    def test_bytes_entry_id_handled(self):
        """Accepts bytes entry_id (Redis sometimes returns bytes)."""
        entry_id_bytes = _entry_id_for_age(180).encode()
        assert not _signal_entry_stale("development:signals:ESH6:5m:aggregated", entry_id_bytes)

    def test_malformed_entry_id_returns_false(self):
        """Malformed entry ID should not crash — returns False (not stale)."""
        assert not _signal_entry_stale("development:signals:ESH6:5m:aggregated", "bad-id")
