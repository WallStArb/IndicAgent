"""Unit tests for ServiceAuditorAgent -- TDD.

Uses __new__ pattern (service test convention) to bypass __init__.
Tests: DAG ordering, systemctl output parsing,
graduated response state machine, DB event schema, dynamic discovery.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _make_agent():
    from services.service_auditor_agent import ServiceAuditorAgent

    agent = ServiceAuditorAgent.__new__(ServiceAuditorAgent)
    agent.name = "service_auditor_agent"
    agent._stop_event = asyncio.Event()
    agent.logger = MagicMock()
    agent.tracer = MagicMock()
    agent.settings = MagicMock(env_name="")
    agent._db_pool = AsyncMock()
    agent._kafka_producer = AsyncMock()
    agent._service_states = {}
    return agent


# -- DAG order ────────────────────────────────────────────────────────────────


def test_dag_order_covers_required_services():
    from services.service_auditor_agent import _DAG_ORDER

    required = {
        "indicagent-ibkr-provider",
        "indicagent-provider-merger",
        "indicagent-bar-aggregator",
        "indicagent-bar-writer",
        "indicagent-bar-auditor",
        "indicagent-intelligence-pipeline",
        "indicagent-signal-tracker-compute",
        "indicagent-signal-writer",
        "indicagent-ai-narrative",
        "indicagent-feature-writer",
        "indicagent-llm-writer",
        "indicagent-cross-asset",
        "indicagent-lifecycle-writer",
        "indicagent-contract-metadata-writer",
        "indicagent-roll-compute",
        "indicagent-macro-compute",
        "indicagent-alpha-swarm",
        "indicagent-signal-metrics-compute",
        "indicagent-signal-metrics-writer",
        "indicagent-signal-auditor",
        "indicagent-parity-auditor",
        "indicagent-feature-snapshot-writer",
        "indicagent-graduation-writer",
    }
    units = set(_DAG_ORDER.keys())
    assert not required - units, f"Missing from _DAG_ORDER: {required - units}"


def test_dag_order_has_at_least_20_entries():
    from services.service_auditor_agent import _DAG_ORDER

    assert len(_DAG_ORDER) >= 20


def test_dag_order_sources_before_sinks():
    from services.service_auditor_agent import _DAG_ORDER

    assert _DAG_ORDER["indicagent-ibkr-provider"] < _DAG_ORDER["indicagent-provider-merger"]
    assert _DAG_ORDER["indicagent-provider-merger"] < _DAG_ORDER["indicagent-bar-aggregator"]
    assert _DAG_ORDER["indicagent-bar-aggregator"] < _DAG_ORDER["indicagent-intelligence-pipeline"]
    assert _DAG_ORDER["indicagent-intelligence-pipeline"] < _DAG_ORDER["indicagent-feature-writer"]


# -- systemctl parsing ─────────────────────────────────────────────────────────


def test_parse_systemctl_show_active():
    from services.service_auditor_agent import _parse_systemctl_show

    active, sub = _parse_systemctl_show("ActiveState=active\nSubState=running\n")
    assert active == "active" and sub == "running"


def test_parse_systemctl_show_start_limit_hit():
    from services.service_auditor_agent import _parse_systemctl_show

    active, sub = _parse_systemctl_show("ActiveState=failed\nSubState=start-limit-hit\n")
    assert active == "failed" and sub == "start-limit-hit"


def test_parse_systemctl_show_empty():
    from services.service_auditor_agent import _parse_systemctl_show

    assert _parse_systemctl_show("") == ("unknown", "unknown")


# -- Dynamic discovery ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_discover_services_returns_sorted_list():
    """_discover_services() parses systemctl output and sorts by DAG order."""
    agent = _make_agent()

    # Mock systemctl output: bar-writer (dag 4) before ibkr-provider (dag 1)
    mock_stdout = (
        b"indicagent-bar-writer.service loaded active running\n"
        b"indicagent-ibkr-provider.service loaded active running\n"
        b"indicagent-intelligence-pipeline.service loaded active running\n"
    )

    mock_proc = AsyncMock()
    mock_proc.communicate = AsyncMock(return_value=(mock_stdout, b""))

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
        result = await agent._discover_services()

    # Should be sorted by DAG order: ibkr-provider (1) < bar-writer (4) < intelligence (5)
    # Unit names are normalized (stripped of .service suffix) to match _DAG_ORDER keys
    assert result[0] == "indicagent-ibkr-provider"
    assert result[1] == "indicagent-bar-writer"
    assert result[2] == "indicagent-intelligence-pipeline"


@pytest.mark.asyncio
async def test_discover_services_empty_output():
    """_discover_services() handles empty systemctl output gracefully."""
    agent = _make_agent()

    mock_proc = AsyncMock()
    mock_proc.communicate = AsyncMock(return_value=(b"", b""))

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
        result = await agent._discover_services()

    assert result == []


# -- SERVICE_UP_GAUGE ──────────────────────────────────────────────────────────


def test_service_up_gauge_exists():
    """SERVICE_UP_GAUGE is a module-level OTelGauge with unit label."""
    from services.service_auditor_agent import SERVICE_UP_GAUGE
    from src.observability.metrics import OTelGauge

    assert isinstance(SERVICE_UP_GAUGE, OTelGauge)
    # Should accept unit= label
    labeled = SERVICE_UP_GAUGE.labels(unit="indicagent-bar-writer")
    assert hasattr(labeled, "set")


# -- Graduated response ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_healthy_service_no_action():
    from services.service_auditor_agent import ServiceState

    agent = _make_agent()
    agent._service_states["indicagent-bar-writer"] = ServiceState()
    agent._emit_health_event = AsyncMock()
    agent._restart_service_by_unit = AsyncMock()

    await agent._evaluate_service_dynamic(
        "indicagent-bar-writer", "active", "running", 0, 1000, True
    )
    agent._emit_health_event.assert_not_called()
    agent._restart_service_by_unit.assert_not_called()


@pytest.mark.asyncio
async def test_dead_service_triggers_restart():
    from services.service_auditor_agent import ServiceState

    agent = _make_agent()
    agent._service_states["indicagent-bar-writer"] = ServiceState()
    agent._emit_health_event = AsyncMock()
    agent._restart_service_by_unit = AsyncMock()

    await agent._evaluate_service_dynamic(
        "indicagent-bar-writer", "failed", "start-limit-hit", 0, 1000, False
    )
    agent._restart_service_by_unit.assert_called_once_with("indicagent-bar-writer")


@pytest.mark.asyncio
async def test_high_lag_degrades_after_two_checks():
    from services.service_auditor_agent import ServiceState

    agent = _make_agent()
    agent._service_states["indicagent-bar-writer"] = ServiceState()
    agent._emit_health_event = AsyncMock()
    agent._restart_service_by_unit = AsyncMock()

    # First check -- no emit yet, just increments counter
    await agent._evaluate_service_dynamic(
        "indicagent-bar-writer", "active", "running", 2000, 1000, True
    )
    agent._restart_service_by_unit.assert_not_called()
    assert agent._service_states["indicagent-bar-writer"].degraded_check_count == 1

    # Second consecutive check -- emits degraded event
    await agent._evaluate_service_dynamic(
        "indicagent-bar-writer", "active", "running", 2000, 1000, True
    )
    agent._restart_service_by_unit.assert_not_called()
    assert agent._emit_health_event.call_count == 1
    assert agent._emit_health_event.call_args[1]["event_type"] == "degraded"


@pytest.mark.asyncio
async def test_escalates_after_three_restarts_in_window():
    from services.service_auditor_agent import ServiceState

    agent = _make_agent()
    now = datetime.now(UTC)
    state = ServiceState()
    state.restart_times = [
        now - timedelta(minutes=8),
        now - timedelta(minutes=5),
        now - timedelta(minutes=2),
    ]
    agent._service_states["indicagent-bar-writer"] = state
    agent._emit_health_event = AsyncMock()
    agent._restart_service_by_unit = AsyncMock()
    agent._send_to_dlq = AsyncMock()

    await agent._evaluate_service_dynamic(
        "indicagent-bar-writer", "failed", "start-limit-hit", 0, 1000, False
    )

    agent._restart_service_by_unit.assert_not_called()
    event_types = [c[1]["event_type"] for c in agent._emit_health_event.call_args_list]
    assert "escalated" in event_types


@pytest.mark.asyncio
async def test_recovery_emits_recovered_event_with_duration():
    from services.service_auditor_agent import ServiceState

    agent = _make_agent()
    state = ServiceState()
    state.last_known_state = "degraded"
    state.degraded_since = datetime.now(UTC) - timedelta(seconds=120)
    agent._service_states["indicagent-bar-writer"] = state
    agent._emit_health_event = AsyncMock()
    agent._restart_service_by_unit = AsyncMock()

    await agent._evaluate_service_dynamic(
        "indicagent-bar-writer", "active", "running", 0, 1000, True
    )

    agent._emit_health_event.assert_called_once()
    kwargs = agent._emit_health_event.call_args[1]
    assert kwargs["event_type"] == "recovered"
    assert kwargs["duration_degraded_s"] is not None
    assert kwargs["duration_degraded_s"] >= 100


# -- DB persistence ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_emit_health_event_inserts_correct_schema():
    agent = _make_agent()
    mock_conn = AsyncMock()
    agent._db_pool.acquire = MagicMock(
        return_value=AsyncMock(
            __aenter__=AsyncMock(return_value=mock_conn),
            __aexit__=AsyncMock(return_value=False),
        )
    )
    agent._kafka_producer = AsyncMock()

    await agent._emit_health_event(
        service="indicagent-bar-writer",
        event_type="restart",
        previous_state="failed",
        reason="StartLimitHit",
        lag_messages=None,
        restart_count=1,
        duration_degraded_s=None,
    )

    mock_conn.execute.assert_called_once()
    sql_and_args = mock_conn.execute.call_args[0]
    assert "service_health_events" in sql_and_args[0]
    assert "indicagent-bar-writer" in sql_and_args
    assert "restart" in sql_and_args


# -- Data stoppage detection ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_data_stoppage_fires_when_provider_alive_but_no_bars():
    from services.service_auditor_agent import _SVC_DATA_PROVIDER, ServiceState

    agent = _make_agent()
    agent._service_states[_SVC_DATA_PROVIDER] = ServiceState()
    agent._emit_health_event = AsyncMock()
    agent._restart_service_by_unit = AsyncMock()
    agent._send_alert = AsyncMock()
    # Force session open so market-hours gate passes
    agent._any_active_session_open = MagicMock(return_value=True)

    lag_threshold = 0  # ibkr-provider has no lag threshold
    # First check -- counter increments but no restart
    await agent._evaluate_service_dynamic(
        _SVC_DATA_PROVIDER, "active", "running", 0, lag_threshold, True, bars_per_sec=0.0
    )
    agent._restart_service_by_unit.assert_not_called()
    assert agent._service_states[_SVC_DATA_PROVIDER].degraded_check_count == 1

    # Second check -- triggers restart
    await agent._evaluate_service_dynamic(
        _SVC_DATA_PROVIDER, "active", "running", 0, lag_threshold, True, bars_per_sec=0.0
    )
    agent._restart_service_by_unit.assert_called_once_with(_SVC_DATA_PROVIDER)
    event_types = [c[1]["event_type"] for c in agent._emit_health_event.call_args_list]
    assert "data_stoppage" in event_types
