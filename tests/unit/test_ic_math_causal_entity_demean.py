"""Unit tests for causal_entity_expanding_mean (todo 185).

Guards against the nonlinear_interaction_combiner leak (static per-symbol drift learned as a
fixed-membership factor exposure) recurring in any future pooled-panel measurement. DB-free.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

_project_root = Path(__file__).parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from src.intelligence.statistics.ic_math import causal_entity_expanding_mean


def _reference_pandas_demean(
    entity_ids: np.ndarray, values: np.ndarray, min_periods: int
) -> np.ndarray:
    """Independent reference implementation via pandas groupby -- deliberately re-derived
    (not calling the function under test) so this test proves equivalence to the documented
    shift(1)/expanding(min_periods=...) semantics, not just self-consistency."""
    df = pd.DataFrame({"entity": entity_ids, "value": values})
    means = df.groupby("entity")["value"].apply(
        lambda s: s.shift(1).expanding(min_periods=min_periods).mean()
    )
    return means.reset_index(level=0, drop=True).sort_index().to_numpy()


def test_causal_entity_expanding_mean_matches_pandas_reference() -> None:
    rng = np.random.default_rng(42)
    entities = np.repeat(["AAA", "BBB", "CCC"], 20)
    values = rng.normal(size=len(entities))
    result = causal_entity_expanding_mean(entities, values, min_periods=3)
    expected = _reference_pandas_demean(entities, values, min_periods=3)
    np.testing.assert_allclose(result, expected, equal_nan=True)


def test_causal_entity_expanding_mean_is_causal_no_lookahead() -> None:
    """Row i's mean must be identical whether or not later rows for the same entity exist --
    proves no future information leaks backward into an earlier row's mean."""
    entities = np.array(["AAA"] * 10)
    values = np.arange(10, dtype=float)
    full = causal_entity_expanding_mean(entities, values, min_periods=1)

    truncated = causal_entity_expanding_mean(entities[:5], values[:5], min_periods=1)
    np.testing.assert_allclose(full[:5], truncated, equal_nan=True)


def test_causal_entity_expanding_mean_never_includes_own_value() -> None:
    """A constant-except-one-outlier series: if row i's mean ever included row i's own
    value, the outlier row's mean would shift measurably. It must not."""
    entities = np.array(["AAA"] * 5)
    values = np.array([1.0, 1.0, 1.0, 1000.0, 1.0])
    result = causal_entity_expanding_mean(entities, values, min_periods=1)
    # Row 3 (the outlier itself) should average only rows [0,1,2] = 1.0, not include 1000.0.
    assert result[3] == pytest.approx(1.0)
    # Row 4 (immediately after the outlier) SHOULD reflect it: mean(1,1,1,1000) = 250.75.
    assert result[4] == pytest.approx(250.75)


def test_causal_entity_expanding_mean_respects_min_periods() -> None:
    entities = np.array(["AAA"] * 5)
    values = np.arange(5, dtype=float)
    result = causal_entity_expanding_mean(entities, values, min_periods=3)
    # Rows with fewer than 3 PRIOR observations (rows 0, 1, 2) are undefined.
    assert np.isnan(result[0])
    assert np.isnan(result[1])
    assert np.isnan(result[2])
    assert not np.isnan(result[3])
    assert not np.isnan(result[4])


def test_causal_entity_expanding_mean_multi_entity_isolation() -> None:
    """One entity's values must never leak into another entity's mean."""
    entities = np.array(["AAA", "AAA", "AAA", "BBB", "BBB", "BBB"])
    values = np.array([10.0, 20.0, 30.0, 1000.0, 1000.0, 1000.0])
    result = causal_entity_expanding_mean(entities, values, min_periods=1)
    # BBB's first defined mean (row 4, one prior BBB obs) must be 1000.0, not contaminated
    # by AAA's much smaller values despite AAA appearing earlier in the array.
    assert result[4] == pytest.approx(1000.0)
