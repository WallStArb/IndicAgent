"""One volume-basis seam through the whole intraday registry (todo 560).

The volume is unchanged; only the basis flips at one row. Every output row that differs from the
single-basis run is masked (NaN, or 1 for a none-mask column), except the basis-safe kernels that
restart at a seam by their own rule. Path-dependent kernels run through a seam, so they and their
downstream are unchanged. A kernel that reads a guarded kernel's output is guarded too: a masked
row must not turn into 0.0 or "no event" downstream. A NULL volume never reaches the registry or
the higher-timeframe series: both raise (todo 564).
"""

from __future__ import annotations

import warnings

import numpy as np
import pytest

from src.intelligence.features.contract.registry import (
    KernelRegistryError,
    compute_kernels,
    default_registry,
)
from tests.unit.intelligence.kernel_parity_reference import synthetic_inputs
from tests.unit.intelligence.test_causality_probe import intraday_kernels, with_derived_inputs

_REGISTRY = default_registry()
_SEAM = 200


def _run(volume: np.ndarray, basis: np.ndarray):
    inputs, config = synthetic_inputs()
    n = len(inputs["ts"])
    rng = np.random.default_rng(11)
    base = {
        **inputs,
        "symbol": np.array(["SPY"] * n, dtype=object),
        "tf": np.array(["5m"] * n, dtype=object),
        **{
            external.name: rng.normal(size=n)
            for external in _REGISTRY.external_inputs
            if external.name.startswith("ext_")
        },
        "volume": volume,
        "volume_basis": basis,
    }
    outputs = [o for k in intraday_kernels(_REGISTRY.kernels) for o in k.outputs]
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return compute_kernels(_REGISTRY, with_derived_inputs(base), config, outputs=outputs)


# a week (above_wk_vwap) and a 479-row rolling POC outlast the 500-row fixture
_LONGER_THAN_THE_FIXTURE = {
    "above_wk_vwap",
    "_poc_price_rolling",
    "poc_rolling_dist_atr",
    "poc_session_rolling_divergence_atr",
}
# amihud_illiq_z restarts its window at a basis change by its own rule (todo 555), so it
# legitimately differs from the single-basis run for a window; so does its product
_RESTARTS_AT_A_SEAM = {"amihud_illiq_z", "illiquidity_momentum_product"}


def test_a_basis_seam_leaves_no_unmasked_difference_anywhere_in_the_registry():
    inputs, _ = synthetic_inputs()
    volume = inputs["volume"].astype(float)
    clean = _run(volume, inputs["volume_basis"])
    basis = inputs["volume_basis"].copy()
    basis[_SEAM:] = 3 - basis[_SEAM:]  # consolidated <-> smart from the seam on
    seamed = _run(volume, basis)
    leaks = {}
    masked_somewhere = False
    for name, want in clean.items():
        if name in _RESTARTS_AT_A_SEAM:
            continue
        want = np.asarray(want, dtype=float)
        got = np.asarray(seamed[name], dtype=float)
        masked = np.isnan(got) | (name.startswith("_") and name.endswith("_is_none") and got == 1.0)
        masked_somewhere |= bool((masked & ~np.isnan(want)).any())
        leak = ~masked & ~np.isclose(got, want, rtol=1e-6, atol=1e-7, equal_nan=True)
        if leak.any():
            leaks[name] = int(leak.sum())
        # masking is bounded: one seam never blanks a quarter of an output
        newly_nan = int((np.isnan(got) & ~np.isnan(want)).sum())
        if newly_nan > len(got) // 4 and name not in _LONGER_THAN_THE_FIXTURE:
            leaks[name] = -newly_nan
    assert not leaks, f"unmasked rows differ from the clean run (negative: over-masked): {leaks}"
    assert masked_somewhere, "the seam masked nothing: the test would pass vacuously"


def test_a_null_volume_bar_raises_in_the_registry():
    inputs, _ = synthetic_inputs()
    volume = inputs["volume"].astype(float).copy()
    volume[_SEAM] = np.nan
    with pytest.raises(KernelRegistryError, match="non-finite volume"):
        _run(volume, inputs["volume_basis"])


def _htf_bars(n: int = 400) -> list[dict]:
    rng = np.random.default_rng(5)
    close = 100 + np.cumsum(rng.normal(0, 1, n))
    return [
        {
            "ts": i,
            "high": float(c + 1),
            "low": float(c - 1),
            "close": float(c),
            "volume": float(rng.uniform(1e3, 1e4)),
        }
        for i, c in enumerate(close)
    ]


def test_the_higher_timeframe_series_raises_on_a_null_volume_bar():
    from src.intelligence.features.kernels.cross_tf import _build_ctf_series

    _, config = synthetic_inputs()
    bars = _htf_bars()
    assert len(_build_ctf_series(bars, config)) == len(bars)
    nulled = [{**b, "volume": float("nan")} if i == 100 else b for i, b in enumerate(bars)]
    with pytest.raises(KernelRegistryError, match="_build_ctf_series.*row 100"):
        _build_ctf_series(nulled, config)
