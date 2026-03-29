"""Tests for StateSerializer — msgpack encode/decode with type tagging."""

from collections import deque

import numpy as np
import pytest
from pydantic import BaseModel

from src.core.state_serializer import (
    PYDANTIC_REGISTRY,
    StateDeserializationError,
    StateSerializer,
    register_pydantic_model,
)


# ---------------------------------------------------------------------------
# Test-local Pydantic model for round-trip tests
# ---------------------------------------------------------------------------


class _TestModel(BaseModel):
    value: float
    name: str


register_pydantic_model(_TestModel)


# ---------------------------------------------------------------------------
# Round-trip tests — encode then decode should produce identical result
# ---------------------------------------------------------------------------


class TestPrimitives:
    def test_int_round_trip(self):
        state = {"x": 42}
        result = StateSerializer.decode(StateSerializer.encode(state))
        assert result == state

    def test_float_round_trip(self):
        state = {"x": 3.14}
        result = StateSerializer.decode(StateSerializer.encode(state))
        assert result == state

    def test_string_round_trip(self):
        state = {"x": "hello"}
        result = StateSerializer.decode(StateSerializer.encode(state))
        assert result == state

    def test_bool_round_trip(self):
        state = {"x": True, "y": False}
        result = StateSerializer.decode(StateSerializer.encode(state))
        assert result == state

    def test_none_round_trip(self):
        state = {"x": None}
        result = StateSerializer.decode(StateSerializer.encode(state))
        assert result == state

    def test_empty_dict_round_trip(self):
        state = {}
        result = StateSerializer.decode(StateSerializer.encode(state))
        assert result == {}


class TestNumpyArrays:
    def test_float64_array_round_trip(self):
        arr = np.array([1.0, 2.5, 3.7], dtype=np.float64)
        state = {"data": arr}
        result = StateSerializer.decode(StateSerializer.encode(state))
        np.testing.assert_array_equal(result["data"], arr)
        assert result["data"].dtype == np.float64

    def test_int32_array_round_trip(self):
        arr = np.array([1, 2, 3], dtype=np.int32)
        state = {"data": arr}
        result = StateSerializer.decode(StateSerializer.encode(state))
        np.testing.assert_array_equal(result["data"], arr)
        assert result["data"].dtype == np.int32

    def test_2d_array_round_trip(self):
        arr = np.array([[1.0, 2.0], [3.0, 4.0]], dtype=np.float64)
        state = {"data": arr}
        result = StateSerializer.decode(StateSerializer.encode(state))
        np.testing.assert_array_equal(result["data"], arr)


class TestPydanticModels:
    def test_registered_model_round_trip(self):
        model = _TestModel(value=1.5, name="test")
        state = {"model": model}
        result = StateSerializer.decode(StateSerializer.encode(state))
        assert isinstance(result["model"], _TestModel)
        assert result["model"].value == 1.5
        assert result["model"].name == "test"

    def test_unknown_pydantic_class_raises(self):
        """Decode a manually-constructed tagged dict with unknown class name."""
        import msgpack

        raw = msgpack.packb(
            {"model": {"__pydantic__": "NonExistentModel", "data": {}}},
            use_bin_type=True,
        )
        with pytest.raises(StateDeserializationError, match="NonExistentModel"):
            StateSerializer.decode(raw)


class TestDeques:
    def test_deque_with_maxlen_round_trip(self):
        d = deque([1, 2, 3], maxlen=5)
        state = {"d": d}
        result = StateSerializer.decode(StateSerializer.encode(state))
        assert isinstance(result["d"], deque)
        assert list(result["d"]) == [1, 2, 3]
        assert result["d"].maxlen == 5

    def test_deque_without_maxlen_round_trip(self):
        d = deque([1, 2, 3])
        state = {"d": d}
        result = StateSerializer.decode(StateSerializer.encode(state))
        assert isinstance(result["d"], deque)
        assert list(result["d"]) == [1, 2, 3]
        assert result["d"].maxlen is None


class TestNestedStructures:
    def test_nested_dict_with_mixed_types(self):
        arr = np.array([1.0, 2.0], dtype=np.float64)
        d = deque([10, 20], maxlen=100)
        model = _TestModel(value=3.14, name="nested")
        state = {
            "level1": {
                "arr": arr,
                "level2": {
                    "deque": d,
                    "model": model,
                    "primitive": 42,
                },
            }
        }
        result = StateSerializer.decode(StateSerializer.encode(state))
        np.testing.assert_array_equal(result["level1"]["arr"], arr)
        assert list(result["level1"]["level2"]["deque"]) == [10, 20]
        assert result["level1"]["level2"]["model"].value == 3.14
        assert result["level1"]["level2"]["primitive"] == 42

    def test_list_with_mixed_types(self):
        arr = np.array([1.0], dtype=np.float64)
        d = deque([1, 2], maxlen=10)
        state = {"items": [arr, d, "hello", 42, None]}
        result = StateSerializer.decode(StateSerializer.encode(state))
        np.testing.assert_array_equal(result["items"][0], arr)
        assert list(result["items"][1]) == [1, 2]
        assert result["items"][2] == "hello"
        assert result["items"][3] == 42
        assert result["items"][4] is None


class TestFullAgentState:
    """Simulates the real five-field agent state dict."""

    def test_full_state_round_trip(self):
        state = {
            "plugin_state": {
                "('rsi', 'ESM6', '1m')": {"value": 65.3, "history": np.array([60.0, 63.0, 65.3])},
                "('macd', 'ESM6', '1m')": {"signal": 0.5, "histogram": np.array([0.1, 0.2, 0.3])},
            },
            "kalman_state": {
                "ESM6:1m": {"x_est": np.array([0.5, 0.02]), "P_est": np.array([[0.01, 0.0], [0.0, 0.01]])}
            },
            "tod_priors": {
                "('trend', '1m', 9)": 1.05,
                "('mean_reversion', '1m', 14)": 0.95,
            },
            "bar_history": {
                "ESM6:1m": deque(
                    [{"open": 5100.0, "high": 5105.0, "low": 5098.0, "close": 5102.0}],
                    maxlen=200,
                ),
            },
            "last_bar_offset": {"ESM6:1m": 12345, "ESM6:5m": 2345},
        }
        result = StateSerializer.decode(StateSerializer.encode(state))

        # plugin_state
        assert result["plugin_state"]["('rsi', 'ESM6', '1m')"]["value"] == 65.3
        np.testing.assert_array_equal(
            result["plugin_state"]["('rsi', 'ESM6', '1m')"]["history"],
            np.array([60.0, 63.0, 65.3]),
        )

        # kalman_state
        np.testing.assert_array_equal(
            result["kalman_state"]["ESM6:1m"]["x_est"],
            np.array([0.5, 0.02]),
        )

        # tod_priors (primitives)
        assert result["tod_priors"]["('trend', '1m', 9)"] == 1.05

        # bar_history (deque)
        assert isinstance(result["bar_history"]["ESM6:1m"], deque)
        assert result["bar_history"]["ESM6:1m"].maxlen == 200

        # last_bar_offset (ints)
        assert result["last_bar_offset"]["ESM6:1m"] == 12345
