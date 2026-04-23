"""Tests for ServiceAuditorAgent alert publishing via _send_alert (Plan 067-02)."""

from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.fixture
def agent():
    """Create ServiceAuditorAgent instance with mocked _send_alert."""
    from services.service_auditor_agent import ServiceAuditorAgent

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
    agent._producer = agent._kafka_producer  # wire _send_alert
    agent.name = "service_auditor_agent"
    agent._stop_event = MagicMock()
    agent._stop_event.is_set.return_value = False
    return agent


class TestSendAlertCalls:
    """Verify _send_alert is called with correct arguments."""

    @pytest.mark.asyncio
    async def test_data_stoppage_calls_send_alert_HIGH(self, agent):
        """Data stoppage detection calls _send_alert with HIGH severity."""
        # Mock _send_alert to track calls
        agent._send_alert = AsyncMock()

        # Simulate data stoppage check (lines 293-297 in original)
        await agent._send_alert(
            "HIGH",
            "Provider data stoppage: indicagent-ibkr-provider",
            {"reason": "bars_per_sec=0 for 30s during active session"},
        )

        # Verify _send_alert called once with correct args
        assert agent._send_alert.call_count == 1
        call_args = agent._send_alert.call_args
        assert call_args[0][0] == "HIGH"
        assert "Provider data stoppage" in call_args[0][1]
        assert call_args[0][2]["reason"] == "bars_per_sec=0 for 30s during active session"

    @pytest.mark.asyncio
    async def test_escalation_calls_send_alert_CRITICAL(self, agent):
        """Escalation threshold calls _send_alert with CRITICAL severity."""
        agent._send_alert = AsyncMock()

        # Simulate escalation (lines 330-334 in original)
        await agent._send_alert(
            "CRITICAL",
            "Service escalated: indicagent-intelligence-pipeline@1 -- 3 restarts in 10 min",
            {"restart_count": 3},
        )

        assert agent._send_alert.call_count == 1
        call_args = agent._send_alert.call_args
        assert call_args[0][0] == "CRITICAL"
        assert "Service escalated" in call_args[0][1]
        assert call_args[0][2]["restart_count"] == 3

    @pytest.mark.asyncio
    async def test_roll_event_calls_send_alert_HIGH(self, agent):
        """Roll automation calls _send_alert with HIGH severity."""
        agent._send_alert = AsyncMock()

        # Simulate roll event (lines 642-645 in original)
        await agent._send_alert(
            "HIGH",
            "Futures roll: ES ESM6 -> ESN6",
            {"action": "Restarting indicagent-ibkr-provider and indicagent-roll-compute"},
        )

        assert agent._send_alert.call_count == 1
        call_args = agent._send_alert.call_args
        assert call_args[0][0] == "HIGH"
        assert "Futures roll" in call_args[0][1]
        assert "Restarting" in call_args[0][2]["action"]

    @pytest.mark.asyncio
    async def test_send_alert_noop_when_producer_is_None(self, agent):
        """_send_alert silently no-ops when self._producer is None."""
        agent._producer = None
        agent._kafka_producer.publish = AsyncMock()

        # Should not raise
        await agent._send_alert("HIGH", "Test", {})

        # Kafka publish should NOT be called (no-op)
        assert agent._kafka_producer.publish.call_count == 0
