# tests/unit/intelligence/test_i7_exhaustion_wiring.py
"""RED test stubs for I7 exhaustion wiring (Plan 05 target).

These tests FAIL with AssertionError (not ImportError) — the I7 plugins
exist but the exhaustion wire logic is not yet implemented.

Wire contract (from 24-CONTEXT.md / PLAN.md interfaces):
  BOOST  (LiquiditySweepReclaim, LiquidityHunt):
    exhaustion_score > 0.6 AND exhaustion_side matches sweep direction
    → confidence += 0.1, "exhaustion_sweep_boost" in supporting_factors

  GUARD  (MomentumBreakout, TrendFollowing):
    exhaustion_score > 0.7 AND exhaustion_bars >= 3
    → confidence -= 0.15, "exhaustion_guard_penalty" in supporting_factors
    → if confidence < threshold after penalty → _no_signal()
"""
from __future__ import annotations

import numpy as np
import pytest

from tests.unit.intelligence.helpers import make_ohlcv

# ─── helpers ──────────────────────────────────────────────────────────────────


def _sweep_frames(
    exhaustion_score: float = 0.0,
    exhaustion_side: str = "none",
    exhaustion_bars: float = 0.0,
    sweep_type: float = 1.0,      # 1=bullish (SSL swept), -1=bearish (BSL swept)
    direction: int = 1,
    n_bars: int = 100,
) -> dict:
    """Build valid frames for LiquiditySweepReclaimPlugin that produces a signal."""
    close = np.full(n_bars, 5000.0)
    df = make_ohlcv(close)
    features = {
        "sweep_detected": 1.0,
        "sweep_reclaimed": 1.0,
        "sweep_type": float(sweep_type),
        "sweep_level": 4990.0 if direction == 1 else 5010.0,
        "atr_14": 8.0,
        "exhaustion_score": exhaustion_score,
        "exhaustion_side": exhaustion_side,
        "exhaustion_bars": exhaustion_bars,
    }
    return {"main": df, "features": features}


def _hunt_frames(
    exhaustion_score: float = 0.0,
    exhaustion_side: str = "none",
    exhaustion_bars: float = 0.0,
    direction: int = 1,
    n_bars: int = 100,
) -> dict:
    """Build valid frames for LiquidityHuntPlugin that produces a signal."""
    # LiquidityHunt: sweep at named pool + significance >= 0.60
    close = np.full(n_bars, 5000.0)
    atr = 8.0
    swept_level = 4992.0 if direction == 1 else 5008.0
    df = make_ohlcv(close)
    features = {
        "sweep_detected": 1.0,
        "sweep_reclaimed": 1.0,
        "sweep_type": 1.0 if direction == 1 else -1.0,
        "sweep_level": swept_level,
        # LiquidityHunt requires hit_ssl or hit_bsl within atr*0.75
        "ssl_level": swept_level if direction == 1 else 0.0,
        "bsl_level": swept_level if direction == -1 else 0.0,
        "ssl_significance": 0.75 if direction == 1 else 0.0,
        "bsl_significance": 0.75 if direction == -1 else 0.0,
        "atr_14": atr,
        "exhaustion_score": exhaustion_score,
        "exhaustion_side": exhaustion_side,
        "exhaustion_bars": exhaustion_bars,
    }
    return {"main": df, "features": features}


def _breakout_frames(
    exhaustion_score: float = 0.0,
    exhaustion_side: str = "none",
    exhaustion_bars: float = 0.0,
    n_bars: int = 50,
) -> dict:
    """Build valid frames for MomentumBreakoutPlugin that produces a long signal."""
    close = np.full(n_bars, 5015.0)   # above swing_high=5010
    volume = np.full(n_bars, 1000.0)
    volume[-1] = 2500.0               # 2.5x avg → above 1.5x threshold
    df = make_ohlcv(close, volume)
    features = {
        "roc_14": 0.8,
        "swing_high": 5010.0,
        "swing_low": 4990.0,
        "trend_regime": 0.6,
        "atr_14": 8.0,
        "exhaustion_score": exhaustion_score,
        "exhaustion_side": exhaustion_side,
        "exhaustion_bars": exhaustion_bars,
    }
    return {"main": df, "features": features}


