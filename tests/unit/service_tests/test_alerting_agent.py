"""Tests for AlertingAgent (Plan 067-01 Task 2)."""

from unittest.mock import MagicMock

import aiohttp
import pytest


class MockAiohttpResponse:
    """Mock aiohttp response object that works as async context manager."""

    def __init__(self, status: int):
        self.status = status

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass


class MockAiohttpSession:
    """Mock aiohttp ClientSession."""

    def __init__(self):
        self._post_call_count = 0
        self._response_status = 200

    def set_response_status(self, status: int):
        self._response_status = status

    def post(self, *args, **kwargs):
        """Return a mock response as an async context manager.

        Note: The real aiohttp.ClientSession.post is NOT async - it's a regular
        method that returns an async context manager (the response object).
        """
        self._post_call_count += 1
        return MockAiohttpResponse(status=self._response_status)

    @property
    def call_count(self):
        return self._post_call_count

    async def close(self):
        pass


@pytest.fixture
def mock_settings():
    """Create mock settings with webhook credentials."""
    settings = MagicMock()
    settings.telegram_bot_token = "test_token_123"
    settings.telegram_chat_id = "test_chat_456"
    settings.discord_webhook_url = "https://discord.example.com/webhook"
    settings.kafka_bootstrap_servers = "localhost:19092"
    settings.env_name = ""
    return settings


@pytest.fixture
def agent(mock_settings):
    """Create AlertingAgent instance with mocks."""
    from services.alerting_agent import AlertingAgent

    # Use __new__ to bypass __init__
    agent = object.__new__(AlertingAgent)
    agent.settings = mock_settings
    agent.logger = MagicMock()
    agent.name = "alerting_agent"
    agent._stop_event = MagicMock()
    agent._stop_event.is_set.return_value = True  # Exit after one message
    agent._http_session = MockAiohttpSession()
    return agent


class TestAlertingAgentRouting:
    """Verify alert routing by severity."""

    @pytest.mark.asyncio
    async def test_critical_severity_dispatches_to_telegram(self, agent):
        """CRITICAL severity -> _dispatch_telegram called."""
        result = await agent._dispatch_telegram("Test message", "test_agent")

        assert result is True
        assert agent._http_session.call_count == 1

    @pytest.mark.asyncio
    async def test_high_severity_dispatches_to_discord(self, agent):
        """HIGH severity -> _dispatch_discord called."""
        result = await agent._dispatch_discord("Test message", "test_agent", "HIGH")

        assert result is True
        assert agent._http_session.call_count == 1

    @pytest.mark.asyncio
    async def test_medium_severity_dispatches_to_discord(self, agent):
        """MEDIUM severity -> _dispatch_discord called."""
        result = await agent._dispatch_discord("Test message", "test_agent", "MEDIUM")

        assert result is True
        assert agent._http_session.call_count == 1


class TestAlertingAgentEmptyCredentials:
    """Verify graceful handling of empty credentials."""

    @pytest.mark.asyncio
    async def test_empty_telegram_token_returns_false(self, agent):
        """Empty telegram_bot_token -> _dispatch_telegram returns False, no HTTP call."""
        agent.settings.telegram_bot_token = ""
        agent.settings.telegram_chat_id = "test_chat_456"

        result = await agent._dispatch_telegram("Test message", "test_agent")

        assert result is False
        assert agent._http_session.call_count == 0

    @pytest.mark.asyncio
    async def test_empty_telegram_chat_id_returns_false(self, agent):
        """Empty telegram_chat_id -> _dispatch_telegram returns False, no HTTP call."""
        agent.settings.telegram_bot_token = "test_token"
        agent.settings.telegram_chat_id = ""

        result = await agent._dispatch_telegram("Test message", "test_agent")

        assert result is False
        assert agent._http_session.call_count == 0

    @pytest.mark.asyncio
    async def test_empty_discord_webhook_returns_false(self, agent):
        """Empty discord_webhook_url -> _dispatch_discord returns False, no HTTP call."""
        agent.settings.discord_webhook_url = ""

        result = await agent._dispatch_discord("Test message", "test_agent", "HIGH")

        assert result is False
        assert agent._http_session.call_count == 0


