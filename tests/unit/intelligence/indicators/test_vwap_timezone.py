"""Tests for VWAPPlugin timezone-aware datetime handling (BUG-01 fix)."""

from __future__ import annotations

from datetime import UTC, datetime

import numpy as np
import pandas as pd
import pytest


def _make_tz_frames(n: int = 30) -> dict:
    """Build a frames dict with tz-aware UTC timestamps in the 'main' DataFrame."""
    base = datetime(2026, 3, 18, 14, 0, 0, tzinfo=UTC)
    timestamps = [base.replace(minute=i % 60, hour=14 + i // 60) for i in range(n)]
    close = 5000.0 + np.cumsum(np.random.default_rng(0).normal(0, 1, n))
    spread = np.abs(close) * 0.001
    df = pd.DataFrame(
        {
            "timestamp": timestamps,
            "open": close - spread * 0.5,
            "high": close + spread,
            "low": close - spread,
            "close": close,
            "volume": np.full(n, 1000.0),
        }
    )
    return {"main": df}


def _make_naive_frames(n: int = 30) -> dict:
    """Build a frames dict with naive timestamps for comparison."""
    base = datetime(2026, 3, 18, 14, 0, 0)  # no tzinfo
    timestamps = [base.replace(minute=i % 60, hour=14 + i // 60) for i in range(n)]
    close = 5000.0 + np.cumsum(np.random.default_rng(1).normal(0, 1, n))
    spread = np.abs(close) * 0.001
    df = pd.DataFrame(
        {
            "timestamp": timestamps,
            "open": close - spread * 0.5,
            "high": close + spread,
            "low": close - spread,
            "close": close,
            "volume": np.full(n, 1000.0),
        }
    )
    return {"main": df}


class TestVWAPTimezoneHandling:
    @pytest.mark.unit
    def test_compute_full_handles_tz_aware_timestamps(self):
        """VWAPPlugin.compute_full() must not raise on tz-aware UTC timestamps.

        Regression test for: 'Tz-aware datetime.datetime cannot be converted
        to datetime64 unless utc=True' (fired on every bar for all 61 symbols).
        """
        from src.intelligence.indicators.vwap import VWAPPlugin

        plugin = VWAPPlugin()
        frames = _make_tz_frames(n=30)
        # Must not raise TypeError on tz-aware timestamps
        result = plugin.compute_full(frames)
        assert result != {}, "Expected VWAP result for valid tz-aware input"
        assert "vwap" in result

    @pytest.mark.unit
    def test_compute_next_handles_tz_aware_timestamps(self):
        """VWAPPlugin.compute_next() must not raise on tz-aware timestamps."""
        from src.intelligence.indicators.vwap import VWAPPlugin

        plugin = VWAPPlugin()
        frames = _make_tz_frames(n=30)
        # Seed state via compute_full first
        plugin.compute_full(frames)
        # Then compute_next should also handle tz-aware ts
        result = plugin.compute_next(frames)
        assert isinstance(result, dict)
        if result:  # may return {} on session boundary — that's fine
            assert "vwap" in result

    @pytest.mark.unit
    def test_compute_full_also_works_with_naive_timestamps(self):
        """VWAPPlugin.compute_full() still works with naive timestamps (regression guard)."""
        from src.intelligence.indicators.vwap import VWAPPlugin

        plugin = VWAPPlugin()
        frames = _make_naive_frames(n=30)
        result = plugin.compute_full(frames)
        assert result != {}
        assert "vwap" in result

    @pytest.mark.unit
    def test_vwap_output_keys_present(self):
        """compute_full() returns all expected VWAP output keys."""
        from src.intelligence.indicators.vwap import VWAPPlugin

        plugin = VWAPPlugin()
        frames = _make_tz_aware_frames_same_day(n=20)
        result = plugin.compute_full(frames)
        assert result != {}
        expected_keys = {"vwap", "vwap_upper_1", "vwap_lower_1", "vwap_upper_2", "vwap_lower_2", "vwap_std"}
        assert expected_keys.issubset(result.keys()), f"Missing keys: {expected_keys - result.keys()}"


def _make_tz_aware_frames_same_day(n: int = 20) -> dict:
    """Tz-aware frames where all bars are on the same calendar date."""
    base = datetime(2026, 3, 18, 14, 0, 0, tzinfo=UTC)
    timestamps = [base.replace(minute=i) for i in range(n)]
    close = 5000.0 + np.arange(n, dtype=float)
    spread = 1.0
    df = pd.DataFrame(
        {
            "timestamp": timestamps,
            "open": close - 0.5,
            "high": close + spread,
            "low": close - spread,
            "close": close,
            "volume": np.full(n, 500.0),
        }
    )
    return {"main": df}
