"""Tests for ServiceAuditorAgent alert publishing via _send_alert (Plan 067-02).

Tests invoke the real business logic that triggers _send_alert, not _send_alert directly.
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.service_auditor_agent import (
    ServiceAuditorAgent,
    ServiceSpec,
    ServiceState,
    _SVC_DATA_PROVIDER,
)


@pytest.fixture
def agent():
    """Create ServiceAuditorAgent with mocked dependencies."""
    agent = object.__new__(ServiceAuditorAgent)
    settings = MagicMock()
    settings.telegram_bot_token = ""
    settings.telegram_chat_id = ""
    settings.discord_webhook_url = ""
    settings.env_name = "test"
    settings.database_url = ""
    settings.kafka_bootstrap_servers = "localhost:19092"
    agent.settings = settings
    agent.logger = MagicMock()
    agent._http_session = MagicMock()
    agent._kafka_producer = MagicMock()
    agent._producer = agent._kafka_producer
    agent.name = "service_auditor_agent"
    agent._stop_event = MagicMock()
    agent._stop_event.is_set.return_value = False
    agent._handled_rolls = set()
    agent._service_states = {}
    agent._emit_health_event = AsyncMock()
    agent._restart_service = AsyncMock()
    agent._restart_roll_service = AsyncMock()
    agent._send_to_dlq = AsyncMock()
    return agent


def _make_spec(unit: str = "indicagent-test.service") -> ServiceSpec:
    return ServiceSpec(
        unit=unit,
        metrics_port=9999,
        lag_threshold_messages=1000,
        dag_order=1,
        market_hours_only=False,
    )


class TestSendAlertViaBusinessLogic:
    """Verify _send_alert is called with correct args through real code paths."""

    @pytest.mark.asyncio
    async def test_data_stoppage_calls_send_alert_HIGH(self, agent):
        """Data stoppage (2 checks of bars_per_sec=0 during active session) -> _send_alert HIGH."""
        spec = _make_spec(_SVC_DATA_PROVIDER)
        agent._service_states[spec.unit] = ServiceState()
        agent._send_alert = AsyncMock()

        with patch.object(agent, "_any_active_session_open", return_value=True):
            # First check: degraded_since set, count=1
            await agent._evaluate_service(
                spec, active_state="active", sub_state="running",
                lag_messages=0, has_metrics=True, bars_per_sec=0.0,
            )
            assert agent._send_alert.call_count == 0  # not yet

            # Second check: count >= 2 -> alert
            await agent._evaluate_service(
                spec, active_state="active", sub_state="running",
                lag_messages=0, has_metrics=True, bars_per_sec=0.0,
            )

        assert agent._send_alert.call_count == 1
        call_args = agent._send_alert.call_args
        assert call_args[0][0] == "HIGH"
        assert "Provider data stoppage" in call_args[0][1]

    @pytest.mark.asyncio
    async def test_escalation_calls_send_alert_CRITICAL(self, agent):
        """Service escalated after 3 restarts in 10 min -> _send_alert CRITICAL."""
        spec = _make_spec()
        state = ServiceState()
        now = datetime.now(UTC)
        state.restart_times = [now - timedelta(minutes=i) for i in range(3)]
        agent._service_states[spec.unit] = state
        agent._send_alert = AsyncMock()

        await agent._evaluate_service(
            spec, active_state="failed", sub_state="start-limit-hit",
            lag_messages=0, has_metrics=False,
        )

        assert agent._send_alert.call_count == 1
        call_args = agent._send_alert.call_args
        assert call_args[0][0] == "CRITICAL"
        assert "Service escalated" in call_args[0][1]
        assert call_args[0][2]["restart_count"] == 3

    @pytest.mark.asyncio
    async def test_roll_event_calls_send_alert_HIGH(self, agent):
        """Roll event with new contract -> _send_alert HIGH."""
        agent._send_alert = AsyncMock()

        await agent._handle_roll_event({
            "symbol": "ES",
            "old_contract": "ESM6",
            "new_contract": "ESN6",
            "detection_method": "volume",
        })

        assert agent._send_alert.call_count == 1
        call_args = agent._send_alert.call_args
        assert call_args[0][0] == "HIGH"
        assert "Futures roll" in call_args[0][1]
        assert "ESM6" in call_args[0][1]
        assert "ESN6" in call_args[0][1]
        assert "Restarting" in call_args[0][2]["action"]

    @pytest.mark.asyncio
    async def test_send_alert_noop_when_producer_is_None(self, agent):
        """_send_alert silently no-ops when self._producer is None."""
        agent._producer = None
        agent._kafka_producer.publish = AsyncMock()

        await agent._send_alert("HIGH", "Test", {})

        assert agent._kafka_producer.publish.call_count == 0
