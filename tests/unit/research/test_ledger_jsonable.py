"""jsonable: evidence dicts become strict JSON before the terminal research_run write.

Postgres jsonb refuses NaN and numpy types are not JSON types (183-RESEARCH pitfall 8), so
ledger.finish_run converts evidence with jsonable and serializes with allow_nan=False.
"""

from __future__ import annotations

import json

import numpy as np
import pytest

from src.intelligence.research.ledger import jsonable


def test_numpy_nan_inf_tuple_and_keys() -> None:
    value = {
        "a": np.float32(1.5),
        "b": np.array([1.0, np.nan]),
        "c": float("inf"),
        "d": (np.int64(2),),
        3: None,
    }
    result = jsonable(value)
    assert result == {"a": 1.5, "b": [1.0, None], "c": None, "d": [2], "3": None}
    assert type(result["a"]) is float
    assert type(result["d"][0]) is int
    json.dumps(result, allow_nan=False)


def test_nested_recursion() -> None:
    value = {"outer": [{"x": np.float64(-np.inf)}, [np.int32(4), "s", True]]}
    assert jsonable(value) == {"outer": [{"x": None}, [4, "s", True]]}


def test_numpy_bool() -> None:
    assert jsonable(np.bool_(True)) is True


def test_nan_in_2d_array() -> None:
    assert jsonable(np.array([[np.nan, 2.0]])) == [[None, 2.0]]


def test_unsupported_type_raises() -> None:
    with pytest.raises(TypeError):
        jsonable(object())
    with pytest.raises(TypeError):
        jsonable({"k": {1, 2}})
