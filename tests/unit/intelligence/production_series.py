"""Rows of one series computed through the path the corpus rerun runs (R2 item 2).

`series_rows` replaces the deleted `FeatureFactory.compute_batch` in the tests that check input
alignment and causality: it builds the kernel inputs with `_series_kernel_inputs` (the one
definition of the macro and higher-timeframe alignment) and computes every column with
`_compute_series_columns`. Values are float32 columns read back as Python floats; a missing value
is NaN (never None, never a fill), so a test compares with `pytest.approx` and `math.isnan`.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Mapping, Sequence
from datetime import datetime
from types import SimpleNamespace
from typing import Any

import numpy as np

from src.intelligence.features.contract.registry import constant_volume_basis
from src.intelligence.features.feature_factory_config import FeatureFactoryConfig
from src.intelligence.features.feature_vector_persistence import feature_vectors_numeric_columns
from src.intelligence.features.kernels._hmm import HmmConfig
from tests.unit.intelligence.kernel_parity_reference import dt_to_ns
from tests.unit.intelligence.regime_kernel_fixtures import SMALL_HMM_APR

_BAR_FIELDS = ("open", "high", "low", "close", "volume")


def series_columns(
    bars: Sequence[Mapping[str, Any]],
    symbol: str,
    tf: str,
    config: FeatureFactoryConfig,
    *,
    cross_asset_by_date: dict | None = None,
    beta_by_date: dict | None = None,
    htf_bars: list[dict] | None = None,
) -> dict[str, np.ndarray]:
    """Every numeric feature_vectors column of the series, one float32 array per column."""
    from services.backfill_feature_factory import _compute_series_columns, _series_kernel_inputs

    if config.hmm is None:  # the regime kernels run under the unit-test HMM values
        config = dataclasses.replace(config, hmm=HmmConfig.from_values(SMALL_HMM_APR.get))
    ts = np.array([dt_to_ns(b["ts"]) for b in bars], dtype=np.int64)
    arrays = {
        "ts": ts,
        **{f: np.array([b[f] for b in bars], dtype=np.float64) for f in _BAR_FIELDS},
        "volume_basis": constant_volume_basis(len(bars)),
    }
    inputs = _series_kernel_inputs(
        symbol,
        tf,
        arrays,
        config,
        cross_asset_by_date or {},
        beta_by_date or {},
        htf_bars or [],
    )
    series = _compute_series_columns(inputs, config)
    return {name: series.numeric[:, j] for j, name in enumerate(feature_vectors_numeric_columns())}


def series_rows(
    bars: Sequence[Mapping[str, Any]],
    symbol: str,
    tf: str,
    config: FeatureFactoryConfig,
    **inputs: Any,
) -> dict[datetime, SimpleNamespace]:
    """The same columns as one namespace per bar, keyed by the bar's timestamp."""
    columns = series_columns(bars, symbol, tf, config, **inputs)
    return {
        bar["ts"]: SimpleNamespace(**{name: float(col[i]) for name, col in columns.items()})
        for i, bar in enumerate(bars)
    }
