"""The G4 drift measurement (todo 584): per float output, the largest windowed-versus-full
difference in float32 ulps, recorded without raising."""

from __future__ import annotations

import numpy as np

from src.intelligence.features.contract.causality_probe import (
    STATUS_MEMORY_VIOLATION_MEASURED,
    STATUS_OK,
    MemoryViolation,
    measure_memory_drift,
    memory_check,
    probe_registry,
)
from src.intelligence.features.contract.registry import KernelRegistry
from src.intelligence.features.kernels._primitives import _k

ROWS = np.array([40, 80, 120])


def _inputs(n=200):
    rng = np.random.default_rng(3)
    return {"close": (100.0 + np.cumsum(rng.normal(0, 1, n))).astype(np.float64)}


def _rolling_mean(window):
    def compute(x, config):
        c = np.asarray(x["close"], dtype=float)
        out = np.array([c[max(0, i - window + 1) : i + 1].mean() for i in range(len(c))])
        return {"s": out.astype(np.float32)}

    return compute


def _kernel(name, memory):
    return _k(name, ["s"], ["close"], lambda config, m=memory: m, _rolling_mean(5))


def test_a_correctly_declared_memory_has_zero_drift():
    kernel = _kernel("exact", 4)
    full = {"s": _rolling_mean(5)(_inputs(), None)["s"]}
    stats = measure_memory_drift(kernel, _inputs(), None, ROWS, full=full)
    assert stats["s"]["max_ulp"] == 0.0 and stats["s"]["n_diff"] == 0.0


def test_an_under_declared_memory_is_measured_not_raised():
    inputs = _inputs()
    kernel = _kernel("short", 1)
    full = {"s": _rolling_mean(5)(inputs, None)["s"]}
    stats = measure_memory_drift(kernel, inputs, None, ROWS, full=full)
    assert stats["s"]["max_ulp"] > 0.0 and stats["s"]["max_rel"] > 0.0


def test_probe_registry_records_a_violation_only_in_drift_mode():
    inputs = _inputs()
    registry = KernelRegistry.from_kernels([_kernel("short", 1)], ())
    try:
        probe_registry(registry, inputs, None, ROWS)
    except MemoryViolation:
        pass
    else:
        raise AssertionError("the default mode must still raise")
    drift: dict = {}
    statuses = probe_registry(registry, inputs, None, ROWS, drift=drift)
    assert statuses == {"short": STATUS_MEMORY_VIOLATION_MEASURED}
    assert drift["short"]["s"]["max_ulp"] > 0.0
    good = KernelRegistry.from_kernels([_kernel("exact", 4)], ())
    assert probe_registry(good, inputs, None, ROWS, drift={}) == {"exact": STATUS_OK}
    assert (
        memory_check(
            _kernel("exact", 4), inputs, None, ROWS, full={"s": _rolling_mean(5)(inputs, None)["s"]}
        )
        == 4
    )
