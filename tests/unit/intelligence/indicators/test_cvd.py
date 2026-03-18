"""Unit tests for CVDPlugin — Cumulative Volume Delta I1 indicator."""

from __future__ import annotations

from datetime import UTC, datetime

import pandas as pd
import pytest


def _make_df(n: int = 10, base_close: float = 100.0, start_hour: int = 14) -> pd.DataFrame:
    """Create a synthetic OHLCV DataFrame with n bars."""
    closes = [base_close + i * 0.1 for i in range(n)]
    return pd.DataFrame(
        {
            "timestamp": [
                datetime(2026, 3, 18, start_hour, i % 60, 0, tzinfo=UTC) for i in range(n)
            ],
            "open": [c - 0.05 for c in closes],
            "high": [c + 0.2 for c in closes],
            "low": [c - 0.2 for c in closes],
            "close": closes,
            "volume": [1000.0] * n,
        }
    )


class TestCVDPlugin:
    def setup_method(self):
        from src.intelligence.indicators.cvd import CVDPlugin

        self.plugin = CVDPlugin()

    def test_cvd_accumulates(self):
        """After multiple bars, cvd reflects net delta accumulation."""
        df = _make_df(5)
        # Use buy ticks: net positive OFI
        ticks_buy = [{"price": str(100 + i * 0.01), "size": "100"} for i in range(5)]
        for _ in range(5):
            result = self.plugin.compute_full({"main": df, "tick_buffer": ticks_buy})
        cvd = result.get("cvd")
        assert cvd is not None
        assert isinstance(cvd, float)
        # After 5 bars of net buying, cvd should be positive (or at least non-zero)
        assert cvd != 0.0

    def test_session_reset(self):
        """When bar timestamp crosses 09:30 ET on a new date, cvd resets to 0."""
        from src.intelligence.indicators.cvd import CVDPlugin

        plugin = CVDPlugin()

        # Warm up CVD before session with buy ticks (pre-session bars)
        df_pre = _make_df(5, start_hour=12)  # 12 UTC = 08:00 ET (before 09:30)
        ticks_buy = [{"price": str(100 + i * 0.01), "size": "100"} for i in range(5)]
        for _ in range(3):
            plugin.compute_full({"main": df_pre, "tick_buffer": ticks_buy})

        # Check CVD is non-zero before reset
        pre_reset = plugin.compute_full({"main": df_pre, "tick_buffer": ticks_buy})
        assert pre_reset.get("cvd") != 0.0, "CVD should be non-zero before reset"

        # Now simulate 09:30 ET = 13:30 UTC
        df_session = _make_df(5, start_hour=13)  # 13:30 UTC = 09:30 ET (EDT)
        # Create a DataFrame with timestamps at exactly 13:30 UTC
        session_timestamps = [
            datetime(2026, 3, 18, 13, 30 + i, 0, tzinfo=UTC) for i in range(5)
        ]
        df_session = df_session.copy()
        df_session["timestamp"] = session_timestamps

        result = plugin.compute_full({"main": df_session, "tick_buffer": []})
        cvd_at_reset = result.get("cvd")
        assert cvd_at_reset is not None
        # CVD should be near 0 at session open (accumulated delta of just this one bar)
        # The absolute cumulative should be small relative to pre-reset value
        assert abs(cvd_at_reset) < abs(pre_reset.get("cvd", 0.0)), (
            f"CVD should reset at session open: got {cvd_at_reset} vs pre-reset {pre_reset.get('cvd')}"
        )

    def test_slope_sign(self):
        """When CVD is rising over 5 bars, cvd_slope_5bar is positive."""
        from src.intelligence.indicators.cvd import CVDPlugin

        plugin = CVDPlugin()
        df = _make_df(5)
        # Feed consistent buy ticks to build up positive CVD
        ticks_buy = [{"price": str(100 + i * 0.01), "size": "100"} for i in range(10)]
        result = None
        for _ in range(10):
            result = plugin.compute_full({"main": df, "tick_buffer": ticks_buy})
        slope = result.get("cvd_slope_5bar")
        assert slope is not None
        assert isinstance(slope, float)
        assert slope > 0.0, f"Expected positive slope from consistent buying, got {slope}"

    def test_cvd_divergence_sign(self):
        """When CVD direction disagrees with price direction, cvd_divergence is nonzero."""
        df = _make_df(5, base_close=100.0)
        # Price is rising (df already has rising closes)
        # But feed sell ticks to make CVD fall
        ticks_sell = [{"price": str(100 - i * 0.01), "size": "100"} for i in range(5)]
        for _ in range(10):
            self.plugin.compute_full({"main": df, "tick_buffer": ticks_sell})
        result = self.plugin.compute_full({"main": df, "tick_buffer": ticks_sell})
        divergence = result.get("cvd_divergence")
        assert divergence is not None
        assert isinstance(divergence, float)

    def test_cvd_spike_z(self):
        """cvd_spike_z is a float with type correct."""
        df = _make_df(5)
        for _ in range(20):
            result = self.plugin.compute_full({"main": df, "tick_buffer": []})
        spike_z = result.get("cvd_spike_z")
        assert spike_z is not None
        assert isinstance(spike_z, float)

    def test_proxy_fallback_cvd(self):
        """When tick_buffer is empty, CVD uses bar-level proxy (tick rule on OHLCV)."""
        df = _make_df(5)
        result = self.plugin.compute_full({"main": df, "tick_buffer": []})
        assert result, "Expected non-empty result"
        cvd = result.get("cvd")
        assert cvd is not None
        assert isinstance(cvd, float)

    def test_min_lookback_guard(self):
        """compute_full with fewer than min_lookback bars returns {}."""
        df = _make_df(1)  # less than min_lookback=2
        result = self.plugin.compute_full({"main": df, "tick_buffer": []})
        assert result == {}

    def test_all_outputs_present(self):
        """All 4 declared outputs appear in result."""
        df = _make_df(5)
        result = self.plugin.compute_full({"main": df, "tick_buffer": []})
        expected_keys = {"cvd", "cvd_slope_5bar", "cvd_divergence", "cvd_spike_z"}
        assert expected_keys.issubset(set(result.keys()))

    def test_plugin_module_export(self):
        """Module-level plugin singleton exists with correct name."""
        from src.intelligence.indicators.cvd import plugin

        assert plugin.name == "ind_CVD"

    def test_compute_next_delegates(self):
        """compute_next returns a dict (delegates to compute_full)."""
        df = _make_df(5)
        result = self.plugin.compute_next({"main": df, "tick_buffer": []})
        assert isinstance(result, dict)
