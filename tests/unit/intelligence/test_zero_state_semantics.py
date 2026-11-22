"""Positive semantics of the zero_is_state columns declared in todo 652.

Each declaration says a 0.0 is a measured state once the column's object exists. The no-object
contract test pins the absent side (NaN); this file pins the measured side on small hand-built
series: the state reads 0.0, a paired series reads non-zero, and the object-absent case reads
None (NaN once stored). Also guards the APR seed that keeps swing_amplitude_expanding from being
a constant 0.0.
"""

from __future__ import annotations

import math
import re
from pathlib import Path

import numpy as np

from src.intelligence.features.feature_factory_config import (
    FEATURE_APR_FIELDS,
    FeatureFactoryConfig,
)
from src.intelligence.features.kernels.smc import _compute_bos_choch
from src.intelligence.features.kernels.vp_sr import (
    _compute_fib_zones,
    _compute_swing_momentum,
    _compute_swing_structure,
)
from tests.unit.intelligence.test_swing_fib_trend_structure_primitives import _make_cfg

_MIGRATION_267 = (
    Path(__file__).resolve().parents[3]
    / "production/migrations/267_swing_fib_trend_structure_primitives.sql"
)


def _arr(values):
    return np.asarray(values, dtype=float)


# --- swing_pattern -------------------------------------------------------------------------


def _pattern(highs, lows):
    cfg = _make_cfg(swing_pivot_window=1, swing_lookback_bars=len(highs))
    return _compute_swing_structure(_arr(highs), _arr(lows), 10.0, 1.0, cfg)["swing_pattern"]


_HIGHS = [10, 12, 10, 14, 10, 10]  # peaks 12 then 14: a higher high


def test_swing_pattern_zero_when_the_last_high_and_low_types_disagree():
    assert _pattern(_HIGHS, [9, 7, 9, 6, 9, 9]) == 0.0  # higher high, lower low
    assert _pattern(_HIGHS, [9, 6, 9, 7, 9, 9]) == 1.0  # higher high, higher low
    assert _pattern([10, 14, 10, 12, 10, 10], [9, 7, 9, 6, 9, 9]) == -1.0
    assert _pattern(_HIGHS, [9, 9, 9, 9, 9, 9]) is None  # no trough: no pattern object


# --- fib_cluster_strength ------------------------------------------------------------------

_SWING = {"swing_high_price": 110.0, "swing_low_price": 100.0}


def test_fib_cluster_strength_zero_when_no_levels_fall_within_the_atr_threshold():
    cfg = _make_cfg()
    assert _compute_fib_zones(105.0, 1.0, _SWING, cfg)["fib_cluster_strength"] == 0.0
    assert _compute_fib_zones(105.0, 10.0, _SWING, cfg)["fib_cluster_strength"] > 0.0
    assert math.isnan(_compute_fib_zones(105.0, 0.0, _SWING, cfg)["fib_cluster_strength"])
    flat = {"swing_high_price": 100.0, "swing_low_price": 100.0}  # no fib object
    assert _compute_fib_zones(105.0, 1.0, flat, cfg)["fib_cluster_strength"] is None


# --- swing_amplitude_expanding and swing_amplitude_intensity -------------------------------


def _momentum(path):
    cfg = _make_cfg(
        swing_momentum_confirm_n=1,
        swing_momentum_max_extremes=4,
        swing_momentum_lookback_bars=len(path),
    )
    p = _arr(path)
    return _compute_swing_momentum(p, p, np.ones(len(p)), cfg)


def test_swing_amplitude_flags_zero_when_the_last_legs_are_not_growing():
    growing = _momentum([100, 103, 99, 106, 96, 110, 92, 100])  # legs 10, 14, 18
    assert growing["swing_amplitude_expanding"] == 1.0
    assert growing["swing_amplitude_intensity"] > 0.0
    shrinking = _momentum([100, 112, 90, 108, 94, 104, 98, 100])  # legs 14, 10, 6
    assert shrinking["swing_amplitude_expanding"] == 0.0
    assert shrinking["swing_amplitude_intensity"] == 0.0
    too_few = _momentum([100, 103, 99, 106, 107])  # two confirmed extremes, four needed
    assert too_few["swing_amplitude_expanding"] is None
    assert too_few["swing_amplitude_intensity"] is None


def test_swing_amplitude_expanding_needs_a_max_extremes_seed_above_three():
    """amps has max_extremes - 1 entries and the flag needs three, so a seed of 3 or less would
    make swing_amplitude_expanding (and the intensity it gates) a constant 0.0."""
    assert FeatureFactoryConfig.swing_momentum_max_extremes >= 4  # dataclass default
    seed = next(
        d for _, k, _, d in FEATURE_APR_FIELDS if k == "feature.swing_momentum.max_extremes"
    )
    assert seed >= 4
    sql_seed = re.search(
        r"\('feature\.swing_momentum\.max_extremes', '(\d+)'", _MIGRATION_267.read_text()
    )
    assert sql_seed is not None and int(sql_seed.group(1)) >= 4


# --- bars_since_last_shift -----------------------------------------------------------------


def _bars_since_shift(path):
    cfg = _make_cfg(smc_bos_choch_lookback=len(path), smc_bos_choch_swing_neighbor=1)
    p = _arr(path)
    return _compute_bos_choch(p, p, p, float(p[-1]), 1.0, cfg)["bars_since_last_shift"]


_ZIGZAG = [100, 105, 100, 104, 99, 103, 102]  # swing highs 105, 104, 103; lows 100, 99, 102


def test_bars_since_last_shift_zero_on_a_break_at_the_current_bar():
    assert _bars_since_shift([*_ZIGZAG, 110]) == 0.0  # close above the last swing high
    assert _bars_since_shift([*_ZIGZAG, 110, 111, 112]) == 2.0  # the same break, two bars old
    assert _bars_since_shift([*_ZIGZAG, 102.5]) is None  # no break in the window
