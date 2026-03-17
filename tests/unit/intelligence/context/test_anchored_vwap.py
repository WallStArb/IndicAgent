"""Tests for AnchoredVWAPPlugin (I4 context tier) — migration from I3/structure with new fields."""

import numpy as np
import pandas as pd
import pytest

_EXPECTED_OUTPUTS = frozenset(
    {
        # Original 8 fields
        "session_vwap",
        "session_vwap_dist_pct",
        "swing_vwap",
        "weekly_vwap",
        "above_session_vwap",
        "above_swing_vwap",
        "above_weekly_vwap",
        "vwap_alignment_score",
        # New 7 fields
        "avwap_upper_band",
        "avwap_lower_band",
        "swing_vwap_upper_band",
        "swing_vwap_lower_band",
        "session_vwap_deviation_sigma",
        "swing_vwap_deviation_sigma",
        "session_vwap_deviation_velocity",
    }
)


def _make_frames(n: int = 50, swing_high_idx: int = 20, swing_low_idx: int = 30) -> dict:
    """Build a frames dict with synthetic OHLCV data and swing index features."""
    rng = np.random.default_rng(42)
    close = 100.0 + rng.normal(0, 1.0, n)
    high = close + rng.uniform(0.1, 0.5, n)
    low = close - rng.uniform(0.1, 0.5, n)
    volume = rng.uniform(1000, 5000, n)
    df = pd.DataFrame({"high": high, "low": low, "close": close, "volume": volume})
    features = {
        "close": float(close[-1]),
        "swing_high_idx": swing_high_idx,
        "swing_low_idx": swing_low_idx,
    }
    return {"main": df, "features": features}


class TestAnchoredVWAPPluginMetadata:
    @pytest.mark.unit
    def test_plugin_name(self):
        """AnchoredVWAPPlugin.name == 'ctx_AnchoredVWAP'."""
        from src.intelligence.context.anchored_vwap import plugin

        assert plugin.name == "ctx_AnchoredVWAP"

    @pytest.mark.unit
    def test_plugin_outputs_contains_all_15_fields(self):
        """plugin.outputs contains all 8 existing + 7 new fields (15 total)."""
        from src.intelligence.context.anchored_vwap import plugin

        assert plugin.outputs == _EXPECTED_OUTPUTS


