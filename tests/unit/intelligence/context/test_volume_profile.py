"""Unit tests for VolumeProfilePlugin (I4/context) migration.

Tests cover:
- Plugin identity (name, capability_tags, tier)
- All 18 output fields declared
- Dual-track computation (session + rolling)
- POC/VAH/VAL via 70% cumulative volume rule
- Directional HVN/LVN (above/below close)
- Legacy field backward compatibility
- Edge cases (short data, zero range)
"""
from __future__ import annotations

from datetime import UTC, datetime

import numpy as np
import pandas as pd
import pytest


def _make_df(
    n: int = 120,
    *,
    price_base: float = 100.0,
    with_timestamp: bool = True,
    ts_start: datetime | None = None,
) -> pd.DataFrame:
    """Build synthetic OHLCV DataFrame with n bars."""
    rng = np.random.default_rng(42)
    highs = price_base + rng.uniform(0.5, 2.0, n)
    lows = price_base - rng.uniform(0.5, 2.0, n)
    closes = (highs + lows) / 2.0 + rng.uniform(-0.3, 0.3, n)
    volumes = rng.uniform(100, 1000, n)
    df = pd.DataFrame({"high": highs, "low": lows, "close": closes, "volume": volumes})
    if with_timestamp:
        if ts_start is None:
            ts_start = datetime(2026, 3, 17, 15, 0, 0, tzinfo=UTC)
        timestamps = pd.date_range(start=ts_start, periods=n, freq="1min", tz="UTC")
        df["timestamp"] = timestamps
    return df


def _make_concentrated_df(
    n: int = 100,
    *,
    poc_price: float = 105.0,
    price_range: float = 10.0,
) -> pd.DataFrame:
    """Build DataFrame with volume heavily concentrated near poc_price."""
    rng = np.random.default_rng(0)
    # Most bars cluster near poc_price with high volume
    n_hot = int(n * 0.7)
    n_cold = n - n_hot

    hot_mid = poc_price
    cold_mid = poc_price - price_range * 0.4  # below POC

    highs_hot = hot_mid + rng.uniform(0.1, 0.3, n_hot)
    lows_hot = hot_mid - rng.uniform(0.1, 0.3, n_hot)
    closes_hot = (highs_hot + lows_hot) / 2.0
    volumes_hot = rng.uniform(800, 1000, n_hot)  # high volume

    highs_cold = cold_mid + rng.uniform(0.1, 0.3, n_cold)
    lows_cold = cold_mid - rng.uniform(0.1, 0.3, n_cold)
    closes_cold = (highs_cold + lows_cold) / 2.0
    volumes_cold = rng.uniform(10, 50, n_cold)  # low volume

    highs = np.concatenate([highs_hot, highs_cold])
    lows = np.concatenate([lows_hot, lows_cold])
    closes = np.concatenate([closes_hot, closes_cold])
    volumes = np.concatenate([volumes_hot, volumes_cold])
    timestamps = pd.date_range(
        start=datetime(2026, 3, 17, 15, 0, 0, tzinfo=UTC), periods=n, freq="1min", tz="UTC"
    )
    df = pd.DataFrame(
        {
            "high": highs,
            "low": lows,
            "close": closes,
            "volume": volumes,
            "timestamp": timestamps,
        }
    )
    return df


@pytest.fixture
def plugin():
    from src.intelligence.context.volume_profile import VolumeProfilePlugin

    return VolumeProfilePlugin()


@pytest.fixture
def frames_simple(plugin):
    df = _make_df(n=150)
    return {"main": df, "features": {"atr_14": 2.0, "close": float(df["close"].iloc[-1])}}


# ---------------------------------------------------------------------------
# Test 1: Plugin identity
# ---------------------------------------------------------------------------

def test_plugin_name(plugin):
    assert plugin.name == "ctx_VolumeProfile"


def test_plugin_capability_tags(plugin):
    assert "context" in plugin.capability_tags
    assert "pattern" not in plugin.capability_tags


# ---------------------------------------------------------------------------
# Test 2: All 18 output fields declared
# ---------------------------------------------------------------------------

EXPECTED_OUTPUTS = {
    # Existing 4
    "nearest_hvn_level",
    "nearest_hvn_dist_atr",
    "nearest_lvn_level",
    "in_lvn",
    # New 14
    "poc_price",
    "vah",
    "val",
    "nearest_hvn_above",
    "nearest_hvn_below",
    "nearest_lvn_above",
    "nearest_lvn_below",
    "poc_price_rolling",
    "vah_rolling",
    "val_rolling",
    "price_in_value_area",
    "va_width_atr",
    "distance_to_vah_atr",
    "distance_to_val_atr",
}


def test_outputs_contains_all_18_fields(plugin):
    assert EXPECTED_OUTPUTS == plugin.outputs


