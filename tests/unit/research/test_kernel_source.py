"""kernel_source (184-02 B2b, B2c): present-row compute, warmup and gap masks, refusals."""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

from src.intelligence.features.contract.registry import (
    Kernel,
    KernelRegistry,
    feature_memory_bars,
)
from src.intelligence.features.research_kernels.rolling import (
    rolling_percentile_kernel,
    rolling_vwap_deviation_kernel,
)
from src.intelligence.research import kernel_source as ks
from src.intelligence.research.kernel_source import (
    KernelSourceRefused,
    kernel_member_memory_bars,
    kernel_registry,
    kernel_source,
)
from src.intelligence.research.panel import Panel

N, M = 300, 3
# The stored windows as a provenance config carries them (APR values at 2026-10-27).
CONFIG = SimpleNamespace(percentile_window_fast=50, percentile_window_slow=200, high_52w_window=252)


def _panel(n: int = N, m: int = M, seed: int = 3) -> tuple[Panel, np.ndarray, np.ndarray]:
    rng = np.random.default_rng(seed)
    close = 100.0 * np.exp(np.cumsum(rng.normal(0.0, 0.01, (n, m)), axis=0))
    spread = np.abs(rng.normal(0.0, 0.4, (n, m)))
    panel = Panel(
        tf="1d",
        symbols=tuple(f"s{j}" for j in range(m)),
        timestamps=np.datetime64("2020-01-01") + np.arange(n).astype("timedelta64[D]"),
        bars_per_session=1,
        valid=np.ones(n, dtype=bool),
        open=close * 0.999,
        close=close,
        volume=rng.integers(1, 5_000, (n, m)).astype(float),
    )
    return panel, close + spread, close - spread


def _with_gaps(panel: Panel, j: int, rows) -> Panel:
    close = panel.close.copy()
    close[list(rows), j] = np.nan
    return Panel(**{**{f: getattr(panel, f) for f in panel.__dataclass_fields__}, "close": close})


def test_float32_grid_shape_and_warmup_nan():
    panel, _, _ = _panel()
    out = kernel_source(
        panel, ["rk_price_percentile_w20"], {"rk_price_percentile": 20}, CONFIG, max_gap_rows=0
    )
    arr = out.values["rk_price_percentile_w20"]
    assert arr.dtype == np.float32 and arr.shape == (N, M)
    assert np.isnan(arr[:19]).all() and np.isfinite(arr[19:]).all()
    assert out.memory_bars == {"rk_price_percentile_w20": 19}
    assert out.warmup_masked["rk_price_percentile_w20"] == 19 * M
    kernel = rolling_percentile_kernel(20)
    direct = kernel.compute({"close": panel.close[:, 1]}, None)[kernel.name].astype(np.float32)
    assert np.array_equal(arr[:, 1], direct, equal_nan=True)


def test_absent_rows_are_nan_and_present_rows_match_compressed_series():
    panel, _, _ = _panel()
    absent = [5, 40, 41, 42, 200]
    gapped = _with_gaps(panel, 0, absent)
    out = kernel_source(
        gapped, ["rk_price_percentile_w10"], {"rk_price_percentile": 10}, CONFIG, max_gap_rows=10
    )
    arr = out.values["rk_price_percentile_w10"][:, 0]
    assert np.isnan(arr[absent]).all()
    present = np.setdiff1d(np.arange(N), absent)
    kernel = rolling_percentile_kernel(10)
    direct = kernel.compute({"close": panel.close[present, 0]}, None)[kernel.name]
    assert np.array_equal(arr[present], direct.astype(np.float32), equal_nan=True)
    # Warmup counts present rows from the symbol's first present row: row 5 is absent, so the
    # first nine present rows are 0..4 and 6..9.
    assert np.isnan(arr[:10]).all() and np.isfinite(arr[10])


def test_gap_rule_masks_windows_spanning_too_many_absent_rows():
    panel, _, _ = _panel()
    gapped = _with_gaps(panel, 0, range(100, 104))  # four absent grid rows
    w = 10
    out = kernel_source(
        gapped, [f"rk_price_percentile_w{w}"], {"rk_price_percentile": w}, CONFIG, max_gap_rows=3
    )
    arr = out.values[f"rk_price_percentile_w{w}"][:, 0]
    # Present rows 104..112 have a trailing 10-present-row window reaching back across the gap
    # (span 13 > 9 + 3); row 113's window starts at 104 (span 9).
    assert np.isnan(arr[104:113]).all()
    assert np.isfinite(arr[113]) and np.isfinite(arr[99])
    assert out.gap_masked[f"rk_price_percentile_w{w}"] == 9
    loose = kernel_source(
        gapped, [f"rk_price_percentile_w{w}"], {"rk_price_percentile": w}, CONFIG, max_gap_rows=4
    )
    assert loose.gap_masked[f"rk_price_percentile_w{w}"] == 0
    assert np.isfinite(loose.values[f"rk_price_percentile_w{w}"][104:113, 0]).all()


def test_invalid_rows_are_absent():
    panel, high, low = _panel()
    valid = panel.valid.copy()
    valid[50] = False
    shut = Panel(**{**{f: getattr(panel, f) for f in panel.__dataclass_fields__}, "valid": valid})
    out = kernel_source(
        shut, ["rk_vwap_dev_w5"], {"rk_vwap_dev": 5}, None, max_gap_rows=1, high=high, low=low
    )
    assert np.isnan(out.values["rk_vwap_dev_w5"][50]).all()


