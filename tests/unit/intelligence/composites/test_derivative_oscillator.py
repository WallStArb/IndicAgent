# tests/unit/intelligence/composites/test_derivative_oscillator.py
"""Unit tests for DerivativeOscillatorPlugin (Constance Brown triple-smoothed RSI derivative)."""
from __future__ import annotations

from src.intelligence.composites.derivative_oscillator import DerivativeOscillatorPlugin

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_frames(rsi: float | None) -> dict:
    """Build a minimal frames dict with the given RSI value."""
    if rsi is None:
        return {"features": {}}
    return {"features": {"rsi_14": rsi}}


def feed_bars(plugin: DerivativeOscillatorPlugin, rsi_values: list[float | None]) -> list[dict]:
    """Feed a sequence of RSI bars through the plugin and collect outputs."""
    results = []
    for rsi in rsi_values:
        result = plugin.compute_full(make_frames(rsi))
        results.append(result)
    return results


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_outputs_present():
    """After warmup (~18 bars), plugin emits all 4 output keys."""
    plugin = DerivativeOscillatorPlugin()
    plugin._state = {}
    # Feed 30 bars of synthetic RSI values
    rsi_sequence = [50.0 + i * 0.5 for i in range(30)]
    results = feed_bars(plugin, rsi_sequence)
    # After warmup (EMA5×EMA3 seeding + 9 SMA bars = ~18 bars), outputs should be present
    last = results[-1]
    assert "deriv_osc" in last, f"deriv_osc missing from output: {last}"
    assert "deriv_osc_signal" in last, f"deriv_osc_signal missing from output: {last}"
    assert "deriv_osc_cross_bullish" in last, f"deriv_osc_cross_bullish missing: {last}"
    assert "deriv_osc_cross_bearish" in last, f"deriv_osc_cross_bearish missing: {last}"


def test_missing_rsi():
    """frames with no rsi_14 key → plugin returns {}."""
    plugin = DerivativeOscillatorPlugin()
    plugin._state = {}
    result = plugin.compute_full({"features": {}})
    assert result == {}


def test_non_numeric_rsi():
    """rsi_14 = 'bad' (non-numeric) → plugin returns {}."""
    plugin = DerivativeOscillatorPlugin()
    plugin._state = {}
    result = plugin.compute_full({"features": {"rsi_14": "bad"}})
    assert result == {}


def test_warmup_separation():
    """After 8 bars, state[ema5] is updated but plugin returns {} (sma9 not full)."""
    plugin = DerivativeOscillatorPlugin()
    plugin._state = {}
    rsi_sequence = [50.0] * 8
    results = feed_bars(plugin, rsi_sequence)
    # All 8 outputs should be empty (sma9 buf has 8 entries, need 9)
    for result in results:
        assert result == {}, f"Expected empty output during warmup, got: {result}"
    # But state should have ema5 updated
    assert plugin._state.get("ema5") is not None, "ema5 should be seeded after 8 valid RSI bars"


def test_bullish_cross():
    """Construct RSI sequence that drives ema3 to cross above signal line; assert deriv_osc_cross_bullish=1."""
    plugin = DerivativeOscillatorPlugin()
    plugin._state = {}
    # Phase 1: push RSI down so ema3 < signal (bearish territory)
    low_rsi = [30.0] * 20
    feed_bars(plugin, low_rsi)
    # Phase 2: sharply reverse upward — ema3 should cross above signal
    high_rsi = [80.0] * 20
    results = feed_bars(plugin, high_rsi)
    # At least one bar should have bullish cross
    bullish_fires = [r.get("deriv_osc_cross_bullish", 0) for r in results if r]
    assert 1 in bullish_fires, (
        f"Expected deriv_osc_cross_bullish=1 in {len(results)} bars after RSI reversal, "
        f"but got crosses: {bullish_fires}"
    )


def test_bearish_cross():
    """Mirror of bullish: drive ema3 below signal; assert deriv_osc_cross_bearish=1."""
    plugin = DerivativeOscillatorPlugin()
    plugin._state = {}
    # Phase 1: push RSI high so ema3 > signal (bullish territory)
    high_rsi = [80.0] * 20
    feed_bars(plugin, high_rsi)
    # Phase 2: sharply reverse downward — ema3 should cross below signal
    low_rsi = [20.0] * 20
    results = feed_bars(plugin, low_rsi)
    bearish_fires = [r.get("deriv_osc_cross_bearish", 0) for r in results if r]
    assert 1 in bearish_fires, (
        f"Expected deriv_osc_cross_bearish=1 in {len(results)} bars after RSI reversal, "
        f"but got crosses: {bearish_fires}"
    )


def test_output_types():
    """All 4 outputs are float or int (not None, not str)."""
    plugin = DerivativeOscillatorPlugin()
    plugin._state = {}
    rsi_sequence = [50.0 + i * 0.3 for i in range(30)]
    results = feed_bars(plugin, rsi_sequence)
    last = results[-1]
    assert last, "Expected non-empty output after 30 bars"
    for key in ("deriv_osc", "deriv_osc_signal", "deriv_osc_cross_bullish", "deriv_osc_cross_bearish"):
        assert key in last, f"Missing key: {key}"
        val = last[key]
        assert isinstance(val, (int, float)), f"{key}={val!r} is not int/float"


def test_no_cross_on_stable():
    """Stable RSI sequence — both cross flags remain 0 throughout."""
    plugin = DerivativeOscillatorPlugin()
    plugin._state = {}
    # Warmup with slightly rising RSI (avoid exact flat to ensure signal != 0)
    warmup = [50.0 + i * 0.1 for i in range(20)]
    feed_bars(plugin, warmup)
    # Now stable RSI — no cross should fire
    stable_rsi = [52.0] * 15
    results = feed_bars(plugin, stable_rsi)
    for i, r in enumerate(results):
        if r:  # skip warmup empties
            assert r.get("deriv_osc_cross_bullish", 0) == 0, (
                f"Unexpected bullish cross at stable bar {i}: {r}"
            )
            assert r.get("deriv_osc_cross_bearish", 0) == 0, (
                f"Unexpected bearish cross at stable bar {i}: {r}"
            )
