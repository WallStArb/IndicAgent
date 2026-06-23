"""Unit tests for ServiceAuditor -- TDD.

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
    from services.service_auditor import ServiceAuditor

    agent = ServiceAuditor.__new__(ServiceAuditor)
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
    from services.service_auditor import _DAG_ORDER

    required = {
        "indicagent-ibkr-provider",
        "indicagent-provider-merger",
        "indicagent-bar-aggregator",
        "indicagent-bar-writer",
        "indicagent-bar-auditor",
        "indicagent-intelligence-pipeline",
        "indicagent-signal-tracker-compute",
        "indicagent-signal-writer",
        "indicagent-feature-writer",
        "indicagent-llm-writer",
        "indicagent-cross-asset",
        "indicagent-lifecycle-writer",
        "indicagent-macro-compute",
        "indicagent-alpha-swarm",
        "indicagent-signal-metrics-compute",
        "indicagent-signal-metrics-writer",
        "indicagent-signal-auditor",
        # indicagent-parity-auditor and indicagent-feature-snapshot-writer removed:
        # these services do not exist in the live system (not in /etc/systemd/system/).
        "indicagent-graduation-writer",
    }
    units = set(_DAG_ORDER.keys())
    assert not required - units, f"Missing from _DAG_ORDER: {required - units}"


def test_dag_order_has_at_least_20_entries():
    from services.service_auditor import _DAG_ORDER

    assert len(_DAG_ORDER) >= 20


def test_dag_order_sources_before_sinks():
    from services.service_auditor import _DAG_ORDER

    assert _DAG_ORDER["indicagent-ibkr-provider"] < _DAG_ORDER["indicagent-provider-merger"]
    assert _DAG_ORDER["indicagent-provider-merger"] < _DAG_ORDER["indicagent-bar-aggregator"]
    assert _DAG_ORDER["indicagent-bar-aggregator"] < _DAG_ORDER["indicagent-intelligence-pipeline"]
    assert _DAG_ORDER["indicagent-intelligence-pipeline"] < _DAG_ORDER["indicagent-feature-writer"]


# -- systemctl parsing ─────────────────────────────────────────────────────────


def test_parse_systemctl_show_active():
    from services.service_auditor import _parse_systemctl_show

    active, sub = _parse_systemctl_show("ActiveState=active\nSubState=running\n")
    assert active == "active" and sub == "running"


def test_parse_systemctl_show_start_limit_hit():
    from services.service_auditor import _parse_systemctl_show

    active, sub = _parse_systemctl_show("ActiveState=failed\nSubState=start-limit-hit\n")
    assert active == "failed" and sub == "start-limit-hit"


def test_parse_systemctl_show_empty():
    from services.service_auditor import _parse_systemctl_show

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


@pytest.mark.asyncio
async def test_discover_services_strips_bullet_prefix_from_failed_units():
    """_discover_services() handles ● bullet prefix on failed units."""
    agent = _make_agent()

    mock_stdout = (
        b"\xe2\x97\x8f indicagent-bar-writer.service loaded failed failed\n"
        b"indicagent-ibkr-provider.service loaded active running\n"
    )

    mock_proc = AsyncMock()
    mock_proc.communicate = AsyncMock(return_value=(mock_stdout, b""))

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
        result = await agent._discover_services()

    assert "indicagent-bar-writer" in result
    assert "indicagent-ibkr-provider" in result


# -- SERVICE_UP_GAUGE ──────────────────────────────────────────────────────────


def test_service_up_gauge_exists():
    """SERVICE_UP_GAUGE is a module-level OTel up_down_counter with .add() interface."""
    from services.service_auditor import SERVICE_UP_GAUGE

    # OTel up_down_counter has .add() method
    assert hasattr(SERVICE_UP_GAUGE, "add")


# -- Phase 106 regression tests ────────────────────────────────────────────────


def test_all_live_services_in_dag_order():
    """9 services added in 106-02 are present in _DAG_ORDER with expected priorities."""
    from services.service_auditor import _DAG_ORDER

    # Infrastructure sentinels: priority 0
    assert _DAG_ORDER["indicagent-redpanda-ready"] == 0
    assert _DAG_ORDER["indicagent-redpanda-watchdog"] == 0
    # Oneshot/analytics tier: priority 8
    assert _DAG_ORDER["indicagent-weight-updater"] == 8
    assert _DAG_ORDER["indicagent-shadow-auditor"] == 8
    assert _DAG_ORDER["indicagent-ml-orchestrator"] == 8
    assert _DAG_ORDER["indicagent-ml-data-quality"] == 8
    assert _DAG_ORDER["indicagent-ml-discovery"] == 8
    # API / dashboard: priority 10
    assert _DAG_ORDER["indicagent-api"] == 10
    assert _DAG_ORDER["indicagent-dashboard"] == 10


def test_feature_vector_pipeline_priority_is_6():
    """feature-vector-pipeline must be priority 6 (after cross-asset=5, before writers=7)."""
    from services.service_auditor import _DAG_ORDER

    assert _DAG_ORDER["indicagent-feature-vector-pipeline"] == 6
    # cross-asset/macro are 5 (upstream), feature-writer is 7 (downstream)
    assert _DAG_ORDER["indicagent-cross-asset"] == 5
    assert _DAG_ORDER["indicagent-feature-writer"] == 7


@pytest.mark.asyncio
async def test_oneshot_units_not_restarted():
    """Oneshot services in _ONESHOT_UNITS are skipped in graduated-eval restart path."""
    from services.service_auditor import (
        _ONESHOT_UNITS,
        ServiceState,
    )

    agent = _make_agent()
    agent._http_session = MagicMock()
    agent._any_active_session_open = MagicMock(return_value=False)

    restart_mock = AsyncMock()
    agent._restart_service_by_unit = restart_mock
    agent._emit_health_event = AsyncMock()
    agent._send_to_dlq = AsyncMock()
    agent._send_alert = AsyncMock()

    # Pick a unit from _ONESHOT_UNITS
    oneshot_unit = "indicagent-weight-updater"
    assert oneshot_unit in _ONESHOT_UNITS

    agent._service_states[oneshot_unit] = ServiceState()

    # Drive the graduated-eval path with a failed/dead state
    await agent._evaluate_service_dynamic(
        unit=oneshot_unit,
        active_state="inactive",
        sub_state="dead",
        lag_messages=0,
        lag_threshold=0,
        has_metrics=False,
        bars_per_sec=0.0,
    )

    # Restart must NOT have been called for a oneshot unit
    restart_mock.assert_not_awaited()


def test_stall_loop_skips_oneshot_units():
    """Stall-loop restart path skips oneshot units — verified in production code."""
    import inspect

    import services.service_auditor as svc_mod
    from services.service_auditor import _ONESHOT_UNITS

    source = inspect.getsource(svc_mod.ServiceAuditor._prometheus_check_loop)
    assert (
        "if unit in _ONESHOT_UNITS" in source
    ), "_prometheus_check_loop must guard the stall restart path"
    assert (
        "continue" in source
    ), "_prometheus_check_loop must skip (continue) oneshot units in stall loop"

    assert "indicagent-ml-training" in _ONESHOT_UNITS


def test_lag_thresholds_cover_consumers():
    """Lag threshold keys for graduation-compute etc. must be in the migration SQL.

    Phase 109 Plan 05 Task 3: _LAG_THRESHOLDS was removed and replaced with
    config_state rows (alert.lag.*). This test verifies the migration contains
    the expected keys for the consumers that previously had entries.
    """
    migration_path = "production/migrations/109_config_foundation.sql"
    with open(migration_path) as f:
        migration_sql = f.read()

    assert "alert.lag.graduation-compute" in migration_sql
    # graduation-writer and signal-metrics-writer ARE Kafka consumers
    assert "alert.lag.graduation-writer" in migration_sql
    assert "alert.lag.signal-metrics-writer" in migration_sql


def test_agent_id_to_unit_feature_writer_key():
    """_AGENT_ID_TO_UNIT uses the auto-derived key feature_vector_writer (renamed from feature_writer in 138-P0)."""
    from services.service_auditor import _AGENT_ID_TO_UNIT

    assert _AGENT_ID_TO_UNIT["feature_vector_writer"] == "indicagent-feature-writer"
    assert "feature_writer" not in _AGENT_ID_TO_UNIT
    assert "feature_writer_agent" not in _AGENT_ID_TO_UNIT


def test_service_auditor_has_unique_highest_priority():
    """service-auditor must have a strictly higher priority than all monitored services.

    Sharing a priority wave with monitored services means the auditor could be
    restarted mid-cascade alongside the services it is supposed to restart.
    """
    from services.service_auditor import _DAG_ORDER

    auditor_priority = _DAG_ORDER["indicagent-service-auditor"]
    other_priorities = {k: v for k, v in _DAG_ORDER.items() if k != "indicagent-service-auditor"}
    assert all(
        auditor_priority > p for p in other_priorities.values()
    ), f"service-auditor priority {auditor_priority} must exceed all other service priorities"


def test_redpanda_watchdog_in_oneshot_units():
    """indicagent-redpanda-watchdog is Type=oneshot and must be in _ONESHOT_UNITS.

    Without this, the auditor restarts it after every 2-min timer run when it
    transitions to inactive — competing with the systemd timer schedule.
    """
    from services.service_auditor import _ONESHOT_UNITS

    assert "indicagent-redpanda-watchdog" in _ONESHOT_UNITS


# -- Graduated response ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_healthy_service_no_action():
    from services.service_auditor import ServiceState

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
    from services.service_auditor import ServiceState

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
    from services.service_auditor import ServiceState

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
    from services.service_auditor import ServiceState

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
    from services.service_auditor import ServiceState

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
    from services.service_auditor import _SVC_DATA_PROVIDER, ServiceState

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