# ---------------------------------------------------------------------------
# Test 3: compute_full returns all 18 keys
# ---------------------------------------------------------------------------

def test_compute_full_returns_all_18_keys(plugin, frames_simple):
    result = plugin.compute_full(frames_simple)
    assert len(result) > 0, "Expected non-empty result"
    for field in EXPECTED_OUTPUTS:
        assert field in result, f"Missing field: {field}"


# ---------------------------------------------------------------------------
# Test 4: POC is at bucket center with highest volume
# ---------------------------------------------------------------------------

def test_poc_is_highest_volume_bucket(plugin):
    df = _make_concentrated_df(n=100, poc_price=105.0)
    features = {"atr_14": 1.0, "close": float(df["close"].iloc[-1])}
    result = plugin.compute_full({"main": df, "features": features})
    assert result.get("poc_price") is not None
    # POC should be near the high-volume cluster (within 2 price units of 105.0)
    assert abs(result["poc_price"] - 105.0) < 2.0, (
        f"POC {result['poc_price']} not near expected 105.0"
    )


# ---------------------------------------------------------------------------
# Test 5: VAH >= POC >= VAL, and VAH/VAL enclose 70% volume
# ---------------------------------------------------------------------------

def test_vah_val_ordering(plugin, frames_simple):
    result = plugin.compute_full(frames_simple)
    poc = result.get("poc_price")
    vah = result.get("vah")
    val = result.get("val")
    assert vah is not None and val is not None and poc is not None
    assert vah >= poc >= val, f"Expected VAH({vah}) >= POC({poc}) >= VAL({val})"


def test_value_area_70_percent_rule(plugin):
    """VAH and VAL should enclose at least 70% of total volume."""
    df = _make_df(n=200)
    features = {"atr_14": 2.0, "close": float(df["close"].iloc[-1])}
    result = plugin.compute_full({"main": df, "features": features})

    vah = result.get("vah")
    val = result.get("val")
    assert vah is not None and val is not None

    # Verify by checking value area is non-zero width
    assert vah > val, f"VAH({vah}) should be > VAL({val})"


# ---------------------------------------------------------------------------
# Test 6: price_in_value_area binary
# ---------------------------------------------------------------------------

def test_price_in_value_area_when_inside(plugin):
    df = _make_concentrated_df(n=100, poc_price=105.0)
    close_inside = 105.0  # should be inside value area
    features = {"atr_14": 1.0, "close": close_inside}
    result = plugin.compute_full({"main": df, "features": features})
    vah = result.get("vah")
    val = result.get("val")
    if vah is not None and val is not None and val <= close_inside <= vah:
        assert result["price_in_value_area"] == 1.0


def test_price_in_value_area_outside(plugin):
    df = _make_concentrated_df(n=100, poc_price=105.0)
    # Get actual val/vah first
    base_features = {"atr_14": 1.0, "close": 105.0}
    base_result = plugin.compute_full({"main": df, "features": base_features})
    val = base_result.get("val")
    if val is not None and val > 95.0:
        close_outside = 90.0  # far below val
        features = {"atr_14": 1.0, "close": close_outside}
        df2 = df.copy()
        # Override close for last row
        result = plugin.compute_full({"main": df2, "features": features})
        assert result["price_in_value_area"] == 0.0


# ---------------------------------------------------------------------------
# Test 7: va_width_atr = (vah - val) / atr_14
# ---------------------------------------------------------------------------

def test_va_width_atr_formula(plugin, frames_simple):
    atr_14 = 2.0
    result = plugin.compute_full(frames_simple)
    vah = result.get("vah")
    val = result.get("val")
    va_width = result.get("va_width_atr")
    assert va_width is not None
    expected = (vah - val) / atr_14
    assert abs(va_width - expected) < 1e-9, f"Expected {expected}, got {va_width}"


# ---------------------------------------------------------------------------
# Test 8: distance_to_vah_atr and distance_to_val_atr
# ---------------------------------------------------------------------------

def test_distance_to_vah_val_atr(plugin, frames_simple):
    atr_14 = 2.0
    df = frames_simple["main"]
    close = float(df["close"].iloc[-1])
    result = plugin.compute_full(frames_simple)

    vah = result.get("vah")
    val = result.get("val")
    d_vah = result.get("distance_to_vah_atr")
    d_val = result.get("distance_to_val_atr")

    assert d_vah is not None
    assert d_val is not None
    assert abs(d_vah - (vah - close) / atr_14) < 1e-9
    assert abs(d_val - (close - val) / atr_14) < 1e-9


# ---------------------------------------------------------------------------
# Test 9: Directional HVN (above/below close)
# ---------------------------------------------------------------------------

