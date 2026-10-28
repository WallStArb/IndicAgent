"""Research kernels (184-02 B2a, B2c): parity with the stored originals, causality, memory,
placement outside discovery."""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

from src.intelligence.features.contract.causality_probe import (
    CausalityViolation,
    causality_probe,
    memory_check,
)
from src.intelligence.features.contract.registry import (
    Kernel,
    KernelRegistry,
    default_registry,
    discover_kernels,
)
from src.intelligence.features.kernels.price import (
    _high_52w_dist_series_full,
    _price_percentile_series_full,
)
from src.intelligence.features.research_kernels import rolling
from src.intelligence.features.research_kernels.rolling import (
    CONFIG_FREE_KERNELS,
    KERNELS,
    STORED_EQUIVALENTS,
    STORED_WINDOW_FIELD,
    family_of,
    rolling_max_distance_kernel,
    rolling_percentile_kernel,
    rolling_vwap_deviation_kernel,
    window_of,
)

N = 400
ROWS = np.array([50, 120, 250, 399])


def _bars(n: int, seed: int = 7) -> dict[str, np.ndarray]:
    rng = np.random.default_rng(seed)
    close = 100.0 * np.exp(np.cumsum(rng.normal(0.0, 0.01, n)))
    spread = np.abs(rng.normal(0.0, 0.5, n))
    return {
        "close": close,
        "high": close + spread,
        "low": close - spread,
        "volume": rng.integers(0, 5_000, n).astype(float),
    }


INPUTS = _bars(N)
PARITY = _bars(2_000, seed=11)


def _run(kernel: Kernel, inputs, config=None) -> np.ndarray:
    out = kernel.compute({k: inputs[k] for k in kernel.inputs}, config)
    return np.asarray(out[kernel.outputs[0]]).astype(np.float32)


@pytest.mark.parametrize("window", [20, 60, 252])
def test_percentile_parity_bit_equal_after_warmup(window):
    ours = _run(rolling_percentile_kernel(window), PARITY)
    ref = _price_percentile_series_full(PARITY["close"], window).astype(np.float32)
    assert np.array_equal(ours[window - 1 :], ref[window - 1 :])


@pytest.mark.parametrize("window", [20, 60, 252])
def test_high_dist_parity_bit_equal_after_warmup(window):
    ours = _run(rolling_max_distance_kernel(window), PARITY)
    ref = _high_52w_dist_series_full(PARITY["close"], window).astype(np.float32)
    assert np.array_equal(ours[window - 1 :], ref[window - 1 :])


def test_percentile_parity_with_ties():
    close = np.round(PARITY["close"], 0)  # many ties exercise the weak (<=) count
    ours = _run(rolling_percentile_kernel(60), {"close": close})
    ref = _price_percentile_series_full(close, 60).astype(np.float32)
    assert np.array_equal(ours[59:], ref[59:])


@pytest.mark.parametrize(
    "factory",
    [rolling_percentile_kernel, rolling_max_distance_kernel, rolling_vwap_deviation_kernel],
)
def test_pre_warmup_rows_are_nan(factory):
    out = _run(factory(30), INPUTS)
    assert np.isnan(out[:29]).all()
    assert np.isfinite(out[29:]).any()


@pytest.mark.parametrize("window", [5, 20, 60])
def test_vwap_deviation_memory_and_causality(window):
    kernel = rolling_vwap_deviation_kernel(window)
    causality_probe(kernel, INPUTS, None, ROWS)
    assert memory_check(kernel, INPUTS, None, ROWS) == window - 1


def test_vwap_deviation_zero_volume_window_is_nan():
    inputs = dict(INPUTS)
    inputs["volume"] = INPUTS["volume"].copy()
    inputs["volume"][100:120] = 0.0
    inputs["volume"][300] = np.nan
    out = _run(rolling_vwap_deviation_kernel(10), inputs)
    assert np.isnan(out[119])  # rows 110..119 all zero volume
    assert np.isnan(out[300:310]).all()  # every window holding the NaN volume
    assert np.isfinite(out[310])


