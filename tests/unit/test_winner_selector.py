"""Tests for winner_selector.py — Phase 68-01.

Tests cover:
- _aggregate_via_cis does NOT modify confidence (boost removed)
- n_agreeing_signals and n_opposing_signals captured on selected signal
- Long bias parameterization in _aggregate_fallback
- select_winner accepts long_bias kwarg
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from src.intelligence.pipeline.winner_selector import (
    _aggregate_fallback,
    _aggregate_via_cis,
    select_winner,
)


def _make_signal(
    plugin: str = "TestPlugin",
    direction: int = 1,
    confidence: float = 0.7,
    adjusted_rank: float = 1.0,
    regime_eligible: bool = True,
) -> dict:
    """Create a minimal signal dict for testing."""
    return {
        "setup_plugin": plugin,
        "direction": direction,
        "confidence": confidence,
        "adjusted_rank": adjusted_rank,
        "regime_eligible": regime_eligible,
    }


def _make_cis_result(direction: int = 1, cis_score: float = 0.8) -> MagicMock:
    """Create a mock CIS result with a direction attribute."""
    mock = MagicMock()
    mock.direction = direction
    mock.cis_score = cis_score
    return mock


# ---------------------------------------------------------------------------
# Test 1: _aggregate_via_cis does NOT modify confidence
# ---------------------------------------------------------------------------


class TestCISAggregationNoBoost:
    """Confidence boost per agreeing signal is removed."""

    def test_cis_aggregate_does_not_boost_confidence(self):
        """Returned confidence equals input confidence — no boost applied."""
        signals = [
            _make_signal(plugin="TrendA", direction=1, confidence=0.60),
            _make_signal(plugin="TrendB", direction=1, confidence=0.70),
        ]
        cis_result = _make_cis_result(direction=1)
        selected, method = _aggregate_via_cis(signals, cis_result, signals)

        # confidence should NOT be boosted above the winning signal's original value
        assert selected["confidence"] == 0.60  # lowest adjusted_rank wins

    def test_cis_aggregate_no_boost_with_many_agreeing(self):
        """Even with 5 agreeing signals, confidence is not boosted."""
        signals = [_make_signal(plugin=f"Trend{i}", direction=1, confidence=0.5 + i * 0.05)
                   for i in range(5)]
        cis_result = _make_cis_result(direction=1)
        selected, method = _aggregate_via_cis(signals, cis_result, signals)

        # No boost — confidence should be exactly the winner's input
        assert selected["confidence"] == signals[0]["confidence"]


# ---------------------------------------------------------------------------
# Test 2 & 5: n_agreeing_signals and n_opposing_signals captured
# ---------------------------------------------------------------------------


class TestAgreeingOpposingCapture:
    """n_agreeing_signals and n_opposing_signals captured on selected signal."""

    def test_cis_aggregate_sets_n_agreeing_signals(self):
        """_aggregate_via_cis sets n_agreeing_signals on the selected signal."""
        signals = [
            _make_signal(plugin="TrendA", direction=1),
            _make_signal(plugin="TrendB", direction=1),
            _make_signal(plugin="ShortA", direction=-1),
        ]
        cis_result = _make_cis_result(direction=1)
        selected, _ = _aggregate_via_cis(signals, cis_result, signals)

        assert "n_agreeing_signals" in selected
        assert selected["n_agreeing_signals"] == 2  # two longs
        assert "n_opposing_signals" in selected
        assert selected["n_opposing_signals"] == 1  # one short

    def test_cis_aggregate_n_agreeing_is_integer(self):
        """n_agreeing_signals is an integer, not float."""
        signals = [_make_signal(plugin="A", direction=1)]
        cis_result = _make_cis_result(direction=1)
        selected, _ = _aggregate_via_cis(signals, cis_result, signals)

        assert isinstance(selected["n_agreeing_signals"], int)
        assert isinstance(selected["n_opposing_signals"], int)


# ---------------------------------------------------------------------------
# Test 3: _aggregate_fallback with long_bias=True (default behavior preserved)
# ---------------------------------------------------------------------------


class TestFallbackLongBias:
    """Long bias in tiebreaks is configurable."""

    def test_fallback_tie_long_bias_true_returns_long(self):
        """With longs==shorts and long_bias=True, returns long signal."""
        active = [
            _make_signal(plugin="LongA", direction=1, adjusted_rank=1.0),
            _make_signal(plugin="ShortA", direction=-1, adjusted_rank=2.0),
        ]
        selected, method = _aggregate_fallback(active, active, long_bias=True)

        assert selected["direction"] == 1
        assert method == "priority_majority"

    def test_fallback_majority_long_wins_regardless_of_bias(self):
        """When longs > shorts, long wins regardless of long_bias setting."""
        active = [
            _make_signal(plugin="LongA", direction=1),
            _make_signal(plugin="LongB", direction=1),
            _make_signal(plugin="ShortA", direction=-1),
        ]
        selected_true, _ = _aggregate_fallback(active, active, long_bias=True)
        selected_false, _ = _aggregate_fallback(active, active, long_bias=False)

        assert selected_true["direction"] == 1
        assert selected_false["direction"] == 1


# ---------------------------------------------------------------------------
# Test 4: _aggregate_fallback with long_bias=False
# ---------------------------------------------------------------------------


class TestFallbackNoBias:
    """When long_bias=False and tie, returns highest-ranked regardless of direction."""

    def test_fallback_tie_long_bias_false_returns_highest_ranked(self):
        """With longs==shorts and long_bias=False, returns highest-ranked signal."""
        active = [
            _make_signal(plugin="LongA", direction=1, adjusted_rank=5.0),
            _make_signal(plugin="ShortA", direction=-1, adjusted_rank=1.0),
        ]
        selected, method = _aggregate_fallback(active, active, long_bias=False)

        # ShortA has better (lower) adjusted_rank, so it should win
        assert selected["direction"] == -1
        assert selected["setup_plugin"] == "ShortA"


# ---------------------------------------------------------------------------
# Test: select_winner accepts long_bias kwarg
# ---------------------------------------------------------------------------


class TestSelectWinnerKwarg:
    """select_winner accepts long_bias keyword argument."""

    def test_select_winner_default_long_bias(self):
        """select_winner with default long_bias=True returns long on tie."""
        signals = [
            _make_signal(plugin="LongA", direction=1, adjusted_rank=1.0),
            _make_signal(plugin="ShortA", direction=-1, adjusted_rank=2.0),
        ]
        winner, all_ranked, method = select_winner(signals)

        assert winner is not None
        assert winner["direction"] == 1  # long bias default

    def test_select_winner_explicit_long_bias_false(self):
        """select_winner with long_bias=False on tie returns highest-ranked."""
        signals = [
            _make_signal(plugin="LongA", direction=1, adjusted_rank=5.0),
            _make_signal(plugin="ShortA", direction=-1, adjusted_rank=1.0),
        ]
        winner, all_ranked, method = select_winner(signals, long_bias=False)

        assert winner is not None
        assert winner["direction"] == -1  # short has better rank, no bias

    def test_select_winner_no_boost_with_cis(self):
        """select_winner does not boost confidence when CIS overrides."""
        signals = [
            _make_signal(plugin="TrendA", direction=1, confidence=0.60, adjusted_rank=1.0),
            _make_signal(plugin="TrendB", direction=1, confidence=0.70, adjusted_rank=2.0),
        ]
        cis_result = _make_cis_result(direction=1)
        original_confidence = 0.60  # TrendA wins by adjusted_rank

        winner, _, _ = select_winner(signals, cis_result)

        assert winner["confidence"] == original_confidence

    def test_no_confidence_boost_import(self):
        """_CONFIDENCE_BOOST_PER_AGREE is NOT imported in winner_selector."""
        import src.intelligence.pipeline.winner_selector as ws
        assert not hasattr(ws, "_CONFIDENCE_BOOST_PER_AGREE")