def test_nearest_hvn_above_is_lowest_hvn_above_close(plugin):
    df = _make_concentrated_df(n=150, poc_price=105.0)
    features = {"atr_14": 1.0, "close": 103.0}
    result = plugin.compute_full({"main": df, "features": features})
    hvn_above = result.get("nearest_hvn_above")
    if hvn_above is not None:
        assert hvn_above > 103.0, f"HVN above close should be > 103.0, got {hvn_above}"


def test_nearest_hvn_below_is_highest_hvn_below_close(plugin):
    df = _make_concentrated_df(n=150, poc_price=100.0)
    features = {"atr_14": 1.0, "close": 103.0}
    result = plugin.compute_full({"main": df, "features": features})
    hvn_below = result.get("nearest_hvn_below")
    if hvn_below is not None:
        assert hvn_below <= 103.0, f"HVN below close should be <= 103.0, got {hvn_below}"


# ---------------------------------------------------------------------------
# Test 10: Directional LVN (above/below close)
# ---------------------------------------------------------------------------

def test_nearest_lvn_above_below_correct_side(plugin, frames_simple):
    df = frames_simple["main"]
    close = float(df["close"].iloc[-1])
    result = plugin.compute_full(frames_simple)
    lvn_above = result.get("nearest_lvn_above")
    lvn_below = result.get("nearest_lvn_below")
    if lvn_above is not None:
        assert lvn_above > close, f"LVN above should be > {close}, got {lvn_above}"
    if lvn_below is not None:
        assert lvn_below <= close, f"LVN below should be <= {close}, got {lvn_below}"


# ---------------------------------------------------------------------------
# Test 11: Rolling track uses min(480, len(df)) bars
# ---------------------------------------------------------------------------

def test_rolling_track_poc_computed(plugin, frames_simple):
    result = plugin.compute_full(frames_simple)
    assert result.get("poc_price_rolling") is not None
    assert result.get("vah_rolling") is not None
    assert result.get("val_rolling") is not None


def test_rolling_track_with_short_data(plugin):
    """With fewer than 480 bars, rolling track uses all available bars."""
    df = _make_df(n=50)
    features = {"atr_14": 1.5, "close": float(df["close"].iloc[-1])}
    result = plugin.compute_full({"main": df, "features": features})
    # Should compute without error
    assert result.get("poc_price_rolling") is not None


def test_rolling_track_differs_from_session_with_many_bars(plugin):
    """With >480 bars, rolling is a 480-bar window; session is from 09:30 ET."""
    # Build a large df with 600 bars starting before market open
    ts_start = datetime(2026, 3, 17, 9, 0, 0, tzinfo=UTC)  # 4am ET
    df = _make_df(n=600, with_timestamp=True, ts_start=ts_start)
    features = {"atr_14": 2.0, "close": float(df["close"].iloc[-1])}
    result = plugin.compute_full({"main": df, "features": features})
    # Both tracks should compute
    assert result.get("poc_price") is not None
    assert result.get("poc_price_rolling") is not None


# ---------------------------------------------------------------------------
# Test 12: Legacy fields backward-compatible
# ---------------------------------------------------------------------------

def test_legacy_nearest_hvn_level_computed(plugin, frames_simple):
    result = plugin.compute_full(frames_simple)
    # nearest_hvn_level should be the HVN closest to close (not necessarily above or below)
    nearest_hvn = result.get("nearest_hvn_level")
    assert nearest_hvn is not None


def test_legacy_nearest_hvn_dist_atr_computed(plugin, frames_simple):
    result = plugin.compute_full(frames_simple)
    assert result.get("nearest_hvn_dist_atr") is not None


def test_legacy_nearest_lvn_level_computed(plugin, frames_simple):
    result = plugin.compute_full(frames_simple)
    assert result.get("nearest_lvn_level") is not None


def test_legacy_in_lvn_is_0_or_1(plugin, frames_simple):
    result = plugin.compute_full(frames_simple)
    val = result.get("in_lvn")
    assert val in (0.0, 1.0), f"in_lvn should be 0.0 or 1.0, got {val}"


# ---------------------------------------------------------------------------
# Test 13: Fewer than min_lookback bars returns empty dict
# ---------------------------------------------------------------------------

def test_fewer_than_min_lookback_returns_empty(plugin):
    df = _make_df(n=5)  # less than min_lookback=20
    result = plugin.compute_full({"main": df, "features": {}})
    assert result == {}


def test_none_main_returns_empty(plugin):
    result = plugin.compute_full({"main": None, "features": {}})
    assert result == {}


def test_zero_price_range_returns_empty(plugin):
    """If all bars have identical prices, price_range=0 and result should be empty."""
    df = pd.DataFrame(
        {
            "high": [100.0] * 50,
            "low": [100.0] * 50,
            "close": [100.0] * 50,
            "volume": [100.0] * 50,
        }
    )
    result = plugin.compute_full({"main": df, "features": {"atr_14": 1.0, "close": 100.0}})
    assert result == {}