def _trend_frames(
    exhaustion_score: float = 0.0,
    exhaustion_side: str = "none",
    exhaustion_bars: float = 0.0,
    n_bars: int = 100,
) -> dict:
    """Build valid frames for TrendFollowingPlugin that produces a long signal."""
    close = np.linspace(5000, 5200, n_bars)
    df = make_ohlcv(close)
    features = {
        "trend_regime": 0.8,
        "trend_confidence": 0.75,
        "swing_pattern": 1.0,
        "trend_strength": 0.7,
        "ctf_score": 0.6,
        "atr_14": 10.0,
        "sma_20": 5180.0,
        "ema_21": 5185.0,
        "exhaustion_score": exhaustion_score,
        "exhaustion_side": exhaustion_side,
        "exhaustion_bars": exhaustion_bars,
    }
    return {"main": df, "features": features}


# ─── LiquiditySweepReclaim boost tests ────────────────────────────────────────


def test_sweep_reclaim_exhaustion_boost_applied_above_threshold():
    """LiquiditySweepReclaim: exhaustion_score=0.65 in sweep direction → boost applied.

    Expected: confidence increases by 0.1 and 'exhaustion_sweep_boost' in supporting.
    This FAILS until Plan 05 adds the boost wire.
    """
    from src.intelligence.trading.liquidity_sweep_reclaim import LiquiditySweepReclaimPlugin

    # baseline without exhaustion
    plugin = LiquiditySweepReclaimPlugin()
    baseline = plugin.compute_full(_sweep_frames(exhaustion_score=0.0, exhaustion_side="none"))
    assert baseline.get("signal_type") != "none", "Test setup failed: need a real signal"

    # with exhaustion boost
    plugin2 = LiquiditySweepReclaimPlugin()
    with_boost = plugin2.compute_full(_sweep_frames(
        exhaustion_score=0.65, exhaustion_side="bull",
    ))
    assert "exhaustion_sweep_boost" in with_boost.get("supporting_factors", [])
    assert with_boost["confidence"] == pytest.approx(baseline["confidence"] + 0.1, abs=0.001)


def test_sweep_reclaim_no_boost_when_score_below_threshold():
    """LiquiditySweepReclaim: exhaustion_score=0.5 (below 0.6) → no boost applied."""
    from src.intelligence.trading.liquidity_sweep_reclaim import LiquiditySweepReclaimPlugin

    plugin = LiquiditySweepReclaimPlugin()
    result = plugin.compute_full(_sweep_frames(
        exhaustion_score=0.5, exhaustion_side="bull",
    ))
    assert "exhaustion_sweep_boost" not in result.get("supporting_factors", [])


# ─── LiquidityHunt boost tests ────────────────────────────────────────────────


def test_liquidity_hunt_exhaustion_boost_applied_above_threshold():
    """LiquidityHunt: exhaustion_score=0.7 in sweep direction → confidence + 0.1, tag in supporting.

    This FAILS until Plan 05 adds the boost wire.
    """
    from src.intelligence.trading.liquidity_hunt import LiquidityHuntPlugin

    # baseline without exhaustion
    plugin = LiquidityHuntPlugin()
    baseline = plugin.compute_full(_hunt_frames(exhaustion_score=0.0, exhaustion_side="none"))
    assert baseline.get("signal_type") != "none", "Test setup failed: need a real signal"

    # with exhaustion boost
    plugin2 = LiquidityHuntPlugin()
    with_boost = plugin2.compute_full(_hunt_frames(
        exhaustion_score=0.7, exhaustion_side="bull",
    ))
    assert "exhaustion_sweep_boost" in with_boost.get("supporting_factors", [])
    assert with_boost["confidence"] == pytest.approx(baseline["confidence"] + 0.1, abs=0.001)


def test_liquidity_hunt_no_boost_when_below_threshold():
    """LiquidityHunt: exhaustion_score=0.55 → no boost."""
    from src.intelligence.trading.liquidity_hunt import LiquidityHuntPlugin

    plugin = LiquidityHuntPlugin()
    result = plugin.compute_full(_hunt_frames(
        exhaustion_score=0.55, exhaustion_side="bull",
    ))
    assert "exhaustion_sweep_boost" not in result.get("supporting_factors", [])


# ─── MomentumBreakout guard tests ────────────────────────────────────────────


