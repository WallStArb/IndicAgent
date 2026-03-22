"""Tests for src/intelligence/trading/plugin_utils.py."""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.intelligence.trading.plugin_utils import (
    default_compute_next,
    extract_ohlcv,
    no_signal,
    signal_type_for_direction,
)

# --- no_signal ---

def test_no_signal_returns_dict():
    result = no_signal()
    assert isinstance(result, dict)


def test_no_signal_signal_type():
    assert no_signal()["signal_type"] == "none"


def test_no_signal_direction():
    assert no_signal()["direction"] == 0


def test_no_signal_confidence():
    assert no_signal()["confidence"] == 0.0


def test_no_signal_new_dict_each_call():
    a = no_signal()
    b = no_signal()
    a["extra"] = 1
    assert "extra" not in b


# --- extract_ohlcv ---

def _make_frames(n: int) -> dict:
    df = pd.DataFrame(
        {
            "open": np.ones(n),
            "high": np.ones(n) * 2,
            "low": np.zeros(n),
            "close": np.ones(n) * 1.5,
        }
    )
    return {"main": df}


def test_extract_ohlcv_none_when_main_missing():
    result = extract_ohlcv({}, 5)
    assert result is None


def test_extract_ohlcv_none_when_main_is_none():
    result = extract_ohlcv({"main": None}, 5)
    assert result is None


def test_extract_ohlcv_none_when_too_few_bars():
    frames = _make_frames(4)
    result = extract_ohlcv(frames, 5)
    assert result is None


def test_extract_ohlcv_returns_tuple_on_exact_min():
    frames = _make_frames(5)
    result = extract_ohlcv(frames, 5)
    assert result is not None
    assert len(result) == 4


def test_extract_ohlcv_returns_tuple_on_more_than_min():
    frames = _make_frames(20)
    result = extract_ohlcv(frames, 10)
    assert result is not None
    assert len(result) == 4


def test_extract_ohlcv_returns_numpy_arrays():
    frames = _make_frames(10)
    o, h, low, c = extract_ohlcv(frames, 5)
    for arr in (o, h, low, c):
        assert isinstance(arr, np.ndarray)


def test_extract_ohlcv_values_correct():
    frames = _make_frames(5)
    o, h, low, c = extract_ohlcv(frames, 5)
    np.testing.assert_array_equal(o, np.ones(5))
    np.testing.assert_array_equal(h, np.ones(5) * 2)
    np.testing.assert_array_equal(low, np.zeros(5))
    np.testing.assert_array_equal(c, np.ones(5) * 1.5)


# --- default_compute_next ---

class _FakePlugin:
    def compute_full(self, windows):
        return {"called_with": windows}


def test_default_compute_next_delegates():
    plugin = _FakePlugin()
    windows = {"foo": "bar"}
    result = default_compute_next(plugin, windows)
    assert result == {"called_with": windows}


# --- signal_type_for_direction ---

def test_signal_type_for_direction_long():
    assert signal_type_for_direction("trend", 1) == "trend_long"


def test_signal_type_for_direction_short():
    assert signal_type_for_direction("trend", -1) == "trend_short"


def test_signal_type_for_direction_other_prefix():
    assert signal_type_for_direction("momentum", 1) == "momentum_long"


def test_signal_type_for_direction_short_prefix():
    assert signal_type_for_direction("fvg_fill", -1) == "fvg_fill_short"
