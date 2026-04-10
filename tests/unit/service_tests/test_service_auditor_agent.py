"""Unit tests for ServiceAuditorAgent — TDD.

Uses __new__ pattern (service test convention) to bypass __init__.
Tests: registry completeness, DAG ordering, systemctl output parsing,
graduated response state machine, DB event schema.
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
    agent._env_name = ""
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
        "indicagent-bar-aggregator-compute", "indicagent-bar-writer",
        "indicagent-bar-auditor", "indicagent-intelligence-pipeline@1",
        "indicagent-signal-tracker", "indicagent-signal-writer",
        "indicagent-ai-narrative", "indicagent-feature-writer",
        "indicagent-llm-writer", "indicagent-cross-asset",
    }
    assert not required - units, f"Missing: {required - units}"


def test_registry_dag_order_sources_before_sinks():
    from services.service_auditor_agent import SERVICE_REGISTRY
    by_unit = {s.unit: s.dag_order for s in SERVICE_REGISTRY}
    assert by_unit["indicagent-ibkr-provider"] < by_unit["indicagent-provider-merger"]
    assert by_unit["indicagent-provider-merger"] < by_unit["indicagent-bar-aggregator-compute"]
    assert by_unit["indicagent-bar-aggregator-compute"] < by_unit["indicagent-intelligence-pipeline@1"]
    assert by_unit["indicagent-intelligence-pipeline@1"] < by_unit["indicagent-feature-writer"]


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


# ── Plan 03: asyncio.gather parallelism + bar-replay registry ─────────────────

def test_registry_includes_bar_replay():
    """SERVICE_REGISTRY must include indicagent-bar-replay at dag_order=3, port=9135."""
    from services.service_auditor_agent import SERVICE_REGISTRY
    units = {s.unit for s in SERVICE_REGISTRY}
    assert "indicagent-bar-replay" in units, "indicagent-bar-replay missing from SERVICE_REGISTRY"
    spec = next(s for s in SERVICE_REGISTRY if s.unit == "indicagent-bar-replay")
    assert spec.metrics_port == 9135
    assert spec.dag_order == 3
    assert spec.lag_threshold_messages == 0


def test_agent_id_to_unit_includes_bar_replay():
    """_AGENT_ID_TO_UNIT must map 'bar_replay_agent' -> 'indicagent-bar-replay'."""
    from services.service_auditor_agent import _AGENT_ID_TO_UNIT
    assert _AGENT_ID_TO_UNIT.get("bar_replay_agent") == "indicagent-bar-replay"


def test_registry_covers_all_active_services_including_bar_replay():
    """Extended required set must include indicagent-bar-replay."""
    from services.service_auditor_agent import SERVICE_REGISTRY
    units = {s.unit for s in SERVICE_REGISTRY}
    required = {
        "indicagent-ibkr-provider", "indicagent-provider-merger",
        "indicagent-bar-aggregator-compute", "indicagent-bar-writer",
        "indicagent-bar-auditor", "indicagent-intelligence-pipeline@1",
        "indicagent-signal-tracker", "indicagent-signal-writer",
        "indicagent-ai-narrative", "indicagent-feature-writer",
        "indicagent-llm-writer", "indicagent-cross-asset",
        "indicagent-bar-replay",  # Plan 03 addition
    }
    assert not required - units, f"Missing: {required - units}"


@pytest.mark.asyncio
async def test_systemd_check_loop_uses_asyncio_gather():
    """_systemd_check_loop must use asyncio.gather for parallel checks, not sequential loop."""
    from services.service_auditor_agent import _SORTED_REGISTRY

    agent = _make_agent()
    # _stop_event is not set, so running=True initially
    agent._systemd_check_interval = 0

    gather_called_with_count: list[int] = []
    original_gather = asyncio.gather

    async def _mock_check_systemd_state(unit: str) -> tuple[str, str]:
        return ("active", "running")

    agent._check_systemd_state = _mock_check_systemd_state
    agent._evaluate_service = AsyncMock()

    async def _patched_gather(*coros, return_exceptions=False):
        gather_called_with_count.append(len(coros))
        # Stop after first iteration
        agent._stop_event.set()
        # Run the real gather so results are correct
        return await original_gather(*coros, return_exceptions=return_exceptions)

    with patch("services.service_auditor_agent.asyncio.gather", side_effect=_patched_gather):
        try:
            await asyncio.wait_for(agent._systemd_check_loop(), timeout=2.0)
        except asyncio.TimeoutError:
            pass

    assert len(gather_called_with_count) >= 1, "asyncio.gather was never called"
    # Should have been called with one coroutine per registry entry
    assert gather_called_with_count[0] == len(_SORTED_REGISTRY), (
        f"Expected gather with {len(_SORTED_REGISTRY)} coroutines, got {gather_called_with_count[0]}"
    )


@pytest.mark.asyncio
async def test_systemd_check_loop_skips_exception_results():
    """Exception results from asyncio.gather must be logged and skipped, not propagated."""
    from services.service_auditor_agent import _SORTED_REGISTRY

    agent = _make_agent()
    # _stop_event not set → running=True initially
    agent._systemd_check_interval = 0
    agent._evaluate_service = AsyncMock()

    # First spec raises, rest return active
    call_count = 0

    async def _mock_check_systemd_state(unit: str) -> tuple[str, str]:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise RuntimeError("systemctl timeout")
        return ("active", "running")

    agent._check_systemd_state = _mock_check_systemd_state

    sleep_count = 0

    async def _mock_sleep(delay):
        nonlocal sleep_count
        sleep_count += 1
        if sleep_count >= 1:
            agent._stop_event.set()

    with patch("services.service_auditor_agent.asyncio.sleep", side_effect=_mock_sleep):
        try:
            await asyncio.wait_for(agent._systemd_check_loop(), timeout=2.0)
        except asyncio.TimeoutError:
            pass

    # _evaluate_service should NOT have been called for the exception result
    # (all remaining are active/running, so no _evaluate_service call at all)
    agent._evaluate_service.assert_not_called()
    # logger.warning should have been called for the exception
    agent.logger.warning.assert_called()


@pytest.mark.asyncio
async def test_systemd_check_loop_calls_evaluate_on_failed():
    """asyncio.gather result with active='failed' must trigger _evaluate_service."""
    from services.service_auditor_agent import ServiceState, _SORTED_REGISTRY

    agent = _make_agent()
    # _stop_event not set → running=True initially
    agent._systemd_check_interval = 0
    agent._evaluate_service = AsyncMock()

    # All specs return "failed"
    async def _mock_check_systemd_state(unit: str) -> tuple[str, str]:
        return ("failed", "start-limit-hit")

    agent._check_systemd_state = _mock_check_systemd_state

    sleep_count = 0

    async def _mock_sleep(delay):
        nonlocal sleep_count
        sleep_count += 1
        if sleep_count >= 1:
            agent._stop_event.set()

    # Provide service_states for all specs
    for spec in _SORTED_REGISTRY:
        agent._service_states[spec.unit] = ServiceState()

    with patch("services.service_auditor_agent.asyncio.sleep", side_effect=_mock_sleep):
        try:
            await asyncio.wait_for(agent._systemd_check_loop(), timeout=2.0)
        except asyncio.TimeoutError:
            pass

    # _evaluate_service must have been called at least once (for failed services)
    assert agent._evaluate_service.call_count >= 1
