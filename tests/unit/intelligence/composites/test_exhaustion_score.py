# tests/unit/intelligence/composites/test_exhaustion_score.py
"""RED test stubs for ExhaustionScorePlugin (Plan 03 target).

All tests FAIL with ImportError until Plan 03 creates
src/intelligence/composites/exhaustion_score.py.
"""

from __future__ import annotations

import pytest

from src.intelligence.composites.exhaustion_score import ExhaustionScorePlugin


def make_frames(
    rsi_14=50.0,
    rsi_curvature=0.0,
    macd_hist_slope=0.0,
    prev_exhaustion_score=None,
    prev_exhaustion_side=None,
    prev_exhaustion_bars=None,
) -> dict:
    """Build minimal frames dict for ExhaustionScore tests."""
    features: dict = {
        "rsi_14": rsi_14,
        "rsi_curvature": rsi_curvature,
        "macd_hist_slope": macd_hist_slope,
    }
    prev: dict = {}
    if prev_exhaustion_score is not None:
        prev["exhaustion_score"] = prev_exhaustion_score
    if prev_exhaustion_side is not None:
        prev["exhaustion_side"] = prev_exhaustion_side
    if prev_exhaustion_bars is not None:
        prev["exhaustion_bars"] = prev_exhaustion_bars
    return {"features": features, "prev_features": prev}


# ── score tier tests ──────────────────────────────────────────────────────────


def test_exhaustion_score_1_0_all_three_bull_conditions():
    """3/3 bullish conditions: rsi>70, curvature<0, hist_slope<0 → score=1.0."""
    plugin = ExhaustionScorePlugin()
    result = plugin.compute_next(
        make_frames(
            rsi_14=75.0,
            rsi_curvature=-0.5,
            macd_hist_slope=-0.1,
        )
    )
    assert result["exhaustion_score"] == pytest.approx(1.0)


def test_exhaustion_score_0_6_two_of_three_bull_conditions():
    """2/3 bullish conditions: rsi>70 and curvature<0, but hist_slope>0 → score=0.6."""
    plugin = ExhaustionScorePlugin()
    result = plugin.compute_next(
        make_frames(
            rsi_14=75.0,
            rsi_curvature=-0.5,
            macd_hist_slope=0.1,
        )
    )
    assert result["exhaustion_score"] == pytest.approx(0.6)


def test_exhaustion_score_0_2_one_of_three_bull_conditions():
    """1/3 bullish conditions: rsi>70 only (curvature and hist_slope wrong) → score=0.2."""
    plugin = ExhaustionScorePlugin()
    result = plugin.compute_next(
        make_frames(
            rsi_14=75.0,
            rsi_curvature=0.3,
            macd_hist_slope=0.1,
        )
    )
    assert result["exhaustion_score"] == pytest.approx(0.2)


def test_exhaustion_score_0_0_no_conditions():
    """No exhaustion conditions met → score=0.0."""
    plugin = ExhaustionScorePlugin()
    result = plugin.compute_next(
        make_frames(
            rsi_14=55.0,
            rsi_curvature=0.1,
            macd_hist_slope=0.2,
        )
    )
    assert result["exhaustion_score"] == pytest.approx(0.0)


def test_exhaustion_score_bear_all_three():
    """3/3 bearish conditions: rsi<30, curvature>0, hist_slope>0 → score=1.0."""
    plugin = ExhaustionScorePlugin()
    result = plugin.compute_next(
        make_frames(
            rsi_14=25.0,
            rsi_curvature=0.5,
            macd_hist_slope=0.1,
        )
    )
    assert result["exhaustion_score"] == pytest.approx(1.0)


# ── exhaustion_side tests ─────────────────────────────────────────────────────


def test_exhaustion_side_bull_when_rsi_above_70():
    """rsi>70 with any score → exhaustion_side='bull'."""
    plugin = ExhaustionScorePlugin()
    result = plugin.compute_next(
        make_frames(
            rsi_14=75.0,
            rsi_curvature=-0.5,
            macd_hist_slope=-0.1,
        )
    )
    assert result["exhaustion_side"] == "bull"


def test_exhaustion_side_bear_when_rsi_below_30():
    """rsi<30 with bearish conditions → exhaustion_side='bear'."""
    plugin = ExhaustionScorePlugin()
    result = plugin.compute_next(
        make_frames(
            rsi_14=25.0,
            rsi_curvature=0.5,
            macd_hist_slope=0.1,
        )
    )
    assert result["exhaustion_side"] == "bear"


def test_exhaustion_side_none_when_no_exhaustion():
    """RSI in neutral zone (30-70) → exhaustion_side='none'."""
    plugin = ExhaustionScorePlugin()
    result = plugin.compute_next(
        make_frames(
            rsi_14=55.0,
            rsi_curvature=0.0,
            macd_hist_slope=0.0,
        )
    )
    assert result["exhaustion_side"] == "none"


# ── exhaustion_bars counter tests ─────────────────────────────────────────────


def test_exhaustion_bars_increments_each_consecutive_bar():
    """exhaustion_bars increments on each bar that condition holds."""
    plugin = ExhaustionScorePlugin()
    # bar 1: condition holds → bars=1
    r1 = plugin.compute_next(
        make_frames(
            rsi_14=75.0,
            rsi_curvature=-0.5,
            macd_hist_slope=-0.1,
        )
    )
    assert r1["exhaustion_bars"] >= 1.0
    # bar 2: condition still holds → bars increments
    r2 = plugin.compute_next(
        make_frames(
            rsi_14=76.0,
            rsi_curvature=-0.4,
            macd_hist_slope=-0.05,
        )
    )
    assert r2["exhaustion_bars"] > r1["exhaustion_bars"]


def test_exhaustion_bars_resets_to_zero_when_condition_breaks():
    """exhaustion_bars resets to 0 when exhaustion condition stops holding."""
    plugin = ExhaustionScorePlugin()
    # bar 1: condition holds
    plugin.compute_next(
        make_frames(
            rsi_14=75.0,
            rsi_curvature=-0.5,
            macd_hist_slope=-0.1,
        )
    )
    # bar 2: condition breaks (RSI drops to neutral)
    r2 = plugin.compute_next(
        make_frames(
            rsi_14=55.0,
            rsi_curvature=0.1,
            macd_hist_slope=0.1,
        )
    )
    assert r2["exhaustion_bars"] == pytest.approx(0.0)
