"""Unit tests for ServiceAuditorAgent — TDD.

Uses __new__ pattern (service test convention) to bypass __init__.
Tests: registry completeness, DAG ordering, systemctl output parsing,
graduated response state machine, DB event schema.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

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


# ── Registry ──────────────────────────────────────────────────────────────────

def test_registry_covers_all_active_services():
    from services.service_auditor_agent import SERVICE_REGISTRY
    units = {s.unit for s in SERVICE_REGISTRY}
    required = {
        "indicagent-ibkr-provider", "indicagent-provider-merger",
        "indicagent-bar-aggregator", "indicagent-bar-writer",
        "indicagent-bar-auditor", "indicagent-intelligence-pipeline",
        "indicagent-signal-tracker-compute", "indicagent-signal-writer",
        "indicagent-ai-narrative", "indicagent-feature-writer",
        "indicagent-llm-writer", "indicagent-cross-asset",
        "indicagent-lifecycle-writer", "indicagent-contract-metadata-writer",
        "indicagent-roll-compute", "indicagent-macro-compute",
        "indicagent-swarm-orchestrator", "indicagent-swarm-writer",
        "indicagent-signal-metrics-compute", "indicagent-signal-metrics-writer",
        "indicagent-signal-auditor", "indicagent-parity-auditor",
        "indicagent-feature-snapshot-writer", "indicagent-graduation-writer",
    }
    assert not required - units, f"Missing: {required - units}"


def test_registry_dag_order_sources_before_sinks():
    from services.service_auditor_agent import SERVICE_REGISTRY
    by_unit = {s.unit: s.dag_order for s in SERVICE_REGISTRY}
    assert by_unit["indicagent-ibkr-provider"] < by_unit["indicagent-provider-merger"]
    assert by_unit["indicagent-provider-merger"] < by_unit["indicagent-bar-aggregator"]
    assert by_unit["indicagent-bar-aggregator"] < by_unit["indicagent-intelligence-pipeline"]
    assert by_unit["indicagent-intelligence-pipeline"] < by_unit["indicagent-feature-writer"]


# ── systemctl parsing ─────────────────────────────────────────────────────────

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


# ── Graduated response ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_healthy_service_no_action():
    from services.service_auditor_agent import ServiceSpec, ServiceState
    agent = _make_agent()
    spec = ServiceSpec("indicagent-bar-writer", 9121, 1000, 4, True)
    agent._service_states["indicagent-bar-writer"] = ServiceState()

    with MagicMock() as _:
        agent._emit_health_event = AsyncMock()
        agent._restart_service = AsyncMock()
        await agent._evaluate_service(spec, "active", "running", 0, True)
        agent._emit_health_event.assert_not_called()
        agent._restart_service.assert_not_called()


@pytest.mark.asyncio
async def test_dead_service_triggers_restart():
    from services.service_auditor_agent import ServiceSpec, ServiceState
    agent = _make_agent()
    spec = ServiceSpec("indicagent-bar-writer", 9121, 1000, 4, True)
    agent._service_states["indicagent-bar-writer"] = ServiceState()
    agent._emit_health_event = AsyncMock()
    agent._restart_service = AsyncMock()

    await agent._evaluate_service(spec, "failed", "start-limit-hit", 0, False)
    agent._restart_service.assert_called_once_with(spec)


@pytest.mark.asyncio
async def test_high_lag_degrades_after_two_checks():
    from services.service_auditor_agent import ServiceSpec, ServiceState
    agent = _make_agent()
    spec = ServiceSpec("indicagent-bar-writer", 9121, 1000, 4, True)
    agent._service_states["indicagent-bar-writer"] = ServiceState()
    agent._emit_health_event = AsyncMock()
    agent._restart_service = AsyncMock()

    # First check — no emit yet, just increments counter
    await agent._evaluate_service(spec, "active", "running", 2000, True)
    agent._restart_service.assert_not_called()
    assert agent._service_states["indicagent-bar-writer"].degraded_check_count == 1

    # Second consecutive check — emits degraded event
    await agent._evaluate_service(spec, "active", "running", 2000, True)
    agent._restart_service.assert_not_called()
    assert agent._emit_health_event.call_count == 1
    assert agent._emit_health_event.call_args[1]["event_type"] == "degraded"


@pytest.mark.asyncio
async def test_escalates_after_three_restarts_in_window():
    from services.service_auditor_agent import ServiceSpec, ServiceState
    agent = _make_agent()
    spec = ServiceSpec("indicagent-bar-writer", 9121, 1000, 4, True)
    now = datetime.now(UTC)
    state = ServiceState()
    state.restart_times = [
        now - timedelta(minutes=8),
        now - timedelta(minutes=5),
        now - timedelta(minutes=2),
    ]
    agent._service_states["indicagent-bar-writer"] = state
    agent._emit_health_event = AsyncMock()
    agent._restart_service = AsyncMock()
    agent._send_to_dlq = AsyncMock()

    await agent._evaluate_service(spec, "failed", "start-limit-hit", 0, False)

    agent._restart_service.assert_not_called()
    event_types = [c[1]["event_type"] for c in agent._emit_health_event.call_args_list]
    assert "escalated" in event_types


@pytest.mark.asyncio
async def test_recovery_emits_recovered_event_with_duration():
    from services.service_auditor_agent import ServiceSpec, ServiceState
    agent = _make_agent()
    spec = ServiceSpec("indicagent-bar-writer", 9121, 1000, 4, True)
    state = ServiceState()
    state.last_known_state = "degraded"
    state.degraded_since = datetime.now(UTC) - timedelta(seconds=120)
    agent._service_states["indicagent-bar-writer"] = state
    agent._emit_health_event = AsyncMock()
    agent._restart_service = AsyncMock()

    await agent._evaluate_service(spec, "active", "running", 0, True)

    agent._emit_health_event.assert_called_once()
    kwargs = agent._emit_health_event.call_args[1]
    assert kwargs["event_type"] == "recovered"
    assert kwargs["duration_degraded_s"] is not None
    assert kwargs["duration_degraded_s"] >= 100


# ── DB persistence ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_emit_health_event_inserts_correct_schema():
    agent = _make_agent()
    mock_conn = AsyncMock()
    agent._db_pool.acquire = MagicMock(return_value=AsyncMock(
        __aenter__=AsyncMock(return_value=mock_conn),
        __aexit__=AsyncMock(return_value=False),
    ))
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


# ── Prometheus health check ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_fetch_prometheus_health_maps_jobs_to_units():
    agent = _make_agent()
    agent._http_session = AsyncMock()
    mock_resp = AsyncMock()
    mock_resp.status = 200
    mock_resp.json = AsyncMock(return_value={
        "data": {
            "result": [
                {"metric": {"job": "indicagent-ibkr-provider"}, "value": [0, "1"]},
                {"metric": {"job": "indicagent-intelligence-pipeline"}, "value": [0, "1"]},
                {"metric": {"job": "indicagent-bar-aggregator-compute"}, "value": [0, "1"]},
                {"metric": {"job": "indicagent-ai-narrative"}, "value": [0, "0"]},  # down
            ]
        }
    })
    mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_resp.__aexit__ = AsyncMock(return_value=False)
    agent._http_session.get = MagicMock(return_value=mock_resp)

    result = await agent._fetch_prometheus_health()

    assert "indicagent-ibkr-provider" in result
    assert "indicagent-intelligence-pipeline" in result
    assert "indicagent-bar-aggregator" in result  # job name translated
    assert "indicagent-ai-narrative" not in result  # value was 0 (down)


# ── Data stoppage detection ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_data_stoppage_fires_when_provider_alive_but_no_bars():
    from services.service_auditor_agent import ServiceSpec, ServiceState, _SVC_DATA_PROVIDER
    agent = _make_agent()
    spec = ServiceSpec(_SVC_DATA_PROVIDER, 9129, 0, 1, False)
    agent._service_states[_SVC_DATA_PROVIDER] = ServiceState()
    agent._emit_health_event = AsyncMock()
    agent._restart_service = AsyncMock()
    agent._send_alert = AsyncMock()
    # Force session open so market-hours gate passes
    agent._any_active_session_open = MagicMock(return_value=True)

    # First check — counter increments but no restart
    await agent._evaluate_service(spec, "active", "running", 0, True, bars_per_sec=0.0)
    agent._restart_service.assert_not_called()
    assert agent._service_states[_SVC_DATA_PROVIDER].degraded_check_count == 1

    # Second check — triggers restart
    await agent._evaluate_service(spec, "active", "running", 0, True, bars_per_sec=0.0)
    agent._restart_service.assert_called_once_with(spec)
    event_types = [c[1]["event_type"] for c in agent._emit_health_event.call_args_list]
    assert "data_stoppage" in event_types
