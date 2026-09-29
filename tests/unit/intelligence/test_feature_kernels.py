"""Registered feature kernels against compute_batch and the causality probe (186-12, D-25, D-26).

(a) every registered feature column is a persisted FeatureVector column;
(b) each kernel output equals the compute_batch column on the 500-bar synthetic fixture;
(c) compute_batch no longer calls the moved scalar helpers;
(d) the causality probe and memory check pass every kernel under two configs.
"""

from __future__ import annotations

import inspect
from datetime import UTC, datetime
from functools import lru_cache

import numpy as np
import pytest

from src.intelligence.feature_cache import FeatureCache
from src.intelligence.feature_factory import FeatureFactory
from src.intelligence.features.causality_probe import probe_registry
from src.intelligence.features.feature_vector_persistence import _ALL_COLUMN_NAMES
from src.intelligence.features.registry import compute_kernels, default_registry
from tests.unit.intelligence import kernel_parity_reference as ref

MANIFEST = ref.load_manifest()
PROBE_ROWS = np.array([700, 1200, 1800, 2400, 2999])
PROBE_BARS = 3000

# Kernels whose output depends on where the series starts (registry path_dependent).
PATH_DEPENDENT = {"calendar_above_wk_vwap"}
ACAUSAL_CONTROLS = {"canary_acausal_placebo"}

# compute_batch calls none of these helpers by name any more; it reads registry outputs.
DELEGATED_HELPERS = (
    "_in_ny_session",
    "_in_london_kz",
    "_in_overlap",
    "_power_hour",
    "_opening_range",
    "_session_time_pos",
    "_dow_encoding",
    "_month_position",
    "_quarter_position",
    "_days_to_month_end_fraction",
    "_quarter_cycle_encoding",
    "_tdom_encoding",
    "_minute_of_hour_encoding",
    "_hour_of_day_sin",
    "_hour_of_day_cos",
    "_week_of_month_sin",
    "_week_of_month_cos",
    "_day_of_month_sin",
    "_day_of_month_cos",
    "_week_of_year_sin",
    "_week_of_year_cos",
    "_month_sin",
    "_month_cos",
    "_opex_flag",
    "_quad_witching_flag",
    "_earnings_season_flag",
    "_days_since_quarter_end",
    "_canary_noise_gaussian",
    "_canary_noise_uniform",
    "_canary_near_constant",
    "_canary_acausal_placebo",
)


def synthetic_bars(n: int, seed: int = 42) -> dict[str, np.ndarray]:
    """Same generator order as the parity fixture's synthetic case, for any length."""
    rng = np.random.default_rng(seed)
    closes = np.cumprod(1.0 + rng.normal(0, 0.005, n)) * 100.0
    spread = closes * rng.uniform(0.001, 0.008, n)
    highs = closes + spread
    lows = closes - spread
    opens = closes + rng.normal(0, 0.003, n) * closes
    highs = np.maximum(highs, np.maximum(opens, closes))
    lows = np.minimum(lows, np.minimum(opens, closes))
    volumes = rng.uniform(1e5, 1e7, n)
    base = ref.dt_to_ns(datetime(2023, 1, 3, 14, 30, tzinfo=UTC))
    ts = base + np.arange(n, dtype=np.int64) * 5 * 60 * 1_000_000_000
    return {
        "ts": ts,
        "open": opens,
        "high": highs,
        "low": lows,
        "close": closes,
        "volume": volumes,
        "symbol": np.array(["SPY"] * n, dtype=object),
    }


@lru_cache(maxsize=1)
def _synthetic_case():
    inputs, config = ref.synthetic_inputs()
    inputs = {**inputs, "symbol": np.array(["SPY"] * len(inputs["ts"]), dtype=object)}
    bars = ref._bars_from_arrays(
        *(inputs[f] for f in ("ts", "open", "high", "low", "close", "volume"))
    )
    results = FeatureFactory.compute_batch(
        bars, "SPY", "5m", FeatureCache(), config, warm_up_bars=0
    )
    batch = {
        name: np.array([getattr(fv, name) for _, fv in results], dtype=np.float64)
        for name in _ALL_COLUMN_NAMES
        if hasattr(results[0][1], name)
    }
    kernels = compute_kernels(default_registry(), inputs, config)
    return kernels, batch, len(inputs["ts"])


def test_feature_columns_are_persisted_columns():
    columns = default_registry().feature_columns()
    assert columns
    assert set(columns) <= set(_ALL_COLUMN_NAMES)


def test_kernel_outputs_equal_compute_batch_rows_1_onward():
    kernels, batch, n = _synthetic_case()
    columns = default_registry().feature_columns()
    for name in columns:
        assert name in batch, f"{name} is not a FeatureVector field"
        got = kernels[name][1:].astype(np.float32)
        want = batch[name].astype(np.float32)
        assert len(got) == len(want) == n - 1
        bad = ~((got == want) | (np.isnan(got) & np.isnan(want)))
        assert (
            not bad.any()
        ), f"{name}: row {int(np.argmax(bad)) + 1} got {got[bad][0]!r} want {want[bad][0]!r}"


def _code_lines(func) -> str:
    return "\n".join(
        line for line in inspect.getsource(func).splitlines() if not line.lstrip().startswith("#")
    )


def test_compute_batch_calls_no_delegated_helper():
    body = _code_lines(FeatureFactory.compute_batch)
    called = [name for name in DELEGATED_HELPERS if f"{name}(" in body]
    assert called == []


@pytest.mark.parametrize("config_key", ["synthetic_config", "real_config"])
def test_probe_registry_passes_every_kernel(config_key):
    config = ref.build_config(MANIFEST[config_key])
    statuses = probe_registry(default_registry(), synthetic_bars(PROBE_BARS), config, PROBE_ROWS)
    expected = {
        kernel.name: (
            "acausal_control_detected"
            if kernel.name in ACAUSAL_CONTROLS
            else "path_dependent_skipped_memory" if kernel.name in PATH_DEPENDENT else "ok"
        )
        for kernel in default_registry().kernels
    }
    assert statuses == expected
