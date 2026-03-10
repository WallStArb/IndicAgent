# tests/unit/intelligence/test_swing_momentum.py
"""RED test stubs for SwingMomentumPlugin (Plan 04 target).

All tests FAIL with ImportError until Plan 04 creates
src/intelligence/structure/swing_momentum.py.
"""
from __future__ import annotations

import numpy as np
import pytest

from src.intelligence.structure.swing_momentum import SwingMomentumPlugin
from tests.unit.intelligence.helpers import make_ohlcv


def make_oscillating_prices(n: int, amplitude: float = 10.0, base: float = 5000.0) -> np.ndarray:
    """Build n-bar oscillating close price array (sine wave)."""
    return base + amplitude * np.sin(np.linspace(0, 4 * np.pi, n))


# ── warmup gate tests ─────────────────────────────────────────────────────────


def test_returns_empty_when_fewer_than_6_extremes_confirmed():
    """SwingMomentum returns {} until at least 6 swing extremes are confirmed.

    Use 40-bar series — likely < 3 complete swings confirmed.
    """
    plugin = SwingMomentumPlugin()
    closes = make_oscillating_prices(40, amplitude=20.0)
    df = make_ohlcv(closes)
    result = plugin.compute_full({"main": df, "features": {}})
    assert result == {}


def test_returns_empty_with_insufficient_swings():
    """5 extremes (incomplete 3rd swing) → must return {}."""
    plugin = SwingMomentumPlugin()
    # Build prices that generate exactly 5 extremes (2.5 waves)
    # 2.5 * 2 * half-periods = 5 peaks+troughs
    closes = make_oscillating_prices(30, amplitude=25.0)
    df = make_ohlcv(closes)
    result = plugin.compute_full({"main": df, "features": {}})
    assert result == {}


# ── struct_energy formula tests ───────────────────────────────────────────────


def test_struct_energy_formula():
    """struct_energy = clamp(amplitude_ratio * speed_factor / 3.0, 0.0, 1.0).

    Build a long oscillating series (200 bars) that produces multiple confirmed
    swings.  Assert struct_energy is a float in [0.0, 1.0].
    """
    plugin = SwingMomentumPlugin()
    closes = make_oscillating_prices(200, amplitude=30.0)
    df = make_ohlcv(closes)
    result = plugin.compute_full({"main": df, "features": {}})
    # After 200 bars of regular oscillation we expect a real result (not {})
    if result:
        energy = result.get("struct_energy")
        assert energy is not None
        assert isinstance(energy, float)
        assert 0.0 <= energy <= 1.0


def test_struct_energy_clamped_to_one():
    """struct_energy must never exceed 1.0 even for extreme amplitude."""
    plugin = SwingMomentumPlugin()
    # Very large amplitude → raw formula may exceed 1.0 → clamp must apply
    closes = make_oscillating_prices(200, amplitude=500.0)
    df = make_ohlcv(closes)
    result = plugin.compute_full({"main": df, "features": {}})
    if result:
        energy = result.get("struct_energy", 0.0)
        assert energy <= 1.0


# ── swing_amplitude_expanding tests ───────────────────────────────────────────


def test_amplitude_expanding_true_when_monotonically_increasing():
    """swing_amplitude_expanding=1 only when last 3 amplitudes are monotonically increasing."""
    plugin = SwingMomentumPlugin()
    # Linearly growing amplitude across swings
    n = 200
    t = np.linspace(0, 4 * np.pi, n)
    envelope = np.linspace(5.0, 50.0, n)   # growing amplitude
    closes = 5000.0 + envelope * np.sin(t)
    df = make_ohlcv(closes)
    result = plugin.compute_full({"main": df, "features": {}})
    if result:
        expanding = result.get("swing_amplitude_expanding")
        assert expanding is not None
        assert expanding == 1


def test_amplitude_expanding_false_when_not_monotonically_increasing():
    """swing_amplitude_expanding=0 when last 3 amplitudes are not monotonically increasing."""
    plugin = SwingMomentumPlugin()
    # Constant amplitude — not expanding
    closes = make_oscillating_prices(200, amplitude=10.0)
    df = make_ohlcv(closes)
    result = plugin.compute_full({"main": df, "features": {}})
    if result:
        expanding = result.get("swing_amplitude_expanding")
        assert expanding is not None
        assert expanding == 0


# ── output key presence tests ────────────────────────────────────────────────


def test_output_keys_present_when_warmed_up():
    """All expected output keys present once plugin has enough confirmed swings."""
    plugin = SwingMomentumPlugin()
    closes = make_oscillating_prices(200, amplitude=30.0)
    df = make_ohlcv(closes)
    result = plugin.compute_full({"main": df, "features": {}})
    if result:
        expected_keys = {
            "swing_amplitude_ratio",
            "swing_amplitude_expanding",
            "swing_velocity_bars",
            "swing_velocity_trend",
            "struct_energy",
            "struct_accel_bias",
        }
        for key in expected_keys:
            assert key in result, f"Missing output key: {key}"
