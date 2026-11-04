"""An invalid ATR changes only the outputs that divide by ATR (todo 584 6d).

bos_choch, fair_value_gap and order_blocks used to return their whole fallback on an invalid ATR,
which also wiped outputs that never touch it (directions, counts, strengths, flags). With a
valid ATR (1.0) and an invalid one (0.0) on the same bars, every other output must be equal.
"""

from __future__ import annotations

import numpy as np
import pytest

from src.intelligence.features.kernels.smc import (
    _compute_bos_choch,
    _compute_fvg,
    _compute_order_blocks,
)
from tests.unit.intelligence import kernel_parity_reference as ref

CONFIG = ref.build_config(ref.load_manifest()["synthetic_config"])


def _bars(n=400, seed=5):
    rng = np.random.default_rng(seed)
    close = 100.0 * np.cumprod(1.0 + rng.normal(0.0, 0.01, n))
    open_ = np.concatenate(([close[0]], close[:-1]))
    spread = np.abs(rng.normal(0.0, 0.004, n)) * close
    high = np.maximum(open_, close) + spread
    low = np.minimum(open_, close) - spread
    volume = rng.uniform(1e5, 2e5, n)
    return open_, high, low, close, volume


ATR_OUTPUTS = {
    "bos_choch": {"bos_strength", "choch_strength"},
    "fair_value_gap": {"fvg_dist_atr", "fvg_size_atr"},
    "order_blocks": {"ob_bull_dist_atr", "ob_bear_dist_atr", "breaker_dist_atr"},
}


def _call(name, atr):
    o, h, lo, c, v = _bars()
    if name == "bos_choch":
        return _compute_bos_choch(h, lo, c, float(c[-1]), atr, CONFIG)
    if name == "fair_value_gap":
        return _compute_fvg(h, lo, c, float(c[-1]), atr, CONFIG)
    return _compute_order_blocks(o, h, lo, c, v, float(c[-1]), atr, CONFIG)


@pytest.mark.parametrize("name", sorted(ATR_OUTPUTS))
def test_invalid_atr_changes_only_the_atr_outputs(name):
    valid, invalid = _call(name, 1.0), _call(name, 0.0)
    assert set(valid) == set(invalid)
    for key in valid:
        if key in ATR_OUTPUTS[name]:
            assert invalid[key] is None
        else:
            assert invalid[key] == valid[key], key


@pytest.mark.parametrize("name", sorted(ATR_OUTPUTS))
def test_the_fixture_exercises_the_non_atr_outputs(name):
    """Guard against a vacuous comparison: the valid-ATR result holds a non-neutral value."""
    valid = _call(name, 1.0)
    others = {k: v for k, v in valid.items() if k not in ATR_OUTPUTS[name]}
    assert any(v not in (0.0, None) for v in others.values()), others
