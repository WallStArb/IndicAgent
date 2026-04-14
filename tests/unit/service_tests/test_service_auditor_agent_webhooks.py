"""Tests for ServiceAuditorAgent webhook dispatch (Plan 067-01 Task 6)."""

from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.fixture
def mock_settings():
    """Create mock settings with webhook credentials."""
    settings = MagicMock()
    settings.telegram_bot_token = "test_token_123"
    settings.telegram_chat_id = "test_chat_456"
    settings.discord_webhook_url = "https://discord.example.com/webhook"
    return settings


@pytest.fixture
def agent(mock_settings):
    """Create ServiceAuditorAgent instance with mocks."""
    from services.service_auditor_agent import ServiceAuditorAgent

    # Use __new__ to bypass __init__
    agent = object.__new__(ServiceAuditorAgent)
    agent._settings = mock_settings
    agent.logger = MagicMock()
    agent._http_session = MagicMock()
    agent._http_session.post = AsyncMock()
    agent.name = "service_auditor_agent"
    return agent


class TestWebhookDispatch:
    """Verify webhook routing logic (Task 6)."""

    @pytest.mark.asyncio
    async def test_dispatch_webhook_critical_routes_to_telegram_only(self, agent):
        """CRITICAL severity sends to Telegram, not Discord."""
        # Mock successful Telegram response
        agent._http_session.post.return_value = MagicMock(status=200)

        await agent._dispatch_webhook("CRITICAL", "Test Title", "Test body")

        # Telegram called once
        assert agent._http_session.post.call_count == 1
        call_args = agent._http_session.post.call_args
        assert "telegram.org" in call_args[0][0]

    @pytest.mark.asyncio
    async def test_dispatch_webhook_high_routes_to_discord_only(self, agent):
        """HIGH severity sends to Discord, not Telegram."""
        agent._http_session.post.return_value = MagicMock(status=204)

        await agent._dispatch_webhook("HIGH", "Test Title", "Test body")

        # Discord called once
        assert agent._http_session.post.call_count == 1
        call_args = agent._http_session.post.call_args
        assert "discord.example.com" in call_args[0][0]

    @pytest.mark.asyncio
    async def test_dispatch_webhook_medium_routes_to_discord_only(self, agent):
        """MEDIUM severity sends to Discord, not Telegram."""
        agent._http_session.post.return_value = MagicMock(status=204)

        await agent._dispatch_webhook("MEDIUM", "Test Title", "Test body")

        assert agent._http_session.post.call_count == 1
        call_args = agent._http_session.post.call_args
        assert "discord.example.com" in call_args[0][0]

    @pytest.mark.asyncio
    async def test_dispatch_webhook_empty_token_is_noop(self, agent, mock_settings):
        """Empty webhook tokens = no-op, no HTTP calls."""
        mock_settings.telegram_bot_token = ""
        mock_settings.discord_webhook_url = ""

        await agent._dispatch_webhook("CRITICAL", "Test", "Body")

        # Zero HTTP calls
        assert agent._http_session.post.call_count == 0

    @pytest.mark.asyncio
    async def test_dispatch_webhook_http_error_is_logged_not_raised(self, agent):
        """HTTP errors are logged, not raised."""
        import aiohttp

        # Mock aiohttp client error
        agent._http_session.post.side_effect = aiohttp.ClientError("Connection failed")

        # Should not raise
        await agent._dispatch_webhook("CRITICAL", "Test", "Body")

        # Error logged
        assert agent.logger.error.called or agent.logger.warning.called
