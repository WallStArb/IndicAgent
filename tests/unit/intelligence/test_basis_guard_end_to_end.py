"""One dropped volume bar through the whole intraday registry (todo 560).

Every output row that differs from the clean run is masked (NaN, or 1 for a none-mask column),
except the outputs of the path-dependent kernels that have no reset anchor (`vwap_dev_sigma`,
`ctf_source`) and the kernels downstream of them: a dropped bar masks only its own row there and
the residual error is the accepted tolerance recorded in todo 560. A kernel that reads a guarded
kernel's output is guarded too: a masked row must not turn into 0.0 or "no event" downstream.
"""

from __future__ import annotations

import warnings

import numpy as np

from src.intelligence.features.contract.registry import compute_kernels, default_registry
from tests.unit.intelligence.kernel_parity_reference import synthetic_inputs
from tests.unit.intelligence.test_causality_probe import intraday_kernels, with_derived_inputs

_REGISTRY = default_registry()
_DROP = 200


def _run(volume: np.ndarray, basis: np.ndarray):
    inputs, config = synthetic_inputs()
    n = len(inputs["ts"])
    rng = np.random.default_rng(11)
    base = {
        **inputs,
        "symbol": np.array(["SPY"] * n, dtype=object),
        "tf": np.array(["5m"] * n, dtype=object),
        **{
            e.name: rng.normal(size=n)
            for e in _REGISTRY.external_inputs
            if e.name.startswith("ext_")
        },
        "volume": volume,
        "volume_basis": basis,
    }
    outputs = [o for k in intraday_kernels(_REGISTRY.kernels) for o in k.outputs]
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return (
            compute_kernels(_REGISTRY, with_derived_inputs(base), config, outputs=outputs),
            inputs,
        )


# a week (above_wk_vwap) and a 479-row rolling POC outlast the 500-row fixture
_LONGER_THAN_THE_FIXTURE = {
    "above_wk_vwap",
    "_poc_price_rolling",
    "poc_rolling_dist_atr",
    "poc_session_rolling_divergence_atr",
}


def _accepted_unmasked() -> set[str]:
    """Outputs of the no-reset path-dependent kernels and of everything downstream of them."""
    roots = {"vwap_dev_sigma", "ctf_source"}
    names = set(roots)
    for kernel in _REGISTRY.kernels:
        if {up.name for up in _REGISTRY._upstream(kernel)} & roots:
            names.add(kernel.name)
    # amihud_illiq_z drops the missing bar from its z-score window by its own valid-fraction rule
    # (todo 555), so it legitimately differs from the clean run for a window; so does its product
    outputs = {o for k in _REGISTRY.kernels if k.name in names for o in k.outputs}
    return outputs | {"amihud_illiq_z", "illiquidity_momentum_product"}


def test_a_dropped_bar_leaves_no_unmasked_difference_anywhere_in_the_registry():
    inputs, _ = synthetic_inputs()
    clean, _ = _run(inputs["volume"].astype(float), inputs["volume_basis"])
    volume = inputs["volume"].astype(float).copy()
    volume[_DROP] = np.nan
    basis = inputs["volume_basis"].copy()
    basis[_DROP] = 0
    dirty, _ = _run(volume, basis)
    accepted = _accepted_unmasked()
    leaks = {}
    for name, want in clean.items():
        if name in accepted:
            continue
        want = np.asarray(want, dtype=float)
        got = np.asarray(dirty[name], dtype=float)
        masked = np.isnan(got) | (name.startswith("_") and name.endswith("_is_none") and got == 1.0)
        leak = ~masked & ~np.isclose(got, want, rtol=1e-6, atol=1e-7, equal_nan=True)
        if leak.any():
            leaks[name] = int(leak.sum())
        # masking is bounded: one dropped bar never blanks a quarter of an output
        newly_nan = int((np.isnan(got) & ~np.isnan(want)).sum())
        if newly_nan > len(got) // 4 and name not in _LONGER_THAN_THE_FIXTURE:
            leaks[name] = -newly_nan
    assert not leaks, f"unmasked rows differ from the clean run (negative: over-masked): {leaks}"


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


def test_the_higher_timeframe_series_does_not_collapse_to_neutral_after_a_null_volume_bar():
    from src.intelligence.features.kernels.cross_tf import _build_ctf_series

    _, config = synthetic_inputs()
    bars = _htf_bars()
    clean = _build_ctf_series(bars, config)
    # a NULL volume at row 100 was a silent 0.0 on every later row (cumsum of NaN)
    nulled = [{**b, "volume": float("nan")} if i == 100 else b for i, b in enumerate(bars)]
    got = _build_ctf_series(nulled, config)
    align = np.array([r.ctf_vwap_align for r in got.values()])
    want = np.array([r.ctf_vwap_align for r in clean.values()])
    assert np.isnan(align[100]) and not np.isnan(np.delete(align, 100)).any()  # 1 of 101 bars
    assert (align[101:] == want[101:]).mean() > 0.9  # not a run of 0.0
    early = [{**b, "volume": float("nan")} if i == 2 else b for i, b in enumerate(bars)]
    assert np.isnan(
        [r.ctf_vwap_align for r in _build_ctf_series(early, config).values()][2:19]
    ).all()
