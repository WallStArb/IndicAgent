"""Tests for SSE snapshot age filter on signal streams."""

import inspect
import time

import pytest

from src.api.routes.sse import _build_stream_list, _event_name_for_stream, _signal_entry_stale


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


@pytest.mark.unit
class TestSnapshotLoopNoAgeFilter:
    """Confirm the snapshot loop does NOT call _signal_entry_stale."""

    def test_function_retained(self):
        """_signal_entry_stale must still exist (retained for future live-loop use)."""
        assert callable(_signal_entry_stale)
        assert _signal_entry_stale.__code__ is not None

    def test_snapshot_loop_does_not_call_stale_filter(self):
        """The snapshot block (if not last_event_id:) must not contain _signal_entry_stale."""
        import src.api.routes.sse as sse_module

        source = inspect.getsource(sse_module)
        # Find the snapshot block: between "if not last_event_id:" and "# ── Live:"
        snapshot_start = source.find("if not last_event_id:")
        live_start = source.find("# ── Live:", snapshot_start)
        assert snapshot_start != -1, "Could not locate snapshot block in sse.py"
        assert live_start != -1, "Could not locate live loop marker in sse.py"
        snapshot_block = source[snapshot_start:live_start]
        assert "_signal_entry_stale" not in snapshot_block, (
            "Snapshot loop must NOT call _signal_entry_stale — "
            "count=2 xrevrange is the correct recency guard"
        )

    def test_old_5m_signal_stale_function_still_correct(self):
        """_signal_entry_stale still returns True for a 25-min-old 5m signal."""
        old_id = _entry_id_for_age(1500)
        assert _signal_entry_stale("development:signals:ESH6:5m:aggregated", old_id)

    def test_fresh_5m_signal_not_stale_function(self):
        """_signal_entry_stale still returns False for a 3-min-old 5m signal."""
        fresh_id = _entry_id_for_age(180)
        assert not _signal_entry_stale("development:signals:ESH6:5m:aggregated", fresh_id)


@pytest.mark.unit
class TestIntelligenceI7Routing:
    def teardown_method(self, method):
        _event_name_for_stream.cache_clear()

    def test_event_name_for_intelligence_i7_es_1m(self):
        """intelligence_i7 stream maps to signal_scorecard event."""
        assert _event_name_for_stream("development:intelligence_i7:ESH6:1m") == "signal_scorecard"

    def test_event_name_for_intelligence_i7_nq_5m(self):
        """intelligence_i7 stream for NQ maps to signal_scorecard event."""
        assert _event_name_for_stream("development:intelligence_i7:NQH6:5m") == "signal_scorecard"

    def test_intelligence_data_not_regressed(self):
        """intelligence: stream still returns intelligence_data (no regression)."""
        assert _event_name_for_stream("development:intelligence:ESH6:1m") == "intelligence_data"

    def test_build_stream_list_includes_intelligence_i7(self):
        """_build_stream_list includes at least one intelligence_i7 stream for single TF."""
        streams = _build_stream_list(["ES"], "1m")
        assert any("intelligence_i7" in s for s in streams)

    def test_build_stream_list_includes_two_intelligence_i7_for_two_tfs(self):
        """_build_stream_list includes 2 intelligence_i7 streams for two timeframes."""
        streams = _build_stream_list(["ES"], "1m,5m")
        i7_streams = [s for s in streams if "intelligence_i7" in s]
        assert len(i7_streams) == 2

    def test_build_stream_list_i7_stream_contains_correct_tf(self):
        """intelligence_i7 streams carry the correct timeframe suffix."""
        streams = _build_stream_list(["ES"], "1m,5m")
        i7_streams = [s for s in streams if "intelligence_i7" in s]
        tfs_in_streams = {s.split(":")[-1] for s in i7_streams}
        assert tfs_in_streams == {"1m", "5m"}
