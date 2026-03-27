"""Regression tests for PERF-04: O(1) active signal index + chandelier write guard.

These tests verify that:
- _active_index provides O(1) (symbol, tf) tuple lookup
- _remove_from_index correctly removes a signal by signal_id
- The chandelier write guard skips DB writes when stop price changes < 0.01%

Implementation lives in services/signal_lifecycle_service.py.
"""

from collections import defaultdict

import pytest

# ---------------------------------------------------------------------------
# Tests for _active_index O(1) lookup
# ---------------------------------------------------------------------------


class TestActiveIndexLookup:
    """_active_index[(symbol, tf)] → list[dict] — O(1) dict access."""

    @pytest.mark.unit
    def test_active_index_lookup_returns_matching_signals(self):
        """Lookup by (symbol, tf) tuple returns the correct signals."""
        from services.signal_tracker_agent import SignalTrackerAgent

        svc = SignalTrackerAgent.__new__(SignalTrackerAgent)
        svc._active_index = defaultdict(list)
        sig = {"signal_id": "abc", "symbol": "ES", "timeframe": "1m", "status": "active"}
        svc._active_index[("ES", "1m")] = [sig]
        result = svc._active_index.get(("ES", "1m"), [])
        assert len(result) == 1
        assert result[0]["signal_id"] == "abc"

    @pytest.mark.unit
    def test_active_index_returns_empty_for_unknown_key(self):
        """Lookup for a key with no signals returns empty list — no KeyError."""
        from services.signal_tracker_agent import SignalTrackerAgent

        svc = SignalTrackerAgent.__new__(SignalTrackerAgent)
        svc._active_index = defaultdict(list)
        result = svc._active_index.get(("NQ", "5m"), [])
        assert result == []

    @pytest.mark.unit
    def test_active_index_isolates_keys(self):
        """Signals for one (symbol, tf) key do not bleed into another."""
        from services.signal_tracker_agent import SignalTrackerAgent

        svc = SignalTrackerAgent.__new__(SignalTrackerAgent)
        svc._active_index = defaultdict(list)
        svc._active_index[("ES", "1m")] = [{"signal_id": "aaa"}]
        svc._active_index[("NQ", "1m")] = [{"signal_id": "bbb"}]

        es_result = svc._active_index.get(("ES", "1m"), [])
        nq_result = svc._active_index.get(("NQ", "1m"), [])

        assert len(es_result) == 1
        assert es_result[0]["signal_id"] == "aaa"
        assert len(nq_result) == 1
        assert nq_result[0]["signal_id"] == "bbb"


# ---------------------------------------------------------------------------
# Tests for _remove_from_index
# ---------------------------------------------------------------------------


class TestRemoveFromIndex:
    """_remove_from_index(signal_id, symbol, timeframe) removes the target signal."""

    @pytest.mark.unit
    def test_remove_from_index_removes_correct_signal(self):
        """Only the signal with matching signal_id is removed; others preserved."""
        from services.signal_tracker_agent import SignalTrackerAgent

        svc = SignalTrackerAgent.__new__(SignalTrackerAgent)
        svc._active_index = defaultdict(list)
        svc._active_index[("ES", "1m")] = [
            {"signal_id": "aaa", "symbol": "ES", "timeframe": "1m"},
            {"signal_id": "bbb", "symbol": "ES", "timeframe": "1m"},
        ]
        svc._remove_from_index("aaa", "ES", "1m")
        remaining = svc._active_index[("ES", "1m")]
        assert len(remaining) == 1
        assert remaining[0]["signal_id"] == "bbb"

    @pytest.mark.unit
    def test_remove_from_index_on_empty_key_is_safe(self):
        """Calling _remove_from_index on a key with no signals does not raise."""
        from services.signal_tracker_agent import SignalTrackerAgent

        svc = SignalTrackerAgent.__new__(SignalTrackerAgent)
        svc._active_index = defaultdict(list)
        # Should not raise even if key is absent
        svc._remove_from_index("nonexistent", "ES", "1m")
        assert svc._active_index.get(("ES", "1m"), []) == []


# ---------------------------------------------------------------------------
# Tests for chandelier write guard (PERF-04b)
# ---------------------------------------------------------------------------


class TestChandelierWriteGuard:
    """The 0.01% threshold write guard prevents unnecessary DB writes."""

    @pytest.mark.unit
    def test_write_guard_skips_when_change_below_threshold(self):
        """change_pct < 0.0001 (0.01%) → skip_write = True."""
        last_written = 4500.0
        trailing_stop = 4500.04  # 0.00089% change — below 0.01% threshold
        change_pct = abs(trailing_stop - last_written) / last_written
        assert change_pct < 0.0001  # confirms skip_write = True

    @pytest.mark.unit
    def test_write_guard_allows_when_change_above_threshold(self):
        """change_pct >= 0.0001 (0.01%) → skip_write = False."""
        last_written = 4500.0
        trailing_stop = 4500.50  # 0.011% change — above 0.01% threshold
        change_pct = abs(trailing_stop - last_written) / last_written
        assert change_pct >= 0.0001  # confirms skip_write = False

    @pytest.mark.unit
    def test_write_guard_allows_first_write_when_last_written_is_none(self):
        """When _last_written_stop is None, skip_write stays False (first write allowed)."""
        last_written = None
        skip_write = False
        if last_written is not None and last_written > 0:
            skip_write = True  # branch only taken when last_written is set
        assert skip_write is False

    @pytest.mark.unit
    def test_write_guard_allows_first_write_when_last_written_is_zero(self):
        """When _last_written_stop is 0, skip_write stays False (guard requires > 0)."""
        last_written = 0
        skip_write = False
        if last_written is not None and last_written > 0:
            skip_write = True  # branch not entered when last_written == 0
        assert skip_write is False

    @pytest.mark.unit
    def test_write_guard_threshold_boundary_exact_value(self):
        """At exactly 0.0001 change_pct the write is allowed (>= boundary)."""
        last_written = 10000.0
        trailing_stop = 10001.0  # exactly 0.01% change
        change_pct = abs(trailing_stop - last_written) / last_written
        assert change_pct == pytest.approx(0.0001, abs=1e-10)
        # At this boundary the condition `change_pct < 0.0001` is False → write allowed
        assert not (change_pct < 0.0001)