def test_vwap_deviation_formula():
    w, t = 20, 250
    sl = slice(t - w + 1, t + 1)
    tp = (INPUTS["high"][sl] + INPUTS["low"][sl] + INPUTS["close"][sl]) / 3.0
    vwap = (tp * INPUTS["volume"][sl]).sum() / INPUTS["volume"][sl].sum()
    expected = (INPUTS["close"][t] - vwap) / tp.std()
    out = _run(rolling_vwap_deviation_kernel(w), INPUTS)
    assert out[t] == np.float32(expected)


@pytest.mark.parametrize("kernel", KERNELS, ids=lambda k: k.name)
def test_causality_and_memory_every_exposed_kernel(kernel):
    causality_probe(kernel, INPUTS, None, ROWS)
    assert memory_check(kernel, INPUTS, None, ROWS) == window_of(kernel.name) - 1
    assert kernel.memory_atol == 0.0 and not kernel.path_dependent


@pytest.mark.parametrize("factory", rolling.FACTORIES.values())
def test_guard5_truncation_probe_at_spec_windows(factory):
    for window in (2, 7, 63):
        kernel = factory(window)
        causality_probe(kernel, INPUTS, None, ROWS)
        memory_check(kernel, INPUTS, None, ROWS)
        assert not KernelRegistry.from_kernels((kernel,)).is_path_dependent(kernel.outputs[0])


def test_guard5_acausal_control_fails_the_probe():
    inner = rolling_percentile_kernel(20)

    def ahead(x, config):
        out = inner.compute(x, config)[inner.outputs[0]]
        return {"ahead": np.concatenate([out[1:], [np.nan]])}  # row t reads row t + 1

    control = Kernel(
        name="ahead",
        outputs=("ahead",),
        inputs=("close",),
        memory=lambda c: 20,
        compute=ahead,
        acausal_control=True,
    )
    with pytest.raises(CausalityViolation):
        causality_probe(control, INPUTS, None, ROWS)


def test_research_kernels_are_not_discovered_or_stored():
    stored = set(default_registry().feature_columns())
    for kernel in KERNELS:
        assert not set(kernel.outputs) & stored
    found = discover_kernels(package="src.intelligence.features.research_kernels")
    assert sorted(k.name for k in found.kernels) == sorted(k.name for k in KERNELS)


def test_exposed_windows_differ_from_stored_columns():
    """KERNELS never duplicates a stored column at the APR windows of 2026-10-27; kernel_source
    re-checks against the provenance config per call."""
    stored_windows = {
        "percentile_window_fast": 50,
        "percentile_window_slow": 200,
        "high_52w_window": 252,
    }
    for kernel in KERNELS:
        family = family_of(kernel.name)
        for column in STORED_EQUIVALENTS[family]:
            assert window_of(kernel.name) != stored_windows[STORED_WINDOW_FIELD[column]]


def test_stored_equivalents_name_registry_columns():
    reg = default_registry()
    for columns in STORED_EQUIVALENTS.values():
        for column in columns:
            reg.by_output(column)
            assert column in STORED_WINDOW_FIELD


@pytest.mark.parametrize("bad", [0, 1, -3, 2.5, "20", True, None])
def test_bad_window_raises(bad):
    for factory in rolling.FACTORIES.values():
        with pytest.raises(ValueError):
            factory(bad)


def test_config_free_kernels_ignore_config():
    assert set(CONFIG_FREE_KERNELS) == set(rolling.FACTORIES)
    other = SimpleNamespace(percentile_window_fast=3, high_52w_window=4)
    for kernel in KERNELS:
        assert family_of(kernel.name) in CONFIG_FREE_KERNELS
        assert np.array_equal(
            _run(kernel, INPUTS, None), _run(kernel, INPUTS, other), equal_nan=True
        )
        assert kernel.memory(None) == kernel.memory(other)


def test_family_and_window_parse():
    assert family_of("rk_high_dist_w126") == "rk_high_dist"
    assert window_of("rk_vwap_dev_w20") == 20
    assert family_of("high_52w_dist") is None
    assert family_of("rk_unknown_w5") is None
