"""Causality probe and memory check (186-08, D-27)."""

from __future__ import annotations

import numpy as np
import pytest

from src.intelligence.features.contract.causality_probe import (
    CausalityViolation,
    MemoryViolation,
    causality_probe,
    memory_check,
    probe_registry,
)
from src.intelligence.features.contract.registry import (
    Kernel,
    KernelRegistry,
    compute_kernels,
    default_registry,
)

N = 400
ROWS = np.array([50, 120, 250, 399])
CFG = object()
_rng = np.random.default_rng(7)
INPUTS = {"close": _rng.normal(100.0, 5.0, N).cumsum().astype(np.float64)}


def _trail(x, w):
    out = np.full(len(x), np.nan)
    for i in range(w - 1, len(x)):
        out[i] = x[i - w + 1 : i + 1].mean()
    return out


def _kernel(fn, memory=0, inputs=("close",)):
    return Kernel(
        name="k",
        outputs=("out",),
        inputs=inputs,
        memory=lambda c: memory,
        compute=lambda x, c: {"out": fn(x["close"])},
    )


def _centered(x):
    out = _trail(x, 3)
    return np.roll(out, -1)  # reads row t+1


def _full_sample_z(x):
    return (x - x.mean()) / x.std()


def test_causal_rolling_mean_passes():
    k = _kernel(lambda x: _trail(x, 5), memory=4)
    causality_probe(k, INPUTS, CFG, ROWS)
    assert memory_check(k, INPUTS, CFG, ROWS) == 4


def test_lookahead_raises():
    with pytest.raises(CausalityViolation, match="'out'"):
        causality_probe(_kernel(_centered), INPUTS, CFG, ROWS)


def test_full_sample_normalization_raises():
    with pytest.raises(CausalityViolation):
        causality_probe(_kernel(_full_sample_z), INPUTS, CFG, ROWS)


def _panel():
    return {"close": np.random.default_rng(3).normal(size=(N, 6))}


def _rank(x):
    return x.argsort(axis=1).argsort(axis=1).astype(np.float64)


def _rank_next_row(x):
    return np.roll(_rank(x), -1, axis=0)


def test_cross_sectional_rank_passes_and_next_row_raises():
    causality_probe(_kernel(_rank), _panel(), CFG, ROWS)
    with pytest.raises(CausalityViolation):
        causality_probe(_kernel(_rank_next_row), _panel(), CFG, ROWS)


def test_truncation_cuts_every_symbol():
    seen = []

    def spy(x):
        seen.append(x.shape)
        return np.zeros(x.shape)

    causality_probe(_kernel(spy), _panel(), CFG, np.array([10]))
    assert (11, 6) in seen


def _ulp_kernel(k):
    def fn(x):
        out = x.astype(np.float32) * np.float32(1.0)
        if len(x) == N:
            out = out + np.float32(k) * np.spacing(out)
        return out

    return _kernel(fn)


def test_ulp_tolerance():
    causality_probe(_ulp_kernel(1), INPUTS, CFG, ROWS, ulp=1)
    with pytest.raises(CausalityViolation):
        causality_probe(_ulp_kernel(1), INPUTS, CFG, ROWS, ulp=0)
    with pytest.raises(CausalityViolation):
        causality_probe(_ulp_kernel(2), INPUTS, CFG, ROWS, ulp=1)


def test_nan_handling():
    causality_probe(_kernel(lambda x: _trail(x, 5)), INPUTS, CFG, np.array([2, 3]))

    def nan_only_full(x):
        out = x.astype(np.float64).copy()
        if len(x) == N:
            out[10] = np.nan
        return out

    with pytest.raises(CausalityViolation):
        causality_probe(_kernel(nan_only_full), INPUTS, CFG, ROWS)


def test_memory_underdeclared_raises():
    w = 8
    ok = _kernel(lambda x: _trail(x, w), memory=w - 1)
    assert memory_check(ok, INPUTS, CFG, ROWS) == w - 1
    bad = _kernel(lambda x: _trail(x, w), memory=w - 2)
    with pytest.raises(MemoryViolation):
        memory_check(bad, INPUTS, CFG, ROWS)


def test_probe_registry_empty_and_chain():
    a = Kernel("a", ("a",), ("close",), lambda c: 4, lambda x, c: {"a": _trail(x["close"], 5)})
    b = Kernel("b", ("b",), ("a",), lambda c: 2, lambda x, c: {"b": _trail(x["a"], 3)})
    reg = KernelRegistry.from_kernels([b, a])
    assert probe_registry(reg, INPUTS, CFG, ROWS) == {"a": "ok", "b": "ok"}


