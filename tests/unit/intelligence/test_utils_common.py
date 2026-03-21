"""Tests for src/intelligence/utils/common.py.

Verifies that utils/common.py is a faithful promotion of composites/common.py
with identical behavior for all four utility functions.
"""

from __future__ import annotations

from src.intelligence.utils.common import (
    crossover_detect,
    is_num,
    threshold_cross,
    track_bars_ago,
)


# --- import path ---

def test_import_from_utils_common():
    """Import succeeds from the new tier-agnostic path."""
    from src.intelligence.utils.common import (  # noqa: F401
        crossover_detect,
        is_num,
        threshold_cross,
        track_bars_ago,
    )


# --- is_num ---

def test_is_num_int():
    assert is_num(1) is True


def test_is_num_float():
    assert is_num(1.5) is True


def test_is_num_string():
    assert is_num("a") is False


def test_is_num_none():
    assert is_num(None) is False


def test_is_num_list():
    assert is_num([1]) is False


def test_is_num_zero():
    assert is_num(0) is True


# --- crossover_detect ---

def test_crossover_detect_bullish():
    """a crosses above b from below."""
    bullish, bearish = crossover_detect(0.9, 1.1, 1.0, 1.0)
    assert bullish == 1
    assert bearish == 0


def test_crossover_detect_bearish():
    """a crosses below b from above."""
    bullish, bearish = crossover_detect(1.1, 0.9, 1.0, 1.0)
    assert bullish == 0
    assert bearish == 1


def test_crossover_detect_no_cross():
    bullish, bearish = crossover_detect(1.0, 1.0, 0.5, 0.5)
    assert bullish == 0
    assert bearish == 0


def test_crossover_detect_non_numeric():
    """Any None input returns (0, 0) — no crash."""
    assert crossover_detect(None, 1.0, 1.0, 1.0) == (0, 0)


# --- threshold_cross ---

def test_threshold_cross_up():
    assert threshold_cross(0.9, 1.1, 1.0, "up") == 1


def test_threshold_cross_up_not_crossed():
    assert threshold_cross(0.9, 0.95, 1.0, "up") == 0


def test_threshold_cross_down():
    assert threshold_cross(1.1, 0.9, 1.0, "down") == 1


def test_threshold_cross_down_not_crossed():
    assert threshold_cross(1.1, 1.05, 1.0, "down") == 0


def test_threshold_cross_non_numeric():
    assert threshold_cross(None, 1.0, 1.0, "up") == 0


# --- track_bars_ago ---

def test_track_bars_ago_event():
    state: dict = {}
    result = track_bars_ago(state, "k", True)
    assert result == 0.0


def test_track_bars_ago_increments():
    state: dict = {}
    track_bars_ago(state, "k", True)
    track_bars_ago(state, "k", False)
    result = track_bars_ago(state, "k", False)
    assert result == 2.0


def test_track_bars_ago_resets_on_event():
    state: dict = {}
    track_bars_ago(state, "k", False)
    track_bars_ago(state, "k", False)
    result = track_bars_ago(state, "k", True)
    assert result == 0.0


def test_track_bars_ago_capped_at_max_bars():
    state: dict = {"k": 998.0}
    result = track_bars_ago(state, "k", False)
    assert result == 999.0


def test_track_bars_ago_does_not_exceed_max():
    state: dict = {"k": 999.0}
    result = track_bars_ago(state, "k", False)
    assert result == 999.0
