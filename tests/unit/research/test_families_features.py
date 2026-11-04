"""The feature family module (plan 184-05): the centred member and its battery pointer."""

import importlib

import numpy as np
import pytest

from src.intelligence.research import static_sizes
from src.intelligence.research.families import features
from src.intelligence.research.families.common import centred_rank


def test_centred_is_the_signed_centred_rank():
    x = np.random.default_rng(0).standard_normal((30, 40))
    up = features.centred(x, bars_per_session=1, coverage_floor=20)
    down = features.centred(x, bars_per_session=1, coverage_floor=20, sign=-1)
    assert np.array_equal(up, centred_rank(x, coverage_floor=20), equal_nan=True)
    assert np.array_equal(down, -centred_rank(x, coverage_floor=20), equal_nan=True)


@pytest.mark.parametrize("sign", [0, 2, -2, 1.0, True])
def test_sign_is_plus_or_minus_one(sign):
    with pytest.raises(ValueError):
        features.centred(np.zeros((3, 30)), bars_per_session=1, coverage_floor=20, sign=sign)


def test_a_thin_row_is_nan():
    x = np.random.default_rng(1).standard_normal((4, 30))
    x[1, 12:] = np.nan
    out = features.centred(x, bars_per_session=1, coverage_floor=20)
    assert np.isnan(out[1]).all() and np.isfinite(out[0]).all()


def test_the_battery_pointer_resolves_to_a_static_gate():
    assert importlib.import_module(features.NULL_BATTERY).__name__ == features.NULL_BATTERY
    assert isinstance(static_sizes.gate_for(features), static_sizes.StaticGate)
