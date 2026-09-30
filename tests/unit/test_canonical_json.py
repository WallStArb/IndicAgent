"""One canonical JSON text for every identity hash (research specs, unit identities, batch keys).

CI-clean: no DB, no network.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime

import pytest

from services._batch_utils import BulkLoadSpec
from src.core.canonical_json import canonical_json
from src.intelligence.research import spec as research_spec


def test_sorted_compact_and_not_ascii_escaped() -> None:
    assert canonical_json({"b": 1, "a": [1.5, "é"]}) == '{"a":[1.5,"é"],"b":1}'


def test_nan_and_non_json_values_raise_instead_of_hashing_a_guess() -> None:
    with pytest.raises(ValueError):
        canonical_json({"a": float("nan")})
    with pytest.raises(TypeError):
        canonical_json({"a": datetime(2026, 1, 1, tzinfo=UTC)})


def test_the_research_spec_hash_uses_the_same_function() -> None:
    assert research_spec.canonical_json is canonical_json


def test_bulk_load_keys_equal_the_inline_dumps_they_replaced_for_json_inputs() -> None:
    spec = BulkLoadSpec(
        writer="ic_measure.proposer",
        target_table="feature_ic_scores_v2",
        time_column="training_window_end",
        tf="1d",
        range_start=datetime(2020, 1, 1, tzinfo=UTC),
        range_end=datetime(2025, 12, 24, tzinfo=UTC),
        symbols=("SPY", "QQQ"),
        code_key="a" * 64,
        apr_snapshot={"alpha.ic.fdr_alpha": 0.05, "h": [1, 2, 5], "s": "x"},
        input_digest="b" * 64,
        replace_where={"tf": "1d", "symbol": "POOLED", "regime_scope": "unstratified"},
    )

    def old(obj: object, **extra: object) -> str:
        return hashlib.sha256(
            json.dumps(obj, sort_keys=True, separators=(",", ":"), **extra).encode()
        ).hexdigest()

    assert spec.apr_hash == old(spec.apr_snapshot, default=str)
    assert spec.unit_key == old(
        {
            "writer": spec.writer,
            "target_table": spec.target_table,
            "tf": "1d",
            "replace_where": {"tf": "1d", "symbol": "POOLED", "regime_scope": "unstratified"},
        }
    )


def test_a_nan_in_the_apr_snapshot_refuses_the_spec_key() -> None:
    spec = BulkLoadSpec(
        writer="w",
        target_table="t",
        time_column="c",
        tf="1d",
        range_start=datetime(2020, 1, 1, tzinfo=UTC),
        range_end=datetime(2021, 1, 1, tzinfo=UTC),
        symbols=("SPY",),
        code_key="a" * 64,
        apr_snapshot={"x": float("nan")},
        input_digest="b" * 64,
    )
    with pytest.raises(ValueError):
        _ = spec.batch_key
