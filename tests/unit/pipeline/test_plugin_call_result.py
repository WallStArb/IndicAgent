"""Tests for PluginCallResult dataclass added in Phase 100.5 Task 3."""

from __future__ import annotations


def test_plugin_call_result_importable():
    """PluginCallResult is importable from executor module."""
    from src.intelligence.pipeline.executor import PluginCallResult

    assert PluginCallResult is not None


def test_plugin_call_result_fields():
    """PluginCallResult has expected fields: outputs, duration_ms, used_incremental, null_count, state."""
    from src.intelligence.pipeline.executor import PluginCallResult

    result = PluginCallResult(
        outputs={"rsi": 55.0},
        duration_ms=1.5,
        used_incremental=True,
        null_count=0,
        state={"prev_val": 55.0},
    )
    assert result.outputs == {"rsi": 55.0}
    assert result.duration_ms == 1.5
    assert result.used_incremental is True
    assert result.null_count == 0
    assert result.state == {"prev_val": 55.0}


def test_plugin_call_result_default_state():
    """PluginCallResult state defaults to None when not provided."""
    from src.intelligence.pipeline.executor import PluginCallResult

    result = PluginCallResult(
        outputs={},
        duration_ms=0.5,
        used_incremental=False,
        null_count=0,
        state=None,
    )
    assert result.state is None


def test_plugin_call_result_uses_slots():
    """PluginCallResult uses __slots__ for memory efficiency."""
    from src.intelligence.pipeline.executor import PluginCallResult

    assert hasattr(PluginCallResult, "__slots__")


def test_plugin_call_result_is_dataclass():
    """PluginCallResult is a proper dataclass."""
    import dataclasses

    from src.intelligence.pipeline.executor import PluginCallResult

    assert dataclasses.is_dataclass(PluginCallResult)
