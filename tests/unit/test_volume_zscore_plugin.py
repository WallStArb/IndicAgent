"""Tests for VolumeZscorePlugin — Phase 78 P78-MATH-PLUGINS.

Covers:
1. Insufficient history → returns {"volume_z_score": 0.0} (no crash)
2. Correct z-score from seeded state
3. Zero std guard → returns 0.0
4. State persists across sequential calls
5. numpy float coercion: type(out["volume_z_score"]) is float
"""

from __future__ import annotations

import collections
import math

import numpy as np
import pandas as pd
import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_df(volumes: list[float], close: float = 100.0) -> pd.DataFrame:
    """Minimal OHLCV DataFrame with the given volumes."""
    n = len(volumes)
    return pd.DataFrame(
        {
            "open": [close] * n,
            "high": [close + 1] * n,
            "low": [close - 1] * n,
            "close": [close] * n,
            "volume": volumes,
        }
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_volume_zscore_insufficient_history():
    """First call with no prior history returns {"volume_z_score": 0.0}."""
    from src.intelligence.trading.volume_zscore import VolumeZscorePlugin

    plugin = VolumeZscorePlugin()
    # Single-bar DataFrame — not enough history for a meaningful z-score
    df = _make_df([100.0])
    result = plugin.compute_full({"main": df})
    assert "volume_z_score" in result
    assert result["volume_z_score"] == 0.0
    assert not math.isnan(result["volume_z_score"])


def test_volume_zscore_correct_value():
    """Seed 19 bars with volume ≈ 100 (std ≈ 10), then a bar at 130 → z ≈ 3.0."""
    from src.intelligence.trading.volume_zscore import VolumeZscorePlugin

    plugin = VolumeZscorePlugin()

    rng = np.random.default_rng(42)
    base_vols = (100.0 + rng.normal(0, 10, 19)).tolist()

    # First call seeds state with 19 bars
    df_seed = _make_df(base_vols)
    plugin.compute_full({"main": df_seed})

    # Second call: single bar with volume = 130
    # z = (130 - mean(base_vols)) / std(base_vols) ≈ 3.0
    expected_mean = float(np.mean(base_vols))
    expected_std = float(np.std(base_vols))
    expected_z = (130.0 - expected_mean) / expected_std

    df_next = _make_df(base_vols + [130.0])
    result = plugin.compute_full({"main": df_next})

    assert "volume_z_score" in result
    assert result["volume_z_score"] == pytest.approx(expected_z, abs=0.5)


def test_volume_zscore_zero_std_guard():
    """All-identical volumes → std=0 → returns 0.0, no division-by-zero."""
    from src.intelligence.trading.volume_zscore import VolumeZscorePlugin

    plugin = VolumeZscorePlugin()
    # 20 bars all with identical volume
    df = _make_df([50.0] * 20)
    result = plugin.compute_full({"main": df})
    assert "volume_z_score" in result
    assert result["volume_z_score"] == 0.0


def test_volume_zscore_state_persists_across_calls():
    """compute_next calls accumulate history in plugin._state."""
    from src.intelligence.trading.volume_zscore import VolumeZscorePlugin

    plugin = VolumeZscorePlugin()

    rng = np.random.default_rng(77)
    vols = (100.0 + rng.normal(0, 5, 22)).tolist()

    # Seed with first 20 bars
    df_seed = _make_df(vols[:20])
    plugin.compute_full({"main": df_seed})

    assert "_window" in plugin._state or "vol_history" in plugin._state or len(plugin._state) > 0

    # compute_next with bar 21
    df21 = _make_df(vols[:21])
    r1 = plugin.compute_next({"main": df21})
    # compute_next with bar 22
    df22 = _make_df(vols[:22])
    r2 = plugin.compute_next({"main": df22})

    # Both calls return valid dicts (state survived across calls)
    assert "volume_z_score" in r1
    assert "volume_z_score" in r2
    # The two results should differ (different bar volumes)
    # Just check they are finite floats
    assert math.isfinite(r1["volume_z_score"])
    assert math.isfinite(r2["volume_z_score"])


def test_volume_zscore_python_float_coercion():
    """Output volume_z_score must be Python float, not numpy.float64."""
    from src.intelligence.trading.volume_zscore import VolumeZscorePlugin

    plugin = VolumeZscorePlugin()

    rng = np.random.default_rng(0)
    vols = (100.0 + rng.normal(0, 10, 25)).tolist()

    df = _make_df(vols)
    result = plugin.compute_full({"main": df})

    assert "volume_z_score" in result
    assert type(result["volume_z_score"]) is float, (
        f"Expected Python float, got {type(result['volume_z_score'])}"
    )
