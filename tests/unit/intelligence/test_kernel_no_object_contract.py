"""Registry-wide no-object contract (todo 584 item 4c, design D1 rules 2/4/5).

On a flat no-object series (constant prices, volume and every external input NaN)
each stored feature column must be honest about what does not exist:

- outside ``Kernel.zero_is_state``: all-NaN after the kernel's effective-memory
  warmup slice. A fabricated 0.0/0.5/1.0 here asserts a measurement that was never
  made (the object does not exist), the exact silent-wrong-answer class the corpus
  rerun cannot afford.
- inside ``zero_is_state``: 0.0 (or NaN where the window does not exist) is the
  measured state -- an event flag, a count over a fully observed window, or an
  always-measured bar-level column. Asserted finite-or-NaN, never inf, never None.

Exempt kernels whose object always exists (the four calendar kernels and the three
canaries) are skipped: their inputs are the clock, not the market, so a flat price
series is not a no-object series for them.

The flat series is long enough (700 bars) that every kernel has post-warmup rows.
The 2-bar series pins the short-history edge: no window exists yet, so nothing
outside zero_is_state may be finite there either.
"""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime, timedelta

import numpy as np
import pytest

from src.intelligence.features.contract.registry import (
    KernelRegistryError,
    compute_kernels,
    constant_volume_basis,
    default_registry,
)
from src.intelligence.features.kernels.regime import HmmConfig
from tests.unit.intelligence.regime_kernel_fixtures import SMALL_HMM_APR
from tests.unit.intelligence.test_swing_fib_trend_structure_primitives import _make_cfg

# Manifest 4c: exempt because their object always exists (clock inputs).
_EXEMPT_KERNELS = frozenset(
    {
        "calendar_session",
        "calendar_cycles",
        "calendar_events",
        "calendar_above_wk_vwap",
        "canary_noise",
        "canary_constant",
        "canary_acausal_placebo",
        # a level, not an event: ln(dollar volume) of a flat positive-volume series is measured
        "size_proxy",
    }
)

_FLAT_BARS = 700  # deepest effective memory in the registry leaves post-warmup rows


def _no_object_registry():
    return default_registry(), dataclasses.replace(
        _make_cfg(), hmm=HmmConfig.from_values(SMALL_HMM_APR.get)
    )


def _no_object_inputs(registry, n: int) -> dict[str, np.ndarray]:
    base = datetime(2023, 1, 3, 14, 0, tzinfo=UTC)
    ts = np.array(
        [int((base + timedelta(minutes=5 * i)).timestamp() * 1e9) for i in range(n)],
        dtype=np.int64,
    )
    inputs: dict[str, np.ndarray] = {
        "ts": ts,
        "open": np.full(n, 100.0),
        "high": np.full(n, 100.0),
        "low": np.full(n, 100.0),
        "close": np.full(n, 100.0),
        "volume": np.full(n, 1000.0),
        "volume_basis": constant_volume_basis(n),
        "symbol": np.array(["TEST"] * n, dtype=object),
        "tf": np.array(["5m"] * n, dtype=object),
    }
    for ext in registry.external_inputs:
        if ext.name not in inputs:
            inputs[ext.name] = np.full(n, np.nan)
    return inputs


def _stored_columns(registry):
    """(kernel, column) pairs the corpus stores, exempt kernels excluded."""
    return [
        (kernel, column)
        for kernel in registry.kernels
        if kernel.name not in _EXEMPT_KERNELS
        for column in kernel.outputs
        if not column.startswith("_")  # in-memory intermediates are never stored
    ]


@pytest.fixture(scope="module")
def flat_and_short():
    registry, config = _no_object_registry()
    flat = compute_kernels(registry, _no_object_inputs(registry, _FLAT_BARS), config)
    short = compute_kernels(registry, _no_object_inputs(registry, 2), config)
    return registry, config, flat, short


def _warmup_slice(registry, config, kernel, values: np.ndarray) -> np.ndarray:
    try:
        mem = registry.effective_memory_bars(kernel.name, config)
    except KernelRegistryError:
        # path-dependent upstream: no finite memory, every row is stored
        mem = 0
    return values[mem:]


@pytest.mark.parametrize(
    "scenario,n_bars",
    [("flat", _FLAT_BARS), ("two_bar", 2)],
)
def test_no_object_columns_are_nan_or_declared_state(flat_and_short, scenario, n_bars):
    registry, config, flat, short = flat_and_short
    out = flat if scenario == "flat" else short
    owner = {o: k for k in registry.kernels for o in k.outputs}
    # Detection-threshold counts of ATR-gated kernels (186-31 review round 6): the flat
    # fixture's bars hold ATR == 0 on every row, so a detection tolerance of atr_val * mult
    # is unmeasurable and these zero_is_state columns read all-NaN here -- the correct
    # reading, not a broken declaration. Their measured-0.0 contract holds wherever the
    # detection ran and is pinned against the helpers directly in the smc and
    # support-resistance primitive tests.
    atr_gated = {
        (kernel.name, column) for kernel in registry.kernels for column in kernel.atr_gated_state
    }

    offenders_missing = []  # finite outside zero_is_state: a fabricated measurement
    offenders_bad_state = []  # inside zero_is_state but not a measured state
    checked = 0
    for kernel, column in _stored_columns(registry):
        values = np.asarray(out[column], dtype=float)
        stored = _warmup_slice(registry, config, kernel, values)
        checked += 1
        if column in kernel.zero_is_state and (kernel.name, column) not in atr_gated:
            if np.isinf(stored).any():
                offenders_bad_state.append((column, kernel.name, "inf"))
            elif (
                scenario == "flat"
                and len(stored)
                and np.isnan(stored).all()
                # an externally fed pass-through reads this test's all-NaN externals, so its
                # NaN says nothing about the declaration
                and not any(name.startswith("ext_") for name in kernel.inputs)
            ):
                # all-NaN on the long flat series means the declaration does not
                # describe the kernel's real behavior (at two bars NaN is expected:
                # the window does not exist yet)
                offenders_bad_state.append((column, kernel.name, "all-NaN on flat"))
        else:
            if np.isfinite(stored).any():
                offenders_missing.append((column, kernel.name, int(np.isfinite(stored).sum())))

    assert not offenders_missing, (
        f"finite values on the no-object {scenario} series outside zero_is_state "
        f"(fabricated measurements): {offenders_missing}"
    )
    assert not offenders_bad_state, f"bad zero_is_state declarations: {offenders_bad_state}"
    assert checked > 200  # the registry must not silently shrink under this test


def test_zero_is_state_names_are_real_outputs(flat_and_short):
    registry, _, _, _ = flat_and_short
    outputs = set(registry.outputs())
    bad = {
        (k.name, name) for k in registry.kernels for name in k.zero_is_state if name not in outputs
    }
    assert not bad, f"zero_is_state names that are not kernel outputs: {sorted(bad)}"


def test_exempt_kernels_exist(flat_and_short):
    registry, _, _, _ = flat_and_short
    names = {k.name for k in registry.kernels}
    missing = _EXEMPT_KERNELS - names
    assert (
        not missing
    ), f"exempt kernels retired from the registry; prune them from _EXEMPT_KERNELS: {missing}"