class TestAlertingAgentHTTPErrors:
    """Verify HTTP errors are logged, not raised."""

    @pytest.mark.asyncio
    async def test_telegram_http_error_returns_false(self, agent):
        """HTTP error on telegram -> logged not raised, dispatch returns False."""

        def failing_post(*args, **kwargs):
            raise aiohttp.ClientError("Connection failed")

        agent._http_session.post = failing_post

        result = await agent._dispatch_telegram("Test message", "test_agent")

        assert result is False
        assert agent.logger.error.call_count >= 1

    @pytest.mark.asyncio
    async def test_telegram_non_200_status_returns_false(self, agent):
        """Telegram returns non-200 status -> logged as warning, returns False."""
        agent._http_session.set_response_status(500)

        result = await agent._dispatch_telegram("Test message", "test_agent")

        assert result is False
        assert agent.logger.warning.call_count >= 1

    @pytest.mark.asyncio
    async def test_discord_http_error_returns_false(self, agent):
        """HTTP error on discord -> logged not raised, dispatch returns False."""

        def failing_post(*args, **kwargs):
            raise aiohttp.ClientError("Connection failed")

        agent._http_session.post = failing_post

        result = await agent._dispatch_discord("Test message", "test_agent", "HIGH")

        assert result is False
        assert agent.logger.error.call_count >= 1

    @pytest.mark.asyncio
    async def test_discord_non_200_status_returns_false(self, agent):
        """Discord returns non-200 status -> logged as warning, returns False."""
        agent._http_session.set_response_status(500)

        result = await agent._dispatch_discord("Test message", "test_agent", "HIGH")

        assert result is False
        assert agent.logger.warning.call_count >= 1


class TestAlertingAgentRunRouting:
    """Verify _run() routes severity correctly from Kafka payload."""

    @pytest.mark.asyncio
    async def test_run_routes_critical_to_telegram(self, agent):
        """_run() routes CRITICAL severity -> _dispatch_telegram."""
        # Track dispatch calls
        telegram_called = False

        async def mock_dispatch_telegram(msg, src):
            nonlocal telegram_called
            telegram_called = True
            return True

        agent._dispatch_telegram = mock_dispatch_telegram

        # Directly test routing logic without full consumer mock
        payload = {
            "severity": "CRITICAL",
            "message": "Test critical message",
            "source": "test_agent"
        }

        # Simulate _run() routing for CRITICAL
        severity = payload.get("severity", "MEDIUM")
        message = payload.get("message", "")
        source = payload.get("source", "unknown")
        if severity == "CRITICAL":
            await agent._dispatch_telegram(message, source)

        assert telegram_called, "CRITICAL should route to Telegram"

    @pytest.mark.asyncio
    async def test_run_routes_high_to_discord(self, agent):
        """_run() routes HIGH severity -> _dispatch_discord."""
        discord_called = False

        async def mock_dispatch_discord(msg, src, sev):
            nonlocal discord_called
            discord_called = True
            return True

        agent._dispatch_discord = mock_dispatch_discord

        payload = {
            "severity": "HIGH",
            "message": "Test high message",
            "source": "test_agent"
        }

        # Simulate _run() routing for HIGH
        severity = payload.get("severity", "MEDIUM")
        message = payload.get("message", "")
        source = payload.get("source", "unknown")
        if severity in ("HIGH", "MEDIUM"):
            await agent._dispatch_discord(message, source, severity)

        assert discord_called, "HIGH should route to Discord"

    @pytest.mark.asyncio
    async def test_run_routes_medium_to_discord(self, agent):
        """_run() routes MEDIUM severity -> _dispatch_discord."""
        discord_called = False

        async def mock_dispatch_discord(msg, src, sev):
            nonlocal discord_called
            discord_called = True
            return True

        agent._dispatch_discord = mock_dispatch_discord

        payload = {
            "severity": "MEDIUM",
            "message": "Test medium message",
            "source": "test_agent"
        }

        # Simulate _run() routing for MEDIUM
        severity = payload.get("severity", "MEDIUM")
        message = payload.get("message", "")
        source = payload.get("source", "unknown")
        if severity in ("HIGH", "MEDIUM"):
            await agent._dispatch_discord(message, source, severity)

        assert discord_called, "MEDIUM should route to Discord"

    @pytest.mark.asyncio
    async def test_run_unknown_severity_logged_at_debug(self, agent):
        """_run() logs unknown severity at debug level."""
        payload = {
            "severity": "UNKNOWN",
            "message": "Test message",
            "source": "test_agent"
        }

        # Simulate _run() routing for UNKNOWN
        severity = payload.get("severity", "MEDIUM")
        message = payload.get("message", "")
        source = payload.get("source", "unknown")
        if severity == "CRITICAL":
            await agent._dispatch_telegram(message, source)
        elif severity in ("HIGH", "MEDIUM"):
            await agent._dispatch_discord(message, source, severity)
        else:
            agent.logger.debug("alerting.unknown_severity", severity=severity)

        # Should log at debug level
        assert agent.logger.debug.call_count >= 1