def test_memory_atol_tolerates_last_bit_but_zero_is_exact():
    def jitter(x):
        out = x.astype(np.float64).copy()
        if len(x) == N:
            out = out + 1e-3  # a full-length pass differs from a windowed one in the last bits
        return out

    exact = _kernel(jitter)
    with pytest.raises(MemoryViolation):
        memory_check(exact, INPUTS, CFG, ROWS)
    loose = Kernel(
        "k",
        ("out",),
        ("close",),
        lambda c: 0,
        lambda x, c: {"out": jitter(x["close"])},
        memory_atol=1e-2,
    )
    assert memory_check(loose, INPUTS, CFG, ROWS) == 0


def _inf_kernel(sign):
    def emit(x):
        out = x.astype(np.float64).copy()
        out[-1] = sign * np.inf  # the probed row is the last row of every windowed run
        if len(x) == N:
            out[ROWS] = np.inf
        return out

    return Kernel(
        "k",
        ("out",),
        ("close",),
        lambda c: 3,
        lambda x, c: {"out": emit(x["close"])},
        memory_atol=1e-2,
    )


def test_memory_atol_treats_equal_infinities_as_equal():
    """inf - inf is NaN, which the tolerance comparison read as a violation."""
    assert memory_check(_inf_kernel(+1.0), INPUTS, CFG, ROWS) == 3


def test_memory_atol_still_flags_opposite_infinities():
    with pytest.raises(MemoryViolation):
        memory_check(_inf_kernel(-1.0), INPUTS, CFG, ROWS)


def test_probe_registry_reports_path_dependent_and_acausal_control():
    def anchored(x):  # depends on the first row: no finite memory
        return x - x[0]

    a = Kernel(
        "a",
        ("a",),
        ("close",),
        lambda c: 0,
        lambda x, c: {"a": anchored(x["close"])},
        path_dependent=True,
        path_dependent_reason="anchored at first close",
    )
    ctl = Kernel(
        "ctl",
        ("ctl",),
        ("close",),
        lambda c: 0,
        lambda x, c: {"ctl": _centered(x["close"])},
        acausal_control=True,
    )
    reg = KernelRegistry.from_kernels([a, ctl])
    assert probe_registry(reg, INPUTS, CFG, ROWS) == {
        "a": "path_dependent_skipped_memory",
        "ctl": "acausal_control_detected",
    }


def test_probe_registry_fails_when_acausal_control_is_not_detected():
    blind = Kernel(
        "blind",
        ("blind",),
        ("close",),
        lambda c: 0,
        lambda x, c: {"blind": x["close"]},
        acausal_control=True,
    )
    with pytest.raises(CausalityViolation, match="cannot detect lookahead"):
        probe_registry(KernelRegistry.from_kernels([blind]), INPUTS, CFG, ROWS)


@pytest.fixture(scope="module")
def _registered_case():
    from tests.unit.intelligence.kernel_parity_reference import synthetic_inputs

    inputs, config = synthetic_inputs()
    n = len(inputs["ts"])
    ext_rng = np.random.default_rng(11)
    available = {
        **inputs,
        "symbol": np.array(["SPY"] * n, dtype=object),
        **{
            e.name: ext_rng.normal(size=n)
            for e in default_registry().external_inputs
            if e.name.startswith("ext_")
        },
    }
    available.update(compute_kernels(default_registry(), available, config))
    return available, config


@pytest.mark.parametrize("kernel", default_registry().kernels, ids=lambda k: k.name)
def test_registered_kernels_are_causal(kernel, _registered_case):
    available, config = _registered_case
    rows = np.array([120, 250, 400, 498])
    if kernel.acausal_control:
        with pytest.raises(CausalityViolation):
            causality_probe(kernel, available, config, rows)
        return
    causality_probe(kernel, available, config, rows)
    if kernel.path_dependent:
        assert kernel.path_dependent_reason  # memory_check is skipped: no finite memory exists
        return
    memory_check(kernel, available, config, rows)


def test_probe_registry_computes_each_kernel_once_when_no_row_is_probed():
    calls: list[str] = []

    def counted(name):
        def compute(x, c):
            calls.append(name)
            return {name: np.cumsum(next(iter(x.values())))}

        return compute

    kernels = [
        Kernel(
            "a",
            ("a",),
            ("close",),
            lambda c: 0,
            counted("a"),
            path_dependent=True,
            path_dependent_reason="test",
        ),
        Kernel(
            "b",
            ("b",),
            ("a",),
            lambda c: 0,
            counted("b"),
            path_dependent=True,
            path_dependent_reason="test",
        ),
    ]
    reg = KernelRegistry.from_kernels(kernels)
    inputs = {"close": np.arange(1.0, 9.0)}
    statuses = probe_registry(reg, inputs, CFG, np.array([], dtype=int))
    assert statuses == {"a": "path_dependent_skipped_memory", "b": "path_dependent_skipped_memory"}
    assert calls == ["a", "b"]
