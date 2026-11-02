"""The volume-basis guard's invariant (todo 560), as a property over random basis seams.

For every guarded kernel with finite memory M, an output row the guard leaves unmasked equals the
same kernel run on only its trailing M + 1 bars: the guard changes which rows exist, never what
an existing row means. A row it masks is NaN (a none-mask row is 1). A non-finite volume never
reaches a kernel: compute raises on it (todo 564).
"""

from __future__ import annotations

import numpy as np
import pytest

from src.intelligence.features.contract.registry import (
    KernelRegistryError,
    _guard_volume,
    compute_kernels,
    default_registry,
)
from tests.unit.intelligence import kernel_parity_reference as ref

_REGISTRY = default_registry()
_GUARDED = [
    k.name
    for k in _REGISTRY.kernels
    if "volume" in k.inputs and not k.volume_basis_safe and not k.path_dependent
]
# memory 479 against a 500-row fixture: every row is dirty or warmup, nothing finite to compare
_TOO_LONG_FOR_FIXTURE = {"rolling_poc"}


def _case(seed: int):
    inputs, config = ref.synthetic_inputs()
    n = len(inputs["ts"])
    rng = np.random.default_rng(seed)
    full = {
        **inputs,
        "symbol": np.array(["SPY"] * n, dtype=object),
        "tf": np.array(["5m"] * n, dtype=object),
    }
    basis = np.ones(n, dtype=np.int64)
    for seam in rng.choice(np.arange(30, n - 30), size=2, replace=False):
        basis[seam:] = 3 - basis[seam]  # flips 1 <-> 2 at the seam
    return full, config, basis


@pytest.mark.parametrize("seed", [0, 1, 2])
@pytest.mark.parametrize("name", _GUARDED)
def test_unmasked_rows_equal_the_kernel_on_their_trailing_window(name, seed):
    kernel = _REGISTRY.by_name(name)
    full, config, basis = _case(seed)
    n = len(basis)
    cut = {k: full[k] for k in kernel.inputs if k in full}
    if "_atr_raw_padded" in kernel.inputs:
        pytest.skip("needs an upstream kernel output; covered by the end-to-end checks")
    got = _guard_volume(kernel, cut, basis, config)[0]
    memory = int(kernel.memory(config))
    compared = 0
    for out_name, column in got.items():
        column = np.asarray(column, dtype=float)
        is_mask = out_name.startswith("_") and out_name.endswith("_is_none")
        for t in range(memory, n):
            span = slice(t - memory, t + 1)
            if len(set(basis[span])) != 1:
                # a window across a seam is masked: NaN, or 1.0 for a none-mask row
                assert (column[t] == 1.0) if is_mask else np.isnan(column[t]), (out_name, t)
                continue
            if t % 5:
                continue  # the kernel re-run per row is the cost; every 5th clean row
            window = {
                k: v[span] if getattr(v, "ndim", 0) >= 1 and len(v) == n else v
                for k, v in cut.items()
            }
            want = np.asarray(kernel.compute(window, config)[out_name], dtype=float)[-1]
            assert column[t] == pytest.approx(want, rel=1e-6, abs=1e-8, nan_ok=True), (
                out_name,
                t,
            )
            compared += np.isfinite(want) and not is_mask
    if name not in _TOO_LONG_FOR_FIXTURE:
        assert compared, f"{name}: no clean finite row was compared, the test would pass vacuously"


def test_a_none_mask_column_is_never_nan_at_a_segment_start():
    kernel = _REGISTRY.by_name("swing_momentum")
    full, config, _ = _case(0)
    n = len(full["ts"])
    basis = np.ones(n, dtype=np.int64)
    basis[251:] = 2
    cut = {k: full[k] for k in kernel.inputs if k in full}
    if "_atr_raw_padded" in kernel.inputs:
        pytest.skip("needs an upstream kernel output; covered by the end-to-end checks")
    got = _guard_volume(kernel, cut, basis, config)[0]
    for out_name, column in got.items():
        if out_name.startswith("_") and out_name.endswith("_is_none"):
            assert not np.isnan(np.asarray(column, dtype=float)).any(), out_name


@pytest.mark.parametrize("name", ["vwap_dev_sigma", "ctf_source"])
def test_a_path_dependent_kernel_runs_through_a_seam_unmasked(name):
    kernel = _REGISTRY.by_name(name)
    full, config, basis = _case(0)
    cut = {k: full[k] for k in kernel.inputs if k in full}
    got = _guard_volume(kernel, cut, basis, config)[0]
    whole = kernel.compute(cut, config)
    for out_name, column in got.items():
        np.testing.assert_array_equal(
            np.asarray(column, dtype=float), np.asarray(whole[out_name], dtype=float)
        )


def _bars_ts(n: int) -> np.ndarray:
    """n 15m RTH-ish bars from Monday 2023-01-02 14:30 UTC, 26 bars a day, weekdays only."""
    from datetime import UTC, datetime, timedelta

    out, day = [], datetime(2023, 1, 2, 14, 30, tzinfo=UTC)
    while len(out) < n:
        if day.weekday() < 5:
            out.extend(day + timedelta(minutes=15 * k) for k in range(26))
        day += timedelta(days=1)
    return np.array(out[:n], dtype=object)


def test_session_levels_ignores_volume_so_it_is_declared_volume_basis_safe():
    kernel = _REGISTRY.by_name("session_levels")
    assert kernel.volume_basis_safe
    full, config, _ = _case(0)
    n = len(full["ts"])
    x = {**full, "tf": np.array(["15m"] * n, dtype=object), "ts_dt": _bars_ts(n)}
    x["_atr_raw_padded"] = np.full(n, 1.5)
    cut = {k: x[k] for k in kernel.inputs}
    want = kernel.compute(dict(cut), config)
    rescaled = np.random.default_rng(3).uniform(0.1, 10.0, n) * full["volume"]
    got = kernel.compute({**cut, "volume": rescaled}, config)
    for out_name, column in want.items():
        np.testing.assert_array_equal(
            np.asarray(got[out_name], dtype=float), np.asarray(column, dtype=float)
        )


def test_a_null_volume_reaching_compute_raises():
    inputs, config = ref.synthetic_inputs()
    volume = inputs["volume"].astype(float).copy()
    volume[200] = np.nan
    with pytest.raises(KernelRegistryError, match="non-finite volume.*row 200"):
        compute_kernels(_REGISTRY, {**inputs, "volume": volume}, config, outputs=["rel_volume"])
