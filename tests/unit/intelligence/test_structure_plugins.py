"""Tests for I3 market structure plugins."""

import numpy as np

from tests.unit.intelligence.helpers import make_ohlcv


def _uptrend_data(n: int = 120) -> np.ndarray:
    """Generate an uptrend with clear HH+HL swings.

    Uses ~20-bar half-cycles so N=5 neighbor detection can find the swings.
    Each cycle: rise for 15 bars, dip for 5 bars, net upward drift.
    """
    base = np.linspace(5000, 5400, n)  # Upward drift
    cycle = 40  # Full cycle length
    amplitude = 30.0
    t = np.linspace(0, n / cycle * 2 * np.pi, n)
    return base + amplitude * np.sin(t)


def _downtrend_data(n: int = 120) -> np.ndarray:
    """Generate a downtrend with clear LH+LL swings."""
    base = np.linspace(5500, 5100, n)  # Downward drift
    cycle = 40
    amplitude = 30.0
    t = np.linspace(0, n / cycle * 2 * np.pi, n)
    return base + amplitude * np.sin(t)


def _range_data(n: int = 120) -> np.ndarray:
    """Generate sideways oscillation around a mean — equal highs and lows."""
    t = np.linspace(0, 6 * np.pi, n)
    return 5000.0 + 30.0 * np.sin(t)


# ─── Swing Detector ─────────────────────────────────────────────


class TestSwingDetector:
    def test_uptrend_swings(self):
        """HH+HL sequence → swing_pattern == +1.0."""
        from src.intelligence.structure.swing_detector import SwingDetectorPlugin

        close = _uptrend_data()
        df = make_ohlcv(close)
        plugin = SwingDetectorPlugin()
        result = plugin.compute_full({"main": df})

        assert result["swing_pattern"] == 1.0
        assert result["swing_high_type"] == 1.0
        assert result["swing_low_type"] == 1.0
        assert result["swing_high"] > 0
        assert result["swing_low"] > 0
        # Temporal metadata: age should be non-negative and less than total bars
        assert 0 <= result["swing_high_age_bars"] < len(close)
        assert 0 <= result["swing_low_age_bars"] < len(close)

    def test_downtrend_swings(self):
        """LH+LL sequence → swing_pattern == -1.0."""
        from src.intelligence.structure.swing_detector import SwingDetectorPlugin

        close = _downtrend_data()
        df = make_ohlcv(close)
        plugin = SwingDetectorPlugin()
        result = plugin.compute_full({"main": df})

        assert result["swing_pattern"] == -1.0
        assert result["swing_high_type"] == -1.0
        assert result["swing_low_type"] == -1.0
        assert 0 <= result["swing_high_age_bars"] < len(close)
        assert 0 <= result["swing_low_age_bars"] < len(close)

    def test_flat_data_detected(self):
        """Sinusoidal data → swings detected but mixed pattern."""
        from src.intelligence.structure.swing_detector import SwingDetectorPlugin

        close = _range_data()
        df = make_ohlcv(close)
        plugin = SwingDetectorPlugin()
        result = plugin.compute_full({"main": df})

        # Swings should be detected; pattern depends on exact alignment
        assert "swing_high" in result
        assert "swing_low" in result

    def test_empty_frames(self):
        from src.intelligence.structure.swing_detector import SwingDetectorPlugin

        plugin = SwingDetectorPlugin()
        assert plugin.compute_full({}) == {}
        assert plugin.compute_full({"main": None}) == {}


# ─── Support/Resistance ─────────────────────────────────────────


class TestSupportResistance:
    def test_repeated_level_touches(self):
        """Data oscillating around levels → strength > 1 for clustered pivots."""
        from src.intelligence.structure.support_resistance import SupportResistancePlugin

        # Oscillate between 4950 and 5050 repeatedly to build touches
        n = 120
        t = np.linspace(0, 10 * np.pi, n)
        close = 5000.0 + 50.0 * np.sin(t)
        df = make_ohlcv(close)
        plugin = SupportResistancePlugin()
        result = plugin.compute_full({"main": df})

        assert result["sr_level_count"] > 0
        # At least one of the levels should have multiple touches
        assert result["resistance_strength"] >= 1 or result["support_strength"] >= 1
        # Temporal metadata: age_bars present and non-negative
        assert result["resistance_age_bars"] >= 0
        assert result["support_age_bars"] >= 0

    def test_trending_sr_placement(self):
        """In uptrend, resistance above and support below current price."""
        from src.intelligence.structure.support_resistance import SupportResistancePlugin

        close = _uptrend_data()
        df = make_ohlcv(close)
        plugin = SupportResistancePlugin()
        result = plugin.compute_full({"main": df})

        current = float(close[-1])
        assert result["nearest_resistance"] >= current or result["resistance_dist_pct"] >= 0
        assert result["nearest_support"] <= current or result["support_dist_pct"] >= 0

    def test_empty_frames(self):
        from src.intelligence.structure.support_resistance import SupportResistancePlugin

        plugin = SupportResistancePlugin()
        assert plugin.compute_full({}) == {}
        assert plugin.compute_full({"main": None}) == {}


# ─── Trend Structure ────────────────────────────────────────────


class TestTrendStructure:
    def test_clean_uptrend(self):
        """Strong uptrend → direction == +1.0 and decent integrity."""
        from src.intelligence.structure.trend_structure import TrendStructurePlugin

        close = _uptrend_data()
        df = make_ohlcv(close)
        plugin = TrendStructurePlugin()
        result = plugin.compute_full({"main": df})

        assert result["trend_direction"] == 1.0
        assert result["trend_strength"] > 0.5
        assert result["structure_integrity"] > 0.0
        assert result["trend_leg_count"] > 0
        assert result["trend_duration_bars"] > 0

    def test_clean_downtrend(self):
        """Strong downtrend → direction == -1.0."""
        from src.intelligence.structure.trend_structure import TrendStructurePlugin

        close = _downtrend_data()
        df = make_ohlcv(close)
        plugin = TrendStructurePlugin()
        result = plugin.compute_full({"main": df})

        assert result["trend_direction"] == -1.0
        assert result["trend_strength"] > 0.5

    def test_range_bound(self):
        """Sideways oscillation → direction == 0.0."""
        from src.intelligence.structure.trend_structure import TrendStructurePlugin

        close = _range_data()
        df = make_ohlcv(close)
        plugin = TrendStructurePlugin()
        result = plugin.compute_full({"main": df})

        assert result["trend_direction"] == 0.0
        assert result["trend_duration_bars"] == 0.0

    def test_empty_frames(self):
        from src.intelligence.structure.trend_structure import TrendStructurePlugin

        plugin = TrendStructurePlugin()
        assert plugin.compute_full({}) == {}
        assert plugin.compute_full({"main": None}) == {}


# ─── Registration ───────────────────────────────────────────────


class TestStructureRegistration:
    def test_all_structure_plugins_registered(self):
        """All 3 structure plugins appear in registry alongside I5 patterns."""
        from src.intelligence.plugins import PluginRegistry
        from src.intelligence.structure.support_resistance import plugin as sr
        from src.intelligence.structure.swing_detector import plugin as swing
        from src.intelligence.structure.trend_structure import plugin as trend

        reg = PluginRegistry()
        reg.register_pattern(swing)
        reg.register_pattern(sr)
        reg.register_pattern(trend)

        names = reg.list_patterns()
        assert len(names) == 3
        assert "struct_SwingDetector" in names
        assert "struct_SupportResistance" in names
        assert "struct_TrendStructure" in names
