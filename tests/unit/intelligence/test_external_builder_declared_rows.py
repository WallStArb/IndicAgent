"""The pass-through kernels declare the first row each external builder can emit (todo 652).

The beta and market residual columns reach the registry as pass-throughs of builders that run
outside it (`build_symbol_beta_series`, `build_market_residual_series`); each declares a
`definition` so the screen's G2 and G6 measure them from the row the builder first emits a
value, not from row 0. The builders are run here on a healthy series and the first finite
record row is compared with `definition_warmup`.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta

import numpy as np
import pytest

from src.intelligence.features.kernels.macro import build_symbol_beta_series
from src.intelligence.features.kernels.residual import (
    RESIDUAL_COLUMNS,
    build_market_residual_series,
)
from tests.unit.intelligence.test_kernel_no_object_contract import _no_object_registry

_N = 700


def _bars(seed: int) -> list[dict]:
    rng = np.random.default_rng(seed)
    closes = 100.0 * np.exp(np.cumsum(rng.normal(0, 0.01, _N)))
    start = datetime(2020, 1, 1, tzinfo=UTC)
    return [{"ts": start + timedelta(days=i), "close": float(c)} for i, c in enumerate(closes)]


def _first_row(records: dict, bars: list[dict], pick) -> int | None:
    """The 0-based bar row of the first record whose picked value is finite."""
    for i, bar in enumerate(bars):
        record = records.get(bar["ts"].date())
        value = None if record is None else pick(record)
        if value is not None and math.isfinite(value):
            return i
    return None


@pytest.fixture(scope="module")
def registry_and_config():
    return _no_object_registry()


def test_beta_columns_are_declared_at_the_builders_first_row(registry_and_config):
    registry, config = registry_and_config
    records = build_symbol_beta_series(_bars(1), _bars(2), _bars(3), "TEST", config)
    bars = _bars(1)
    for column, index in (("equity_beta_z", 0), ("rate_beta_z", 1)):
        first = _first_row(records, bars, lambda r, k=index: r[k])
        declared = registry.definition_warmup(column, config, "1d")
        assert first == declared, (column, first, declared)
    assert declared == config.factor_beta_window + config.factor_beta_zscore_window - 1


def test_market_residual_columns_are_declared_at_the_builders_first_row(registry_and_config):
    registry, config = registry_and_config
    records = build_market_residual_series(_bars(1), _bars(2), "TEST", config)
    bars = _bars(1)
    for column in RESIDUAL_COLUMNS:
        first = _first_row(records, bars, lambda r, c=column: getattr(r, c))
        declared = registry.definition_warmup(column, config, "1d")
        assert first == declared, (column, first, declared)


def test_the_cross_asset_record_columns_keep_a_zero_definition(registry_and_config):
    """Their first row is where their input series begin (data), so the screen starts their
    clock from the stored rows rather than from a declaration."""
    registry, config = registry_and_config
    for column in ("vix_z", "tip_tlt_ret_z", "hyg_lqd_ret_z", "sb_corr_z"):
        assert registry.definition_warmup(column, config, "1d") == 0
