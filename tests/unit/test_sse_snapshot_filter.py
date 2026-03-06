"""Tests for SSE snapshot age filter on signal streams."""
import time

import pytest


def _entry_id_for_age(seconds_ago: float) -> str:
    """Create a Redis entry ID that appears N seconds old."""
    unix_ms = int((time.time() - seconds_ago) * 1000)
    return f"{unix_ms}-0"


def _is_signal_entry_stale(stream_name: str, entry_id: str) -> bool:
    """Mirror of the filter logic to be added to sse.py."""
    _TF_MINUTES = {"1m": 1, "5m": 5, "15m": 15, "1h": 60, "4h": 240, "1d": 1440}
    if "signals:" not in stream_name:
        return False
    # Extract TF from stream key: "development:signals:ESH6:5m:aggregated"
    parts = stream_name.split(":")
    # Find the part after the symbol (last segment before "aggregated")
    try:
        agg_idx = parts.index("aggregated")
        tf = parts[agg_idx - 1]
    except (ValueError, IndexError):
        return False
    tf_minutes = _TF_MINUTES.get(tf)
    if tf_minutes is None:
        return False
    max_age_s = 2 * tf_minutes * 60
    try:
        entry_unix_ms = int(entry_id.split("-")[0])
    except (ValueError, IndexError):
        return False
    age_s = (time.time() * 1000 - entry_unix_ms) / 1000
    return age_s > max_age_s


@pytest.mark.unit
class TestSseSnapshotFilter:
    def test_fresh_5m_signal_not_stale(self):
        """Entry 3 minutes old on 5m stream: max_age=600s → not stale."""
        entry_id = _entry_id_for_age(180)
        assert not _is_signal_entry_stale("development:signals:ESH6:5m:aggregated", entry_id)

    def test_old_5m_signal_is_stale(self):
        """Entry 25 minutes old on 5m stream: max_age=600s → stale."""
        entry_id = _entry_id_for_age(1500)
        assert _is_signal_entry_stale("development:signals:ESH6:5m:aggregated", entry_id)

    def test_old_1h_signal_not_stale(self):
        """Entry 90 minutes old on 1h stream: max_age=7200s → not stale."""
        entry_id = _entry_id_for_age(5400)
        assert not _is_signal_entry_stale("development:signals:ESH6:1h:aggregated", entry_id)

    def test_very_old_1h_signal_is_stale(self):
        """Entry 3 hours old on 1h stream: max_age=7200s → stale."""
        entry_id = _entry_id_for_age(10800)
        assert _is_signal_entry_stale("development:signals:ESH6:1h:aggregated", entry_id)

    def test_non_signal_stream_never_stale(self):
        """Intelligence and indicator streams are never filtered."""
        entry_id = _entry_id_for_age(99999)
        assert not _is_signal_entry_stale("development:intelligence:ESH6:5m", entry_id)
        assert not _is_signal_entry_stale("development:indicators:ESH6:5m", entry_id)

    def test_1m_boundary(self):
        """Entry 3 min 1 sec old on 1m stream: max_age=120s → stale."""
        entry_id = _entry_id_for_age(181)
        assert _is_signal_entry_stale("development:signals:ESH6:1m:aggregated", entry_id)
