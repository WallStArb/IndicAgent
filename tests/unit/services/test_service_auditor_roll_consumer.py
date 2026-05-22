"""Tests for ServiceAuditorAgent _restart_roll_service behavior.

NOTE: The original tests in this file tested a broken schema (event_type/new_expiry fields
that don't exist in RollEvent). Those tests have been replaced by
test_service_auditor_roll_schema.py which tests the correct RollEvent schema.
The _restart_roll_service tests are preserved below.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.service_auditor_agent import ServiceAuditorAgent


@pytest.mark.asyncio
async def test_restart_roll_service_increments_counter():
    """Successful restart calls SERVICE_AUDITOR_SERVICE_RESTARTS_TOTAL.add(1, ...)."""
    agent = ServiceAuditorAgent.__new__(ServiceAuditorAgent)
    agent.settings = MagicMock(env_name="")
    agent.logger = MagicMock()

    mock_proc = AsyncMock()
    mock_proc.returncode = 0
    mock_proc.communicate = AsyncMock(return_value=(b"", b""))

    with (
        patch("asyncio.create_subprocess_exec", return_value=mock_proc) as mock_exec,
        patch(
            "services.service_auditor_agent.SERVICE_AUDITOR_SERVICE_RESTARTS_TOTAL"
        ) as mock_counter,
    ):
        await agent._restart_roll_service("indicagent-ibkr-provider")
        assert mock_exec.call_count == 1
        mock_counter.add.assert_called_once_with(1, {"service_name": "indicagent-ibkr-provider"})


@pytest.mark.asyncio
async def test_restart_roll_service_subprocess_failure_is_logged():
    """Subprocess failure does not raise; error is logged and metric not incremented."""
    agent = ServiceAuditorAgent.__new__(ServiceAuditorAgent)
    agent.settings = MagicMock(env_name="")
    agent.logger = MagicMock()

    mock_proc = AsyncMock()
    mock_proc.returncode = 1
    mock_proc.communicate = AsyncMock(return_value=(b"", b"error"))

    with (
        patch("asyncio.create_subprocess_exec", return_value=mock_proc),
        patch(
            "services.service_auditor_agent.SERVICE_AUDITOR_SERVICE_RESTARTS_TOTAL"
        ) as mock_counter,
    ):
        await agent._restart_roll_service("indicagent-ibkr-provider")
        assert agent.logger.error.called
        mock_counter.add.assert_not_called()
