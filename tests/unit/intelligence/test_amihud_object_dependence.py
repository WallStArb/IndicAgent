"""amihud_illiq_z and illiquidity_momentum_product are object dependent (2026-11-26, pilot G2 on MLSS).

The z-score needs a window holding at least ceil(amihud_min_valid_fraction * amihud_zscore_window)
valid observations, and a flat close (a zero return) is no observation. So the first finite row of an
illiquid name sits later than any declared memory: it is data dependent, declared as the kernel's object
(like vol_range_ratio), with the none mask the rebuild writer counts, so pilot G2 does not judge it
and G6 judges the share of rows where the object exists."""

from __future__ import annotations

import math
from types import SimpleNamespace

import numpy as np

from src.intelligence.bars.vendor_kind import VOLUME_BASIS_CONSOLIDATED
from src.intelligence.features.contract.registry import default_registry
from src.intelligence.features.kernels.volume import (
    _compute_amihud,
    _compute_illiquidity_momentum_product,
    none_mask_name,
)

WINDOW, FRACTION = 20, 0.8
CONFIG = SimpleNamespace(amihud_zscore_window=WINDOW, amihud_min_valid_fraction=FRACTION)


def _sparse_then_dense(n: int = 140, sparse_until: int = 70) -> tuple[np.ndarray, np.ndarray]:
    """Closes with about 30 percent flat sessions (no return, no observation) until `sparse_until`,
    then a move every session."""
    rng = np.random.default_rng(7)
    closes = np.empty(n)
    closes[0] = 10.0
    for i in range(1, n):
        flat = i < sparse_until and i % 10 in (2, 5, 8)
        closes[i] = closes[i - 1] if flat else closes[i - 1] * (1.0 + rng.choice([-1, 1]) * 0.01)
    return closes, 1e5 * rng.uniform(0.5, 1.5, n)


def _expected_none(closes: np.ndarray) -> np.ndarray:
    """A per-row oracle: the row has no value unless its own return exists and the last WINDOW bars
    hold at least max(2, ceil(FRACTION * WINDOW)) returns."""
    valid = np.concatenate([[False], closes[1:] != closes[:-1]])
    needed = max(2, math.ceil(FRACTION * WINDOW))
    return np.array(
        [
            not (valid[i] and valid[max(0, i - WINDOW + 1) : i + 1].sum() >= needed)
            for i in range(len(closes))
        ]
    )


def _inputs(closes, volumes):
    return {
        "close": closes,
        "volume": volumes,
        "volume_basis": np.full(len(closes), VOLUME_BASIS_CONSOLIDATED),
    }


def test_the_none_mask_is_true_exactly_where_the_window_or_the_row_has_no_observation():
    closes, volumes = _sparse_then_dense()
    out = _compute_amihud(_inputs(closes, volumes), CONFIG)
    mask = out[none_mask_name("amihud_illiq_z")].astype(bool)
    assert (mask == np.isnan(out["amihud_illiq_z"])).all()
    assert (mask == _expected_none(closes)).all()


def test_a_sparse_stretch_is_the_object_missing_and_a_dense_one_is_not():
    closes, volumes = _sparse_then_dense()
    mask = _compute_amihud(_inputs(closes, volumes), CONFIG)[none_mask_name("amihud_illiq_z")]
    assert mask[WINDOW:70].all()  # about 30 percent flat: fewer than 16 returns in every window
    assert not mask[100:].any()  # a move every session: warm, every row has its value
    first_finite = int(np.argmin(mask))
    assert first_finite > WINDOW  # later than a liquid name's first finite row (bar WINDOW)


def test_the_product_inherits_the_amihud_object_and_only_that():
    closes, volumes = _sparse_then_dense()
    out_amihud = _compute_amihud(_inputs(closes, volumes), CONFIG)
    amihud = out_amihud["amihud_illiq_z"]
    momentum = np.full(len(closes), 0.5)
    gap = np.flatnonzero(~np.isnan(amihud))[:3]
    momentum[gap] = np.nan  # a momentum gap where amihud has a value
    out = _compute_illiquidity_momentum_product(
        {
            "amihud_illiq_z": amihud,
            none_mask_name("amihud_illiq_z"): out_amihud[none_mask_name("amihud_illiq_z")],
            "momentum_z_fast": momentum,
        },
        CONFIG,
    )
    product = out["illiquidity_momentum_product"]
    mask = out[none_mask_name("illiquidity_momentum_product")].astype(bool)
    assert (mask == np.isnan(amihud)).all()  # no amihud value, no product object
    # a NaN momentum is a missing value, never an absent object
    assert np.isnan(product[gap]).all() and not mask[gap].any()


def test_both_columns_are_declared_object_dependent_with_their_none_masks():
    registry = default_registry()
    declared = registry.object_dependent_outputs()
    assert {"amihud_illiq_z", "illiquidity_momentum_product"} <= declared
    outputs = {o for kernel in registry.kernels for o in kernel.outputs}
    assert none_mask_name("amihud_illiq_z") in outputs
    assert none_mask_name("illiquidity_momentum_product") in outputs
