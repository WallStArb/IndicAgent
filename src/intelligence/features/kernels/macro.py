"""Macro kernels: cross-asset and factor-beta pass-through plus the two macro products (D-25).

The daily cross-asset record (`build_cross_asset_series`) and the per-symbol beta record
(`build_symbol_beta_series`) are built by the caller from daily bars; a kernel receives them as
external inputs on the row grid. The contract that keeps them causal is in each external's
`alignment` string.
"""

from __future__ import annotations

import numpy as np

from src.intelligence.features.registry import ExternalInput, Kernel

_ALIGNMENT = (
    "daily cross-asset record aligned by the caller: available at the 16:00 ET close of its date"
)

MACRO_COLUMNS: tuple[str, ...] = (
    "vix_z",
    "flight_quality",
    "yield_slope_z",
    "tip_tlt_ret_z",
    "hyg_lqd_ret_z",
    "sb_corr_fast",
    "sb_corr_slow",
    "sb_corr_z",
    "equity_beta_z",
    "rate_beta_z",
)

EXTERNAL_INPUTS = tuple(
    ExternalInput(f"ext_{name}", np.dtype(np.float64), _ALIGNMENT) for name in MACRO_COLUMNS
)


def _compute_pass_through(x, config):
    return {name: np.asarray(x[f"ext_{name}"], dtype=np.float64).copy() for name in MACRO_COLUMNS}


def _compute_products(x, config):
    return {
        "yield_slope_momentum_product": x["yield_slope_z"] * x["momentum_z_fast"],
        "vix_reversion_product": x["vix_z"] * x["momentum_reversal_z"],
    }


KERNELS = (
    Kernel(
        name="macro_pass_through",
        outputs=MACRO_COLUMNS,
        inputs=tuple(f"ext_{name}" for name in MACRO_COLUMNS),
        # Pass-through: the path dependence of the builders (flight_quality anchors to the
        # first close, the z-scores accumulate) belongs to the builder kernels 186-15 creates.
        memory=lambda config: 0,
        compute=_compute_pass_through,
    ),
    Kernel(
        name="macro_products",
        outputs=("yield_slope_momentum_product", "vix_reversion_product"),
        inputs=("yield_slope_z", "momentum_z_fast", "vix_z", "momentum_reversal_z"),
        memory=lambda config: 0,
        compute=_compute_products,
    ),
)
