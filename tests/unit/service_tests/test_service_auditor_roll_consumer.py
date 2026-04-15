"""Tests for ServiceAuditorAgent roll event consumer."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.service_auditor_agent import ServiceAuditorAgent


@pytest.mark.asyncio
async def test_handle_roll_event_fires_on_roll_complete_only():
    """Only roll_complete events trigger ibkr-provider restart; others do not."""
    agent = ServiceAuditorAgent.__new__(ServiceAuditorAgent)
    agent.settings = MagicMock(env_name="test")
    agent._handled_rolls = set()
    agent.logger = MagicMock()
    agent._restart_ibkr_provider = AsyncMock()
    agent._dispatch_webhook = AsyncMock()

    # roll_complete should trigger restart
    await agent._handle_roll_event(
        {"event_type": "roll_complete", "symbol": "ES", "new_expiry": "ESM6", "old_expiry": "ESH6"}
    )
    assert agent._restart_ibkr_provider.call_count == 1
    assert agent._dispatch_webhook.call_count == 1

    # roll_imminent should NOT trigger restart
    agent._restart_ibkr_provider.reset_mock()
    agent._dispatch_webhook.reset_mock()
    await agent._handle_roll_event(
        {"event_type": "roll_imminent", "symbol": "ES", "new_expiry": "ESM6", "old_expiry": "ESH6"}
    )
    assert agent._restart_ibkr_provider.call_count == 0
    assert agent._dispatch_webhook.call_count == 0

    # roll_detected should NOT trigger restart
    await agent._handle_roll_event(
        {"event_type": "roll_detected", "symbol": "ES", "new_expiry": "ESM6", "old_expiry": "ESH6"}
    )
    assert agent._restart_ibkr_provider.call_count == 0
    assert agent._dispatch_webhook.call_count == 0


@pytest.mark.asyncio
async def test_handle_roll_event_dedup_prevents_double_restart():
    """Same (symbol, new_expiry) roll only triggers restart once; deduped by in-memory set."""
    agent = ServiceAuditorAgent.__new__(ServiceAuditorAgent)
    agent.settings = MagicMock(env_name="test")
    agent._handled_rolls = set()
    agent.logger = MagicMock()
    agent._restart_ibkr_provider = AsyncMock()
    agent._dispatch_webhook = AsyncMock()

    payload = {
        "event_type": "roll_complete",
        "symbol": "ES",
        "new_expiry": "ESM6",
        "old_expiry": "ESH6",
    }

    # First call should trigger restart
    await agent._handle_roll_event(payload)
    assert agent._restart_ibkr_provider.call_count == 1
    assert ("ES", "ESM6") in agent._handled_rolls

    # Second call with same (symbol, new_expiry) should be deduped
    await agent._handle_roll_event(payload)
    assert agent._restart_ibkr_provider.call_count == 1  # Still 1, not 2


@pytest.mark.asyncio
async def test_restart_ibkr_provider_increments_counter():
    """Successful restart increments SERVICE_AUDITOR_SERVICE_RESTARTS_TOTAL metric."""
    agent = ServiceAuditorAgent.__new__(ServiceAuditorAgent)
    agent.settings = MagicMock(env_name="")
    agent.logger = MagicMock()

    from src.observability.metrics import SERVICE_AUDITOR_SERVICE_RESTARTS_TOTAL

    # Reset counter to 0
    SERVICE_AUDITOR_SERVICE_RESTARTS_TOTAL.labels(service_name="indicagent-ibkr-provider")._value.set(
        0
    )

    mock_proc = AsyncMock()
    mock_proc.returncode = 0
    mock_proc.communicate = AsyncMock(return_value=(b"", b""))

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc) as mock_exec:
        await agent._restart_ibkr_provider()
        assert mock_exec.call_count == 1
        # Verify metric incremented
        metric = SERVICE_AUDITOR_SERVICE_RESTARTS_TOTAL.labels(
            service_name="indicagent-ibkr-provider"
        )
        assert metric._value.get() == 1


@pytest.mark.asyncio
async def test_restart_ibkr_provider_subprocess_failure_is_logged():
    """Subprocess failure does not raise; error is logged and metric not incremented."""

    agent = ServiceAuditorAgent.__new__(ServiceAuditorAgent)
    agent.settings = MagicMock(env_name="")
    agent.logger = MagicMock()

    from src.observability.metrics import SERVICE_AUDITOR_SERVICE_RESTARTS_TOTAL

    # Reset counter to 0
    SERVICE_AUDITOR_SERVICE_RESTARTS_TOTAL.labels(service_name="indicagent-ibkr-provider")._value.set(
        0
    )

    mock_proc = AsyncMock()
    mock_proc.returncode = 1
    mock_proc.communicate = AsyncMock(return_value=(b"", b"error"))

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
        await agent._restart_ibkr_provider()
        # Verify error was logged
        assert agent.logger.error.called
        # Verify metric NOT incremented (failed restart)
        metric = SERVICE_AUDITOR_SERVICE_RESTARTS_TOTAL.labels(
            service_name="indicagent-ibkr-provider"
        )
        assert metric._value.get() == 0