class TestAnchoredVWAPComputeFull:
    @pytest.mark.unit
    def test_compute_full_returns_all_15_keys(self):
        """compute_full() with 50-bar data returns all 15 field names."""
        from src.intelligence.context.anchored_vwap import plugin

        result = plugin.compute_full(_make_frames(50))
        assert set(result.keys()) == _EXPECTED_OUTPUTS

    @pytest.mark.unit
    def test_compute_full_no_none_values(self):
        """compute_full() with adequate data returns non-None float values for core fields."""
        from src.intelligence.context.anchored_vwap import plugin

        result = plugin.compute_full(_make_frames(50))
        core_fields = {
            "session_vwap",
            "session_vwap_dist_pct",
            "weekly_vwap",
            "above_session_vwap",
            "above_swing_vwap",
            "above_weekly_vwap",
            "vwap_alignment_score",
            "avwap_upper_band",
            "avwap_lower_band",
            "session_vwap_deviation_sigma",
            "session_vwap_deviation_velocity",
        }
        for field in core_fields:
            assert result[field] is not None, f"Expected non-None for {field}"
            assert isinstance(result[field], float), f"Expected float for {field}"

    @pytest.mark.unit
    def test_session_vwap_deviation_sigma_formula(self):
        """session_vwap_deviation_sigma == (close - session_vwap) / session_std."""
        from src.intelligence.context.anchored_vwap import plugin

        n = 50
        rng = np.random.default_rng(7)
        close = 100.0 + rng.normal(0, 1.0, n)
        high = close + 0.3
        low = close - 0.3
        volume = np.ones(n) * 1000.0
        df = pd.DataFrame({"high": high, "low": low, "close": close, "volume": volume})
        frames = {"main": df, "features": {"close": float(close[-1])}}

        result = plugin.compute_full(frames)

        typical = (high + low + close) / 3.0
        tpv = typical * volume
        total_vol = float(volume.sum())
        expected_session_vwap = float(tpv.sum() / total_vol)
        deviations = typical - expected_session_vwap
        session_std = float(np.std(deviations))
        expected_sigma = (float(close[-1]) - expected_session_vwap) / session_std

        assert abs(result["session_vwap_deviation_sigma"] - expected_sigma) < 1e-10

    @pytest.mark.unit
    def test_avwap_bands_formula(self):
        """avwap_upper_band == session_vwap + 2 * session_std; lower == vwap - 2 * std."""
        from src.intelligence.context.anchored_vwap import plugin

        n = 50
        close = np.linspace(99.0, 101.0, n)
        high = close + 0.2
        low = close - 0.2
        volume = np.ones(n) * 1000.0
        df = pd.DataFrame({"high": high, "low": low, "close": close, "volume": volume})
        frames = {"main": df, "features": {"close": float(close[-1])}}

        result = plugin.compute_full(frames)

        typical = (high + low + close) / 3.0
        tpv = typical * volume
        total_vol = float(volume.sum())
        session_vwap = float(tpv.sum() / total_vol)
        deviations = typical - session_vwap
        session_std = float(np.std(deviations))

        assert abs(result["avwap_upper_band"] - (session_vwap + 2.0 * session_std)) < 1e-10
        assert abs(result["avwap_lower_band"] - (session_vwap - 2.0 * session_std)) < 1e-10

    @pytest.mark.unit
    def test_swing_vwap_bands_computed(self):
        """swing_vwap_upper_band and swing_vwap_lower_band are non-None when anchor_idx set."""
        from src.intelligence.context.anchored_vwap import plugin

        frames = _make_frames(50, swing_high_idx=20, swing_low_idx=30)
        result = plugin.compute_full(frames)

        assert result["swing_vwap_upper_band"] is not None
        assert result["swing_vwap_lower_band"] is not None
        assert isinstance(result["swing_vwap_upper_band"], float)
        assert isinstance(result["swing_vwap_lower_band"], float)

    @pytest.mark.unit
    def test_velocity_computed_via_state(self):
        """session_vwap_deviation_velocity is computed from 3-bar sigma history in _state."""
        from src.intelligence.context.anchored_vwap import AnchoredVWAPPlugin

        p = AnchoredVWAPPlugin()
        frames = _make_frames(50)
        frames["symbol"] = "TEST"
        frames["timeframe"] = "1m"

        # Run 3 times to allow state accumulation
        p.compute_full(frames)
        p.compute_full(frames)
        result = p.compute_full(frames)

        assert result["session_vwap_deviation_velocity"] is not None
        assert isinstance(result["session_vwap_deviation_velocity"], float)

    @pytest.mark.unit
    def test_fewer_than_min_lookback_returns_empty(self):
        """compute_full() with < min_lookback bars returns {}."""
        from src.intelligence.context.anchored_vwap import plugin

        df = pd.DataFrame(
            {
                "high": [100.5, 101.0, 100.8],
                "low": [99.5, 100.0, 99.8],
                "close": [100.0, 100.5, 100.2],
                "volume": [1000.0, 1200.0, 800.0],
            }
        )
        frames = {"main": df, "features": {}}
        result = plugin.compute_full(frames)
        assert result == {}

    @pytest.mark.unit
    def test_backward_compatibility_session_vwap(self):
        """session_vwap matches reference computation from original plugin logic."""
        from src.intelligence.context.anchored_vwap import plugin

        n = 50
        close = np.linspace(98.0, 102.0, n)
        high = close + 0.5
        low = close - 0.5
        volume = np.ones(n) * 2000.0
        df = pd.DataFrame({"high": high, "low": low, "close": close, "volume": volume})
        frames = {"main": df, "features": {"close": float(close[-1])}}

        result = plugin.compute_full(frames)

        typical = (high + low + close) / 3.0
        tpv = typical * volume
        expected_vwap = float(tpv.sum() / volume.sum())

        assert abs(result["session_vwap"] - expected_vwap) < 1e-10

    @pytest.mark.unit
    def test_swing_vwap_is_none_without_anchor(self):
        """swing_vwap is None when no swing_high_idx or swing_low_idx in features."""
        from src.intelligence.context.anchored_vwap import plugin

        n = 50
        close = np.linspace(98.0, 102.0, n)
        high = close + 0.5
        low = close - 0.5
        volume = np.ones(n) * 2000.0
        df = pd.DataFrame({"high": high, "low": low, "close": close, "volume": volume})
        frames = {"main": df, "features": {}}

        result = plugin.compute_full(frames)
        assert result["swing_vwap"] is None
        assert result["swing_vwap_upper_band"] is None
        assert result["swing_vwap_lower_band"] is None
        assert result["swing_vwap_deviation_sigma"] is None
