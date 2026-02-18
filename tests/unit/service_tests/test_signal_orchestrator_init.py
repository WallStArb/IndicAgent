"""Tests for SignalOrchestratorService initialization."""
from unittest.mock import patch
import pytest


def test_service_loads_default_config():
    from services.signal_orchestrator_service import SignalOrchestratorService

    with patch("services.signal_orchestrator_service.start_metrics_server"):
        svc = SignalOrchestratorService()

    assert "symbols" in svc.config["service"]
    assert "timeframes" in svc.config["service"]
    assert svc.config["service"]["min_history_bars"] == 50


def test_service_loads_custom_config(tmp_path):
    import json
    config_file = tmp_path / "test_config.json"
    config_file.write_text(json.dumps({
        "service": {"symbols": ["ESH6"], "timeframes": ["15m"]}
    }))

    from services.signal_orchestrator_service import SignalOrchestratorService

    with patch("services.signal_orchestrator_service.start_metrics_server"):
        svc = SignalOrchestratorService(str(config_file))

    assert svc.config["service"]["symbols"] == ["ESH6"]
    assert svc.config["service"]["timeframes"] == ["15m"]


def test_service_builds_point_value_map():
    from services.signal_orchestrator_service import SignalOrchestratorService

    with patch("services.signal_orchestrator_service.start_metrics_server"):
        svc = SignalOrchestratorService()

    # Must have point_values for configured symbols
    # Each symbol maps to its contract's point_value (or 1.0 if unknown)
    assert isinstance(svc.point_values, dict)
    for sym in svc.config["service"]["symbols"]:
        assert sym in svc.point_values
        assert isinstance(svc.point_values[sym], float)
