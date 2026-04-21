"""Test parity_match_rate alert threshold in ParityAuditorAgent."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.parity_auditor_agent import PARITY_ALERT_THRESHOLD, ParityAuditorAgent


@pytest.fixture
def agent():
    with patch("services.parity_auditor_agent.asyncpg"), \
         patch("services.parity_auditor_agent.AIOKafkaProducer"):
        a = ParityAuditorAgent.__new__(ParityAuditorAgent)
        a.name = "ParityAuditorAgent"
        a.settings = MagicMock(
            env_name="test",
            kafka_bootstrap_servers="localhost:9092",
        )
        a.logger = MagicMock()
        a._producer = AsyncMock()
        return a


@pytest.mark.asyncio
async def test_alert_published_when_match_rate_below_threshold(agent):
    """Alert is published to topic_alert_requests when match_rate < 0.95."""
    agent._producer.send_and_wait = AsyncMock()
    await agent._maybe_alert_parity("ES", "1m", match_rate=0.80)
    agent._producer.send_and_wait.assert_awaited_once()
    call_kwargs = agent._producer.send_and_wait.call_args
    assert b"parity_alert" in call_kwargs[1]["key"]


@pytest.mark.asyncio
async def test_no_alert_when_match_rate_above_threshold(agent):
    """No alert when match_rate >= PARITY_ALERT_THRESHOLD."""
    agent._producer.send_and_wait = AsyncMock()
    await agent._maybe_alert_parity("ES", "1m", match_rate=0.97)
    agent._producer.send_and_wait.assert_not_awaited()


@pytest.mark.asyncio
async def test_alert_at_exact_threshold_suppressed(agent):
    """No alert when match_rate == PARITY_ALERT_THRESHOLD (exclusive lower bound)."""
    agent._producer.send_and_wait = AsyncMock()
    await agent._maybe_alert_parity("ES", "1m", match_rate=PARITY_ALERT_THRESHOLD)
    agent._producer.send_and_wait.assert_not_awaited()