def test_momentum_breakout_guard_penalty_applied_when_threshold_met():
    """MomentumBreakout: score=0.8, bars=3 → confidence -= 0.15, tag in supporting.

    This FAILS until Plan 05 adds the guard wire.
    """
    from src.intelligence.trading.momentum_breakout import MomentumBreakoutPlugin

    # baseline without exhaustion
    plugin = MomentumBreakoutPlugin()
    baseline = plugin.compute_full(_breakout_frames(exhaustion_score=0.0, exhaustion_bars=0.0))
    assert baseline.get("signal_type") != "none", "Test setup failed: need a real signal"

    # with guard penalty
    plugin2 = MomentumBreakoutPlugin()
    with_guard = plugin2.compute_full(_breakout_frames(
        exhaustion_score=0.8, exhaustion_side="bull", exhaustion_bars=3.0,
    ))
    assert "exhaustion_guard_penalty" in with_guard.get("supporting_factors", [])
    expected_conf = max(0.0, baseline["confidence"] - 0.15)
    assert with_guard["confidence"] == pytest.approx(expected_conf, abs=0.005)


def test_momentum_breakout_no_penalty_when_bars_below_threshold():
    """MomentumBreakout: score=0.8 but exhaustion_bars=2 → no penalty (bars threshold not met)."""
    from src.intelligence.trading.momentum_breakout import MomentumBreakoutPlugin

    plugin = MomentumBreakoutPlugin()
    result = plugin.compute_full(_breakout_frames(
        exhaustion_score=0.8, exhaustion_side="bull", exhaustion_bars=2.0,
    ))
    assert "exhaustion_guard_penalty" not in result.get("supporting_factors", [])


def test_momentum_breakout_no_penalty_when_score_below_threshold():
    """MomentumBreakout: exhaustion_bars=3 but score=0.6 (below 0.7) → no penalty."""
    from src.intelligence.trading.momentum_breakout import MomentumBreakoutPlugin

    plugin = MomentumBreakoutPlugin()
    result = plugin.compute_full(_breakout_frames(
        exhaustion_score=0.6, exhaustion_side="bull", exhaustion_bars=3.0,
    ))
    assert "exhaustion_guard_penalty" not in result.get("supporting_factors", [])


# ─── TrendFollowing guard tests ───────────────────────────────────────────────


def test_trend_following_guard_penalty_applied_when_threshold_met():
    """TrendFollowing: score=0.75, bars=4 → confidence -= 0.15, tag in supporting.

    This FAILS until Plan 05 adds the guard wire.
    """
    from src.intelligence.trading.trend_following import TrendFollowingPlugin

    # baseline without exhaustion
    plugin = TrendFollowingPlugin()
    baseline = plugin.compute_full(_trend_frames(exhaustion_score=0.0, exhaustion_bars=0.0))
    assert baseline.get("signal_type") != "none", "Test setup failed: need a real signal"

    # with guard penalty
    plugin2 = TrendFollowingPlugin()
    with_guard = plugin2.compute_full(_trend_frames(
        exhaustion_score=0.75, exhaustion_side="bull", exhaustion_bars=4.0,
    ))
    assert "exhaustion_guard_penalty" in with_guard.get("supporting_factors", [])


def test_trend_following_guard_suppresses_signal_when_confidence_drops_too_low():
    """TrendFollowing: guard penalty causes confidence to drop below threshold → _no_signal().

    Use a marginal-confidence setup so penalty pushes it below the guard threshold.
    This FAILS until Plan 05 adds the guard wire.
    """
    from src.intelligence.trading.trend_following import TrendFollowingPlugin

    close = np.linspace(5000, 5060, 100)  # weak trend
    df = make_ohlcv(close)
    # Marginal confidence inputs
    features = {
        "trend_regime": 0.55,
        "trend_confidence": 0.45,
        "swing_pattern": 0.5,
        "trend_strength": 0.3,
        "ctf_score": 0.2,
        "atr_14": 10.0,
        "exhaustion_score": 0.8,
        "exhaustion_side": "bull",
        "exhaustion_bars": 5.0,
    }
    plugin = TrendFollowingPlugin()
    result = plugin.compute_full({"main": df, "features": features})
    # After penalty, low-confidence signal should be suppressed
    assert result.get("signal_type") == "none" or result.get("direction") == 0
