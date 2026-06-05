"""Tests for src/intelligence/trading/atr_utils.py."""

from __future__ import annotations

from src.intelligence.trading.atr_utils import get_atr, get_atr_with_floor_from_frames


def test_get_atr_valid():
    assert get_atr({"atr_14": 1.5}) == 1.5


def test_get_atr_zero_returns_none():
    assert get_atr({"atr_14": 0.0}) is None


def test_get_atr_negative_returns_none():
    assert get_atr({"atr_14": -0.5}) is None


def test_get_atr_missing_key_returns_none():
    assert get_atr({}) is None


def test_get_atr_none_value_returns_none():
    assert get_atr({"atr_14": None}) is None


def test_get_atr_string_value_returns_none():
    assert get_atr({"atr_14": "bad"}) is None


def test_get_atr_small_positive():
    result = get_atr({"atr_14": 0.001})
    assert result == 0.001


def test_get_atr_int_value():
    result = get_atr({"atr_14": 2})
    assert result == 2.0


def test_get_atr_no_recomputation_present():
    """Ensure the module does not import np or contain high/low ATR calculation logic."""
    import inspect

    import src.intelligence.trading.atr_utils as mod

    source = inspect.getsource(mod)
    assert "np.mean" not in source
    assert "high" not in source.split("def get_atr")[1].split("\n")[0]


def test_get_atr_with_floor_from_frames_valid():
    """Test extraction from frames dict with valid ATR."""
    frames = {
        "symbol": "ES",
        "i1": {"atr_14": 2.0},
    }
    result = get_atr_with_floor_from_frames(frames)
    assert result is not None
    assert isinstance(result, float)


def test_get_atr_with_floor_from_frames_missing_symbol():
    """Test extraction with missing symbol falls back to __symbol__."""
    frames = {
        "__symbol__": "ES",
        "i1": {"atr_14": 2.0},
    }
    result = get_atr_with_floor_from_frames(frames)
    assert result is not None


def test_get_atr_with_floor_from_frames_missing_i1():
    """Test extraction with missing i1 dict returns None."""
    frames = {
        "symbol": "ES",
    }
    result = get_atr_with_floor_from_frames(frames)
    assert result is None


def test_get_atr_with_floor_from_frames_empty_frames():
    """Test extraction with empty frames dict returns None."""
    result = get_atr_with_floor_from_frames({})
    assert result is None
