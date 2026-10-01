"""The feature_vectors_v2 row contract (186-25): registry-derived columns pinned to the 186-24
migration, the dropped set pinned to its evidence file, and the row builder's NaN policy."""

from __future__ import annotations

import json
import math
from datetime import UTC, datetime

import pytest

from src.intelligence.features import feature_vector_persistence as persistence
from src.intelligence.features.contract.registry import UNOWNED_COLUMNS, default_registry
from src.intelligence.features.feature_vector_persistence import (
    FEATURE_VECTORS_V2_COLUMNS,
    FEATURE_VECTORS_V2_DROPPED_FEATURE_COLUMNS,
    feature_vector_v2_row_values,
    feature_vectors_v2_columns,
    feature_vectors_v2_numeric_columns,
)
from tests.unit.intelligence.test_feature_vectors_v2_schema import (
    _EVIDENCE,
    METADATA_DROPPED,
    expected_columns,
    parsed_columns,
)

_DROPPED_METADATA = (
    "feature_vector_id",
    "pipeline_version",
    "feature_factory_version",
    "bar_close_ts",
    "regime_label_source",
)


def test_column_count_and_order_match_the_migration() -> None:
    assert len(FEATURE_VECTORS_V2_COLUMNS) == 312
    assert FEATURE_VECTORS_V2_COLUMNS[:5] == (
        "symbol",
        "tf",
        "bar_ts",
        "regime",
        "regime_volatility",
    )
    # Same set and the same order as the DDL the 186-24 test parses.
    assert list(FEATURE_VECTORS_V2_COLUMNS) == parsed_columns()
    assert set(FEATURE_VECTORS_V2_COLUMNS) == expected_columns()


def test_numeric_columns_are_the_registry_derivation_never_typed() -> None:
    registry = default_registry()
    numeric = feature_vectors_v2_numeric_columns()
    assert len(numeric) == 307
    assert list(numeric) == [
        c
        for c in registry.feature_columns()
        if c not in FEATURE_VECTORS_V2_DROPPED_FEATURE_COLUMNS | {"regime", "regime_volatility"}
    ]
    assert feature_vectors_v2_columns() == FEATURE_VECTORS_V2_COLUMNS


def test_dropped_columns_absent_and_pinned_to_the_evidence_file() -> None:
    evidence = json.loads(_EVIDENCE.read_text())
    assert set(evidence["dropped_columns"]) == set(FEATURE_VECTORS_V2_DROPPED_FEATURE_COLUMNS)
    assert set(evidence["metadata_dropped"]) == set(_DROPPED_METADATA)
    columns = set(FEATURE_VECTORS_V2_COLUMNS)
    assert not columns & set(FEATURE_VECTORS_V2_DROPPED_FEATURE_COLUMNS)
    assert not columns & set(_DROPPED_METADATA)
    assert set(_DROPPED_METADATA) == set(METADATA_DROPPED)
    # The three rank columns are not in feature_columns(); days_to_month_end is, so it is the
    # one the derivation excludes explicitly.
    assert "days_to_month_end" in default_registry().feature_columns()
    for name in ("momentum_rank_z", "volume_rank_z", "volatility_rank_z"):
        assert name in UNOWNED_COLUMNS
        assert name not in default_registry().feature_columns()
    assert {"asian_session_high_dist_atr", "asian_session_low_dist_atr"} <= columns


def test_lazy_attribute_rejects_unknown_names() -> None:
    with pytest.raises(AttributeError):
        persistence.NO_SUCH_COLUMNS  # noqa: B018


def _numeric(fill: float) -> list[float]:
    return [fill] * len(feature_vectors_v2_numeric_columns())


def test_row_values_put_keys_and_regime_first_and_match_the_column_count() -> None:
    ts = datetime(2020, 1, 2, 14, 30, tzinfo=UTC)
    row = feature_vector_v2_row_values("SPY", "5m", ts, "bull", None, _numeric(1.5))
    assert row[:5] == ("SPY", "5m", ts, "bull", None)
    assert len(row) == len(FEATURE_VECTORS_V2_COLUMNS)
    assert all(v == 1.5 for v in row[5:])


def test_nan_is_missing_so_none_and_never_zero_or_nan_text() -> None:
    numeric = _numeric(2.0)
    nan_at = (0, 17, len(numeric) - 1)
    for i in nan_at:
        numeric[i] = math.nan
    numeric[3] = 0.0
    numeric[4] = math.inf
    row = feature_vector_v2_row_values(
        "SPY", "1d", datetime(2020, 1, 2, tzinfo=UTC), None, None, numeric
    )
    values = row[5:]
    for i in nan_at:
        assert values[i] is None
    assert values[3] == 0.0 and values[3] is not None  # a real zero stays a zero
    assert values[4] == math.inf  # infinity is kept, it is a loud value not a missing one
    assert sum(v is None for v in values) == len(nan_at)


def test_wrong_numeric_length_raises() -> None:
    with pytest.raises(ValueError, match="numeric values"):
        feature_vector_v2_row_values(
            "SPY", "1d", datetime(2020, 1, 2, tzinfo=UTC), None, None, [1.0]
        )
