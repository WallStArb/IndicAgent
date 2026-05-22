"""Tests for PluginObserver and NoOpPluginObserver (Phase 100.5 Task 4)."""

from __future__ import annotations

from unittest.mock import patch


def test_plugin_observer_importable():
    """PluginObserver is importable from plugin_observer module."""
    from src.observability.plugin_observer import PluginObserver

    assert PluginObserver is not None


def test_noop_plugin_observer_importable():
    """NoOpPluginObserver is importable from plugin_observer module."""
    from src.observability.plugin_observer import NoOpPluginObserver

    assert NoOpPluginObserver is not None


def test_plugin_observer_has_required_methods():
    """PluginObserver has all required methods."""
    from src.observability.plugin_observer import PluginObserver

    observer = PluginObserver()
    assert callable(getattr(observer, "record_result", None))
    assert callable(getattr(observer, "record_error", None))
    assert callable(getattr(observer, "record_circuit_breaker_change", None))
    assert callable(getattr(observer, "record_warmup_skip", None))
    assert callable(getattr(observer, "record_state_error", None))
    assert callable(getattr(observer, "record_i7_signal", None))


def test_noop_plugin_observer_has_required_methods():
    """NoOpPluginObserver has all required methods (same interface)."""
    from src.observability.plugin_observer import NoOpPluginObserver

    observer = NoOpPluginObserver()
    assert callable(getattr(observer, "record_result", None))
    assert callable(getattr(observer, "record_error", None))
    assert callable(getattr(observer, "record_circuit_breaker_change", None))
    assert callable(getattr(observer, "record_warmup_skip", None))
    assert callable(getattr(observer, "record_state_error", None))
    assert callable(getattr(observer, "record_i7_signal", None))


def test_noop_observer_record_result_is_noop():
    """NoOpPluginObserver.record_result does nothing and returns None."""
    from src.observability.plugin_observer import NoOpPluginObserver

    observer = NoOpPluginObserver()
    result = observer.record_result("RSI", "i1", 1.5, used_incremental=True, null_count=0)
    assert result is None


def test_noop_observer_record_error_is_noop():
    """NoOpPluginObserver.record_error does nothing and returns None."""
    from src.observability.plugin_observer import NoOpPluginObserver

    observer = NoOpPluginObserver()
    result = observer.record_error("RSI", "i1", "ValueError: bad input")
    assert result is None


def test_noop_observer_record_circuit_breaker_change_is_noop():
    """NoOpPluginObserver.record_circuit_breaker_change does nothing."""
    from src.observability.plugin_observer import NoOpPluginObserver

    observer = NoOpPluginObserver()
    result = observer.record_circuit_breaker_change("RSI", "open")
    assert result is None


def test_noop_observer_record_warmup_skip_is_noop():
    """NoOpPluginObserver.record_warmup_skip does nothing."""
    from src.observability.plugin_observer import NoOpPluginObserver

    observer = NoOpPluginObserver()
    result = observer.record_warmup_skip("RSI", "i1")
    assert result is None


def test_noop_observer_record_state_error_is_noop():
    """NoOpPluginObserver.record_state_error does nothing."""
    from src.observability.plugin_observer import NoOpPluginObserver

    observer = NoOpPluginObserver()
    result = observer.record_state_error("RSI", "missing _state key")
    assert result is None


def test_noop_observer_record_i7_signal_is_noop():
    """NoOpPluginObserver.record_i7_signal does nothing."""
    from src.observability.plugin_observer import NoOpPluginObserver

    observer = NoOpPluginObserver()
    result = observer.record_i7_signal("TrendPlugin", 0.75)
    assert result is None


def test_plugin_observer_record_result_calls_metrics():
    """PluginObserver.record_result records duration histogram."""
    from src.observability.plugin_observer import PluginObserver

    observer = PluginObserver()
    with (patch.object(observer._duration_hist, "record") as mock_record,):
        observer.record_result("RSI", "i1", 2.0, used_incremental=False, null_count=0)
        mock_record.assert_called_once_with(2.0, {"plugin_name": "RSI", "tier": "i1"})


def test_plugin_observer_record_warmup_skip_increments_counter():
    """PluginObserver.record_warmup_skip increments warmup skip counter."""
    from src.observability.plugin_observer import PluginObserver

    observer = PluginObserver()
    with patch.object(observer._warmup_skip_counter, "add") as mock_add:
        observer.record_warmup_skip("RSI", "i1")
        mock_add.assert_called_once_with(1, {"plugin_name": "RSI", "tier": "i1"})


def test_plugin_observer_record_i7_signal_records_confidence():
    """PluginObserver.record_i7_signal records confidence histogram and signal counter."""
    from src.observability.plugin_observer import PluginObserver

    observer = PluginObserver()
    with (
        patch.object(observer._signal_emit_counter, "add") as mock_add,
        patch.object(observer._confidence_hist, "record") as mock_record,
    ):
        observer.record_i7_signal("TrendPlugin", 0.75)
        mock_add.assert_called_once_with(1, {"plugin_name": "TrendPlugin"})
        mock_record.assert_called_once_with(0.75, {"plugin_name": "TrendPlugin"})
