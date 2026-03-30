"""State checkpoint serializer for IntelligencePipelineComputeAgent.

Converts full agent state dicts (containing numpy arrays, Pydantic models,
deques, and primitives) to/from msgpack bytes via explicit type tagging.

Type tag encoding:
    numpy.ndarray -> {"__ndarray__": true, "data": [...], "dtype": str}
    Pydantic      -> {"__pydantic__": "ClassName", "data": {...}}
    deque         -> {"__deque__": true, "data": [...], "maxlen": int|null}
    primitives    -> pass-through (int, float, str, bool, None)
    dict/list     -> recurse on values/items

Note: dict keys are stringified (str(k)) during encoding. Tuple keys like
(plugin_name, symbol, tf) are restored via ast.literal_eval in the consumer.
"""

from __future__ import annotations

from collections import deque
from typing import Any

import msgpack
import numpy as np
from pydantic import BaseModel

# Registry of Pydantic model classes by name — populated lazily on first decode().
# Any Pydantic model stored in plugin state MUST be registered here.
PYDANTIC_REGISTRY: dict[str, type[BaseModel]] = {}

_PRIMITIVES = (int, float, str, bool, type(None))
_default_models_registered = False


def register_pydantic_model(cls: type[BaseModel]) -> None:
    """Register a Pydantic model class for state deserialization."""
    PYDANTIC_REGISTRY[cls.__name__] = cls


class StateDeserializationError(Exception):
    """Raised when a Pydantic class name in checkpoint data is not in PYDANTIC_REGISTRY."""


class StateSerializer:
    """Encode/decode agent state dicts to/from msgpack bytes with type tagging."""

    @staticmethod
    def encode(state: dict) -> bytes:
        """Walk state dict, apply type tags, return msgpack bytes."""
        try:
            tagged = _tag_value(state)
            return msgpack.packb(tagged, use_bin_type=True)
        except Exception as exc:
            raise TypeError(f"State contains non-serializable data: {exc}") from exc

    @staticmethod
    def decode(payload: bytes) -> dict:
        """Deserialize msgpack bytes, reconstruct tagged types."""
        _ensure_default_models_registered()
        raw = msgpack.unpackb(payload, raw=False)
        return _untag_value(raw)


def _tag_value(obj: Any) -> Any:
    """Recursively tag special types for msgpack serialization."""
    # Fast-path for common primitives — avoids 4 expensive isinstance checks
    if isinstance(obj, _PRIMITIVES):
        return obj
    if isinstance(obj, np.ndarray):
        return {"__ndarray__": True, "data": obj.tolist(), "dtype": str(obj.dtype)}
    if isinstance(obj, BaseModel):
        return {"__pydantic__": type(obj).__name__, "data": obj.model_dump()}
    if isinstance(obj, deque):
        return {"__deque__": True, "data": [_tag_value(item) for item in obj], "maxlen": obj.maxlen}
    if isinstance(obj, dict):
        return {str(k): _tag_value(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_tag_value(item) for item in obj]
    return obj


def _untag_value(obj: Any) -> Any:
    """Recursively reconstruct tagged types from msgpack deserialization."""
    if isinstance(obj, dict):
        if obj.get("__ndarray__") is True:
            return np.array(obj["data"], dtype=obj["dtype"])
        if "__pydantic__" in obj and "data" in obj and len(obj) == 2:
            cls_name = obj["__pydantic__"]
            cls = PYDANTIC_REGISTRY.get(cls_name)
            if cls is None:
                raise StateDeserializationError(
                    f"Unknown Pydantic class: {cls_name}. "
                    f"Registered: {list(PYDANTIC_REGISTRY.keys())}"
                )
            return cls(**_untag_value(obj["data"]))
        if obj.get("__deque__") is True:
            return deque(
                [_untag_value(item) for item in obj["data"]],
                maxlen=obj.get("maxlen"),
            )
        return {k: _untag_value(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_untag_value(item) for item in obj]
    return obj


# ---------------------------------------------------------------------------
# Auto-register intelligence schema models used in plugin state.
# Lazy: called on first decode() to avoid eager import at module load time.
# ---------------------------------------------------------------------------


def _ensure_default_models_registered() -> None:
    global _default_models_registered
    if _default_models_registered:
        return
    _default_models_registered = True
    try:
        from src.intelligence.schemas import (
            I1Indicators,
            I2Events,
            I3Structure,
            I4Context,
            I5Patterns,
            I6Confluence,
            SMCContext,
        )

        for cls in [
            I1Indicators,
            I2Events,
            I3Structure,
            I4Context,
            I5Patterns,
            I6Confluence,
            SMCContext,
        ]:
            register_pydantic_model(cls)
    except ImportError:
        pass  # schemas not available in all test contexts
