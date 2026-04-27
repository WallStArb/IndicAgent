"""Unit tests for yield curve slope macro factor.

TDD RED→GREEN→REFACTOR cycle for yield_curve.py.
"""

from __future__ import annotations

from collections import deque

from src.intelligence.macro.yield_curve import compute_yield_curve_slope


class TestYieldCurveSlope:
    """Test suite for compute_yield_curve_slope()."""

    def test_compute_yield_curve_slope_with_sufficient_data(self):
        """Verify yield curve slope computed correctly with sufficient bars."""
        # Create mock bars data (price up = yield down)
        bars = {
            "ZT": deque(
                [
                    {"close": 108.0, "ts": "2026-01-01T10:00:00Z"},
                    {"close": 108.5, "ts": "2026-01-01T10:01:00Z"},
                    {"close": 109.0, "ts": "2026-01-01T10:02:00Z"},
                ],
                maxlen=100,
            ),
            "ZN": deque(
                [
                    {"close": 110.0, "ts": "2026-01-01T10:00:00Z"},
                    {"close": 110.5, "ts": "2026-01-01T10:01:00Z"},
                    {"close": 111.0, "ts": "2026-01-01T10:02:00Z"},
                ],
                maxlen=100,
            ),
            "ZB": deque(
                [
                    {"close": 115.0, "ts": "2026-01-01T10:00:00Z"},
                    {"close": 115.5, "ts": "2026-01-01T10:01:00Z"},
                    {"close": 116.0, "ts": "2026-01-01T10:02:00Z"},
                ],
                maxlen=100,
            ),
        }

        result = compute_yield_curve_slope(bars, lookback=3)

        # Verify output structure
        assert "yield_curve_slope" in result
        assert "yield_curve_regime" in result
        assert isinstance(result["yield_curve_slope"], float)
        assert isinstance(result["yield_curve_regime"], str)

        # Verify slope in valid range [-1, +1]
        assert -1.0 <= result["yield_curve_slope"] <= 1.0

        # Verify regime is one of expected values
        assert result["yield_curve_regime"] in {"steepening", "flattening", "inverted", "normal"}

    def test_yield_curve_steepening_regime(self):
        """Verify steepening regime when ZT up (short rates down) more than ZB."""
        bars = {
            "ZT": deque([{"close": 110.0}] * 10, maxlen=100),  # Short rates down significantly
            "ZN": deque([{"close": 110.0}] * 10, maxlen=100),
            "ZB": deque([{"close": 115.0}] * 10, maxlen=100),  # Long rates unchanged
        }

        result = compute_yield_curve_slope(bars, lookback=10)

        # Positive slope = steepening
        assert result["yield_curve_slope"] > 0.0
        assert result["yield_curve_regime"] in {"steepening", "normal"}

    def test_yield_curve_flattening_regime(self):
        """Verify flattening regime when ZT down (short rates up) more than ZB."""
        bars = {
            "ZT": deque(
                [{"close": 106.0}] * 10, maxlen=100
            ),  # Short rates up significantly (price lower)
            "ZN": deque([{"close": 110.0}] * 10, maxlen=100),
            "ZB": deque(
                [{"close": 105.0}] * 10, maxlen=100
            ),  # Long rates down EVEN MORE (price even lower)
        }

        result = compute_yield_curve_slope(bars, lookback=10)

        # When ZB drops more than ZT, long rates fall more than short rates = flattening
        assert result["yield_curve_slope"] < 0.0
        assert result["yield_curve_regime"] in {"flattening", "inverted"}

    def test_yield_curve_inverted_regime(self):
        """Verify inverted regime when ZB yield > ZT yield (curve inversion)."""
        bars = {
            "ZT": deque(
                [{"close": 110.0}] * 10, maxlen=100
            ),  # Short-term yield lower (price higher)
            "ZN": deque([{"close": 110.0}] * 10, maxlen=100),
            "ZB": deque(
                [{"close": 105.0}] * 10, maxlen=100
            ),  # Long-term yield HIGHER (price lower)
        }

        result = compute_yield_curve_slope(bars, lookback=10)

        # Inverted curve
        assert result["yield_curve_regime"] == "inverted"

    def test_insufficient_data_returns_default(self):
        """Verify default values returned when insufficient bars available."""
        bars = {
            "ZT": deque([{"close": 108.0}], maxlen=100),  # Only 1 bar
            "ZN": deque([{"close": 110.0}], maxlen=100),
            "ZB": deque([{"close": 115.0}], maxlen=100),
        }

        result = compute_yield_curve_slope(bars, lookback=10)

        # Should return default values
        assert result["yield_curve_slope"] == 0.0
        assert result["yield_curve_regime"] == "normal"

    def test_missing_instruments_returns_default(self):
        """Verify default values when rate futures symbols missing."""
        bars = {
            "ES": deque([{"close": 4000.0}] * 10, maxlen=100),  # Not a rate future
        }

        result = compute_yield_curve_slope(bars, lookback=10)

        # Should return default values
        assert result["yield_curve_slope"] == 0.0
        assert result["yield_curve_regime"] == "normal"
