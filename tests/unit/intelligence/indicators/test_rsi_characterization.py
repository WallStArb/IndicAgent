"""Characterization tests for RSI zero-loss guard behavior.

These tests document and pin existing behavior — do not modify without
understanding the Wilder smoothing math.
"""

import pandas as pd
import pytest

from src.intelligence.indicators.rsi import RSIPlugin


@pytest.mark.unit
class TestRSIZeroLossCharacterization:
    """Characterization tests pinning RSI zero-loss and normal-path behavior."""

    def test_rsi_zero_loss_returns_100(self):
        """Characterization: when avg_loss decays to 0.0, RSI must return exactly 100.0."""
        p = RSIPlugin()
        p._state = {"rsi_14": {"avg_gain": 1.5, "avg_loss": 0.0, "prev_close": 100.0}}
        df = pd.DataFrame({"close": [101.0]})
        result = p.compute_next({"main": df})
        assert result["rsi_14"] == 100.0

    def test_rsi_normal_path_formula(self):
        """Characterization: normal path (avg_loss > 0) returns correct 100 - 100/(1+RS) value.

        With avg_gain=1.0, avg_loss=1.0 (RS=1.0) and a flat close (delta=0):
        - avg_gain decays: (1.0*13 + 0) / 14 = 13/14
        - avg_loss decays: (1.0*13 + 0) / 14 = 13/14
        - RS stays 1.0, RSI stays 50.0
        """
        p = RSIPlugin()
        p._state = {"rsi_14": {"avg_gain": 1.0, "avg_loss": 1.0, "prev_close": 100.0}}
        df = pd.DataFrame({"close": [100.0]})
        result = p.compute_next({"main": df})
        assert result["rsi_14"] == pytest.approx(50.0, abs=0.01)

    def test_rsi_state_persists_across_calls(self):
        """Characterization: state mutates correctly across two consecutive compute_next() calls.

        Wilder smoothing (period=14):
        Initial: avg_gain=0.5, avg_loss=0.5, prev_close=100.0

        Call 1: close=101.0 (delta=+1.0, gain=1.0, loss=0.0)
          avg_gain = (0.5*13 + 1.0) / 14 = 7.5 / 14
          avg_loss = (0.5*13 + 0.0) / 14 = 6.5 / 14
          RSI1 > 50 (gain > loss)

        Call 2: close=100.5 (delta=-0.5 relative to 101.0, gain=0.0, loss=0.5)
          avg_gain decays, avg_loss increases
          RSI2 < RSI1 (loss added, gain decayed)
        """
        p = RSIPlugin()
        p._state = {"rsi_14": {"avg_gain": 0.5, "avg_loss": 0.5, "prev_close": 100.0}}

        df1 = pd.DataFrame({"close": [101.0]})
        result1 = p.compute_next({"main": df1})
        rsi1 = result1["rsi_14"]

        df2 = pd.DataFrame({"close": [100.5]})
        result2 = p.compute_next({"main": df2})
        rsi2 = result2["rsi_14"]

        assert 0.0 <= rsi1 <= 100.0, f"RSI1 out of range: {rsi1}"
        assert 0.0 <= rsi2 <= 100.0, f"RSI2 out of range: {rsi2}"
        assert rsi2 < rsi1, f"Expected RSI to drop after loss bar: rsi1={rsi1:.4f}, rsi2={rsi2:.4f}"
