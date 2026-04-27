"""Unit tests for flight_to_quality macro factor."""

from collections import deque
import pytest

from src.intelligence.macro.flight_to_quality import compute_flight_to_quality


class TestFlightToQuality:
    """Test flight-to-quality factor computation."""

    def test_compute_ftq_risk_on(self):
        """Test risk-on regime: SPY up, TLT down → positive score."""
        bars = {
            "SPY": deque([
                {"close": 100.0},
                {"close": 101.0},  # +1% return
                {"close": 102.0},
            ], maxlen=100),
            "TLT": deque([
                {"close": 100.0},
                {"close": 99.0},   # -1% return
                {"close": 98.0},
            ], maxlen=100),
        }

        result = compute_flight_to_quality(bars, lookback=2)

        assert result["ftq_score"] > 0  # SPY outperforming TLT = risk-on
        assert result["ftq_regime"] == "risk_on"

    def test_compute_ftq_risk_off(self):
        """Test risk-off regime: SPY down, TLT up → negative score."""
        bars = {
            "SPY": deque([
                {"close": 100.0},
                {"close": 99.0},   # -1% return
                {"close": 98.0},
            ], maxlen=100),
            "TLT": deque([
                {"close": 100.0},
                {"close": 101.0},  # +1% return
                {"close": 102.0},
            ], maxlen=100),
        }

        result = compute_flight_to_quality(bars, lookback=2)

        assert result["ftq_score"] < 0  # TLT outperforming SPY = risk-off
        assert result["ftq_regime"] == "risk_off"

    def test_compute_ftq_neutral(self):
        """Test neutral regime: SPY/TLT flat → score near 0."""
        bars = {
            "SPY": deque([
                {"close": 100.0},
                {"close": 100.0},  # Flat
                {"close": 100.0},
            ], maxlen=100),
            "TLT": deque([
                {"close": 100.0},
                {"close": 100.0},  # Flat
                {"close": 100.0},
            ], maxlen=100),
        }

        result = compute_flight_to_quality(bars, lookback=2)

        assert abs(result["ftq_score"]) < 0.1  # Near zero
        assert result["ftq_regime"] == "neutral"

    def test_insufficient_data(self):
        """Test insufficient data: Missing TLT/SPY → returns 0.0, neutral."""
        bars = {
            "SPY": deque([], maxlen=100),
            "TLT": deque([], maxlen=100),
        }

        result = compute_flight_to_quality(bars, lookback=10)

        assert result["ftq_score"] == 0.0
        assert result["ftq_regime"] == "neutral"

    def test_ftq_regime_classification(self):
        """Test regime classification thresholds."""
        # Test risk_on threshold (>0.2%)
        bars_risk_on = {
            "SPY": deque([
                {"close": 100.0},
                {"close": 100.3},  # +0.3%
            ], maxlen=100),
            "TLT": deque([
                {"close": 100.0},
                {"close": 100.0},  # Flat
            ], maxlen=100),
        }
        result = compute_flight_to_quality(bars_risk_on, lookback=1)
        assert result["ftq_regime"] == "risk_on"

        # Test risk_off threshold (<-0.2%)
        bars_risk_off = {
            "SPY": deque([
                {"close": 100.0},
                {"close": 100.0},  # Flat
            ], maxlen=100),
            "TLT": deque([
                {"close": 100.0},
                {"close": 100.3},  # +0.3% (TLT up = risk-off)
            ], maxlen=100),
        }
        result = compute_flight_to_quality(bars_risk_off, lookback=1)
        assert result["ftq_regime"] == "risk_off"

        # Test neutral (between thresholds)
        bars_neutral = {
            "SPY": deque([
                {"close": 100.0},
                {"close": 100.1},  # +0.1% (below threshold)
            ], maxlen=100),
            "TLT": deque([
                {"close": 100.0},
                {"close": 100.0},  # Flat
            ], maxlen=100),
        }
        result = compute_flight_to_quality(bars_neutral, lookback=1)
        assert result["ftq_regime"] == "neutral"

    def test_ftq_score_range(self):
        """Test ftq_score is always in [-1, +1]."""
        # Extreme case: SPY +10%, TLT -10%
        bars = {
            "SPY": deque([
                {"close": 100.0},
                {"close": 110.0},  # +10%
            ], maxlen=100),
            "TLT": deque([
                {"close": 100.0},
                {"close": 90.0},   # -10%
            ], maxlen=100),
        }

        result = compute_flight_to_quality(bars, lookback=1)

        assert -1.0 <= result["ftq_score"] <= 1.0

    def test_missing_symbol(self):
        """Test graceful degradation when one symbol missing."""
        bars = {
            "SPY": deque([
                {"close": 100.0},
                {"close": 101.0},
            ], maxlen=100),
            # TLT missing
        }

        result = compute_flight_to_quality(bars, lookback=2)

        # Should return neutral when insufficient data
        assert result["ftq_score"] == 0.0
        assert result["ftq_regime"] == "neutral"
