# tests/unit/intelligence/composites/test_acceleration_regime.py
"""RED test stubs for AccelerationRegimePlugin (Plan 03 target).

All tests FAIL with ImportError until Plan 03 creates
src/intelligence/composites/acceleration_regime.py.
"""

from __future__ import annotations

import pytest

from src.intelligence.composites.acceleration_regime import AccelerationRegimePlugin


def make_frames(
    rsi_curvature=0.0,
    macd_hist_slope=0.0,
    price_accel=0.0,
    hma_accel=0.0,
) -> dict:
    """Build frames dict for AccelerationRegime tests.

    The plugin derives accel_score via sign-voting over the 4 acceleration
    measures.  Pass controlled values to get deterministic accel_score outcomes.
    """
    features: dict = {
        "rsi_curvature": rsi_curvature,
        "macd_hist_slope": macd_hist_slope,
        "price_accel": price_accel,
        "hma_accel": hma_accel,
    }
    return {"features": features, "prev_features": {}}


# ── regime state tests ────────────────────────────────────────────────────────


def test_accel_regime_building_when_score_above_0_5():
    """accel_score > 0.5 → regime='building'."""
    plugin = AccelerationRegimePlugin()
    # All 4 measures strongly positive → accel_score = 1.0
    result = plugin.compute_next(
        make_frames(
            rsi_curvature=1.0,
            macd_hist_slope=0.5,
            price_accel=0.3,
            hma_accel=0.4,
        )
    )
    assert result["accel_regime"] == "building"


def test_accel_regime_waning_when_score_below_minus_0_3():
    """accel_score < -0.3 → regime='waning'."""
    plugin = AccelerationRegimePlugin()
    # All 4 measures negative → accel_score = -1.0
    result = plugin.compute_next(
        make_frames(
            rsi_curvature=-1.0,
            macd_hist_slope=-0.5,
            price_accel=-0.3,
            hma_accel=-0.4,
        )
    )
    assert result["accel_regime"] == "waning"


def test_accel_regime_neutral_when_score_near_zero():
    """|accel_score| <= 0.3 without prior inflection → regime='neutral'."""
    plugin = AccelerationRegimePlugin()
    # 2 positive, 2 negative → net zero → neutral
    result = plugin.compute_next(
        make_frames(
            rsi_curvature=0.1,
            macd_hist_slope=-0.1,
            price_accel=0.05,
            hma_accel=-0.05,
        )
    )
    assert result["accel_regime"] == "neutral"


def test_accel_regime_peak_fires_once_on_inflection_bar():
    """'peak' fires exactly once on the bar where prev_score > 0.3 AND current <= 0.3."""
    plugin = AccelerationRegimePlugin()
    # bar 1: score > 0.3 (stored in state as prev_accel_score)
    plugin.compute_next(
        make_frames(
            rsi_curvature=1.0,
            macd_hist_slope=0.5,
            price_accel=0.3,
            hma_accel=0.4,
        )
    )
    # bar 2: score crosses down through 0.3 threshold → peak
    result = plugin.compute_next(
        make_frames(
            rsi_curvature=-0.1,
            macd_hist_slope=-0.1,
            price_accel=-0.1,
            hma_accel=-0.1,
        )
    )
    assert result["accel_regime"] == "peak"


def test_accel_regime_trough_fires_once_on_inflection_bar():
    """'trough' fires exactly once on the bar where prev_score < -0.3 AND current >= -0.3."""
    plugin = AccelerationRegimePlugin()
    # bar 1: score < -0.3
    plugin.compute_next(
        make_frames(
            rsi_curvature=-1.0,
            macd_hist_slope=-0.5,
            price_accel=-0.3,
            hma_accel=-0.4,
        )
    )
    # bar 2: score crosses up through -0.3 threshold → trough
    result = plugin.compute_next(
        make_frames(
            rsi_curvature=0.1,
            macd_hist_slope=0.1,
            price_accel=0.1,
            hma_accel=0.1,
        )
    )
    assert result["accel_regime"] == "trough"


# ── accel_score and accel_agreement ──────────────────────────────────────────


def test_accel_score_is_float_in_range():
    """accel_score must be a float in [-1.0, 1.0]."""
    plugin = AccelerationRegimePlugin()
    result = plugin.compute_next(
        make_frames(
            rsi_curvature=0.5,
            macd_hist_slope=0.3,
            price_accel=0.2,
            hma_accel=0.1,
        )
    )
    score = result["accel_score"]
    assert isinstance(score, float)
    assert -1.0 <= score <= 1.0


def test_accel_agreement_is_float_in_range():
    """accel_agreement must be a float in [0.0, 1.0]."""
    plugin = AccelerationRegimePlugin()
    result = plugin.compute_next(
        make_frames(
            rsi_curvature=0.5,
            macd_hist_slope=0.3,
            price_accel=0.2,
            hma_accel=0.1,
        )
    )
    agreement = result["accel_agreement"]
    assert isinstance(agreement, float)
    assert 0.0 <= agreement <= 1.0


def test_accel_agreement_max_when_all_agree():
    """All 4 measures same sign → accel_agreement = 1.0."""
    plugin = AccelerationRegimePlugin()
    result = plugin.compute_next(
        make_frames(
            rsi_curvature=1.0,
            macd_hist_slope=0.5,
            price_accel=0.3,
            hma_accel=0.4,
        )
    )
    assert result["accel_agreement"] == pytest.approx(1.0)


def test_accel_agreement_min_when_split():
    """2 positive / 2 negative → accel_agreement = 0.5."""
    plugin = AccelerationRegimePlugin()
    result = plugin.compute_next(
        make_frames(
            rsi_curvature=1.0,
            macd_hist_slope=-0.5,
            price_accel=0.3,
            hma_accel=-0.4,
        )
    )
    assert result["accel_agreement"] == pytest.approx(0.5)