def test_guard5_refuses_path_dependent_output():
    panel, high, low = _panel()
    with pytest.raises(KernelSourceRefused, match="D7 guard 5"):
        kernel_source(panel, ["vwap_dev_sigma"], {}, CONFIG, max_gap_rows=0, high=high, low=low)
    with pytest.raises(KernelSourceRefused, match="D7 guard 5"):
        kernel_member_memory_bars("vwap_dev_sigma", {}, CONFIG)


def test_unknown_output_and_family_refused():
    panel, _, _ = _panel()
    with pytest.raises(KernelSourceRefused):
        kernel_source(panel, ["no_such_column"], {}, CONFIG, max_gap_rows=0)
    with pytest.raises(KernelSourceRefused):
        kernel_source(panel, ["rk_price_percentile_w30"], {"rk_nope": 30}, CONFIG, max_gap_rows=0)
    # A window other than the pinned one is not in the registry.
    with pytest.raises(KernelSourceRefused):
        kernel_source(
            panel, ["rk_price_percentile_w30"], {"rk_price_percentile": 20}, CONFIG, max_gap_rows=0
        )


def test_missing_high_low_refused():
    panel, _, _ = _panel()
    with pytest.raises(KernelSourceRefused, match="high"):
        kernel_source(panel, ["rk_vwap_dev_w20"], {"rk_vwap_dev": 20}, None, max_gap_rows=0)


def test_bad_max_gap_rows_refused():
    panel, _, _ = _panel()
    for bad in (-1, 1.5, True):
        with pytest.raises(KernelSourceRefused):
            kernel_source(
                panel, ["rk_high_dist_w20"], {"rk_high_dist": 20}, CONFIG, max_gap_rows=bad
            )


@pytest.mark.parametrize(
    "output, family, window",
    [
        ("rk_price_percentile_w50", "rk_price_percentile", 50),
        ("rk_price_percentile_w200", "rk_price_percentile", 200),
        ("rk_high_dist_w252", "rk_high_dist", 252),
    ],
)
def test_stored_window_refused(output, family, window):
    panel, _, _ = _panel()
    with pytest.raises(KernelSourceRefused, match="row 10"):
        kernel_source(panel, [output], {family: window}, CONFIG, max_gap_rows=0)


def test_stored_window_check_needs_config():
    panel, _, _ = _panel()
    with pytest.raises(KernelSourceRefused, match="provenance config"):
        kernel_source(panel, ["rk_high_dist_w126"], {"rk_high_dist": 126}, None, max_gap_rows=0)


def test_member_memory_from_registry():
    windows = {"rk_price_percentile": 126}
    assert kernel_member_memory_bars("rk_price_percentile_w126", windows, None) == 125
    reg = kernel_registry(windows, None)
    assert feature_memory_bars("rk_price_percentile_w126", None, registry=reg) == 125  # type: ignore[arg-type]
    assert kernel_member_memory_bars("high_52w_dist", {}, CONFIG) == 252


def _composed_registry(monkeypatch):
    """A research kernel consuming the stored high_52w_dist, built in the test."""

    def compute(x, config):
        return {"rk_test_composed": np.asarray(x["high_52w_dist"], dtype=float) * 2.0}

    composed = Kernel(
        name="rk_test_composed",
        outputs=("rk_test_composed",),
        inputs=("high_52w_dist",),
        memory=lambda c: 0,
        compute=compute,
    )
    original = ks.kernel_registry

    def patched(windows, config):
        base = original(windows, config)
        return KernelRegistry.from_kernels(base.kernels + (composed,), base.external_inputs)

    monkeypatch.setattr(ks, "kernel_registry", patched)


def test_config_refused_for_composed_kernel_without_config(monkeypatch):
    _composed_registry(monkeypatch)
    panel, _, _ = _panel()
    with pytest.raises(KernelSourceRefused, match="provenance config"):
        kernel_source(panel, ["rk_test_composed"], {}, None, max_gap_rows=0)
    with pytest.raises(KernelSourceRefused, match="provenance config"):
        kernel_member_memory_bars("rk_test_composed", {}, None)


def test_config_composed_kernel_resolves_upstream_with_explicit_config(monkeypatch):
    _composed_registry(monkeypatch)
    panel, _, _ = _panel()
    config = SimpleNamespace(high_52w_window=30)
    out = kernel_source(panel, ["rk_test_composed"], {}, config, max_gap_rows=0)
    arr = out.values["rk_test_composed"]
    assert out.memory_bars["rk_test_composed"] == 30  # own 0 + upstream high_52w_dist's 30
    from src.intelligence.features.kernels.price import _high_52w_dist_series_full

    expected = (_high_52w_dist_series_full(panel.close[:, 2], 30) * 2.0).astype(np.float32)
    assert np.array_equal(arr[30:, 2], expected[30:])
    assert np.isnan(arr[:30]).all()


def test_config_free_research_kernel_runs_with_none():
    panel, high, low = _panel()
    out = kernel_source(
        panel, ["rk_vwap_dev_w20"], {"rk_vwap_dev": 20}, None, max_gap_rows=0, high=high, low=low
    )
    kernel = rolling_vwap_deviation_kernel(20)
    j = 1
    direct = kernel.compute(
        {
            "high": high[:, j],
            "low": low[:, j],
            "close": panel.close[:, j],
            "volume": panel.volume[:, j],
        },
        None,
    )[kernel.name].astype(np.float32)
    assert np.array_equal(out.values["rk_vwap_dev_w20"][:, j], direct, equal_nan=True)


def test_config_module_never_builds_a_default_config():
    import inspect

    text = inspect.getsource(ks)
    assert "FeatureFactoryConfig()" not in text
    assert "ConfigService" not in text
